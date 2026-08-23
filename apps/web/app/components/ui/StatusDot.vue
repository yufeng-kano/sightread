<script setup lang="ts">
/**
 * Status indicator. The dot is never alone — it always ships with its label, because
 * color-only status fails both colorblind users and screen readers.
 *
 * Succeeded takes the accent: a finished job is the data this page is about. Running and
 * queued sit on their own quiet steps, outside the danger hue, so a job in flight never
 * reads as a problem. Failed colours the label as well as the dot — it is the one state a
 * reader has to find while scanning a column of rows.
 */
withDefaults(
  defineProps<{
    tone?: 'ok' | 'danger' | 'info' | 'neutral'
    label: string
  }>(),
  { tone: 'neutral' },
)
</script>

<template>
  <span class="status" :class="tone">
    <span class="dot" aria-hidden="true" />
    <span class="label">{{ label }}</span>
  </span>
</template>

<style scoped>
.status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.dot {
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--queued);
}

.label {
  color: var(--ink);
  white-space: nowrap;
}

.ok .dot {
  background: var(--accent);
}

.info .dot {
  background: var(--running);
}

.danger .dot {
  background: var(--danger);
}

.danger .label {
  color: var(--danger);
}
</style>
