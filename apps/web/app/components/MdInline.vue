<script setup lang="ts">
/**
 * One line of prose with its inline content rendered — `Bu$^{1,2}$` reads as typeset math
 * and `**96.5**` reads bold, not as source characters (docs/web.md § Result viewer).
 * The split lives in `parseInline`; the rendering, including the `data-tex`/`data-src`
 * sources copy-as-markdown reads back, lives in `MdSegments`.
 */
import { parseInline } from '~/lib/markdown'

const props = defineProps<{ text: string }>()

const segments = computed(() => parseInline(props.text))
</script>

<template>
  <MdSegments :segments="segments" />
</template>
