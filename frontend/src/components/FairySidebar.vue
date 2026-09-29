<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()
const moving = ref(false)
const failed = ref(false)
const motionCycle = ref(0)
const sparks = [
  { x: 24, y: -42, delay: 0 }, { x: 46, y: -22, delay: 45 },
  { x: 58, y: 12, delay: 90 }, { x: 32, y: 38, delay: 30 },
  { x: -18, y: -32, delay: 65 }, { x: -26, y: 22, delay: 110 },
]
let settleTimer: ReturnType<typeof setTimeout> | undefined
watch(() => props.open, () => {
  motionCycle.value += 1
  moving.value = true
  clearTimeout(settleTimer)
  settleTimer = setTimeout(() => { moving.value = false }, 940)
})
onMounted(() => { for (const pose of ['push', 'pull']) { const image = document.createElement('img'); image.src = `/mascot/fairy-door-${pose}.png` } })
onBeforeUnmount(() => clearTimeout(settleTimer))
</script>
<template>
  <div class="fairy-sidebar" :class="{ 'is-closed': !open, 'is-moving': moving }">
    <div id="fairy-sidebar-door" class="fairy-sidebar-door" :inert="open ? undefined : true" :aria-hidden="!open">
      <div class="fairy-sidebar-panel"><slot /></div>
    </div>
    <span v-if="moving" :key="`edge-${motionCycle}`" class="fairy-edge-flare" aria-hidden="true" />
    <button class="fairy-door-handle" type="button" :aria-label="open ? '收起问答侧栏' : '展开问答侧栏'" :aria-expanded="open" aria-controls="fairy-sidebar-door" :title="open ? '精灵帮你收起侧栏' : '精灵帮你展开侧栏'" @click="emit('update:open', !open)">
      <span class="fairy-door-light" aria-hidden="true" />
      <span v-if="moving" :key="motionCycle" class="fairy-magic-burst" aria-hidden="true">
        <span class="fairy-magic-ring" />
        <i v-for="(spark, index) in sparks" :key="index" class="fairy-magic-spark" :style="{ '--spark-x': `${spark.x}px`, '--spark-y': `${spark.y}px`, '--spark-delay': `${spark.delay}ms` }">✦</i>
      </span>
      <span v-if="!failed" class="fairy-door-art" aria-hidden="true">
      <img :key="motionCycle" class="fairy-door-sprite" :src="open ? '/mascot/fairy-door-push.png' : '/mascot/fairy-door-pull.png'" alt="" draggable="false" @error="failed = true" />
      </span>
      <span v-else class="fairy-door-fallback"><AppIcon :name="open ? 'back' : 'arrow'" :size="22" /></span>
      <span class="fairy-door-caption">{{ open ? '收起' : '展开' }}</span>
    </button>
  </div>
