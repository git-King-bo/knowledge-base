<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { fetchKnowledgeBases, fetchProviders } from './lib/api'
import type { KnowledgeBase, ProviderConfig } from './lib/types'
import AppIcon from './components/AppIcon.vue'
import KnowledgeWorkspace from './views/KnowledgeWorkspace.vue'
import RetrievalWorkspace from './views/RetrievalWorkspace.vue'
import UsageDashboard from './views/UsageDashboard.vue'
import ProviderSettings from './views/ProviderSettings.vue'
import { useTask } from './composables/useTask'
const tabs = [
  { id: 'knowledge', label: '知识库', icon: 'book', description: '连接团队知识，让每一份资料都产生价值。' },
  { id: 'retrieval', label: '检索测试', icon: 'search', description: '验证召回结果，让回答有据可依。' },
  { id: 'chat', label: '知识问答', icon: 'chat', description: '基于知识库提问，沿着来源探索答案。' },
  { id: 'usage', label: 'Token 监控', icon: 'chart', description: '看清每一次模型调用，掌握每一份 Token 消耗。' },
  { id: 'settings', label: '模型配置', icon: 'settings', description: '统一管理模型服务，连接你的 AI 能力。' },
]
const activeTab = ref('knowledge')
const selectedBaseIds = reactive<Record<string, string>>({ retrieval: '', chat: '' })
const baseRequests = reactive<Record<string, number>>({ retrieval: 0, chat: 0 })
const bases = ref<KnowledgeBase[]>([])
const providers = ref<ProviderConfig[]>([])
const connected = ref(false)
const { busy, error, run } = useTask()
const current = computed(() => tabs.find(tab => tab.id === activeTab.value)!)
async function load() {
  await run(async () => {
    const [nextBases, nextProviders] = await Promise.all([fetchKnowledgeBases(), fetchProviders()])
    bases.value = nextBases
    providers.value = nextProviders
    connected.value = true
  })
  if (error.value) connected.value = false
}
async function refreshBases() { bases.value = await fetchKnowledgeBases() }
async function refreshProviders() { providers.value = await fetchProviders() }
function navigate(id: string, baseId?: string) {
  if (baseId !== undefined) {
    selectedBaseIds[id] = baseId
    baseRequests[id] = (baseRequests[id] || 0) + 1
  }
  activeTab.value = id
  window.location.hash = id
}
function readHash() {
  const id = window.location.hash.slice(1)
  activeTab.value = tabs.some(tab => tab.id === id) ? id : 'knowledge'
}
onMounted(() => { readHash(); window.addEventListener('hashchange', readHash); void load() })
onUnmounted(() => window.removeEventListener('hashchange', readHash))
</script>
<template>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="#knowledge">
<span class="brand-mark">
<AppIcon name="layers" :size="24" />
</span>
<span>知序<span class="brand-en">KNOWLEDGE OS</span>
</span>
</a>
      <div class="workspace-switch">
<span class="workspace-avatar">K</span>
<div>知识工作空间<small>个人工作空间</small>
</div>
<span class="muted">⌄</span>
</div>
      <span class="nav-caption">工作空间</span>
      <nav aria-label="主导航">
<a v-for="tab in tabs.slice(0, 4)" :key="tab.id" :href="`#${tab.id}`" :class="{ active: activeTab === tab.id }" :aria-current="activeTab === tab.id ? 'page' : undefined">
<AppIcon :name="tab.icon" />{{ tab.label }}<span v-if="tab.id === 'knowledge'" class="nav-count">{{ bases.length }}</span>
</a>
</nav>
      <span class="nav-caption">管理</span>
      <nav>
<a href="#settings" :class="{ active: activeTab === 'settings' }">
<AppIcon name="settings" />模型配置</a>
</nav>
      <div class="sidebar-bottom">
<div class="small-label">知识的价值，在于被使用</div>
<p>从资料到答案，连接每一步。</p>
<div class="connection">
<span class="status-dot" :class="{ offline: !connected }">
</span>{{ connected ? '服务已连接' : busy ? '正在连接服务' : '服务未连接' }}<button class="icon-button" aria-label="重新连接服务" :disabled="busy" @click="load">
<AppIcon name="refresh" :size="15" />
</button>
</div>
</div>
    </aside>
    <div class="main-shell">
      <header class="topbar">
<div>
<span class="muted">工作空间</span>
<span class="breadcrumb-separator">/</span>{{ current.label }}</div>
<span class="topbar-right">
<span class="env-pill">本地工作空间</span>
<span class="user-avatar">知</span>
</span>
</header>
      <main :class="{ 'chat-page': activeTab === 'chat' }">
        <div v-if="error" class="notice error" role="alert">无法连接后端：{{ error }} <button @click="load" :disabled="busy">重试</button>
</div>
        <div v-if="activeTab !== 'chat' && activeTab !== 'usage'" class="page-heading">
<div>
<div class="eyebrow">{{ activeTab === 'usage' ? 'USAGE & ANALYTICS' : 'YOUR KNOWLEDGE, CONNECTED' }}</div>
<h1>{{ current.label }}</h1>
<p>{{ current.description }}</p>
</div>
<span class="page-index">{{ String(tabs.findIndex(tab => tab.id === activeTab) + 1).padStart(2, '0') }} / 05</span>
</div>
        <KnowledgeWorkspace v-if="activeTab === 'knowledge'" :bases="bases" :loading="busy" :refresh="refreshBases" @navigate="navigate" />
        <KeepAlive :max="2">
          <RetrievalWorkspace v-if="activeTab === 'retrieval' || activeTab === 'chat'" :key="activeTab" :mode="activeTab" :bases="bases" :providers="providers" :initial-base-id="selectedBaseIds[activeTab] || ''" :base-request="baseRequests[activeTab] || 0" />
        </KeepAlive>
        <UsageDashboard v-if="activeTab === 'usage'" :providers="providers" :bases="bases" />
        <ProviderSettings v-if="activeTab === 'settings'" :providers="providers" :refresh="refreshProviders" />
      </main>
    </div>
  </div>
</template>
