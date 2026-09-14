import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, h, nextTick, ref } from 'vue'
import MacDialog from '../src/components/MacDialog.vue'
import { bottomBox, createGeniePath, genieBand, genieOpacity, drawGenie, originBox } from '../src/lib/genie'
import { captures, setMode, waiting } from './dialog-image-mock'

const env = globalThis as any
const flush = async () => { for (let i = 0; i < 8; i++) await nextTick() }
async function mount(extra: Record<string, unknown> = {}) {
  const visible = ref(false)
  const events: string[] = []
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ setup: () => () => h(MacDialog, {
    modelValue: visible.value, 'onUpdate:modelValue': (value: boolean) => { visible.value = value },
    title: 'Test', onOpened: () => events.push('opened'), onClosed: () => events.push('closed'), ...extra,
  }, { default: () => [h('input'), h('div', { class: 'scroller' }, [h('p', 'first'), h('p', 'second')])] }) })
  app.mount(host)
  const dialog = document.body.querySelector('dialog:last-of-type') as HTMLDialogElement
  return { visible, dialog, events, dispose() { app.unmount(); host.remove() } }
}
function finishFrames() { env.advanceDialogFrame(100); env.advanceDialogFrame(1000) }

const source = { left: 200, top: 200, width: 500, height: 400 }
const targets = [
  { name: 'right', box: { left: 1000, top: 390, width: 40, height: 20 }, horizontal: true, positive: true },
  { name: 'left', box: { left: -100, top: 390, width: 40, height: 20 }, horizontal: true, positive: false },
  { name: 'above', box: { left: 430, top: -100, width: 40, height: 20 }, horizontal: false, positive: false },
  { name: 'below', box: { left: 430, top: 900, width: 40, height: 20 }, horizontal: false, positive: true },
  { name: 'inside right', box: { left: 490, top: 390, width: 40, height: 20 }, horizontal: true, positive: true },
  { name: 'inside left', box: { left: 370, top: 390, width: 40, height: 20 }, horizontal: true, positive: false },
  { name: 'inside above', box: { left: 430, top: 330, width: 40, height: 20 }, horizontal: false, positive: false },
  { name: 'inside below', box: { left: 430, top: 450, width: 40, height: 20 }, horizontal: false, positive: true },
  { name: 'coincident centers', box: { left: 430, top: 390, width: 40, height: 20 }, horizontal: false, positive: true },
]

test('four directions and internal targets: correct neck, exact endpoints, ordered bands', () => {
  for (const { name, box, horizontal, positive } of targets) {
    const path = createGeniePath(source, box)
    assert.equal(path.horizontal, horizontal, name); assert.equal(path.positive, positive, name)
    for (let step = 0; step <= 100; step++) {
      const p = step / 100
      let previous = -Infinity
      for (let index = 0; index <= 100; index++) {
        const point = genieBand(path, index / 100, p)
        assert.ok(point.position > previous, `${name} at ${p}`)
        assert.ok(point.breadth > 0); previous = point.position
      }
    }
    for (const [progress, rect] of [[0, source], [1, box]] as const) {
      for (const band of [0, .25, .5, .75, 1]) {
        const point = genieBand(path, band, progress)
        assert.deepEqual(point, horizontal
          ? { position: rect.left + band * rect.width, cross: rect.top, breadth: rect.height }
          : { position: rect.top + band * rect.height, cross: rect.left, breadth: rect.width })
      }
    }
    const near = positive ? 1 : 0
    assert.ok(genieBand(path, near, .2).breadth < genieBand(path, 1 - near, .2).breadth, name)
    const forward = Array.from({ length: 101 }, (_, i) => genieBand(path, .3, i / 100))
    const reverse = Array.from({ length: 101 }, (_, i) => genieBand(path, .3, (100 - i) / 100)).reverse()
    assert.deepEqual(forward, reverse)
  }
  const diagonal = createGeniePath(source, { left: 530, top: 490, width: 40, height: 20 })
  assert.equal(diagonal.horizontal, false, 'ties consistently choose vertical')
})

