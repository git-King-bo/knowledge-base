export interface ServerEvent { event: string; data: string }

/** SSE framing is independent of network chunks, UTF-8 characters, and CR/LF boundaries. */
export async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: ServerEvent) => boolean | void,
  signal?: AbortSignal,
) {
  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8', { fatal: true })
  let buffer = ''
  let name = 'message'
  let fields: string[] = []
  let size = 0
  let stopped = false
  const abort = () => { void reader.cancel().catch(() => {}) }
  signal?.addEventListener('abort', abort, { once: true })
  function line(value: string) {
    if (value === '') {
      if (fields.length) stopped = onEvent({ event: name, data: fields.join('\n') }) === false
      name = 'message'; fields = []; size = 0
    } else if (!value.startsWith(':')) {
      const colon = value.indexOf(':')
      const key = colon === -1 ? value : value.slice(0, colon)
      const content = colon === -1 ? '' : value.slice(colon + 1).replace(/^ /, '')
      if (key === 'event') name = content
      if (key === 'data') { fields.push(content); size += content.length }
      if (size > 1_000_000) throw new Error('流式事件过大')
    }
  }
  function drain(final = false) {
    let consumed = 0
    for (let index = 0; index < buffer.length && !stopped; index++) {
      const char = buffer[index]
      if (char !== '\r' && char !== '\n') continue
      if (char === '\r' && index === buffer.length - 1 && !final) break
      line(buffer.slice(consumed, index))
      if (char === '\r' && buffer[index + 1] === '\n') index++
      consumed = index + 1
    }
    buffer = buffer.slice(consumed)
    if (buffer.length > 1_000_000) throw new Error('流式事件过大')
  }
  try {
    signal?.throwIfAborted()
    while (!stopped) {
      const { done, value } = await reader.read()
      signal?.throwIfAborted()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      drain(done)
      if (done) break
    }
    // An unterminated event at EOF is intentionally not dispatched.
  } finally {
    signal?.removeEventListener('abort', abort)
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
