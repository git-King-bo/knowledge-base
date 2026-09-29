<script setup lang="ts">
import { reactive, ref } from 'vue'
import { createProvider, updateProvider, switchProvider, testProvider, chatWithProvider } from '../lib/api'
import type { ProviderConfig } from '../lib/types'
import { useTask } from '../composables/useTask'
import AppIcon from '../components/AppIcon.vue'
import FairyIcon from '../components/FairyIcon.vue'
import AppSelect from '../components/AppSelect.vue'
import AppDialog from '../components/AppDialog.vue'
import MacDialog from '../components/MacDialog.vue'
const props = defineProps<{ providers: ProviderConfig[]; refresh: () => Promise<void> }>()
const { busy, error, run } = useTask()
const editingId = ref('')
const dialog = ref(false)
const dialogOrigin = ref<HTMLElement>()
const helpVisible = ref(false)
const helpTrigger = ref<HTMLButtonElement>()
const notice = ref('')
const testingId = ref('')
const thinkingOptions = [{ value: 'default', label: '默认' }, { value: 'on', label: '开启' }, { value: 'off', label: '关闭' }]
const thinkingValue = (value?: boolean | null) => value == null ? 'default' : value ? 'on' : 'off'
const thinkingFlag = (value: string) => value === 'default' ? null : value === 'on'
const form = reactive({ thinkingMode: 'default', name: '', baseUrl: '', apiKey: '', defaultModel: '' })
const testResults = ref<Record<string, { ok: boolean; message: string }>>({})
const chatProvider = ref<ProviderConfig>()
const prompt = ref('请用一句话介绍你自己。')
const response = ref('')
function open(provider?: ProviderConfig, event?: MouseEvent) {
  dialogOrigin.value = event?.currentTarget as HTMLElement | undefined
  editingId.value = provider?.id || ''
  Object.assign(form, { thinkingMode: thinkingValue(provider?.enableThinking), name: provider?.name || '', baseUrl: provider?.baseUrl || '', apiKey: '', defaultModel: provider?.defaultModel || '' })
  error.value = ''; dialog.value = true
}
function save() {
  void run(async () => {
    const payload = { apiKey: form.apiKey, enableThinking: thinkingFlag(form.thinkingMode), name: form.name.trim(), baseUrl: form.baseUrl.trim(), defaultModel: form.defaultModel.trim() }
    if (!payload.name || !payload.baseUrl || !payload.defaultModel) throw new Error('请填写完整配置')
    if (editingId.value) await updateProvider(editingId.value, payload)
    else await createProvider(payload)
    form.apiKey = ''; await props.refresh(); dialog.value = false; notice.value = '模型服务配置已保存。'
  })
}
function setThinking(provider: ProviderConfig, mode: string) {
  void run(async () => {
    await updateProvider(provider.id, { ...provider, enableThinking: thinkingFlag(mode) })
    await props.refresh()
    notice.value = mode === 'default' ? '思考模式已恢复为模型默认。' : `思考模式已${mode === 'on' ? '开启' : '关闭'}。`
  })
}
function makeDefault(provider: ProviderConfig) { void run(async () => { await switchProvider(provider.id); await props.refresh(); notice.value = `已将 ${provider.name} 设为默认服务。` }) }
function test(provider: ProviderConfig) { testingId.value = provider.id; void run(async () => { testResults.value[provider.id] = await testProvider(provider.id) }) }
function sendTest() {
  if (!chatProvider.value || !prompt.value.trim()) return
  const provider = chatProvider.value
  void run(async () => { response.value = ''; const result = await chatWithProvider({ providerId: provider.id, content: prompt.value.trim() }); response.value = result.content })
}
</script>
<template>
  <div v-if="error && !dialog && !chatProvider" class="notice error" role="alert">{{ error }}</div>
<div v-if="notice" class="notice success" role="status">{{ notice }}</div>
  <div class="section-toolbar">
<div>
<h2>模型服务 <span class="badge">{{ providers.length }}</span>
</h2>
<p class="muted">配置默认模型，供知识问答调用。</p>
</div>
<button class="primary" :disabled="busy" @click="open(undefined, $event)">
<AppIcon name="plus" :size="16" />添加模型服务</button>
</div>
  <div v-if="!providers.length" class="empty-state panel">
<FairyIcon name="settings" :size="88" portrait />
<h3>尚未连接模型服务</h3>
<p>添加兼容服务的 API 地址、密钥和模型名称。</p>
</div>
  <div class="provider-grid">
<article v-for="provider in providers" :key="provider.id" class="panel provider-card">
<div class="provider-heading">
<FairyIcon :name="provider.provider === 'mock' ? 'settings' : 'spark'" :size="54" />
<div>
<h2>{{ provider.name }}</h2>
<span v-if="provider.provider === 'mock'" class="muted">本地测试</span>
</div>
<span v-if="provider.isDefault" class="badge purple">默认服务</span>
</div>
<dl>
<div>
<dt>默认模型</dt>
<dd>{{ provider.defaultModel }}</dd>
</div>
<div>
<dt>API 地址</dt>
<dd>{{ provider.baseUrl }}</dd>
</div>
<div>
<dt>密钥状态</dt>
<dd>{{ provider.apiKeyHint }}</dd>
</div>
</dl>
<div v-if="provider.provider !== 'mock'" class="thinking-setting">
<span>思考模式</span>
<div class="thinking-choices" role="group" :aria-label="`${provider.name}思考模式`">
<button v-for="option in thinkingOptions" :key="option.value" type="button" :disabled="busy"
  :aria-pressed="thinkingValue(provider.enableThinking) === option.value"
  @click="setThinking(provider, option.value)">{{ option.label }}</button>
