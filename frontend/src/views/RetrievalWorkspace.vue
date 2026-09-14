<script setup lang="ts">
import { computed, reactive, ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { streamKnowledge, searchKnowledge, fetchKnowledgeBaseSources } from '../lib/api'
import type { KnowledgeBase, KnowledgeChunk, KnowledgeSource, ProviderConfig, WebSearchMode, WebSource } from '../lib/types'
import { renderMarkdown, safeExternalUrl, escapeHtml } from '../lib/renderMarkdown'
import { createFrameBuffer } from '../lib/frameBuffer'
import { useTask } from '../composables/useTask'
import AppIcon from '../components/AppIcon.vue'
import AppSelect from '../components/AppSelect.vue'
import '../styles/knowledge-chat.css'
const props = defineProps<{ mode: 'retrieval' | 'chat'; bases: KnowledgeBase[]; providers: ProviderConfig[]; initialBaseId: string }>()
const { busy, error, run } = useTask()
const baseId = ref(props.initialBaseId)
const mobileSettingsOpen = ref(false)
const providerId = ref('')
const model = ref('')
const question = ref('')
const topK = ref(5)
const webMode = ref<WebSearchMode>('knowledge')
const sources = ref<KnowledgeSource[]>([])
const hits = ref<KnowledgeChunk[]>([])
const searched = ref(false)
const elapsed = ref(0)
const searchedQuery = ref('')
type AskPayload = Parameters<typeof streamKnowledge>[0]
type ChatTurn = { id: number; question: string; answer: string; html: string;
  sources: KnowledgeChunk[]; webSources: WebSource[]; model: string; request: AskPayload;
  status: 'waiting' | 'streaming' | 'done' | 'stopped' | 'error' }
const messages = ref<ChatTurn[]>([])
const scrollContainer = ref<HTMLElement>()
const followOutput = ref(true)
let streamController: AbortController | undefined
let streamBuffer: ReturnType<typeof createFrameBuffer> | undefined
let disposed = false
function stopGeneration() { streamController?.abort() }
function trackScroll() {
  const container = scrollContainer.value
  if (container) followOutput.value = container.scrollHeight - container.scrollTop - container.clientHeight < 80
}
onBeforeUnmount(() => { disposed = true; stopGeneration(); streamBuffer?.dispose() })
const activeCitation = ref<{ messageId: number; kind: 'chunk' | 'web'; index: number }>()
const citationNotice = ref<{ messageId: number; text: string }>()
let citationTimer: ReturnType<typeof setTimeout> | undefined

function clearCitation() {
  clearTimeout(citationTimer)
  activeCitation.value = undefined
  citationNotice.value = undefined
}

async function focusCitation(event: MouseEvent, messageId: number) {
  const button = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>('.source-inline-ref')
  if (!button) return
  const kind = button.dataset.webRef !== undefined ? 'web' : 'chunk'
  const index = Number(kind === 'web' ? button.dataset.webRef : button.dataset.chunkRef)
  if (!Number.isInteger(index) || index < 0) return
  const turn = (event.currentTarget as HTMLElement).closest('.conversation-turn')
  const details = turn?.querySelector<HTMLDetailsElement>('.answer-sources')
  const target = details?.querySelector<HTMLElement>(`[data-${kind}-index="${index}"]`)
  clearCitation()
  if (!details || !target) {
    citationNotice.value = { messageId, text: `本次回答未返回 ${kind === 'web' ? 'Web' : 'Chunk'} ${index} 的来源内容。` }
    return
  }
  followOutput.value = false
  details.open = true
  activeCitation.value = { messageId, kind, index }
  await nextTick()
  target.focus({ preventScroll: true })
  target.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' })
  citationTimer = setTimeout(() => { activeCitation.value = undefined }, 2600)
}

onBeforeUnmount(clearCitation)
const activeBases = computed(() => props.bases.filter(base => base.status === 'active'))
const ready = computed(() => Boolean(baseId.value && question.value.trim() && (props.mode === 'retrieval' || providerId.value)))
watch(() => props.bases, () => { if (!activeBases.value.some(base => base.id === baseId.value)) baseId.value = activeBases.value[0]?.id || '' }, { immediate: true })
watch(() => props.providers, () => { if (!providerId.value) providerId.value = props.providers.find(provider => provider.isDefault)?.id || props.providers[0]?.id || '' }, { immediate: true })
watch(providerId, () => { model.value = props.providers.find(provider => provider.id === providerId.value)?.defaultModel || '' }, { immediate: true })
watch(baseId, async (id) => {
  clearCitation()
  hits.value = []; searched.value = false; messages.value = []; sources.value = []
  if (!id) return
  try { const list = await fetchKnowledgeBaseSources(id); if (baseId.value === id) sources.value = list }
  catch (cause) { if (baseId.value === id) error.value = cause instanceof Error ? cause.message : '读取来源失败' }
}, { immediate: true })
const selectedBase = computed(() => activeBases.value.find(base => base.id === baseId.value))
const selectedProvider = computed(() => props.providers.find(provider => provider.id === providerId.value))
const composerInput = ref<HTMLTextAreaElement>()
const suggestions = [
  { icon: 'summary', title: '提炼核心内容', description: '快速掌握资料的重点与结论', question: '请总结资料中的核心内容与关键结论。' },
  { icon: 'workflow', title: '梳理操作流程', description: '将知识整理为清晰的执行步骤', question: '资料中有哪些操作流程和注意事项？请分步骤说明。' },
  { icon: 'compare', title: '对比关键差异', description: '归纳不同方案的异同与适用场景', question: '请对比资料中提到的不同方案，并说明关键差异与适用场景。' },
  { icon: 'checklist', title: '生成行动清单', description: '把资料中的建议变成待办事项', question: '请根据资料整理一份行动清单，并标注相关依据。' },
]
function useSuggestion(value: string) {
  question.value = value
  composerInput.value?.focus()
}
const sourceName = (id: string) => sources.value.find(source => source.id === id)?.filename || id
async function generateTurn(turn: ChatTurn, continuing = false) {
      const previousAnswer = turn.answer
      turn.status = 'waiting'
      followOutput.value = true
      const controller = new AbortController()
      streamController = controller
      const buffer = createFrameBuffer((text, final) => {
        turn.answer = text
        try { turn.html = renderMarkdown(text, { sourceRefs: true, streaming: !final }) }
        catch { turn.html = `<p>${escapeHtml(text)}</p>` }
        if (turn.status === 'waiting' && text) turn.status = 'streaming'
        void nextTick(() => {
          if (!disposed && followOutput.value && scrollContainer.value) {
            scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight
          }
        })
      })
      if (previousAnswer) buffer.append(previousAnswer)
      streamBuffer = buffer
      try {
        await streamKnowledge({ ...turn.request,
          continuation: continuing && (turn.sources.length || turn.webSources.length)
            ? { answer: previousAnswer, sources: turn.sources, webSources: turn.webSources } : undefined,
        }, {
          signal: controller.signal,
          onMeta(meta) { turn.request.providerId = meta.providerId; turn.request.model = meta.model; Object.assign(turn, { sources: meta.sources, webSources: meta.webSources, model: meta.model }) },
          onDelta(text) { buffer.append(text) },
        })
        turn.status = 'done'
      } catch (cause) {
        turn.status = controller.signal.aborted ? 'stopped' : 'error'
        if (!controller.signal.aborted) throw cause
      } finally {
        await buffer.finish()
        if (streamController === controller) { streamController = undefined; streamBuffer = undefined }
      }
}
function continueGeneration(turn: ChatTurn) {
  if (busy.value || !['stopped', 'error'].includes(turn.status)) return
  void run(() => generateTurn(turn, true))
}
function submit() {
  if (!ready.value || busy.value) return
  void run(async () => {
    const value = question.value.trim()
    const started = performance.now()
    if (props.mode === 'retrieval') {
      searched.value = false; hits.value = []
      const result = await searchKnowledge(value, topK.value, baseId.value)
      hits.value = result.hits; searched.value = true; searchedQuery.value = value
    } else {
      const turn = reactive<ChatTurn>({ id: Date.now(), question: value, answer: '', html: '',
        sources: [], webSources: [], model: model.value, status: 'waiting',
        request: { question: value, knowledgeBaseId: baseId.value, providerId: providerId.value,
          model: model.value || undefined, topK: topK.value, webSearchMode: webMode.value } })
      messages.value.push(turn)
      question.value = ''
      await generateTurn(turn)
    }
    elapsed.value = Math.round(performance.now() - started)
  })
}
</script>
<template>
  <div v-if="error" class="notice error" role="alert">{{ error }}</div>
  <div class="retrieval-layout" :class="{ 'qa-layout': mode === 'chat' }">
    <aside v-if="mode === 'retrieval'" class="panel config-panel">
<div class="panel-header">
<h2>{{ mode === 'retrieval' ? '检索配置' : '问答配置' }}</h2>
<AppIcon name="settings" :size="18" />
</div>
<div class="panel-body">
<label>选择知识库<AppSelect v-model="baseId" label="选择知识库" placeholder="请选择知识库" :disabled="busy" :options="activeBases.map(base => ({ value: base.id, label: base.name }))" />
</label>
<p v-if="!activeBases.length" class="muted">请先创建知识库并导入资料。</p>
<label>召回数量 <span class="range-value">Top {{ topK }}</span>
<input v-model.number="topK" type="range" min="1" max="12" :disabled="busy" />
<span class="range-labels">
<span>1 段</span>
<span>12 段</span>
</span>
</label>

<div class="config-note">
<AppIcon name="layers" :size="20" />
<strong>从召回到可信答案</strong>
<p>先检查相关切片，再验证答案引用。资料内容更新后，可重新导入并重建索引。</p>
</div>
</div>
</aside>
    <aside v-else class="panel qa-settings" :class="{ 'is-expanded': mobileSettingsOpen }" aria-label="问答设置">
      <header class="qa-panel-header">
        <span class="qa-header-icon"><AppIcon name="settings" :size="19" /></span>
        <div><h2>问答设置</h2><p>为本次提问选择知识与模型</p></div>
        <button class="qa-config-toggle" :aria-expanded="mobileSettingsOpen" aria-controls="qa-settings-body" @click="mobileSettingsOpen = !mobileSettingsOpen">{{ mobileSettingsOpen ? '收起' : '展开' }}<AppIcon :name="mobileSettingsOpen ? 'close' : 'settings'" :size="14" /></button>
      </header>
      <div id="qa-settings-body" class="qa-settings-body">
        <section class="qa-setting-group">
          <h3><AppIcon name="book" :size="16" />知识来源<span>01</span></h3>
          <label>知识库<AppSelect v-model="baseId" label="选择知识库" placeholder="请选择知识库" :disabled="busy" :options="activeBases.map(base => ({ value: base.id, label: base.name }))" /></label>
          <div v-if="selectedBase" class="qa-base-stats">
            <span><AppIcon name="file" :size="14" /><strong>{{ selectedBase.sourceCount }}</strong>份资料</span>
            <span><AppIcon name="layers" :size="14" /><strong>{{ selectedBase.chunkCount }}</strong>个切片</span>
          </div>
          <p v-else class="qa-field-note">请先创建知识库并导入资料。</p>
        </section>
        <section class="qa-setting-group">
          <h3><AppIcon name="spark" :size="16" />模型配置<span>02</span></h3>
          <label>模型服务<AppSelect v-model="providerId" label="模型服务" placeholder="选择模型服务" :disabled="busy" :options="providers.map(provider => ({ value: provider.id, label: provider.name + (provider.isDefault ? '（默认）' : '') }))" /></label>
          <label>模型名称<input v-model="model" :disabled="busy" placeholder="输入模型名称" /></label>
          <p v-if="selectedProvider?.provider === 'mock'" class="qa-field-note">Mock 模式仅返回测试内容，不产生真实 Token 用量。</p>
        </section>
        <section class="qa-setting-group">
          <h3><AppIcon name="search" :size="16" />检索配置<span>03</span></h3>
          <label class="qa-range-field"><span>召回数量<output>Top {{ topK }}</output></span><input v-model.number="topK" type="range" min="1" max="12" :disabled="busy" /><span class="range-labels"><span>1 段</span><span>12 段</span></span></label>
          <label>资料范围<AppSelect v-model="webMode" label="资料范围" :disabled="busy" :options="[{ value: 'knowledge', label: '仅知识库' }, { value: 'auto', label: '按需补充联网搜索' }, { value: 'web', label: '知识库 + 联网搜索' }]" /></label>
          <p v-if="webMode !== 'knowledge'" class="qa-field-note">联网搜索需配置搜索服务；未返回网页时仅使用知识库资料。</p>
        </section>
      </div>
      <footer class="qa-settings-footer"><AppIcon name="link" :size="16" /><div><strong>每一份答案，都有迹可循</strong><p>点击回答中的引用，可定位原始资料。</p></div></footer>
    </aside>
    <section v-if="mode === 'retrieval'" class="panel retrieval-results">
<div class="panel-header">
<h2>检索测试</h2>
<span class="badge">只检索，不生成答案</span>
</div>
<form class="panel-body retrieval-form" @submit.prevent="submit">
<label>输入测试问题<textarea v-model="question" rows="4" maxlength="5000" placeholder="输入与你的资料相关的问题，检查知识库能召回哪些内容…" :disabled="busy" />
</label>
<button class="primary" :disabled="!ready || busy">
<AppIcon name="search" :size="17" />{{ busy ? '检索中…' : '开始检索' }}</button>
</form>
<div class="results-heading">
<h3>召回结果 <span class="badge">{{ hits.length }}</span>
</h3>
<span class="muted">{{ searched ? `${elapsed} ms · Top ${topK}` : '等待测试' }}</span>
</div>
<div v-if="!hits.length" class="empty-state">
<span class="empty-icon">
<AppIcon name="search" :size="28" />
</span>
<h3>{{ searched ? '没有召回相关内容' : '看看知识库如何理解你的问题' }}</h3>
<p>{{ searched ? '尝试调整问题表述，或检查知识库是否已导入相关资料。' : '输入一个真实问题，查看命中的片段与相关度。' }}</p>
</div>
<div v-else class="panel-body">
<p class="muted">测试问题：{{ searchedQuery }}</p>
<article v-for="(hit, index) in hits" :key="hit.id" class="chunk-card">
<div>
<span class="badge purple">#{{ index + 1 }}</span>
<strong>{{ sourceName(hit.sourceId) }}</strong>
<span class="score">相关度 {{ (hit.score ?? 0).toFixed(3) }}</span>
</div>
<p>{{ hit.content }}</p>
<small class="muted">Chunk {{ hit.chunkIndex }} · {{ hit.tokenCount }} 词元（本地估算）</small>
</article>
</div>
</section>
    <section v-else class="panel chat-panel" aria-label="知识问答">
      <header class="qa-panel-header qa-chat-header">
        <span class="qa-header-icon assistant"><AppIcon name="assistant" :size="20" /></span>
        <div class="qa-chat-heading"><h2>知识助手<span class="qa-assistant-badge">AI</span></h2><p :title="selectedBase?.name">{{ selectedBase ? `知识库 · ${selectedBase.name}` : '选择知识库，即可开始提问' }}</p></div>
        <button class="qa-reset-button" :disabled="busy || !messages.length" @click="messages = []; clearCitation()"><AppIcon name="reset" :size="15" /><span>清空会话</span></button>
      </header>
      <div ref="scrollContainer" class="chat-scroll" @scroll="trackScroll" :class="{ 'is-welcome': !messages.length && !busy }">
        <div v-if="!messages.length && !busy" class="qa-welcome">
          <div class="qa-welcome-symbol" aria-hidden="true"><span></span><AppIcon name="assistant" :size="32" /><span></span></div>
          <h2>从一个问题，发现更多知识</h2>
          <p>让散落的资料成为清晰的答案，每个结论都可追溯。</p>
          <div class="qa-suggestions">
            <button v-for="(item, index) in suggestions" :key="item.icon" :disabled="busy" @click="useSuggestion(item.question)">
              <span class="qa-suggestion-icon" :class="`suggestion-tone-${index}`"><AppIcon :name="item.icon" :size="20" /></span>
              <span class="qa-suggestion-copy"><strong>{{ item.title }}</strong><small>{{ item.description }}</small></span>
              <AppIcon name="arrow" :size="15" />
            </button>
          </div>
          <span class="qa-welcome-note"><AppIcon name="link" :size="13" />基于你的知识库 · 回答附带来源引用</span>
        </div>
<article v-for="message in messages" :key="message.id" class="conversation-turn">
<div class="user-question">{{ message.question }}</div>
<div class="answer-label">
<span class="qa-message-avatar"><AppIcon name="assistant" :size="16" /></span>知识助手<span class="muted">{{ message.model }}</span>
</div>
<div class="markdown-body" @click="focusCitation($event, message.id)" v-html="message.html" />
<p v-if="message.status === 'waiting'" class="qa-stream-status" role="status"><span class="loading-dot"></span>正在检索资料，等待模型响应…</p>
<p v-else-if="message.status === 'streaming'" class="qa-stream-status" role="status"><span class="loading-dot"></span>正在生成…</p>
<p v-else-if="message.status === 'stopped'" class="qa-stream-status" role="status">已停止生成，已接收的内容已保留。</p>
<p v-else-if="message.status === 'error'" class="qa-stream-status" role="status">生成中断，已保留部分内容，可继续生成。</p>
<button v-if="message.status === 'stopped' || message.status === 'error'" type="button" class="qa-stop-button" :disabled="busy" @click="continueGeneration(message)"><span aria-hidden="true">▶</span>继续生成</button>
<p v-if="citationNotice?.messageId === message.id" class="citation-notice" role="status">{{ citationNotice.text }}</p>
<details class="answer-sources">
<summary>参考来源 · {{ message.sources.length + message.webSources.length }} 处</summary>
<article
  v-for="source in message.sources"
  :key="source.id"
  class="chunk-card citation-source"
  :class="{ 'is-citation-active': activeCitation?.messageId === message.id && activeCitation.kind === 'chunk' && activeCitation.index === source.chunkIndex }"
  :data-chunk-index="source.chunkIndex"
  :aria-label="`${sourceName(source.sourceId)}，Chunk ${source.chunkIndex}`"
  tabindex="-1"
>
<div>
<strong>{{ sourceName(source.sourceId) }}</strong>
<span class="badge">Chunk {{ source.chunkIndex }}</span>
</div>
<p>{{ source.content }}</p>
</article>
<article
  v-for="source in message.webSources"
  :key="source.url"
  class="chunk-card citation-source"
  :class="{ 'is-citation-active': activeCitation?.messageId === message.id && activeCitation.kind === 'web' && activeCitation.index === source.index }"
  :data-web-index="source.index"
  :aria-label="`Web ${source.index}，${source.title}`"
  tabindex="-1"
>
<a :href="safeExternalUrl(source.url)" target="_blank" rel="noopener noreferrer">Web {{ source.index }} · {{ source.title }}</a>
<p>{{ source.snippet }}</p>
</article>
</details>
</article>
<div v-if="busy && !messages.length" class="answer-label">
<span class="loading-dot">
</span>正在检索资料并生成回答…</div>
</div>
      <div class="qa-composer-area">
        <form class="chat-composer" @submit.prevent="submit">
          <textarea ref="composerInput" v-model="question" aria-label="输入问题" rows="3" maxlength="5000" placeholder="向你的知识库提问…" :disabled="busy" @keydown.ctrl.enter.prevent="submit" @keydown.meta.enter.prevent="submit" />
          <div class="qa-composer-toolbar">
            <span class="qa-scope-chip" :title="selectedBase?.name"><AppIcon :name="webMode === 'knowledge' ? 'book' : 'globe'" :size="14" />{{ webMode === 'knowledge' ? '知识库问答' : webMode === 'auto' ? '按需联网' : '知识库 + 联网' }}</span>
            <span class="qa-keyboard-hint">⌘ / Ctrl + Enter</span>
            <button v-if="busy" type="button" class="qa-stop-button" @click="stopGeneration"><span aria-hidden="true">■</span>停止生成</button>
            <button v-else class="primary qa-send-button" :disabled="!ready || busy" :aria-label="busy ? '正在生成回答' : '发送问题'"><span>{{ busy ? '生成中' : '发送' }}</span><AppIcon name="send" :size="17" /></button>
          </div>
        </form>
        <p class="qa-composer-note">每次提问独立检索，重要信息请结合引用来源核对。</p>
      </div>
</section>
  </div>
</template>
