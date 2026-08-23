<script setup lang="ts">
/**
 * The data column of a signed-in screen — the screen's second scroll axis.
 *
 * Either one full-height panel, or a `split` of two that scroll independently, divided by a
 * rule rather than a gap. Splitting is what keeps two collections readable at once: with one
 * scrollbar the reader has to scroll past every day of usage to reach the models.
 *
 * `min-width: 0` and `min-height: 0` are load-bearing here. A grid track defaults to
 * `auto`, and without them a table's `min-width` would widen the whole region past the
 * viewport instead of scrolling inside its own panel.
 */
const props = withDefaults(
  defineProps<{
    /** Two stacked panels, each scrolling on its own. */
    split?: boolean
    /** The rows' proportion when split. Equal halves unless a page says otherwise. */
    ratio?: string
  }>(),
  { ratio: '1fr 1fr' },
)

/** Every track is `minmax(0, …)`: a bare `1fr` floors at its content, and the panel would
 *  then grow with its table instead of scrolling inside its half. */
const rows = computed(() =>
  props.ratio
    .split(' ')
    .filter(Boolean)
    .map((row) => `minmax(0, ${row})`)
    .join(' '),
)
</script>

<template>
  <div
    class="region"
    :class="{ split }"
    :style="split ? { gridTemplateRows: rows } : undefined"
  >
    <slot />
  </div>
</template>

<style scoped>
/*
 * A grid even when it holds one panel: `minmax(0, 1fr)` is what hands that panel a bounded
 * height to scroll inside. A flex column would let it size to its content instead, and the
 * table would grow the region rather than scrolling in place.
 */
.region {
  display: grid;
  grid-template-rows: minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  background: var(--paper);
}

@media (max-width: 900px) {
  /* One scroll axis below the breakpoint: the panels stack and the content region scrolls
     as a whole, so the rows must not be bounded any more. */
  .region,
  .region.split {
    display: block;
  }
}
</style>
