import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, h, nextTick, ref } from 'vue'
import FairySidebar from '../src/components/FairySidebar.vue'

test('fairy door preserves settings through rapid toggles and keeps the collapsed panel inert', async () => {
  const open = ref(true)
  const setting = ref('保留的设置')
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ render: () => h(FairySidebar, { open: open.value, 'onUpdate:open': value => { open.value = value } },
    { default: () => h('input', { value: setting.value, onInput: (event: Event) => { setting.value = (event.target as HTMLInputElement).value }, 'aria-label': '测试设置' }) }) })
  try {
    app.mount(host); await nextTick()
    const button = host.querySelector('button')!
    const input = host.querySelector('input')!
    input.value = '用户修改后的设置'
    input.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
    assert.match(host.querySelector('img')!.src, /fairy-door-push.png$/)
    button.click(); await nextTick()
    assert.equal(button.getAttribute('aria-expanded'), 'false')
    assert.equal(host.querySelector('#fairy-sidebar-door')!.getAttribute('aria-hidden'), 'true')
    assert.ok(host.querySelector('#fairy-sidebar-door')!.hasAttribute('inert'))
    assert.match(host.querySelector('img')!.src, /fairy-door-pull.png$/)
    button.click(); await nextTick()
    button.click(); await nextTick()
    button.click(); await nextTick()
    assert.equal(button.getAttribute('aria-expanded'), 'true')
    assert.equal(host.querySelector('input'), input)
    assert.equal(input.value, '用户修改后的设置')
    assert.equal(host.querySelector('#fairy-sidebar-door')!.hasAttribute('inert'), false)
    host.querySelector('img')!.dispatchEvent(new Event('error')); await nextTick()
    assert.ok(host.querySelector('.fairy-door-fallback'))
    button.click(); await nextTick()
    assert.equal(button.getAttribute('aria-expanded'), 'false')
  } finally { app.unmount(); host.remove() }
})
