<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import {
  askKnowledge,
  createKnowledgeBase as createKnowledgeBaseRequest,
  createDocument as createDocumentRequest,
  createModel as createModelRequest,
  createProvider as createProviderRequest,
  deleteKnowledgeBase as deleteKnowledgeBaseRequest,
  deleteDocument as deleteDocumentRequest,
  fetchAIActivityLogs,
  fetchCategories,
  fetchDocuments,
  fetchKnowledgeBaseChunks,
  fetchKnowledgeBaseSources,
  fetchKnowledgeBases,
  fetchKnowledgeChunks,
  fetchKnowledgeSources,
  fetchModels,
  fetchProviders,
  rebuildKnowledgeSourceEmbeddings,
  removeKnowledgeBaseSource,
  switchProvider,
  testProvider,
  chatWithProvider,
  updateDocument as updateDocumentRequest,
  updateKnowledgeBase as updateKnowledgeBaseRequest,
  uploadKnowledgeBaseFile,
} from './lib/api'
import { renderMarkdown } from './lib/renderMarkdown'
import { initialCategories, initialDocuments, initialProviders, initialProviderModels } from './lib/seed'
import type {
  AIActivityLog,
  DocumentItem,
  KnowledgeBase,
  KnowledgeChunk,
  KnowledgeSource,
  ProviderConfig,
  ProviderModel,
} from './lib/types'

type WorkspaceTab = 'documents' | 'import' | 'qa' | 'monitor'
type LogFilter = 'all' | AIActivityLog['action']
type MemoryView = 'list' | 'chat'
type BaseDialogMode = 'create' | 'edit'
type MemoryChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: KnowledgeChunk[]
}

const activeTab = ref<WorkspaceTab>('import')
const memoryView = ref<MemoryView>('list')
const baseDialogOpen = ref(false)
const baseDialogMode = ref<BaseDialogMode>('create')

const documents = ref<DocumentItem[]>(structuredClone(initialDocuments))
const categories = ref(structuredClone(initialCategories))
const providers = ref<ProviderConfig[]>(structuredClone(initialProviders))
const providerModels = ref<Record<string, ProviderModel[]>>(structuredClone(initialProviderModels))
const knowledgeBases = ref<KnowledgeBase[]>([])
const knowledgeSources = ref<KnowledgeSource[]>([])
const baseSources = ref<KnowledgeSource[]>([])
const baseChunks = ref<KnowledgeChunk[]>([])
const selectedBaseId = ref('')
const selectedSourceId = ref('')
const selectedSourceChunks = ref<KnowledgeChunk[]>([])
const searchResults = ref<KnowledgeChunk[]>([])
const activityLogs = ref<AIActivityLog[]>([])
const dialogFile = ref<File | null>(null)
const memoryChatMessages = ref<MemoryChatMessage[]>([])

const searchQuery = ref('')
const baseSearchQuery = ref('')
const askQuestion = ref('请根据已导入资料总结这批知识库的重点。')
const askAnswer = ref('')
const askSources = ref<KnowledgeChunk[]>([])
const activeSourceChunkId = ref('')
const chatPrompt = ref('请用一句话说明这个知识库当前能做什么。')
const chatResponse = ref('')
const importNotice = ref('准备导入资料')
const apiNotice = ref('本地演示数据')
const logFilter = ref<LogFilter>('all')
const isLoading = ref(false)
const isSaving = ref(false)
const isUploading = ref(false)
const isAsking = ref(false)
const isChatting = ref(false)
const retryingSourceId = ref('')
const backendConnected = ref(false)
let activeSourceTimer: ReturnType<typeof window.setTimeout> | null = null

const activeCategoryId = ref<string | 'all'>('all')
const activeDocumentId = ref(documents.value[0]?.id ?? '')
const activeProviderId = ref(providers.value.find((item) => item.isDefault)?.id ?? providers.value[0]?.id ?? '')

const providerDraft = reactive({
  name: '',
  provider: 'openai',
  baseUrl: 'https://api.openai.com/v1',
  apiKey: '',
  defaultModel: 'gpt-4.1-mini',
})

const baseDraft = reactive({
  name: '新知识库',
  description: '',
})

const baseEditor = reactive({
  name: '',
  description: '',
  tags: '',
})

const activeDocument = computed(
  () => documents.value.find((item) => item.id === activeDocumentId.value) ?? documents.value[0],
)

const categorySummaries = computed(() =>
  categories.value.map((category) => ({
    ...category,
    count: backendConnected.value
      ? category.count
      : documents.value.filter((document) => document.categoryId === category.id).length,
  })),
)

const filteredDocuments = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()

  return documents.value.filter((item) => {
    const matchCategory = activeCategoryId.value === 'all' || item.categoryId === activeCategoryId.value
    const matchKeyword =
      !keyword ||
      item.title.toLowerCase().includes(keyword) ||
      item.summary.toLowerCase().includes(keyword) ||
      item.content.toLowerCase().includes(keyword)

    return matchCategory && matchKeyword
  })
})

const currentProvider = computed(
  () => providers.value.find((item) => item.id === activeProviderId.value) ?? providers.value[0],
)

