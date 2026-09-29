<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(defineProps<{ autoplay?: boolean }>(), { autoplay: true })
const emit = defineEmits<{ phase: [value: 'idle' | 'playing' | 'revealing'] }>()
const active = ref(false)
const ready = ref(false)
const revealing = ref(false)
const dialog = ref<HTMLDialogElement>()
const mascot = ref<HTMLImageElement>()
let media: MediaQueryList | undefined
let timers: ReturnType<typeof setTimeout>[] = []
let generation = 0
let dead = false
let previousOverflow = ''
let scrollLocked = false
let previousFocus: HTMLElement | null = null

function finish() {
  const token = ++generation
  timers.forEach(clearTimeout)
  timers = []
  dialog.value?.close()
  if (scrollLocked) { document.body.style.overflow = previousOverflow; scrollLocked = false }
  active.value = false
  ready.value = false
  revealing.value = false
  emit('phase', 'idle')
  void nextTick(() => {
    if (!dead && token === generation && previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
  })
}

async function play() {
  if (dead || active.value || media?.matches) return
  const token = ++generation
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  active.value = true
  ready.value = false
  revealing.value = false
  emit('phase', 'playing')
  await nextTick()
  if (dead || token !== generation) return
  previousOverflow = document.body.style.overflow
  scrollLocked = true
  document.body.style.overflow = 'hidden'
  try { dialog.value?.showModal() } catch { finish(); return }
  // Never hold the workspace behind a failed or slow image download.
  timers.push(setTimeout(finish, 1800))
  try { await mascot.value?.decode() } catch { if (token === generation) finish(); return }
  if (dead || token !== generation) return
  timers.forEach(clearTimeout)
  timers = []
  ready.value = true
  timers.push(setTimeout(() => {
    revealing.value = true
    emit('phase', 'revealing')
  }, 1450))
  timers.push(setTimeout(finish, 4650))
}

function motionChanged() { if (media?.matches && active.value) finish() }
onMounted(() => {
  media = matchMedia('(prefers-reduced-motion: reduce)')
  media.addEventListener('change', motionChanged)
  if (props.autoplay) void play()
})
onBeforeUnmount(() => { dead = true; finish(); media?.removeEventListener('change', motionChanged) })
defineExpose({ play })
</script>

<template>
  <Teleport to="body">
    <dialog v-if="active" ref="dialog" class="magic-entrance" :class="{ 'is-ready': ready, 'is-revealing': revealing }" aria-label="知识精灵开屏动画" aria-describedby="entrance-caption" @cancel.prevent="finish">
      <div class="entrance-veil" aria-hidden="true" />
      <div class="entrance-mist mist-rose" aria-hidden="true" />
      <div class="entrance-mist mist-blue" aria-hidden="true" />
      <div class="entrance-dust" aria-hidden="true">
        <i v-for="i in 28" :key="i" :style="{ '--dust-x': `${20 + (i * 37 % 63)}%`, '--dust-y': `${21 + (i * 23 % 56)}%`, '--dust-delay': `${(i % 7) * .09}s`, '--dust-drift': `${45 + i * 4}px`, '--dust-rise': `${-35 - (i % 6) * 20}px` }" />
      </div>
      <div class="entrance-content">
        <span class="entrance-eyebrow">A LITTLE KNOWLEDGE MAGIC</span>
        <div class="entrance-stage" aria-hidden="true">
          <div class="entrance-orbit orbit-back" /><div class="entrance-orbit orbit-front" />
          <div class="entrance-fairy">
            <img ref="mascot" src="/mascot/knowledge-fairy.webp" alt="" width="616" height="640" fetchpriority="high" />
            <span class="entrance-wand-light" />
          </div>
          <svg class="entrance-trail" viewBox="0 0 400 360" fill="none">
            <defs><linearGradient id="entrance-starlight" x1="70" y1="130" x2="355" y2="220" gradientUnits="userSpaceOnUse"><stop stop-color="#fff0cd" /><stop offset=".45" stop-color="#efcfdf" /><stop offset="1" stop-color="#b2dce5" /></linearGradient></defs>
            <path class="trail-glow" pathLength="1" d="M112 132 C60 66 336 51 341 139 C346 223 112 253 83 203 C45 137 329 133 361 235" />
            <path class="trail-core" pathLength="1" d="M112 132 C60 66 336 51 341 139 C346 223 112 253 83 203 C45 137 329 133 361 235" />
          </svg>
          <span v-for="(star, i) in [{ x: 23, y: 28 }, { x: 49, y: 19 }, { x: 76, y: 24 }, { x: 84, y: 42 }, { x: 66, y: 60 }, { x: 35, y: 65 }, { x: 20, y: 55 }, { x: 88, y: 67 }]" :key="i" class="entrance-star" :style="{ left: `${star.x}%`, top: `${star.y}%`, '--star-delay': `${.95 + i * .09}s`, '--star-turn': `${i % 2 ? 24 : -24}deg` }">{{ i % 3 ? '✦' : '✧' }}</span>
          <span class="entrance-ground" />
        </div>
        <h2>让灵感，轻轻发生。</h2>
        <p id="entrance-caption">一挥魔法，开启你的知识世界</p>
        <span class="entrance-dots" aria-hidden="true"><i /><i /><i /></span>
      </div>
      <button class="entrance-skip" type="button" autofocus @click="finish">跳过动画 <span>Esc</span></button>
    </dialog>
  </Teleport>
</template>

<style>
@property --entrance-melt { syntax: '<percentage>'; inherits: false; initial-value: -35%; }
.magic-entrance { position: fixed; inset: 0; width: 100%; height: 100%; max-width: none; max-height: none; border: 0; padding: 0; margin: 0; color: #637c89; background: transparent; overflow: hidden; }
.magic-entrance[open] { display: grid; place-items: center; }
.magic-entrance::backdrop { background: transparent; }
.entrance-veil { position: absolute; inset: 0; background: radial-gradient(ellipse at 24% 22%, #eed5de9c, transparent 52%), radial-gradient(ellipse at 80% 25%, #c1dce09c, transparent 55%), linear-gradient(150deg, #f7f1ea, #edf3ee 60%, #e9e6f1); }
.entrance-content { position: relative; width: min(460px, 92vw); text-align: center; padding-bottom: 30px; pointer-events: none; }
.entrance-eyebrow { display: block; color: #8f9fa6; font-size: 9px; letter-spacing: 3px; opacity: 0; }
.entrance-stage { position: relative; width: min(400px, 88vw); height: min(360px, 79.2vw); margin: 15px auto 0; }
.entrance-fairy { position: absolute; inset: 3% 10% 6%; opacity: 0; transform-origin: 48% 65%; }
.entrance-fairy img { display: block; width: 100%; height: 100%; object-fit: contain; filter: drop-shadow(0 14px 17px #8c7e8720); }
.entrance-wand-light { position: absolute; width: 16%; aspect-ratio: 1; left: 17%; top: 24%; border-radius: 50%; background: radial-gradient(circle, #fffdf2, #fff1d699 18%, #ffedc82e 48%, transparent 70%); opacity: 0; }
.entrance-orbit { position: absolute; inset: 9% 12% 8%; border: 1px solid #fffdfab3; border-radius: 50%; transform: rotate(-24deg) scaleY(.7); opacity: 0; }
.orbit-back { box-shadow: 0 0 0 20px #ffffff15, 0 0 0 40px #ffffff0b; }
.orbit-front { inset: 23% 3% 14%; transform: rotate(22deg) scaleY(.67); border-color: #cab9c933; }
.entrance-trail { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.entrance-trail path { stroke: url(#entrance-starlight); stroke-linecap: round; stroke-dasharray: 1; stroke-dashoffset: 1; }
.trail-glow { stroke-width: 8px; filter: blur(5px); }.trail-core { stroke-width: 1.7px; }
.entrance-star { position: absolute; color: #fff9e4; opacity: 0; font-size: 17px; text-shadow: 0 0 9px #e9cbb7b3; }
.entrance-star:nth-of-type(3n) { color: #d4c0d0; font-size: 11px; }
.entrance-ground { position: absolute; left: 31%; right: 28%; bottom: 3%; height: 14px; border-radius: 50%; background: #8ea7b52b; filter: blur(10px); opacity: 0; }
.entrance-content h2 { color: #677c8a; font-size: 25px; font-weight: 500; letter-spacing: 3px; margin: 10px 0; opacity: 0; }
.entrance-content p { color: #8d9da6; font-size: 12px; letter-spacing: 1px; opacity: 0; }
.entrance-dots { display: flex; justify-content: center; gap: 7px; margin-top: 24px; opacity: 0; }
.entrance-dots i { width: 4px; height: 4px; background: #b8cad0; border-radius: 50%; }.entrance-dots i:nth-child(2) { background: #d7bdca; }.entrance-dots i:nth-child(3) { background: #dbceba; }
button.entrance-skip { position: absolute; right: max(28px, env(safe-area-inset-right)); bottom: max(25px, env(safe-area-inset-bottom)); border-radius: 20px; background: #ffffff85; border: 1px solid #ffffffb3; color: #6c8592; box-shadow: none; font-size: 11px; padding: 9px 15px; }
.entrance-skip span { border: 1px solid #d3e0e5; border-radius: 5px; padding: 1px 4px; font-size: 9px; color: #8a9faa; }
.is-ready .entrance-fairy { animation: fairy-arrive .7s cubic-bezier(.2,.7,.3,1) both, fairy-cast 1.85s .6s ease-in-out forwards; }
.is-ready .entrance-wand-light { animation: wand-bloom 1.85s .6s ease-in-out both; }
.is-ready .entrance-trail path { animation: starlight-draw 1.85s .7s cubic-bezier(.36,.06,.4,1) both; }
.is-ready .entrance-star { animation: starlight-mote 1.45s var(--star-delay) ease-out both; }
.is-ready .entrance-orbit, .is-ready .entrance-ground { animation: entrance-opacity 1s .15s both; }
.is-ready .entrance-eyebrow { animation: entrance-text .8s .15s both; }
.is-ready .entrance-content h2 { animation: entrance-text .8s .45s both; }
.is-ready .entrance-content p, .is-ready .entrance-dots { animation: entrance-text .8s .65s both; }
/* The two scenes overlap for the entire dissolve, rather than a circular wipe. */
.entrance-mist { position: absolute; inset: -15%; pointer-events: none; opacity: 0; }
.mist-rose { background: radial-gradient(ellipse at 35% 48%, #f6e1e4b3, transparent 48%); }
.mist-blue { background: radial-gradient(ellipse at 64% 50%, #d4e9e9aa, transparent 46%); }
.entrance-dust { position: absolute; inset: 0; pointer-events: none; }
.entrance-dust i { position: absolute; left: var(--dust-x); top: var(--dust-y); width: 3px; height: 3px; opacity: 0; border-radius: 50%; background: #fffae7; box-shadow: 0 0 7px 2px #ead6b866; }
.entrance-dust i:nth-child(3n) { width: 5px; height: 5px; background: #e4cddc; }
.entrance-dust i:nth-child(4n) { background: #c6e0e5; }
.magic-entrance.is-revealing .entrance-veil { animation: veil-dissolve 3.05s ease-in-out both; }
.magic-entrance.is-revealing .mist-rose { animation: mist-drift 3.1s ease-out both; }
.magic-entrance.is-revealing .mist-blue { animation: mist-drift 2.9s .12s ease-out both; animation-direction: reverse; }
.magic-entrance.is-revealing .entrance-dust i { animation: dust-disperse 2.5s var(--dust-delay) ease-out both; }
.magic-entrance.is-revealing .entrance-fairy img { animation: fairy-melt 2.7s .25s ease-in-out both; }
.magic-entrance.is-revealing .entrance-content { animation: fairy-depart 3s ease-in-out both; }
.magic-entrance.is-revealing .entrance-skip { animation: fairy-depart 3s ease-in both; }
@supports (mask-image: linear-gradient(120deg, transparent, black)) {
  .magic-entrance.is-revealing .entrance-fairy img {
    mask-image: linear-gradient(120deg, transparent calc(var(--entrance-melt) - 22%), #000 calc(var(--entrance-melt) + 22%));
    animation: fairy-melt 2.7s .25s ease-in-out both, fairy-erosion 2.7s .25s ease-in-out both;
  }
}
.app-shell.entrance-playing { opacity: 0; }
.app-shell.entrance-revealing { animation: workspace-awaken 3.1s ease-in-out both; }
.entrance-revealing .sidebar { animation: workspace-piece 2.7s .1s ease-out both; }
.entrance-revealing .topbar { animation: workspace-piece 2.7s .2s ease-out both; }
.entrance-revealing main { animation: workspace-piece 2.7s .3s ease-out both; }
button.magic-replay { background: #fffdf566; box-shadow: none; border-color: #ffffff90; color: #8b8296; font-size: 11px; min-height: 32px; border-radius: 20px; padding: 6px 11px; }
@keyframes fairy-arrive { from { opacity: 0; transform: translateY(18px) scale(.94); } to { opacity: 1; transform: translateY(0) scale(1); } }
@keyframes fairy-cast { 0% { transform: rotate(0); } 28% { transform: translate(-7px, -4px) rotate(-12deg); } 66% { transform: translate(9px, -9px) rotate(10deg); } 100% { transform: translate(3px, -3px) rotate(2deg); } }
@keyframes wand-bloom { 0% { opacity: .2; transform: scale(.5); } 50% { opacity: 1; transform: scale(2); } 100% { opacity: .35; transform: scale(1.4); } }
@keyframes starlight-draw { 0% { stroke-dashoffset: 1; opacity: 0; } 15% { opacity: .9; } 80% { opacity: 1; } 100% { stroke-dashoffset: 0; opacity: .3; } }
@keyframes starlight-mote { 0% { opacity: 0; transform: translateY(5px) scale(.3); } 25% { opacity: 1; transform: translateY(0) scale(1); } 100% { opacity: 0; transform: translateY(-22px) rotate(var(--star-turn)) scale(.4); } }
@keyframes entrance-text { from { opacity: 0; transform: translateY(7px); } to { opacity: 1; transform: translateY(0); } }
@keyframes entrance-opacity { from { opacity: 0; } to { opacity: 1; } }
@keyframes veil-dissolve { 0% { opacity: 1; } 22% { opacity: .9; } 55% { opacity: .45; } 82% { opacity: .12; } 100% { opacity: 0; } }
@keyframes fairy-depart { 0%, 15% { opacity: 1; } 55% { opacity: .68; } 100% { opacity: 0; transform: translate(14px, -18px); } }
@keyframes fairy-melt { 0%, 12% { opacity: 1; filter: drop-shadow(0 14px 17px #8c7e8720); } 55% { opacity: .72; filter: drop-shadow(0 0 12px #fff1da70) blur(1px); } 100% { opacity: 0; filter: blur(5px); } }
@keyframes fairy-erosion { from { --entrance-melt: -35%; } to { --entrance-melt: 125%; } }
@keyframes mist-drift { 0% { opacity: 0; transform: translate(-3%, 2%) scale(.94); } 30% { opacity: .7; } 100% { opacity: 0; transform: translate(6%, -4%) scale(1.12); } }
@keyframes dust-disperse { 0% { opacity: 0; transform: translate(0, 0) scale(.5); } 20% { opacity: .85; } 65% { opacity: .5; } 100% { opacity: 0; transform: translate(var(--dust-drift), var(--dust-rise)) scale(.15); } }
@keyframes workspace-awaken { 0% { opacity: 0; } 30% { opacity: .32; } 65% { opacity: .82; } 100% { opacity: 1; } }
@keyframes workspace-piece { from { opacity: .45; translate: 0 6px; } to { opacity: 1; translate: 0 0; } }
@media (max-width: 640px) { .entrance-content h2 { font-size: 22px; }.entrance-eyebrow { font-size: 7px; letter-spacing: 2px; }.entrance-skip { right: 20px; bottom: 22px; }.magic-replay span { display: none; } }
@media (max-height: 600px) { .entrance-stage { width: 260px; height: 234px; }.entrance-content { padding-bottom: 0; }.entrance-content h2 { font-size: 20px; }.entrance-dots { margin-top: 14px; } }
@media (prefers-reduced-motion: reduce) { .magic-entrance { display: none !important; }.app-shell.entrance-playing, .app-shell.entrance-revealing { opacity: 1; animation: none; }button.magic-replay { display: none; } }
</style>
