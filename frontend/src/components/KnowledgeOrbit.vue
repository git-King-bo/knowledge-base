<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
const props = defineProps<{ paused: boolean; travel?: boolean }>()
const canvas = ref<HTMLCanvasElement>(), ready = ref(false)
let ctx: CanvasRenderingContext2D | null = null
let frame = 0, width = 0, height = 0, time = 0, previous = 0
let pointerX = 0, pointerY = 0, cameraX = 0, cameraY = 0, mounted = false
let resizeObserver: ResizeObserver | undefined, field: HTMLCanvasElement | undefined, orbitInk: CanvasGradient | undefined
let starGlow: HTMLCanvasElement | undefined
let travelTime = 0
const smooth = (value: number) => { const t = Math.max(0, Math.min(1, value)); return t * t * (3 - 2 * t) }
const TAU = Math.PI * 2
// Deterministic points preserve the composition on resize and in the static version.
const noise = (n: number) => { const v = Math.sin(n * 127.1 + 311.7) * 43758.5453; return v - Math.floor(v) }
const stars = Array.from({ length: 130 }, (_, i) => ({ x: noise(i), y: noise(i + 200), size: .4 + noise(i + 400) * 1.2 }))
function geometry() {
  const mobile = width <= 700
  return { x: width * (mobile ? .63 : .335), y: mobile ? 185 : height * .44,
    radius: mobile ? Math.min(width * .66, 270) : Math.min(width * .285, height * .43, 430), mobile }
}
function resize() {
  if (!canvas.value || !ctx) return
  const box = canvas.value.getBoundingClientRect()
  width = box.width; height = box.height
  if (!width || !height) return
  const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
  canvas.value.width = Math.round(width * dpr); canvas.value.height = Math.round(height * dpr)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  const { x, y, radius } = geometry()
  field = document.createElement('canvas')
  field.width = canvas.value.width; field.height = canvas.value.height
  const background = field.getContext('2d')
  if (background) {
    background.scale(dpr, dpr)
    const halo = background.createRadialGradient(x, y, radius * .15, x, y, radius * 1.5)
    halo.addColorStop(0, '#122431'); halo.addColorStop(.42, '#182027'); halo.addColorStop(1, '#080d13')
    background.fillStyle = halo; background.fillRect(0, 0, width, height)
    const rim = background.createRadialGradient(x + radius * .3, y + radius * .23, 0, x + radius * .3, y + radius * .23, radius * .85)
    rim.addColorStop(0, 'rgba(190,139,82,.07)'); rim.addColorStop(1, 'rgba(190,139,82,0)')
    background.fillStyle = rim; background.fillRect(0, 0, width, height)
    for (const star of stars) {
      background.fillStyle = `rgba(190,210,226,${.15 + star.size * .22})`
      background.beginPath(); background.arc(star.x * width, star.y * height, star.size * .6, 0, TAU); background.fill()
    }
  }
  // Cache a tiny light sprite: the depth layer adds no per-frame gradients or blurs.
  starGlow = document.createElement('canvas'); starGlow.width = 48; starGlow.height = 48
  const light = starGlow.getContext('2d')
  if (light) {
    const glow = light.createRadialGradient(24, 24, 0, 24, 24, 24)
    glow.addColorStop(0, '#f8eee0'); glow.addColorStop(.08, '#d8e5efb0')
    glow.addColorStop(.22, '#b5d4ed24'); glow.addColorStop(1, '#b5d4ed00')
    light.fillStyle = glow; light.fillRect(0, 0, 48, 48)
  }
  orbitInk = ctx.createLinearGradient(x - radius, y - radius * .4, x + radius, y + radius * .4)
  orbitInk.addColorStop(0, '#638a9e'); orbitInk.addColorStop(.27, '#b4cbd0'); orbitInk.addColorStop(.52, '#e4c39a')
  orbitInk.addColorStop(.78, '#ffdfad'); orbitInk.addColorStop(1, '#bd8153')
  draw()
}
function draw() {
  if (!ctx || !width || !height) return
  const c = ctx, base = geometry(), { mobile } = base
  const progress = props.travel ? Math.min(travelTime / 3.8, 1) : 0
  const align = smooth(progress / .55), dissolve = smooth((progress - .3) / .4)
  const centerX = base.x + (width / 2 - base.x) * align
  const centerY = base.y + (height / 2 - base.y) * align
  const radius = base.radius * (1 + progress * progress * 3)
  c.clearRect(0, 0, width, height)
  c.fillStyle = '#080d13'; c.fillRect(0, 0, width, height)
  c.globalAlpha = 1 - dissolve
  if (field) c.drawImage(field, 0, 0, width, height)
  if (starGlow) {
    for (let i = 0; i < (mobile ? 10 : 22); i++) {
      const depth = .3 + noise(i + 4000) * .7
      const x = noise(i + 4100) * width + cameraX * depth * 18
      const y = noise(i + 4200) * height + cameraY * depth * 12
      const size = 10 + depth * 15
      c.globalAlpha = (1 - dissolve) * (.24 + depth * .2 + Math.sin(time * .55 + i * 2.3) * .10)
      c.drawImage(starGlow, x - size / 2, y - size / 2, size, size)
    }
  }
  c.globalAlpha = 1
  const tilt = (-.38 + cameraX * .075 + Math.sin(time * .085) * .04) * (1 - align)
  const pitch = (.48 + cameraY * .12 + Math.sin(time * .12) * .07) * (1 - align) + align
  const cos = Math.cos(tilt), sin = Math.sin(tilt)
  function point(angle: number, band: number) {
    const r = radius * (.40 + band * .66)
    const wave = Math.sin(angle * 3 + band * 5 - time * .25) * radius * .035 * band
    const px = Math.cos(angle) * (r + wave), depth = Math.sin(angle) * r
    const py = depth * pitch + Math.sin(angle * 2 + band * 3 + time * .18) * radius * .045
    const perspective = 1 + depth / (radius * 5)
    return { x: centerX + (px * cos - py * sin) * perspective + cameraX * 13,
      y: centerY + (px * sin + py * cos) * perspective + cameraY * 9 }
  }
  // Filaments form a warped archive disc; camera drift and light packets have independent velocities.
  c.strokeStyle = orbitInk ?? '#dcc29e'
  const bands = mobile ? 28 : 48, steps = mobile ? 100 : 150
  for (let band = 0; band < bands; band++) {
    const b = band / (bands - 1)
    c.globalAlpha = (.14 + Math.sin(b * Math.PI) * .30) * (1 - dissolve)
    c.lineWidth = band % 8 === 0 ? 1.15 : .55
    c.shadowColor = '#e7ba83'; c.shadowBlur = band === 15 || band === 32 ? 9 : 0
    c.beginPath()
    for (let step = 0; step <= steps; step++) {
      const p = point(step / steps * TAU, b)
      if (step === 0) c.moveTo(p.x, p.y); else c.lineTo(p.x, p.y)
    }
    c.stroke()
  }
  c.shadowBlur = 0
  // Short local streaks keep the illuminated edge crisp without full-frame blur.
  c.globalCompositeOperation = 'lighter'
  for (let i = 0; i < (mobile ? 40 : 90); i++) {
    const band = noise(i + 700), angle = noise(i + 800) * TAU + time * (.055 + noise(i + 900) * .11)
    const tail = .008 + noise(i + 1000) * .055
    c.globalAlpha = (.24 + noise(i + 1100) * .6) * (1 - dissolve); c.lineWidth = i % 7 === 0 ? 1.8 : .9; c.beginPath()
    for (let j = 0; j <= 5; j++) {
      const p = point(angle - tail + tail * j / 5, band)
      if (j === 0) c.moveTo(p.x, p.y); else c.lineTo(p.x, p.y)
    }
    c.stroke()
    if (i % 7 === 0) {
      const p = point(angle, band)
      c.fillStyle = '#ffe9c5'; c.beginPath(); c.arc(p.x, p.y, 1.3, 0, TAU); c.fill()
    }
  }
  // Discrete sheets enter the same orbits: information becoming connected.
  for (let i = 0; i < (mobile ? 9 : 18); i++) {
    const angle = noise(i + 1400) * TAU + time * .075
    const p = point(angle, 1.12 + noise(i + 1500) * .20)
    c.save(); c.translate(p.x, p.y); c.rotate(angle + tilt)
    c.globalAlpha = (.12 + noise(i + 1600) * .22) * (1 - dissolve); c.strokeStyle = '#e7d7bb'; c.lineWidth = .7
    const size = 3 + noise(i + 1700) * 5
    c.strokeRect(-size / 2, -size, size, size * 1.4); c.restore()
  }
  c.globalCompositeOperation = 'source-over'; c.globalAlpha = 1
  if (progress > 0) {
    // Perspective projection: stars approach the camera, then wrap behind the vanishing point.
    const arrival = smooth(progress / .45), distance = travelTime * .08 + travelTime ** 3 * .09
    const lens = Math.min(width, height) * .55
    for (let i = 0; i < (mobile ? 160 : 340); i++) {
      const angle = noise(i + 2000) * TAU + progress * .12
      const ring = .15 + noise(i + 2400) * 2.1
      const z = .16 + ((noise(i + 2800) * 4 - distance) % 4 + 4) % 4
      const tail = .004 + progress * progress * .24
      const dx = Math.cos(angle) * ring * lens, dy = Math.sin(angle) * ring * lens
      const x = centerX + dx / z, y = centerY + dy / z
      c.globalAlpha = arrival * Math.min(1, (4.16 - z) * 1.5) * (.3 + noise(i + 3200) * .65)
      c.strokeStyle = i % 5 === 0 ? '#edc999' : '#c3dce9'
      c.lineWidth = Math.min(2.6, .55 + .5 / z)
      c.beginPath(); c.moveTo(centerX + dx / (z + tail), centerY + dy / (z + tail)); c.lineTo(x, y); c.stroke()
    }
    c.globalAlpha = 1
  }
}
function stop() { cancelAnimationFrame(frame); frame = 0; previous = 0 }
function tick(now: number) {
  frame = 0
  if (props.paused || document.hidden || !mounted) { previous = 0; return }
  const dt = previous ? Math.min((now - previous) / 1000, .05) : 0
  previous = now; time += dt
  if (props.travel) travelTime += dt
  const weight = 1 - Math.exp(-5 * dt)
  cameraX += (pointerX - cameraX) * weight; cameraY += (pointerY - cameraY) * weight
  draw(); frame = requestAnimationFrame(tick)
}
function syncPlayback() { stop(); if (mounted && ctx && !props.paused && !document.hidden) frame = requestAnimationFrame(tick) }
function move(event: PointerEvent) {
  if (props.paused || event.pointerType === 'touch') return
  pointerX = (event.clientX / window.innerWidth - .5) * 2; pointerY = (event.clientY / window.innerHeight - .5) * 2
}
function resetPointer() { pointerX = 0; pointerY = 0 }
watch(() => props.paused, syncPlayback)
watch(() => props.travel, () => { travelTime = 0; resetPointer() })
onMounted(() => {
  try { ctx = canvas.value?.getContext('2d', { alpha: false }) ?? null } catch { ctx = null }
  // Canvas is an enhancement: unsupported contexts keep the SVG artwork and working form.
  if (!ctx || typeof ctx.createRadialGradient !== 'function') { ctx = null; return }
  mounted = true; resize(); ready.value = true
  if (typeof ResizeObserver !== 'undefined') { resizeObserver = new ResizeObserver(resize); resizeObserver.observe(canvas.value!) }
  window.addEventListener('resize', resize); window.addEventListener('pointermove', move, { passive: true })
  document.documentElement.addEventListener('pointerleave', resetPointer)
  document.addEventListener('visibilitychange', syncPlayback); syncPlayback()
})
onUnmounted(() => {
  mounted = false; stop(); resizeObserver?.disconnect()
  window.removeEventListener('resize', resize); window.removeEventListener('pointermove', move)
  document.documentElement.removeEventListener('pointerleave', resetPointer)
  document.removeEventListener('visibilitychange', syncPlayback)
  field = undefined; starGlow = undefined; orbitInk = undefined; ctx = null
})
</script>

<template>
  <div class="knowledge-orbit" aria-hidden="true">
    <svg v-if="!ready" class="orbit-fallback" viewBox="0 0 800 600" fill="none">
      <defs><linearGradient id="orbit-fallback-ink"><stop stop-color="#7295a7" /><stop offset="1" stop-color="#efcc9d" /></linearGradient></defs>
      <g transform="translate(400 280) rotate(-22)" stroke="url(#orbit-fallback-ink)">
        <ellipse v-for="i in 28" :key="i" :rx="115 + i * 6" :ry="45 + i * 2.5" :opacity=".12 + i * .012" stroke-width=".8" />
      </g>
    </svg>
    <canvas ref="canvas" :class="{ ready }"></canvas>
  </div>
</template>

<style scoped>
.knowledge-orbit { position:absolute; inset:0; z-index:-2; overflow:hidden; pointer-events:none; background:#080d13; }
.knowledge-orbit canvas { display:block; width:100%; height:100%; opacity:0; }
.knowledge-orbit canvas.ready { opacity:1; }
.orbit-fallback { position:absolute; width:70%; height:85%; left:0; top:0; }
@media (max-width:700px) { .orbit-fallback { width:120%; height:440px; left:5%; } }
</style>
