<script setup lang="ts">
/**
 * The product mark and name, linking home — the same in both shells.
 *
 * The mark is the `scan-text` glyph reversed out of an accent square: the brand is the one
 * place besides data where the accent appears, and a monogram at this size was reading as a
 * stray pair of letters rather than as a mark.
 *
 * `size` is the sign-in page's larger cut. Everything else takes the sidebar's. Without
 * `to` — the sign-in page, where there is nowhere to go — it is a plain block rather than a
 * link to the page you are already on.
 */
withDefaults(defineProps<{ to?: string; size?: 'md' | 'lg' }>(), {
  size: 'md',
  to: undefined,
})

const { t } = useI18n()
</script>

<template>
  <NuxtLink v-if="to" class="brand" :class="size" :to="to">
    <span class="brand-mark" aria-hidden="true">
      <UiIcon name="scan-text" />
    </span>
    <span class="brand-name">{{ t('app.name') }}</span>
  </NuxtLink>
  <div v-else class="brand" :class="size">
    <span class="brand-mark" aria-hidden="true">
      <UiIcon name="scan-text" />
    </span>
    <span class="brand-name">{{ t('app.name') }}</span>
  </div>
</template>

<style scoped>
.brand {
  display: flex;
  align-items: center;
  min-width: 0;
  flex-shrink: 0;
  font-family: var(--font-display);
  font-weight: var(--weight-semibold);
}

.brand.md {
  gap: 10px;
  font-size: var(--display-2xs);
}

.brand.lg {
  gap: var(--space-3);
  font-size: var(--display-xs);
}

.brand-mark {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  background: var(--accent);
  color: var(--accent-fg);
}

.brand.md .brand-mark {
  width: 26px;
  height: 26px;
  border-radius: var(--radius);
}

.brand.lg .brand-mark {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-mark);
}

.brand.md .brand-mark :deep(svg) {
  width: 16px;
  height: 16px;
}

.brand.lg .brand-mark :deep(svg) {
  width: 22px;
  height: 22px;
}

/* The wordmark never wraps — it is a name, and a two-line one reads as two words. */
.brand-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
