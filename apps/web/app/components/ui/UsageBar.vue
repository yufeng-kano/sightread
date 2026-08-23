<script setup lang="ts">
/**
 * One row's share of the largest value in its column, as a bar.
 *
 * Unlike a quota meter the fill never escalates through amber to red: a bigger share of a
 * month's spend is not a worse state, it is just a bigger number. The figure it ranks is
 * always printed beside it, so the bar is emphasis and never the only signal — which is
 * also why it carries an accessible name rather than a visible label.
 *
 * A meter is data, so it is one of the few things allowed to be the accent colour.
 */
const props = defineProps<{
  /** 0..1, this row against the largest row in the same table. */
  share: number
  /** Accessible name — the row this bar belongs to. */
  label: string
}>()

const percent = computed(() => Math.round(Math.max(0, Math.min(1, props.share)) * 100))
</script>

<template>
  <div
    class="track"
    role="meter"
    :aria-valuenow="percent"
    aria-valuemin="0"
    aria-valuemax="100"
    :aria-label="label"
  >
    <div class="fill" :style="{ width: `${percent}%` }" />
  </div>
</template>

<style scoped>
/* 3px and square. A rounded cap on a 3px bar spends a third of the smallest value on the
   curve, which is what made short rows unreadable. */
.track {
  height: 3px;
  background: var(--hair);
  overflow: hidden;
}

.fill {
  height: 100%;
  min-width: 1px;
  background: var(--accent);
  transition: width var(--duration-slow) var(--ease);
}
</style>
