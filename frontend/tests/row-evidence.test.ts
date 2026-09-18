import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, h, nextTick } from 'vue'
import RetrievalWorkspace from '../src/views/RetrievalWorkspace.vue'

test('structured answer exposes row evidence and clicking its citation opens the matching card', async () => {
  const oldFetch = globalThis.fetch
  const oldScroll = HTMLElement.prototype.scrollIntoView
  const oldMedia = window.matchMedia
  let scrolled = false
  HTMLElement.prototype.scrollIntoView = () => { scrolled = true }
  window.matchMedia = globalThis.matchMedia
  const row = { index: 1, source_id: 'file', filename: '人才.xlsx', sheet: '人员表', excel_row: 616,
    fields: { '姓名': '示例人员', '领域': '具身智能', 'OpenAlex h-index': '78', 'OpenAlex主页': 'https://openalex.org/A123' } }
  globalThis.fetch = async input => {
    if (!String(input).endsWith('/ask/stream')) return Response.json([])
    return new Response(`event: meta\ndata: ${JSON.stringify({ provider_id: 'provider', model: 'test', sources: [], web_sources: [], row_sources: [row] })}\n\nevent: delta\ndata: ${JSON.stringify({ text: '示例人员（Record 1）' })}\n\nevent: done\ndata: {}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
  }
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ render: () => h(RetrievalWorkspace, { mode: 'chat', initialBaseId: 'base',
    bases: [{ id: 'base', name: '人才库', description: '', tags: [], status: 'active', sourceCount: 1, chunkCount: 20, createdAt: '', updatedAt: '' }],
    providers: [{ id: 'provider', name: '模型', provider: 'mock', baseUrl: '', defaultModel: 'test', apiKeyHint: '', isDefault: true }],
  }) })
  try {
    app.mount(host); await nextTick()
    const input = host.querySelector('textarea')!
    input.value = '查询具身智能人才'; input.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    for (let i = 0; i < 3; i++) {
      await new Promise(resolve => setTimeout(resolve, 0))
      ;(globalThis as unknown as { advanceDialogFrame: (time: number) => void }).advanceDialogFrame(100 + i * 16)
      await nextTick()
    }
    assert.match(host.querySelector('summary')!.textContent!, /1 处/)
    const card = host.querySelector('[data-record-index="1"]')!
    assert.ok(card.textContent?.includes('Excel 第 616 行'))
    assert.ok(card.textContent?.includes('78'))
    assert.equal(card.querySelector('a')?.getAttribute('href'), 'https://openalex.org/A123')
    host.querySelector<HTMLButtonElement>('[data-record-ref="1"]')!.click(); await nextTick()
    assert.ok(host.querySelector('details')!.open)
    assert.ok(card.classList.contains('is-citation-active'))
    assert.ok(scrolled)
  } finally {
    app.unmount(); host.remove(); globalThis.fetch = oldFetch
    HTMLElement.prototype.scrollIntoView = oldScroll; window.matchMedia = oldMedia
  }
})
