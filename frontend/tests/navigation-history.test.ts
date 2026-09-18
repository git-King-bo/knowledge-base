import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, nextTick } from 'vue'
import App from '../src/App.vue'

const settle = async () => { for (let i = 0; i < 3; i++) { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() } }

test('navigation retains search results, history snapshots and independent chat drafts', async () => {
  const previousFetch = globalThis.fetch
  const oldHash = window.location.hash
  let searches = 0
  globalThis.fetch = async input => {
    const url = new URL(String(input))
    if (url.pathname.endsWith('/knowledge/bases')) return Response.json([{
      id: 'base', name: '测试库', description: '', tags: [], status: 'active', source_count: 1,
      chunk_count: 10, created_at: '2026-09-17T00:00:00', updated_at: '2026-09-17T00:00:00',
    }])
    if (url.pathname.endsWith('/knowledge/search')) {
      searches++
      return Response.json({ query: url.searchParams.get('q'), hits: [{ id: 'hit', source_id: 'file',
        chunk_index: 1, title: null, content: `结果：${url.searchParams.get('q')}`, token_count: 10, score: .8 }] })
    }
    return Response.json([])
  }
  const host = document.createElement('div'); document.body.append(host)
  window.location.hash = 'retrieval'
  const app = createApp(App)
  const navigate = async (tab: string) => { window.location.hash = tab; window.dispatchEvent(new Event('hashchange')); await settle() }
  const type = (text: string) => { const input = host.querySelector('textarea')!; input.value = text; input.dispatchEvent(new Event('input', { bubbles: true })) }
  const search = async (text: string) => { type(text); await nextTick(); host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await settle() }
  try {
    app.mount(host); await settle()
    await search('第一问')
    await search('第二问')
    assert.equal(searches, 2)
    const history = host.querySelector('[aria-label="最近搜索"]')!
    const previous = [...history.querySelectorAll('button')].find(button => button.textContent?.includes('第一问'))!
    previous.click(); await nextTick()
    assert.ok(host.textContent?.includes('结果：第一问'))
    assert.equal(searches, 2, 'restoring history must not call the search API')
    await navigate('chat'); type('尚未发送的问题'); await nextTick()
    await navigate('knowledge')
    await navigate('retrieval')
    assert.equal(host.querySelector('textarea')?.value, '第一问')
    assert.ok(host.textContent?.includes('结果：第一问'))
    assert.equal(host.querySelectorAll('.search-history-entry').length, 2)
    assert.equal(searches, 2)
    await navigate('chat')
    assert.equal(host.querySelector('textarea')?.value, '尚未发送的问题')
    await navigate('retrieval')
    const clear = [...host.querySelectorAll('button')].find(button => button.textContent === '清空历史')!
    clear.click(); await nextTick()
    assert.equal(host.querySelector('[aria-label="最近搜索"]'), null)
  } finally { app.unmount(); host.remove(); globalThis.fetch = previousFetch; window.location.hash = oldHash }
})
