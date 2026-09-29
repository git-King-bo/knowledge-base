<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import AppSelect from '../components/AppSelect.vue'
import { buildAgentTimeline, modelMessages, prettyData, stageFacts } from '../lib/agentTimeline'
import { renderMarkdown } from '../lib/renderMarkdown'
import { fetchAgentTrace, fetchAgentTraces, fetchTraceConversations, type AgentTrace, type AgentTraceDetail, type TraceConversation } from '../lib/agentMonitor'
const conversations = ref<TraceConversation[]>([]), conversation = ref(''), keyword = ref(''), status = ref('')
const rows = ref<AgentTrace[]>([]), detail = ref<AgentTraceDetail>(), selected = ref('')
const page = ref(1), total = ref(0), pageSize = ref(20), busy = ref(false), detailBusy = ref(false), error = ref(''), detailError = ref('')
const totals = ref({ total_tokens: 0, call_count: 0, unknown_calls: 0 })
const timeline = computed(() => detail.value ? buildAgentTimeline(detail.value) : [])
const outputHtml = computed(() => renderMarkdown(detail.value?.answer || ''))
const clientEvents = computed(() => {
  const events = detail.value?.request.client_events
  return Array.isArray(events) ? events.filter((event): event is {name: string; elapsed_ms: number} => typeof event?.name === 'string' && typeof event?.elapsed_ms === 'number') : []
})
const stepLabels: Record<string, string> = { success: '完成', error: '失败', skipped: '跳过', fallback: '降级', running: '执行中' }
let listVersion = 0, detailVersion = 0
const labels: Record<string, string> = { success: '已完成', error: '失败', cancelled: '已停止', running: '执行中', interrupted: '未完整结束' }
const statusOptions = [{ value: '', label: '全部状态' }, ...Object.entries(labels).map(([value, label]) => ({ value, label }))]
const conversationOptions = computed(() => [{ value: '', label: '全部历史对话' }, ...conversations.value
  .filter(item => item.id === conversation.value || item.title.toLocaleLowerCase().includes(keyword.value.trim().toLocaleLowerCase()))
  .map(item => ({ value: item.id, label: item.title, description: item.has_traces ? '已有关联执行记录' : '历史会话 · 暂无链路记录' }))])
const num = (value: number | null) => value === null ? '未上报' : value.toLocaleString()
const duration = (ms: number | null) => ms === null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
async function open(id: string) {
  const version = ++detailVersion
  selected.value = id; detail.value = undefined; detailError.value = ''; detailBusy.value = true
  try { const result = await fetchAgentTrace(id); if (version === detailVersion) detail.value = result }
  catch (e) { if (version === detailVersion) detailError.value = String(e) }
  finally { if (version === detailVersion) detailBusy.value = false }
}
async function load() {
  const version = ++listVersion
  ++detailVersion; detailBusy.value = false; detail.value = undefined; detailError.value = ''; busy.value = true; error.value = ''
  try {
    const result = await fetchAgentTraces(conversation.value, status.value, page.value)
    if (version !== listVersion) return
    rows.value = result.items; total.value = result.total; pageSize.value = result.page_size; totals.value = result.summary
    const next = result.items.find(item => item.id === selected.value) || result.items[0]
    selected.value = next?.id || ''
    if (next) await open(next.id)
  } catch (e) { if (version === listVersion) { error.value = String(e); rows.value = []; total.value = 0; totals.value = { total_tokens: 0, call_count: 0, unknown_calls: 0 } } }
  finally { if (version === listVersion) busy.value = false }
}
function filter() { page.value = 1; selected.value = ''; void load() }
async function refresh() {
  try { conversations.value = await fetchTraceConversations() }
  catch (e) { error.value = '历史会话加载失败：' + String(e); return }
  await load()
}
onMounted(refresh)
</script>

