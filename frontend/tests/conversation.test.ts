import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, h, nextTick, ref } from 'vue'
import RetrievalWorkspace from '../src/views/RetrievalWorkspace.vue'
import { buildConversationHistory } from '../src/lib/conversation'

const settle = async () => {
  for (let i = 0; i < 5; i++) {
    await new Promise(resolve => setTimeout(resolve, 0))
    ;(globalThis as unknown as { advanceDialogFrame: (time: number) => void }).advanceDialogFrame(100 + i * 16)
    await nextTick()
  }
}

test('followups send conversation history, changing bases preserves it, clear resets it', async () => {
  const oldFetch = globalThis.fetch
  const requests: any[] = []
  const baseId = ref('one')
  const baseRequest = ref(0)
  globalThis.fetch = async (input, init) => {
    if (!String(input).endsWith('/ask/stream')) return Response.json([])
    requests.push(JSON.parse(String(init?.body)))
    const meta = { provider_id: 'provider', model: 'test', sources: [], web_sources: [], retrieval_query: '已解析的追问' }
    return new Response(`event: meta\ndata: ${JSON.stringify(meta)}\n\nevent: delta\ndata: ${JSON.stringify({ text: `回答${requests.length}` })}\n\nevent: done\ndata: {}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
  }
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ render: () => h(RetrievalWorkspace, { mode: 'chat', initialBaseId: baseId.value, baseRequest: baseRequest.value,
    bases: ['one', 'two'].map(id => ({ id, name: id, description: '', tags: [], status: 'active' as const, sourceCount: 1, chunkCount: 1, createdAt: '', updatedAt: '' })),
    providers: [{ id: 'provider', name: '模型', provider: 'mock', baseUrl: '', defaultModel: 'test', apiKeyHint: '', isDefault: true }],
  }) })
  const submit = async (question: string) => {
    const input = host.querySelector<HTMLTextAreaElement>('[aria-label="输入问题"]')!
    input.value = question; input.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await settle()
  }
  try {
    app.mount(host); await settle()
    const count = host.querySelector<HTMLInputElement>('.qa-range-field input[type="range"]')!
    count.value = '8'; count.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
    await submit('第一个方案是什么？')
    assert.deepEqual(requests[0].history, [])
    assert.equal(requests[0].top_k, 8)
    assert.equal(requests[0].talent_page_size, 8)
    await submit('它有什么缺点？')
    assert.deepEqual(requests[1].history, [{ question: '第一个方案是什么？', answer: '回答1' }])
    baseId.value = 'two'; baseRequest.value++; await settle()
    assert.equal(host.querySelectorAll('.conversation-turn').length, 2)
    await submit('换这个知识库再比较一下')
    assert.equal(requests[2].knowledge_base_id, 'two')
    assert.equal(requests[2].history.length, 2)
    host.querySelector<HTMLButtonElement>('.qa-reset-button')!.click(); await settle()
    assert.equal(host.querySelectorAll('.conversation-turn').length, 0)
    await submit('新的主题')
    assert.deepEqual(requests[3].history, [])
    assert.deepEqual(requests[1].history, [{ question: '第一个方案是什么？', answer: '回答1' }], 'request snapshots must remain stable')
  } finally { app.unmount(); host.remove(); globalThis.fetch = oldFetch }
})

test('context excludes unfinished answers and stays within turn and character budgets', () => {
  const turns = Array.from({ length: 20 }, (_, index) => ({ question: `问${index}`, answer: `答${index}`, status: 'done' }))
  turns.push({ question: '失败的问题', answer: '不完整回答', status: 'error' })
  const history = buildConversationHistory(turns)
  assert.equal(history.length, 12)
  assert.equal(history[0]?.question, '问8')
  assert.equal(history.at(-1)?.answer, '答19')
  const large = buildConversationHistory(turns.map(turn => ({ ...turn, answer: '文'.repeat(10000) })))
  assert.ok(large.every(turn => turn.answer.length <= 6000))
  assert.ok(large.reduce((sum, turn) => sum + turn.question.length + turn.answer.length, 0) <= 24000)
})

test('personnel pagination state is saved in history and next-page button submits it', async () => {
  const oldFetch = globalThis.fetch
  const requests: any[] = []
  const state = { knowledge_base_id: 'one', query: '清华大学人才',
    plan: { filters: [{ field: '当前机构', op: 'contains', value: '清华大学' }], sort_by: null, descending: true, limit: 5 },
    offset: 0, page_size: 5, returned: 5, has_more: true }
  globalThis.fetch = async (input, init) => {
    if (!String(input).endsWith('/ask/stream')) return Response.json([])
    requests.push(JSON.parse(String(init?.body)))
    const meta = { provider_id: 'provider', model: 'test', sources: [], web_sources: [], row_sources: [],
      query_state: requests.length === 1 ? state : { ...state, offset: 5, returned: 3, has_more: false } }
    return new Response(`event: meta\ndata: ${JSON.stringify(meta)}\n\nevent: delta\ndata: ${JSON.stringify({ text: '已查询人才名单' })}\n\nevent: done\ndata: {}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
  }
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ render: () => h(RetrievalWorkspace, { mode: 'chat', initialBaseId: 'one',
    bases: [{ id: 'one', name: '人才库', description: '', tags: [], status: 'active' as const, sourceCount: 1, chunkCount: 1, createdAt: '', updatedAt: '' }],
    providers: [{ id: 'provider', name: '模型', provider: 'mock', baseUrl: '', defaultModel: 'test', apiKeyHint: '', isDefault: true }],
  }) })
  try {
    app.mount(host); await settle()
    const input = host.querySelector<HTMLTextAreaElement>('[aria-label="输入问题"]')!
    input.value = '清华大学人才'; input.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await settle()
    const next = [...host.querySelectorAll('button')].find(button => button.textContent === '下一页')!
    assert.ok(next)
    next.click(); await settle()
    assert.equal(requests[1].question, '继续')
    assert.deepEqual(requests[1].history[0].query_state, state)
    assert.equal(requests[1].talent_page_size, 5)
    assert.equal([...host.querySelectorAll('button')].some(button => button.textContent === '下一页'), false)
  } finally { app.unmount(); host.remove(); globalThis.fetch = oldFetch }
})

