import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, h, nextTick } from 'vue'
import FilePreview from '../src/components/FilePreview.vue'

const flushPreview = async () => { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }

test('file preview pages rows, changes sheets, escapes cells and emits close', async () => {
  const previousFetch = globalThis.fetch
  const calls: URL[] = []
  globalThis.fetch = async input => {
    const url = new URL(String(input)); calls.push(url)
    const sheet = Number(url.searchParams.get('sheet')), offset = Number(url.searchParams.get('offset'))
    return Response.json({ kind: 'table', sheets: ['名单', '另一表'], columns: 2, columns_truncated: false,
      total: sheet ? 1 : 112, rows: [{ number: offset + 1, cells: [sheet ? '第二张表' : '<script>unsafe</script>', '0'] }] })
  }
  const host = document.createElement('div'); document.body.append(host)
  let closed = false
  const app = createApp({ render: () => h(FilePreview, { baseId: 'base', source: {
    id: 'source', filename: '名单.xlsx', mimeType: '', status: 'parsed', chunkCount: 10, createdAt: '',
  }, onClose: () => { closed = true } }) })
  try {
    app.mount(host); await flushPreview()
    const dialog = document.querySelector('.file-preview') as HTMLDialogElement
    assert.ok(dialog.open)
    assert.equal(dialog.querySelector('script'), null)
    assert.equal(dialog.querySelector('td')?.textContent, '<script>unsafe</script>')
    const button = (label: string) => [...dialog.querySelectorAll('button')].find(item => item.textContent === label)!
    button('下一页').click(); await flushPreview()
    assert.equal(calls.at(-1)?.searchParams.get('offset'), '50')
    button('另一表').click(); await flushPreview()
    assert.equal(calls.at(-1)?.searchParams.get('offset'), '0')
    assert.equal(calls.at(-1)?.searchParams.get('sheet'), '1')
    assert.equal(dialog.querySelector('td')?.textContent, '第二张表')
    assert.ok(button('下一页').disabled)
    dialog.querySelector<HTMLButtonElement>('[aria-label="关闭预览"]')!.click()
    assert.ok(closed)
  } finally { app.unmount(); host.remove(); globalThis.fetch = previousFetch }
})