const currentModels = computed(() => providerModels.value[currentProvider.value?.id ?? ''] ?? [])
const markdownPreview = computed(() => renderMarkdown(activeDocument.value?.content ?? ''))
const selectedKnowledgeBase = computed(
  () => knowledgeBases.value.find((item) => item.id === selectedBaseId.value) ?? knowledgeBases.value[0],
)
const filteredLogs = computed(() =>
  logFilter.value === 'all' ? activityLogs.value : activityLogs.value.filter((item) => item.action === logFilter.value),
)
const dialogFileName = computed(() => dialogFile.value?.name ?? '未选择文件')
const filteredKnowledgeBases = computed(() => {
  const keyword = baseSearchQuery.value.trim().toLowerCase()
  if (!keyword) return knowledgeBases.value
  return knowledgeBases.value.filter((item) => {
    const haystack = `${item.name} ${item.description} ${item.tags.join(' ')}`.toLowerCase()
    return haystack.includes(keyword)
  })
})

function indexModels(models: ProviderModel[]) {
  return models.reduce<Record<string, ProviderModel[]>>((acc, model) => {
    acc[model.providerId] = [...(acc[model.providerId] ?? []), model]
    return acc
  }, {})
}

async function refreshLogs() {
  if (!backendConnected.value) return
  try {
    activityLogs.value = await fetchAIActivityLogs(200)
  } catch {
    apiNotice.value = '日志刷新失败'
  }
}

async function refreshKnowledgeSources() {
  if (!backendConnected.value) return
  try {
    const [nextBases, nextSources] = await Promise.all([fetchKnowledgeBases(), fetchKnowledgeSources()])
    knowledgeBases.value = nextBases
    knowledgeSources.value = nextSources
    if (!selectedBaseId.value || !knowledgeBases.value.some((item) => item.id === selectedBaseId.value)) {
      selectedBaseId.value = knowledgeBases.value[0]?.id ?? ''
    }
    if (!selectedSourceId.value && knowledgeSources.value[0]) {
      selectedSourceId.value = knowledgeSources.value[0].id
    }
    if (selectedBaseId.value) {
      await refreshSelectedBaseDetails()
    } else if (selectedSourceId.value) {
      selectedSourceChunks.value = await fetchKnowledgeChunks(selectedSourceId.value)
    }
  } catch {
    importNotice.value = '知识库刷新失败'
  }
}

async function refreshSelectedBaseDetails() {
  if (!backendConnected.value || !selectedBaseId.value) return
  try {
    const [sources, chunks] = await Promise.all([
      fetchKnowledgeBaseSources(selectedBaseId.value),
      fetchKnowledgeBaseChunks(selectedBaseId.value),
    ])
    baseSources.value = sources
    baseChunks.value = chunks
    syncBaseEditor()
  } catch {
    importNotice.value = '知识库详情刷新失败'
  }
}

function syncBaseEditor() {
  const target = selectedKnowledgeBase.value
  baseEditor.name = target?.name ?? ''
  baseEditor.description = target?.description ?? ''
  baseEditor.tags = target?.tags.join(', ') ?? ''
}

async function loadWorkspace() {
  isLoading.value = true
  try {
    const [nextCategories, nextDocuments, nextProviders, nextModels] = await Promise.all([
      fetchCategories(),
      fetchDocuments(),
      fetchProviders(),
      fetchModels(),
    ])
    categories.value = nextCategories
    documents.value = nextDocuments
    providers.value = nextProviders
    providerModels.value = indexModels(nextModels)
    activeDocumentId.value = nextDocuments[0]?.id ?? ''
    activeProviderId.value =
      nextProviders.find((item) => item.isDefault)?.id ?? nextProviders[0]?.id ?? ''
    backendConnected.value = true
    apiNotice.value = '已连接后端'
    await Promise.all([refreshKnowledgeSources(), refreshLogs()])
  } catch {
    backendConnected.value = false
    apiNotice.value = '后端未连接，当前使用本地演示数据'
  } finally {
    isLoading.value = false
  }
}

async function refreshAll() {
  await loadWorkspace()
}

async function refreshCategories() {
  if (!backendConnected.value) return
  try {
    categories.value = await fetchCategories()
  } catch {
    apiNotice.value = '分类刷新失败'
  }
}

function selectDocument(id: string) {
  activeDocumentId.value = id
}

function updateDocumentField(key: keyof DocumentItem, value: string) {
  const target = activeDocument.value
  if (!target) return
  target[key] = value as never
  target.updatedAt = new Date().toISOString()
}

async function createDocument() {
  const draft = {
    title: '未命名文档',
    summary: '先写一句概要，帮助别人快速理解这篇文档。',
    content: '# 新文档\n\n从这里开始写。',
    categoryId: categories.value[0]?.id ?? 'general',
    tags: ['draft'],
    status: 'draft' as const,
  }

  if (!backendConnected.value) {
    const localDocument: DocumentItem = {
      id: crypto.randomUUID(),
      ...draft,
      updatedAt: new Date().toISOString(),
    }
    documents.value.unshift(localDocument)
    activeDocumentId.value = localDocument.id
    return
  }

  isSaving.value = true
  try {
    const next = await createDocumentRequest(draft)
    documents.value.unshift(next)
    activeDocumentId.value = next.id
    apiNotice.value = '文档已创建'
    await refreshCategories()
  } catch {
    apiNotice.value = '创建失败，请检查后端服务'
  } finally {
    isSaving.value = false
  }
}

async function saveDocument() {
  const target = activeDocument.value
  if (!target) return

  if (!backendConnected.value) {
    target.updatedAt = new Date().toISOString()
    apiNotice.value = '本地已保存，未写入后端'
    return
  }

  isSaving.value = true
  try {
    const next = await updateDocumentRequest(target)
    const index = documents.value.findIndex((item) => item.id === next.id)
    if (index >= 0) {
      documents.value[index] = next
    }
    apiNotice.value = '文档已保存'
    await refreshCategories()
  } catch {
    apiNotice.value = '保存失败，请检查后端服务'
  } finally {
    isSaving.value = false
  }
}

