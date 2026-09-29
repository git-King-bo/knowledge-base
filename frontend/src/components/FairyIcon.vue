<script setup lang="ts">
import AppIcon from './AppIcon.vue'
withDefaults(defineProps<{ name?: string; size?: number; portrait?: boolean }>(), {
  name: 'spark', size: 48, portrait: false,
})
</script>

<template>
  <span class="fairy-icon" :class="[`fairy-icon--${name}`, { 'fairy-icon--portrait': portrait }]" :style="{ '--fairy-size': `${size}px` }" aria-hidden="true">
    <img v-if="portrait" src="/mascot/fairy-avatar.webp" alt="" width="192" height="192" decoding="async" />
    <AppIcon v-else :name="name" :size="Math.round(size * .48)" />
    <span v-if="portrait && name !== 'spark'" class="fairy-icon-badge"><AppIcon :name="name" :size="Math.max(10, Math.round(size * .24))" /></span>
    <span v-else class="fairy-icon-glint">✦</span>
  </span>
</template>
