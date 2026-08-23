<script setup lang="ts">
/**
 * Inline message: an error that did not block the page, a save confirmation, the one-time
 * key reveal.
 *
 * Errors and warnings announce themselves (`role="alert"`) since they usually appear in
 * response to something the user just did; neutral and success tones are polite, so a
 * background refresh succeeding does not interrupt a screen reader mid-sentence.
 */
const props = withDefaults(defineProps<{ tone?: 'neutral' | 'ok' | 'warn' | 'error' }>(), {
  tone: 'neutral',
})

const assertive = computed(() => props.tone === 'error' || props.tone === 'warn')
</script>

<template>
  <div
    class="banner"
    :class="tone"
    :role="assertive ? 'alert' : 'status'"
    :aria-live="assertive ? 'assertive' : 'polite'"
  >
    <div class="banner-body">
      <slot />
    </div>
    <div v-if="$slots.actions" class="banner-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
/*
 * A rule and a word, not a tinted slab. This design carries meaning with hairlines, so a
 * banner is bounded the way every other block on the page is and takes its tone from the
 * text and the border rather than from a fill.
 */
.banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--hair);
  background: var(--paper);
  color: var(--muted);
  font-size: var(--text-sm);
  line-height: 1.6;
}

.banner-body {
  min-width: 0;
  /* Backend error text can be one long unbroken token (a URL, a JSON blob); without this it
     would push its container wider than the column. */
  overflow-wrap: anywhere;
}

.banner-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.error {
  border-color: var(--danger-edge);
  color: var(--danger);
}

/* The one-time key reveal. Ink on the rail surface: it has to be the loudest block on the
   page without borrowing the accent, which belongs to data. */
.warn {
  border-color: var(--edge);
  background: var(--rail);
  color: var(--ink);
}

.ok {
  color: var(--ink);
}
</style>
