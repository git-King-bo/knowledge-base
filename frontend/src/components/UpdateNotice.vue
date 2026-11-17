<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { canSaveDrafts, dirtyGuards, saveUpdateDrafts, updateBusy } from '../lib/updateSafety'
import { createVersionChecker } from '../lib/versionCheck'
declare const __APP_VERSION__: string
const version = typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : 'development'
const available = ref(''), dismissed = ref(''), expanded = ref(false), waiting = ref(false), error = ref('')
const visible = computed(() => available.value && available.value !== dismissed.value)
const checker = createVersionChecker(version, next => { available.value = next })
let timer: ReturnType<typeof setInterval> | undefined
let leaving = false
function check() { if (!document.hidden && navigator.onLine !== false) void checker.check() }
function reload() {
  // Recheck at the moment of activation: work may have started after opening the prompt.
  if (updateBusy.value) { expanded.value = true; return }
  leaving = true
  window.location.reload()
}
function update() {
  if (updateBusy.value || dirtyGuards.value.length) expanded.value = true
  else reload()
}
function saveAndReload() {
  if (updateBusy.value) return
  if (!saveUpdateDrafts()) { error.value = '草稿保存失败，请返回页面保存内容后再更新。'; return }
  reload()
}
function later() { dismissed.value = available.value; expanded.value = false; waiting.value = false }
function beforeUnload(event: BeforeUnloadEvent) {
  if (!leaving && (updateBusy.value || dirtyGuards.value.length)) { event.preventDefault(); event.returnValue = '' }
}
watch([updateBusy, () => dirtyGuards.value.length], () => {
  if (waiting.value && !updateBusy.value && !dirtyGuards.value.length) reload()
})
onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload)
  if (version === 'development') return
  check()
  timer = setInterval(check, 60_000)
  document.addEventListener('visibilitychange', check)
  window.addEventListener('online', check)
})
onUnmounted(() => {
  clearInterval(timer); checker.stop()
  document.removeEventListener('visibilitychange', check); window.removeEventListener('online', check)
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>
<template>
  <aside v-if="visible" class="update-notice" aria-label="应用更新" role="status">
    <strong>新版本已发布</strong>
    <p>更新后即可使用最新功能。</p>
    <template v-if="expanded">
      <p v-if="updateBusy">操作正在进行，请等待提交、上传或回答结束。</p>
      <p v-if="dirtyGuards.length">尚未保存：{{ dirtyGuards.map(item => item.label).join('、') }}。可返回继续操作，完成后再更新。</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <button v-if="updateBusy" @click="waiting = true" :disabled="waiting">{{ waiting ? '等待操作完成，未保存内容仍会保留' : '完成后更新（无未保存内容时）' }}</button>
      <button v-if="canSaveDrafts" :disabled="updateBusy" @click="saveAndReload">保存问答草稿并更新</button>
      <button v-if="dirtyGuards.length" :disabled="updateBusy" @click="reload">放弃未保存内容并更新</button>
      <button @click="expanded = false; waiting = false">返回继续操作</button>
    </template>
    <div class="update-actions"><button v-if="!expanded" class="primary" @click="update">立即更新</button><button @click="later">稍后</button></div>
  </aside>
</template>
<style scoped>
.update-notice {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 12000;
  width: min(300px, calc(100vw - 32px));
  max-height: calc(100dvh - 40px);
  overflow-y: auto;
  padding: 14px 16px;
  border: 1px solid #ddd2eb;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 6px 24px #3522471a;
  color: #30263e;
}
.update-notice strong { font-size: 14px; }
.update-notice p { margin: 5px 0 9px; font-size: 12px; line-height: 1.5; }
.update-notice button { min-height: 30px; margin: 3px 5px 3px 0; padding: 5px 10px; font-size: 12px; }
.update-actions { display: flex; gap: 6px; flex-wrap: wrap; }
@media (max-width: 600px) {
  .update-notice { top: 16px; right: 16px; max-height: calc(100dvh - 32px); }
}
</style>