async function deleteDocument(id: string) {
  if (backendConnected.value) {
    try {
      await deleteDocumentRequest(id)
      apiNotice.value = '文档已删除'
    } catch {
      apiNotice.value = '删除失败，请检查后端服务'
      return
    }
  }

  documents.value = documents.value.filter((item) => item.id !== id)
  if (activeDocumentId.value === id) {
    activeDocumentId.value = documents.value[0]?.id ?? ''
  }
  await refreshCategories()
}

async function activateProvider(id: string) {
  if (backendConnected.value) {
    try {
      await switchProvider(id)
      apiNotice.value = '默认模型已切换'
      await refreshLogs()
    } catch {
      apiNotice.value = '切换失败，请检查后端服务'
      return
    }
  }

  providers.value = providers.value.map((item) => ({ ...item, isDefault: item.id === id }))
  activeProviderId.value = id
}

async function addProvider() {
  if (!providerDraft.name.trim()) return

  let nextProvider: ProviderConfig

  if (backendConnected.value) {
    try {
      nextProvider = await createProviderRequest({
        name: providerDraft.name.trim(),
        provider: providerDraft.provider,
        baseUrl: providerDraft.baseUrl.trim(),
        apiKey: providerDraft.apiKey,
        defaultModel: providerDraft.defaultModel.trim(),
      })
      providerModels.value[nextProvider.id] = await fetchModels(nextProvider.id)
      apiNotice.value = '模型提供方已新增'
    } catch {
      apiNotice.value = '新增提供方失败，请检查后端服务'
      return
    }
  } else {
    const id = crypto.randomUUID()
    nextProvider = {
      id,
      name: providerDraft.name.trim(),
      provider: providerDraft.provider,
      baseUrl: providerDraft.baseUrl.trim(),
      apiKeyHint: providerDraft.apiKey ? '已填写' : '未填写',
      defaultModel: providerDraft.defaultModel.trim(),
      isDefault: providers.value.length === 0,
    }
    providerModels.value[id] = [
      {
        id: crypto.randomUUID(),
        providerId: id,
        name: providerDraft.defaultModel.trim(),
        contextWindow: 128000,
        supportsTools: true,
        supportsVision: false,
        status: 'ready',
      },
    ]
  }

  providers.value.push(nextProvider)
  if (nextProvider.isDefault) {
    activeProviderId.value = nextProvider.id
  }

  providerDraft.name = ''
  providerDraft.baseUrl = 'https://api.openai.com/v1'
  providerDraft.apiKey = ''
  providerDraft.defaultModel = 'gpt-4.1-mini'
}

async function addModel(providerId: string) {
  if (backendConnected.value) {
    try {
      const nextModel = await createModelRequest(providerId)
      providerModels.value[providerId] = [...(providerModels.value[providerId] ?? []), nextModel]
      apiNotice.value = '模型已新增'
    } catch {
      apiNotice.value = '新增模型失败，请检查后端服务'
    }
    return
  }

  const nextModel: ProviderModel = {
    id: crypto.randomUUID(),
    providerId,
    name: 'new-model',
    contextWindow: 32000,
    supportsTools: false,
    supportsVision: false,
    status: 'draft',
  }

  providerModels.value[providerId] = [...(providerModels.value[providerId] ?? []), nextModel]
}

async function testCurrentProvider() {
  if (!currentProvider.value || !backendConnected.value) return
  try {
    const result = await testProvider(currentProvider.value.id)
    apiNotice.value = result.ok ? `测试通过：${result.message}` : `测试失败：${result.message}`
    await refreshLogs()
  } catch {
    apiNotice.value = 'Provider 测试失败'
  }
}

async function sendChat() {
  if (!chatPrompt.value.trim()) return

  if (!backendConnected.value) {
    chatResponse.value = '后端未连接，无法调用模型。'
    return
  }

  isChatting.value = true
  chatResponse.value = ''
  try {
    const response = await chatWithProvider({
      providerId: currentProvider.value?.id,
      model: currentProvider.value?.defaultModel,
      content: chatPrompt.value.trim(),
    })
    chatResponse.value = response.content
    apiNotice.value = `模型已响应：${response.model}`
    await refreshLogs()
  } catch {
    chatResponse.value = '模型调用失败，请检查 Provider、模型名、API Key 或网络。'
  } finally {
    isChatting.value = false
  }
}

async function onDialogFilePicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  dialogFile.value = file ?? null
  input.value = ''
}

function openCreateBaseDialog() {
  baseDialogMode.value = 'create'
  baseDraft.name = ''
  baseDraft.description = ''
  dialogFile.value = null
  baseDialogOpen.value = true
}

async function openEditBaseDialog(base: KnowledgeBase) {
  selectedBaseId.value = base.id
  baseDialogMode.value = 'edit'
  baseEditor.name = base.name
  baseEditor.description = base.description
  baseEditor.tags = base.tags.join(', ')
  dialogFile.value = null
  baseDialogOpen.value = true
  await refreshSelectedBaseDetails()
}

function closeBaseDialog() {
  baseDialogOpen.value = false
  dialogFile.value = null
}

