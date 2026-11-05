<script setup lang="ts">
import { ref } from 'vue'
defineProps<{ casting: boolean }>()
const painting = ref<HTMLElement>()
function portalOrigin() {
  const stage = painting.value?.getBoundingClientRect()
  const page = painting.value?.closest('.login-page')?.getBoundingClientRect()
  if (!stage) return undefined
  return { x: stage.left - (page?.left ?? 0) + stage.width * 500 / 1586, y: stage.top - (page?.top ?? 0) + stage.height * 384 / 992, scale: stage.width / 1586 }
}
defineExpose({ portalOrigin })
// The artwork and its effects share one fixed-ratio stage on every screen.
const dust = Array.from({ length: 24 }, (_, i) => ({
  x: 3 + i * 37 % 59, y: 12 + i * 29 % 64, delay: `${-(i % 8) * .8}s`,
}))
const stars = Array.from({ length: 64 }, () => ({
  x: 3 + Math.random() * 64, y: 5 + Math.random() * 84,
  size: `${.8 + Math.random() * 2.1}px`, delay: `${-Math.random() * 14}s`, duration: `${2.5 + Math.random() * 6}s`,
}))
// Sampled from the bright pixels in the painted blue nebula, rather than empty space.
const nebulaStars = [
  [71.5,85.89],[48.17,84.88],[58.13,89.11],[69.99,84.68],[52.59,80.65],[45.27,86.29],
  [66.08,72.98],[43.88,67.94],[51.45,82.46],[72.89,87.7],[66.2,83.27],[41.11,70.36],
  [59.77,91.13],[65.2,89.31],[69.48,79.44],[59.9,73.19],[52.21,78.63],[64.06,87.3],
  [53.97,84.48],[62.93,84.88],[49.43,68.35],[61.66,87.7],[67.47,90.12],[65.7,86.69],
  [40.98,87.9],[44.89,70.16],[58.01,76.81],[47.29,66.13],[46.53,68.95],[53.59,92.54],
  [41.87,94.15],[68.85,83.06],[53.09,86.49],[49.81,83.87],[77.55,80.85],[73.77,85.08],
  [71.25,82.66],[89.79,85.48],[43.25,87.1],[89.91,80.24],[68.35,92.34],[66.08,92.74],
  [80.08,80.65],[67.72,80.65],[75.41,81.65],[46.15,73.19],
  [38.46,12.3],[58.64,12.9],[43.76,18.15],[61.29,20.36],[34.68,21.37],[26.48,25.6],
  [47.16,27.82],[45.78,31.45],[38.46,39.72],[53.97,42.54],[58.89,43.15],[55.99,57.26],
].map(([x,y]) => ({ x, y, size: `${12 + Math.random() * 8}px`, delay: `${-Math.random() * 14}s`, duration: `${5 + Math.random() * 8}s` }))
const lights = [
  { x: 57.8, y: 12, size: 64, delay: '-1s' },
  { x: 10.5, y: 32.5, size: 46, delay: '-3s' },
  { x: 4.3, y: 58, size: 54, delay: '-2s' },
  { x: 50.4, y: 83.5, size: 36, delay: '-4s' },
  { x: 47, y: 28.5, size: 30, delay: '-.5s' },
].map(light => ({ ...light, delay: `${-Math.random() * 12}s`, duration: `${2.5 + Math.random() * 5}s` }))
</script>

