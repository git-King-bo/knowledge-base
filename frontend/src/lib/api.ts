import { readEventStream } from './sse'
import type {
  AIActivityLog,
  KnowledgeBase,
  KnowledgeChunk,
  KnowledgeSearchResult,
  KnowledgeSource,
  ProviderTestResult,
  ProviderConfig,
  ProviderModel,
  WebSearchMode,
  WebSource,
} from './types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001/api'

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

type ApiHeaderProvider = HeadersInit | (() => HeadersInit | Promise<HeadersInit>)
let apiHeaders: ApiHeaderProvider = {}

/** Supply application auth/tenant headers dynamically; never expose model provider keys here. */
export function setApiHeaders(headers: ApiHeaderProvider) { apiHeaders = headers }

export async function apiFetch(path: string, options: RequestInit = {}) {
  const headers = new Headers(typeof apiHeaders === 'function' ? await apiHeaders() : apiHeaders)
  new Headers(options.headers).forEach((value, key) => headers.set(key, value))
  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', headers.get('Content-Type') ?? 'application/json')
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
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

  return response
}

export async function request<T>(path: string, options: RequestInit = {}) {
  const response = await apiFetch(path, options)
  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
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

interface ApiWebSource {
  index: number
  title: string
  url: string
  snippet: string
  provider: string
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

function toWebSource(item: ApiWebSource): WebSource {
  return {
    index: item.index,
    title: item.title,
    url: item.url,
    snippet: item.snippet,
    provider: item.provider,
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

export async function rebuildKnowledgeSourceEmbeddings(sourceId: string, knowledgeBaseId?: string) {
  const data = await request<ApiKnowledgeSource>(
    `/knowledge/sources/${encodeURIComponent(sourceId)}/embeddings/rebuild${knowledgeBaseId ? `?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}` : ''}`,
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
  webSearchMode?: WebSearchMode
}) {
  const data = await request<{
    answer: string
    provider_id: string
    model: string
    sources: ApiKnowledgeChunk[]
    web_sources: ApiWebSource[]
  }>('/knowledge/ask', {
    method: 'POST',
    body: JSON.stringify({
      question: payload.question,
      knowledge_base_id: payload.knowledgeBaseId,
      provider_id: payload.providerId,
      model: payload.model,
      top_k: payload.topK ?? 5,
      web_search_mode: payload.webSearchMode ?? 'knowledge',
    }),
  })
  return {
    answer: data.answer,
    providerId: data.provider_id,
    model: data.model,
    sources: data.sources.map(toKnowledgeChunk),
    webSources: data.web_sources.map(toWebSource),
  }
}

export async function fetchAIActivityLogs(limit = 100) {
  const data = await request<ApiAIActivityLog[]>(`/ai/logs?limit=${limit}`)
  return data.map(toActivityLog)
}

export async function updateProvider(id: string, payload: { name: string; provider: string; baseUrl: string; defaultModel: string; apiKey?: string }) {
  return toProvider(await request<ApiProvider>(`/ai/providers/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify({ name: payload.name, provider: payload.provider, base_url: payload.baseUrl, default_model: payload.defaultModel, ...(payload.apiKey ? { api_key: payload.apiKey } : {}) }),
  }))
}


export interface KnowledgeStreamMeta {
  providerId: string
  model: string
  sources: KnowledgeChunk[]
  webSources: WebSource[]
}

export async function streamKnowledge(
  payload: Parameters<typeof askKnowledge>[0] & { continuation?: { answer: string; sources: KnowledgeChunk[]; webSources: WebSource[] } },
  options: {
    signal?: AbortSignal
    headers?: HeadersInit
    onMeta: (meta: KnowledgeStreamMeta) => void
    onDelta: (text: string) => void
  },
) {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'text/event-stream')
  headers.set('Content-Type', 'application/json')
  const response = await apiFetch('/knowledge/ask/stream', {
    method: 'POST', headers, signal: options.signal,
    body: JSON.stringify({
      question: payload.question, knowledge_base_id: payload.knowledgeBaseId,
      provider_id: payload.providerId, model: payload.model,
      top_k: payload.topK ?? 5, web_search_mode: payload.webSearchMode ?? 'knowledge',
      continuation: payload.continuation && {
        answer: payload.continuation.answer,
        sources: payload.continuation.sources.map(source => ({ id: source.id, source_id: source.sourceId,
          chunk_index: source.chunkIndex, title: source.title, content: source.content,
          token_count: source.tokenCount, score: source.score })),
        web_sources: payload.continuation.webSources,
      },
    }),
  })
  if (!response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
    throw new Error('服务器未返回有效的流式响应')
  }
  let complete = false
  let hasMeta = false
  let length = payload.continuation?.answer.length ?? 0
  let receivedText = false
  await readEventStream(response.body, event => {
    const value = JSON.parse(event.data)
    if (!value || typeof value !== 'object') throw new Error('流式响应格式错误')
    if (event.event === 'meta') {
      if (hasMeta || typeof value.provider_id !== 'string' || typeof value.model !== 'string'
        || !Array.isArray(value.sources) || !Array.isArray(value.web_sources)) throw new Error('来源信息格式错误')
      hasMeta = true
      options.onMeta({ providerId: value.provider_id, model: value.model,
        sources: value.sources.map(toKnowledgeChunk), webSources: value.web_sources.map(toWebSource) })
    } else if (event.event === 'delta') {
      if (!hasMeta || typeof value.text !== 'string') throw new Error('流式文本格式错误')
      receivedText ||= value.text.length > 0
      length += value.text.length
      if (length > 400_000) throw new Error('回答内容超过显示上限')
      options.onDelta(value.text)
    } else if (event.event === 'error') {
      throw new Error(typeof value.message === 'string' ? value.message : '回答生成失败')
    } else if (event.event === 'done') {
      if (!hasMeta || !receivedText) throw new Error('服务器未返回回答内容')
      complete = true
      return false
    }
  }, options.signal)
  if (!complete) throw new Error('连接提前断开，已接收的内容已保留，请重试。')
}
