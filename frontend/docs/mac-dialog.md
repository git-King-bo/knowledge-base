# MacDialog

当前项目为 Vue 3 + TypeScript，使用原生 `<dialog>`，未安装 Element Plus。MacDialog 延续 `.dialog` 的配色、圆角、标题和表单样式，以原生模态层提供遮罩、焦点限制、Escape 和焦点返回，以引用计数维护嵌套滚动锁。原有 AppDialog 仍可使用；知识库和模型服务的添加／编辑表单已接入 MacDialog，其中“如何填写服务地址？”是实际嵌套示例。

## 基本用法

```vue
<script setup lang="ts">
import { ref } from 'vue'
import MacDialog from './components/MacDialog.vue'
const visible = ref(false)
const trigger = ref<HTMLButtonElement>()
</script>

<template>
  <button ref="trigger" @click="visible = true">打开</button>
  <MacDialog v-model="visible" :origin="trigger" :duration="680" title="编辑资料">
    <input placeholder="输入内容，关闭后仍保留" />
    <template #footer>
      <button @click="visible = false">完成</button>
    </template>
  </MacDialog>
</template>
```

请保持组件挂载，通过 `v-model` 关闭。使用 `v-if="visible"` 会直接卸载，无法播放关闭动画。需要关闭后释放内容时使用 `destroy-on-close`，它会等动画完成。默认保留同一组真实节点，因此表单值、选区和滚动位置不会因为动画被替换。动画期间画面为静态快照，实时内容在恢复 DOM 后更新。

## 参数、插槽与事件

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `modelValue` / `v-model` | 必传 | 显隐状态 |
| `origin` | 无 | DOM 元素、Vue ref、带 `$el` 的组件实例（包括 Element Plus 按钮）、返回这些对象的函数 |
| `duration` | `680` | 单程完整路径的毫秒数；越小越快，`0` 禁用动画，负数按 `0` 处理。反向仅走剩余路程 |
| `dockX` | `0.5` | 默认底部目标的水平比例，限制在 0～1 |
| `title` | 空 | 标题及原生 dialog 的可访问名称 |
| `destroyOnClose` | `false` | 关闭完成后销毁插槽内容 |
| `closeOnClickModal` | `true` | 点击遮罩请求关闭 |
| `closeOnPressEscape` | `true` | Escape 请求关闭 |
| `beforeClose` | 无 | `(done) => void`，用于拦截关闭按钮、遮罩、Escape；允许时调用 `done()` |

支持默认、`header`、`footer` 插槽，均提供 `{ close }`。额外 class、style、属性和事件透传到内容面板；例如 `style="width: 700px"`。不要在样式中覆盖面板 `opacity`，它用于动画交接。自定义标题可用 `#header="{ titleId }"`，并给标题节点设置 `:id="titleId"`，保持可访问名称关联。

事件为 `update:modelValue`、`open`、`opened`、`close`、`closed`。`open` / `close` 在显隐意图变化时触发；`opened` / `closed` 只在抵达相应终点时触发。中途反向不会发出被取消方向的完成事件。`beforeClose` 不拦截父组件直接改变 v-model。可通过组件 ref 访问 `dialog` 原生元素和 `requestClose()`；应使用 v-model / requestClose 以播放关闭动画，原生 `close()` 或 `form method="dialog"` 会直接关闭并清理。

## 目标位置

点击绑定时同步保存 `currentTarget`，不要保存图标等内部节点对应的 `target`，也不要异步读取事件：

```ts
const origin = ref<HTMLElement>()
function open(event: MouseEvent) {
  origin.value = event.currentTarget as HTMLElement
  visible.value = true
}
```

也可使用 `:origin="() => trigger"`。每次独立打开／关闭读取元素的 `getBoundingClientRect()`；关闭目标不可见或已移除时使用本次打开记录的位置；打开目标无效时使用默认底部目标。中途反向期间不重新读取目标，保证路径连续。元素的尺寸也参与终点映射。比较目标中心与弹窗中心的水平、垂直距离：水平距离更大时横向形变，否则纵向形变（相等时选纵向）。右侧目标右窄左宽，左侧目标左窄右宽，上方目标上窄下宽，下方目标下窄上宽。内部目标也遵循同一规则；中心重合时稳定选择向下。各带沿运动轴保持有序，不会翻折。窗口 resize 时直接完成当前意图，避免使用旧视口画布。

不传目标即可使用底部模式：

```vue
<MacDialog v-model="visible" title="底部展开" :dock-x="0.75" :duration="450">
  弹窗内容
</MacDialog>
```

