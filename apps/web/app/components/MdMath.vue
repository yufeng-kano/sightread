<script setup lang="ts">
/**
 * One display-math block, typeset by KaTeX — `\begin{cases}` reads as the braced system
 * it is, not as source code (docs/web.md § Result viewer).
 *
 * `data-md` carries the block's `$$…$$` source, which is what copy-as-markdown hands
 * back. TeX KaTeX cannot parse falls back to the verbatim <pre> this block always was —
 * a wrong formula is worse than a visible one — and the <pre> path is what copy already
 * serializes as `$$…$$` (app/lib/copy.ts).
 */
import { renderTexHtml } from '~/lib/math'

const props = defineProps<{ tex: string }>()

const html = computed(() => renderTexHtml(props.tex, true))
const source = computed(() => `$$\n${props.tex}\n$$`)
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- KaTeX escapes its input; `trust` is off -->
  <div v-if="html !== null" class="md-math-block" :data-md="source" v-html="html" />
  <pre v-else class="md-math">{{ tex }}</pre>
</template>

<style scoped>
/* The formula keeps the body's colour; wider than the measure, it scrolls in place like a
   table rather than stretching the page. */
.md-math-block {
  overflow-x: auto;
  overscroll-behavior-x: contain;
  color: var(--ink-soft);
}

.md-math-block :deep(.katex-display) {
  margin: 0;
}

/* The verbatim fallback, styled here rather than borrowed from the viewer's scope: the
   conditional root must not depend on parent scoped-style propagation to be readable. */
.md-math {
  margin: 0;
  overflow-x: auto;
  color: var(--ink-soft);
  font-family: var(--mono);
  font-size: var(--text-sm);
  line-height: 1.7;
  white-space: pre;
}
</style>
