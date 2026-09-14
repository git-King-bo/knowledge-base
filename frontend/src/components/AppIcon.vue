<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string> = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  search: 'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  chat: 'M21 11.5a8.5 8.5 0 0 1-8.5 8.5H3l1.8-4A8.5 8.5 0 1 1 21 11.5 M8 10h8 M8 14h5',
  chart: 'M3 3v18h18 M7 15v-4 M12 15V7 M17 15V4',
  settings: 'M4 7h16 M4 17h16 M8 4v6 M16 14v6',
  plus: 'M12 5v14 M5 12h14',
  book: 'M4 3h6a3 3 0 0 1 3 3v15a4 4 0 0 0-4-2H3V3z M13 6a3 3 0 0 1 3-3h5v16h-5a3 3 0 0 0-3 2',
  upload: 'M12 16V3 M7 8l5-5 5 5 M4 16v5h16v-5',
  arrow: 'M5 12h14 M14 7l5 5-5 5',
  back: 'M19 12H5 M10 7l-5 5 5 5',
  file: 'M14 2H5v20h14V7z M14 2v5h5 M8 12h8 M8 16h6',
  refresh: 'M20 7V2 M20 7h-5 M20 7a9 9 0 1 0 1 8',
  download: 'M12 3v13 M7 11l5 5 5-5 M4 17v4h16v-4',
  spark: 'M12 2l3 7 7 3-7 3-3 7-3-7-7-3 7-3z',
  close: 'M6 6l12 12 M6 18L18 6',
  check: 'M5 12l4 4L19 6',
  layers: 'M12 2L2 7l10 5 10-5z M2 12l10 5 10-5 M2 17l10 5 10-5',
  assistant: 'M8 3h8l5 5v8l-5 5H8l-5-5V8z M8 9h8 M8 13h5 M15 16h1',
  summary: 'M6 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2 M8 8h8 M8 12h8 M8 16h5',
  workflow: 'M4 4h6v6H4z M14 14h6v6h-6z M10 7h7v7 M7 10v7h7',
  compare: 'M9 4H4v16h5 M15 4h5v16h-5 M9 9h6 M12 6l3 3-3 3 M15 15H9 M12 12l-3 3 3 3',
  checklist: 'M3 6l2 2 3-4 M11 6h10 M3 13l2 2 3-4 M11 13h10 M4 20h3 M11 20h10',
  globe: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M3 12h18 M12 3c5 5 5 13 0 18 M12 3c-5 5-5 13 0 18',
  send: 'M12 19V5 M6 11l6-6 6 6',
  reset: 'M4 10a8 8 0 1 1 1 8 M4 4v6h6 M12 8v4l3 2',
  link: 'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2',
  clock: 'M12 7v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
}
</script>
<template><svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] || paths.grid" /></svg></template>