嵌套时每个弹窗独立维护 v-model、origin、快照和动画进度；将子 MacDialog 放在父插槽中即可，它会 Teleport 到 body 并进入独立原生模态层。父窗口关闭不会自动改变子窗口的 v-model，需要联动时由调用方管理。

## 动画实现与降级

`dialogSnapshot.ts` 仅为截图创建临时克隆，复制表单值与当前滚动视口，包括 textarea；密码按掩码截图。`html-to-image` 将克隆栅格化。`genie.ts` 对窗口及全部内容共同形变，横向运动绘制纵向列带，纵向运动绘制横向行带：靠近目标的一端先收窄，之后沿弯曲边缘收束至目标，打开使用完全相同的进度函数反向播放。不是对真实 DOM 做整块缩放或裁剪。


曲线柔和度 `softness` 根据中心距离和水平偏移计算，范围 0～1。目标越近或越偏向侧面，窄口形成越缓慢，主体也更早跟随：

| 曲线参数 | 远距离底部中央（softness=0） | 近处／侧面（softness=1） |
| --- | --- | --- |
| 收窄阶段完成时刻 | 0.48 | 0.72 |
| 主体开始跟随时刻 | 0.24 | 0.10 |
| 中心移动混入整体平滑进度的权重 | 0 | 0.55 |
| 尾段淡出起点 | 0.94 | 0.88 |

远距离底部中央保留项目原版的 0.48／0.24 参数，保证原有收窄与跟随节奏。其余参数按柔和度连续插值；中心移动从各带的收拢路径混合到共同路径，保留平滑 S 形边缘并减轻侧向急弯。尾段以 smoothstep 渐进淡出整张 Canvas，避免逐带透明度叠加产生接缝。形变的起终点仍精确对应两个矩形。

运动轴上的带间距始终为 `((1 - travel) × sourceLength + travel × targetLength) / bands`，两个矩形的尺寸均为正，因此行带／列带不会交叉。曲线仅取决于冻结的两个矩形和当前进度；反向时几何、柔和度和淡出沿同一路径返回。计时仍为每帧 `Δ时间 / duration`，未改变 duration 的含义。

Canvas 留在当前 dialog 的原生顶层内，支持嵌套层级。真实节点保留，结束时恢复显示；动画帧、900ms 快照超时定时器、临时克隆和画布在结束／卸载时释放。截图任务本身不能强制取消，超时后其迟到结果会被丢弃并清空。失败／超时直接完成最新显隐意图，不阻塞操作。

`prefers-reduced-motion: reduce` 跳过截图和动画，运行中切换也立即完成。字体、跨域图片、视频、复杂 CSS 的快照兼容性受浏览器与 html-to-image 限制，资源失败时走直接显隐降级。

## 验证

```sh
cd frontend
npm run test:dialog
npm test
npm run build
npm run dev
```

开发服务的 `/mac-dialog-demo.html` 是无需后端的交互验证页面，包含文字、图片、选择框、滚动区、嵌套，以及左右上下、内部、默认底部中央的目标预设，可独立调整水平／垂直位置，并触发移动／隐藏目标、双向反向和中途卸载。真实接入可在主页面 `#knowledge` 的“新建知识库”和 `#settings` 检查。

自动测试已通过：11 组弹窗测试，以及现有 7 组回归测试。弹窗测试使用 JSDOM、模拟 Canvas 与可控动画帧，验证四向与内部目标的窄口方向、行／列绘制轴、无翻折、精确终点、柔和曲线连续性、原版底部节奏、尾段淡出、各方向快速反向及原有时长控制、目标解析与位置缓存、真实节点／选区／滚动保留、滚动锁计数、减少动态效果、失败／超时、延迟销毁及卸载。生产构建通过。

**本次未完成实际浏览器动画检查**：Browser 运行时重试后返回 `No browser is available`，浏览器列表为空。用户确认连接后再次检查，Chrome 正在运行，但官方诊断未检测到 ChatGPT 浏览器扩展，且本地通信清单 `com.openai.codexextension.json` 缺失；需重新安装 Browser 插件并确认 Chrome 扩展已安装、启用。自动测试不能替代真实 Canvas／SVG 栅格化、文字图片清晰度、分带接缝、原生焦点返回及遮罩层级的视觉验收。可用浏览器中请在上述示例页面依次检查：左／右／上／下／内部目标，0／680／更慢时长，快速反向，目标移动或消失，子弹窗关闭后父表单和滚动位置，系统减少动态效果，以及动画中卸载后页面恢复交互。
