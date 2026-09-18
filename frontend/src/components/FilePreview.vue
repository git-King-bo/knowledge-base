<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { apiFetch, request } from '../lib/api'
import type { KnowledgeSource } from '../lib/types'
import AppIcon from './AppIcon.vue'
const props = defineProps<{ baseId: string; source: KnowledgeSource }>()
const emit = defineEmits<{ close: [] }>()
type Preview = { kind: 'pdf' }
  | { kind: 'text'; text: string; offset: number; total: number; note: string }
  | { kind: 'table'; sheets: string[]; rows: { number: number; cells: string[] }[]; columns: number;
      columns_truncated: boolean; total: number }
const dialog = ref<HTMLDialogElement>()
const titleId = useId()
const sheet = ref(0), offset = ref(0), retry = ref(0)
const preview = ref<Preview>()
const loading = ref(false), error = ref(''), pdfUrl = ref('')
const filePath = computed(() => `/knowledge/bases/${encodeURIComponent(props.baseId)}/sources/${encodeURIComponent(props.source.id)}`)
const step = computed(() => preview.value?.kind === 'table' ? 50 : 1)
const hasNext = computed(() => preview.value && preview.value.kind !== 'pdf' && offset.value + step.value < preview.value.total)
function columnName(index: number) {
  let name = ''
  for (let n = index; n > 0; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + (n - 1) % 26) + name
  return name
}
watch([sheet, offset, retry], async (_, __, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  loading.value = true; error.value = ''
  try {
    const data = await request<Preview>(`${filePath.value}/preview?sheet=${sheet.value}&offset=${offset.value}&limit=50`, { signal: controller.signal })
    if (controller.signal.aborted) return
    preview.value = data
    if (data.kind === 'pdf' && !pdfUrl.value) {
      const response = await apiFetch(`${filePath.value}/file`, { signal: controller.signal })
      const blob = await response.blob()
      if (!controller.signal.aborted) pdfUrl.value = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))
    }
  } catch (cause) {
    if (!controller.signal.aborted) error.value = cause instanceof Error ? cause.message : '预览加载失败'
  } finally { if (!controller.signal.aborted) loading.value = false }
}, { immediate: true })
onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => { if (pdfUrl.value) URL.revokeObjectURL(pdfUrl.value); dialog.value?.close() })
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="file-preview" :aria-labelledby="titleId" @cancel.prevent="emit('close')">
      <header class="preview-header"><AppIcon name="file" :size="22" />
        <div><h2 :id="titleId">{{ source.filename }}</h2><p>文件预览</p></div>
        <button class="icon-button" aria-label="关闭预览" @click="emit('close')"><AppIcon name="close" /></button>
      </header>
      <nav v-if="preview?.kind === 'table' && preview.sheets.length" class="preview-sheets" aria-label="工作表">
        <button v-for="(name, index) in preview.sheets" :key="index" :aria-pressed="sheet === index" :disabled="loading"
          @click="sheet = index; offset = 0">{{ name }}</button>
      </nav>
      <div v-if="error" class="preview-state" role="alert">{{ error }}<button @click="retry++">重试</button></div>
      <div v-else-if="loading" class="preview-state" role="status">正在加载文件…</div>
      <template v-else-if="preview">
        <div v-if="preview.kind === 'table'" class="preview-table-scroll">
          <table v-if="preview.rows.length" class="preview-table">
            <thead><tr><th scope="col">行号</th><th v-for="column in preview.columns" :key="column" scope="col">{{ columnName(column) }}</th></tr></thead>
            <tbody><tr v-for="row in preview.rows" :key="row.number"><th scope="row">{{ row.number }}</th>
              <td v-for="column in preview.columns" :key="column">{{ row.cells[column - 1] || '' }}</td>
            </tr></tbody>
          </table><div v-else class="preview-state">此工作表暂无内容</div>
        </div>
        <iframe v-else-if="preview.kind === 'pdf' && pdfUrl" class="preview-pdf" :src="pdfUrl" :title="source.filename" />
        <pre v-else-if="preview.kind === 'text'" class="preview-text">{{ preview.text }}</pre>
      </template>
      <footer class="preview-footer">
        <div v-if="preview?.kind === 'table'">
          <p>共 {{ preview.total }} 个非空行（含表头）<span v-if="preview.total"> · 当前 {{ offset + 1 }}–{{ Math.min(offset + 50, preview.total) }} 行</span></p>
          <small>显示单元格内容，不保留原始样式；公式显示已保存的结果。{{ preview.columns_truncated ? '仅展示前 200 列。' : '' }}</small>
        </div>
        <div v-else-if="preview?.kind === 'text'"><p>第 {{ offset + 1 }} / {{ preview.total }} 页</p><small>{{ preview.note || '完整正文按页展示' }}</small></div>
        <div v-else><small>文件内容预览</small></div>
        <div v-if="preview && preview.kind !== 'pdf'" class="preview-pagination">
          <button :disabled="loading || offset === 0" @click="offset = Math.max(0, offset - step)">上一页</button>
          <button :disabled="loading || !hasNext" @click="offset += step">下一页</button>
        </div>
      </footer>
    </dialog>
  </Teleport>
