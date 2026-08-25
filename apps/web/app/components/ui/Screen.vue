<script setup lang="ts">
/**
 * One signed-in screen: the narrative rail and the data region, side by side.
 *
 * The two-column contract lives here rather than in the layout so that a page has a single
 * root and can own its own breakpoint behaviour. Both children scroll independently, and
 * this element never scrolls above the breakpoint — that is the whole point of it
 * (docs/web.md § Design system).
 *
 * `min-width: 0` on the tracks is load-bearing: a grid track defaults to `auto`, and one
 * table's own minimum width would otherwise widen the screen past the viewport rather than
 * scrolling inside its panel.
 *
 * `full` drops the rail column for a screen that has no margin to write in — the library,
 * whose navigation is its own breadcrumb and whose actions are in its context menu. Without
 * it the grid would keep the empty column and the data region would start 280px in.
 */
defineProps<{ full?: boolean }>()
</script>

<template>
  <div class="screen" :class="{ full }">
    <slot />
  </div>
</template>

<style scoped>
.screen {
  display: grid;
  grid-template-columns: var(--rail-width) minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  background: var(--paper);
}

.screen.full {
  grid-template-columns: minmax(0, 1fr);
}

/* One column below the breakpoint: the rail collapses above the data region, and the
   content region around this becomes the single scroll axis. */
@media (max-width: 900px) {
  .screen {
    display: block;
  }
}
</style>
