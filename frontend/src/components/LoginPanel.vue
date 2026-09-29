<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { request } from '../lib/api'
import { currentUser, type User } from '../lib/auth'
import KnowledgeOrbit from './KnowledgeOrbit.vue'

const emit = defineEmits<{ entering: []; entered: [] }>()
const entering = ref(false), revealing = ref(false)
let entranceTimers: ReturnType<typeof setTimeout>[] = []
let disposed = false, entranceFinished = false
function finishEntrance() {
  if (!entering.value || entranceFinished) return
  entranceFinished = true
  entranceTimers.forEach(clearTimeout); entranceTimers = []
  emit('entered')
}
function skipEntrance(event: KeyboardEvent) { if (event.key === 'Escape') finishEntrance() }
function visibilityChanged() { if (document.hidden) finishEntrance() }

const username = ref('admin'), password = ref(''), error = ref(''), busy = ref(false)
const showPassword = ref(false), paused = ref(false), reducedMotion = ref(false)
const motionPaused = computed(() => paused.value || reducedMotion.value)
let media: MediaQueryList | undefined
function updateMotion() { reducedMotion.value = media?.matches ?? false; if (reducedMotion.value) finishEntrance() }
onMounted(() => {
  media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  updateMotion()
  media?.addEventListener('change', updateMotion)
  window.addEventListener('keydown', skipEntrance)
  document.addEventListener('visibilitychange', visibilityChanged)
})
onUnmounted(() => {
  disposed = true; entranceTimers.forEach(clearTimeout)
  media?.removeEventListener('change', updateMotion)
  window.removeEventListener('keydown', skipEntrance)
  document.removeEventListener('visibilitychange', visibilityChanged)
})
async function login() {
  if (busy.value || entering.value) return
  busy.value = true
  error.value = ''
  try {
    const user = await request<User>('/auth/login', {
      method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }),
    })
    if (disposed) return
    password.value = ''
    entering.value = true
    emit('entering')
    currentUser.value = user
    if (reducedMotion.value || document.hidden) finishEntrance()
    else {
      entranceTimers.push(setTimeout(() => { revealing.value = true }, 3600))
      entranceTimers.push(setTimeout(finishEntrance, 4800))
    }
  } catch (e) { error.value = e instanceof Error ? e.message : '登录失败，请稍后重试' }
  finally { if (!entering.value) busy.value = false }
}
</script>

<template>
  <main class="login-page" :class="{ 'is-paused': motionPaused, 'is-entering': entering, 'is-revealing': revealing }">
    <KnowledgeOrbit :paused="motionPaused" :travel="entering" />
    <span v-if="entering" class="entrance-status" role="status">登录成功，正在进入…</span>
    <div class="scene-shade" aria-hidden="true"></div>
    <header class="login-header" :inert="entering || undefined">
      <div class="login-brand" aria-label="知序知识库">
        <svg class="login-mark" viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M20 4 35 12.5V27L20 36 5 27V12.5L20 4Z" stroke="currentColor" /><path d="m5 12.5 15 9 15-9M20 21.5V36m-7.5-27.7 15 8.7v14.5" stroke="currentColor" /></svg>
        <span>知序</span>
      </div>
      <button class="motion-toggle" type="button" :aria-pressed="motionPaused" :disabled="reducedMotion"
        :aria-label="reducedMotion ? '已跟随系统减少动态效果' : paused ? '播放背景动效' : '暂停背景动效'" @click="paused = !paused">
        <svg v-if="motionPaused" viewBox="0 0 16 16" aria-hidden="true"><path d="m5 3 8 5-8 5Z" fill="currentColor" /></svg>
        <svg v-else viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3v10M11 3v10" stroke="currentColor" stroke-width="2" /></svg>
        <span>{{ reducedMotion ? '静态模式' : paused ? '播放动效' : '暂停动效' }}</span>
      </button>
    </header>
    <div class="login-layout" :inert="entering || undefined">
      <div class="login-art-space" aria-hidden="true"></div>
      <section class="login-gateway" aria-labelledby="login-title">
        <h1 id="login-title">登录</h1>
        <form class="login-form" :class="{ 'has-error': error }" :aria-busy="busy" @submit.prevent="login">
          <div class="login-field">
            <label for="login-username">用户名</label>
            <div class="input-shell">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="8" r="3.5" /><path d="M5 21v-3a7 7 0 0 1 14 0v3" /></svg>
              <input id="login-username" v-model="username" autocomplete="username" required maxlength="80" placeholder="输入你的用户名"
                :readonly="busy" autocapitalize="none" :spellcheck="false" :aria-describedby="error ? 'login-error' : undefined" @input="error = ''" />
            </div>
          </div>
          <div class="login-field">
            <label for="login-password">密码</label>
            <div class="input-shell">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" /></svg>
              <input id="login-password" v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" required maxlength="256"
                placeholder="输入你的密码" :readonly="busy" :aria-describedby="error ? 'login-error' : undefined" @input="error = ''" />
              <button class="password-toggle" type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" :aria-pressed="showPassword" @click="showPassword = !showPassword">
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6S2 12 2 12Z" /><circle cx="12" cy="12" r="2.5" /><path v-if="showPassword" d="m3 3 18 18" /></svg>
              </button>
            </div>
          </div>
          <div class="form-feedback" aria-live="polite">
            <p v-if="error" id="login-error" role="alert">{{ error }}</p>
          </div>
          <button class="login-submit" type="submit" :disabled="busy">
            <span>{{ busy ? '登录中…' : '登录' }}</span>
            <span v-if="busy" class="login-spinner" aria-hidden="true"></span>
            <svg v-else viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6" /></svg>
          </button>
        </form>

      </section>
    </div>

  </main>
