<script setup lang="ts">
/**
 * The top of the left rail: what this screen is, in two lines.
 *
 * It is not a top bar any more. The design puts the page's identity — an uppercase eyebrow
 * naming the range or the state of the data, then the title in the display serif — at the
 * head of the narrative rail, and the screen's controls either in the rail beneath it or in
 * the panel header they act on (docs/web.md § Design system).
 *
 * The eyebrow is a fact about the data ("Last 30 days", "3 active", "OAuth · no key"), never
 * a line explaining what the page is for.
 */
withDefaults(
  defineProps<{
    title: string
    eyebrow?: string
    /** One step down, for a title that is two words wide ("MCP Connector"). */
    size?: 'md' | 'lg'
  }>(),
  { size: 'lg', eyebrow: undefined },
)
</script>

<template>
  <header class="rail-header">
    <p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p>
    <h1 class="title" :class="size">{{ title }}</h1>
  </header>
</template>

<style scoped>
.rail-header {
  display: grid;
  gap: var(--space-3);
  min-width: 0;
}

.title {
  min-width: 0;
  /* Tight enough that a two-line title reads as one block rather than two rows. */
  line-height: 1.05;
  overflow-wrap: anywhere;
}

.title.lg {
  font-size: var(--display-4xl);
}

.title.md {
  font-size: var(--display-3xl);
}
</style>
