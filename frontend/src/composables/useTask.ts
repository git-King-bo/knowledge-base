import { ref } from 'vue'

export function useTask() {
  const busy = ref(false)
  const error = ref('')
  async function run<T>(task: () => Promise<T>): Promise<T | undefined> {
    if (busy.value) return
    busy.value = true
    error.value = ''
    try { return await task() }
    catch (cause) { error.value = cause instanceof Error ? cause.message : '操作失败，请重试' }
    finally { busy.value = false }
  }
  return { busy, error, run }
}
