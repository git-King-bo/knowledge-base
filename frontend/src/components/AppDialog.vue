<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
defineProps<{ title: string }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
onMounted(() => dialog.value?.showModal())
</script>
<template><Teleport to="body"><dialog ref="dialog" class="dialog" aria-labelledby="dialog-title" @cancel.prevent="emit('close')"><header><h2 id="dialog-title">{{ title }}</h2><button class="icon-button" aria-label="关闭" @click="emit('close')"><AppIcon name="close" /></button></header><slot /></dialog></Teleport></template>