<template>
  <section class="agent-monitor">
    <div class="panel monitor-filters"><label>搜索历史对话<input v-model="keyword" placeholder="输入对话标题，缩小下拉选项" /></label><div class="conversation-filter"><span>历史对话</span><AppSelect v-model="conversation" label="历史对话" :options="conversationOptions" @change="filter" /></div><div><span>执行状态</span><AppSelect v-model="status" label="执行状态" :options="statusOptions" @change="filter" /></div><button class="refresh-records" :disabled="busy" @click="refresh"><AppIcon name="refresh" :size="16" />刷新记录</button></div>
    <p v-if="error" class="notice error" role="alert">{{ error }} <button @click="refresh">重试</button></p>
    <div class="filter-summary" aria-live="polite"><span>当前筛选 · {{ total }} 次请求</span><span>{{ totals.call_count }} 次模型调用</span><span>累计已知 <strong>{{ num(totals.total_tokens) }}</strong> Token</span><span v-if="totals.unknown_calls">另有 {{ totals.unknown_calls }} 次调用用量未知</span></div>
    <div class="monitor-layout">
      <div class="trace-area">
        <div v-if="busy || detailBusy" class="panel monitor-empty" role="status">正在读取执行详情…</div>
        <div v-else-if="detailError" class="panel monitor-empty" role="alert"><p>{{ detailError }}</p><button @click="open(selected)">重新加载</button></div>
        <template v-else-if="detail">
          <div class="trace-primary-row">
          <section class="panel trace-overview"><div class="trace-title"><h3>{{ detail.question }}</h3><span class="status" :class="detail.status">{{ labels[detail.status] || detail.status }}</span></div><p class="trace-id">{{ time(detail.created_at) }} · 请求 {{ detail.id }}<template v-if="detail.turn_id"> · 对话轮次 {{ detail.turn_id }}</template></p>
            <div class="trace-metrics"><div><span>已知 Token 总量</span><strong>{{ num(detail.total_tokens) }}<small v-if="detail.unknown_calls"> + 未知</small></strong></div><div><span>输入 / 输出</span><strong>{{ num(detail.input_tokens) }} <small>/</small> {{ num(detail.output_tokens) }}</strong></div><div><span>请求总耗时</span><strong>{{ detail.status === 'running' ? '执行中' : duration(detail.duration_ms) }}</strong></div><div><span>首次输出耗时</span><strong>{{ duration(detail.first_token_ms) }}</strong></div></div>
            <p v-if="detail.status === 'running'" class="monitor-hint">请求仍在执行，步骤与消耗将在结束后汇总。点击刷新查看最新状态。</p>
            <p v-else-if="detail.unknown_calls" class="monitor-hint">{{ detail.unknown_calls }} 次调用未上报 Token，合计仅包含已知用量，不代表全部消耗。</p>
            <p v-else class="monitor-hint">{{ detail.call_count }} 次模型调用 · 缓存命中 {{ num(detail.cached_tokens) }} Token（包含在输入中，不重复计入总量）。{{ !detail.call_count && detail.status === 'success' ? '本次通过程序直接生成结果，没有模型调用。' : '' }}</p>
            <p v-if="detail.error" class="notice error">{{ detail.error }}</p>
          </section>
          <section class="panel trace-section trace-execution"><div class="section-heading"><AppIcon name="workflow" :size="18" /><h3>执行时间线</h3></div><p class="section-description">按实际执行路径展示。展开操作详情查看输入、结果和策略；模型调用与输出在对应步骤中展示。</p>
            <ol class="trace-timeline" tabindex="0" aria-label="完整执行过程">
              <li v-if="detail.request.client_started_at"><span class="step-dot"><AppIcon name="chat" :size="12" /></span><div class="step-body"><div><strong>页面用户输入与提交</strong><span>浏览器 · {{ detail.request.client_started_at }}</span></div><pre class="user-input">{{ detail.question }}</pre><details class="stage-detail"><summary>提交参数</summary><pre>{{ JSON.stringify(detail.request, null, 2) }}</pre></details></div></li>
              <li v-for="(step, index) in timeline" :key="step.call?.id || index"><span class="step-dot" :class="step.status"><AppIcon :name="step.status === 'error' ? 'close' : step.status === 'skipped' ? 'arrow' : step.call ? 'spark' : 'check'" :size="12" /></span><div class="step-body">
                <div><strong>{{ step.call ? step.call.stage : step.queryComparison ? '查询改写与实际检索语句' : step.name }}</strong><span>{{ stepLabels[step.status] || step.status }} · +{{ duration(step.start_ms) }}<template v-if="step.duration_ms"> · 耗时 {{ duration(step.duration_ms) }}</template></span></div>
                <template v-if="step.call">
                  <div class="inline-model"><span>{{ step.call.model }}</span><span>{{ step.call.provider_id }}</span><span>输入 {{ num(step.call.input_tokens) }} / 输出 {{ num(step.call.output_tokens) }}</span><strong>{{ num(step.call.total_tokens) }} Token</strong></div>
                  <details class="model-exchange" open><summary>模型请求与响应</summary><div class="exchange-content"><h4>请求</h4><div v-for="(message, i) in modelMessages(step.call.request_text)" :key="i" class="model-message"><span>{{ message.role }}</span><pre>{{ message.content }}</pre></div><h4>响应</h4><pre class="model-response">{{ prettyData(step.call.response_text) || '未返回内容' }}</pre><p class="call-footnote">缓存命中 {{ num(step.call.cached_tokens) }} Token · {{ step.call.source === 'reported' ? '服务商上报' : step.call.source === 'mock' ? '模拟调用' : '用量未知' }}</p></div></details>
                </template>
                <template v-else><section v-if="step.queryComparison" class="query-comparison" aria-label="用户原文与实际检索语句"><p class="step-reason">{{ step.queryComparison.explanation }}</p><div class="query-texts"><div><h4>用户原文</h4><pre>{{ step.queryComparison.original }}</pre></div><div><h4>实际检索语句</h4><pre>{{ step.queryComparison.query }}</pre></div></div></section><p v-if="step.data?.reason" class="step-reason">{{ step.data.reason }}</p><details v-if="stageFacts(step.data).length" class="stage-detail" :open="step.name === '查询意图与路径' || step.name === '查询未执行'"><summary>操作详情</summary><dl><div v-for="fact in stageFacts(step.data)" :key="fact.label"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div></dl></details></template>
              </div></li>
              <li><span class="step-dot"><AppIcon name="chat" :size="12" /></span><div class="step-body"><div><strong>{{ detail.request.continuation ? '本次续写输出' : '最终输出' }}</strong><span>{{ labels[detail.status] }}</span></div><div v-if="detail.answer" class="timeline-answer" v-html="outputHtml" /><p v-else class="step-reason">尚无输出内容</p></div></li>
              <li v-if="clientEvents.length"><span class="step-dot"><AppIcon name="check" :size="12" /></span><div class="step-body"><div><strong>浏览器接收与页面展示</strong><span>浏览器独立计时</span></div><dl class="client-events"><div v-for="(event, i) in clientEvents" :key="i"><dt>{{ event.name }}</dt><dd>+{{ duration(event.elapsed_ms) }}</dd></div></dl><p class="step-reason">相对页面发起请求计时，包含网络与浏览器处理，不能与服务端阶段耗时相加。</p></div></li>
              <li v-else><span class="step-dot skipped"><AppIcon name="clock" :size="12" /></span><div class="step-body"><div><strong>浏览器接收与页面展示</strong><span>未记录</span></div><p class="step-reason">此记录暂无浏览器回传数据；旧记录无法补录，新增请求完成后可刷新查看。</p></div></li>
            </ol>
          </section>
          </div>
        </template>
        <div v-else class="panel monitor-empty trace-placeholder"><AppIcon name="workflow" :size="34" /><strong>暂无执行记录</strong><p>请选择其他历史对话或调整筛选条件。</p></div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.agent-monitor { display: grid; gap: 20px; }
