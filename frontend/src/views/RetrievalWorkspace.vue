<script setup lang="ts">
import { computed, reactive, ref, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'
import { request, streamKnowledge, searchKnowledge, fetchKnowledgeBaseSources } from '../lib/api'
import type { KnowledgeBase, KnowledgeChunk, KnowledgeSource, ProviderConfig, RowSource, TalentResult, WebSearchMode, WebSource } from '../lib/types'
import { renderMarkdown, safeExternalUrl, escapeHtml } from '../lib/renderMarkdown'
import { createFrameBuffer } from '../lib/frameBuffer'
import { currentUser } from '../lib/auth'
import { buildConversationHistory } from '../lib/conversation'
import { useTask } from '../composables/useTask'
import AppIcon from '../components/AppIcon.vue'
import FairySidebar from '../components/FairySidebar.vue'
import FairyIcon from '../components/FairyIcon.vue'
import AppSelect from '../components/AppSelect.vue'
import '../styles/knowledge-chat.css'
const props = defineProps<{ mode: 'retrieval' | 'chat'; bases: KnowledgeBase[]; providers: ProviderConfig[]; initialBaseId: string; baseRequest?: number }>()
const { busy, error, run } = useTask()
const baseId = ref(props.initialBaseId)
const mobileSettingsOpen = ref(false)
const sidebarOpen = ref(true)
const providerId = ref('')
const model = ref('')
const question = ref('')
const topK = ref(5)
const webMode = ref<WebSearchMode>('knowledge')
const sources = ref<KnowledgeSource[]>([])
const hits = ref<KnowledgeChunk[]>([])
const talentResults = ref<TalentResult[]>([])
const talentNotice = ref('')
const searched = ref(false)
const elapsed = ref(0)
const searchedQuery = ref('')
type SearchEntry = { id: number; baseId: string; query: string; topK: number; hits: KnowledgeChunk[]; talentResults: TalentResult[]; talentNotice: string; elapsed: number }
const searchHistory = ref<SearchEntry[]>([])
const currentHistory = computed(() => searchHistory.value.filter(entry => entry.baseId === baseId.value))
function restoreSearch(entry: SearchEntry) {
  if (busy.value || entry.baseId !== baseId.value) return
  question.value = entry.query; searchedQuery.value = entry.query; topK.value = entry.topK
  hits.value = entry.hits; talentResults.value = entry.talentResults; elapsed.value = entry.elapsed; searched.value = true; error.value = ''
  talentNotice.value = entry.talentNotice
}
type AskPayload = Parameters<typeof streamKnowledge>[0]
type ChatTurn = { id: number; question: string; answer: string; html: string;
  query_state?: import('../lib/conversation').TalentQueryState;
  retrievalQuery?: string;
  sources: KnowledgeChunk[]; webSources: WebSource[]; rowSources: RowSource[]; model: string; request: AskPayload;
  status: 'waiting' | 'streaming' | 'done' | 'stopped' | 'error' }
const messages = ref<ChatTurn[]>([])
const conversationId = ref<string>(crypto.randomUUID())
const saved = ref<{id:string;title:string;favorite:boolean;updated_at?:string}[]>([])
const historySearch = ref('')
const historyLoading = ref(false)
const historyError = ref('')
const openingId = ref('')
const deletingId = ref('')
function savedDate(value?: string) {
  if (!value) return null
  const date = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : value + 'Z')
  return Number.isNaN(date.getTime()) ? null : date
}
const historyGroups = computed(() => {
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
  const groups = ['今天', '昨天', '更早'].map(label => ({ label, items: [] as typeof saved.value }))
  for (const item of saved.value) {
    if (!item.title.toLocaleLowerCase().includes(historySearch.value.trim().toLocaleLowerCase())) continue
    const date = savedDate(item.updated_at)
    groups[date && date >= today ? 0 : date && date >= yesterday ? 1 : 2]!.items.push(item)
  }
  return groups.filter(group => group.items.length)
})
function historyTime(value?: string) {
  const date = savedDate(value)
  return date ? date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '已保存'
}
function switchSidebar(history: boolean) {
  sidebarOpen.value = true
  historyOpen.value = history
  mobileSettingsOpen.value = true
  if (history) void loadSaved()
}
const favorite = ref(false), feedback = ref(''), historyOpen = ref(false), saveNotice = ref('')
async function loadSaved() {
  if (!currentUser.value) return
  historyLoading.value = true; historyError.value = ''
  try { saved.value = await request('/conversations') }
  catch (e) { historyError.value = '读取会话失败，请重试。' }
  finally { historyLoading.value = false }
}
async function saveChat() {
  if(!currentUser.value || !messages.value.length) return
  try {
    await request('/conversations/'+conversationId.value, {method:'PUT',body:JSON.stringify({title:messages.value[0]?.question.slice(0,160)||'会话',messages:messages.value.map(({html,...rest})=>rest),favorite:favorite.value,feedback:feedback.value})})
    saveNotice.value='会话已保存';await loadSaved()
  } catch(e) { saveNotice.value='会话保存失败：'+String(e) }
}
async function openSaved(id:string) {
  if(busy.value || openingId.value || deletingId.value)return
  openingId.value=id;historyError.value=''
  try { const item=await request<{messages:ChatTurn[];favorite:boolean;feedback:string}>('/conversations/'+id)
    messages.value=item.messages.map(t=>({...t,html:renderMarkdown(t.answer,{sourceRefs:true}),status:['waiting','streaming'].includes(t.status)?'stopped':t.status}))
    conversationId.value=id;favorite.value=item.favorite;feedback.value=item.feedback
    const lastRequest = item.messages.at(-1)?.request
    if (lastRequest?.knowledgeBaseId && activeBases.value.some(base => base.id === lastRequest.knowledgeBaseId)) baseId.value = lastRequest.knowledgeBaseId
    question.value='';error.value='';clearCitation();mobileSettingsOpen.value=false
  } catch(e) { historyError.value='打开会话失败，请重试。' }
  finally { openingId.value='' }
}
async function removeSaved(id:string) {
  if (busy.value || openingId.value || deletingId.value) return
  deletingId.value=id;historyError.value=''
  try {
    await request('/conversations/'+id,{method:'DELETE'})
    if (conversationId.value === id) clearConversation()
    await loadSaved()
  } catch(e) { historyError.value='删除失败，请重试。' }
  finally { deletingId.value='' }
}
onMounted(loadSaved)
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
const activeCitation = ref<{ messageId: number; kind: 'chunk' | 'web' | 'record'; index: number }>()
const citationNotice = ref<{ messageId: number; text: string }>()
let citationTimer: ReturnType<typeof setTimeout> | undefined

