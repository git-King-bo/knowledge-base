<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
const props = defineProps<{ paused: boolean; travel?: boolean; origin?: { x: number; y: number; scale: number } }>()
const canvas = ref<HTMLCanvasElement>(), ready = ref(false)
let ctx: CanvasRenderingContext2D | null = null
let frame = 0, width = 0, height = 0, time = 0, previous = 0, travelTime = 0, mounted = false
let travelStarted: number | undefined
let pointerX = 0, pointerY = 0, cameraX = 0, cameraY = 0
let resizeObserver: ResizeObserver | undefined, glow: HTMLCanvasElement | undefined
const TAU = Math.PI * 2
const noise = (n: number) => { const v = Math.sin(n * 127.1 + 311.7) * 43758.5453; return v - Math.floor(v) }
const smooth = (n: number) => { const t = Math.max(0, Math.min(1, n)); return t * t * (3 - 2 * t) }
// Each cycle chooses a new brightness, so stars do not pulse in a repeating chorus.
const stars = Array.from({ length: 110 }, (_, i) => ({ x: noise(i), y: noise(i + 200), size: .5 + noise(i + 400) * 1.3, period: 1.8 + noise(i + 600) * 4.5, phase: noise(i + 800) * 10 }))
function source() {
  if (props.origin) return props.origin
  const stage = Math.min(1120, width, height * 1.279)
  return { x: width / 2 - 290 + stage * (500 / 1586 - .335), y: height / 2 + stage * (384 - 496) / 1586, scale: stage / 1586 }
}
function resize() {
  if (!canvas.value || !ctx) return
  const box = canvas.value.getBoundingClientRect(); width = box.width; height = box.height
  if (!width || !height) return
  // The fast-moving tunnel has no text; bound its raster work on high-DPI displays.
  const dpr = Math.min(window.devicePixelRatio || 1, 1.5, Math.sqrt(2_000_000 / (width * height)))
  canvas.value.width = Math.round(width * dpr); canvas.value.height = Math.round(height * dpr)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  glow = document.createElement('canvas'); glow.width = 48; glow.height = 48
  const light = glow.getContext('2d')
  if (light) {
    const ink = light.createRadialGradient(24, 24, 0, 24, 24, 24)
    ink.addColorStop(0, '#fff8e6'); ink.addColorStop(.06, '#ddecff'); ink.addColorStop(.2, '#b7d8ff50'); ink.addColorStop(1, '#91baff00')
    light.fillStyle = ink; light.fillRect(0, 0, 48, 48)
  }
  draw()
}
function draw() {
  if (!ctx || !width || !height) return
  const c = ctx, origin = source(), mobile = width <= 700
  const t = props.travel ? travelTime : 0
  const align = smooth((t - .5) / 1.1)
  const x = origin.x + (width / 2 - origin.x) * align
  const y = origin.y + (height / 2 - origin.y) * align
  c.clearRect(0, 0, width, height)
  // Transparent until the fairy has dissolved. Never paint an opaque panel over her.
  if (props.travel) {
    c.fillStyle = `rgba(3,8,21,${smooth((t - .65) / .65) * .98})`
    c.fillRect(0, 0, width, height)
  }
  if (glow) {
    for (let i = 0; i < stars.length; i++) {
      const star = stars[i]!, clock = (time + star.phase) / star.period, cycle = Math.floor(clock), phase = clock - cycle
      const pulse = Math.sin(phase * Math.PI) ** (5 + noise(i + cycle * 31) * 7)
      const brightness = noise(i + cycle * 173 + 1200)
      c.globalAlpha = (.04 + pulse * brightness * .8) * (1 - smooth(t / 1.2))
      const size = 6 + star.size * 9
      c.drawImage(glow, star.x * width - size / 2 + cameraX * star.size * 4, star.y * height - size / 2 + cameraY * star.size * 3, size, size)
    }
  }
  c.globalAlpha = 1
  if (!props.travel) return
  const arrival = smooth((t - .25) / .65), flight = smooth((t - .65) / 1.2)
  const sourceRadius = origin.scale * 499
  const lens = sourceRadius + (Math.min(width, height) * .48 - sourceRadius) * align
  const distance = Math.max(0, t - .25) ** 2 * .85
  c.globalCompositeOperation = 'lighter'
  const halo = c.createRadialGradient(x, y, 0, x, y, lens * 1.5)
  halo.addColorStop(0, '#b8c5ff12'); halo.addColorStop(.35, '#668aff16'); halo.addColorStop(.7, '#9c72ed12'); halo.addColorStop(1, '#557aff00')
  c.globalAlpha = arrival; c.fillStyle = halo; c.fillRect(0, 0, width, height)
  // The original gold-blue ellipse becomes the mouth of a perspective tunnel.
  for (let i = 0; i < (mobile ? 15 : 24); i++) {
    const depth = .28 + ((i / 24 * 3.6 - distance * .38) % 3.6 + 3.6) % 3.6
    const radius = lens / depth
    if (radius > Math.max(width, height) * 1.8) continue
    c.strokeStyle = i % 3 === 0 ? '#f3cc98' : i % 3 === 1 ? '#98caff' : '#d0bbff'
    c.globalAlpha = arrival * (.12 + .48 / (1 + depth))
    c.lineWidth = 1 + 1.1 / depth
    c.beginPath()
    for (let j = 0; j <= 90; j++) {
      const angle = j / 90 * TAU
      const twist = -.4363 * (1 - align) + t * .11 + i * .025
      const px = Math.cos(angle) * radius, py = Math.sin(angle) * radius * (.443 + .557 * align)
      const dx = px * Math.cos(twist) - py * Math.sin(twist), dy = px * Math.sin(twist) + py * Math.cos(twist)
      if (j === 0) c.moveTo(x + dx, y + dy); else c.lineTo(x + dx, y + dy)
    }
    c.stroke()
  }
  for (let i = 0; i < (mobile ? 180 : 400); i++) {
    const angle = noise(i + 2000) * TAU + t * .045
    const ring = .12 + noise(i + 2400) * 2.2
    const depth = .18 + ((noise(i + 2800) * 4 - distance) % 4 + 4) % 4
    const tail = .006 + flight * .36
    const dx = Math.cos(angle) * ring * lens, dy = Math.sin(angle) * ring * lens
    c.globalAlpha = flight * Math.min(1, (4.18 - depth) * 1.5) * (.3 + noise(i + 3200) * .65)
    c.strokeStyle = i % 5 === 0 ? '#edc999' : i % 7 === 0 ? '#c2b4f3' : '#b8d9ff'
    c.lineWidth = Math.min(3, .65 + .7 / depth)
    c.beginPath(); c.moveTo(x + dx / (depth + tail), y + dy / (depth + tail)); c.lineTo(x + dx / depth, y + dy / depth); c.stroke()
    if (glow && i % 8 === 0) {
      const size = Math.min(32, 9 + 4 / depth); c.drawImage(glow, x + dx / depth - size / 2, y + dy / depth - size / 2, size, size)
    }
  }
  c.globalCompositeOperation = 'source-over'; c.globalAlpha = 1
}
function stop() { cancelAnimationFrame(frame); frame = 0; previous = 0 }
function tick(now: number) {
  frame = 0
  if (props.paused || document.hidden || !mounted) { previous = 0; return }
  const dt = previous ? Math.min((now - previous) / 1000, .05) : 0
  previous = now; time += dt
  if (props.travel) {
    travelStarted ??= now
    travelTime = Math.max(0, (now - travelStarted) / 1000)
  }
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
watch(() => props.travel, () => { travelTime = 0; travelStarted = undefined; resetPointer() })
onMounted(() => {
  try { ctx = canvas.value?.getContext('2d', { alpha: true }) ?? null } catch { ctx = null }
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
  glow = undefined; ctx = null
})
</script>

<template>
  <div class="knowledge-orbit" aria-hidden="true" :data-travelling="travel || undefined" :data-origin-x="origin?.x" :data-origin-y="origin?.y">
    <svg v-if="!ready" class="orbit-fallback" viewBox="0 0 800 600" fill="none">
      <defs><linearGradient id="orbit-fallback-ink"><stop stop-color="#7295a7" /><stop offset="1" stop-color="#efcc9d" /></linearGradient></defs>
      <g transform="translate(400 280) rotate(-22)" stroke="url(#orbit-fallback-ink)"><ellipse v-for="i in 16" :key="i" :rx="115 + i * 6" :ry="45 + i * 2.5" :opacity=".06 + i * .006" stroke-width=".8" /></g>
    </svg>
    <canvas ref="canvas" :class="{ ready }"></canvas>
  </div>
</template>

<style scoped>
.knowledge-orbit { position:absolute; inset:0; overflow:hidden; pointer-events:none; background:transparent; }
.knowledge-orbit canvas { display:block; width:100%; height:100%; opacity:0; }
.knowledge-orbit canvas.ready { opacity:1; }
.orbit-fallback { position:absolute; width:70%; height:85%; left:0; top:0; }
@media(max-width:700px) { .orbit-fallback { width:120%; height:440px; left:5%; } }
</style>
