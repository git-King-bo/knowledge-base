import type { Ref } from 'vue'

export type Origin = Element | { $el?: Element } | Ref<unknown> | (() => unknown) | null | undefined
export type Box = { left: number; top: number; width: number; height: number }
export const clamp = (v: number) => Math.max(0, Math.min(1, v))
const smooth = (v: number) => { const t = clamp(v); return t * t * (3 - 2 * t) }
const mix = (a: number, b: number, t: number) => a + (b - a) * t

export function originBox(origin: Origin): Box | undefined {
  try {
    let value: unknown = origin
    const seen = new Set<unknown>()
    while (value && !seen.has(value)) {
      seen.add(value)
      if (value instanceof Element) {
        const style = getComputedStyle(value)
        const r = value.getBoundingClientRect()
        if (!value.isConnected || !value.getClientRects().length || style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0 || r.width <= 0 || r.height <= 0) return
        for (let parent = value.parentElement; parent; parent = parent.parentElement) {
          if (Number(getComputedStyle(parent).opacity) === 0) return
        }
        return { left: r.left, top: r.top, width: r.width, height: r.height }
      }
      if (typeof value === 'function') value = value()
      else if (typeof value === 'object' && 'value' in value) value = value.value
      else if (typeof value === 'object' && '$el' in value) value = value.$el
      else return
    }
  } catch { /* A stale template ref or user resolver is an invalid target. */ }
}

export function bottomBox(dockX: number, width = innerWidth, height = innerHeight): Box {
  return { left: clamp(Number.isFinite(dockX) ? dockX : .5) * (width - 48), top: height - 4, width: 48, height: 4 }
}

export type GeniePath = ReturnType<typeof createGeniePath>

/** Freeze this geometry for both directions of a reversible animation. */
export function createGeniePath(source: Box, target: Box) {
  const dx = target.left + target.width / 2 - source.left - source.width / 2
  const dy = target.top + target.height / 2 - source.top - source.height / 2
  const horizontal = Math.abs(dx) > Math.abs(dy)
  const axis = (box: Box) => horizontal
    ? { start: box.left, length: box.width, center: box.top + box.height / 2, breadth: box.height }
    : { start: box.top, length: box.height, center: box.left + box.width / 2, breadth: box.width }
  const from = axis(source), to = axis(target)
  const distance = Math.hypot(dx, dy)
  // Center distances within 0.2–0.8 window lengths gradually soften the neck.
  // Far, vertically centered docks retain the original .48/.24 timing.
  const proximity = 1 - smooth((distance / Math.max(1, from.length / 2) - .4) / 1.2)
  const lateral = distance ? smooth(Math.abs(dx) / distance) : 0
  const softness = Math.max(proximity, lateral)
  return {
    horizontal, from, to, softness,
    positive: (horizontal ? dx : dy) >= 0,
    neckEnd: mix(.48, .72, softness),
    followStart: mix(.24, .10, softness),
    fadeStart: mix(.94, .88, softness),
  }
}

export function genieOpacity(path: GeniePath, progress: number) {
  return 1 - smooth((progress - path.fadeStart) / (1 - path.fadeStart))
}

/** Axis position is affine in band index, so its derivative is always positive:
 * (1 - travel) * sourceLength + travel * targetLength. This also holds inside
 * the dialog and for targets behind either edge; no band can cross another.
 */
export function genieBand(path: GeniePath, band: number, progress: number) {
  const p = clamp(progress) // 0 = real window, 1 = target
  const { from, to } = path
  const near = path.positive ? band : 1 - band
  const travel = smooth((p - path.followStart) / (1 - path.followStart))
  const neck = smooth(p / path.neckEnd) * smooth(near) * (1 - travel) + travel
  // A shared center trajectory reduces sideways bending without removing the
  // S-shaped neck. Both terms have exact 0/1 endpoints and zero end velocity.
  const centerTravel = mix(neck, smooth(p), path.softness * .55)
  return {
    position: mix(from.start + band * from.length, to.start + band * to.length, travel),
    cross: mix(from.center, to.center, centerTravel) - mix(from.breadth, to.breadth, neck) / 2,
    breadth: mix(from.breadth, to.breadth, neck),
  }
}

export function drawGenie(ctx: CanvasRenderingContext2D, snapshot: HTMLCanvasElement, source: Box, target: Box, progress: number) {
  ctx.clearRect(0, 0, innerWidth, innerHeight)
  const path = createGeniePath(source, target)
  // Fade the composited canvas, not individual overlapping strips (which
  // would create dark seams as alpha decreases).
  ctx.canvas.style.opacity = String(genieOpacity(path, progress))
  const bands = Math.ceil(path.from.length * 1.5)
  const end = genieBand(path, 1, progress).position
  for (let i = 0; i < bands; i++) {
    const a = genieBand(path, i / bands, progress)
    const b = genieBand(path, (i + 1) / bands, progress)
    const length = Math.min(b.position + .35, end) - a.position
    if (path.horizontal) {
      // Vertical source columns: x is the ordered motion axis, y narrows.
      ctx.drawImage(snapshot, i * snapshot.width / bands, 0, snapshot.width / bands, snapshot.height,
        a.position, a.cross, length, a.breadth)
    } else {
      // Horizontal source rows: y is the ordered motion axis, x narrows.
      ctx.drawImage(snapshot, 0, i * snapshot.height / bands, snapshot.width, snapshot.height / bands,
        a.cross, a.position, a.breadth, length)
    }
  }
}

let locks = 0
let savedOverflow = ''
export function lockScroll() {
  if (!locks++) { savedOverflow = document.documentElement.style.overflow; document.documentElement.style.overflow = 'hidden' }
  let released = false
  return () => { if (!released) { released = true; if (!--locks) document.documentElement.style.overflow = savedOverflow } }
}
