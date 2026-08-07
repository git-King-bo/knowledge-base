import type {
  AIActivityLog,
  DocumentItem,
  KnowledgeBase,
  KnowledgeCategory,
  KnowledgeChunk,
  KnowledgeSearchResult,
  KnowledgeSource,
  ProviderTestResult,
  ProviderConfig,
  ProviderModel,
} from './types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001/api'

interface ApiDocument {
  id: string
  title: string
  summary: string
  content: string
  category_id: string
  tags: string[]
  status: DocumentItem['status']
  updated_at: string
}

interface ApiCategory {
  id: string
  name: string
  count: number
}

interface ApiProvider {
  id: string
  name: string
  provider: string
  base_url: string
  api_key_hint: string
  default_model: string
  is_default: boolean
}

interface ApiModel {
  id: string
  provider_id: string
  name: string
  context_window: number
  supports_tools: boolean
  supports_vision: boolean
  status: ProviderModel['status']
}

async function request<T>(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', headers.get('Content-Type') ?? 'application/json')
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers,
    ...options,
  })

  if (!response.ok) {
    let detail = ''
    try {
      const payload = (await response.clone().json()) as { detail?: unknown }
      detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
    } catch {
      detail = await response.text()
    }
    throw new Error(detail || `Request failed: ${response.status} ${response.statusText}`)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

function toDocument(item: ApiDocument): DocumentItem {
  return {
    id: item.id,
    title: item.title,
    summary: item.summary,
    content: item.content,
    categoryId: item.category_id,
    tags: item.tags,
    status: item.status,
    updatedAt: item.updated_at,
  }
}

function toProvider(item: ApiProvider): ProviderConfig {
  return {
    id: item.id,
    name: item.name,
    provider: item.provider,
    baseUrl: item.base_url,
    apiKeyHint: item.api_key_hint,
    defaultModel: item.default_model,
    isDefault: item.is_default,
  }
}

function toModel(item: ApiModel): ProviderModel {
  return {
    id: item.id,
    providerId: item.provider_id,
    name: item.name,
    contextWindow: item.context_window,
    supportsTools: item.supports_tools,
    supportsVision: item.supports_vision,
    status: item.status,
  }
}

interface ApiKnowledgeSource {
  id: string
  filename: string
  mime_type: string
  status: KnowledgeSource['status']
  chunk_count: number
  error_message: string | null
  created_at: string
}

interface ApiKnowledgeBase {
  id: string
  name: string
  description: string
  tags: string[]
  status: KnowledgeBase['status']
  source_count: number
  chunk_count: number
  created_at: string
  updated_at: string
}

interface ApiKnowledgeChunk {
  id: string
  source_id: string
  chunk_index: number
  title: string | null
  content: string
  token_count: number
  score?: number | null
}

interface ApiAIActivityLog {
  id: string
  action: AIActivityLog['action']
  provider_id: string
  model: string
  success: boolean
  latency_ms: number
  request_text: string
  response_text: string
  created_at: string
}

interface ApiProviderTestResult {
  provider_id: string
  ok: boolean
  message: string
  details?: Record<string, string> | null
}

function toKnowledgeSource(item: ApiKnowledgeSource): KnowledgeSource {
  return {
    id: item.id,
    filename: item.filename,
    mimeType: item.mime_type,
    status: item.status,
    chunkCount: item.chunk_count,
    errorMessage: item.error_message,
    createdAt: item.created_at,
  }
}

function toKnowledgeBase(item: ApiKnowledgeBase): KnowledgeBase {
  return {
    id: item.id,
    name: item.name,
    description: item.description,
    tags: item.tags,
    status: item.status,
    sourceCount: item.source_count,
    chunkCount: item.chunk_count,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  }
}

function toKnowledgeChunk(item: ApiKnowledgeChunk): KnowledgeChunk {
  return {
    id: item.id,
    sourceId: item.source_id,
    chunkIndex: item.chunk_index,
    title: item.title,
    content: item.content,
    tokenCount: item.token_count,
    score: item.score,
  }
}

function toActivityLog(item: ApiAIActivityLog): AIActivityLog {
  return {
    id: item.id,
    action: item.action,
    providerId: item.provider_id,
    model: item.model,
    success: item.success,
    latencyMs: item.latency_ms,
    requestText: item.request_text,
    responseText: item.response_text,
    createdAt: item.created_at,
  }
}

function toProviderTestResult(item: ApiProviderTestResult): ProviderTestResult {
  return {
    providerId: item.provider_id,
    ok: item.ok,
    message: item.message,
    details: item.details ?? null,
  }
}

export async function fetchCategories() {
  const data = await request<ApiCategory[]>('/categories')
  return data satisfies KnowledgeCategory[]
}

export async function fetchDocuments(params: { q?: string; categoryId?: string } = {}) {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  if (params.categoryId) query.set('category_id', params.categoryId)
  const suffix = query.size ? `?${query.toString()}` : ''
  const data = await request<ApiDocument[]>(`/documents${suffix}`)
  return data.map(toDocument)
}

export async function createDocument(payload: Omit<DocumentItem, 'id' | 'updatedAt'>) {
  const data = await request<ApiDocument>('/documents', {
    method: 'POST',
    body: JSON.stringify({
      title: payload.title,
      summary: payload.summary,
      content: payload.content,
      category_id: payload.categoryId,
      tags: payload.tags,
      status: payload.status,
    }),
  })
  return toDocument(data)
}

export async function updateDocument(payload: DocumentItem) {
  const data = await request<ApiDocument>(`/documents/${payload.id}`, {
    method: 'PUT',
    body: JSON.stringify({
      title: payload.title,
      summary: payload.summary,
      content: payload.content,
      category_id: payload.categoryId,
      tags: payload.tags,
      status: payload.status,
    }),
  })
  return toDocument(data)
}

export async function deleteDocument(id: string) {
  await request<void>(`/documents/${id}`, { method: 'DELETE' })
}

export async function fetchProviders() {
  const data = await request<ApiProvider[]>('/ai/providers')
  return data.map(toProvider)
}

export async function createProvider(payload: {
  name: string
  provider: string
  baseUrl: string
  apiKey?: string
  defaultModel: string
}) {
  const data = await request<ApiProvider>('/ai/providers', {
    method: 'POST',
    body: JSON.stringify({
      name: payload.name,
      provider: payload.provider,
      base_url: payload.baseUrl,
      api_key: payload.apiKey || null,
      default_model: payload.defaultModel,
    }),
  })
  return toProvider(data)
}

export async function switchProvider(id: string) {
  const data = await request<ApiProvider>(`/ai/providers/${id}/switch`, { method: 'POST' })
  return toProvider(data)
}

export async function testProvider(id: string) {
  const data = await request<ApiProviderTestResult>(`/ai/providers/${id}/test`, { method: 'POST' })
  return toProviderTestResult(data)
}

export async function fetchModels(providerId?: string) {
  const suffix = providerId ? `?provider_id=${encodeURIComponent(providerId)}` : ''
  const data = await request<ApiModel[]>(`/ai/models${suffix}`)
  return data.map(toModel)
}

export async function createModel(providerId: string) {
  const data = await request<ApiModel>(`/ai/providers/${providerId}/models`, {
    method: 'POST',
    body: JSON.stringify({
      name: 'new-model',
      context_window: 32000,
      supports_tools: false,
      supports_vision: false,
      status: 'draft',
    }),
  })
  return toModel(data)
}

export async function chatWithProvider(payload: {
  providerId?: string
  model?: string
  content: string
}) {
  return request<{ provider_id: string; model: string; content: string }>('/ai/chat', {
    method: 'POST',
    body: JSON.stringify({
      provider_id: payload.providerId,
      model: payload.model,
      messages: [
        {
          role: 'user',
          content: payload.content,
        },
      ],
    }),
  })
}

export async function uploadKnowledgeFile(file: File) {
  const formData = new FormData()
  formData.set('file', file)
  const response = await request<{
    source: ApiKnowledgeSource
    chunks: ApiKnowledgeChunk[]
    knowledge_base?: ApiKnowledgeBase | null
  }>('/knowledge/upload', {
    method: 'POST',
    body: formData,
  })
  return {
    source: toKnowledgeSource(response.source),
    chunks: response.chunks.map(toKnowledgeChunk),
    knowledgeBase: response.knowledge_base ? toKnowledgeBase(response.knowledge_base) : null,
  }
}

export async function fetchKnowledgeBases() {
  const data = await request<ApiKnowledgeBase[]>('/knowledge/bases')
  return data.map(toKnowledgeBase)
}

export async function createKnowledgeBase(payload: { name: string; description?: string; tags?: string[] }) {
  const data = await request<ApiKnowledgeBase>('/knowledge/bases', {
    method: 'POST',
    body: JSON.stringify({
      name: payload.name,
      description: payload.description ?? '',
      tags: payload.tags ?? [],
    }),
  })
  return toKnowledgeBase(data)
}

export async function updateKnowledgeBase(payload: {
  id: string
  name?: string
  description?: string
  tags?: string[]
  status?: KnowledgeBase['status']
}) {
  const data = await request<ApiKnowledgeBase>(`/knowledge/bases/${encodeURIComponent(payload.id)}`, {
    method: 'PUT',
    body: JSON.stringify({
      name: payload.name,
      description: payload.description,
      tags: payload.tags,
      status: payload.status,
    }),
  })
  return toKnowledgeBase(data)
}

export async function deleteKnowledgeBase(id: string) {
  await request<void>(`/knowledge/bases/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export async function uploadKnowledgeBaseFile(knowledgeBaseId: string, file: File) {
  const formData = new FormData()
  formData.set('file', file)
  const response = await request<{
    source: ApiKnowledgeSource
    chunks: ApiKnowledgeChunk[]
    knowledge_base: ApiKnowledgeBase
  }>(`/knowledge/bases/${encodeURIComponent(knowledgeBaseId)}/upload`, {
    method: 'POST',
    body: formData,
  })
  return {
    source: toKnowledgeSource(response.source),
    chunks: response.chunks.map(toKnowledgeChunk),
    knowledgeBase: toKnowledgeBase(response.knowledge_base),
  }
}

export async function fetchKnowledgeBaseSources(knowledgeBaseId: string) {
  const data = await request<ApiKnowledgeSource[]>(
    `/knowledge/bases/${encodeURIComponent(knowledgeBaseId)}/sources`,
  )
  return data.map(toKnowledgeSource)
}

export async function fetchKnowledgeBaseChunks(knowledgeBaseId: string) {
  const data = await request<ApiKnowledgeChunk[]>(
    `/knowledge/bases/${encodeURIComponent(knowledgeBaseId)}/chunks`,
  )
  return data.map(toKnowledgeChunk)
}

export async function removeKnowledgeBaseSource(knowledgeBaseId: string, sourceId: string) {
  const data = await request<ApiKnowledgeBase>(
    `/knowledge/bases/${encodeURIComponent(knowledgeBaseId)}/sources/${encodeURIComponent(sourceId)}`,
    { method: 'DELETE' },
  )
  return toKnowledgeBase(data)
}

export async function fetchKnowledgeSources() {
  const data = await request<ApiKnowledgeSource[]>('/knowledge/sources')
  return data.map(toKnowledgeSource)
}

export async function fetchKnowledgeChunks(sourceId: string) {
  const data = await request<ApiKnowledgeChunk[]>(`/knowledge/sources/${encodeURIComponent(sourceId)}/chunks`)
  return data.map(toKnowledgeChunk)
}

export async function rebuildKnowledgeSourceEmbeddings(sourceId: string) {
  const data = await request<ApiKnowledgeSource>(
    `/knowledge/sources/${encodeURIComponent(sourceId)}/embeddings/rebuild`,
    { method: 'POST' },
  )
  return toKnowledgeSource(data)
}

export async function searchKnowledge(query: string, topK = 5, knowledgeBaseId?: string) {
  const params = new URLSearchParams({ q: query, top_k: String(topK) })
  if (knowledgeBaseId) params.set('knowledge_base_id', knowledgeBaseId)
  const data = await request<KnowledgeSearchResult & { hits: ApiKnowledgeChunk[] }>(
    `/knowledge/search?${params.toString()}`,
  )
  return {
    query: data.query,
    hits: data.hits.map(toKnowledgeChunk),
  }
}

export async function askKnowledge(payload: {
  question: string
  knowledgeBaseId?: string
  providerId?: string
  model?: string
  topK?: number
}) {
  const data = await request<{ answer: string; provider_id: string; model: string; sources: ApiKnowledgeChunk[] }>(
    '/knowledge/ask',
    {
      method: 'POST',
      body: JSON.stringify({
        question: payload.question,
        knowledge_base_id: payload.knowledgeBaseId,
        provider_id: payload.providerId,
        model: payload.model,
        top_k: payload.topK ?? 5,
      }),
    },
  )
  return {
    answer: data.answer,
    providerId: data.provider_id,
    model: data.model,
    sources: data.sources.map(toKnowledgeChunk),
  }
}

export async function fetchAIActivityLogs(limit = 100) {
  const data = await request<ApiAIActivityLog[]>(`/ai/logs?limit=${limit}`)
  return data.map(toActivityLog)
}
