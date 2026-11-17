import { computed, onScopeDispose, ref, shallowReactive, watch } from 'vue'

export const activeTasks = ref(0)
export interface UpdateGuard {
  label: string
  dirty: () => boolean
  busy?: () => boolean
  saveDraft?: () => boolean
}
const guards = shallowReactive(new Set<UpdateGuard>())
export function useUpdateGuard(guard: UpdateGuard) {
  guards.add(guard)
  onScopeDispose(() => guards.delete(guard))
}
export const dirtyGuards = computed(() => [...guards].filter(guard => guard.dirty()))
export const updateBusy = computed(() => activeTasks.value > 0 || [...guards].some(guard => guard.busy?.()))
export const canSaveDrafts = computed(() => dirtyGuards.value.length > 0 && dirtyGuards.value.every(guard => guard.saveDraft))
export function saveUpdateDrafts() {
  return canSaveDrafts.value && dirtyGuards.value.every(guard => guard.saveDraft?.())
}

export function useFormUpdateGuard(label: string, open: () => boolean, value: () => unknown) {
  const initial = ref('')
  watch(open, visible => { if (visible) initial.value = JSON.stringify(value()) }, { immediate: true, flush: 'sync' })
  useUpdateGuard({ label, dirty: () => open() && JSON.stringify(value()) !== initial.value })
}
