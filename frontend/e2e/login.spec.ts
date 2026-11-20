import { test, expect } from './fixtures'

test('登录成功进入工作空间，退出后回到登录页 @smoke', async ({ page, api }) => {
  api.user = null
  await page.goto('/')
  await page.getByRole('textbox', { name: '用户名' }).fill('tester')
  await page.getByLabel('密码', { exact: true }).fill('test-only-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  expect(api.user).toBeNull()
})

test('错误凭据显示错误，修改输入后清除提示', async ({ page, api }) => {
  api.user = null
  api.loginStatus = 401
  await page.goto('/')
  await page.getByRole('textbox', { name: '用户名' }).fill('tester')
  await page.getByLabel('密码', { exact: true }).fill('wrong-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('用户名或密码错误')
  await page.getByLabel('密码', { exact: true }).fill('changed-password')
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.getByRole('button', { name: '显示密码' }).click()
  await expect(page.getByLabel('密码', { exact: true })).toHaveAttribute('type', 'text')
})
