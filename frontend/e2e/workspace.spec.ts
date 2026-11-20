import { test, expect, openWorkspace } from './fixtures'

test('工作空间加载、过滤知识库并打开详情 @smoke', async ({ page, api }) => {
  expect(api.bases).toHaveLength(1)
  await openWorkspace(page)
  await expect(page).toHaveTitle(/知序/)
  await page.getByRole('textbox', { name: '搜索知识库' }).fill('不存在的库')
  await expect(page.getByRole('heading', { name: '没有符合条件的知识库' })).toBeVisible()
  await page.getByRole('textbox', { name: '搜索知识库' }).fill('前端测试')
  await page.getByRole('button', { name: /COLLECTION.*前端测试知识库/ }).click()
  await expect(page.getByRole('button', { name: '全部知识库' })).toBeVisible()
  await expect(page.getByRole('button', { name: '编辑信息' })).toBeVisible()
})

test('创建知识库表单提交并展示保存结果 @smoke', async ({ page, api }) => {
  await openWorkspace(page)
  await page.getByRole('button', { name: '新建知识库', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '新建知识库' })
  await expect(dialog.getByRole('button', { name: '保存知识库' })).toBeDisabled()
  await dialog.getByRole('textbox', { name: '知识库名称' }).fill('浏览器新建库')
  await dialog.getByRole('textbox', { name: '描述' }).fill('来自前端自动测试')
  await dialog.getByRole('button', { name: '保存知识库' }).click()
  await expect(page.getByRole('status')).toContainText('知识库已保存')
  expect(api.bases.at(-1)?.name).toBe('浏览器新建库')
})

test('检索结果与输入跨导航保留 @smoke', async ({ page, api }) => {
  expect(api.user).not.toBeNull()
  await openWorkspace(page)
  await page.getByRole('link', { name: '检索测试', exact: true }).click()
  await page.getByRole('textbox', { name: '输入测试问题' }).fill('测试问题')
  await page.getByRole('button', { name: '开始检索', exact: true }).click()
  await expect(page.getByText('这是固定的检索命中内容')).toBeVisible()
  await page.getByRole('link', { name: /^知识库/ }).first().click()
  await page.getByRole('link', { name: '检索测试', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '输入测试问题' })).toHaveValue('测试问题')
  await expect(page.getByText('这是固定的检索命中内容')).toBeVisible()
})

test('接口失败显示错误并允许重试', async ({ page, api }) => {
  api.listStatus = 500
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('测试服务暂时不可用')
  api.listStatus = 200
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '前端测试知识库' })).toBeVisible()
})

test('只读账号隐藏编辑与管理入口', async ({ page, api }) => {
  api.user!.role = 'viewer'
  await openWorkspace(page)
  await expect(page.getByRole('button', { name: '新建知识库', exact: true })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '模型配置', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: /COLLECTION.*前端测试知识库/ }).click()
  await expect(page.getByRole('button', { name: '编辑信息' })).toHaveCount(0)
  await expect(page.locator('input[type=file]')).toHaveCount(0)
})

test('空知识库状态允许开始创建', async ({ page, api }) => {
  api.bases = []
  await openWorkspace(page)
  await expect(page.getByRole('heading', { name: '让知识，从这里开始' })).toBeVisible()
  await page.getByRole('button', { name: '创建第一个知识库' }).click()
  await expect(page.getByRole('dialog', { name: '新建知识库' })).toBeVisible()
})

test('新版本提示保护未提交登录输入且可以推迟更新', async ({ page, api }) => {
  api.user = null
  await page.goto('/')
  await page.getByRole('textbox', { name: '用户名' }).fill('尚未提交')
  await page.route('**/version.json', route => route.fulfill({ json: { version: 'next-release' } }))
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  const notice = page.getByRole('status', { name: '应用更新' })
  await notice.getByRole('button', { name: '立即更新' }).click()
  await expect(notice).toContainText('尚未保存：登录输入')
  await notice.getByRole('button', { name: '稍后' }).click()
  await expect(notice).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: '用户名' })).toHaveValue('尚未提交')
})

test('上传预览确认后展示已接收状态', async ({ page, api }) => {
  expect(api.user).not.toBeNull()
  await openWorkspace(page)
  await page.getByRole('button', { name: /COLLECTION.*前端测试知识库/ }).click()
  page.once('dialog', dialog => dialog.accept())
  await expect(page.locator('input[type=file]')).toBeEnabled()
  await page.locator('input[type=file]').setInputFiles({ name: 'example.txt', mimeType: 'text/plain', buffer: Buffer.from('前端上传测试') })
  await expect(page.getByRole('status')).toContainText('1 份资料已接收')
})

test('固定 SSE 响应渲染 Markdown 并保留会话', async ({ page, api }) => {
  expect(api.user).not.toBeNull()
  await openWorkspace(page)
  await page.getByRole('link', { name: '知识问答', exact: true }).click()
  await page.getByRole('textbox', { name: '输入问题', exact: true }).fill('浏览器测试问题')
  await page.getByRole('textbox', { name: '输入问题', exact: true }).press('Control+Enter')
  await expect(page.locator('.markdown-body strong')).toHaveText('固定的流式内容')
  await expect(page.getByRole('button', { name: '清空会话' })).toBeEnabled()
  await expect(page.getByText('生成中断，已保留部分内容，可继续生成。')).toHaveCount(0)
})
