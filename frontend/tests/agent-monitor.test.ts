import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, nextTick } from 'vue'
import AgentMonitor from '../src/views/AgentMonitor.vue'
import { streamKnowledge } from '../src/lib/api'
const settle = async () => { for (let i = 0; i < 6; i++) { await new Promise(r => setTimeout(r, 0)); await nextTick() } }

test('monitor filters by history and distinguishes unreported usage from zero', async () => {
  const previous = globalThis.fetch
  const previousScroll = HTMLElement.prototype.scrollIntoView
  HTMLElement.prototype.scrollIntoView = () => {}
  const urls: URL[] = []
  const row = { id: 'trace-a', question: '测试请求', status: 'success', created_at: '2026-09-29T00:00:00Z',
    duration_ms: 800, first_token_ms: 100, conversation_id: 'history-a', turn_id: 'turn-a', call_count: 1,
    unknown_calls: 1, input_tokens: null, output_tokens: null, cached_tokens: null, total_tokens: 0 }
  globalThis.fetch = async input => {
    const url = new URL(String(input), 'http://localhost'); urls.push(url)
    if (url.pathname.endsWith('/conversations')) return Response.json([{ id: 'history-a', title: '测试历史', has_traces: true }])
    if (url.pathname.endsWith('/trace-a')) return Response.json({ ...row, answer: '最终回答', error: '', request: {}, stages: [], calls: [] })
    return Response.json({ items: [row], total: 1, page_size: 20, summary: { total_tokens: 0, call_count: 1, unknown_calls: 1 } })
  }
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp(AgentMonitor)
  try {
    app.mount(host); await settle()
    assert.match(host.textContent || '', /1 次调用未上报 Token/)
    assert.match(host.textContent || '', /最终回答/)
    const trigger = host.querySelector<HTMLButtonElement>('[role="combobox"]')!
    trigger.click(); await settle()
    const options = host.querySelectorAll<HTMLElement>('[role="option"]')
    options[1]!.click(); await settle()
    assert.ok(urls.some(url => url.searchParams.get('conversation_id') === 'history-a'))
  } finally { app.unmount(); host.remove(); globalThis.fetch = previous; HTMLElement.prototype.scrollIntoView = previousScroll }
})

test('stream requests carry stable history and turn identifiers alongside continuation', async () => {
  const previous = globalThis.fetch
  let body: Record<string, unknown> = {}
  globalThis.fetch = async (_input, init) => {
    body = JSON.parse(String(init?.body))
    return new Response('event: meta\ndata: {"provider_id":"p","model":"m","sources":[],"web_sources":[]}\n\nevent: delta\ndata: {"text":"回答"}\n\nevent: done\ndata: {}\n\n', { headers: { 'Content-Type': 'text/event-stream' } })
  }
  try {
    await streamKnowledge({ question: '追问', conversationId: 'history-a', turnId: 'turn-a',
      continuation: { answer: '先前输出', sources: [], webSources: [] } }, { onMeta() {}, onDelta() {} })
    assert.equal(body.conversation_id, 'history-a')
    assert.equal(body.turn_id, 'turn-a')
    assert.equal((body.continuation as {answer: string}).answer, '先前输出')
  } finally { globalThis.fetch = previous }
})

test('timeline keeps calls next to their stage once and parses role messages', async () => {
  const { buildAgentTimeline, modelMessages } = await import('../src/lib/agentTimeline')
  const call = { id: 'call-1', stage: '查询改写', model: 'm', provider_id: 'p', action: 'ask', success: true,
    latency_ms: 10, total_tokens: 5, input_tokens: 3, output_tokens: 2, cached_tokens: 0, source: 'reported', request_text: '', response_text: '' }
  const steps = buildAgentTimeline({ duration_ms: 30, stages: [{ name: '调用模型', start_ms: 1, duration_ms: 10, status: 'success', data: { call_id: 'call-1' } }], calls: [call] } as import('../src/lib/agentMonitor').AgentTraceDetail)
  assert.equal(steps.length, 1)
  assert.equal(steps[0]?.call?.total_tokens, 5)
  const text = '[会话检索改写]\n' + JSON.stringify([{ role: 'system', content: '规则' }, { role: 'user', content: '问题\n上下文' }])
  assert.deepEqual(modelMessages(text), [{ role: '系统指令', content: '规则' }, { role: '用户消息 / 检索上下文', content: '问题\n上下文' }])
  assert.equal(modelMessages('旧提示词')[0]?.content, '旧提示词')
})

test('browser trace reports header, first text and completion on its own clock', async () => {
  const previous = globalThis.fetch
  let trace: import('../src/lib/api').ClientTrace | undefined
  globalThis.fetch = async () => new Response('event: meta\ndata: {"provider_id":"p","model":"m","sources":[],"web_sources":[]}\n\nevent: delta\ndata: {"text":"回答"}\n\nevent: done\ndata: {}\n\n', { headers: { 'Content-Type': 'text/event-stream', 'X-Agent-Trace-ID': 'trace-1' } })
  try {
    await streamKnowledge({ question: '问题' }, { onMeta() {}, onDelta() {}, onTrace(value) { trace = value } })
    assert.equal(trace?.id, 'trace-1')
    assert.deepEqual(trace?.events.map(event => event.name), ['页面发起请求', '收到响应头', '收到首段文本', '流式响应读取完成'])
    assert.ok(trace?.events.every(event => event.elapsed_ms >= 0))
  } finally { globalThis.fetch = previous }
})

test('timeline exposes actual query and distinguishes unchanged, rewritten, reused and fallback', async () => {
  const { buildAgentTimeline } = await import('../src/lib/agentTimeline')
  const compare = (query: string, extra: string[] = [], reused = false) => buildAgentTimeline({
    stages: [...extra.map(name => ({ name, start_ms: 0, status: 'success', duration_ms: 0 })),
      { name: '确定检索问题', start_ms: 1, status: 'success', duration_ms: 0,
        data: { original: '他们的排名', query, reused_page_plan: reused } }], calls: [], duration_ms: 2,
  } as import('../src/lib/agentMonitor').AgentTraceDetail).at(-1)?.queryComparison
  assert.match(compare('他们的排名')!.explanation, /未改写/)
  assert.deepEqual(compare('清华大学人才按 OpenAlex h-index 排序', ['查询改写结果']), {
    original: '他们的排名', query: '清华大学人才按 OpenAlex h-index 排序',
    explanation: '模型结合历史对话，将当前输入改写为独立检索语句。',
  })
  assert.match(compare('他们的排名', ['查询改写结果'])!.explanation, /模型已判断/)
  assert.match(compare('上一轮查询', [], true)!.explanation, /复用/)
  assert.match(compare('历史文本\n当前问题', ['查询改写降级'])!.explanation, /降级/)
})
