<script setup lang="ts">
/**
 * Where should this go? — the keyboard's route to a move (docs/web.md § Files).
 *
 * Dragging a row onto a folder is the fast way and the one most people will use, but a drag
 * is invisible to a keyboard and to assistive tech, so every move is also available here.
 * It is the same tree, in a dialog, with a destination to pick.
 *
 * A folder cannot be moved into its own subtree; `forbidden` carries that set so the choice
 * is refused here rather than by the server after the fact.
 */
import type { LibraryFolder } from '~/lib/api'
import { folderPath, type FolderId } from '~/lib/library'

const props = withDefaults(
  defineProps<{
    folders: LibraryFolder[]
    /** What is being moved — the dialog's title says so. */
    name: string
    /** Where it is now: preselected, and not a move if it is still chosen. */
    current: FolderId
    /** Destinations this item may not enter. */
    forbidden?: Set<number>
    pending?: boolean
    /** Why the last attempt failed — inside the dialog, which is where it happened. */
    error?: string | null
  }>(),
  { forbidden: () => new Set<number>(), error: null },
)

const emit = defineEmits<{ move: [FolderId]; cancel: [] }>()

const { t } = useI18n()

const destination = ref<FolderId>(props.current)
/** Opened down to where the item lives, so the dialog starts on the part of the tree that
 *  is about it rather than on a collapsed root. */
const expanded = ref(new Set(folderPath(props.folders, props.current).map((row) => row.id)))

function toggle(id: number) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
}

const canMove = computed(
  () =>
    destination.value !== props.current &&
    !(destination.value !== null && props.forbidden.has(destination.value)),
)
</script>

<template>
  <UiModal :title="t('files.moveTitle')" :busy="pending" @close="emit('cancel')">
    <template #title>
      <h2 class="title">{{ t('files.moveTitle') }}</h2>
      <p class="subject">{{ name }}</p>
    </template>

    <UiBanner v-if="error" class="failure" tone="error">{{ error }}</UiBanner>

    <div class="picker">
      <FolderTree
        :folders="folders"
        :selected="destination"
        :expanded="expanded"
        @select="destination = $event"
        @toggle="toggle"
      />
    </div>

    <template #footer>
      <UiButton variant="ghost" :disabled="pending" @click="emit('cancel')">
        {{ t('common.cancel') }}
      </UiButton>
      <UiButton
        variant="primary"
        :disabled="!canMove"
        :loading="pending"
        @click="emit('move', destination)"
      >
        {{ t('files.move') }}
      </UiButton>
    </template>
  </UiModal>
</template>

<style scoped>
.title {
  font-size: var(--display-sm);
  letter-spacing: normal;
}

/* The thing being moved, under the verb — a fact, not a sentence explaining the dialog. */
.subject {
  margin-top: var(--space-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--faint);
  font-size: var(--text-xs);
}

.failure {
  margin-bottom: var(--space-4);
}

/* Bounded and scrolling: a deep tree must not push the dialog's buttons off the screen. */
.picker {
  max-height: 320px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: var(--space-2);
  border: 1px solid var(--line-strong);
  background: var(--rail);
}
</style>
