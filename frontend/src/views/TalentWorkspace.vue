<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { request, apiFetch } from '../lib/api'
import { currentUser } from '../lib/auth'
import type { KnowledgeBase } from '../lib/types'
import AppDialog from '../components/AppDialog.vue'
import AppSelect from '../components/AppSelect.vue'
import AppIcon from '../components/AppIcon.vue'

const props = defineProps<{ bases: KnowledgeBase[] }>()
type Row = { openalex_h_index: string | null; id: string; name: string; organization: string; position: string; domain: string; location: string }
type Detail = { id: string; fields: Record<string, string | null>; formulas: Record<string, string>; source_id: string; sheet_name: string; source_row: number; revision: number; indexed: boolean }
const rows = ref<Row[]>([]), total = ref(0), page = ref(1)
const metricSort = ref<'none' | 'desc' | 'asc'>('none')
function toggleMetricSort() { metricSort.value = metricSort.value === 'none' ? 'desc' : metricSort.value === 'desc' ? 'asc' : 'none'; search() }
const base = ref(''), q = ref(''), org = ref(''), domain = ref('')
const error = ref(''), notice = ref(''), busy = ref(false), saving = ref(false), opening = ref(''), detailError = ref('')
const detail = ref<Detail>(), history = ref<{ created_at: string; fields: Record<string, string> }[]>([])
const duplicates = ref<{ name: string; count: number }[]>([])
const editing = ref(false)
const canEdit = computed(() => currentUser.value?.role === 'admin' || currentUser.value?.role === 'editor')
const baseOptions = computed(() => [
  { value: '', label: '全部可访问知识库', description: `在 ${props.bases.length} 个可访问知识库中查找` },
  ...props.bases.map(item => ({ value: item.id, label: item.name, description: item.description || `${item.sourceCount} 份资料` })),
])
const groups = [
  { title: '基本信息', icon: 'file', keys: ['姓名', '英文名', '当前机构', '当前职务', '所在国家／城市', '领域', '人才身份', '技术角色定位', '未来产业方向', '细分关键词'] },
  { title: '个人经历与成果', icon: 'book', keys: ['详细个人简介', '教育经历', '工作经历', '创业／项目经历', '代表成果', '公开观点', '开源资产摘要'] },
  { title: '学术指标', icon: 'chart', keys: ['Google Scholar总引用数', 'Google Scholar h-index', 'Google Scholar主页', '学术指标更新时间', 'OpenAlex作品数', 'OpenAlex总引用数', 'OpenAlex h-index', 'OpenAlex主页', 'OpenAlex指标更新时间'] },
  { title: '联系与资料来源', icon: 'link', keys: ['公开联系方式线索', '来源链接', '证据链接', '深度调研文档'] },
  { title: '更新与运营记录', icon: 'clock', keys: ['本次变化摘要', '待人工确认事项', '上次自动更新时间', '自动更新结果', '关联运营记录'] },
]
const fieldGroups = computed(() => {
  const fields = detail.value?.fields || {}
  const known = new Set(groups.flatMap(group => group.keys))
  return [...groups, { title: '其他信息', icon: 'layers', keys: Object.keys(fields).filter(key => !known.has(key)) }]
    .map(group => ({ ...group, keys: group.keys.filter(key => Object.hasOwn(fields, key)) }))
    .filter(group => group.keys.length)
})
const profileName = computed(() => detail.value?.fields['姓名'] || detail.value?.fields['人员姓名'] || detail.value?.fields['员工姓名'] || detail.value?.fields['name'] || '人才详情')
function isLong(key: string) { return /简介|经历|成果|观点|摘要|记录|事项|链接|文档|线索/.test(key) || (detail.value?.fields[key]?.length || 0) > 80 }
function params() { return new URLSearchParams({ knowledge_base_id: base.value, q: q.value, organization: org.value, domain: domain.value, page: String(page.value), page_size: '30', sort_by: metricSort.value === 'none' ? 'name' : 'openalex_h_index', sort_order: metricSort.value === 'none' ? 'asc' : metricSort.value }) }
async function load() {
  busy.value = true; error.value = ''
  try {
    const data = await request<{ items: Row[]; total: number }>('/talents?' + params())
    rows.value = data.items; total.value = data.total
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
function search() { page.value = 1; void load() }
function reset() { metricSort.value = 'none'; base.value = ''; q.value = ''; org.value = ''; domain.value = ''; duplicates.value = []; notice.value = ''; search() }
async function open(id: string) {
  if (opening.value) return
  opening.value = id; error.value = ''; detailError.value = ''; history.value = []; editing.value = false
  try {
    detail.value = await request<Detail>('/talents/' + id)
    try {
      const records = await request<typeof history.value>('/talents/' + id + '/history')
      if (detail.value?.id === id) history.value = records
    } catch { if (detail.value?.id === id) detailError.value = '修改历史加载失败，当前资料仍可查看。' }
  } catch (e) { error.value = String(e) } finally { opening.value = '' }
}
function closeDetail() { if (!saving.value) detail.value = undefined }
async function save() {
  if (!detail.value || saving.value) return
  saving.value = true; detailError.value = ''
  try {
    await request('/talents/' + detail.value.id, { method: 'PUT', body: JSON.stringify({ fields: detail.value.fields, revision: detail.value.revision }) })
    detail.value = undefined; notice.value = '人才信息已保存，索引更新已加入后台任务。'; await load()
  } catch (e) { detailError.value = String(e) } finally { saving.value = false }
}
async function exportData() {
  try {
    const res = await apiFetch('/talents/export?' + params())
    const url = URL.createObjectURL(await res.blob()), a = document.createElement('a')
    a.href = url; a.download = '人才列表.csv'; a.click(); URL.revokeObjectURL(url)
  } catch (e) { error.value = String(e) }
}
async function checkDuplicates() {
  try {
    duplicates.value = await request('/talents/duplicates')
    notice.value = duplicates.value.length ? '同名仅表示可能重复，请核对机构和来源，系统不会自动合并。' : '没有同名记录。'
  } catch (e) { error.value = String(e) }
}
onMounted(load)
</script>

<template>
  <section class="panel talent-panel">
    <div class="talent-heading">
      <div><div class="heading-title"><span class="heading-icon"><AppIcon name="book" /></span><h2>人才档案</h2></div><p>筛选人才、查看完整资料，持续维护团队的人才积累。</p></div>
      <div class="heading-actions"><button type="button" @click="exportData"><AppIcon name="download" :size="16" />导出结果</button><button type="button" @click="checkDuplicates"><AppIcon name="compare" :size="16" />检查同名</button></div>
    </div>
    <form class="filters" @submit.prevent="search">
      <div class="filter-field base-filter"><span>可访问知识库</span><AppSelect v-model="base" :options="baseOptions" label="可访问知识库" :disabled="busy" @change="search" /></div>
      <label class="filter-field"><span>姓名或简介</span><input v-model="q" aria-label="姓名或简介" placeholder="搜索姓名、简介关键词" /></label>
      <label class="filter-field"><span>机构</span><input v-model="org" aria-label="机构" placeholder="输入机构名称" /></label>
      <label class="filter-field"><span>领域</span><input v-model="domain" aria-label="领域" placeholder="输入专业领域" /></label>
      <div class="filter-actions"><button class="primary" :disabled="busy"><AppIcon name="search" :size="16" />{{ busy ? '查询中…' : '查询' }}</button><button type="button" :disabled="busy" @click="reset">重置</button></div>
    </form>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <div v-if="duplicates.length" class="duplicate-tags"><button v-for="d in duplicates" :key="d.name" :disabled="busy" @click="q = d.name; search()">{{ d.name }}<span>{{ d.count }} 条</span></button></div>
    <div class="result-heading"><h3>人才列表 <span>{{ total.toLocaleString() }}</span></h3><span aria-live="polite">{{ busy ? '正在加载人才资料…' : '点击完整信息，查看人才档案' }}</span></div>
    <div class="table-wrap" :aria-busy="busy">
      <table><colgroup><col style="width: 14%" /><col style="width: 19%" /><col style="width: 22%" /><col style="width: 11%" /><col style="width: 10%" /><col style="width: 14%" /><col style="width: 10%" /></colgroup><thead><tr><th>姓名</th><th>机构</th><th>职务</th><th>领域</th><th>地区</th><th :aria-sort="metricSort === 'desc' ? 'descending' : metricSort === 'asc' ? 'ascending' : 'none'"><button type="button" class="sort-button" :disabled="busy" title="按数值排序，缺失或无效值排在最后；点击切换降序、升序、默认" @click="toggleMetricSort">OpenAlex h-index <span aria-hidden="true">{{ metricSort === 'desc' ? '↓' : metricSort === 'asc' ? '↑' : '↕' }}</span></button></th><th class="action-cell">操作</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id">
          <td><div class="person-name"><span class="avatar">{{ row.name?.slice(0, 1) || '人' }}</span><strong :title="row.name">{{ row.name || '未填写姓名' }}</strong></div></td>
          <td><span class="cell-text" :title="row.organization">{{ row.organization || '—' }}</span></td><td><span class="cell-text" :title="row.position">{{ row.position || '—' }}</span></td><td><span v-if="row.domain" class="domain-tag" :title="row.domain">{{ row.domain }}</span><span v-else>—</span></td><td><span class="cell-text" :title="row.location">{{ row.location || '—' }}</span></td>
          <td><span class="cell-text" :title="row.openalex_h_index || undefined">{{ row.openalex_h_index || '—' }}</span></td><td class="action-cell"><button class="detail-button" :disabled="!!opening" :aria-label="`查看${row.name}的完整信息`" @click="open(row.id)">{{ opening === row.id ? '加载中…' : '完整信息' }}<AppIcon name="arrow" :size="15" /></button></td>
        </tr></tbody>
      </table>
      <div v-if="!rows.length" class="empty-state"><AppIcon :name="busy ? 'clock' : 'search'" :size="30" /><strong>{{ busy ? '正在加载人才记录' : '没有匹配的人才记录' }}</strong><p v-if="!busy">试试调整关键词，或选择其他知识库。</p><button v-if="!busy && (base || q || org || domain)" @click="reset">清除筛选条件</button></div>
    </div>
    <footer class="pagination"><span>每页 30 条 · 共 {{ Math.max(1, Math.ceil(total / 30)) }} 页</span><div><button :disabled="page === 1 || busy" aria-label="上一页" @click="page--; load()"><AppIcon name="back" :size="16" /></button><span>第 {{ page }} 页</span><button :disabled="page * 30 >= total || busy" aria-label="下一页" @click="page++; load()"><AppIcon name="arrow" :size="16" /></button></div></footer>
  </section>

  <AppDialog v-if="detail" title="完整人才信息" wide @close="closeDetail">
    <div class="profile-banner"><span class="avatar profile-avatar">{{ profileName.slice(0, 1) }}</span><div class="profile-intro"><h3>{{ profileName }}</h3><p>{{ [detail.fields['当前机构'], detail.fields['当前职务']].filter(Boolean).join(' · ') || '机构与职务暂未填写' }}</p></div><span class="sync-badge" :class="{ pending: !detail.indexed }"><AppIcon :name="detail.indexed ? 'check' : 'clock'" :size="13" />{{ detail.indexed ? '索引已同步' : '索引待同步' }}</span></div>
    <div class="source-line"><AppIcon name="file" :size="14" /><span>来源：{{ detail.sheet_name }} · 第 {{ detail.source_row }} 行</span><span>{{ Object.keys(detail.fields).length }} 个字段</span></div>
    <p v-if="detailError" class="notice error" role="alert">{{ detailError }}</p>
    <div class="profile-content" :class="{ 'is-editing': editing }" tabindex="0" aria-label="人才完整资料">
      <section v-for="group in fieldGroups" :key="group.title" class="field-section"><div class="section-title"><AppIcon :name="group.icon" :size="17" /><h3>{{ group.title }}</h3><span>{{ group.keys.length }}</span></div>
        <div class="talent-fields"><div v-for="key in group.keys" :key="key" class="field" :class="{ 'field-wide': isLong(key) }">
          <label v-if="editing"><span>{{ key }}</span><textarea v-model="detail.fields[key]" :rows="isLong(key) ? 4 : 2" :disabled="saving" placeholder="暂未填写" /></label>
          <template v-else><span class="field-label">{{ key }}</span><p class="field-value" :class="{ 'is-empty': !detail.fields[key] }">{{ detail.fields[key] || '暂未填写' }}</p></template>
        </div></div>
      </section>
      <details v-if="history.length" class="history-section"><summary><AppIcon name="clock" :size="16" />修改历史 <span>{{ history.length }} 条</span></summary><details v-for="(h, index) in history" :key="`${h.created_at}-${index}`" class="history-entry"><summary>{{ h.created_at }}</summary><dl><div v-for="(value, key) in h.fields" :key="key"><dt>{{ key }}</dt><dd>{{ value || '暂未填写' }}</dd></div></dl></details></details>
    </div>
    <footer class="profile-footer"><span>{{ editing ? '保存后将自动更新检索索引' : canEdit ? '完整保留原始资料，可按需编辑' : '当前账号具有只读权限' }}</span><div><button :disabled="saving" @click="closeDetail">{{ editing ? '取消' : '关闭' }}</button><button v-if="canEdit && !editing" class="primary" @click="editing = true"><AppIcon name="file" :size="15" />编辑资料</button><button v-if="canEdit && editing" class="primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存并更新索引' }}</button></div></footer>
  </AppDialog>
</template>

<style scoped>
.talent-panel { padding: 28px; min-width: 0; max-width: 100%; }
.talent-heading, .heading-title, .heading-actions, .filter-actions, .result-heading, .person-name, .pagination, .pagination > div, .profile-banner, .source-line, .section-title, .profile-footer, .profile-footer > div { display: flex; align-items: center; gap: 12px; }
.talent-heading { justify-content: space-between; gap: 24px; margin-bottom: 26px; }
.heading-title h2 { font-size: 20px; letter-spacing: -.4px; }
.heading-icon { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 11px; background: var(--accent-soft); color: var(--accent); }
.talent-heading p { margin-top: 10px; color: var(--muted); font-size: 13px; line-height: 1.6; }
.heading-actions { flex-shrink: 0; gap: 8px; }
.filters { display: grid; grid-template-columns: minmax(210px, 1.4fr) minmax(150px, 1.2fr) minmax(120px, 1fr) minmax(110px, 1fr) auto; align-items: end; gap: 14px; padding: 20px; border: 1px solid var(--border); border-radius: 12px; background: #fafafe; }
.filter-field { min-width: 0; display: grid; gap: 9px; font-size: 12px; color: #646477; }
.filter-field input { margin: 0; height: 40px; }
.base-filter :deep(.app-select-trigger) { min-height: 40px; }
.filter-actions { gap: 8px; }
.filter-actions button { min-height: 40px; white-space: nowrap; }
.result-heading { justify-content: space-between; margin: 27px 0 15px; }
.result-heading h3 { display: flex; align-items: center; gap: 9px; font-size: 15px; }
.result-heading h3 span { border-radius: 6px; padding: 3px 8px; background: var(--accent-soft); color: var(--accent); font-size: 12px; font-weight: 600; }
.result-heading > span, .pagination { color: var(--muted); font-size: 12px; }
.table-wrap { min-width: 0; max-width: 100%; overflow: auto; border: 1px solid var(--border); border-radius: 12px; }
table { table-layout: fixed; min-width: 1200px; width: 100%; border-collapse: collapse; font-size: 13px; }
th { background: #f8f9fc; color: #818296; font-size: 12px; font-weight: 500; white-space: nowrap; }
td, th { padding: 16px; text-align: left; border-bottom: 1px solid #eff0f5; overflow: hidden; }
td { color: #626376; line-height: 1.6; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: #fcfbff; }
.person-name { min-width: 0; gap: 10px; color: #343446; }
.person-name strong { min-width: 0; font-weight: 600; }
.cell-text, .person-name strong, .domain-tag { display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.avatar { display: grid; place-items: center; flex-shrink: 0; width: 34px; height: 34px; border-radius: 11px; background: #eeebf9; color: #7964b4; font-size: 14px; font-weight: 600; }
.domain-tag { display: inline-block; vertical-align: middle; box-sizing: border-box; padding: 3px 9px; border-radius: 6px; background: #f1f0f8; color: #7c6b9c; font-size: 12px; }
.action-cell { text-align: right; white-space: nowrap; }
.detail-button { min-height: 32px; padding: 5px 9px; border-color: transparent; color: var(--accent); background: transparent; }
.pagination { justify-content: space-between; margin-top: 18px; }
.pagination button { min-height: 32px; padding: 6px 9px; }
.empty-state { padding: 48px 20px; display: grid; justify-items: center; gap: 12px; text-align: center; color: #9a90b5; }
.empty-state strong { color: #666277; font-size: 14px; }
.empty-state p { font-size: 13px; color: var(--muted); }
.duplicate-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.duplicate-tags span { color: var(--muted); font-size: 11px; }
.profile-banner { flex-shrink: 0; padding: 20px; border: 1px solid #eae4f6; border-radius: 12px; background: linear-gradient(110deg, #f4f0fc, #fafaff); }
.profile-avatar { width: 54px; height: 54px; font-size: 23px; border-radius: 16px; background: #e7dff7; }
.profile-intro { min-width: 0; flex: 1; }
.profile-intro h3 { font-size: 21px; overflow-wrap: anywhere; }
.profile-intro p { margin-top: 7px; color: #888095; font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.sync-badge { display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0; padding: 5px 8px; border-radius: 6px; background: #e9f5ef; color: #46856c; font-size: 11px; }
.sync-badge.pending { color: #a27a38; background: #fbf2df; }
.source-line { flex-shrink: 0; gap: 6px; margin: 14px 2px 18px; color: #9590a2; font-size: 12px; }
.source-line span:first-of-type { flex: 1; overflow-wrap: anywhere; }
.profile-content { min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 2px 9px 2px 2px; scrollbar-width: thin; scrollbar-color: #d9d1e8 transparent; }
.field-section + .field-section { margin-top: 24px; }
.section-title { gap: 8px; color: #8b79af; margin-bottom: 12px; }
.section-title h3 { color: #51465f; font-size: 14px; font-weight: 600; }
.section-title > span { margin-left: auto; font-size: 11px; color: #a39baa; }
.talent-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid #eeeaf3; border-radius: 10px; overflow: hidden; background: #fcfbfd; }
.field { padding: 14px 16px; min-width: 0; border-bottom: 1px solid #eeeaf3; }
.field-wide { grid-column: 1 / -1; }
.field-label, .field label > span { display: block; color: #94889e; font-size: 12px; margin-bottom: 7px; }
.field-value { color: #4c4358; font-size: 13px; line-height: 1.85; white-space: pre-wrap; overflow-wrap: anywhere; }
.field-value.is-empty { color: #bbb4c3; }
.field label { margin: 0; }
.field textarea { display: block; margin: 0; font-size: 13px; }
.is-editing .talent-fields { background: #fff; }
.history-section { border: 1px solid #eeeaf3; border-radius: 10px; margin-top: 24px; padding: 14px 16px; font-size: 13px; }
.history-section summary { cursor: pointer; color: #786a8c; line-height: 1.8; }
.history-section summary svg { vertical-align: middle; margin: 0 6px; }
.history-section summary span { color: #a69daf; font-size: 12px; margin-left: 6px; }
.history-entry { margin-top: 12px; }
.history-entry dl { margin: 12px 0; }
.history-entry dl > div { padding: 9px 0; border-bottom: 1px solid #eeeaf3; }
.history-entry dt { color: #94889e; font-size: 12px; }
.history-entry dd { margin: 5px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
.profile-footer { flex-shrink: 0; justify-content: space-between; border-top: 1px solid #eeeaf3; padding-top: 18px; margin-top: 18px; }
.profile-footer > span { color: #a197ad; font-size: 12px; margin-right: auto; }
.profile-footer > div { gap: 8px; }
@media (max-width: 1200px) { .filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }.filter-actions { grid-column: 1 / -1; justify-content: flex-end; } }
@media (max-width: 640px) {
  .talent-panel { padding: 16px; }.talent-heading { flex-direction: column; align-items: flex-start; gap: 16px; }.filters { grid-template-columns: 1fr; padding: 14px; }.result-heading > span { display: none; }td, th { padding: 12px; }.pagination { gap: 8px; }.profile-banner { flex-wrap: wrap; padding: 14px; }.profile-intro { flex-basis: calc(100% - 70px); }.sync-badge { margin-left: 66px; }.talent-fields { grid-template-columns: 1fr; }.source-line { flex-wrap: wrap; }.profile-footer { flex-wrap: wrap; }.profile-footer > span { width: 100%; }.profile-footer > div { margin-left: auto; }
}
.sort-button { padding: 0; min-height: 32px; border: 0; background: transparent; box-shadow: none; color: inherit; font: inherit; white-space: nowrap; }
</style>
