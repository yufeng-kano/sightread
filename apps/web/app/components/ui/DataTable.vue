<!--
  The one place table markup lives.

  What a page's own `<table>` reliably gets wrong, all handled here:

  1. It scrolls in place. The table carries a `min-width` and never wraps a cell, so a
     narrow region gives it a horizontal scrollbar inside its panel instead of squeezing
     columns until the row rhythm breaks.
  2. Sticky header — the column names stay while the body scrolls inside its panel, on an
     inset rule rather than a border (a sticky cell's border scrolls away from the cell).
  3. Alignment — numeric columns are right-aligned with tabular numerals, header and cells
     together, declared once per column rather than re-specified per cell.
  4. Rhythm — the first column sits flush with the panel's gutter and every column after it
     takes the same left padding, so the eye has one left edge per column.

  Cells render through a per-column slot named `cell-<key>`, falling back to the column's
  `value()`.
-->
<script setup lang="ts" generic="Row">
import type { TableColumn } from '~/lib/table'

withDefaults(
  defineProps<{
    columns: TableColumn<Row>[]
    rows: Row[]
    rowKey: (row: Row) => string
    /** Accessible caption. Visually hidden — the panel header carries the visible title. */
    caption: string
    /** `tight` is the usage tables' denser row; `normal` is jobs and keys. */
    density?: 'normal' | 'tight'
  }>(),
  { density: 'normal' },
)

defineSlots<Record<string, (props: { row: Row }) => unknown>>()
</script>

<template>
  <table class="table" :class="density">
    <caption class="sr-only">{{ caption }}</caption>
    <thead>
      <tr>
        <th
          v-for="column in columns"
          :key="column.key"
          scope="col"
          :class="{ numeric: column.numeric, end: column.align === 'end' }"
          :style="column.width ? { width: column.width } : undefined"
        >
          <span v-if="!column.header && column.srHeader" class="sr-only">{{ column.srHeader }}</span>
          <template v-else>{{ column.header }}</template>
        </th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="row in rows" :key="rowKey(row)">
        <td
          v-for="column in columns"
          :key="column.key"
          :class="{ numeric: column.numeric, end: column.align === 'end' }"
        >
          <slot :name="`cell-${column.key}`" :row="row">{{ column.value?.(row) ?? '' }}</slot>
        </td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.table {
  width: 100%;
  /* The floor a row needs before its cells would have to wrap. Past it the panel body
     scrolls sideways — see the file comment. */
  min-width: var(--table-min);
  border-collapse: separate;
  border-spacing: 0;
  font-size: var(--text-sm);
  white-space: nowrap;
}

.table th {
  position: sticky;
  top: 0;
  z-index: 1;
  height: var(--control-height-sm);
  padding: 0;
  text-align: left;
  vertical-align: middle;
  font-size: var(--text-3xs);
  font-weight: var(--weight-semibold);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--faint);
  /* Opaque, not translucent: rows scrolling under a semi-transparent header smear into the
     labels. It inherits the panel's surface so a sunken panel's header matches it. */
  background: inherit;
  /* An inset shadow, not `border-bottom`: a sticky cell's border scrolls away independently
     of the cell itself, leaving the header floating unruled. */
  box-shadow: inset 0 -1px 0 var(--line-strong);
}

.table td {
  padding: var(--cell-y) 0;
  border-bottom: 1px solid var(--line-soft);
  vertical-align: middle;
  color: var(--ink);
}

.table.tight td {
  padding: var(--cell-y-tight) 0;
}

/* Every column after the first is set in from the one before it; the first sits on the
   panel's own gutter so the table has the same left edge as the heading above it. */
.table th + th,
.table td + td {
  padding-left: var(--cell-x);
}

/* The panel's bottom padding is the space under the table — a rule there would read as a
   line under the panel rather than between two rows. */
.table tbody tr:last-child td {
  border-bottom: none;
}

/*
 * Column alignment, applied to the header and its cells as one. Written as `.table th` /
 * `.table td` rather than a bare `.numeric`, because `.table th`'s `text-align: left` sits
 * at a higher specificity and would otherwise win — leaving every numeric header
 * left-aligned over right-aligned figures.
 */
.table th.numeric,
.table td.numeric {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* A control column: the header sits over the control rather than at the far edge. */
.table th.end,
.table td.end {
  text-align: right;
}

/*
 * A link or any block a cell holds must be told to ellipsize. Left inline it produces a
 * second line box inside the cell, and rows then differ in height by a pixel or two down
 * the whole table.
 */
.table td :deep(.cell-block) {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
