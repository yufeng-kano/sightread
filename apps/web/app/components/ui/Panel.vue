<script setup lang="ts">
/**
 * A region of the data column: a non-scrolling header over a body that scrolls on its own.
 *
 * This is what replaced the card. The design carries structure with hairlines and headings,
 * so a panel has no border, no radius and no shadow — what separates two stacked panels is
 * the 1px rule between them and the lower one's `sunken` surface (docs/web.md § Design
 * system).
 *
 * `min-width: 0` and `min-height: 0` are load-bearing on both the panel and its body: a
 * flex child defaults to `auto`, and one wide table would then push the whole content
 * region past the viewport instead of scrolling inside here.
 *
 * Two shapes. With a `title` it is a headed panel whose body holds a table or a list. With
 * `section` it is one full-height reading column — no header, generous padding — for the
 * screens whose data region is prose and controls rather than rows.
 */
defineProps<{
  title?: string
  /** The lower half of a split region: the surface that says "second panel", not "card". */
  sunken?: boolean
  /** Headerless, with a reading column's own padding. */
  section?: boolean
  /** The panel is the first thing in a full-height region, so its header sits lower. */
  lead?: boolean
  /** The lower panel of a split region: the 1px rule that divides the two. */
  divided?: boolean
  /** The body manages its own padding — an empty state, a skeleton, a nested grid. */
  flush?: boolean
}>()

defineSlots<{
  default: () => unknown
  /** Right of the heading: this dataset's own metadata ("34 days recorded") or one small button. */
  meta?: () => unknown
}>()
</script>

<template>
  <section class="panel" :class="{ sunken, divided }">
    <header v-if="title || $slots.meta" class="panel-head" :class="{ lead }">
      <h2 v-if="title" class="panel-title">{{ title }}</h2>
      <div v-if="$slots.meta" class="panel-meta">
        <slot name="meta" />
      </div>
    </header>

    <div class="panel-body" :class="{ section, flush }">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--paper);
}

.panel.sunken {
  background: var(--paper-sunken);
}

/* What separates two stacked panels — a rule, not a gap and not a card edge. */
.panel.divided {
  border-top: 1px solid var(--line);
}

/* Baseline alignment, not centre: the serif heading and the uppercase meta beside it have
   very different cap heights, and centring them leaves the meta floating. */
.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
  flex-shrink: 0;
  padding: var(--space-6) var(--panel-x) var(--space-3);
}

.panel-head.lead {
  padding-top: var(--space-10);
  padding-bottom: var(--space-4);
}

.panel-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--display-sm);
  letter-spacing: normal;
}

/* Uppercase and quiet: a fact about this panel's dataset, never a subtitle explaining it. */
.panel-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
  font-size: var(--text-2xs);
  letter-spacing: var(--tracking-meta);
  text-transform: uppercase;
  color: var(--faint);
  white-space: nowrap;
}

/* The scroll axis this panel owns. */
.panel-body {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding: 0 var(--panel-x) var(--space-6);
}

.panel-body.section {
  padding: var(--space-10) var(--panel-x) var(--space-12);
}

.panel-body.flush {
  padding: 0;
}

/*
 * Below the breakpoint the whole content region becomes one scroll axis, so a panel's body
 * is no longer a bounded box: it takes its natural height and `overflow: auto` then only
 * ever produces the horizontal scrollbar a wide table needs.
 */
@media (max-width: 900px) {
  .panel {
    --panel-x: var(--space-5);
  }

  .panel-head {
    padding-top: var(--space-7);
  }

  .panel-body.section {
    padding: var(--space-7) var(--panel-x) var(--space-10);
  }
}
</style>
