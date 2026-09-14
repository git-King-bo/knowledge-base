<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { createKnowledgeBase, updateKnowledgeBase, deleteKnowledgeBase, fetchKnowledgeBaseSources, fetchKnowledgeBaseChunks, uploadKnowledgeBaseFile, removeKnowledgeBaseSource, rebuildKnowledgeSourceEmbeddings } from '../lib/api'
import type { KnowledgeBase, KnowledgeSource, KnowledgeChunk } from '../lib/types'
import { useTask } from '../composables/useTask'
import AppIcon from '../components/AppIcon.vue'
import AppSelect from '../components/AppSelect.vue'
import AppDialog from '../components/AppDialog.vue'
import MacDialog from '../components/MacDialog.vue'
const props = defineProps<{ bases: KnowledgeBase[]; loading: boolean; refresh: () => Promise<void> }>()
const emit = defineEmits<{ navigate: [tab: string, baseId: string] }>()
const { busy, error, run } = useTask()
const query = ref('')
const status = ref('active')
const selectedId = ref('')
const selected = computed(() => props.bases.find(base => base.id === selectedId.value))
const sources = ref<KnowledgeSource[]>([])
const chunks = ref<KnowledgeChunk[]>([])
const sourceFilter = ref('')
const detailTab = ref('sources')
const dialog = ref<'create' | 'edit' | 'delete' | 'remove' | ''>('')
const formMode = ref<'create' | 'edit'>('create')
const formOrigin = ref<HTMLElement>()
const formVisible = computed({
  get: () => dialog.value === 'create' || dialog.value === 'edit',
  set: (visible: boolean) => { dialog.value = visible ? formMode.value : '' },
})
const removingSource = ref<KnowledgeSource>()
const form = reactive({ name: '', description: '', tags: '' })
const notice = ref('')
const uploadProgress = ref('')
const filtered = computed(() => props.bases.filter(base => (status.value === 'all' || base.status === status.value) && `${base.name} ${base.description} ${base.tags.join(' ')}`.toLowerCase().includes(query.value.toLowerCase())))
const displayedChunks = computed(() => chunks.value.filter(chunk => !sourceFilter.value || chunk.sourceId === sourceFilter.value))
const totalSources = computed(() => props.bases.reduce((sum, base) => sum + base.sourceCount, 0))
const totalChunks = computed(() => props.bases.reduce((sum, base) => sum + base.chunkCount, 0))
const date = (value: string) => new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleDateString('zh-CN')
async function loadDetail(id = selectedId.value) {
  const [nextSources, nextChunks] = await Promise.all([fetchKnowledgeBaseSources(id), fetchKnowledgeBaseChunks(id)])
  sources.value = nextSources; chunks.value = nextChunks
}
function openBase(base: KnowledgeBase) {
  selectedId.value = base.id; sources.value = []; chunks.value = []; notice.value = ''; sourceFilter.value = ''; detailTab.value = 'sources'
  void run(() => loadDetail(base.id))
}
function openForm(mode: 'create' | 'edit', event: MouseEvent) {
  formMode.value = mode
  formOrigin.value = event.currentTarget as HTMLElement
  form.name = mode === 'edit' ? selected.value?.name || '' : ''
  form.description = mode === 'edit' ? selected.value?.description || '' : ''
  form.tags = mode === 'edit' ? selected.value?.tags.join(', ') || '' : ''
  error.value = ''; dialog.value = mode
}
function saveBase() {
  void run(async () => {
    const payload = { name: form.name.trim(), description: form.description.trim(), tags: form.tags.split(/[,，]/).map(tag => tag.trim()).filter(Boolean) }
    if (!payload.name) throw new Error('请输入知识库名称')
    const base = dialog.value === 'edit' ? await updateKnowledgeBase({ id: selectedId.value, ...payload }) : await createKnowledgeBase(payload)
    await props.refresh(); dialog.value = ''; selectedId.value = base.id; await loadDetail(base.id)
    notice.value = '知识库已保存，可以开始导入资料。'
  })
}
function archive() {
  if (!selected.value) return
  const base = selected.value
  void run(async () => { await updateKnowledgeBase({ id: base.id, status: base.status === 'active' ? 'archived' : 'active' }); await props.refresh() })
}
function confirmDelete() {
  void run(async () => {
    if (dialog.value === 'delete') { await deleteKnowledgeBase(selectedId.value); selectedId.value = '' }
    else if (removingSource.value) { await removeKnowledgeBaseSource(selectedId.value, removingSource.value.id); await loadDetail() }
    await props.refresh(); dialog.value = ''
  })
}
function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) return
  void run(async () => {
    let complete = 0
    const failures: string[] = []
    try {
      for (const [index, file] of files.entries()) {
        uploadProgress.value = `正在处理 ${index + 1}/${files.length} · ${file.name}`
        try {
          if (file.size > 20 * 1024 * 1024) throw new Error('超过 20 MB')
          await uploadKnowledgeBaseFile(selectedId.value, file); complete++
        } catch (cause) { failures.push(`${file.name}：${cause instanceof Error ? cause.message : '导入失败'}`) }
      }
      await props.refresh(); await loadDetail()
      notice.value = `${complete} 份资料已导入。`
      if (failures.length) throw new Error(failures.join('；'))
    } finally { uploadProgress.value = '' }
  })
}
function rebuild(source: KnowledgeSource) {
  void run(async () => { await rebuildKnowledgeSourceEmbeddings(source.id, selectedId.value); await loadDetail(); notice.value = '向量索引已重建。' })
}
</script>
<template>
  <div v-if="error && !dialog" class="notice error" role="alert">{{ error }}</div>
  <div v-if="notice" class="notice success" role="status">{{ notice }}</div>
  <template v-if="!selected">
    <section class="stat-grid three">
