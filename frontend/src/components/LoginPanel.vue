<script setup lang="ts">
import { useUpdateGuard } from '../lib/updateSafety'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { request } from '../lib/api'
import { currentUser, type User } from '../lib/auth'
import KnowledgeOrbit from './KnowledgeOrbit.vue'
import FairyAwakening from './FairyAwakening.vue'

const emit = defineEmits<{ entering: []; entered: [] }>()
const entering = ref(false), revealing = ref(false)
const fairyScene = ref<InstanceType<typeof FairyAwakening>>()
const portalOrigin = ref<{ x: number; y: number; scale: number }>()
const entranceFadeMs = 900
let entranceTimers: ReturnType<typeof setTimeout>[] = []
let disposed = false, entranceFinished = false
function finishEntrance() {
  if (!entering.value || entranceFinished) return
  entranceFinished = true
  entranceTimers.forEach(clearTimeout); entranceTimers = []
  emit('entered')
}
function entranceTransitionEnded(event: TransitionEvent) {
  if (revealing.value && event.target === event.currentTarget && event.propertyName === 'opacity') finishEntrance()
}
function skipEntrance(event: KeyboardEvent) { if (event.key === 'Escape') finishEntrance() }
const hidden = ref(false)
function visibilityChanged() { hidden.value = document.hidden; if (document.hidden) finishEntrance() }

const username = ref(''), password = ref(''), error = ref(''), busy = ref(false)
useUpdateGuard({ label: '登录输入（不会保存为草稿）', dirty: () => !entering.value && Boolean(username.value || password.value), busy: () => busy.value })
const showPassword = ref(false), paused = ref(false), reducedMotion = ref(false)
const motionPaused = computed(() => paused.value || reducedMotion.value || hidden.value)
let media: MediaQueryList | undefined
function updateMotion() { reducedMotion.value = media?.matches ?? false; if (reducedMotion.value) finishEntrance() }
onMounted(() => {
  media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  updateMotion()
  visibilityChanged()
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
    portalOrigin.value = fairyScene.value?.portalOrigin()
    entering.value = true
    emit('entering')
    currentUser.value = user
    await nextTick()
    portalOrigin.value = fairyScene.value?.portalOrigin()
    if (disposed) return
    if (motionPaused.value) finishEntrance()
    else {
      entranceTimers.push(setTimeout(() => {
        revealing.value = true
        // Normal completion comes from transitionend. This only releases a missing event.
        entranceTimers.push(setTimeout(finishEntrance, entranceFadeMs + 250))
      }, 2300))
    }
  } catch (e) { error.value = e instanceof Error ? e.message : '登录失败，请稍后重试' }
  finally { if (!entering.value) busy.value = false }
}
</script>

