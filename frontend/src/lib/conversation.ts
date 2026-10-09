export type TalentQueryState = { knowledge_base_id: string | null; query: string; plan: Record<string, unknown>;
  snapshot_id?: string | null; offset: number; page_size: number; returned: number; has_more: boolean }
export type ConversationContext = { question: string; answer: string; query_state?: TalentQueryState }

/** Preserve complete pairs and the most recent context within the API budget. */
export function buildConversationHistory(turns: Array<ConversationContext & { status: string }>): ConversationContext[] {
  const result: ConversationContext[] = []
  let remaining = 24_000
  for (const turn of turns.filter(turn => turn.status === 'done' && turn.answer.trim()).slice(-12).reverse()) {
    const question = turn.question.slice(0, 5000)
    const answer = turn.answer.slice(0, 6000)
    const size = question.length + answer.length
    if (size > remaining) break
    result.unshift({ question, answer, ...(turn.query_state ? { query_state: turn.query_state } : {}) })
    remaining -= size
  }
  return result
}