</template>
<style scoped>
.fairy-sidebar { position: relative; min-width: 0; min-height: 0; height: 100%; isolation: isolate; }
/* The panel and palm share the same moving edge throughout the grid transition. */
.fairy-sidebar-door { width: calc(100% - var(--qa-fairy-space)); height: 100%; min-height: 0; overflow: clip; }
.fairy-sidebar-panel { width: var(--qa-sidebar-width, 266px); height: 100%; margin-left: calc(100% - var(--qa-sidebar-width, 266px)); }
.fairy-sidebar-door :deep(.qa-settings) { height: 100%; width: 100%; min-width: 0; overflow: hidden; border-radius: 25px; border: 1px solid #fff; box-shadow: var(--card-shadow); }
.is-closed .fairy-sidebar-door { pointer-events: none; }
.fairy-door-handle { position: absolute; z-index: 3; left: calc(100% - var(--qa-fairy-space)); top: clamp(24px, 40%, calc(100% - 124px)); display: flex; flex-direction: column; align-items: center; justify-content: center; width: 76px; min-height: 94px; padding: 0; border: 0; border-radius: 20px; background: transparent; box-shadow: none; color: #668796; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.fairy-door-handle:hover:not(:disabled), .fairy-door-handle:active:not(:disabled) { background: transparent; border: 0; box-shadow: none; transform: none; }
.fairy-door-handle:focus-visible { outline: 2px solid #89afbb; outline-offset: 3px; }
/* Mirror around the image center; using the palm as the mirror origin shifts
   the entire character almost one image-width away from the panel. */
.fairy-door-art { position: relative; left: -2%; display: block; width: 100%; flex: none; transform: scaleX(-1); transform-origin: center; pointer-events: none; }
.fairy-door-sprite { display: block; width: 100%; height: auto; max-width: none; filter: drop-shadow(0 4px 5px #6e829521); transform-origin: 98% 42%; user-select: none; pointer-events: none; }
/* Each pose has a different palm position inside its transparent image. */
.is-closed .fairy-door-art { left: -8%; }
.is-closed .fairy-door-sprite { transform-origin: 92% 42%; }
.fairy-door-light { position: absolute; left: -1px; top: 29px; width: 3px; height: 24px; border-radius: 100%; background: linear-gradient(transparent, #e9d8ab, transparent); opacity: .4; box-shadow: 0 0 16px #e4cda877; transition: opacity 250ms; }
.fairy-door-caption { margin-top: -2px; padding: 3px 7px; border: 1px solid #e3ebe8; border-radius: 8px; background: #fffdf5eb; color: #7b9099; font-size: 10px; line-height: 1.4; opacity: 0; transform: translateY(-3px); transition: opacity 160ms, transform 160ms; }
.fairy-door-handle:hover .fairy-door-caption, .fairy-door-handle:focus-visible .fairy-door-caption, .is-closed .fairy-door-caption { opacity: 1; transform: none; }
.is-closed .fairy-door-light { opacity: 0; }
.fairy-door-fallback { display: grid; place-items: center; width: 40px; height: 48px; border-radius: 14px; background: #e5eff1; }
.is-moving .fairy-door-sprite { animation: fairy-door-pull 900ms both; }
.is-moving.is-closed .fairy-door-sprite { animation-name: fairy-door-push; }
.is-moving .fairy-door-light { opacity: 1; }
/* All magic shares the palm/edge anchor and never participates in layout. */
.fairy-edge-flare { position: absolute; z-index: 2; pointer-events: none; left: calc(100% - var(--qa-fairy-space) - 1px); top: 25px; bottom: 25px; width: 2px; border-radius: 50%; background: linear-gradient(transparent, #e6cb94 25%, #fffdf0 45%, #9edbe2 70%, transparent); box-shadow: 0 0 12px #a3dfe7, 0 0 24px #e9cc9955; transform-origin: 50% 40%; animation: fairy-edge-awaken 880ms both; }
.fairy-edge-flare::after { content: ''; position: absolute; inset: 0 -17px; background: linear-gradient(90deg, transparent, #b8e7e52b, #fff9e855, transparent); }
.fairy-magic-burst { position: absolute; z-index: 2; left: 0; top: 33px; width: 0; height: 0; pointer-events: none; }
.fairy-magic-ring { position: absolute; left: -15px; top: -15px; width: 30px; height: 30px; border: 1px solid #e6ce9c; border-radius: 50%; box-shadow: 0 0 12px #e5d8af66, inset 0 0 8px #c0e3e677; animation: fairy-ring-release 720ms 70ms both; }
.fairy-magic-spark { position: absolute; left: -5px; top: -7px; font-size: 13px; font-style: normal; color: #d4b577; text-shadow: 0 0 7px #fff8dc; animation: fairy-spark-release 670ms calc(90ms + var(--spark-delay)) both; }
.fairy-magic-spark:nth-child(odd) { color: #89bac8; font-size: 9px; }
@keyframes fairy-door-pull {
  0% { transform: rotate(0) scale(1); }
  12% { transform: rotate(-7deg) scale(.97, 1.02); }
  40% { transform: rotate(9deg) scale(1.04, .97); }
  72% { transform: rotate(-3deg) scale(.99, 1.01); }
  88% { transform: rotate(1.5deg); }
  100% { transform: rotate(0) scale(1); }
}
@keyframes fairy-door-push {
  0% { transform: rotate(0) scale(1); }
  12% { transform: rotate(6deg) scale(1.02, .98); }
  42% { transform: rotate(-10deg) scale(.96, 1.03); }
  74% { transform: rotate(3deg) scale(1.02, .99); }
  90% { transform: rotate(-1deg); }
  100% { transform: rotate(0) scale(1); }
}
@keyframes fairy-edge-awaken {
  0% { opacity: 0; transform: scaleY(.08); }
  18% { opacity: .95; transform: scaleY(.7); }
  45% { opacity: .8; transform: scaleY(1); }
  100% { opacity: 0; transform: scaleY(1); }
}
@keyframes fairy-ring-release {
  0% { opacity: 0; transform: scale(.25); }
  22% { opacity: .85; }
  100% { opacity: 0; transform: scale(2.2); }
}
@keyframes fairy-spark-release {
  0% { opacity: 0; transform: translate(0, 0) scale(.2) rotate(0); }
  18% { opacity: 1; }
  100% { opacity: 0; transform: translate(var(--spark-x), var(--spark-y)) scale(.3) rotate(85deg); }
}
@media (max-width: 960px) {
  .fairy-sidebar { height: auto; }
  .fairy-sidebar-panel { width: 100%; margin-left: 0; }
  .is-closed { height: 94px; }
  .is-closed .fairy-sidebar-door { height: 0; overflow: hidden; }
  .fairy-door-handle { top: 24px; width: 60px; min-height: 70px; }
  .is-closed .fairy-door-handle { top: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .fairy-sidebar *, .fairy-sidebar *::after { transition: none !important; animation: none !important; }
  .fairy-edge-flare, .fairy-magic-burst { display: none; }
}
</style>
