import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

/** Animate related chart values on one clock, preserving item identity across updates. */
export function useAnimatedMetrics(target: () => Record<string, number>, duration = 1100) {
  const displayed = ref<Record<string, number>>({})
  const mounted = ref(false)
  const reducedMotion = ref(false)
  let frame: number | undefined
  let preference: MediaQueryList | undefined

  function cancel() {
    if (frame !== undefined) cancelAnimationFrame(frame)
    frame = undefined
  }
  function syncPreference() { reducedMotion.value = preference?.matches ?? false }

  watch([target, mounted, reducedMotion], ([next]) => {
    cancel()
    if (!mounted.value) return
    const entries = Object.entries(next)
    if (reducedMotion.value || duration <= 0 || entries.length === 0) {
      displayed.value = { ...next }
      return
    }
    const from = Object.fromEntries(entries.map(([key]) => [key, displayed.value[key] ?? 0]))
    if (entries.every(([key, value]) => from[key] === value)) {
      displayed.value = { ...next }
      return
    }
    displayed.value = from
    const started = performance.now()
    function tick(now: number) {
      const progress = Math.min(1, Math.max(0, (now - started) / duration))
      const eased = 1 - Math.pow(1 - progress, 3)
      displayed.value = progress === 1 ? { ...next } : Object.fromEntries(
        entries.map(([key, value]) => [key, from[key]! + (value - from[key]!) * eased]),
      )
      if (progress < 1) frame = requestAnimationFrame(tick)
      else frame = undefined
    }
    frame = requestAnimationFrame(tick)
  }, { immediate: true })

  onMounted(() => {
    preference = window.matchMedia('(prefers-reduced-motion: reduce)')
    syncPreference()
    preference.addEventListener('change', syncPreference)
    mounted.value = true
  })
  onBeforeUnmount(() => {
    cancel()
    preference?.removeEventListener('change', syncPreference)
  })
  return displayed
}
