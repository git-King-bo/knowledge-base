import test from 'node:test'
import assert from 'node:assert/strict'
import { readEventStream } from '../src/lib/sse'
import { createFrameBuffer } from '../src/lib/frameBuffer'

const { renderMarkdown, safeExternalUrl } = await import('../src/lib/renderMarkdown')
const { streamKnowledge, setApiHeaders } = await import('../src/lib/api')

function byteStream(text: string, width = 1) {
  const bytes = new TextEncoder().encode(text)
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < bytes.length; i += width) controller.enqueue(bytes.slice(i, i + width))
      controller.close()
    },
  })
}
function fragment(html: string) {
  const template = document.createElement('template')
  template.innerHTML = html
  return template.content
}
function assertSafe(html: string) {
  const content = fragment(html)
  assert.equal(content.querySelector('script,style,iframe,object,embed,svg,math,form,img'), null)
  for (const element of content.querySelectorAll('*')) {
    for (const attribute of element.attributes) assert.ok(!/^on/i.test(attribute.name))
    const href = element.getAttribute('href')
    if (href) assert.match(href, /^https?:\/\//)
    assert.equal(element.hasAttribute('style'), false)
  }
}

test('SSE handles split UTF-8, CRLF, comments, and multiline data', async () => {
  const events: unknown[] = []
  await readEventStream(byteStream(': ping\r\nevent: delta\r\ndata: {"text":\r\ndata: "中文🙂"}\r\n\r\nevent: done\ndata: {}\n\n'), event => { events.push([event.event, JSON.parse(event.data)]) })
  assert.deepEqual(events, [['delta', { text: '中文🙂' }], ['done', {}]])
})

test('SSE does not dispatch an incomplete final event and cancels pending reads', async () => {
  const events: unknown[] = []
  await readEventStream(byteStream('event: delta\ndata: {"text":"partial"}'), event => { events.push(event) })
  assert.deepEqual(events, [])
  let cancelled = false
  const controller = new AbortController()
  const reading = readEventStream(new ReadableStream({ cancel() { cancelled = true } }), () => {}, controller.signal)
  controller.abort()
  await assert.rejects(reading, { name: 'AbortError' })
  assert.equal(cancelled, true)
})

test('fetch streaming merges global and per-request headers and validates completion', async () => {
  const previous = globalThis.fetch
  let meta: unknown
  let text = ''
  const payload = 'event: meta\ndata: {"provider_id":"provider","model":"test","sources":[],"web_sources":[]}\n\n'
    + 'event: delta\ndata: {"text":"你好"}\n\nevent: done\ndata: {}\n\n'
  setApiHeaders(() => ({ Authorization: 'Bearer app-session', 'X-Tenant': 'workspace' }))
  globalThis.fetch = async (_url, init) => {
    const headers = new Headers(init?.headers)
    assert.equal(headers.get('Authorization'), 'Bearer request-session')
    assert.equal(headers.get('X-Tenant'), 'workspace')
    assert.equal(headers.get('X-Trace'), 'trace-123')
    assert.equal(headers.get('Accept'), 'text/event-stream')
    assert.equal(init?.method, 'POST')
    assert.equal(JSON.parse(init?.body as string).question, '你好')
    assert.deepEqual(JSON.parse(init?.body as string).continuation, { answer: '已有内容', sources: [], web_sources: [] })
    return new Response(byteStream(payload), { headers: { 'Content-Type': 'text/event-stream' } })
  }
  try {
    await streamKnowledge({ question: '你好', continuation: { answer: '已有内容', sources: [], webSources: [] } }, {
      headers: new Headers({ authorization: 'Bearer request-session', 'X-Trace': 'trace-123' }),
      onMeta(value) { meta = value }, onDelta(value) { text += value },
    })
    assert.equal(text, '你好')
    assert.deepEqual(meta, { providerId: 'provider', model: 'test', sources: [], webSources: [] })
    globalThis.fetch = async () => new Response(byteStream(payload.replace('event: done\ndata: {}\n\n', '')), { headers: { 'Content-Type': 'text/event-stream' } })
    await assert.rejects(streamKnowledge({ question: '你好' }, { onMeta() {}, onDelta() {} }), /提前断开/)
  } finally { globalThis.fetch = previous; setApiHeaders({}) }
})

test('many deltas render once per frame, including the terminal flush', async () => {
  const callbacks = new Map<number, FrameRequestCallback>()
  let id = 0
  const previousFrame = globalThis.requestAnimationFrame
  const previousCancel = globalThis.cancelAnimationFrame
  globalThis.requestAnimationFrame = callback => { callbacks.set(++id, callback); return id }
  globalThis.cancelAnimationFrame = key => { callbacks.delete(key) }
  function flush() {
    const current = [...callbacks.values()]
    callbacks.clear()
    current.forEach(callback => callback(16))
  }
  try {
    const renders: unknown[] = []
    const buffer = createFrameBuffer((text, final) => renders.push([text, final]))
    for (const text of ['中', '文', ' ', '**', '重点']) buffer.append(text)
    assert.equal(callbacks.size, 1)
    assert.equal(renders.length, 0)
    flush()
    assert.deepEqual(renders, [['中文 **重点', false]])
    buffer.append('**')
    const finished = buffer.finish()
    assert.equal(callbacks.size, 1)
    flush()
    await finished
    assert.deepEqual(renders.at(-1), ['中文 **重点**', true])
    buffer.dispose()
    buffer.append('not rendered')
    assert.equal(callbacks.size, 0)
    const abandoned = createFrameBuffer(() => assert.fail('rendered after unmount'))
    abandoned.append('partial')
    const pending = abandoned.finish()
    abandoned.dispose()
    await pending
    assert.equal(callbacks.size, 0)
  } finally {
    globalThis.requestAnimationFrame = previousFrame
    globalThis.cancelAnimationFrame = previousCancel
  }
})

test('streaming Markdown keeps HTML closed and completes code/emphasis/link syntax', () => {
  const partial = renderMarkdown('```js\nconst text = "<script>";\n(Chunk 8)', { streaming: true, sourceRefs: true })
  assert.match(partial, /<pre><code[^>]*>/)
  assert.match(partial, /<\/code><\/pre>/)
  assert.equal(fragment(partial).querySelector('button'), null)
  const final = renderMarkdown('```js\nconst x = 1\n```\n\n**重点**（Chunk 8）\n\n[参考](https://example.com)', { sourceRefs: true })
  const content = fragment(final)
  assert.equal(content.querySelector('strong')?.textContent, '重点')
  assert.equal(content.querySelector('button')?.getAttribute('data-chunk-ref'), '8')
  assert.equal(content.querySelector('a')?.getAttribute('rel'), 'noopener noreferrer')
  assert.ok(content.querySelector('code .hljs-keyword'))
})

test('citations retain style and remain literal inside code', () => {
  const output = renderMarkdown('正文（Chunk 49, Web 1）。`（Chunk 7）`\n\n```text\n（Chunk 8）\n```', { sourceRefs: true })
  const content = fragment(output)
  assert.equal(content.querySelectorAll('.source-inline-ref').length, 2)
  assert.equal(content.querySelector('[data-web-ref="1"]')?.textContent, 'W1')
  assert.equal(content.querySelector('[data-chunk-ref="7"]'), null)
  assert.equal(content.querySelector('[data-chunk-ref="8"]'), null)
})

test('personnel evidence references keep their own identifiers and do not alter code', () => {
  const content = fragment(renderMarkdown('人员甲（Record 1），人员乙 Record 2。`Record 3`', { sourceRefs: true }))
  assert.equal(content.querySelector('[data-record-ref="1"]')?.textContent, '证据 1')
  assert.equal(content.querySelector('[data-record-ref="2"]')?.getAttribute('aria-label'), '查看人才证据 2')
  assert.equal(content.querySelector('[data-chunk-ref]'), null)
  assert.equal(content.querySelector('[data-record-ref="3"]'), null)
})

test('bare citations become readable source labels without changing code or link targets', () => {
  const source = '- Chunk 243 明确提到算法。\n- **Chunk 290** 指出创新能力。\n\n'
    + '共同证据：Chunk 243、Chunk 299（Chunk 215）。\n\n'
    + '`Chunk 8` [参考](https://example.com/Chunk%20243)';
  for (const streaming of [false, true]) {
    const content = fragment(renderMarkdown(source, { sourceRefs: true, streaming }))
    assert.equal(content.querySelector('[data-chunk-ref="243"]')?.textContent, '来源 243')
    assert.equal(content.querySelector('strong [data-chunk-ref="290"]')?.textContent, '来源 290')
    assert.equal(content.querySelectorAll('.source-inline-ref').length, 5)
    assert.equal(content.querySelectorAll('.source-inline-refs--label').length, 4)
    assert.equal(content.querySelector('[data-chunk-ref="215"]')?.textContent, '215')
    assert.equal(content.querySelector('[data-chunk-ref="8"]'), null)
    assert.equal(content.querySelector('a')?.getAttribute('href'), 'https://example.com/Chunk%20243')
  }
})

test('every streamed prefix is sanitized against HTML, URL and forged-reference attacks', () => {
  const attacks = [
    '<script>alert(1)</script>', '<img src=x onerror=alert(1)>',
    '<svg><a onload=alert(1)>x</a></svg>',
    '[点击](javascript:alert%281%29)', '[点击](data:text/html,alert)',
    '<a href="javascript:alert(1)" onclick="alert(1)">x</a>',
    '<button data-chunk-ref="9" class="source-inline-ref" onclick="alert(1)">fake</button>',
    '<form id="attributes"><input name="__proto__"></form>',
    '![image](https://example.com/tracker.png)',
  ]
  for (const attack of attacks) {
    for (let end = 1; end <= attack.length; end++) {
      const html = renderMarkdown(attack.slice(0, end), { streaming: true, sourceRefs: true })
      assertSafe(html)
      assert.equal(fragment(html).querySelector('button'), null)
    }
    assertSafe(renderMarkdown(attack, { sourceRefs: true }))
  }
  assert.equal(safeExternalUrl('javascript:alert(1)'), undefined)
  assert.equal(safeExternalUrl('data:text/html,boom'), undefined)
})
