import { test as base, expect, type Page } from '@playwright/test'

type User = { id: string; username: string; role: string; enabled: boolean }
export const admin = { id: 'e2e-user', username: 'tester', role: 'admin', enabled: true }
export const initialBase = {
  id: 'base-1', name: '前端测试知识库', description: '固定浏览器测试资料', tags: ['E2E'],
  status: 'active', source_count: 1, chunk_count: 1,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}
export type ApiState = {
  user: User | null
  bases: typeof initialBase[]
  listStatus: number
  loginStatus: number
}
export const test = base.extend<{ api: ApiState }>({
  api: async ({ page, baseURL }, use) => {
    const state: ApiState = { user: { ...admin }, bases: [{ ...initialBase }], listStatus: 200, loginStatus: 200 }
    const unexpected: string[] = []
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const request = route.request()
      const url = new URL(request.url())
      // Never let a browser test reach a real API or an external service.
      if (url.origin !== new URL(baseURL!).origin) {
        unexpected.push(request.url()); await route.abort(); return
      }
      if (!url.pathname.startsWith('/api/')) { await route.continue(); return }
      const key = `${request.method()} ${url.pathname}`
      const json = (body: unknown, status = 200) => route.fulfill({ status, json: body })
      switch (key) {
        case 'GET /api/auth/me': await json(state.user || { detail: '未登录' }, state.user ? 200 : 401); return
        case 'POST /api/auth/login':
          if (state.loginStatus !== 200) { await json({ detail: '用户名或密码错误' }, state.loginStatus); return }
          state.user = { ...admin }; await json(state.user); return
        case 'POST /api/auth/logout': state.user = null; await json({}); return
        case 'GET /api/knowledge/bases':
          await json(state.listStatus === 200 ? state.bases : { detail: '测试服务暂时不可用' }, state.listStatus); return
        case 'POST /api/knowledge/bases': {
          const item = { ...initialBase, ...request.postDataJSON(), id: 'created-base', source_count: 0, chunk_count: 0 }
          state.bases.push(item); await json(item); return
        }
        case 'GET /api/ai/providers': await json([{ id: 'ui-service', name: '界面测试服务', provider: 'openai-compatible', base_url: 'https://invalid.example', api_key_hint: '', default_model: 'ui-test', is_default: true }]); return
        case 'POST /api/knowledge/ask/stream':
          await route.fulfill({ contentType: 'text/event-stream', body: [
            'event: meta\ndata: ' + JSON.stringify({ provider_id: 'ui-service', model: 'ui-test', sources: [], web_sources: [] }),
            'event: delta\ndata: ' + JSON.stringify({ text: '这是**固定的流式内容**。' }),
            'event: done\ndata: {}',
          ].join('\n\n') + '\n\n' }); return
        case 'POST /api/imports/base-1/reuse': await json({ reused: false }); return
        case 'POST /api/imports/base-1/preview':
          await json({ talent_records: 0, fields: [], characters: 10, duplicate_name_rows: 0 }); return
        case 'POST /api/imports/base-1': await json({ reused: false, source_id: 'uploaded-source' }); return
        case 'GET /api/conversations': await json([]); return
        case 'GET /api/knowledge/search':
          await json({ query: url.searchParams.get('q'), hits: [{ id: 'chunk-1', source_id: 'source-1',
            chunk_index: 1, content: '这是固定的检索命中内容', token_count: 12, score: 0.9, title: null }] }); return
      }
      if (request.method() === 'PUT' && /^\/api\/conversations\/[^/]+$/.test(url.pathname)) {
        await json({}); return
      }
      if (request.method() === 'GET' && /^\/api\/knowledge\/bases\/[^/]+\/(sources|chunks)$/.test(url.pathname)) {
        await json([]); return
      }
      unexpected.push(key)
      await json({ detail: `未声明的测试请求：${key}` }, 501)
    })
    await use(state)
    expect(unexpected, 'All API responses must be explicitly mocked; external network is forbidden').toEqual([])
    expect(errors, 'No uncaught browser exceptions').toEqual([])
  },
})
export { expect }
export async function openWorkspace(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
  await expect(page.getByText('服务已连接', { exact: false })).toBeVisible()
}