async function submitBaseDialog() {
  if (baseDialogMode.value === 'create') {
    if (!backendConnected.value || !baseDraft.name.trim()) return
    isSaving.value = true
    try {
      const next = await createKnowledgeBaseRequest({
        name: baseDraft.name.trim(),
        description: baseDraft.description.trim(),
        tags: [],
      })
      knowledgeBases.value = [next, ...knowledgeBases.value]
      selectedBaseId.value = next.id
      syncBaseEditor()
      if (dialogFile.value) {
        isUploading.value = true
        const result = await uploadKnowledgeBaseFile(next.id, dialogFile.value)
        knowledgeBases.value = knowledgeBases.value.map((item) =>
          item.id === result.knowledgeBase.id ? result.knowledgeBase : item,
        )
        baseSources.value = [result.source]
        baseChunks.value = result.chunks
      }
      importNotice.value = '知识库已创建'
      closeBaseDialog()
    } catch {
      importNotice.value = '创建知识库失败'
    } finally {
      isSaving.value = false
      isUploading.value = false
    }
    return
  }

  await saveKnowledgeBase()
  if (dialogFile.value && selectedBaseId.value) {
    isUploading.value = true
    try {
      const result = await uploadKnowledgeBaseFile(selectedBaseId.value, dialogFile.value)
      const index = knowledgeBases.value.findIndex((item) => item.id === result.knowledgeBase.id)
      if (index >= 0) knowledgeBases.value[index] = result.knowledgeBase
      await refreshSelectedBaseDetails()
    } catch {
      importNotice.value = '追加文件失败'
    } finally {
      isUploading.value = false
    }
  }
  closeBaseDialog()
}

async function removeBaseSource(sourceId: string) {
  if (!backendConnected.value || !selectedBaseId.value) return
  isSaving.value = true
  try {
    const next = await removeKnowledgeBaseSource(selectedBaseId.value, sourceId)
    const index = knowledgeBases.value.findIndex((item) => item.id === next.id)
    if (index >= 0) {
      knowledgeBases.value[index] = next
    }
    baseSources.value = baseSources.value.filter((item) => item.id !== sourceId)
    await refreshSelectedBaseDetails()
    importNotice.value = '文件已从记忆库移除'
  } catch {
    importNotice.value = '移除文件失败'
  } finally {
    isSaving.value = false
  }
}

async function retrySourceEmbedding(sourceId: string) {
  if (!backendConnected.value || retryingSourceId.value) return
  retryingSourceId.value = sourceId
  try {
    const next = await rebuildKnowledgeSourceEmbeddings(sourceId)
    baseSources.value = baseSources.value.map((item) => (item.id === next.id ? next : item))
    knowledgeSources.value = knowledgeSources.value.map((item) => (item.id === next.id ? next : item))
    importNotice.value = '向量化已完成'
  } catch (error) {
    await refreshSelectedBaseDetails()
    importNotice.value = error instanceof Error ? error.message : '向量化重试失败'
  } finally {
    retryingSourceId.value = ''
  }
}

async function deleteKnowledgeBase(base: KnowledgeBase) {
  const confirmed = window.confirm(`确认删除「${base.name}」吗？`)
  if (!confirmed || !backendConnected.value) return
  isSaving.value = true
  try {
    await deleteKnowledgeBaseRequest(base.id)
    knowledgeBases.value = knowledgeBases.value.filter((item) => item.id !== base.id)
    if (selectedBaseId.value === base.id) {
      selectedBaseId.value = knowledgeBases.value[0]?.id ?? ''
      baseSources.value = []
      baseChunks.value = []
      if (selectedBaseId.value) {
        await refreshSelectedBaseDetails()
      }
    }
    importNotice.value = '记忆库已删除'
  } catch {
    importNotice.value = '删除记忆库失败'
  } finally {
    isSaving.value = false
  }
}

async function saveKnowledgeBase() {
  const target = selectedKnowledgeBase.value
  if (!backendConnected.value || !target) return
  isSaving.value = true
  try {
    const next = await updateKnowledgeBaseRequest({
      id: target.id,
      name: baseEditor.name.trim(),
      description: baseEditor.description.trim(),
      tags: baseEditor.tags
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      status: target.status,
    })
    const index = knowledgeBases.value.findIndex((item) => item.id === next.id)
    if (index >= 0) {
      knowledgeBases.value[index] = next
    }
    importNotice.value = '知识库卡片已保存'
  } catch {
    importNotice.value = '保存知识库失败'
  } finally {
    isSaving.value = false
  }
}

async function selectKnowledgeBase(id: string) {
  selectedBaseId.value = id
  searchResults.value = []
  await refreshSelectedBaseDetails()
}

async function openKnowledgeChat(base: KnowledgeBase) {
  selectedBaseId.value = base.id
  memoryView.value = 'chat'
  activeTab.value = 'import'
  askAnswer.value = ''
  askSources.value = []
  memoryChatMessages.value = []
  await refreshSelectedBaseDetails()
}

function backToMemoryList() {
  memoryView.value = 'list'
  askQuestion.value = '请根据已导入资料总结这批知识库的重点。'
}

async function focusSourceChunk(chunkId: string) {
  activeSourceChunkId.value = chunkId
  await nextTick()
  const target = document.querySelector<HTMLElement>(`[data-chunk-id="${chunkId}"]`)
  target?.scrollIntoView({ behavior: 'smooth', block: 'center' })

  if (activeSourceTimer) {
    window.clearTimeout(activeSourceTimer)
  }
  activeSourceTimer = window.setTimeout(() => {
    if (activeSourceChunkId.value === chunkId) {
      activeSourceChunkId.value = ''
    }
  }, 2600)
}

