export type WebSearchMode = 'knowledge' | 'web' | 'auto'

export interface ProviderConfig {
  id: string
  name: string
  provider: string
  baseUrl: string
  apiKeyHint: string
  defaultModel: string
  isDefault: boolean
}

export interface ProviderModel {
  id: string
  providerId: string
  name: string
  contextWindow: number
  supportsTools: boolean
  supportsVision: boolean
  status: 'ready' | 'draft' | 'disabled'
}

export interface KnowledgeBase {
  id: string
  name: string
  description: string
  tags: string[]
  status: 'active' | 'archived'
  sourceCount: number
  chunkCount: number
  createdAt: string
  updatedAt: string
}

export interface KnowledgeSource {
  id: string
  filename: string
  mimeType: string
  status: 'uploaded' | 'parsed' | 'failed'
  chunkCount: number
  errorMessage: string | null
  createdAt: string
}

export interface KnowledgeChunk {
  id: string
  sourceId: string
  chunkIndex: number
  title: string | null
  content: string
  tokenCount: number
  score?: number | null
}

export interface KnowledgeSearchResult {
  query: string
  hits: KnowledgeChunk[]
}

export interface WebSource {
  index: number
  title: string
  url: string
  snippet: string
  provider: string
}

export interface KnowledgeUploadResult {
  source: KnowledgeSource
  chunks: KnowledgeChunk[]
  knowledgeBase?: KnowledgeBase | null
}

export interface AIActivityLog {
  id: string
  action: 'chat' | 'ask' | 'test' | 'embedding'
  providerId: string
  model: string
  success: boolean
  latencyMs: number
  requestText: string
  responseText: string
  createdAt: string
}

export interface ProviderTestResult {
  providerId: string
  ok: boolean
  message: string
  details?: Record<string, string> | null
}