<template>
  <div class="fairy-awakening" :class="{ 'is-casting': casting }" aria-hidden="true">
    <div class="celestial-backdrop" />
    <div ref="painting" class="fairy-painting">
    <div class="nebula-field">
    <img class="fairy-scene" src="/mascot/fairy-celestial-background.png" alt="" width="1586" height="992" fetchpriority="high" />
      <i v-for="(star, i) in nebulaStars" :key="`nebula-${i}`" class="nebula-star" :style="{ left: `${star.x}%`, top: `${star.y}%`, '--nebula-star-size': star.size, '--nebula-star-delay': star.delay, '--nebula-star-duration': star.duration }" />
      <span v-for="(light, i) in lights" :key="`painted-${i}`" class="painted-twinkle" :style="{ left: `${light.x}%`, top: `${light.y}%`, '--twinkle-delay': light.delay, '--twinkle-duration': light.duration }" />
      <span class="nebula-cloud cloud-blue" /><span class="nebula-cloud cloud-gold" />
    </div>
    <div class="living-stars"><i v-for="(star, i) in stars" :key="i" :style="{ left: `${star.x}%`, top: `${star.y}%`, '--star-size': star.size, '--star-delay': star.delay, '--star-duration': star.duration }" />
      <span class="shooting-star meteor-one" /><span class="shooting-star meteor-two" /><span class="shooting-star meteor-three" />
    </div>
    <svg class="intro-orbit" viewBox="0 0 1586 992" fill="none"><ellipse cx="500" cy="384" rx="499" ry="221" transform="rotate(-25 500 384)" pathLength="1000" /></svg>
    <svg width="0" height="0" class="fairy-filter"><defs><filter id="fairy-awakening-outline" x="-20%" y="-20%" width="140%" height="140%" color-interpolation-filters="sRGB"><feMorphology in="SourceAlpha" operator="dilate" radius="1.2" result="expanded"/><feComposite in="expanded" in2="SourceAlpha" operator="out" result="edge"/><feFlood flood-color="#e3ecff"/><feComposite in2="edge" operator="in" result="lit"/><feGaussianBlur in="lit" stdDeviation="3" result="glow"/><feMerge><feMergeNode in="glow"/><feMergeNode in="lit"/></feMerge></filter></defs></svg>
    <div class="fairy-floating"><div class="fairy-body">
      <img class="fairy-outline" src="/mascot/knowledge-fairy.webp" alt="" width="616" height="640" />
      <img class="fairy-material" src="/mascot/knowledge-fairy.webp" alt="" width="616" height="640" fetchpriority="high" />
      <img class="fairy-prismatic" src="/mascot/knowledge-fairy.webp" alt="" width="616" height="640" />
    </div></div>
    <span class="summon-ring" />
    <span v-for="i in 18" :key="`summon-${i}`" class="summon-spark" :style="{ left: `${14 + i * 17 % 38}%`, top: `${15 + i * 23 % 55}%`, '--summon-delay': `${.6 + i * .065}s`, '--summon-drift': `${i % 2 ? -22 : 22}px` }" />
    <svg class="flowing-orbits" viewBox="0 0 1586 992" fill="none">
      <defs><linearGradient id="flowing-orbit-gold"><stop stop-color="#fff6d5"/><stop offset=".5" stop-color="#f8c484"/><stop offset="1" stop-color="#d6e7ff"/></linearGradient></defs>
      <ellipse class="orbit-packet orbit-gold" cx="500" cy="384" rx="499" ry="221" transform="rotate(-25 500 384)" pathLength="1000"/>
      <ellipse class="orbit-packet orbit-blue" cx="500" cy="392" rx="469" ry="245" transform="rotate(-25 500 392)" pathLength="1000"/>
      <ellipse class="orbit-thread" cx="500" cy="384" rx="499" ry="221" transform="rotate(-25 500 384)" pathLength="1000"/>
    </svg>
    <span v-for="(mote, i) in dust" :key="`dust-${i}`" class="celestial-dust" :style="{ left: `${mote.x}%`, top: `${mote.y}%`, '--dust-delay': mote.delay }" />
    <div class="celestial-lights">
      <span v-for="(light, i) in lights" :key="i" class="celestial-light" :style="{ left: `${light.x}%`, top: `${light.y}%`, '--light-size': `${light.size}px`, '--light-delay': light.delay }" />
      <span class="fairy-wand" />
      <span class="cast-wave" />
    </div>
    </div>
    <div class="fairy-message"><h2>让知识，<span>闪闪发光。</span></h2><p>一点灵感，开启无限可能</p></div>
  </div>
</template>

