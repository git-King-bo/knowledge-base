import type { AgentCall, AgentTraceDetail } from './agentMonitor'
export type TimelineStep = AgentTraceDetail['stages'][number] & { call?: AgentCall; queryComparison?: { original: string; query: string; explanation: string } }
export function buildAgentTimeline(detail: AgentTraceDetail): TimelineStep[] {
  const used = new Set<string>()
  const steps: TimelineStep[] = detail.stages.map(step => {
    const call = detail.calls.find(item => item.id === step.data?.call_id)
    if (call) used.add(call.id)
    const query = step.data?.query
    const original = step.data?.original
    const queryComparison = step.name === '确定检索问题' && typeof query === 'string' && typeof original === 'string'
      ? { original, query, explanation: step.data?.reused_page_plan
        ? '复用上一轮分页查询，沿用原检索语句。'
        : detail.stages.some(item => item.name === '查询改写降级')
          ? '改写降级：使用保留上下文的检索文本。'
          : detail.stages.some(item => item.name === '查询改写结果')
            ? query === original ? '模型已判断，检索语句与用户原文一致。' : '模型结合历史对话，将当前输入改写为独立检索语句。'
            : query === original ? '本次使用用户原文检索，未改写。' : '以下为本次实际使用的检索语句。' }
      : undefined
    return { ...step, call, queryComparison }
  })
  for (const call of detail.calls) if (!used.has(call.id)) steps.push({ name: call.stage, start_ms: detail.duration_ms,
    duration_ms: call.latency_ms, status: call.success ? 'success' : 'error', call })
  return steps
}
export function modelMessages(text: string): { role: string; content: string }[] {
  try {
    const data: unknown = JSON.parse(text.replace(/^\[会话检索改写\]\s*/, ''))
    if (Array.isArray(data) && data.length && data.every(item => item && typeof item.role === 'string' && typeof item.content === 'string')) {
      const labels: Record<string, string> = { system: '系统指令', user: '用户消息 / 检索上下文', assistant: '历史回答', tool: '工具结果' }
      return data.map(item => ({ role: labels[item.role] || item.role, content: item.content }))
    }
  } catch { /* Existing logs may contain unstructured prompts. */ }
  return [{ role: '请求内容', content: prettyData(text) }]
}
export function prettyData(text: string) {
  try { return JSON.stringify(JSON.parse(text), null, 2) } catch { return text }
}
export const fieldLabels: Record<string, string> = {
  intent: '查询意图', operation: '统计操作', field: '目标字段', filters: '筛选条件', basis: '统计口径', distinct: '不同字段值数量', empty: '空值记录数', groups: '分组结果', code: '原因类型', question: '用户输入', parameters: '请求参数', history: '带入的历史对话', result: '执行结果', reason: '原因',
  knowledge_base_id: '知识库', provider: '服务类型', provider_id: '模型服务', model: '模型', input_turns: '传入轮数', retained_turns: '保留轮数', max_turns: '轮数上限', character_budget: '字符预算',
  original: '原始问题', query: '检索问题', rewritten: '改写结果', reused_page_plan: '复用分页计划', sheets: '人才数据表', unreadable_files: '无法读取的文件', source: '来源', plan: '查询计划', validation: '校验内容',
  matched: '匹配记录', rankable: '可排序记录', missing_values: '指标缺失数', sort_by: '排序字段', descending: '降序', unranked: '未进行数值排序', offset: '分页起点', returned: '返回数量', total: '总数量',
  records: '输出记录数', model_call: '模型调用', query_state: '查询状态', dimensions: '向量维度', terms: '词项及频次', candidate_count: '候选片段数', constraints: '候选范围限制', hit: '缓存命中',
  compatible_candidates: '兼容向量数', positive_candidates: '正分候选数', top_k: 'Top K', lexical_weight: '词项权重', embedding_weight: '向量权重', algorithm: '排序算法', scores: '选中片段的分数',
  sources: '来源明细', chunks: '片段 / 文本分块', web_sources: '网页来源数', table_summaries: '全表统计数', retrieval_query: '检索问题', messages: '模型消息数', characters: '字符数',
  protocol: '调用协议', message_count: '消息数', output_characters: '输出字符数', mode: '检索模式', history_turns: '历史轮数', continuation: '续写', reused_chunks: '复用知识片段', reused_web_sources: '复用网页',
}
const intentLabels: Record<string, string> = { filter: '字段筛选与排序', aggregate: '全表聚合统计', semantic: '语义检索', document: '文档问答', clarify: '需要补充条件', unsupported: '暂不支持' }
const operationLabels: Record<string, string> = { count: '记录计数', distinct_count: '字段去重计数', group_count: '字段分组计数' }
export function stageFacts(data?: Record<string, unknown>) {
  return Object.entries(data || {}).filter(([key]) => key !== 'call_id').map(([key, value]) => ({
    label: fieldLabels[key] || key, value: key === 'intent' && typeof value === 'string' ? intentLabels[value] || value : key === 'operation' && typeof value === 'string' ? operationLabels[value] || value : typeof value === 'boolean' ? value ? '是' : '否' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '无'),
  }))
}