.filter-summary { display: flex; flex-wrap: wrap; gap: 12px 24px; color: #96889f; font-size: 12px; padding: 0 2px; }.filter-summary strong { color: var(--accent); font-size: 15px; }
.section-heading, .trace-title, .request-meta, .request-pagination, .request-stats { display: flex; align-items: center; gap: 10px; }
.monitor-filters { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.5fr) minmax(0, .7fr) auto; align-items: end; gap: 18px; padding: 20px; }.monitor-filters > div { display: grid; gap: 9px; min-width: 0; font-size: 13px; color: #505166; }.monitor-filters input { height: 40px; }.monitor-filters :deep(.app-select-trigger) { min-height: 40px; }
.monitor-layout { display: grid; grid-template-columns: minmax(0, 1fr); align-items: start; gap: 20px; }.request-panel { overflow: hidden; }.request-heading { padding: 20px; border-bottom: 1px solid var(--border); }.request-heading h3 { font-size: 15px; }.request-heading h3 span { margin-left: 8px; background: var(--accent-soft); color: var(--accent); padding: 3px 7px; border-radius: 5px; font-size: 12px; }.request-heading p { margin-top: 10px; color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.request-list { max-height: 680px; overflow-y: auto; padding: 8px; }.request-item { display: grid; width: 100%; text-align: left; justify-content: stretch; gap: 12px; border: 1px solid transparent; border-radius: 9px; padding: 14px; margin-bottom: 5px; }.request-item.selected { background: #f4f1fd; border-color: #e4dcf6; }.request-item strong { line-height: 1.7; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: #49405a; }.request-meta { justify-content: space-between; gap: 5px; }.request-meta time { font-size: 11px; color: var(--muted); }.request-stats { color: #9c92aa; font-size: 11px; gap: 7px; }
.status { display: inline-block; flex-shrink: 0; border-radius: 5px; padding: 4px 7px; background: #f1eff5; color: #93869f; font-size: 11px; }.status.success { background: #eaf5ee; color: #508466; }.status.error { background: #fceff0; color: #bf6170; }.status.running { background: #eeebfa; color: var(--accent); }
.request-pagination { justify-content: center; padding: 14px; border-top: 1px solid var(--border); font-size: 12px; color: var(--muted); }.request-pagination button { min-height: 30px; padding: 6px 9px; }.trace-area { display: grid; gap: 18px; min-width: 0; }.trace-overview, .trace-section { padding: 24px; }.trace-title { align-items: flex-start; justify-content: space-between; }.trace-title h3 { font-size: 17px; line-height: 1.7; overflow-wrap: anywhere; }.trace-id { font-size: 11px; color: #a299ad; line-height: 1.8; margin-top: 9px; overflow-wrap: anywhere; }
.trace-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 24px 0 16px; }.trace-metrics > div { display: grid; gap: 10px; border-right: 1px solid var(--border); }.trace-metrics > div:last-child { border: 0; }.trace-metrics span { font-size: 12px; color: var(--muted); }.trace-metrics strong { font-size: 21px; color: #554567; overflow-wrap: anywhere; }.trace-metrics small { font-size: 12px; font-weight: 400; color: #a699b5; }.monitor-hint, .section-description { font-size: 12px; color: #9b91a8; line-height: 1.9; }.monitor-hint { padding: 10px 12px; background: #faf9fd; border-radius: 7px; }.section-heading { color: var(--accent); margin-bottom: 12px; }.section-heading h3 { font-size: 15px; color: #51465e; }.section-heading > span { margin-left: auto; color: var(--muted); font-size: 12px; }
.trace-timeline { list-style: none; padding: 0; margin: 22px 0 0; }.trace-timeline li { display: flex; align-items: flex-start; gap: 14px; position: relative; padding-bottom: 22px; }.trace-timeline li:last-child { padding-bottom: 0; }.trace-timeline li:not(:last-child)::before { content: ''; position: absolute; left: 10px; top: 22px; bottom: 0; width: 1px; background: #eae4f3; }.step-dot { width: 21px; height: 21px; flex-shrink: 0; display: grid; place-items: center; border-radius: 50%; background: #eeebfa; color: #9180b3; }.step-dot.error { background: #fceff0; color: #bf6170; }.step-body { min-width: 0; flex: 1; }.step-body > div { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; min-height: 21px; }.step-body strong { font-size: 13px; font-weight: 500; }.step-body span { color: #a99eb4; font-size: 11px; }.step-body pre { margin: 10px 0 0; font-size: 11px; color: #8e839b; background: #faf9fc; padding: 10px; border-radius: 6px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; line-height: 1.8; }.model-call { border: 1px solid var(--border); border-radius: 9px; margin-top: 12px; overflow: hidden; }.model-call summary { display: flex; align-items: center; gap: 12px; cursor: pointer; padding: 15px; background: #fcfbfe; }.model-call summary::after { content: '+'; color: #a697b8; }.model-call[open] summary::after { content: '−'; }.call-index { display: grid; place-items: center; width: 25px; height: 25px; border-radius: 7px; background: var(--accent-soft); color: var(--accent); font-size: 12px; flex-shrink: 0; }.call-label { flex: 1; min-width: 0; }.call-label strong { font-size: 13px; }.call-label small, .call-total small { display: block; margin-top: 5px; font-size: 11px; color: #a095ad; overflow-wrap: anywhere; }.call-total { text-align: right; font-size: 14px; color: #7c659b; }.call-body { padding: 16px; border-top: 1px solid var(--border); }.call-tokens { display: flex; flex-wrap: wrap; gap: 16px; font-size: 12px; color: #9b8fa7; }.call-tokens b { color: #756480; font-weight: 500; margin-left: 5px; }.call-body h4 { margin: 18px 0 8px; font-size: 12px; font-weight: 500; }.call-body pre, .request-config pre { padding: 12px; background: #f9f8fc; border-radius: 7px; max-height: 300px; overflow: auto; font-size: 12px; }.answer-content { font-size: 13px; color: #655970; max-height: 500px; overflow-y: auto; }.request-config { border-top: 1px solid var(--border); margin-top: 20px; padding-top: 14px; font-size: 12px; color: #9a8ba9; }.request-config summary { cursor: pointer; }.monitor-empty { display: grid; justify-items: center; gap: 14px; padding: 40px 24px; color: #a396b3; text-align: center; }.monitor-empty strong { font-size: 14px; color: #83718f; }.monitor-empty p { font-size: 12px; line-height: 1.9; }.trace-placeholder { min-height: 310px; align-content: center; }.loading-copy { font-size: 12px; padding: 25px; color: var(--muted); }
@media(max-width: 1150px) { .monitor-layout { grid-template-columns: minmax(0, 1fr); }.trace-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }.trace-metrics > div:nth-child(2) { border: 0; } }
@media(max-width: 760px) {.monitor-filters, .monitor-layout { grid-template-columns: 1fr; }.request-list { max-height: 300px; }.trace-overview, .trace-section { padding: 18px; }.model-call summary { flex-wrap: wrap; }.call-total { margin-left: 37px; text-align: left; } }
.refresh-records { min-height: 40px; white-space: nowrap; }

.trace-primary-row { display: grid; grid-template-columns: minmax(0, 1fr) 320px; align-items: start; gap: 18px; }
.trace-primary-row > .trace-execution { grid-column: 1; grid-row: 1; min-width: 0; }
.trace-primary-row > .trace-overview { grid-column: 2; grid-row: 1; min-width: 0; }
.trace-primary-row .trace-metrics { grid-template-columns: 1fr; gap: 0; margin: 20px 0 16px; }
.trace-primary-row .trace-metrics > div { border-right: 0; border-bottom: 1px solid var(--border); padding: 14px 0; }
.trace-primary-row .trace-metrics > div:first-child { padding-top: 0; }
.trace-primary-row .trace-metrics > div:last-child { border-bottom: 0; }
@media(max-width: 900px) {
  .trace-primary-row { grid-template-columns: minmax(0, 1fr) 260px; }
  .trace-primary-row > .trace-overview { padding: 18px; }
}
@media(max-width: 640px) {
  .trace-primary-row { grid-template-columns: minmax(0, 1fr); }
  .trace-primary-row > .trace-overview { grid-column: 1; grid-row: 2; }
}

/* Filters stay above a viewport-sized timeline; additional detail cards remain below. */
.agent-monitor { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.agent-monitor > .monitor-filters, .agent-monitor > .filter-summary, .agent-monitor > .notice { flex-shrink: 0; }
.monitor-layout { flex: 1; min-height: 0; grid-template-rows: minmax(0, 1fr); }
.trace-area { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.trace-area > * { flex-shrink: 0; }
.trace-primary-row { flex: 0 0 100%; min-height: 0; grid-template-rows: minmax(0, 1fr); }
.trace-primary-row > .trace-execution { display: flex; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; }
.trace-execution > .section-heading, .trace-execution > .section-description { flex-shrink: 0; }
.trace-execution > .trace-timeline { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; padding-right: 10px; }
.trace-primary-row > .trace-overview { max-height: 100%; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; }
@media(max-width: 640px) {
  .trace-primary-row { flex-basis: auto; grid-template-rows: minmax(280px, 60dvh) auto; }
  .trace-primary-row > .trace-overview { max-height: none; }
}

.step-dot.skipped { background: #f2f2f5; color: #aaa5b2; }
.step-dot.fallback { background: #fff2dd; color: #b88d49; }
.step-reason { margin: 8px 0; color: #988ba2; font-size: 12px; line-height: 1.8; }
.inline-model { display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 12px 14px; margin-top: 12px; border-radius: 8px; background: #f2f0fa; font-size: 12px; color: #92839f; }
.inline-model strong { margin-left: auto; color: #78628e; }
.stage-detail, .model-exchange { margin-top: 10px; font-size: 12px; border: 1px solid #ede9f2; border-radius: 8px; }
.stage-detail summary, .model-exchange summary { cursor: pointer; padding: 10px 12px; color: #9584a4; }
.stage-detail dl { margin: 0; padding: 0 14px 14px; }
.stage-detail dl > div + div { margin-top: 12px; }
.stage-detail dt { color: #9c90a5; margin-bottom: 5px; }
.stage-detail dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: #6c5e79; line-height: 1.9; }
.exchange-content { padding: 0 14px 14px; }
.exchange-content h4 { font-size: 12px; color: #796987; margin: 16px 0 10px; }
.model-message + .model-message { margin-top: 14px; }
.model-message > span { font-size: 11px; color: #a296ac; }
.step-body .exchange-content pre, .step-body > .user-input { color: #665671; font-size: 13px; line-height: 1.85; }
.call-footnote { margin-top: 12px; font-size: 11px; color: #a397ad; }
.step-body > .timeline-answer { display: block; font-size: 13px; line-height: 1.9; color: #685c74; margin-top: 12px; overflow-wrap: anywhere; }
.timeline-answer :deep(p) { margin: 10px 0; }
.timeline-answer :deep(table) { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
.timeline-answer :deep(th), .timeline-answer :deep(td) { border: 1px solid #e9e4ef; padding: 8px 12px; }
.timeline-answer :deep(pre) { white-space: pre-wrap; padding: 12px; }
.timeline-answer :deep(h1), .timeline-answer :deep(h2), .timeline-answer :deep(h3) { font-size: 15px; margin: 16px 0 10px; }
.client-events { padding: 12px 14px; background: #f8f6fb; border-radius: 8px; font-size: 12px; }
.client-events > div { display: flex; justify-content: space-between; padding: 6px 0; }
.client-events dd { margin: 0; color: #a193af; }
.query-comparison { margin-top: 12px; }
.query-texts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.query-texts h4 { margin: 0; font-size: 12px; font-weight: 500; color: #796987; }
.query-texts pre { color: #554567; font-size: 13px; }
@media(max-width: 900px) { .query-texts { grid-template-columns: minmax(0, 1fr); } }
</style>
