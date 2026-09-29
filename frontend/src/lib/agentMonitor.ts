import { request } from './api'
export interface AgentTrace {
  id: string; conversation_id: string | null; turn_id: string | null; question: string; status: string
  created_at: string; duration_ms: number; first_token_ms: number | null; knowledge_base_id: string | null
  call_count: number; unknown_calls: number; input_tokens: number | null; output_tokens: number | null; total_tokens: number; cached_tokens: number | null
}
export interface AgentCall {
  id: string; stage: string; action: string; provider_id: string; model: string; success: boolean; latency_ms: number
  input_tokens: number | null; output_tokens: number | null; total_tokens: number | null; cached_tokens: number | null
  source: string; request_text: string; response_text: string
}
export interface AgentTraceDetail extends AgentTrace {
  answer: string; error: string; request: Record<string, unknown>
  stages: { name: string; start_ms: number; duration_ms: number; status: string; data?: Record<string, unknown> }[]
  calls: AgentCall[]
}
export interface TraceConversation { id: string; title: string; has_traces: boolean }
export const fetchTraceConversations = () => request<TraceConversation[]>('/agent-monitor/conversations')
export const fetchAgentTraces = (conversation: string, status: string, page: number) => request<{items: AgentTrace[]; total: number; page_size: number; summary: { total_tokens: number; call_count: number; unknown_calls: number }}>(
  '/agent-monitor?' + new URLSearchParams({ conversation_id: conversation, status, page: String(page) }))
export const fetchAgentTrace = (id: string) => request<AgentTraceDetail>('/agent-monitor/' + encodeURIComponent(id))
