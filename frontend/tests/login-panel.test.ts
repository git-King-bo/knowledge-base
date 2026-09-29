import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, nextTick } from 'vue'
import LoginPanel from '../src/components/LoginPanel.vue'
import { currentUser } from '../src/lib/auth'

const flush = async () => { for (let i = 0; i < 5; i++) { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() } }
const frames = (globalThis as unknown as { dialogFrames: Map<number, FrameRequestCallback> }).dialogFrames
const advance = (globalThis as unknown as { advanceDialogFrame: (time: number) => void }).advanceDialogFrame

function mount(options: { reduced?: boolean; canvas?: boolean } = {}) {
  const originalMedia = window.matchMedia
  const originalContext = HTMLCanvasElement.prototype.getContext
  let reduced = options.reduced ?? false, draws = 0
  const motionListeners = new Set<() => void>()
  window.matchMedia = (() => ({ get matches() { return reduced },
    addEventListener: (_: string, listener: () => void) => motionListeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => motionListeners.delete(listener),
  })) as unknown as typeof window.matchMedia
  if (options.canvas) {
    HTMLCanvasElement.prototype.getContext = (() => ({
      createRadialGradient: () => ({ addColorStop() {} }), createLinearGradient: () => ({ addColorStop() {} }),
      scale() {}, setTransform() {}, fillRect() {}, beginPath() {}, arc() {}, fill() {},
      clearRect() { draws++ }, drawImage() {}, moveTo() {}, lineTo() {}, stroke() {},
      save() {}, restore() {}, translate() {}, rotate() {}, strokeRect() {},
    })) as unknown as typeof HTMLCanvasElement.prototype.getContext
  }
  const host = document.createElement('div'); document.body.append(host)
  const phases: string[] = []
  const app = createApp(LoginPanel, { onEntering: () => phases.push('entering'), onEntered: () => phases.push('entered') }); app.mount(host)
  return { host, phases, draws: () => draws, listenerCount: () => motionListeners.size,
    setReduced(value: boolean) { reduced = value; motionListeners.forEach(fn => fn()) },
    dispose() { app.unmount(); host.remove(); window.matchMedia = originalMedia; HTMLCanvasElement.prototype.getContext = originalContext },
  }
}

test('login remains usable without canvas and password visibility never submits the form', async () => {
  const originalFetch = globalThis.fetch
  let requests = 0
  globalThis.fetch = async () => { requests++; return Response.json({}) }
  const f = mount()
  try {
    assert.ok(f.host.querySelector('.orbit-fallback'))
    const password = f.host.querySelector<HTMLInputElement>('#login-password')!
    password.value = 'test-only-password'; password.dispatchEvent(new Event('input', { bubbles: true }))
    f.host.querySelector<HTMLButtonElement>('.password-toggle')!.click(); await flush()
    assert.equal(password.type, 'text'); assert.equal(password.value, 'test-only-password')
    assert.equal(f.host.querySelector('.password-toggle')?.getAttribute('aria-label'), '隐藏密码')
    f.host.querySelector<HTMLButtonElement>('.password-toggle')!.click(); await flush()
    assert.equal(password.type, 'password'); assert.equal(requests, 0)
  } finally { f.dispose(); globalThis.fetch = originalFetch }
})

test('pending login cannot be submitted twice, failed login can be corrected and retried', async () => {
  const originalFetch = globalThis.fetch
  let requests = 0, respond: (value: Response) => void = () => {}
  globalThis.fetch = () => { requests++; return new Promise(resolve => { respond = resolve }) }
  const f = mount()
  try {
    const form = f.host.querySelector('form')!, submit = f.host.querySelector<HTMLButtonElement>('.login-submit')!
    const password = f.host.querySelector<HTMLInputElement>('#login-password')!
    password.value = 'incorrect-test'; password.dispatchEvent(new Event('input', { bubbles: true }))
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await flush()
    assert.equal(requests, 1); assert.equal(submit.disabled, true); assert.equal(password.readOnly, true)
    respond(Response.json({ detail: '用户名或密码错误' }, { status: 401 })); await flush()
    assert.equal(submit.disabled, false); assert.equal(password.readOnly, false)
    assert.match(f.host.querySelector('[role="alert"]')?.textContent ?? '', /用户名或密码错误/)
    assert.equal(password.getAttribute('aria-describedby'), 'login-error')
    password.value = 'corrected-test'; password.dispatchEvent(new Event('input', { bubbles: true })); await flush()
    assert.equal(f.host.querySelector('[role="alert"]'), null)
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await flush()
    respond(Response.json({ id: 'login-test-user', username: 'admin', role: 'admin', enabled: true })); await flush()
    assert.equal(requests, 2); assert.equal(currentUser.value?.id, 'login-test-user'); assert.equal(password.value, '')
  } finally { f.dispose(); globalThis.fetch = originalFetch; currentUser.value = undefined }
})