<template>
  <main class="login-page" :style="{ '--entrance-fade-duration': `${entranceFadeMs}ms` }" @transitionend="entranceTransitionEnded" :class="{ 'is-paused': motionPaused, 'is-entering': entering, 'is-revealing': revealing }">
    <KnowledgeOrbit :paused="motionPaused" :travel="entering" :origin="portalOrigin" />
    <span v-if="entering" class="entrance-status" role="status">登录成功，正在进入…</span>
    <div class="scene-shade" aria-hidden="true"></div>
    <header class="login-header" :inert="entering || undefined">
      <div class="login-brand" aria-label="知序知识库">
        <svg class="login-mark" viewBox="0 0 48 52" fill="none" aria-hidden="true"><path d="M24 2 46 26 24 50 2 26 24 2Z" stroke="currentColor" stroke-width="1.2"/><path d="m24 2 4 20 18 4-18 4-4 20-4-20L2 26l18-4 4-20Z" fill="currentColor"/><path d="M8 19 40 33M24 2v48" stroke="currentColor" stroke-width=".8"/></svg>
        <span>知序</span>
      </div>
      <!-- <div class="motion-controls">
      <button class="motion-toggle" type="button" :aria-pressed="motionPaused" :disabled="reducedMotion"
        :aria-label="reducedMotion ? '已跟随系统减少动态效果' : paused ? '播放背景动效' : '暂停背景动效'" @click="paused = !paused">
        <svg v-if="motionPaused" viewBox="0 0 16 16" aria-hidden="true"><path d="m5 3 8 5-8 5Z" fill="currentColor" /></svg>
        <svg v-else viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3v10M11 3v10" stroke="currentColor" stroke-width="2" /></svg>
        <span>{{ reducedMotion ? '静态模式' : paused ? '播放动效' : '暂停动效' }}</span>
      </button>
      </div> -->
    </header>
    <div class="login-layout" :inert="entering || undefined">
      <div class="login-art-space"><FairyAwakening ref="fairyScene" :casting="entering" /></div>
      <section class="login-gateway" aria-labelledby="login-title">
        <h1 id="login-title">欢迎回来</h1>
        <p class="login-intro">和知识精灵一起，连接每一个灵感。</p>
        <form class="login-form" :class="{ 'has-error': error }" :aria-busy="busy" @submit.prevent="login">
          <div class="login-field">
            <label for="login-username">用户名</label>
            <div class="input-shell">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="8" r="3.5" /><path d="M5 21v-3a7 7 0 0 1 14 0v3" /></svg>
              <input id="login-username" v-model="username" autocomplete="username" required maxlength="80" placeholder="请输入用户名"
                :readonly="busy" autocapitalize="none" :spellcheck="false" :aria-describedby="error ? 'login-error' : undefined" @input="error = ''" />
            </div>
          </div>
          <div class="login-field">
            <label for="login-password">密码</label>
            <div class="input-shell">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" /></svg>
              <input id="login-password" v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" required maxlength="256"
                placeholder="请输入密码" :readonly="busy" :aria-describedby="error ? 'login-error' : undefined" @input="error = ''" />
              <button class="password-toggle" type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" :aria-pressed="showPassword" @click="showPassword = !showPassword">
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6S2 12 2 12Z" /><circle cx="12" cy="12" r="2.5" /><path v-if="!showPassword" d="m3 3 18 18" /></svg>
              </button>
            </div>
          </div>
          <div class="form-feedback" aria-live="polite">
            <p v-if="error" id="login-error" role="alert">{{ error }}</p>
          </div>
          <button class="login-submit" type="submit" :disabled="busy">
            <span>{{ busy ? '登录中…' : '登录' }}</span>
            <span v-if="busy" class="login-spinner" aria-hidden="true"></span>

          </button>
        </form>

      </section>
    </div>
    <footer class="login-footer" :inert="entering || undefined"><span>A LITTLE KNOWLEDGE MAGIC</span><i aria-hidden="true"></i><span>知识有序，灵感无界。</span></footer>
    <!-- <button v-if="entering" class="login-skip" type="button" @click="finishEntrance">跳过动画 <kbd>Esc</kbd></button> -->
  </main>
</template>

