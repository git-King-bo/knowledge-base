<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import MacDialog from '../components/MacDialog.vue'
import hero from '../assets/hero.png'
const visible = ref(false), nested = ref(false), mounted = ref(true), useOrigin = ref(true), missing = ref(false)
const trigger = ref<HTMLButtonElement>(), innerTrigger = ref<HTMLButtonElement>()
const duration = ref(680), dockX = ref(.5), top = ref(85), left = ref(50)
const positions = [
  { name: '右侧', x: 94, y: 50 }, { name: '左侧', x: 6, y: 50 },
  { name: '上方', x: 50, y: 5 }, { name: '下方', x: 50, y: 95 },
  { name: '内部偏右', x: 57, y: 50 }, { name: '内部偏上', x: 50, y: 43 },
]
const timers = new Set<ReturnType<typeof setTimeout>>()
function later(fn: () => void, ms: number) { const timer = setTimeout(() => { timers.delete(timer); fn() }, ms); timers.add(timer) }
function reverse() { visible.value = false; later(() => { visible.value = true }, duration.value * .4) }
onBeforeUnmount(() => timers.forEach(clearTimeout))
</script>
<template>
  <main style="padding: 32px; max-width: 800px">
    <h1>MacDialog 动画验证</h1>
    <p>选择目标方向，对照文字和图片是否一起向按钮收窄。可将时长调至 1600ms 观察弧线。</p>
    <div style="display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0">
      <button v-for="position in positions" :key="position.name" @click="left = position.x; top = position.y; useOrigin = true; missing = false">{{ position.name }}</button>
      <button @click="useOrigin = false; dockX = .5">默认底部中央</button>
    </div>
    <label>时长（ms）<input v-model.number="duration" type="number" min="0" step="100"></label>
    <label>底部比例<input v-model.number="dockX" type="range" min="0" max="1" step=".05"></label>
    <label>目标垂直位置<input v-model.number="top" type="range" min="3" max="92"></label>
    <label>目标水平位置<input v-model.number="left" type="range" min="6" max="94"></label>
    <label><input v-model="useOrigin" type="checkbox">使用按钮目标</label>
    <label><input v-model="missing" type="checkbox">隐藏目标</label>
    <button @click="mounted = !mounted">{{ mounted ? '卸载弹窗' : '挂载弹窗' }}</button>
    <button @click="mounted = true; visible = true">打开（包括无效目标）</button>
    <button @click="mounted = true; visible = true; later(() => { visible = false }, duration * .6)">打开后中途反向</button>
    <button ref="trigger" :style="{ position: 'fixed', top: `${top}vh`, left: `${left}vw`, transform: 'translate(-50%, -50%)', visibility: missing ? 'hidden' : 'visible' }" class="primary" @click="visible = true">目标按钮</button>
    <MacDialog v-if="mounted" v-model="visible" :origin="useOrigin ? trigger : undefined" :duration="duration" :dock-x="dockX" title="可变形窗口">
      <label>表单状态<input value="关闭后再次打开，这段内容仍保留"></label>
      <label>选择状态<select><option>选项一</option><option>选项二</option></select></label>
      <div style="height: 160px; overflow: auto; border: 1px solid #ddd">
        <p v-for="i in 20" :key="i">滚动内容第 {{ i }} 行：文字与窗口共同形变。</p>
      </div>
      <img :src="hero" alt="示例插图" style="width: 100%; height: 110px; object-fit: cover">
      <button ref="innerTrigger" @click="nested = true">打开嵌套弹窗</button>
      <template #footer>
        <button @click="left = 50; top = 3; visible = false">移动目标后关闭</button>
        <button @click="missing = true; visible = false">隐藏目标后关闭</button>
        <button @click="reverse">关闭后中途反向</button>
        <button @click="later(() => { mounted = false }, 200); visible = false">动画中卸载</button>
        <button @click="visible = false">关闭</button>
      </template>
      <MacDialog v-model="nested" :origin="innerTrigger" :duration="duration" title="嵌套弹窗">
        <textarea rows="4" placeholder="父窗口的输入与滚动位置保持不变" />
        <template #footer><button @click="nested = false">返回父窗口</button></template>
      </MacDialog>
    </MacDialog>
  </main>
</template>
