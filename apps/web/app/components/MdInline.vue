<script setup lang="ts">
/**
 * One line of prose with its inline math rendered — `Bu$^{1,2}$` reads as a superscript,
 * not as source characters (docs/web.md § Result viewer).
 *
 * The rendered span keeps its original TeX in `data-tex`, which is how copy-as-markdown
 * hands back the `$…$` the document actually carries rather than the drawn glyphs.
 */
import { parseInline } from '~/lib/markdown'

const props = defineProps<{ text: string }>()

const segments = computed(() => parseInline(props.text))
</script>

<template>
  <template v-for="(segment, index) in segments" :key="index">
    <span
      v-if="segment.kind === 'math'"
      class="md-inline-math"
      :data-tex="`$${segment.tex}$`"
    >
      <template v-for="(token, tokenIndex) in segment.tokens" :key="tokenIndex">
        <sup v-if="token.kind === 'sup'">{{ token.text }}</sup>
        <sub v-else-if="token.kind === 'sub'">{{ token.text }}</sub>
        <template v-else>{{ token.text }}</template>
      </template>
    </span>
    <template v-else>{{ segment.text }}</template>
  </template>
</template>