<style scoped>
.login-page {
  --login-bg:#030a14; --login-text:#f7f4f0; --login-muted:#b5b3ce; --login-accent:#f0cc96;
  --login-ease:cubic-bezier(.16,1,.3,1);
  position:relative; isolation:isolate; width:100%; max-width:none; margin:0; padding:0;
  min-height:100svh; height:100svh; overflow:hidden; background:var(--login-bg); color:var(--login-text);
  font-family:'Songti SC','STSong','Noto Serif SC',serif;
}
.login-page * { box-sizing:border-box; }
.login-page.is-entering { will-change:opacity; position:fixed; inset:0; z-index:2000; min-height:100dvh; }
.login-page :deep(.knowledge-orbit) { z-index:2; opacity:.85; mix-blend-mode:screen; }
.is-entering :deep(.knowledge-orbit) { opacity:1; mix-blend-mode:normal; }
.is-entering .scene-shade { opacity:0; transition:opacity .5s; }
.login-header,.login-gateway,.login-footer { transition:opacity .55s ease,transform .8s ease; }
.is-entering .login-header,.is-entering .login-gateway,.is-entering .login-footer { opacity:0; transform:translateY(-12px); pointer-events:none; }
.login-page.is-revealing { opacity:0; transition:opacity var(--entrance-fade-duration) linear; pointer-events:none; }
.entrance-status { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; }
.scene-shade { position:absolute; inset:0; z-index:1; pointer-events:none; background:linear-gradient(90deg,transparent 63%,#02071130 88%); }
.login-header { position:absolute; inset:28px 40px auto; z-index:3; display:flex; align-items:center; justify-content:space-between; gap:20px; }
.login-brand { display:flex; align-items:center; gap:14px; color:#f4d6a7; font-size:27px; font-weight:500; letter-spacing:.02em; }
.login-mark { width:32px; height:36px; color:#f2c98b; }
.login-page button { cursor:pointer; transform:none; }
.login-page .motion-toggle { background:transparent; box-shadow:none; border:0; }
.login-page button:focus-visible,.login-page input:focus-visible { outline:2px solid var(--login-accent); outline-offset:5px; }
.login-page button:disabled { cursor:default; opacity:.65; }
.motion-controls { display:flex; align-items:center; gap:22px; }
.motion-toggle { display:flex; align-items:center; gap:12px; min-height:44px; padding:0; color:#b9bbdf; background:transparent; border:0; box-shadow:none; font:400 12px/1.4 'Songti SC','STSong',serif; letter-spacing:.08em; }
.motion-toggle svg { width:24px; height:24px; padding:5px; border:1px solid #b9bbdf; border-radius:50%; overflow:visible; }
.login-layout { position:static; }
.login-art-space { position:absolute; inset:0; z-index:0; pointer-events:none; }
.login-gateway { position:absolute; left:calc(50% + 280px); top:50%; width:360px; translate:0 -50%; z-index:2; }
.login-gateway h1 { margin:0 0 12px; color:#fbfafa; font:500 32px/1.35 'Songti SC','STSong','Noto Serif SC',serif; letter-spacing:.07em; }
.login-intro { margin:0 0 34px; color:#bab8d3; font-size:14px; line-height:1.65; letter-spacing:.045em; white-space:nowrap; }
.login-field+.login-field { margin-top:22px; }
.login-field label { display:block; margin-bottom:9px; color:#e7e5f0; font-size:13px; line-height:1.4; }
.input-shell { display:flex; align-items:center; min-height:52px; background:linear-gradient(115deg,#181d2ab8,#1d2234b5); border:1px solid #a5a8d388; border-radius:9px; box-shadow:inset 0 1px 0 #ffffff03; transition:border-color .25s,box-shadow .25s; }
.input-shell:focus-within { border-color:#f2d19f; box-shadow:0 0 0 3px #edc99912; }
.has-error .input-shell { border-color:#e6a69d; }
.input-shell>svg { width:19px; height:19px; margin-left:16px; color:#a2a4bf; stroke:currentColor; stroke-width:1.45; flex:0 0 auto; }
.login-page .input-shell input { background:transparent; border:0; box-shadow:none; color:#f4edf0; padding:15px 12px; min-width:0; width:100%; border-radius:10px; font:400 14px/1.4 'Songti SC','STSong',serif; letter-spacing:.07em; }
.login-page .input-shell input::placeholder { color:#9598b5; opacity:1; }
.login-page .input-shell input:focus-visible { outline:0; }
.login-page .input-shell input:-webkit-autofill { -webkit-text-fill-color:#eceae5; -webkit-box-shadow:0 0 0 100px #171e2d inset; caret-color:white; }
.password-toggle { flex:0 0 44px; display:grid; place-items:center; border:0; min-height:44px; margin-right:4px; padding:10px; background:transparent; color:#a2a4bf; border-radius:4px; box-shadow:none; }
.password-toggle svg { width:19px; height:19px; stroke:currentColor; stroke-width:1.4; }
.form-feedback { min-height:28px; padding:5px 0; color:#ffb4a7; font:12px/1.5 'PingFang SC',sans-serif; }
.form-feedback p { color:#ffb4a7; margin:0; overflow-wrap:anywhere; }
.login-submit { position:relative; display:flex; align-items:center; justify-content:center; gap:14px; overflow:hidden; width:100%; min-height:52px; padding:14px 20px; border-radius:10px; border:1px solid #ffe8bf; background:radial-gradient(ellipse at 15% 0%,#fff3ccf0,transparent 58%),linear-gradient(110deg,#edc58f,#f4d8b0 48%,#d9a66d); color:#16171b; font:500 18px/1.3 'Songti SC','STSong',serif; letter-spacing:.14em; box-shadow:inset 0 0 12px #fff6db6b,0 0 32px #edc08c30; transition:filter .2s,box-shadow .2s; }
.login-submit::before { content:''; position:absolute; inset:0; opacity:.45; pointer-events:none; background-size:110px 110px; background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Cpath fill='%23fff' filter='url(%23n)' opacity='.7' d='M0 0h180v180H0z'/%3E%3C/svg%3E"); mix-blend-mode:soft-light; }
.login-page .login-submit:disabled { opacity:.85; cursor:wait; }
.login-spinner { width:18px; height:18px; border:1.5px solid #24201b40; border-top-color:#24201b; border-radius:50%; animation:login-spin .8s linear infinite; }
.login-footer { position:absolute; left:40px; right:40px; bottom:28px; display:flex; align-items:center; gap:24px; z-index:2; color:#c2c6e5; font-size:9px; line-height:1.5; letter-spacing:.35em; white-space:nowrap; }
.login-footer i { flex:1; height:1px; background:linear-gradient(90deg,#e5c28c,#b5b3ee); }
.login-footer span:last-child { color:#e3c395; letter-spacing:.2em; }
.login-skip { position:fixed; right:30px; bottom:28px; z-index:4; padding:10px 15px; border:1px solid #e6cc9b60; border-radius:30px; background:#080d1380; color:#e8d9c3; font-size:12px; }
.login-skip kbd { margin-left:8px; opacity:.55; font-size:10px; }
.is-paused :deep(.fairy-awakening *),.is-paused :deep(.fairy-awakening *::before),.is-paused :deep(.fairy-awakening *::after) { animation-play-state:paused !important; }
.is-paused :deep(.fairy-scene),.is-paused :deep(.fairy-message),.is-paused :deep(.fairy-material) { opacity:1 !important; filter:none !important; clip-path:none !important; mask-image:none !important; }
.is-paused :deep(.fairy-outline),.is-paused :deep(.fairy-prismatic),.is-paused :deep(.summon-ring),.is-paused :deep(.summon-spark) { opacity:0 !important; }
@keyframes login-spin { to { transform:rotate(360deg); } }
@media(hover:hover) and (pointer:fine) { .login-submit:hover { filter:brightness(1.08); box-shadow:inset 0 0 16px #fff6db80,0 0 38px #edc08c45; }.motion-toggle:hover,.password-toggle:hover { color:#fff1d5; } }
@media(min-width:701px) and (max-height:650px) { .login-page { min-height:650px; height:650px; } }
@media(max-width:1320px) and (min-width:701px) { .login-gateway { left:64%; width:31%; }.login-intro { font-size:13px; }.input-shell { min-height:48px; }.input-shell>svg { margin-left:12px; width:20px; height:20px; }.login-page .input-shell input { padding:13px 10px; }.login-submit { min-height:48px; } }
@media(max-width:700px) {
  .login-page { height:auto; min-height:100svh; overflow:hidden; padding:70px 0 25px; }
  .login-header { inset:16px 22px auto; }.motion-controls { gap:13px; }.login-brand { font-size:27px; gap:9px; }.login-mark { width:30px; height:33px; }.motion-toggle { font-size:11px; gap:7px; }.motion-toggle svg { width:23px; height:23px; padding:5px; }
  .login-art-space { position:relative; height:360px; width:100%; }
  .login-gateway { position:relative; left:auto; top:auto; width:auto; translate:none; margin:24px 28px 0; }
  .login-gateway h1 { font-size:32px; margin-bottom:12px; }.login-intro { font-size:13px; margin-bottom:28px; white-space:normal; }
  .login-field label { font-size:14px; margin-bottom:10px; }.login-field+.login-field { margin-top:24px; }.input-shell { min-height:56px; border-radius:10px; }.input-shell>svg { width:21px; height:21px; margin-left:16px; }.login-page .input-shell input { font-size:15px; padding:16px 13px; }.password-toggle { margin-right:3px; flex-basis:44px; }.password-toggle svg { width:21px; height:21px; }
  .form-feedback { min-height:30px; }.login-submit { min-height:56px; font-size:21px; border-radius:12px; }
  .login-footer { position:relative; left:auto; right:auto; bottom:auto; justify-content:center; margin:40px 20px 0; font-size:8px; }.login-footer i,.login-footer span:last-child { display:none; }
  .is-entering .login-art-space { position:fixed; inset:0; height:100dvh; }.is-entering :deep(.fairy-awakening) { height:100%; }.is-entering :deep(.fairy-painting) { top:45px; }.is-entering :deep(.fairy-message) { display:none; }
}
@media(prefers-reduced-motion:reduce) { .login-page *, .login-page *::before, .login-page *::after { animation:none !important; transition:none !important; } }
</style>