</div>
</div>
<div v-if="testResults[provider.id]" class="notice" :class="testResults[provider.id]?.ok ? 'success' : 'error'" role="status">{{ testResults[provider.id]?.message }}</div>
<div class="provider-actions">
<button :disabled="busy" @click="open(provider, $event)">编辑</button>
<button :disabled="busy" @click="test(provider)">{{ busy && testingId === provider.id ? '测试中…' : '连接测试' }}</button>
<button :disabled="busy" @click="chatProvider = provider; response = ''; error = ''">试用模型</button>
<button v-if="!provider.isDefault" class="text-button accent-text" :disabled="busy" @click="makeDefault(provider)">设为默认</button>
</div>
</article>
</div>
  <div class="notice subtle">
<AppIcon name="chart" :size="18" />
<span>试用模型产生的真实 Token 用量会进入监控平台。连接测试只检查服务连通性，不计入模型消耗。</span>
</div>
  <MacDialog v-model="dialog" :origin="dialogOrigin" :title="editingId ? '编辑模型服务' : '添加模型服务'" :before-close="done => { if (!busy) done() }">
<div v-if="error" class="notice error" role="alert">{{ error }}</div>
<form @submit.prevent="save">
<label>服务名称<input v-model="form.name" required maxlength="120" placeholder="例如：团队模型服务" autofocus />
</label>
<label>API 地址<input v-model="form.baseUrl" required placeholder="https://your-provider.example/v1" maxlength="300" />
</label>
<button ref="helpTrigger" type="button" class="text-button accent-text" @click="helpVisible = true">如何填写服务地址？</button>
<label>API Key<input v-model="form.apiKey" type="password" autocomplete="new-password" :placeholder="editingId ? '留空保留原密钥' : '输入服务密钥'" />
</label>
<label>默认模型<input v-model="form.defaultModel" required maxlength="120" placeholder="输入服务支持的模型名称" />
</label>
<label v-if="form.baseUrl.trim().replace(/\/$/, '') !== 'local://mock'">思考模式<AppSelect v-model="form.thinkingMode" label="思考模式" :disabled="busy" :options="thinkingOptions" /></label>
<p v-if="form.baseUrl.trim().replace(/\/$/, '') !== 'local://mock'" class="field-hint">开启适合复杂推理，关闭响应更快。不支持思考参数的模型请选择默认。</p>
<footer>
<button type="button" :disabled="busy" @click="dialog = false">取消</button>
<button class="primary" :disabled="busy">{{ busy ? '保存中…' : '保存配置' }}</button>
</footer>
</form>
<MacDialog v-model="helpVisible" :origin="helpTrigger" title="服务地址填写说明">
  <p class="dialog-description">填写模型服务商提供的 API 基础地址，例如 https://your-provider.example/v1。模型名称需要与服务商支持的名称一致。</p>
  <label>临时备注<textarea rows="3" placeholder="记录配置说明，关闭后仍会保留" /></label>
  <template #footer><button type="button" class="primary" @click="helpVisible = false">知道了</button></template>
</MacDialog>
</MacDialog>
  <AppDialog v-if="chatProvider" :title="`试用 ${chatProvider.name}`" @close="!busy && (chatProvider = undefined)">
<div v-if="error" class="notice error" role="alert">{{ error }}</div>
<form @submit.prevent="sendTest">
<label>测试问题<textarea v-model="prompt" required rows="3" maxlength="5000" />
</label>
<p v-if="chatProvider.provider === 'mock'" class="field-hint">Mock 仅用于验证调用链路，不产生真实用量。</p>
<div v-if="response" class="test-response">{{ response }}</div>
<footer>
<button class="primary" :disabled="busy || !prompt.trim()">{{ busy ? '调用中…' : '发送测试请求' }}</button>
</footer>
</form>
</AppDialog>
</template>

<style scoped>
.thinking-setting { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:18px 0; font-size:12px; }
.thinking-choices { display:flex; padding:3px; gap:3px; border:1px solid #d5e1e3; border-radius:12px; background:#edf3f3; }
.thinking-choices button { min-height:38px; padding:6px 13px; border:1px solid transparent; border-radius:9px; background:transparent; box-shadow:none; font-size:12px; }
.thinking-choices button[aria-pressed="true"] { background:#fff; color:#355f70; border-color:#cadce2; }
.thinking-choices button:focus-visible { outline:2px solid #587f92; outline-offset:2px; }
@media (max-width:480px) { .thinking-choices button { min-height:44px; } }
</style>