<article class="stat-card">
<span>知识库总数<AppIcon name="book" />
</span>
<strong>{{ bases.length }}<small>个知识空间</small>
</strong>
</article>
<article class="stat-card">
<span>已导入资料<AppIcon name="file" />
</span>
<strong>{{ totalSources }}<small>份知识来源</small>
</strong>
</article>
<article class="stat-card">
<span>知识切片<AppIcon name="layers" />
</span>
<strong>{{ totalChunks.toLocaleString() }}<small>段可检索内容</small>
</strong>
</article>
</section>
    <div class="section-toolbar">
<div class="segmented">
<button v-for="option in [{ id: 'active', label: '使用中' }, { id: 'archived', label: '已归档' }, { id: 'all', label: '全部' }]" :key="option.id" :class="{ selected: status === option.id }" @click="status = option.id">{{ option.label }}</button>
</div>
<div class="toolbar-actions">
<label class="search-input">
<AppIcon name="search" :size="17" />
<input v-model="query" aria-label="搜索知识库" placeholder="搜索知识库名称、标签…" />
</label>
<button class="primary" :disabled="loading || busy" @click="openForm('create', $event)">
<AppIcon name="plus" :size="17" />新建知识库</button>
</div>
</div>
    <div v-if="loading" class="empty-state">正在加载知识库…</div>
    <section v-else-if="filtered.length" class="base-grid">
<button v-for="(base, index) in filtered" :key="base.id" class="base-card" :disabled="busy" @click="openBase(base)">
<div class="base-card-top">
<span class="base-symbol" :class="`tone-${index % 3}`">
<AppIcon name="book" :size="25" />
</span>
<span class="badge" :class="base.status === 'active' ? 'green' : ''">{{ base.status === 'active' ? '使用中' : '已归档' }}</span>
</div>
<h2>{{ base.name }}</h2>
<p>{{ base.description || '添加资料，构建专属知识空间。' }}</p>
<div class="tags">
<span v-for="tag in base.tags" :key="tag">{{ tag }}</span>
<span v-if="!base.tags.length">未设置标签</span>
</div>
<div class="base-card-footer">
<span>
<AppIcon name="file" :size="14" />{{ base.sourceCount }} 份资料<span class="separator">·</span>{{ base.chunkCount }} 切片</span>
<AppIcon name="arrow" :size="17" />
</div>
<small class="muted">更新于 {{ date(base.updatedAt) }}</small>
</button>
</section>
    <div v-else class="empty-state panel">
