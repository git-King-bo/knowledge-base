<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import type { KnowledgeBase, ProviderConfig } from '../lib/types'
import { fetchUsage, usageExportUrl, type UsageOverview } from '../lib/usage'
import { useTask } from '../composables/useTask'
import { useAnimatedMetrics } from '../composables/useAnimatedMetrics'
import AppIcon from '../components/AppIcon.vue'
import AppSelect from '../components/AppSelect.vue'
import CountUpNumber from '../components/CountUpNumber.vue'
defineProps<{ providers: ProviderConfig[]; bases: KnowledgeBase[] }>()
const { busy, error, run } = useTask()
const filters = reactive({ days: 7, providerId: '', model: '', action: '', baseId: '' })
const data = ref<UsageOverview>()
const page = ref(1)
const updatedAt = ref('')
const format = (value: number | null | undefined) => value == null ? '—' : value.toLocaleString('zh-CN')
const summary = computed(() => data.value?.summary)
const maxDaily = computed(() => Math.max(1, ...data.value?.daily.map(point => point.total_tokens) || []))
const pageCount = computed(() => Math.max(1, Math.ceil((data.value?.total || 0) / 20)))
const knownRate = computed(() => summary.value?.requests ? Math.round((1 - summary.value.unknown_requests / summary.value.requests) * 100) : 0)
const successRate = computed(() => summary.value?.requests ? `${((1 - summary.value.failures / summary.value.requests) * 100).toFixed(1)}%` : '—')
const modelChartKey = (providerId: string, model: string) => `model:${JSON.stringify([providerId, model])}`
const chartValues = useAnimatedMetrics(() => {
  if (!data.value) return {}
  const values: Record<string, number> = { coverage: knownRate.value }
  for (const point of data.value.daily) {
    values[`day:${point.date}`] = point.total_tokens / maxDaily.value * 100
  }
  for (const item of data.value.models) {
    values[modelChartKey(item.provider_id, item.model)] = summary.value?.total_tokens
      ? item.total_tokens / summary.value.total_tokens * 100 : 0
  }
  return values
})
const actionLabel = (action: string) => ({ ask: '知识问答', chat: '模型对话', embedding: '向量化' }[action] || action)
function load(reset = false) {
  if (reset) page.value = 1
  void run(async () => {
    try {
      const response = await fetchUsage(filters, page.value)
      data.value = response
      updatedAt.value = new Date().toLocaleTimeString('zh-CN')
    } catch (cause) {
      // Do not leave the previous filter's results visible after a failed update.
      if (reset) data.value = undefined
      throw cause
    }
  })
}
function changePage(delta: number) { page.value += delta; load() }
onMounted(() => load())
</script>
<template>
  <div class="section-toolbar usage-toolbar">
<div class="toolbar-actions">
<span class="live-indicator">
<span class="status-dot" :class="{ offline: !!error }">
</span>{{ updatedAt ? `更新于 ${updatedAt}` : '正在获取统计' }}</span>
</div>
<div class="toolbar-actions">
<AppSelect v-model="filters.days" label="统计时间范围" :disabled="busy" :options="[{ value: 1, label: '今天' }, { value: 7, label: '最近 7 天' }, { value: 30, label: '最近 30 天' }, { value: 90, label: '最近 90 天' }]" @change="load(true)" />
<button :disabled="busy" @click="load()">
<AppIcon name="refresh" :size="16" />{{ busy ? '刷新中…' : '刷新数据' }}</button>
<a class="button" :href="usageExportUrl(filters)" download>
<AppIcon name="download" :size="16" />导出 CSV</a>
</div>
</div>
  <div class="filter-bar panel">