function handleSourceRefClick(event: MouseEvent, sources: KnowledgeChunk[] = []) {
  const target = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>('[data-chunk-ref]')
  if (!target) return
  const chunkIndex = Number(target.dataset.chunkRef)
  const chunk = Number.isFinite(chunkIndex)
    ? sources.find((item) => item.chunkIndex === chunkIndex) ??
      baseChunks.value.find((item) => item.chunkIndex === chunkIndex)
    : null
  if (chunk) {
    void focusSourceChunk(chunk.id)
  }
}

async function runAsk() {
  if (!askQuestion.value.trim() || !backendConnected.value) return
  isAsking.value = true
  const question = askQuestion.value.trim()
  askAnswer.value = ''
  askSources.value = []
  activeSourceChunkId.value = ''
  memoryChatMessages.value.push({
    id: crypto.randomUUID(),
    role: 'user',
    content: question,
  })
  askQuestion.value = ''
  try {
    const result = await askKnowledge({
      question,
      knowledgeBaseId: selectedBaseId.value || undefined,
      providerId: currentProvider.value?.id,
      model: currentProvider.value?.defaultModel,
      topK: 5,
    })
    askAnswer.value = result.answer
    askSources.value = result.sources
    memoryChatMessages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: result.answer,
      sources: result.sources,
    })
    apiNotice.value = `问答完成：${result.model}`
    await refreshLogs()
  } catch {
    askAnswer.value = '问答失败，请检查导入资料、Provider 和网络。'
    memoryChatMessages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: askAnswer.value,
      sources: [],
    })
  } finally {
    isAsking.value = false
  }
}

watch(activeProviderId, async (providerId) => {
  if (!backendConnected.value || !providerId || providerModels.value[providerId]) return
  try {
    providerModels.value[providerId] = await fetchModels(providerId)
  } catch {
    apiNotice.value = '模型列表加载失败'
  }
})

watch(selectedSourceId, async (sourceId) => {
  if (!backendConnected.value || !sourceId) return
  try {
    selectedSourceChunks.value = await fetchKnowledgeChunks(sourceId)
  } catch {
    importNotice.value = '资料块加载失败'
  }
})

watch(selectedBaseId, async () => {
  syncBaseEditor()
})