</template>

<style scoped>
.file-preview { width: min(1200px, calc(100vw - 40px)); height: min(820px, calc(100dvh - 48px)); max-width: none; max-height: none; margin: auto; padding: 0; border: 1px solid #e6deee; border-radius: 16px; background: #fff; color: #55485f; box-shadow: 0 24px 80px #29183e30; }
.file-preview[open] { display: flex; flex-direction: column; }
.file-preview::backdrop { background: #20142d60; backdrop-filter: blur(3px); }
.preview-header { display: flex; align-items: center; gap: 12px; padding: 18px 22px; border-bottom: 1px solid #eee8f4; }
.preview-header > div { flex: 1; min-width: 0; }.preview-header h2 { font-size: 15px; overflow-wrap: anywhere; }.preview-header p { margin-top: 4px; font-size: 11px; color: #93839f; }
.preview-sheets { display: flex; flex-shrink: 0; gap: 8px; overflow: auto; padding: 10px 20px; background: #faf8fc; }.preview-sheets button { white-space: nowrap; font-size: 12px; }.preview-sheets button[aria-pressed='true'] { background: #eee5f8; border-color: #ccb7e2; color: #70508d; }
.preview-table-scroll, .preview-text, .preview-pdf, .preview-state { flex: 1; min-height: 0; }.preview-table-scroll { overflow: auto; }
.preview-table { width: max-content; min-width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; }.preview-table th, .preview-table td { padding: 10px 14px; border-right: 1px solid #eee8f4; border-bottom: 1px solid #eee8f4; vertical-align: top; }
.preview-table thead th { position: sticky; top: 0; z-index: 2; background: #f3eef8; color: #81708f; text-align: center; }.preview-table tr > th:first-child { position: sticky; left: 0; background: #f7f4fa; text-align: center; min-width: 58px; }.preview-table thead th:first-child { z-index: 3; }
.preview-table td { min-width: 160px; max-width: 360px; white-space: pre-wrap; overflow-wrap: anywhere; }.preview-table tbody tr:hover td { background: #fcfaff; }
.preview-text { margin: 0; padding: 24px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.9 ui-monospace, monospace; }.preview-pdf { width: 100%; border: 0; }.preview-state { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 24px; }
.preview-footer { display: flex; flex-shrink: 0; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 22px; border-top: 1px solid #eee8f4; font-size: 12px; }.preview-footer small { display: block; margin-top: 4px; color: #93839f; font-size: 11px; }.preview-pagination { display: flex; flex-shrink: 0; gap: 8px; }
@media (max-width: 640px) { .file-preview { width: calc(100vw - 16px); height: calc(100dvh - 24px); }.preview-footer { align-items: flex-start; flex-direction: column; }.preview-header { padding: 14px; } }
</style>
