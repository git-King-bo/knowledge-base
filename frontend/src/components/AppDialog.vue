<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
withDefaults(defineProps<{ title: string; wide?: boolean }>(), { wide: false })
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
onMounted(() => dialog.value?.showModal())
</script>
<template><Teleport to="body"><dialog ref="dialog" :class="['dialog', { 'dialog-wide': wide }]" aria-labelledby="dialog-title" @cancel.prevent="emit('close')"><header><h2 id="dialog-title">{{ title }}</h2><button class="icon-button" aria-label="关闭" @click="emit('close')"><AppIcon name="close" /></button></header><slot /></dialog></Teleport></template>

<style scoped>
.dialog-wide { width: 920px; overflow: hidden; }
.dialog-wide[open] { display: flex; flex-direction: column; }
.dialog-wide > header { flex-shrink: 0; }
</style>