function clearCitation() {
  clearTimeout(citationTimer)
  activeCitation.value = undefined
  citationNotice.value = undefined
}

function clearConversation() {
  if (busy.value) return
  messages.value = []
  conversationId.value = crypto.randomUUID();favorite.value=false;feedback.value='';saveNotice.value=''
  question.value = ''
  error.value = ''
  followOutput.value = true
  clearCitation()
  composerInput.value?.focus()
}

async function focusCitation(event: MouseEvent, messageId: number) {
  const button = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>('.source-inline-ref')
  if (!button) return
  const kind = button.dataset.recordRef !== undefined ? 'record' : button.dataset.webRef !== undefined ? 'web' : 'chunk'
  const index = Number(kind === 'record' ? button.dataset.recordRef : kind === 'web' ? button.dataset.webRef : button.dataset.chunkRef)
  if (!Number.isInteger(index) || index < 0) return
  const turn = (event.currentTarget as HTMLElement).closest('.conversation-turn')
  const details = turn?.querySelector<HTMLDetailsElement>('.answer-sources')
  const target = details?.querySelector<HTMLElement>(`[data-${kind}-index="${index}"]`)
  clearCitation()
  if (!details || !target) {
    citationNotice.value = { messageId, text: `本次回答未返回 ${kind === 'web' ? '网页来源' : '资料来源'} ${index} 的来源内容。` }
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
watch(() => props.baseRequest, () => {
  if (props.initialBaseId && props.initialBaseId !== baseId.value) {
    stopGeneration()
    baseId.value = props.initialBaseId
  }
})
watch(baseId, async (id) => {
  clearCitation()
  hits.value = []; talentResults.value = []; searched.value = false; sources.value = []
  talentNotice.value = ''
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
      let clientTrace: import('../lib/api').ClientTrace | undefined
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
          conversationId: conversationId.value, turnId: String(turn.id),
          continuation: continuing && previousAnswer
            ? { answer: previousAnswer, sources: turn.sources, webSources: turn.webSources, retrievalQuery: turn.retrievalQuery } : undefined,
        }, {
          signal: controller.signal,
          onTrace(trace) { clientTrace = trace },
          onMeta(meta) { turn.request.providerId = meta.providerId; turn.request.model = meta.model; Object.assign(turn, { sources: meta.sources, webSources: meta.webSources, rowSources: meta.rowSources || [], model: meta.model, retrievalQuery: meta.retrievalQuery, query_state: meta.queryState }) },
          onDelta(text) { buffer.append(text) },
        })
        turn.status = 'done'
      } catch (cause) {
        turn.status = controller.signal.aborted ? 'stopped' : 'error'
        if (!controller.signal.aborted) throw cause
      } finally {
        await buffer.finish()
        await nextTick()
        if (clientTrace) {
          clientTrace.events.push({ name: turn.status === 'done' ? '页面渲染完成' : turn.status === 'stopped' ? '页面输出停止' : '页面输出失败', elapsed_ms: Math.round(performance.now() - clientTrace.startedAt) })
          void request('/agent-monitor/' + encodeURIComponent(clientTrace.id) + '/client-events', { method: 'PUT', body: JSON.stringify({ events: clientTrace.events }) }).catch(() => { /* Telemetry must not interrupt the answer. */ })
        }
        await saveChat()
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
      const searchedBase = baseId.value
      const requestedTopK = topK.value
      searched.value = false; hits.value = []; talentResults.value = []
      talentNotice.value = ''
      const result = await searchKnowledge(value, requestedTopK, searchedBase)
      const entry = { id: Date.now(), baseId: searchedBase, query: value, topK: requestedTopK,
        hits: result.hits, talentResults: result.talentResults || [], talentNotice: result.talentNotice || '', elapsed: Math.round(performance.now() - started) }
      searchHistory.value = [entry, ...searchHistory.value.filter(item => !(item.baseId === searchedBase && item.query === value && item.topK === requestedTopK))].slice(0, 20)
      if (baseId.value !== searchedBase) return
      hits.value = result.hits; searched.value = true; searchedQuery.value = value
      talentResults.value = result.talentResults || []
      talentNotice.value = result.talentNotice || ''
    } else {
      const turn = reactive<ChatTurn>({ id: Date.now(), question: value, answer: '', html: '',
        sources: [], webSources: [], rowSources: [], model: model.value, status: 'waiting',
        request: { question: value, knowledgeBaseId: baseId.value, providerId: providerId.value,
          history: buildConversationHistory(messages.value),
          model: model.value || undefined, topK: topK.value, talentPageSize: topK.value, webSearchMode: webMode.value } })
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
  <div class="retrieval-layout" :class="{ 'qa-layout': mode === 'chat', 'is-sidebar-closed': mode === 'chat' && !sidebarOpen }">
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
<span>1 条</span>
<span>12 条</span>
</span>
</label>

<div class="config-note">
<FairyIcon name="search" :size="58" portrait />
<strong>从召回到可信答案</strong>
<p>先检查相关切片，再验证答案引用。资料内容更新后，可重新导入并重建索引。</p>
</div>
<section v-if="currentHistory.length" class="search-history" aria-label="最近搜索">
  <header><h3>最近搜索</h3><button class="text-button" :disabled="busy" @click="searchHistory = searchHistory.filter(entry => entry.baseId !== baseId)">清空历史</button></header>
  <p>本次打开期间保留最近 20 次搜索，点击回看当时结果。</p>
  <button v-for="entry in currentHistory" :key="entry.id" class="search-history-entry" :disabled="busy" @click="restoreSearch(entry)">
    <span>{{ entry.query }}</span><small>{{ entry.hits.length }} 条结果 · Top {{ entry.topK }}</small>
  </button>
</section>
</div>
</aside>
    <FairySidebar v-else v-model:open="sidebarOpen">
    <aside class="panel qa-settings" :class="{ 'is-expanded': mobileSettingsOpen }" aria-label="问答侧栏">
      <header class="qa-panel-header">
        <span class="qa-header-icon"><AppIcon :name="historyOpen ? 'clock' : 'settings'" :size="19" /></span>
        <div><h2 id="qa-sidebar-title">{{ historyOpen ? '历史会话' : '问答设置' }}</h2><p>{{ historyOpen ? '接着上次的话题' : '选择知识与模型' }}</p></div>
        <button class="qa-config-toggle" :aria-expanded="mobileSettingsOpen" aria-controls="qa-sidebar-content" @click="mobileSettingsOpen = !mobileSettingsOpen">{{ mobileSettingsOpen ? '收起' : '展开' }}<AppIcon :name="mobileSettingsOpen ? 'close' : 'settings'" :size="14" /></button>
        <button class="qa-sidebar-switch" type="button" :aria-label="historyOpen ? '切换到问答设置' : '切换到历史会话'" :title="historyOpen ? '切换到问答设置' : '切换到历史会话'" aria-controls="qa-sidebar-content" @click="switchSidebar(!historyOpen)"><AppIcon name="switch" :size="19" /></button>
      </header>
      <div id="qa-sidebar-content" class="qa-sidebar-content" :class="{ 'to-history': historyOpen }">
      <Transition name="qa-sidebar-swap" mode="out-in">
      <div v-if="!historyOpen" id="qa-settings-body" key="settings" class="qa-settings-body" role="region" aria-labelledby="qa-sidebar-title">
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
          <label class="qa-range-field"><span>返回数量<output>最多 {{ topK }} 条</output></span><input v-model.number="topK" type="range" min="1" max="12" :disabled="busy" /><span class="range-labels"><span>1 条</span><span>12 条</span></span></label>
          <p class="qa-field-note">新查询生效：人才名单控制每页条数，文档问答控制参考片段数；不足时按实际数量返回。</p>
          <label>资料范围<AppSelect v-model="webMode" label="资料范围" :disabled="busy" :options="[{ value: 'knowledge', label: '仅知识库' }, { value: 'auto', label: '按需补充联网搜索' }, { value: 'web', label: '知识库 + 联网搜索' }]" /></label>
          <p v-if="webMode !== 'knowledge'" class="qa-field-note">联网搜索需配置搜索服务；未返回网页时仅使用知识库资料。</p>
        </section>
      </div>
      <div v-else id="qa-history-body" key="history" class="qa-history-body" role="region" aria-labelledby="qa-sidebar-title">
        <div class="qa-history-toolbar">
          <label class="qa-history-search"><AppIcon name="search" :size="15" /><input v-model="historySearch" aria-label="搜索历史会话" placeholder="搜索会话" /><button v-if="historySearch" aria-label="清除搜索" @click="historySearch = ''"><AppIcon name="close" :size="13" /></button></label>
          <button class="qa-new-conversation" type="button" aria-label="新建会话" title="新建会话" :disabled="busy || !!openingId || !!deletingId" @click="clearConversation(); mobileSettingsOpen = false"><AppIcon name="plus" :size="19" /></button>
        </div>
        <div v-if="historyError" class="qa-history-error" role="alert">{{ historyError }}<button @click="loadSaved">重新加载</button></div>
        <div v-if="historyLoading && !saved.length" class="qa-history-empty" role="status"><AppIcon name="clock" :size="24" /><p>正在读取会话…</p></div>
        <div v-else-if="!historyGroups.length && !historyError" class="qa-history-empty"><AppIcon :name="historySearch ? 'search' : 'chat'" :size="28" /><strong>{{ historySearch ? '没有找到相关会话' : '还没有历史会话' }}</strong><p>{{ historySearch ? '试试其他关键词' : '开始提问后，会话会自动保存在这里' }}</p></div>
        <div v-else class="qa-history-list" :aria-busy="historyLoading">
          <section v-for="group in historyGroups" :key="group.label" class="qa-history-group">
            <h3>{{ group.label }}<span>{{ group.items.length }}</span></h3>
            <article v-for="item in group.items" :key="item.id" class="qa-history-item" :class="{ 'is-current': item.id === conversationId }">
              <button class="qa-history-open" :disabled="busy || !!openingId || !!deletingId" :aria-current="item.id === conversationId ? 'true' : undefined" @click="openSaved(item.id)">
                <span class="qa-history-item-icon"><AppIcon name="chat" :size="16" /></span>
                <span class="qa-history-copy"><strong :title="item.title">{{ item.title }}</strong><span><time :datetime="item.updated_at">{{ historyTime(item.updated_at) }}</time><small v-if="openingId === item.id">打开中</small><small v-else-if="item.id === conversationId">当前会话</small></span></span>
              </button>
              <button class="qa-history-delete" :disabled="busy || !!openingId || !!deletingId" :aria-label="`删除会话：${item.title}`" title="删除会话" @click="removeSaved(item.id)"><AppIcon name="trash" :size="14" /></button>
            </article>
          </section>
        </div>
      </div>
      </Transition>
      </div>
      <footer v-if="!historyOpen" class="qa-settings-footer"><AppIcon name="link" :size="16" /><div><strong>每一份答案，都有迹可循</strong><p>点击回答中的引用，可定位原始资料。</p></div></footer>
    </aside>
    </FairySidebar>
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
<p v-if="talentNotice" class="notice" role="status">{{ talentNotice }}</p>
<section v-for="(result, resultIndex) in talentResults" :key="`${result.source_id}-${result.sheet}-${resultIndex}`" class="panel-body talent-results">
  <h3>人才查询 · {{ result.file }} / {{ result.sheet }}</h3>
  <p v-if="result.error" class="notice error">{{ result.error }}</p>
  <template v-else>
    <p class="muted">扫描 {{ result.scanned_records }} 条人员记录，匹配 {{ result.matched_records }} 条<span v-if="result.plan.sort_by"> · 按 {{ result.plan.sort_by }} {{ result.plan.descending ? '降序' : '升序' }}</span></p>
    <p v-if="result.missing_sort_values" class="muted">{{ result.missing_sort_values }} 条记录的排序指标缺失或不是有效数值，未参与排名。</p>
    <div v-if="result.records.length" class="table-wrap"><table><thead><tr><th>姓名</th><th>机构</th><th>领域</th><th v-if="result.plan.sort_by">{{ result.plan.sort_by }}</th><th>原表行号</th></tr></thead>
      <tbody><tr v-for="record in result.records" :key="record.excel_row"><td>{{ record.fields['姓名'] || record.fields['人员姓名'] || record.fields['员工姓名'] || record.fields['name'] || record.fields['full name'] }}</td><td>{{ record.fields['当前机构'] || '—' }}</td><td>{{ record.fields['领域'] || '—' }}</td><td v-if="result.plan.sort_by">{{ record.fields[result.plan.sort_by] }}</td><td>{{ record.excel_row }}</td></tr></tbody></table></div>
    <p v-else class="muted">当前条件下没有可展示的人员记录。</p>
    <p v-if="result.truncated" class="muted">本文件展示 {{ result.returned_records }} 条；本次人才结果合计不超过召回数量 Top {{ topK }}。可调整召回数量查看更多。</p>
  </template>
</section>
<div v-if="!hits.length && !talentResults.length" class="empty-state">
<FairyIcon name="search" :size="82" portrait />
<h3>{{ searched ? '没有召回相关内容' : '看看知识库如何理解你的问题' }}</h3>
<p>{{ searched ? '尝试调整问题表述，或检查知识库是否已导入相关资料。' : '输入一个真实问题，查看命中的片段与相关度。' }}</p>
</div>
<div v-if="hits.length" class="panel-body">
<p class="muted">测试问题：{{ searchedQuery }}</p>
<article v-for="(hit, index) in hits" :key="hit.id" class="chunk-card">
<div>
<span class="badge purple">#{{ index + 1 }}</span>
<strong>{{ sourceName(hit.sourceId) }}</strong>
<span class="score">相关度 {{ (hit.score ?? 0).toFixed(3) }}</span>
</div>
<p>{{ hit.content }}</p>
<small class="muted">片段 {{ hit.chunkIndex }} · {{ hit.tokenCount }} 词元（本地估算）</small>
</article>
</div>
</section>
    <section v-else class="panel chat-panel" aria-label="知识问答">
      <header class="qa-panel-header qa-chat-header">
        <FairyIcon name="spark" :size="42" portrait />
        <div class="qa-chat-heading"><h2>知识精灵<span class="qa-assistant-badge">AI</span></h2><p :title="selectedBase?.name">{{ selectedBase ? `知识库 · ${selectedBase.name}` : '选择知识库，即可开始提问' }}</p></div>
        <button class="qa-reset-button" :disabled="busy || !messages.length" @click="clearConversation"><AppIcon name="reset" :size="15" /><span>清空会话</span></button>
      </header>
      <div ref="scrollContainer" class="chat-scroll" @scroll="trackScroll" :class="{ 'is-welcome': !messages.length && !busy }">
        <div v-if="!messages.length && !busy" class="qa-welcome">
          <div class="fairy-welcome-art" aria-hidden="true"><img src="/mascot/knowledge-fairy.webp" alt="" width="616" height="640" /><span>✦</span></div>
          <span class="welcome-eyebrow">YOUR LITTLE KNOWLEDGE COMPANION</span>
          <h2>你好，今天想发现什么？</h2>
          <p>把问题交给我，一起从知识里找寻答案。</p>
          <div class="qa-suggestions">
            <button v-for="(item, index) in suggestions" :key="item.icon" :disabled="busy" @click="useSuggestion(item.question)">
              <FairyIcon :name="item.icon" :size="42" :class="`suggestion-tone-${index}`" />
              <span class="qa-suggestion-copy"><strong>{{ item.title }}</strong><small>{{ item.description }}</small></span>
              <AppIcon name="arrow" :size="15" />
            </button>
          </div>
          <span class="qa-welcome-note"><AppIcon name="link" :size="13" />基于你的知识库 · 回答附带来源引用</span>
        </div>

<article v-for="message in messages" :key="message.id" class="conversation-turn">
<div class="user-question">{{ message.question }}</div>
<div class="answer-label">
<FairyIcon name="spark" :size="32" portrait />知识精灵<span class="muted">{{ message.model }}</span>
</div>
<div class="markdown-body" @click="focusCitation($event, message.id)" v-html="message.html" />
<p v-if="message.status === 'waiting'" class="qa-stream-status" role="status"><span class="loading-dot"></span>正在检索资料，等待模型响应…</p>
<p v-else-if="message.status === 'streaming'" class="qa-stream-status" role="status"><span class="loading-dot"></span>正在生成…</p>
<p v-else-if="message.status === 'stopped'" class="qa-stream-status" role="status">已停止生成，已接收的内容已保留。</p>
<p v-else-if="message.status === 'error'" class="qa-stream-status" role="status">生成中断，已保留部分内容，可继续生成。</p>
<button v-if="message.status === 'stopped' || message.status === 'error'" type="button" class="qa-stop-button" :disabled="busy" @click="continueGeneration(message)"><span aria-hidden="true">▶</span>继续生成</button>
<button v-if="message === messages[messages.length - 1] && message.status === 'done' && message.query_state?.has_more" type="button" :disabled="busy" @click="question = '继续'; submit()">下一页</button>
<p v-if="citationNotice?.messageId === message.id" class="citation-notice" role="status">{{ citationNotice.text }}</p>
<details class="answer-sources">
<summary>参考来源 · {{ message.sources.length + message.webSources.length + (message.rowSources?.length || 0) }} 处</summary>
<article v-for="source in message.rowSources" :key="`record-${source.index}`" class="chunk-card citation-source"
  :class="{ 'is-citation-active': activeCitation?.messageId === message.id && activeCitation.kind === 'record' && activeCitation.index === source.index }"
  :data-record-index="source.index" :aria-label="`人才证据 ${source.index}，${source.filename}，${source.sheet}，第${source.excel_row}行`" tabindex="-1">
  <div><span class="badge purple">人才证据 {{ source.index }}</span><strong>{{ source.filename }}</strong></div>
  <p class="muted">工作表 {{ source.sheet }} · Excel 第 {{ source.excel_row }} 行 · 上传文件中的原始记录</p>
  <dl class="record-evidence-fields"><template v-for="(value, field) in source.fields" :key="field">
    <dt>{{ field }}</dt><dd><a v-if="safeExternalUrl(value)" :href="safeExternalUrl(value)" target="_blank" rel="noopener noreferrer">{{ value }}</a><span v-else>{{ value || '未填写' }}</span></dd>
  </template></dl>
  <small class="muted">网页链接为原表记录，未实时核验网页内容。</small>
</article>
<article
  v-for="source in message.sources"
  :key="source.id"
  class="chunk-card citation-source"
  :class="{ 'is-citation-active': activeCitation?.messageId === message.id && activeCitation.kind === 'chunk' && activeCitation.index === (source.citationIndex ?? source.chunkIndex) }"
  :data-chunk-index="(source.citationIndex ?? source.chunkIndex)"
  :aria-label="`${sourceName(source.sourceId)}，来源 ${(source.citationIndex ?? source.chunkIndex)}`"
  tabindex="-1"
>
<div>
<strong>{{ sourceName(source.sourceId) }}</strong>
<span class="badge">来源 {{ (source.citationIndex ?? source.chunkIndex) }}</span>
</div>
<p>{{ source.content }}</p>
</article>
<article
  v-for="source in message.webSources"
  :key="source.url"
  class="chunk-card citation-source"
  :class="{ 'is-citation-active': activeCitation?.messageId === message.id && activeCitation.kind === 'web' && activeCitation.index === source.index }"
  :data-web-index="source.index"
  :aria-label="`网页 ${source.index}，${source.title}`"
  tabindex="-1"
>
<a :href="safeExternalUrl(source.url)" target="_blank" rel="noopener noreferrer">网页 {{ source.index }} · {{ source.title }}</a>
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
        <p class="qa-composer-note">已开启上下文记忆 · 参考最近 12 轮完整对话（长内容按长度截取）· 清空会话后重新开始</p>
      </div>
</section>
  </div>
</template>

<style scoped>
.qa-sidebar-switch { display: grid; place-items: center; flex-shrink: 0; width: 34px; height: 34px; margin-left: auto; padding: 0; border: 1px solid transparent; border-radius: 10px; background: transparent; box-shadow: none; color: #7d9ba8; transition: background 160ms, color 160ms; }
.qa-sidebar-switch:hover { background: #eaf2f4; border-color: #dce8eb; color: #496f81; }
.qa-sidebar-content { display: flex; flex: 1; min-height: 0; overflow: hidden; }
.qa-sidebar-content > * { width: 100%; min-width: 0; }
.qa-sidebar-swap-enter-active, .qa-sidebar-swap-leave-active { transition: opacity 140ms ease, transform 180ms cubic-bezier(.22,1,.36,1); }
.qa-sidebar-swap-enter-from { opacity: 0; transform: translateX(-12px); }
.qa-sidebar-swap-leave-to { opacity: 0; transform: translateX(12px); }
.to-history .qa-sidebar-swap-enter-from { transform: translateX(12px); }
.to-history .qa-sidebar-swap-leave-to { transform: translateX(-12px); }
.qa-history-body { display: flex; flex-direction: column; gap: 12px; min-height: 0; padding: 16px 18px 20px; }
.qa-history-toolbar { display: flex; align-items: center; gap: 8px; flex-shrink: 0; min-width: 0; margin-bottom: 5px; }
.qa-history-body .qa-new-conversation { display: grid; place-items: center; width: 36px; height: 36px; min-height: 36px; flex: 0 0 36px; padding: 0; border: 0; border-radius: 9px; background: #eaf1f2; box-shadow: none; color: #678c9c; transition: background 160ms, color 160ms; }
.qa-history-body .qa-new-conversation:hover:not(:disabled) { transform: none; background: #dcebef; color: #395f71; box-shadow: none; }
.qa-history-body .qa-new-conversation:active:not(:disabled) { transform: none; background: #d4e5ea; box-shadow: none; }
.qa-history-search { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; margin: 0; padding: 0 11px; border: 1px solid transparent; border-radius: 9px; color: #95a7ae; background: #eef2f180; transition: background 160ms, border-color 160ms, box-shadow 160ms; }
.qa-history-search > svg { flex-shrink: 0; }
.qa-history-search:focus-within { background: #fffefa; border-color: #bed2da; box-shadow: 0 0 0 3px #9bbdc510; }
.qa-history-search input, .qa-history-search input:focus-visible { width: 100%; min-width: 0; height: 36px; min-height: 36px; margin: 0; padding: 8px 0; border: 0; border-radius: 0; background: transparent; box-shadow: none; outline: none; color: #4c6976; font-size: 12px; font-weight: 400; }
.qa-history-search input::placeholder { color: #98a9af; font-weight: 400; }
.qa-history-search button { display: grid; place-items: center; flex-shrink: 0; width: 22px; height: 22px; min-height: 22px; border: 0; padding: 0; border-radius: 6px; background: transparent; box-shadow: none; color: #91a5ae; }
.qa-history-search button:hover:not(:disabled), .qa-history-search button:active:not(:disabled) { transform: none; background: #e3edef; box-shadow: none; }
.qa-history-list { min-height: 0; flex: 1; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: #d6e2e5 transparent; }
.qa-history-group + .qa-history-group { margin-top: 20px; }
.qa-history-group h3 { display: flex; align-items: center; gap: 8px; margin: 3px 5px 9px; font-size: 11px; font-weight: 500; color: #80959e; }
.qa-history-group h3 span { color: #a5b4ba; font-size: 10px; }
.qa-history-item { display: flex; align-items: center; position: relative; margin-bottom: 5px; padding-right: 4px; border: 1px solid transparent; border-radius: 12px; transition: background 160ms, border-color 160ms; }
.qa-history-item:hover { background: #f1f6f6; }
.qa-history-item.is-current { background: linear-gradient(110deg, #e9f2f4, #f5f8f7); border-color: #d3e3e7; }
.qa-history-open { display: flex; flex: 1; align-items: flex-start; gap: 9px; min-width: 0; padding: 12px 7px; border: 0; border-radius: 10px; box-shadow: none; background: transparent; text-align: left; }
.qa-history-item-icon { display: grid; place-items: center; flex-shrink: 0; width: 24px; height: 26px; color: #91a9b1; }
.is-current .qa-history-item-icon { color: #527f92; }
.qa-history-copy { flex: 1; min-width: 0; }
.qa-history-copy strong { display: -webkit-box; overflow: hidden; -webkit-line-clamp: 2; -webkit-box-orient: vertical; font-size: 12px; font-weight: 500; line-height: 1.65; color: #526e7b; overflow-wrap: anywhere; }
.qa-history-copy > span { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 6px; color: #92a4ac; font-size: 10px; }
.qa-history-copy small { color: #608998; font-size: 9px; }
.qa-history-delete { display: grid; place-items: center; flex-shrink: 0; width: 28px; height: 30px; padding: 0; border: 0; border-radius: 7px; box-shadow: none; background: transparent; color: #98aab1; opacity: 0; transition: opacity 140ms, color 140ms; }
.qa-history-item:hover .qa-history-delete, .qa-history-item:focus-within .qa-history-delete { opacity: 1; }
.qa-history-delete:hover { color: #b47588; background: #f7ecef; }
.qa-history-empty { display: flex; flex: 1; flex-direction: column; align-items: center; justify-content: center; gap: 12px; min-height: 180px; padding: 24px 8px; text-align: center; color: #90a8b0; }
.qa-history-empty > svg { box-sizing: content-box; padding: 17px; border-radius: 22px; background: #edf4f4; }
.qa-history-empty strong { color: #65808d; font-size: 13px; font-weight: 500; }
.qa-history-empty p { max-width: 180px; font-size: 11px; line-height: 1.7; color: #91a3aa; }
.qa-history-error { color: #ac7184; font-size: 12px; line-height: 1.7; }
.qa-history-error button { margin-top: 6px; padding: 5px 8px; font-size: 11px; }
.qa-sidebar-switch:focus-visible, .qa-history-body button:focus-visible { outline: 2px solid #7fabbc; outline-offset: 2px; }
@media (hover: none) { .qa-history-delete { opacity: 1; } }
@media (max-width: 960px) {
  .qa-sidebar-content { display: none; }
  .qa-settings.is-expanded .qa-sidebar-content { display: flex; }
  .qa-history-body { max-height: 440px; }
  .qa-sidebar-switch { margin-left: 4px; }
}
@media (prefers-reduced-motion: reduce) {
  .qa-sidebar-switch, .qa-sidebar-swap-enter-active, .qa-sidebar-swap-leave-active { transition: none; }
}

.record-evidence-fields { display: grid; grid-template-columns: minmax(90px, 150px) minmax(0, 1fr); gap: 8px 14px; margin: 14px 0; font-size: 12px; line-height: 1.8; }
.record-evidence-fields dt { color: #93809f; }
.record-evidence-fields dd { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.search-history { margin-top: 22px; padding-top: 18px; border-top: 1px solid #eee8f4; }
.search-history header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.search-history h3 { font-size: 12px; color: #766486; }
.search-history > p { margin: 8px 0 12px; font-size: 11px; color: #998ba4; line-height: 1.7; }
.search-history-entry { display: flex; flex-direction: column; align-items: flex-start; width: 100%; margin-top: 7px; padding: 10px 12px; border-color: #eee8f4; background: #fcfafe; text-align: left; }
.search-history-entry span { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #705d82; font-size: 12px; }
.search-history-entry small { font-size: 10px; color: #a392b1; }
</style>