<span class="empty-icon">
<AppIcon name="book" :size="32" />
</span>
<h2>{{ bases.length ? '没有符合条件的知识库' : '让知识，从这里开始' }}</h2>
<p>{{ bases.length ? '尝试调整搜索词或切换知识库状态。' : '创建一个知识库，导入资料，验证检索，然后开始提问。' }}</p>
<button v-if="!bases.length" class="primary" @click="openForm('create', $event)">
<AppIcon name="plus" :size="16" />创建第一个知识库</button>
</div>
    <div class="workflow-strip">
<span class="small-label">知识工作流</span>
<span>
<b>01</b> 创建知识库</span>
<AppIcon name="arrow" :size="15" />
<span>
<b>02</b> 导入与切片</span>
<AppIcon name="arrow" :size="15" />
<span>
<b>03</b> 检索测试</span>
<AppIcon name="arrow" :size="15" />
<span>
<b>04</b> 引用式问答</span>
</div>
  </template>
  <template v-else>
    <div class="section-toolbar">
<button class="text-button" :disabled="busy" @click="selectedId = ''; notice = ''; error = ''">
<AppIcon name="back" :size="17" />全部知识库</button>
<div class="toolbar-actions">
<button :disabled="busy" @click="openForm('edit', $event)">编辑信息</button>
<button :disabled="busy" @click="archive">{{ selected.status === 'active' ? '归档' : '恢复使用' }}</button>
<button class="danger-text" :disabled="busy" @click="dialog = 'delete'">删除知识库</button>
</div>
</div>
    <section class="panel base-detail-header">
<span class="base-symbol">
<AppIcon name="book" :size="28" />
</span>
<div>
<h2>{{ selected.name }} <span class="badge" :class="selected.status === 'active' ? 'green' : ''">{{ selected.status === 'active' ? '使用中' : '已归档' }}</span>
</h2>
<p>{{ selected.description || '尚未添加描述' }}</p>
<div class="tags">
<span v-for="tag in selected.tags" :key="tag">{{ tag }}</span>
</div>
</div>
<div class="toolbar-actions">
<button :disabled="!selected.chunkCount || busy || selected.status === 'archived'" @click="emit('navigate', 'retrieval', selected.id)">检索测试</button>
<button class="primary" :disabled="!selected.chunkCount || busy || selected.status === 'archived'" @click="emit('navigate', 'chat', selected.id)">开始问答<AppIcon name="arrow" :size="16" />
</button>
</div>
</section>
    <div v-if="selected.status === 'archived'" class="notice">此知识库已归档。恢复使用后可继续导入、检索与问答。</div>
    <label v-else class="upload-zone" :class="{ disabled: busy }">
<input type="file" multiple accept=".txt,.md,.markdown,.pdf,.docx,.csv,.json" :disabled="busy" @change="upload" />
<span class="empty-icon">
<AppIcon name="upload" :size="25" />
</span>
<strong>{{ uploadProgress || '点击选择资料，自动解析并建立索引' }}</strong>
<span>支持 TXT、Markdown、PDF、DOCX、CSV、JSON · 单个文件不超过 20 MB</span>
</label>
    <section class="panel">
<div class="panel-header">
<div class="tabs">
<button :class="{ selected: detailTab === 'sources' }" @click="detailTab = 'sources'">资料来源 <span>{{ sources.length }}</span>
</button>
<button :class="{ selected: detailTab === 'chunks' }" @click="detailTab = 'chunks'">切片预览 <span>{{ chunks.length }}</span>
</button>
</div>
<span v-if="busy" class="muted">处理中…</span>
</div>
      <template v-if="detailTab === 'sources'">
