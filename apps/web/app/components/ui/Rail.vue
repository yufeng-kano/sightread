<script setup lang="ts">
/**
 * The left column of a signed-in screen: what this page is, and the few figures or the one
 * action that summarise it.
 *
 * It is a narrative margin, not a sidebar of controls — `UiPageHeader` at the top, then a
 * rule-separated stack of headline figures (Usage, Jobs), a live summary of what is in
 * effect (Settings), or the screen's primary action (API keys).
 *
 * It scrolls on its own: this is one of the screen's two scroll axes, and the reason a long
 * table never drags the page title off the top of the window (docs/web.md § Design system).
 */
</script>

<template>
  <aside class="rail">
    <slot />
  </aside>
</template>

<style scoped>
.rail {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  min-width: 0;
  min-height: 0;
  padding: var(--rail-pad-y) var(--rail-pad-x);
  background: var(--paper);
  border-right: 1px solid var(--line);
  overflow-y: auto;
  overscroll-behavior: contain;
}

/* Collapsed above the data region: the column rule becomes the rule under it. */
@media (max-width: 900px) {
  .rail {
    --rail-pad-y: var(--space-7);
    --rail-pad-x: var(--space-5);

    border-right: none;
    border-bottom: 1px solid var(--line);
    overflow: visible;
  }
}
</style>
