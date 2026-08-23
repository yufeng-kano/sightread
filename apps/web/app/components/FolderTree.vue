<script setup lang="ts">
/**
 * The library's folder tree (docs/web.md § Files).
 *
 * Flattened to a list of rows with a depth each, which is the shape a sidebar tree actually
 * wants: one `v-for`, one tab order, and a collapsed folder simply contributes no rows. The
 * flattening itself is `lib/library.ts` — pure, and tested there.
 *
 * Home is a row like any other, because the root is a real place: you navigate to it, and
 * you drop things on it. It just has no folder row behind it, so its id is `null`.
 *
 * Two callers, one component: the rail on `/files`, where a row can be dragged and dropped
 * on, and the move dialog, where a row is only a destination to pick. That is `live`.
 */
import type { LibraryFolder } from '~/lib/api'
import { carriesFiles, claimDrag, setDropEffect } from '~/lib/dnd'
import { flattenTree, type FolderId } from '~/lib/library'

const props = withDefaults(
  defineProps<{
    folders: LibraryFolder[]
    /** The folder currently open, or being picked. `null` is Home. */
    selected: FolderId
    /** Which folders are open. A `Set` the parent owns, so the page can expand a path. */
    expanded: Set<number>
    /** The working tree: its rows can be dragged, and they accept drops. */
    live?: boolean
    /** Whether this row would accept the thing currently being dragged. */
    canDrop?: (target: FolderId) => boolean
    /** The row a drag is over right now — the one drawn as the target. */
    dropTarget?: FolderId
  }>(),
  { live: false, canDrop: () => false, dropTarget: undefined },
)

const emit = defineEmits<{
  select: [FolderId]
  toggle: [number]
  /** The row a drag is over. The page clears it; this only ever names one. */
  hover: [FolderId]
  dropOn: [FolderId, DragEvent]
  /** A folder row started being dragged — the page decides what that means. */
  dragFolder: [LibraryFolder, DragEvent]
}>()

const { t } = useI18n()

/** How long a drag rests on a closed folder before it springs open, as in Finder. */
const SPRING_MS = 600

const rows = computed(() => flattenTree(props.folders, props.expanded))

/** Depth as padding rather than nested lists: one flat tab order, one alignment rule. */
function indent(depth: number): string {
  return `${depth * 14}px`
}

function isTarget(id: FolderId): boolean {
  return props.live && props.dropTarget === id && props.canDrop(id)
}

// --- spring-loaded folders --------------------------------------------------

/**
 * Resting a drag on a closed folder opens it, so a file can be dropped somewhere the tree
 * was not showing when the drag started. Without it a drop into a nested folder means
 * cancelling the drag, opening the level, and starting again.
 */
let springTimer: ReturnType<typeof setTimeout> | undefined
let springingFor: number | undefined

function cancelSpring() {
  clearTimeout(springTimer)
  springTimer = undefined
  springingFor = undefined
}

function armSpring(id: FolderId) {
  if (id === springingFor) {
    return
  }
  cancelSpring()
  if (id === null || props.expanded.has(id)) {
    return
  }
  const row = rows.value.find((candidate) => candidate.folder.id === id)
  if (!row?.hasChildren) {
    return
  }
  springingFor = id
  springTimer = setTimeout(() => {
    emit('toggle', id)
    cancelSpring()
  }, SPRING_MS)
}

/**
 * A drag that walks off the tree stops arming anything, but the timer it already set would
 * still fire — opening a folder half a second after the drop landed somewhere else. The
 * page clears `dropTarget` the moment nothing claims the drag, so that is the signal.
 */
watch(
  () => props.dropTarget,
  (id) => {
    if (id !== springingFor) {
      cancelSpring()
    }
  },
)

onBeforeUnmount(cancelSpring)

// --- drag events ------------------------------------------------------------

function onDragOver(event: DragEvent, id: FolderId) {
  if (!props.live || !props.canDrop(id)) {
    // No preventDefault: the browser then shows the barred cursor, which is the truth.
    cancelSpring()
    return
  }
  // preventDefault is what makes this element a drop target at all; the claim tells the
  // handlers this event bubbles through that it already found its home (lib/dnd.ts).
  event.preventDefault()
  claimDrag(event, 'target')
  setDropEffect(event, carriesFiles(event.dataTransfer) ? 'copy' : 'move')
  if (props.dropTarget !== id) {
    emit('hover', id)
  }
  armSpring(id)
}

function onDrop(event: DragEvent, id: FolderId) {
  cancelSpring()
  emit('dropOn', id, event)
}
</script>

<template>
  <nav class="tree" :aria-label="t('files.tree')">
    <ul class="level">
      <li
        class="row"
        :class="{ active: selected === null, target: isTarget(null) }"
        @dragover="onDragOver($event, null)"
        @drop.prevent="onDrop($event, null)"
      >
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
        :class="{ active: selected === row.folder.id, target: isTarget(row.folder.id) }"
        :style="{ paddingLeft: indent(row.depth) }"
        @dragover="onDragOver($event, row.folder.id)"
        @drop.prevent="onDrop($event, row.folder.id)"
      >
        <!-- The caret is its own control: opening a folder and going into it are two
             different intentions, and a single click cannot mean both. -->
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

        <button
          type="button"
          class="label"
          :draggable="live ? 'true' : 'false'"
          :title="row.folder.name"
          @click="emit('select', row.folder.id)"
          @dragstart="emit('dragFolder', row.folder, $event)"
        >
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
  /* The one thing a drop target may borrow from the accent: a 1px ring, drawn inside so
     the row does not move when it lights up. */
  box-shadow: inset 0 0 0 1px transparent;
  transition:
    background var(--duration-fast) var(--ease),
    box-shadow var(--duration-fast) var(--ease);
}

.row:hover {
  background: var(--rail-active);
}

.row.active {
  background: var(--rail-active);
}

.row.target {
  background: var(--rail-active);
  box-shadow: inset 0 0 0 1px var(--accent);
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
