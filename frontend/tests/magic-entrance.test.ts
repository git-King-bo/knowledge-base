import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, nextTick } from 'vue'
import MagicEntrance from '../src/components/MagicEntrance.vue'

const flush = async () => { for (let i = 0; i < 6; i++) await nextTick() }

function fixture(options: { seen?: boolean; reduced?: boolean; decode?: () => Promise<void>; storageFails?: boolean } = {}) {
  const storageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
  const imagePrototype = window.HTMLImageElement.prototype
  const decodeDescriptor = Object.getOwnPropertyDescriptor(imagePrototype, 'decode')
  const oldMedia = globalThis.matchMedia
  const oldOverflow = document.body.style.overflow
  const stored = new Map(options.seen ? [['knowledge-fairy-entrance-v1', 'seen']] : [])
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: {
    getItem: (key: string) => { if (options.storageFails) throw new Error('blocked'); return stored.get(key) ?? null },
    setItem: (key: string, value: string) => { if (options.storageFails) throw new Error('blocked'); stored.set(key, value) },
  } })
  Object.defineProperty(imagePrototype, 'decode', { configurable: true, value: options.decode ?? (() => Promise.resolve()) })
  globalThis.matchMedia = (() => ({ matches: options.reduced ?? false, addEventListener() {}, removeEventListener() {} })) as unknown as typeof matchMedia
  document.body.style.overflow = 'auto'
  const host = document.createElement('div'); document.body.append(host)
  const phases: string[] = []
  const app = createApp(MagicEntrance, { onPhase: (phase: string) => phases.push(phase) })
  const instance = app.mount(host) as unknown as { play: () => Promise<void> }
  return { phases, stored, instance, dispose() {
    app.unmount(); host.remove()
    globalThis.matchMedia = oldMedia
    document.body.style.overflow = oldOverflow
    if (storageDescriptor) Object.defineProperty(globalThis, 'sessionStorage', storageDescriptor)
    else Reflect.deleteProperty(globalThis, 'sessionStorage')
    if (decodeDescriptor) Object.defineProperty(imagePrototype, 'decode', decodeDescriptor)
    else Reflect.deleteProperty(imagePrototype, 'decode')
  } }
}

test('magic entrance reveals workspace, releases scroll and autoplays again on refresh even with an old seen flag', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const f = fixture()
  try {
    await flush()
    assert.ok(document.querySelector('.magic-entrance.is-ready'))
    assert.equal(document.body.style.overflow, 'hidden')
    t.mock.timers.tick(1450); await flush()
    assert.deepEqual(f.phases, ['playing', 'revealing'])
    t.mock.timers.tick(3200); await flush()
    assert.equal(f.phases.at(-1), 'idle')
    assert.equal(document.querySelector('.magic-entrance'), null)
    assert.equal(document.body.style.overflow, 'auto')
  } finally { f.dispose() }
  const seen = fixture({ seen: true })
  try {
    await flush()
    assert.ok(document.querySelector('.magic-entrance'), 'refresh must replay despite the old session flag')
    document.querySelector<HTMLButtonElement>('.entrance-skip')!.click(); await flush()
    await seen.instance.play(); await flush()
    assert.ok(document.querySelector('.magic-entrance'), 'manual replay remains available')
    document.querySelector<HTMLButtonElement>('.entrance-skip')!.click(); await flush()
    assert.equal(document.body.style.overflow, 'auto')
  } finally { seen.dispose() }
})

test('Escape and pending image timeout never leave the workspace blocked', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const f = fixture({ decode: () => new Promise(() => {}), storageFails: true })
  try {
    await flush()
    document.querySelector('.magic-entrance')!.dispatchEvent(new Event('cancel', { cancelable: true }))
    await flush()
    assert.equal(f.phases.at(-1), 'idle')
    void f.instance.play(); await flush()
    t.mock.timers.tick(1800); await flush()
    assert.equal(document.querySelector('.magic-entrance'), null)
    assert.equal(document.body.style.overflow, 'auto')
  } finally { f.dispose() }
})

test('reduced motion skips the entrance and an image failure restores the workspace', async () => {
  const reduced = fixture({ reduced: true })
  try { await flush(); assert.equal(document.querySelector('.magic-entrance'), null); assert.deepEqual(reduced.phases, []) }
  finally { reduced.dispose() }
  const failed = fixture({ decode: () => Promise.reject(new Error('missing asset')) })
  try { await flush(); assert.equal(failed.phases.at(-1), 'idle'); assert.equal(document.body.style.overflow, 'auto') }
  finally { failed.dispose() }
})