<label>服务<AppSelect v-model="filters.providerId" label="服务" :disabled="busy" :options="[{ value: '', label: '全部服务' }, ...providers.map(provider => ({ value: provider.id, label: provider.name })), { value: 'embedding', label: '向量化服务' }]" @change="load(true)" />
</label>
<label>调用类型<AppSelect v-model="filters.action" label="调用类型" :disabled="busy" :options="[{ value: '', label: '全部类型' }, { value: 'ask', label: '知识问答' }, { value: 'chat', label: '模型对话' }, { value: 'embedding', label: '向量化' }]" @change="load(true)" />
</label>
<label>知识库<AppSelect v-model="filters.baseId" label="知识库" :disabled="busy" :options="[{ value: '', label: '全部知识库' }, ...bases.map(base => ({ value: base.id, label: base.name }))]" @change="load(true)" />
</label>
<label>模型<input v-model="filters.model" placeholder="输入完整模型名称" :disabled="busy" @change="load(true)" />
</label>
</div>
  <div v-if="error" class="notice error" role="alert">统计加载失败：{{ error }}<button :disabled="busy" @click="load()">重试</button>
</div>
  <section class="stat-grid four">
<article class="stat-card featured">
<span>总 Token 消耗<AppIcon name="spark" />
</span>
<strong><CountUpNumber :value="summary?.total_tokens" /></strong>
<small>模型已报告的累计用量</small>
</article>
<article class="stat-card">
<span>输入 Token<AppIcon name="upload" />
</span>
<strong><CountUpNumber :value="summary?.input_tokens" /></strong>
<small>含缓存命中 {{ format(summary?.cached_tokens) }} Token</small>
</article>
<article class="stat-card">
<span>输出 Token<AppIcon name="download" />
</span>
<strong><CountUpNumber :value="summary?.output_tokens" /></strong>
<small>模型生成的输出用量</small>
</article>
<article class="stat-card">
<span>模型调用次数<AppIcon name="chart" />
</span>
<strong><CountUpNumber :value="summary?.requests" /></strong>
<small>成功率 {{ successRate }} · 平均 {{ summary ? `${Math.round(summary.avg_latency_ms)} ms` : '—' }}</small>
</article>
</section>
  <div class="analytics-grid animated-analytics" :aria-busy="busy">
<div v-if="busy && data" class="chart-refresh-overlay" role="status">正在更新图表…</div>
<section class="panel trend-panel">
<div class="panel-header">
<div>
<h2>Token 消耗趋势</h2>
<p>按本地日期统计已报告的 Token 总量</p>
</div>
<span class="chart-legend">
<i>
</i>总消耗</span>
</div>
<div v-if="!data || !summary?.total_tokens" class="empty-state chart-empty">
<AppIcon name="chart" :size="30" />
<h3>{{ busy ? '正在加载用量…' : '暂无已报告的 Token 消耗' }}</h3>
<p>完成真实模型调用后，消耗趋势会显示在这里。</p>
</div>
<div v-else class="chart-container">
<div class="chart-y">
<span>{{ format(maxDaily) }}</span>
<span>{{ format(Math.round(maxDaily / 2)) }}</span>
<span>0</span>
</div>
<div class="bar-chart" role="img" :aria-label="`最近 ${filters.days} 天累计消耗 ${summary.total_tokens} Token`">
<div v-for="(point, index) in data.daily" :key="point.date" class="chart-column">
<div class="bar-track">
<div class="chart-bar" :style="{ height: `${chartValues[`day:${point.date}`] ?? 0}%` }" :title="`${point.date}：${format(point.total_tokens)} Token；${point.requests} 次调用`">
</div>
</div>
<span>{{ filters.days <= 7 || index === 0 || index === data.daily.length - 1 || index % Math.ceil(filters.days / 6) === 0 ? point.date.slice(5).replace('-', '/') : '' }}</span>
</div>
</div>
</div>
</section>
<section class="panel coverage-panel">
<div class="panel-header">
<h2>用量数据覆盖</h2>
<span class="badge">真实数据</span>
</div>
<div class="coverage-ring" :style="{ '--coverage': `${chartValues.coverage ?? 0}%` }">
<div>
<strong><CountUpNumber :value="data ? knownRate : undefined" /><template v-if="data">%</template></strong>
<span>已知用量占比</span>
</div>
</div>
<div class="coverage-details">
<span>已报告用量<strong>{{ summary ? format(summary.requests - summary.unknown_requests) : '—' }} 次</strong>
</span>
<span>未知 / Mock<strong>{{ format(summary?.unknown_requests) }} 次</strong>
</span>
<span>失败调用<strong>{{ format(summary?.failures) }} 次</strong>
</span>
</div>
</section>
</div>
  <div class="notice subtle">
