// Only explicitly allow-listed question text is stored; never serialize a form or user object.
const ttl = 24 * 60 * 60 * 1000
export function draftKey(userId: string, mode: string) { return `kb:update-draft:${encodeURIComponent(userId)}:${mode}` }
export function writeQuestionDraft(storage: Storage, key: string, question: string, now = Date.now()) {
  try {
    if (!question.trim() || question.length > 20_000) return false
    storage.setItem(key, JSON.stringify({ schema: 1, question, savedAt: now }))
    return true
  } catch { return false }
}
export function takeQuestionDraft(storage: Storage, key: string, now = Date.now()): string | undefined {
  try {
    const raw = storage.getItem(key)
    if (!raw) return
    const data = JSON.parse(raw)
    storage.removeItem(key)
    if (data?.schema === 1 && typeof data.question === 'string' && data.question.length <= 20_000 &&
      typeof data.savedAt === 'number' && data.savedAt <= now && now - data.savedAt < ttl) return data.question
  } catch { /* Invalid or unavailable storage never prevents the workspace from opening. */ }
}
