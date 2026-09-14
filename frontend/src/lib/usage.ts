import { request } from './api'
export interface UsageMetrics {
  requests: number
  failures: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cached_tokens: number
  unknown_requests: number
  avg_latency_ms: number
}
export interface UsageRecord {
  id: string
  created_at: string
  action: 'ask' | 'chat' | 'embedding'
  provider_id: string
  model: string
  success: boolean
  latency_ms: number
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  cached_tokens: number | null
  knowledge_base_id: string | null
  source: 'reported' | 'unknown' | 'mock'
}
export interface UsageOverview {
  summary: UsageMetrics
  daily: (UsageMetrics & { date: string })[]
  models: (UsageMetrics & { provider_id: string; model: string })[]
  records: UsageRecord[]
  total: number
  page: number
  page_size: number
}
export interface UsageFilters { days: number; providerId: string; model: string; action: string; baseId: string }
function params(filters: UsageFilters) {
  const query = new URLSearchParams({ days: String(filters.days), timezone_offset: String(-new Date().getTimezoneOffset()) })
  if (filters.providerId) query.set('provider_id', filters.providerId)
  if (filters.model.trim()) query.set('model', filters.model.trim())
  if (filters.action) query.set('action', filters.action)
  if (filters.baseId) query.set('knowledge_base_id', filters.baseId)
  return query
}
export const fetchUsage = (filters: UsageFilters, page = 1) => request<UsageOverview>(`/usage?${params(filters)}&page=${page}`)
export const usageExportUrl = (filters: UsageFilters) => `${import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001/api'}/usage/export?${params(filters)}`