<AppIcon name="layers" :size="18" />
<span>统计包含知识问答、模型对话及向量化请求。未知用量和 Mock 调用不计入 Token 总量；缓存命中是输入用量的一部分，不重复累加。历史缺失字段显示为「—」。</span>
</div>
  <section class="panel model-breakdown">
<div class="panel-header">
<h2>模型用量分布</h2>
<span class="muted">按累计 Token 排序</span>
</div>
<div v-if="!data?.models.length" class="compact-empty">暂无模型调用记录</div>
<div v-else class="table-wrap">
<table>
<thead>
<tr>
<th>模型 / 服务</th>
<th>调用次数</th>
<th>输入 Token</th>
<th>输出 Token</th>
<th>总 Token</th>
<th>消耗占比</th>
</tr>
</thead>
<tbody>
<tr v-for="item in data.models" :key="`${item.provider_id}-${item.model}`">
<td>
<strong>{{ item.model }}</strong>
<small>{{ providers.find(provider => provider.id === item.provider_id)?.name || (item.provider_id === 'embedding' ? '向量化服务' : item.provider_id) }}</small>
</td>
<td>{{ format(item.requests) }}<small v-if="item.unknown_requests">{{ item.unknown_requests }} 次用量未知</small>
</td>
<td>{{ format(item.input_tokens) }}</td>
<td>{{ format(item.output_tokens) }}</td>
<td>
<strong>{{ format(item.total_tokens) }}</strong>
</td>
<td>
<div class="share-bar">
<span :style="{ width: `${chartValues[modelChartKey(item.provider_id, item.model)] ?? 0}%` }">
</span>
</div>
<small>{{ summary?.total_tokens ? (item.total_tokens / summary.total_tokens * 100).toFixed(1) : '0.0' }}%</small>
</td>
</tr>
</tbody>
</table>
</div>
</section>
  <section class="panel">
<div class="panel-header">
<h2>调用明细 <span class="badge">{{ format(data?.total) }}</span>
</h2>
<span class="muted">当前筛选范围内的全部调用</span>
</div>
<div v-if="!data?.records.length" class="compact-empty">{{ busy ? '正在加载调用记录…' : '当前筛选条件下暂无记录' }}</div>
<div v-else class="table-wrap">
<table class="usage-table">
<thead>
<tr>
<th>时间 / 类型</th>
<th>模型</th>
<th>输入</th>
<th>输出</th>
<th>缓存命中</th>
<th>总 Token</th>
<th>用量来源</th>
<th>状态 / 耗时</th>
</tr>
</thead>
<tbody>
<tr v-for="record in data.records" :key="record.id">
<td>{{ new Date(record.created_at).toLocaleString('zh-CN', { hour12: false }) }}<small>{{ actionLabel(record.action) }}</small>
</td>
<td :title="record.model">{{ record.model }}</td>
<td>{{ format(record.input_tokens) }}</td>
<td>{{ format(record.output_tokens) }}</td>
<td>{{ format(record.cached_tokens) }}</td>
<td>
<strong>{{ format(record.total_tokens) }}</strong>
</td>
<td>
<span class="badge" :class="record.source === 'reported' ? 'purple' : ''">{{ record.source === 'reported' ? '服务上报' : record.source === 'mock' ? 'Mock' : '未知' }}</span>
</td>
<td>
<span class="badge" :class="record.success ? 'green' : 'red'">{{ record.success ? '成功' : '失败' }}</span>
<small>{{ record.latency_ms }} ms</small>
</td>
</tr>
</tbody>
</table>
</div>
<footer class="pagination">
<span>共 {{ format(data?.total) }} 条 · 第 {{ page }} / {{ pageCount }} 页</span>
<div>
<button :disabled="busy || page <= 1" @click="changePage(-1)">上一页</button>
<button :disabled="busy || page >= pageCount" @click="changePage(1)">下一页</button>
</div>
</footer>
</section>
</template>
