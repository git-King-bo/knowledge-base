<script setup lang="ts" generic="T extends string | number">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'

type Option = { value: T; label: string; description?: string; disabled?: boolean }
const props = withDefaults(defineProps<{
  options: Option[]
  label: string
  placeholder?: string
  disabled?: boolean
}>(), { placeholder: '请选择', disabled: false })
const model = defineModel<T>({ required: true })
const emit = defineEmits<{ change: [value: T] }>()
const id = `select-${useId()}`
const root = ref<HTMLElement>()
const trigger = ref<HTMLButtonElement>()
const menu = ref<HTMLElement>()
const open = ref(false)
const activeIndex = ref(-1)
const hasPopover = ref(true)
const position = ref({ left: '0px', top: '0px', width: '220px', maxHeight: '300px' })
const selected = computed(() => props.options.find(option => option.value === model.value))
const activeId = computed(() => open.value && activeIndex.value >= 0 ? `${id}-option-${activeIndex.value}` : undefined)
const enabledIndices = computed(() => props.options.flatMap((option, index) => option.disabled ? [] : [index]))
let search = ''
let searchTimer: ReturnType<typeof setTimeout> | undefined

function placeMenu() {
  if (!open.value || !trigger.value || !menu.value) return
  const rect = trigger.value.getBoundingClientRect()
  const viewport = window.visualViewport
  const leftEdge = viewport?.offsetLeft || 0
  const topEdge = viewport?.offsetTop || 0
  const viewportWidth = viewport?.width || window.innerWidth
  const viewportHeight = viewport?.height || window.innerHeight
  const gap = 7
  const bottomSpace = topEdge + viewportHeight - rect.bottom - gap - 12
  const topSpace = rect.top - topEdge - gap - 12
  const above = bottomSpace < 200 && topSpace > bottomSpace
  const maxHeight = Math.max(80, Math.min(310, above ? topSpace : bottomSpace))
  const width = Math.min(Math.max(rect.width, 220), viewportWidth - 24)
  const height = Math.min(menu.value.getBoundingClientRect().height || maxHeight, maxHeight)
  position.value = {
    left: `${Math.max(leftEdge + 12, Math.min(rect.left, leftEdge + viewportWidth - width - 12))}px`,
    top: `${Math.max(topEdge + 12, above ? rect.top - height - gap : rect.bottom + gap)}px`,
    width: `${width}px`,
    maxHeight: `${maxHeight}px`,
  }
}
function scrollActive() {
  void nextTick(() => document.getElementById(activeId.value || '')?.scrollIntoView({ block: 'nearest' }))
}
async function showMenu(last = false) {
  if (props.disabled || open.value) return
  activeIndex.value = props.options.findIndex(option => option.value === model.value && !option.disabled)
  if (activeIndex.value < 0) activeIndex.value = (last ? enabledIndices.value.at(-1) : enabledIndices.value[0]) ?? -1
  open.value = true
  await nextTick()
  if (!open.value || !menu.value) return
  placeMenu()
  if (hasPopover.value) menu.value.showPopover()
  await nextTick()
  placeMenu()
  scrollActive()
}
function closeMenu() {
  if (hasPopover.value && menu.value?.matches(':popover-open')) menu.value.hidePopover()
  open.value = false
  search = ''
  clearTimeout(searchTimer)
}
function choose(index: number) {
  const option = props.options[index]
  if (!option || option.disabled || props.disabled) return
  const changed = option.value !== model.value
  model.value = option.value
  closeMenu()
  trigger.value?.focus({ preventScroll: true })
  if (changed) emit('change', option.value)
}
function move(direction: number) {
  const indices = enabledIndices.value
  if (!indices.length) return
  const current = indices.indexOf(activeIndex.value)
  activeIndex.value = indices[(current + direction + indices.length) % indices.length] ?? -1
  scrollActive()
}
function onKeydown(event: KeyboardEvent) {
  if (props.disabled || event.isComposing) return
  if (event.key === 'Tab') { closeMenu(); return }
  if (event.key === 'Escape') {
    if (open.value) { event.preventDefault(); event.stopPropagation(); closeMenu() }
    return
  }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(event.key)) {
    event.preventDefault()
    if (!open.value) { void showMenu(event.key === 'ArrowUp' || event.key === 'End'); return }
    if (event.key === 'Enter' || event.key === ' ') { choose(activeIndex.value); return }
    if (event.key === 'Home' || event.key === 'End') {
      activeIndex.value = (event.key === 'Home' ? enabledIndices.value[0] : enabledIndices.value.at(-1)) ?? -1
      scrollActive()
    } else move(event.key === 'ArrowDown' ? 1 : -1)
    return
  }
  if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault()
    void showMenu()
    clearTimeout(searchTimer)
    search += event.key.toLocaleLowerCase()
    const query = [...search].every(char => char === search[0]) ? search[0]! : search
    const indices = enabledIndices.value
    const start = indices.indexOf(activeIndex.value)
    const ordered = [...indices.slice(start + 1), ...indices.slice(0, start + 1)]
    const match = ordered.find(index => props.options[index]?.label.toLocaleLowerCase().startsWith(query))
    if (match !== undefined) { activeIndex.value = match; scrollActive() }
    searchTimer = setTimeout(() => { search = '' }, 700)
  }
}
function onOutside(event: PointerEvent) {
  if (open.value && !root.value?.contains(event.target as Node)) closeMenu()
}
function onScroll(event: Event) {
  // Scrolling the options keeps the menu open; scrolling its page closes it.
  if (open.value && !menu.value?.contains(event.target as Node)) closeMenu()
}
watch(() => props.disabled, disabled => { if (disabled) closeMenu() })
watch(() => props.options, () => {
  if (open.value) { closeMenu() }
})
onMounted(() => {
  hasPopover.value = Boolean(menu.value && typeof menu.value.showPopover === 'function')
  document.addEventListener('pointerdown', onOutside, true)
  document.addEventListener('scroll', onScroll, true)
  window.addEventListener('resize', closeMenu)
  window.visualViewport?.addEventListener('resize', closeMenu)
})
onBeforeUnmount(() => {
  closeMenu()
  document.removeEventListener('pointerdown', onOutside, true)
  document.removeEventListener('scroll', onScroll, true)
  window.removeEventListener('resize', closeMenu)
  window.visualViewport?.removeEventListener('resize', closeMenu)
})
</script>