<div v-if="!sources.length" class="empty-state">
<AppIcon name="file" :size="30" />
<p>还没有资料，导入后可在这里查看处理状态。</p>
</div>
<div v-else class="table-wrap">
<table>
<thead>
<tr>
<th>资料名称</th>
<th>处理状态</th>
<th>切片</th>
<th>导入时间</th>
<th>操作</th>
</tr>
</thead>
<tbody>
<tr v-for="source in sources" :key="source.id">
<td>
<div class="file-name">
<AppIcon name="file" :size="18" />{{ source.filename }}</div>
<small v-if="source.errorMessage" class="danger-text">{{ source.errorMessage }}</small>
</td>
<td>
<span class="badge" :class="source.status === 'failed' ? 'red' : source.errorMessage ? 'amber' : 'green'">{{ source.status === 'failed' ? '解析失败' : source.errorMessage ? '索引异常' : source.status === 'parsed' ? '解析完成' : '待解析' }}</span>
</td>
<td>{{ source.chunkCount }}</td>
<td>{{ date(source.createdAt) }}</td>
<td>
<div class="row-actions">
<button class="text-button" :disabled="busy || !source.chunkCount" @click="sourceFilter = source.id; detailTab = 'chunks'">查看</button>
<button class="text-button" :disabled="busy || !source.chunkCount" @click="rebuild(source)">重建索引</button>
<button class="text-button danger-text" :disabled="busy" @click="removingSource = source; dialog = 'remove'">移除</button>
</div>
</td>
</tr>
</tbody>
</table>
</div>
</template>
      <div v-else class="panel-body">
<label class="inline-field">资料筛选<AppSelect v-model="sourceFilter" label="资料筛选" :options="[{ value: '', label: '全部资料' }, ...sources.map(source => ({ value: source.id, label: source.filename }))]" />
</label>
<div v-if="!displayedChunks.length" class="empty-state">暂无切片</div>
<article v-for="chunk in displayedChunks" :key="chunk.id" class="chunk-card">
<div>
<span class="badge">Chunk {{ chunk.chunkIndex }}</span>
<span class="muted">{{ sources.find(source => source.id === chunk.sourceId)?.filename }} · {{ chunk.tokenCount }} 词元（本地估算）</span>
</div>
<p>{{ chunk.content }}</p>
</article>
</div>
    </section>
  </template>
  <MacDialog v-model="formVisible" :origin="formOrigin" :duration="680" :title="formMode === 'create' ? '新建知识库' : '编辑知识库'" :before-close="done => { if (!busy) done() }">
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>
    <form @submit.prevent="saveBase">
<label>知识库名称<input v-model="form.name" required maxlength="120" placeholder="例如：产品与研发知识库" autofocus />
</label>
<label>描述<textarea v-model="form.description" maxlength="800" rows="3" placeholder="介绍知识库的内容与适用场景" />
</label>
<label>标签<input v-model="form.tags" placeholder="用逗号分隔，例如：产品, 内部资料" />
</label>
<footer>
<button type="button" :disabled="busy" @click="dialog = ''">取消</button>
<button class="primary" :disabled="busy || !form.name.trim()">{{ busy ? '保存中…' : '保存知识库' }}</button>
</footer>
</form>
  </MacDialog>
  <AppDialog v-if="dialog === 'delete' || dialog === 'remove'" :title="dialog === 'delete' ? '删除知识库' : '移除资料'" @close="!busy && (dialog = '')">
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>
<p class="dialog-description">{{ dialog === 'delete' ? `确认删除「${selected?.name}」？此操作会删除知识库及其资料关联。` : `确认从此知识库移除「${removingSource?.filename}」？` }}</p>
<footer>
<button :disabled="busy" @click="dialog = ''">取消</button>
<button class="danger" :disabled="busy" @click="confirmDelete">{{ busy ? '处理中…' : '确认操作' }}</button>
</footer>
  </AppDialog>
</template>