test('near and side targets soften gradually; far central bottom keeps its original rhythm', () => {
  const bottom = bottomBox(.5, 900, 1000)
  const baseline = createGeniePath(source, bottom)
  assert.equal(baseline.softness, 0); assert.equal(baseline.neckEnd, .48); assert.equal(baseline.followStart, .24)
  assert.equal(bottomBox(-3, 1000, 800).left, 0); assert.equal(bottomBox(3, 1000, 800).left, 952)
  for (const p of [0, .1, .3, .5, .8, 1]) {
    const smooth = (x: number) => { const t = Math.max(0, Math.min(1, x)); return t * t * (3 - 2 * t) }
    const travel = smooth((p - .24) / .76)
    const neck = smooth(p / .48) * smooth(.7) * (1 - travel) + travel
    const point = genieBand(baseline, .7, p)
    assert.ok(Math.abs(point.breadth - (500 + (48 - 500) * neck)) < 1e-9)
  }
  for (const target of targets.filter(item => item.horizontal || item.name.startsWith('inside'))) {
    const path = createGeniePath(source, target.box)
    assert.ok(path.softness > .7)
    assert.ok(path.neckEnd > baseline.neckEnd); assert.ok(path.followStart < baseline.followStart)
    assert.ok(path.fadeStart < baseline.fadeStart)
    let alpha = 1
    for (let i = 0; i <= 100; i++) { const next = genieOpacity(path, i / 100); assert.ok(next <= alpha && next >= 0); alpha = next }
    assert.equal(genieOpacity(path, path.fadeStart), 1); assert.equal(genieOpacity(path, 1), 0)
    // No mid-path kink at either timing boundary; value and velocity stay continuous.
    for (const p of [path.neckEnd, path.followStart]) {
      const a = genieBand(path, .85, p - .00001), b = genieBand(path, .85, p), c = genieBand(path, .85, p + .00001)
      assert.ok(Math.abs(a.breadth - 2 * b.breadth + c.breadth) < .00001)
      assert.ok(Math.abs(a.cross - 2 * b.cross + c.cross) < .00001)
    }
  }
})

test('renderer samples vertical columns for horizontal motion and horizontal rows for vertical motion', () => {
  const image = document.createElement('canvas'); image.width = 1000; image.height = 800
  const surface = document.createElement('canvas'), ctx = surface.getContext('2d')!
  for (const { box, horizontal } of targets) {
    env.dialogDraws.length = 0
    drawGenie(ctx, image, source, box, .4)
    const calls = env.dialogDraws as number[][]
    assert.equal(calls.length, Math.ceil((horizontal ? source.width : source.height) * 1.5))
    assert.ok(calls.every(call => horizontal ? call[1] === 0 && call[3] === image.height : call[0] === 0 && call[2] === image.width))
    assert.ok(calls[1]![horizontal ? 0 : 1]! > calls[0]![horizontal ? 0 : 1]!)
    // Geometry at the terminal frame stays inside the exact target rectangle.
    env.dialogDraws.length = 0; drawGenie(ctx, image, source, box, 1)
    const last = env.dialogDraws.at(-1)
    assert.ok(Math.abs(last[4] + last[6] - box.left - box.width) < 1e-8)
    assert.ok(Math.abs(last[5] + last[7] - box.top - box.height) < 1e-8)
    assert.equal(surface.style.opacity, '0')
    drawGenie(ctx, image, source, box, 0); assert.equal(surface.style.opacity, '1')
  }
})

test('origin accepts DOM, template ref, component and function; ignores hidden/removed/throwing targets', () => {
  const button = document.createElement('button'); document.body.append(button)
  const expected = originBox(button)
  assert.ok(expected)
  assert.deepEqual(originBox(ref(button)), expected)
  assert.deepEqual(originBox({ $el: button }), expected)
  assert.deepEqual(originBox(() => ({ $el: button })), expected)
  button.style.display = 'none'; assert.equal(originBox(button), undefined)
  button.style.display = ''; button.remove(); assert.equal(originBox(button), undefined)
  assert.equal(originBox(() => { throw Error() }), undefined)
})

