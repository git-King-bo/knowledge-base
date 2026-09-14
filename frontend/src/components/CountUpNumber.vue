<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  value?: number | null
  duration?: number
}>(), { duration: 1100 })

const formatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 })
const displayed = ref<number>()
const mounted = ref(false)
const reducedMotion = ref(false)
const target = computed(() => typeof props.value === 'number' && Number.isFinite(props.value)
  ? Math.max(0, Math.round(props.value))
  : undefined)
const format = (value: number | undefined) => value === undefined ? '—' : formatter.format(value)
let frame: number | undefined
let motionPreference: MediaQueryList | undefined

function stopAnimation() {
  if (frame !== undefined) cancelAnimationFrame(frame)
  frame = undefined
}
function syncMotionPreference() {
  reducedMotion.value = motionPreference?.matches ?? false
}

watch([target, mounted, reducedMotion], ([next]) => {
  stopAnimation()
  if (next === undefined) {
    displayed.value = undefined
    return
  }
  if (!mounted.value) return
  if (reducedMotion.value || props.duration <= 0) {
    displayed.value = next
    return
  }
  const from = displayed.value ?? 0
  displayed.value = from
  if (from === next) return
  const started = performance.now()
  const duration = props.duration
  const destination = next
  function tick(now: number) {
    const progress = Math.min(1, Math.max(0, (now - started) / duration))
    // Start quickly and ease into the exact value; intermediate values are display-only.
    const eased = 1 - Math.pow(1 - progress, 3)
    displayed.value = progress === 1 ? destination : Math.round(from + (destination - from) * eased)
    if (progress < 1) frame = requestAnimationFrame(tick)
    else frame = undefined
  }
  frame = requestAnimationFrame(tick)
}, { immediate: true })

onMounted(() => {
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
  syncMotionPreference()
  motionPreference.addEventListener('change', syncMotionPreference)
  mounted.value = true
})
onBeforeUnmount(() => {
  stopAnimation()
  motionPreference?.removeEventListener('change', syncMotionPreference)
})
</script>

<template>
  <span class="count-up-number">
    <span aria-hidden="true">{{ format(displayed) }}</span>
    <span class="count-up-accessible">{{ format(target) }}</span>
  </span>
</template>

<style scoped>
.count-up-number {
  font-variant-numeric: tabular-nums;
}
.count-up-accessible {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
</style>