<style scoped>
@property --fairy-fill { syntax:'<percentage>'; inherits:false; initial-value:-25%; }
@property --fairy-sheen { syntax:'<percentage>'; inherits:false; initial-value:-20%; }
.fairy-awakening { position:absolute; inset:0; overflow:hidden; }
.celestial-backdrop { position:absolute; inset:-20px; background:radial-gradient(ellipse at 33% 48%,#091426,#030a14 75%); opacity:1; }
/* Extend only the distant, lower-right nebula beyond the capped illustration stage. */
.celestial-backdrop::before { content:''; position:absolute; left:0; top:0; width:min(70%,1250px); height:100%; background:url('/mascot/fairy-celestial-background.png') 100% 100% / auto 290% no-repeat; opacity:.24; filter:blur(3px); mix-blend-mode:screen; mask-image:linear-gradient(90deg,#000 0%,#000 28%,transparent 90%),linear-gradient(0deg,transparent,#000 18%,#000 78%,transparent); mask-composite:intersect; }
/* Match the source aspect ratio; viewport proportions must never stretch a character. */
.fairy-painting { position:absolute; width:min(1120px,100vw,127.9svh); aspect-ratio:1586/992; mix-blend-mode:screen; left:calc(50% - 290px); top:50%; transform:translate(-33.5%,-50%); }
.nebula-field { position:absolute; inset:0; animation:nebula-drift 22s ease-in-out infinite alternate; }
.nebula-cloud { position:absolute; border-radius:50%; pointer-events:none; mix-blend-mode:screen; filter:blur(18px); }
.cloud-blue { left:10%; top:10%; width:48%; height:65%; background:radial-gradient(ellipse,#79a7ff30,transparent 65%); animation:cloud-sail 14s ease-in-out infinite alternate; }
.cloud-gold { left:2%; top:38%; width:48%; height:40%; background:radial-gradient(ellipse,#d6a36520,transparent 65%); animation:cloud-sail 18s -8s ease-in-out infinite alternate-reverse; }
.living-stars { position:absolute; inset:0; }
.living-stars i { position:absolute; width:var(--star-size); height:var(--star-size); border-radius:50%; background:#e7f2ff; box-shadow:0 0 6px 1px #b6d7ff70; animation:living-star var(--star-duration) var(--star-delay) ease-in-out infinite; }
.living-stars i:nth-child(3n) { background:#ffedbf; box-shadow:0 0 8px 1px #ffd69765; }
.shooting-star { position:absolute; width:90px; height:1px; background:linear-gradient(90deg,transparent,#c7e2ff); border-radius:100%; opacity:0; rotate:28deg; transform-origin:right; box-shadow:0 0 5px #b6d7ff50; animation:meteor-pass 12s -7s linear infinite; }
.meteor-one { left:8%; top:16%; }.meteor-two { left:41%; top:12%; animation-duration:17s; animation-delay:-4s; }.meteor-three { left:37%; top:65%; animation-duration:21s; animation-delay:-15s; width:65px; }
.intro-orbit { position:absolute; inset:0; width:100%; height:100%; overflow:visible; pointer-events:none; }
.intro-orbit ellipse { stroke:#d3e8ff; stroke-width:2; stroke-dasharray:1000; filter:drop-shadow(0 0 7px #a6c8ff); animation:orbit-ignite 3.2s ease-in-out both; }
.fairy-scene { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; animation:celestial-awaken 1.8s ease-out both; mask-image:linear-gradient(90deg,transparent,#000 9%,#000 78%,transparent),linear-gradient(0deg,transparent,#000 12%,#000 87%,transparent); mask-composite:intersect; }
.fairy-filter { position:absolute; }
.fairy-floating { position:absolute; left:10%; top:7%; width:43%; aspect-ratio:616/640; will-change:transform; animation:fairy-levitate 6s ease-in-out infinite; }
.fairy-body { position:absolute; inset:0; will-change:transform; animation:fairy-opening-pose 3.6s cubic-bezier(.2,.65,.3,1) both; transform-origin:30% 40%; }
.fairy-body img { position:absolute; inset:0; display:block; width:100%; height:auto; object-fit:contain; }
.fairy-material { mask-image:linear-gradient(180deg,#000 calc(var(--fairy-fill) - 12%),transparent calc(var(--fairy-fill) + 12%)); animation:fairy-materialize 3.6s cubic-bezier(.2,.65,.3,1) both; filter:drop-shadow(0 0 22px #c7d9ff38) drop-shadow(0 8px 28px #edcb9230); }
.fairy-prismatic { mix-blend-mode:screen; filter:brightness(2.8) saturate(.7) drop-shadow(0 0 12px #c3a9ff); mask-image:linear-gradient(180deg,transparent calc(var(--fairy-sheen) - 9%),#000 var(--fairy-sheen),transparent calc(var(--fairy-sheen) + 9%)); animation:prismatic-scan 3.8s ease-in-out both; }
.nebula-star { position:absolute; width:var(--nebula-star-size); height:var(--nebula-star-size); translate:-50% -50%; border-radius:50%; pointer-events:none; background:radial-gradient(circle,#fff 0 1px,#c8e8ffb0 1.3px,#87bfff40 3px,transparent 8px); mix-blend-mode:screen; opacity:0; animation:nebula-star-flare var(--nebula-star-duration) var(--nebula-star-delay) linear infinite; }
.nebula-star:nth-of-type(5n)::after { content:''; position:absolute; inset:48% 8%; background:linear-gradient(90deg,transparent,#d9eeff,transparent); }
@keyframes nebula-star-flare { 0%,49%,100% { opacity:.02; scale:.55; } 57% { opacity:.15; scale:.8; } 62% { opacity:1; scale:1.15; } 67% { opacity:.2; scale:.8; } 71% { opacity:.75; scale:1; } 82% { opacity:.02; scale:.6; } }
.painted-twinkle { position:absolute; width:58px; aspect-ratio:1; translate:-50% -50%; mix-blend-mode:screen; background:radial-gradient(circle,#fffce9c0, #ffe2ac45 12%,transparent 65%); animation:painted-flash var(--twinkle-duration) var(--twinkle-delay) ease-in-out infinite; }
.painted-twinkle::before,.painted-twinkle::after { content:''; position:absolute; inset:8% 49%; background:linear-gradient(transparent,#fff4d7b0,transparent); }.painted-twinkle::after { rotate:90deg; }
.summon-ring { position:absolute; width:40%; aspect-ratio:1; left:11%; top:12%; border:1px solid #c3dfff; border-radius:50%; box-shadow:0 0 14px #a7c9ff66,inset 0 0 12px #ddbfff40; animation:summon-orbit 3.6s ease-out both; }
.summon-spark { position:absolute; width:3px; height:3px; border-radius:50%; background:#fff5d3; box-shadow:0 0 10px 2px #d8c1ff80; opacity:0; animation:summon-sparks 1.7s var(--summon-delay) ease-out both; }
.fairy-outline { filter:url(#fairy-awakening-outline); animation:fairy-inscribe 3.4s ease-in-out both; }
.flowing-orbits { position:absolute; inset:0; width:100%; height:100%; overflow:visible; }
.orbit-packet { stroke:url(#flowing-orbit-gold); stroke-width:2.4; stroke-linecap:round; stroke-dasharray:1 5 2 7 38 947; filter:drop-shadow(0 0 5px #ffda9e); animation:orbit-circulate 15s linear infinite; }
.orbit-blue { stroke:#d1e6ff; stroke-width:1.8; stroke-dasharray:2 8 20 970; animation-duration:21s; animation-direction:reverse; filter:drop-shadow(0 0 5px #87baff); }
.orbit-thread { stroke:#ffd69c; stroke-width:7; stroke-dasharray:12 988; opacity:.3; filter:blur(5px); animation:orbit-circulate 15s linear infinite; }
.celestial-dust { position:absolute; width:3px; height:3px; border-radius:50%; background:#fff2d0; box-shadow:0 0 8px #efcb8e; animation:dust-rise 5s var(--dust-delay) ease-in-out infinite; }
.celestial-dust:nth-of-type(3n) { background:#cde2ff; width:2px; height:2px; }
.celestial-lights { position:absolute; inset:0; }
.celestial-light { position:absolute; width:var(--light-size); aspect-ratio:1; transform:translate(-50%,-50%); border-radius:50%; background:radial-gradient(circle,#fffaf3b0 0%,#ffe2a657 8%,#e1c8a81a 24%,transparent 65%); mix-blend-mode:screen; animation:celestial-twinkle 5s var(--light-delay) ease-in-out infinite; }
.fairy-wand { position:absolute; width:8.5%; aspect-ratio:1; left:17.2%; top:21%; border-radius:50%; background:radial-gradient(circle,#fffde8a0,#ffe5bd33 19%,transparent 65%); mix-blend-mode:screen; animation:celestial-wand 4s ease-in-out infinite; }
.fairy-message { position:absolute; left:calc(50% - 620px); width:660px; top:calc(50% + min(240px,25svh)); text-align:center; animation:celestial-copy 1s 2.5s both; }
.fairy-message h2 { margin:0; color:#fbf3e7; font:500 clamp(28px,2.5vw,40px)/1.35 'Songti SC','STSong','Noto Serif SC',serif; letter-spacing:.035em; white-space:nowrap; text-shadow:0 0 24px #edc99930; }
.fairy-message h2 span { color:#f0c98f; }
.fairy-message p { margin:10px 0 0; color:#e4e1ec; font:400 14px/1.7 'Songti SC','STSong',serif; letter-spacing:.25em; }
.cast-wave { position:absolute; width:18%; aspect-ratio:1; left:12%; top:12%; border-radius:50%; opacity:0; background:radial-gradient(circle,#fff5db90, #b9d1ff38 18%,transparent 65%); }
.is-casting .fairy-material { animation:none; opacity:1; clip-path:none; mask-image:none; }
.is-casting .fairy-prismatic,.is-casting .summon-ring,.is-casting .summon-spark { display:none; }
.is-casting .fairy-outline { animation:none; opacity:0; }
.is-casting .intro-orbit { display:none; }
.is-casting .fairy-body { animation:fairy-cast 1.1s ease-in-out both; }
.is-casting .fairy-painting { animation:celestial-depart 1.4s ease-in both; transform-origin:33.5% 40%; }
.is-casting .flowing-orbits { animation:orbit-expand 2s ease-in both; }
.is-casting .fairy-wand { animation:celestial-cast 1.9s ease-out both; }
.is-casting .cast-wave { animation:celestial-wave 2.2s ease-out both; }
.is-casting .fairy-message { animation:celestial-copy-out .45s ease-out both; }
@keyframes painted-flash { 0%,40%,100% { opacity:.05; scale:.6; } 51% { opacity:.9; scale:1.15; } 63% { opacity:.16; scale:.8; } 77% { opacity:.45; scale:.95; } }
@keyframes prismatic-scan { 0%,17% { opacity:0; --fairy-sheen:-20%; } 30% { opacity:.9; } 80% { opacity:.8; --fairy-sheen:120%; } 100% { opacity:0; --fairy-sheen:140%; } }
@keyframes summon-orbit { 0% { opacity:0; transform:rotate(-25deg) scale(.3,.18); } 25% { opacity:.9; } 65% { opacity:.7; transform:rotate(12deg) scale(1,.65); } 100% { opacity:0; transform:rotate(25deg) scale(1.12,.7); } }
@keyframes summon-sparks { 0% { opacity:0; transform:translate(0,20px) scale(.3); } 25% { opacity:1; } 100% { opacity:0; transform:translate(var(--summon-drift),-28px) scale(.1); } }
@keyframes nebula-drift { from { transform:translate(-5px,3px) scale(1.015) rotate(-.35deg); } to { transform:translate(7px,-5px) scale(1.035) rotate(.35deg); } }
@keyframes cloud-sail { 0% { opacity:.3; transform:translate(-14px,7px) scale(.95); } 100% { opacity:.9; transform:translate(24px,-14px) scale(1.12); } }
@keyframes living-star { 0%,100% { opacity:.12; transform:translate(0,5px) scale(.6); } 35% { opacity:.8; } 60% { opacity:.35; transform:translate(6px,-9px) scale(1.15); } }
@keyframes meteor-pass { 0%,72% { opacity:0; transform:translate(0,0) scaleX(.5); } 74% { opacity:.75; } 82%,100% { opacity:0; transform:translate(155px,82px) scaleX(1.2); } }
@keyframes orbit-ignite { 0% { opacity:0; stroke-dashoffset:1000; } 12% { opacity:1; } 60% { stroke-dashoffset:0; opacity:.9; } 100% { stroke-dashoffset:-160; opacity:0; } }
@keyframes fairy-opening-pose { 0%,12% { transform:translateY(15px) scale(.94) rotate(-2deg); } 68% { transform:translateY(-3px) scale(1.015) rotate(.5deg); } 100% { transform:translateY(0) scale(1) rotate(0); } }
@keyframes celestial-awaken { from { opacity:.15; filter:brightness(.5); } to { opacity:1; filter:brightness(1); } }
@keyframes celestial-copy { from { opacity:0; translate:0 8px; } to { opacity:1; translate:0 0; } }
@keyframes celestial-twinkle { 0%,100% { opacity:.25; scale:.7; } 50% { opacity:1; scale:1.2; } }
@keyframes celestial-wand { 0%,100% { opacity:.35; scale:.85; } 50% { opacity:.8; scale:1.15; } }
@keyframes celestial-depart { 0%,30% { opacity:1; } 100% { opacity:0; } }
@keyframes fairy-levitate { 0%,50%,100% { transform:translateY(0) rotate(0); } 25% { transform:translateY(-5px) rotate(.35deg); } 75% { transform:translateY(4px) rotate(-.3deg); } }
@keyframes fairy-materialize { 0%,27% { opacity:0; --fairy-fill:-25%; filter:brightness(1.8) drop-shadow(0 0 24px #b7d8ff80); } 60% { opacity:1; --fairy-fill:65%; } 90%,100% { opacity:1; --fairy-fill:125%; filter:brightness(1) drop-shadow(0 0 22px #c7d9ff38) drop-shadow(0 8px 28px #edcb9230); } }
@keyframes fairy-inscribe { 0%,8% { opacity:0; clip-path:inset(0 0 100%); } 22% { opacity:1; } 48% { clip-path:inset(0); opacity:1; } 67% { opacity:1; } 90%,100% { opacity:0; clip-path:inset(0); } }
@keyframes fairy-cast { 0% { transform:rotate(0); opacity:1; } 30% { transform:translate(4px,-7px) rotate(3deg); } 70% { opacity:1; transform:translate(-4px,-12px) rotate(-2deg); } 100% { opacity:0; transform:translate(12px,-28px) scale(1.05); } }
@keyframes orbit-circulate { from { stroke-dashoffset:0; } to { stroke-dashoffset:-1000; } }
@keyframes dust-rise { 0%,100% { opacity:0; transform:translate(0,8px) scale(.5); } 45% { opacity:.85; } 85% { opacity:0; transform:translate(12px,-32px) scale(.9); } }
@keyframes orbit-expand { to { opacity:0; transform:scale(1.2); } }
@keyframes celestial-cast { 0% { opacity:.4; scale:1; } 40% { opacity:1; scale:4; } 100% { opacity:0; scale:5; } }
@keyframes celestial-wave { 0% { opacity:0; scale:.1; } 35% { opacity:.75; } 100% { opacity:0; scale:3; } }
@keyframes celestial-copy-out { to { opacity:0; translate:0 -8px; } }
@media(min-width:701px) and (max-width:1320px) { .fairy-painting { left:32%; width:min(95vw,112svh); }.fairy-message { left:2%; width:58%; }.fairy-message h2 { font-size:28px; } }
@media(max-width:700px) {
  .fairy-awakening { position:relative; width:100%; height:360px; }
  .fairy-painting { width:160%; max-width:none; left:0; top:-25px; transform:none; }
  .fairy-message { left:4%; width:92%; top:auto; bottom:4px; }
  .fairy-message h2 { font-size:30px; }.fairy-message p { font-size:12px; margin-top:6px; }
}
@media(prefers-reduced-motion:reduce) { .fairy-awakening * { animation:none !important; transition:none !important; }.fairy-outline,.fairy-prismatic,.summon-ring,.summon-spark,.intro-orbit,.shooting-star { display:none; }.fairy-material { mask-image:none; } }
</style>