onMounted(() => {
  void loadWorkspace()
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Knowledge Base</p>
        <h1>记忆库工作台</h1>
      </div>
      <div class="topbar-actions">
        <span class="status-pill" :class="{ online: backendConnected }">
          {{ isLoading ? '连接中' : apiNotice }}
        </span>
        <button type="button" class="ghost-btn" @click="refreshAll">刷新</button>
        <button v-if="activeTab === 'documents'" type="button" class="ghost-btn" :disabled="isSaving" @click="createDocument">
          新建文档
        </button>
        <button v-if="activeTab === 'documents'" type="button" class="primary-btn" :disabled="isSaving" @click="saveDocument">
          {{ isSaving ? '处理中' : '保存' }}
        </button>
      </div>
    </header>

    <main class="body-shell">
      <nav class="tabs-bar">
        <button class="tab-btn" :class="{ active: activeTab === 'documents' }" @click="activeTab = 'documents'">
          文档
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'import' }" @click="activeTab = 'import'; memoryView = 'list'">
          记忆库
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'qa' }" @click="activeTab = 'qa'">
          问答
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'monitor' }" @click="activeTab = 'monitor'">
          监控
        </button>
      </nav>

      <section class="body-scroll" :class="{ 'memory-chat-scroll': activeTab === 'import' && memoryView === 'chat' }">
        <section v-if="activeTab === 'documents'" class="tab-page docs-page">
          <aside class="panel sidebar">
            <div class="panel-head">
              <h2>分类</h2>
              <span class="count">{{ documents.length }}</span>
            </div>
            <button
              v-for="category in categorySummaries"
              :key="category.id"
              class="category-item"
              :class="{ active: activeCategoryId === category.id }"
              @click="activeCategoryId = category.id"
            >
              <span>{{ category.name }}</span>
              <strong>{{ category.count }}</strong>
            </button>
            <button class="category-item subtle" :class="{ active: activeCategoryId === 'all' }" @click="activeCategoryId = 'all'">
              <span>全部文档</span>
              <strong>{{ documents.length }}</strong>
            </button>

            <div class="panel-divider"></div>

            <div class="panel-head compact">
              <h2>模型提供方</h2>
              <span class="count">{{ providers.length }}</span>
            </div>
            <div class="provider-list">
              <button
                v-for="provider in providers"
                :key="provider.id"
                class="provider-item"
                :class="{ active: currentProvider?.id === provider.id }"
                @click="activeProviderId = provider.id"
              >
                <div>
                  <strong>{{ provider.name }}</strong>
                  <p>{{ provider.provider }} · {{ provider.defaultModel }}</p>
                </div>
                <span v-if="provider.isDefault" class="badge">默认</span>
              </button>
            </div>
          </aside>

          <section class="content-column">
            <section class="toolbar panel">
              <label class="search-box">
                <span>搜索文档</span>
                <input v-model="searchQuery" type="search" placeholder="标题、摘要、正文" />
              </label>
              <label class="inline-select">
                <span>当前模型</span>
                <select v-model="activeProviderId">
                  <option v-for="provider in providers" :key="provider.id" :value="provider.id">
                    {{ provider.name }}
                  </option>
                </select>
              </label>
            </section>

            <section class="doc-grid">
              <section class="panel doc-list-panel">
                <div class="panel-head">
                  <h2>文档列表</h2>
                  <span class="count">{{ filteredDocuments.length }}</span>
                </div>
                <article
                  v-for="document in filteredDocuments"
                  :key="document.id"
                  class="doc-card"
                  :class="{ active: activeDocumentId === document.id }"
                  @click="selectDocument(document.id)"
                >
                  <div class="doc-card-head">
                    <strong>{{ document.title }}</strong>
                    <span>{{ document.status }}</span>
                  </div>
                  <p>{{ document.summary }}</p>
                  <small>{{ document.updatedAt }}</small>
                </article>
              </section>

              <section class="panel editor-panel" v-if="activeDocument">
                <div class="panel-head">
                  <h2>文档编辑</h2>
                  <div class="editor-actions">
                    <button class="ghost-btn" type="button" :disabled="isSaving" @click="deleteDocument(activeDocument.id)">删除</button>
                    <button class="primary-btn" type="button" :disabled="isSaving" @click="saveDocument">
                      {{ isSaving ? '处理中' : '保存' }}
                    </button>
                  </div>
                </div>

                <label>
                  <span>标题</span>
                  <input :value="activeDocument.title" @input="updateDocumentField('title', ($event.target as HTMLInputElement).value)" />
                </label>
                <label>
                  <span>摘要</span>
                  <textarea :value="activeDocument.summary" @input="updateDocumentField('summary', ($event.target as HTMLTextAreaElement).value)" rows="3" />
                </label>
                <label>
                  <span>正文</span>
                  <textarea :value="activeDocument.content" @input="updateDocumentField('content', ($event.target as HTMLTextAreaElement).value)" rows="14" />
                </label>

                <div class="meta-row">
                  <label class="inline-select">
                    <span>分类</span>
                    <select :value="activeDocument.categoryId" @change="updateDocumentField('categoryId', ($event.target as HTMLSelectElement).value)">
                      <option v-for="category in categories" :key="category.id" :value="category.id">{{ category.name }}</option>
                    </select>
                  </label>
                  <label class="inline-select">
                    <span>状态</span>
                    <select :value="activeDocument.status" @change="updateDocumentField('status', ($event.target as HTMLSelectElement).value)">
                      <option value="draft">draft</option>
                      <option value="published">published</option>
                    </select>
                  </label>
                </div>
              </section>
            </section>

            <section class="panel preview-panel" v-if="activeDocument">
              <div class="panel-head">
                <h2>预览</h2>
                <span class="count">{{ activeDocument.tags.join(', ') }}</span>
              </div>
              <div class="markdown-preview" v-html="markdownPreview"></div>
            </section>
          </section>

          <aside class="panel right-rail">
            <div class="panel-head">
              <h2>模型配置</h2>
              <span class="count">{{ currentModels.length }}</span>
            </div>
            <div class="provider-form">
              <input v-model="providerDraft.name" type="text" placeholder="Provider 名称" />
              <input v-model="providerDraft.baseUrl" type="text" placeholder="Base URL" />
              <input v-model="providerDraft.defaultModel" type="text" placeholder="默认模型" />
              <input v-model="providerDraft.apiKey" type="password" placeholder="API Key" />
              <select v-model="providerDraft.provider">
                <option value="openai">openai</option>
                <option value="deepseek">deepseek</option>
                <option value="qwen">qwen</option>
                <option value="mock">mock</option>
              </select>
              <button class="primary-btn" type="button" :disabled="isSaving" @click="addProvider">新增提供方</button>
            </div>

            <div class="panel-divider"></div>

            <div class="panel-head compact">
              <h2>{{ currentProvider?.name ?? 'Provider' }}</h2>
              <button class="ghost-btn" type="button" @click="currentProvider && activateProvider(currentProvider.id)">
                设为默认
              </button>
              <button class="ghost-btn" type="button" @click="testCurrentProvider">测试连接</button>
            </div>
            <div class="model-list">
              <article v-for="model in currentModels" :key="model.id" class="model-item">
                <div>
                  <strong>{{ model.name }}</strong>
                  <p>{{ model.contextWindow }} ctx</p>
                </div>
                <span class="badge" :class="model.status">{{ model.status }}</span>
              </article>
            </div>
            <button class="ghost-btn full-width" type="button" @click="currentProvider && addModel(currentProvider.id)">
              新增模型
            </button>

            <div class="panel-divider"></div>

            <div class="panel-head compact">
              <h2>模型试聊</h2>
              <span class="count">{{ currentProvider?.defaultModel ?? 'model' }}</span>
            </div>
            <div class="chat-box">
              <textarea v-model="chatPrompt" rows="4" placeholder="输入一段问题" />
              <button class="primary-btn" type="button" :disabled="isChatting" @click="sendChat">
                {{ isChatting ? '调用中' : '发送' }}
              </button>
              <div v-if="chatResponse" class="chat-response rich-response" v-html="renderMarkdown(chatResponse)"></div>
            </div>
          </aside>
        </section>

        <section v-else-if="activeTab === 'import'" class="memory-page">
          <section v-if="memoryView === 'list'" class="memory-list-view">
            <div class="memory-head">
              <div>
                <h2>记忆库 <span>{{ knowledgeBases.length }}</span></h2>
                <p>{{ importNotice }}</p>
              </div>
              <button class="primary-btn create-memory-btn" type="button" @click="openCreateBaseDialog">
                <span>+</span>
                创建记忆库
              </button>
            </div>

            <div class="memory-toolbar">
              <label class="memory-search">
                <span>⌕</span>
                <input v-model="baseSearchQuery" type="search" placeholder="请输入名称或描述，支持模糊搜索" />
              </label>
              <button class="icon-btn" type="button" @click="refreshAll">↻</button>
            </div>

            <div v-if="filteredKnowledgeBases.length" class="memory-card-grid">
              <article
                v-for="base in filteredKnowledgeBases"
                :key="base.id"
                class="memory-card"
                :class="{ active: selectedBaseId === base.id }"
                @click="void selectKnowledgeBase(base.id)"
              >
                <button
                  class="memory-delete-btn"
                  type="button"
                  title="删除"
                  aria-label="删除记忆库"
                  @click.stop="void deleteKnowledgeBase(base)"
                >
                  ×
                </button>
                <div class="memory-card-main">
                  <div class="memory-icon">
                    <span></span>
                  </div>
                  <div>
                    <h3>{{ base.name }}</h3>
                    <dl>
                      <div>
                        <dt>描述</dt>
                        <dd>{{ base.description || '暂无描述' }}</dd>
                      </div>
                      <div>
                        <dt>ID</dt>
                        <dd>{{ base.id }}</dd>
                      </div>
                    </dl>
                  </div>
                </div>
                <p>更新于 {{ base.updatedAt.slice(0, 10) }}</p>
                <div class="memory-card-stats">
                  <span>{{ base.sourceCount }} 文件</span>
                  <span>{{ base.chunkCount }} 切片</span>
                </div>
                <div class="memory-card-actions">
                  <button class="memory-action chat-action" type="button" @click.stop="void openKnowledgeChat(base)">对话</button>
                  <button class="memory-action edit-action" type="button" @click.stop="void openEditBaseDialog(base)">编辑</button>
                </div>
              </article>
            </div>

            <div v-else class="memory-empty">
              <div class="empty-illustration">
                <span></span>
                <span></span>
                <span></span>
              </div>
              <h2>暂无记忆库</h2>
              <p>创建一个记忆库并上传文件后，就可以查看切片并开始提问。</p>
              <button class="primary-btn" type="button" @click="openCreateBaseDialog">创建记忆库</button>
            </div>
          </section>

          <section v-else class="memory-chat-view">
            <div class="memory-chat-head">
              <button class="ghost-btn" type="button" @click="backToMemoryList">返回</button>
              <div>
                <h2>{{ selectedKnowledgeBase?.name ?? '记忆库对话' }}</h2>
                <p>{{ selectedKnowledgeBase?.description || '当前记忆库' }}</p>
              </div>
              <button
                class="ghost-btn"
                type="button"
                :disabled="!selectedKnowledgeBase"
                @click="selectedKnowledgeBase && void openEditBaseDialog(selectedKnowledgeBase)"
              >
                编辑
              </button>
            </div>

            <div class="memory-chat-layout">
              <aside class="chunk-side">
                <div class="side-title">
                  <h3>分片详情</h3>
                  <span>{{ baseChunks.length }}</span>
                </div>
                <div class="source-summary">
                  <article v-for="source in baseSources" :key="source.id">
                    <strong>{{ source.filename }}</strong>
                    <span>{{ source.chunkCount }} chunks</span>
                  </article>
                </div>
                <div class="chunk-side-list">
                  <article
                    v-for="chunk in baseChunks"
                    :key="chunk.id"
                    class="chunk-row"
                    :class="{ focused: activeSourceChunkId === chunk.id }"
                    :data-chunk-id="chunk.id"
                  >
                    <div>
                      <strong>Chunk {{ chunk.chunkIndex }}</strong>
                      <span>{{ chunk.tokenCount }} tokens</span>
                    </div>
                    <p>{{ chunk.content }}</p>
                  </article>
                </div>
              </aside>

              <section class="chat-panel">
                <div class="chat-messages">
                  <div v-if="!memoryChatMessages.length" class="chat-empty">
                    <h3>针对当前记忆库提问</h3>
                    <p>{{ currentProvider?.defaultModel ?? 'model' }}</p>
                  </div>
                  <article
                    v-for="message in memoryChatMessages"
                    :key="message.id"
                    class="chat-message"
                    :class="message.role"
                    @click="handleSourceRefClick($event, message.sources)"
                  >
                    <div
                      class="rich-response"
                      v-html="renderMarkdown(message.content, { sourceRefs: message.role === 'assistant' })"
                    ></div>
                  </article>
                </div>
                <div class="chat-input-row">
                  <textarea v-model="askQuestion" rows="3" placeholder="向当前记忆库提问" />
                  <button class="primary-btn" type="button" :disabled="isAsking || !askQuestion.trim()" @click="runAsk">
                    {{ isAsking ? '思考中' : '发送' }}
                  </button>
                </div>
              </section>
            </div>
          </section>
        </section>

        <section v-else-if="activeTab === 'qa'" class="tab-page qa-page">
          <section class="panel">
            <div class="panel-head">
              <h2>知识库问答</h2>
              <span class="count">{{ selectedKnowledgeBase?.name ?? currentProvider?.defaultModel ?? 'model' }}</span>
            </div>
            <div class="provider-form">
              <textarea v-model="askQuestion" rows="5" placeholder="基于资料提问"></textarea>
              <button class="primary-btn" type="button" :disabled="isAsking" @click="runAsk">
                {{ isAsking ? '问答中' : '开始问答' }}
              </button>
            </div>
            <div v-if="askAnswer" class="answer-box">
              <div class="answer-title">回答</div>
              <div
                class="answer-content rich-response"
                @click="handleSourceRefClick($event, askSources)"
                v-html="renderMarkdown(askAnswer, { sourceRefs: true })"
              ></div>
            </div>
            <div v-if="askSources.length" class="source-detail">
              <div class="panel-divider"></div>
              <div class="panel-head compact">
                <h2>引用来源</h2>
                <span class="count">{{ askSources.length }}</span>
              </div>
              <div class="chunk-list">
                <article
                  v-for="chunk in askSources"
                  :key="chunk.id"
                  class="chunk-item"
                  :class="{ focused: activeSourceChunkId === chunk.id }"
                  :data-chunk-id="chunk.id"
                >
                  <div class="chunk-head">
                    <strong>Chunk {{ chunk.chunkIndex }}</strong>
                    <span>{{ chunk.score?.toFixed(3) ?? '0.000' }}</span>
                  </div>
                  <p>{{ chunk.content }}</p>
                </article>
              </div>
            </div>
          </section>
        </section>

        <section v-else class="tab-page monitor-page">
          <section class="panel">
            <div class="panel-head">
              <h2>模型输出监控</h2>
              <div class="monitor-actions">
                <label class="inline-select">
                  <span>筛选</span>
                  <select v-model="logFilter">
                    <option value="all">全部</option>
                    <option value="chat">chat</option>
                    <option value="ask">ask</option>
                    <option value="test">test</option>
                  </select>
                </label>
                <button class="ghost-btn" type="button" @click="refreshLogs">刷新日志</button>
              </div>
            </div>
            <div class="log-list">
              <article v-for="log in filteredLogs" :key="log.id" class="log-item">
                <div class="log-head">
                  <strong>{{ log.action }}</strong>
                  <span>{{ log.model }}</span>
                  <span :class="['badge', log.success ? 'ready' : 'draft']">{{ log.success ? 'ok' : 'fail' }}</span>
                </div>
                <p>{{ log.createdAt }} · {{ log.latencyMs }} ms</p>
                <div class="log-body">
                  <pre>{{ log.requestText }}</pre>
                  <pre>{{ log.responseText }}</pre>
                </div>
              </article>
            </div>
          </section>
        </section>
      </section>
    </main>

    <div v-if="baseDialogOpen" class="modal-backdrop" @click.self="closeBaseDialog">
      <section class="memory-modal">
        <div class="modal-head">
          <h2>{{ baseDialogMode === 'create' ? '创建记忆库' : '编辑记忆库' }}</h2>
          <button class="icon-btn" type="button" @click="closeBaseDialog">×</button>
        </div>
        <div class="modal-form">
          <label>
            <span>名称</span>
            <input
              v-if="baseDialogMode === 'create'"
              v-model="baseDraft.name"
              type="text"
              placeholder="例如：产品手册"
            />
            <input v-else v-model="baseEditor.name" type="text" placeholder="例如：产品手册" />
          </label>
          <label>
            <span>描述</span>
            <textarea
              v-if="baseDialogMode === 'create'"
              v-model="baseDraft.description"
              rows="4"
              placeholder="描述这个记忆库的用途和范围"
            />
            <textarea v-else v-model="baseEditor.description" rows="4" placeholder="描述这个记忆库的用途和范围" />
          </label>
          <label v-if="baseDialogMode === 'edit'">
            <span>标签</span>
            <input v-model="baseEditor.tags" type="text" placeholder="标签，用逗号分隔" />
          </label>
          <label>
            <span>文件</span>
            <input type="file" accept=".txt,.md,.markdown,.csv,.json,.docx,.pdf" @change="onDialogFilePicked" />
          </label>
          <div class="file-hint">{{ dialogFileName }}</div>
          <div v-if="baseDialogMode === 'edit'" class="modal-file-list">
            <div class="modal-file-title">
              <span>已上传文件</span>
              <strong>{{ baseSources.length }}</strong>
            </div>
            <article v-for="source in baseSources" :key="source.id" class="modal-file-item">
              <div>
                <strong>{{ source.filename }}</strong>
                <p>{{ source.status }} · {{ source.chunkCount }} chunks</p>
                <p v-if="source.errorMessage" class="file-error">{{ source.errorMessage }}</p>
              </div>
              <div class="modal-file-actions">
                <button
                  v-if="source.errorMessage"
                  class="ghost-btn"
                  type="button"
                  :disabled="retryingSourceId === source.id"
                  @click="retrySourceEmbedding(source.id)"
                >
                  {{ retryingSourceId === source.id ? '重试中' : '重试向量化' }}
                </button>
                <button class="ghost-btn danger-btn" type="button" :disabled="isSaving" @click="removeBaseSource(source.id)">
                  移除
                </button>
              </div>
            </article>
            <div v-if="!baseSources.length" class="file-hint">暂无上传文件</div>
          </div>
        </div>
        <div class="modal-actions">
          <button class="ghost-btn" type="button" @click="closeBaseDialog">取消</button>
          <button
            class="primary-btn"
            type="button"
            :disabled="
              isSaving ||
              isUploading ||
              (baseDialogMode === 'create' ? !baseDraft.name.trim() : !baseEditor.name.trim())
            "
            @click="submitBaseDialog"
          >
            {{ isSaving || isUploading ? '处理中' : baseDialogMode === 'create' ? '创建' : '保存' }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