test('open/close reverse continuously, retain DOM state and lock until closed', async () => {
  const item = await mount()
  item.visible.value = true; await flush(); finishFrames(); await flush()
  assert.deepEqual(item.events, ['opened'])
  const input = item.dialog.querySelector('input')!; input.value = 'edited'; input.setSelectionRange(1, 3)
  const scroller = item.dialog.querySelector('.scroller')!; scroller.scrollTop = 40
  item.visible.value = false; await flush()
  assert.equal(document.documentElement.style.overflow, 'hidden')
  assert.match(captures.at(-1)!.querySelector('.scroller > div')!.getAttribute('style')!, /-40px/)
  env.advanceDialogFrame(2000); env.advanceDialogFrame(2200)
  const count = captures.length
  const lastDraw = env.dialogDraws.at(-1)
  item.visible.value = true; await flush()
  assert.equal(captures.length, count)
  assert.equal(env.dialogDraws.at(-1), lastDraw)
  env.advanceDialogFrame(2250)
  assert.ok(env.dialogDraws.at(-1)[6] > lastDraw[6])
  env.advanceDialogFrame(3000); await flush()
  assert.equal(item.dialog.querySelector('input'), input); assert.equal(input.value, 'edited'); assert.equal(input.selectionStart, 1)
  assert.equal(scroller.scrollTop, 40)
  item.visible.value = false; await flush(); finishFrames(); await flush()
  assert.equal(item.dialog.open, false); assert.equal(document.documentElement.style.overflow, '')
  assert.equal(item.events.at(-1), 'closed'); item.dispose()
  assert.equal(env.dialogFrames.size, 0)
})

test('reads moved origin, falls back to opening rect when removed, freezes target during reversal', async () => {
  const button = document.createElement('button'); document.body.append(button)
  let reads = 0, left = 40
  button.getBoundingClientRect = () => { reads++; return { left, top: 30, width: 50, height: 20 } as DOMRect }
  const item = await mount({ origin: button })
  item.visible.value = true; await flush(); finishFrames(); await flush(); assert.equal(reads, 1)
  left = 900; item.visible.value = false; await flush(); assert.equal(reads, 2)
  env.advanceDialogFrame(2000); env.advanceDialogFrame(2100)
  item.visible.value = true; await flush(); assert.equal(reads, 2)
  env.advanceDialogFrame(3000); await flush()
  button.remove(); item.visible.value = false; await flush(); finishFrames(); await flush()
  const last = env.dialogDraws.at(-1)
  assert.ok(Math.abs(last[4] + last[6] - 90) < 1e-8) // Right edge of opening target, after horizontal collapse.
  assert.equal(last[5], 30); assert.equal(last[7], 20)
  item.dispose()
})

test('each direction reverses from the current geometry and alpha, without restarting duration', async () => {
  const actualSource = { left: 300, top: 180, width: 500, height: 540 }
  // Translate fixtures so they remain in the same directions relative to the mocked panel.
  for (const { name, box } of targets) {
    const target = { ...box, left: box.left + 100, top: box.top + 50 }
    const button = document.createElement('button'); document.body.append(button)
    button.getBoundingClientRect = () => target as DOMRect
    const item = await mount({ origin: button, duration: 1000 })
    item.visible.value = true; await flush()
    env.advanceDialogFrame(100); env.advanceDialogFrame(1100); await flush()
    assert.deepEqual(item.events, ['opened'], name)
    item.visible.value = false; await flush()
    env.advanceDialogFrame(2000); env.advanceDialogFrame(2950) // .95, already fading
    const surface = item.dialog.querySelector('canvas')!
    const opacity = surface.style.opacity
    const count = captures.length
    const before = env.dialogDraws.at(-1)
    item.visible.value = true; await flush()
    assert.equal(env.dialogDraws.at(-1), before); assert.equal(surface.style.opacity, opacity)
    assert.equal(captures.length, count)
    const drawStart = env.dialogDraws.length
    env.advanceDialogFrame(3000) // .90: exactly 50ms backward on the same 1000ms path
    const path = createGeniePath(actualSource, target)
    const expected = genieBand(path, 0, .9)
    const actual = env.dialogDraws[drawStart]
    assert.ok(Math.abs(actual[4] - (path.horizontal ? expected.position : expected.cross)) < 1e-8, name)
    assert.ok(Math.abs(actual[5] - (path.horizontal ? expected.cross : expected.position)) < 1e-8, name)
    assert.ok(Number(surface.style.opacity) > Number(opacity))
    env.advanceDialogFrame(3899); await flush(); assert.equal(item.events.length, 1)
    env.advanceDialogFrame(3901); await flush(); assert.equal(item.events.length, 2)
    item.dispose(); button.remove()
  }
})