test('sidebar switches to searchable history and restores the selected conversation', async () => {
  const { currentUser } = await import('../src/lib/auth')
  const oldUser = currentUser.value, oldFetch = globalThis.fetch
  currentUser.value = { id: 'user', username: 'admin', role: 'admin', enabled: true }
  globalThis.fetch = async input => {
    const url = String(input)
    if (url.endsWith('/conversations')) return Response.json([
      { id: 'saved-one', title: '清华大学人才', updated_at: new Date().toISOString() },
      { id: 'saved-two', title: '西湖大学人才' }])
    if (url.endsWith('/conversations/saved-one')) return Response.json({ favorite: false, feedback: '', messages: [{
      id: 10, question: '清华大学人才', answer: '已找到人才记录', status: 'done', sources: [], webSources: [], rowSources: [],
      model: 'test', request: { knowledgeBaseId: 'one', question: '清华大学人才' },
    }] })
    return Response.json([])
  }
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ render: () => h(RetrievalWorkspace, { mode: 'chat', initialBaseId: 'one',
    bases: [{ id: 'one', name: '人才库', description: '', tags: [], status: 'active' as const, sourceCount: 1, chunkCount: 1, createdAt: '', updatedAt: '' }],
    providers: [{ id: 'provider', name: '模型', provider: 'mock', baseUrl: '', defaultModel: 'test', apiKeyHint: '', isDefault: true }],
  }) })
  const transition = async () => { await settle(); await new Promise(resolve => setTimeout(resolve, 240)); await settle() }
  try {
    app.mount(host); await settle()
    host.querySelector<HTMLButtonElement>('[aria-label="切换到历史会话"]')!.click(); await transition()
    assert.ok(host.querySelector('[aria-label="切换到问答设置"]'))
    assert.equal(host.querySelector('[role="tablist"]'), null)
    assert.ok(host.querySelector('aside #qa-history-body'))
    assert.equal(host.querySelectorAll('.qa-history-item').length, 2)
    const search = host.querySelector<HTMLInputElement>('[aria-label="搜索历史会话"]')!
    search.value = '清华'; search.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
    assert.equal(host.querySelectorAll('.qa-history-item').length, 1)
    host.querySelector<HTMLButtonElement>('.qa-history-open')!.click(); await settle()
    assert.ok(host.querySelector('.conversation-turn')?.textContent?.includes('已找到人才记录'))
    assert.ok(host.querySelector('.qa-history-item.is-current'))
    host.querySelector<HTMLButtonElement>('[aria-label="切换到问答设置"]')!.click(); await transition()
    assert.ok(host.querySelector('#qa-settings-body'))
    assert.equal(host.querySelectorAll('.conversation-turn').length, 1)
  } finally { app.unmount(); host.remove(); globalThis.fetch = oldFetch; currentUser.value = oldUser }
})