</template>

<style scoped>
.login-page {
  --login-bg:#080d13; --login-text:#f0eee8; --login-muted:#9fa8b1; --login-accent:#edc999;
  --login-line:#ffffff1c; --login-ease:cubic-bezier(.16,1,.3,1);
  position:relative; isolation:isolate; display:flex; flex-direction:column;
  width:100%; max-width:none; margin:0; padding:0; min-height:100svh; overflow:hidden;
  background:var(--login-bg); color:var(--login-text); font-family:'DM Sans','PingFang SC','Microsoft YaHei',sans-serif;
}
.login-page * { box-sizing:border-box; }
.login-page.is-entering { position:fixed; inset:0; z-index:2000; min-height:100dvh; }
.login-header,.login-layout,.scene-shade { transition:opacity 1.1s ease,transform 1.5s cubic-bezier(.4,0,.2,1); }
.is-entering .login-header,.is-entering .login-layout { opacity:0; transform:translateY(-12px); pointer-events:none; }
.is-entering .scene-shade { opacity:0; }
.login-page.is-revealing { opacity:0; transition:opacity 1.2s ease-in-out; pointer-events:none; }
.entrance-status { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; }
.scene-shade { position:absolute; inset:0; z-index:-1; pointer-events:none; background:linear-gradient(90deg,transparent 35%,#080d1340 54%,#080d13e8 76%),linear-gradient(0deg,#080d13 0%,transparent 42%); }
.login-header { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:32px 4.5vw; z-index:1; }
.login-brand { display:flex; align-items:center; gap:13px; font-size:23px; letter-spacing:.15em; font-weight:500; }
.login-mark { width:38px; height:38px; color:var(--login-accent); filter:drop-shadow(0 0 10px #edc9991a); }
.login-page button { font-family:inherit; cursor:pointer; box-shadow:none; transform:none; }
.login-page button:focus-visible,.login-page input:focus-visible { outline:2px solid var(--login-accent); outline-offset:5px; }
.login-page button:disabled { cursor:default; opacity:.65; }
.motion-toggle { display:none; align-items:center; gap:9px; min-height:44px; padding:8px 12px; color:#bec5ca; background:transparent; border:1px solid var(--login-line); border-radius:30px; font-size:11px; }
.motion-toggle svg { width:14px; height:14px; }
.login-layout { width:100%; margin:auto; display:grid; grid-template-columns:minmax(0,1.2fr) minmax(0,1fr); padding:40px 12vw 120px 8vw; gap:8vw; flex:1; align-items:center; }
.login-art-space { min-width:0; }
.login-gateway h1 { margin:0 0 40px; color:var(--login-text); font-size:30px; font-weight:400; letter-spacing:.12em; }
.login-gateway { position:relative; width:100%; max-width:380px; justify-self:end; padding:8px 0; animation:gateway-arrive 1s var(--login-ease) both; }
.login-gateway::before { content:''; position:absolute; left:-38px; top:0; bottom:0; width:1px; background:linear-gradient(180deg,transparent,#e0c39935 28%,#b8cdda20 75%,transparent); opacity:.6; transition:opacity .35s; }
.login-gateway:focus-within::before { opacity:1; }
.login-field+.login-field { margin-top:25px; }
.login-field label { display:flex; justify-content:space-between; margin-bottom:10px; color:#d6d8db; font-size:12px; }
.input-shell { display:flex; align-items:center; min-height:56px; background:linear-gradient(115deg,#ffffff07,#ffffff02); border:1px solid #ffffff22; border-radius:8px; box-shadow:inset 0 1px 0 #ffffff03; transition:border-color .25s,background .25s,box-shadow .25s; }
.input-shell:focus-within { border-color:#d8b98ab3; background:#ffffff08; box-shadow:0 0 0 3px #edc99908,inset 0 1px 0 #ffffff06; }
.input-shell:focus-within>svg { color:#d8b98a; }
.has-error .input-shell { border-color:#dc93886b; }
.input-shell>svg { width:18px; height:18px; margin-left:16px; color:#86929d; stroke:currentColor; stroke-width:1.3; flex:0 0 auto; transition:color .25s; }
.login-page .input-shell input { background:transparent; border:0; box-shadow:none; color:#eceae5; padding:16px 12px; min-width:0; width:100%; border-radius:5px; font:inherit; font-size:14px; }
.login-page .input-shell input::placeholder { color:#7e8995; font-size:12px; }
.login-page .input-shell input:focus-visible { outline-offset:-3px; outline-width:1px; }
.login-page .input-shell input:-webkit-autofill { -webkit-text-fill-color:#eceae5; -webkit-box-shadow:0 0 0 100px #12181e inset; caret-color:white; }
.password-toggle { flex:0 0 44px; display:grid; place-items:center; border:0; min-height:44px; margin-right:3px; padding:10px; background:transparent; color:#939da7; border-radius:4px; }
.password-toggle svg { width:18px; height:18px; stroke:currentColor; stroke-width:1.3; }
.form-feedback { min-height:52px; padding:15px 0 12px; font-size:11px; line-height:1.7; color:#9ca5af; }
.form-feedback p { color:#ffb4a7; margin:0; overflow-wrap:anywhere; }
.login-submit { position:relative; display:flex; align-items:center; justify-content:space-between; overflow:hidden; width:100%; min-height:54px; padding:14px 20px; border-radius:8px; border:1px solid #ebd4b3; background:linear-gradient(110deg,#f0dfc6,#dec098); color:#24201b; font-size:13px; font-weight:600; letter-spacing:.06em; transition:background .2s,border-color .2s; }
.login-submit::before { content:''; position:absolute; inset:0; pointer-events:none; background:linear-gradient(110deg,transparent 20%,#ffffff50 48%,transparent 76%); transform:translateX(-130%); transition:transform .85s cubic-bezier(.2,.65,.3,1); }
.login-submit svg { width:21px; height:21px; stroke:currentColor; stroke-width:1.5; transition:transform .3s var(--login-ease); }
.login-page .login-submit:disabled { opacity:.85; cursor:wait; }
.login-spinner { width:18px; height:18px; border:1.5px solid #24201b40; border-top-color:#24201b; border-radius:50%; animation:login-spin .8s linear infinite; }
@media (hover:hover) and (pointer:fine) {
  .login-page .motion-toggle:hover,.login-page .password-toggle:hover { color:#f0ddbf; background:#ffffff0b; transform:none; box-shadow:none; }
  .input-shell:hover { border-color:#ffffff40; }
  .input-shell:focus-within { border-color:#d8b98ab3; }
  .login-page .login-submit:hover { border-color:#f6e8d3; transform:none; box-shadow:0 5px 24px #edc99912; }
  .login-submit:hover::before { transform:translateX(130%); }
  .login-submit:hover svg { transform:translateX(4px); }
}
.login-page .login-submit:active { background:#d9bf9b; }
.is-paused .login-gateway { animation:none; }
@keyframes gateway-arrive { from { opacity:.35; transform:translateX(16px); } to { opacity:1; transform:translateX(0); } }
@keyframes login-spin { to { transform:rotate(360deg); } }
@media (max-width:1000px) {
  .login-layout { padding:40px 6vw 100px; gap:5vw; grid-template-columns:minmax(0,1fr) minmax(0,1fr); }
}
@media (max-width:700px) {
  .login-header { padding:22px 24px; } .login-mark { width:32px; height:32px; } .login-brand { font-size:20px; }
  .login-layout { display:flex; flex-direction:column; align-items:stretch; gap:0; padding:0 28px 48px; max-width:460px; }
  .login-art-space { min-height:180px; }
  .login-gateway { max-width:none; background:#080d13d9; padding:24px 0; }
  .login-gateway::before { display:none; }
  .login-gateway h1 { font-size:26px; margin-bottom:28px; }
  .scene-shade { background:linear-gradient(0deg,#080d13 30%,#080d1330 75%); }
}
@media (max-width:360px) { .login-layout { padding-left:22px; padding-right:22px; } .login-header { padding:18px 22px; } }
@media (prefers-reduced-motion:reduce) { .login-page *, .login-page *::before, .login-page *::after { animation:none !important; transition:none !important; } }
</style>