test('duration still measures a full linear progress traversal in milliseconds', async () => {
  const item = await mount({ duration: 680 })
  item.visible.value = true; await flush()
  env.advanceDialogFrame(100); env.advanceDialogFrame(779); await flush()
  assert.deepEqual(item.events, [])
  env.advanceDialogFrame(781); await flush(); assert.deepEqual(item.events, ['opened'])
  item.visible.value = false; await flush()
  env.advanceDialogFrame(1000); env.advanceDialogFrame(1679); await flush()
  assert.equal(item.dialog.open, true)
  env.advanceDialogFrame(1681); await flush(); assert.equal(item.dialog.open, false)
  item.dispose()
})

test('nested instances release only their own scroll lock, duration zero skips capture', async () => {
  const parent = await mount({ duration: 0 }), child = await mount({ duration: 0 })
  const count = captures.length
  parent.visible.value = true; child.visible.value = true; await flush()
  assert.equal(captures.length, count)
  child.visible.value = false; await flush(); assert.equal(document.documentElement.style.overflow, 'hidden')
  assert.equal(parent.dialog.open, true)
  child.dispose(); parent.dispose(); assert.equal(document.documentElement.style.overflow, '')
})

test('reduced motion, failed snapshot, timeout and unmount all settle without leaked frames or clones', async () => {
  env.setDialogReducedMotion(true)
  const reduced = await mount(); reduced.visible.value = true; await flush(); assert.deepEqual(reduced.events, ['opened']); reduced.dispose()
  env.setDialogReducedMotion(false)
  setMode('failure')
  const failed = await mount(); failed.visible.value = true; await flush(); assert.deepEqual(failed.events, ['opened']); failed.dispose()
  setMode('pending')
  const pending = await mount(); pending.visible.value = true; await flush(); pending.visible.value = false; await flush()
  await new Promise(resolve => setTimeout(resolve, 950)); await flush()
  assert.equal(pending.dialog.open, false); assert.deepEqual(pending.events, ['closed']); pending.dispose()
  const unmounted = await mount(); unmounted.visible.value = true; await flush(); unmounted.dispose()
  for (const resolve of waiting.splice(0)) { const image = document.createElement('canvas'); resolve(image); await flush(); assert.equal(image.width, 0) }
  assert.equal(document.querySelector('[data-mac-dialog-snapshot]'), null)
  assert.equal(env.dialogFrames.size, 0); assert.equal(document.documentElement.style.overflow, '')
  setMode('success')
})

test('destroyOnClose waits for animation; Escape respects beforeClose', async () => {
  let allow = false
  const item = await mount({ destroyOnClose: true, beforeClose: (done: () => void) => { if (allow) done() } })
  item.visible.value = true; await flush(); finishFrames(); await flush()
  item.dialog.dispatchEvent(new Event('cancel', { cancelable: true })); await flush(); assert.equal(item.visible.value, true)
  allow = true; item.dialog.dispatchEvent(new Event('cancel', { cancelable: true })); await flush()
  assert.ok(item.dialog.querySelector('input')); finishFrames(); await flush(); assert.equal(item.dialog.querySelector('input'), null)
  item.dispose()
})