<template>
  <span ref="root" class="app-select" :class="{ 'is-open': open, 'is-disabled': disabled }">
    <button
      :id="id"
      ref="trigger"
      type="button"
      class="app-select-trigger"
      role="combobox"
      aria-haspopup="listbox"
      :aria-label="`${label}：${selected?.label || placeholder}`"
      :aria-expanded="open"
      :aria-controls="`${id}-listbox`"
      :aria-activedescendant="activeId"
      :disabled="disabled"
      @click="open ? closeMenu() : showMenu()"
      @keydown="onKeydown"
      @blur="closeMenu"
    >
      <span class="app-select-value" :class="{ 'is-placeholder': !selected }" :title="selected?.label">{{ selected?.label || placeholder }}</span>
      <svg class="app-select-chevron" width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m6 8 4 4 4-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg>
    </button>
    <span
      :id="`${id}-listbox`"
      ref="menu"
      class="app-select-menu"
      :class="{ 'is-fallback': !hasPopover && open }"
      popover="manual"
      role="listbox"
      :aria-label="label"
      :style="position"
      @pointerdown.prevent
    >
      <span v-if="!options.length" class="app-select-empty">暂无可选项</span>
      <span
        v-for="(option, index) in options"
        :id="`${id}-option-${index}`"
        :key="option.value"
        class="app-select-option"
        :class="{ 'is-selected': option.value === model, 'is-active': index === activeIndex, 'is-disabled': option.disabled }"
        role="option"
        :aria-selected="option.value === model"
        :aria-disabled="option.disabled || undefined"
        @pointermove="!option.disabled && (activeIndex = index)"
        @click.stop.prevent="choose(index)"
      >
        <span class="app-select-option-copy"><span>{{ option.label }}</span><small v-if="option.description">{{ option.description }}</small></span>
        <svg v-if="option.value === model" class="app-select-check" width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m4.5 10 3.5 3.5 7.5-7.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>
      </span>
    </span>
  </span>
</template>
