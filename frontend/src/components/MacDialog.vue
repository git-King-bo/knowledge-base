<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { bottomBox, clamp, drawGenie, lockScroll, originBox, type Box, type Origin } from '../lib/genie'
import { captureDialog } from '../lib/dialogSnapshot'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  modelValue: boolean; title?: string; origin?: Origin; duration?: number; dockX?: number
  destroyOnClose?: boolean; closeOnClickModal?: boolean; closeOnPressEscape?: boolean
  beforeClose?: (done: () => void) => void
}>(), { title: '', duration: 680, dockX: .5, destroyOnClose: false, closeOnClickModal: true, closeOnPressEscape: true })
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; open: []; opened: []; close: []; closed: [] }>()
const shell = ref<HTMLDialogElement>()
const panel = ref<HTMLElement>()
const canvas = ref<HTMLCanvasElement>()
const rendered = ref(false)
const hidden = ref(false)
const animating = ref(false)
const titleId = useId()
let mounted = false, dead = false, serial = 0, frame = 0, timer: ReturnType<typeof setTimeout> | undefined
let progress = 1, desired = 1, previousTime = 0
let source: Box, target: Box, openedTarget: Box | undefined
let snapshot: HTMLCanvasElement | undefined, disposeCapture: (() => void) | undefined
let unlock: (() => void) | undefined
let media: MediaQueryList | undefined
const reduced = ref(false)
const milliseconds = computed(() => reduced.value ? 0 : Math.max(0, Number.isFinite(props.duration) ? props.duration : 680))

function releaseAnimation() {
  cancelAnimationFrame(frame); frame = 0
  clearTimeout(timer); timer = undefined
  disposeCapture?.(); disposeCapture = undefined
  if (snapshot) { snapshot.width = snapshot.height = 0; snapshot = undefined }
  if (canvas.value) canvas.value.width = canvas.value.height = 0
  hidden.value = false; animating.value = false
}
function finish() {
  serial++
  progress = desired
  releaseAnimation()
  if (desired === 1) {
    shell.value?.close(); unlock?.(); unlock = undefined
    if (props.destroyOnClose) rendered.value = false
    emit('closed')
  } else emit('opened')
}
function tick(time: number) {
  if (dead) return
  const delta = previousTime ? (time - previousTime) / milliseconds.value : 0
  previousTime = time
  progress = clamp(progress + (desired === 1 ? delta : -delta))
  const ctx = canvas.value?.getContext('2d')
  if (!ctx || !snapshot || !milliseconds.value) { finish(); return }
  drawGenie(ctx, snapshot, source, target, progress)
  if (progress === desired) finish()
  else frame = requestAnimationFrame(tick)
}
async function change(open: boolean) {
  desired = open ? 0 : 1
  if (open) emit('open')
  else emit('close')
  // Includes the snapshot-pending phase: reverse without changing the path.
  if (animating.value) { if (!milliseconds.value) finish(); return }
  if (!open && !shell.value?.open) return
  const token = ++serial
  animating.value = true
  if (open) {
    rendered.value = true
    hidden.value = milliseconds.value > 0
    await nextTick()
    if (dead || token !== serial) return
    unlock ??= lockScroll()
    shell.value?.showModal()
  }
  target = originBox(props.origin) ?? (open ? bottomBox(props.dockX) : openedTarget ?? bottomBox(props.dockX))
  if (open) openedTarget = target
  if (!milliseconds.value || !panel.value) { finish(); return }
  const rect = panel.value.getBoundingClientRect()
  source = { left: rect.left, top: rect.top, width: rect.width, height: rect.height }
  try {
    const capture = captureDialog(panel.value)
    disposeCapture = capture.dispose
    timer = setTimeout(() => { if (token === serial) finish() }, 900)
    const image = await capture.promise
    if (dead || token !== serial) { image.width = image.height = 0; return }
    clearTimeout(timer); timer = undefined
    capture.dispose(); disposeCapture = undefined
    snapshot = image
    const surface = canvas.value!
    const ratio = Math.min(devicePixelRatio || 1, 2)
    surface.width = innerWidth * ratio; surface.height = innerHeight * ratio
    const ctx = surface.getContext('2d')
    if (!ctx) { finish(); return }
    ctx.scale(ratio, ratio)
    drawGenie(ctx, image, source, target, progress)
    hidden.value = true
    previousTime = 0
    frame = requestAnimationFrame(tick)
  } catch { if (!dead && token === serial) finish() }
}
function requestClose() {
  const done = () => { if (!dead) emit('update:modelValue', false) }
  if (props.beforeClose) props.beforeClose(done)
  else done()
}
function backdrop(event: MouseEvent) {
  if (event.target === shell.value && props.closeOnClickModal) requestClose()
}
function escape(event: Event) { event.preventDefault(); if (props.closeOnPressEscape) requestClose() }
function nativeClosed() {
  // Also clean up if a consumer uses form method="dialog" or dialog.close().
  if (!shell.value?.open && unlock) {
    desired = 1; emit('update:modelValue', false); finish()
  }
}
function motionChanged() { reduced.value = media?.matches ?? false; if (reduced.value && animating.value) finish() }
function resized() { if (animating.value) finish() }
watch(() => props.modelValue, value => { if (mounted) void change(value) })
watch(milliseconds, value => { if (!value && animating.value) finish() })
onMounted(() => {
  mounted = true
  media = matchMedia('(prefers-reduced-motion: reduce)'); reduced.value = media.matches
  media.addEventListener('change', motionChanged)
  window.addEventListener('resize', resized)
  if (props.modelValue) void change(true)
})
onBeforeUnmount(() => {
  dead = true; serial++; releaseAnimation(); shell.value?.close(); unlock?.()
  media?.removeEventListener('change', motionChanged); window.removeEventListener('resize', resized)
})
defineExpose({ dialog: shell, requestClose })
</script>

<template>
  <Teleport to="body">
    <dialog ref="shell" class="mac-dialog-shell" :aria-labelledby="title ? titleId : undefined" @cancel="escape" @click="backdrop" @close="nativeClosed">
      <section v-if="rendered" ref="panel" v-bind="$attrs" class="dialog mac-dialog-panel" :style="{ opacity: hidden ? 0 : undefined }" :aria-busy="animating || undefined">
        <header><slot name="header" :close="requestClose" :title-id="titleId"><h2 :id="titleId">{{ title }}</h2><button type="button" class="icon-button" aria-label="关闭" @click="requestClose"><AppIcon name="close" /></button></slot></header>
        <slot :close="requestClose" />
        <footer v-if="$slots.footer"><slot name="footer" :close="requestClose" /></footer>
      </section>
      <canvas ref="canvas" class="mac-dialog-canvas" :style="{ visibility: hidden ? 'visible' : 'hidden' }" aria-hidden="true" />
    </dialog>
  </Teleport>
</template>

<style>
.mac-dialog-shell { position: fixed; inset: 0; width: 100%; height: 100%; max-width: none; max-height: none; margin: 0; padding: 0; border: 0; background: transparent; overflow: hidden; color: inherit; }
.mac-dialog-shell[open] { display: grid; place-items: center; }
.mac-dialog-shell::backdrop { background: #20142d60; backdrop-filter: blur(3px); }
.mac-dialog-panel { margin: auto; background: white; overflow: auto; box-sizing: border-box; }
.mac-dialog-canvas { position: fixed; inset: 0; width: 100vw; height: 100vh; pointer-events: none; }
</style>
