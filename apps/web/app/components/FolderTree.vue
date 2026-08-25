<script setup lang="ts">
/**
 * The move dialog's folder picker (docs/web.md § Files).
 *
 * Flattened to a list of rows with a depth each, which is the shape a tree actually wants:
 * one `v-for`, one tab order, and a collapsed folder simply contributes no rows. The
 * flattening itself is `lib/library.ts` — pure, and tested there.
 *
 * Home is a row like any other, because the root is a real destination. It just has no folder
 * row behind it, so its id is `null`.
 *
 * A row here is only a destination to pick: the library screen navigates by its breadcrumb
 * and its folder rows, and moves by drag or by this dialog, so nothing in this tree drags,
 * accepts a drop, or has a menu.
 */
import type { LibraryFolder } from '~/lib/api'
import { flattenTree, type FolderId } from '~/lib/library'

const props = defineProps<{
  folders: LibraryFolder[]
  /** The folder being picked. `null` is Home. */
  selected: FolderId
  /** Which folders are open. A `Set` the parent owns, so it can expand a path. */
  expanded: Set<number>
}>()

const emit = defineEmits<{
  select: [FolderId]
  toggle: [number]
}>()

const { t } = useI18n()

const rows = computed(() => flattenTree(props.folders, props.expanded))

/** Depth as padding rather than nested lists: one flat tab order, one alignment rule. */
function indent(depth: number): string {
  return `${depth * 14}px`
}
</script>

<template>
  <nav class="tree" :aria-label="t('files.tree')">
    <ul class="level">
      <li class="row" :class="{ active: selected === null }">
        <span class="caret-space" />
        <button type="button" class="label" @click="emit('select', null)">
          <UiIcon :name="selected === null ? 'folder-open' : 'folder'" />
          <span class="name">{{ t('files.root') }}</span>
        </button>
      </li>

      <li
        v-for="row in rows"
        :key="row.folder.id"
        class="row"
        :class="{ active: selected === row.folder.id }"
        :style="{ paddingLeft: indent(row.depth) }"
      >
        <!-- The caret is its own control: opening a folder and picking it are two different
             intentions, and a single click cannot mean both. -->
        <button
          v-if="row.hasChildren"
          type="button"
          class="caret"
          :class="{ open: expanded.has(row.folder.id) }"
          :aria-label="
            expanded.has(row.folder.id)
              ? t('files.collapse', { name: row.folder.name })
              : t('files.expand', { name: row.folder.name })
          "
          :aria-expanded="expanded.has(row.folder.id) ? 'true' : 'false'"
          @click="emit('toggle', row.folder.id)"
        >
          <UiIcon name="chevron-right" />
        </button>
        <span v-else class="caret-space" />

        <button type="button" class="label" :title="row.folder.name" @click="emit('select', row.folder.id)">
          <UiIcon
            :name="
              selected === row.folder.id || expanded.has(row.folder.id) ? 'folder-open' : 'folder'
            "
          />
          <span class="name">{{ row.folder.name }}</span>
        </button>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.tree {
  min-width: 0;
}

.level {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.row {
  display: flex;
  align-items: center;
  min-width: 0;
  border-radius: var(--radius);
  transition: background var(--duration-fast) var(--ease);
}

.row:hover {
  background: var(--rail-active);
}

.row.active {
  background: var(--rail-active);
}

.caret,
.caret-space {
  width: 18px;
  flex-shrink: 0;
}

.caret {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: var(--control-height-sm);
  padding: 0;
  border: none;
  background: transparent;
  color: var(--faint);
  cursor: pointer;
}

.caret :deep(svg) {
  width: 12px;
  height: 12px;
  transition: transform var(--duration-fast) var(--ease);
}

.caret.open :deep(svg) {
  transform: rotate(90deg);
}

.label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
  height: var(--control-height-sm);
  padding: 0 var(--space-2) 0 0;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease);
}

.row:hover .label,
.row.active .label {
  color: var(--ink);
}

.row.active .label {
  font-weight: var(--weight-semibold);
}

.label :deep(svg) {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: var(--faint);
}

.name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