test('orbit runs, pauses, resumes and releases all animation work on unmount', async () => {
  const before = frames.size, f = mount({ canvas: true })
  try {
    await flush(); assert.equal(frames.size, before + 1)
    const initial = f.draws(); advance(100); advance(116)
    assert.ok(f.draws() > initial)
    const toggle = f.host.querySelector<HTMLButtonElement>('.motion-toggle')!
    toggle.click(); await flush()
    assert.equal(toggle.getAttribute('aria-pressed'), 'true'); assert.equal(frames.size, before)
    const pausedDraws = f.draws(); advance(1000); assert.equal(f.draws(), pausedDraws)
    toggle.click(); await flush(); assert.equal(frames.size, before + 1)
    f.setReduced(true); await flush()
    assert.equal(frames.size, before); assert.equal(toggle.disabled, true)
    assert.ok(f.host.querySelector('.login-submit')); assert.equal(f.listenerCount(), 1)
    f.setReduced(false); await flush(); assert.equal(frames.size, before + 1)
  } finally { f.dispose() }
  assert.equal(frames.size, before); assert.equal(f.listenerCount(), 0)
})

test('reduced-motion initial load stays still, hidden tabs stop rendering and resume without duplicate loops', async () => {
  const before = frames.size, originalHidden = Object.getOwnPropertyDescriptor(document, 'hidden')
  const f = mount({ canvas: true, reduced: true })
  try {
    await flush(); assert.equal(frames.size, before)
    assert.equal(f.host.querySelector<HTMLButtonElement>('.motion-toggle')!.disabled, true)
    f.setReduced(false); await flush(); assert.equal(frames.size, before + 1)
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    document.dispatchEvent(new Event('visibilitychange')); assert.equal(frames.size, before)
    const draws = f.draws(); advance(1000); assert.equal(f.draws(), draws)
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    document.dispatchEvent(new Event('visibilitychange')); document.dispatchEvent(new Event('visibilitychange'))
    assert.equal(frames.size, before + 1)
  } finally {
    f.dispose()
    if (originalHidden) Object.defineProperty(document, 'hidden', originalHidden)
    else Reflect.deleteProperty(document, 'hidden')
  }
  assert.equal(frames.size, before)
})


test('successful login holds the tunnel through its dissolve and completes exactly once', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => Response.json({ id: 'tunnel-user', username: 'admin', role: 'admin', enabled: true })
  const f = mount({ canvas: true })
  const drain = async () => { for (let i = 0; i < 30; i++) await nextTick() }
  try {
    f.host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await drain()
    assert.deepEqual(f.phases, ['entering'])
    assert.equal(currentUser.value?.id, 'tunnel-user', 'workspace data can load behind the tunnel')
    assert.ok(f.host.querySelector('.is-entering'))
    assert.ok(f.host.querySelector('.login-layout')!.hasAttribute('inert'))
    t.mock.timers.tick(3599); await drain()
    assert.equal(f.host.querySelector('.is-revealing'), null)
    t.mock.timers.tick(1); await drain()
    assert.ok(f.host.querySelector('.is-revealing'))
    assert.deepEqual(f.phases, ['entering'])
    t.mock.timers.tick(1200); await drain()
    assert.deepEqual(f.phases, ['entering', 'entered'])
    window.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape' }))
    assert.deepEqual(f.phases, ['entering', 'entered'])
  } finally { f.dispose(); globalThis.fetch = originalFetch; currentUser.value = undefined }
})

test('reduced motion bypasses the tunnel and Escape releases a running entrance', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => Response.json({ id: 'tunnel-user', username: 'admin', role: 'admin', enabled: true })
  for (const reduced of [true, false]) {
    const f = mount({ reduced })
    try {
      f.host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      await flush()
      if (!reduced) {
        assert.deepEqual(f.phases, ['entering'])
        window.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape' }))
      }
      assert.deepEqual(f.phases, ['entering', 'entered'])
    } finally { f.dispose(); currentUser.value = undefined }
  }
  globalThis.fetch = originalFetch
})
