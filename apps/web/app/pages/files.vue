<script setup lang="ts">
/**
 * The file library: folders on the left, what is in the open one on the right
 * (docs/web.md § Files).
 *
 * Three things make this screen work, and each is a decision rather than a detail:
 *
 *  - **One read.** `GET /api/library` returns the whole tree, so opening a folder is a
 *    filter over data already in memory. There is no spinner between a click and a list.
 *  - **Uploading is a queue.** The server caps running jobs per user, so a five-file drop
 *    earns 429s if it fires at once. Files go up one at a time and a refusal is treated as
 *    back-pressure: the file waits and tries again. Every dropped file is a row from the
 *    moment it is dropped, well before the server knows about it.
 *  - **Polling, not streaming.** While anything is queued or running, the same one read
 *    repeats every couple of seconds and refreshes every row's status and progress at once.
 *
 * Nothing on this screen explains itself in prose: the drop target, the empty folder and
 * the row controls say what they are.
 */
import {
  ApiRequestError,
  createFolder,
  deleteDocument,
  deleteFolder,
  getDocumentResult,
  getLibrary,
  updateDocument,
  updateFolder,
  uploadDocument,
  type JobResult,
  type JobStatus,
  type LibraryDocument,
  type LibraryFolder,
} from '~/lib/api'
import {
  carriesFiles,
  claimDrag,
  dragClaim,
  droppedFiles,
  setDropEffect,
} from '~/lib/dnd'
import { formatBytes, formatShortDateTime } from '~/lib/format'
import {
  canMoveFolder,
  childFolders,
  documentsIn,
  folderPath,
  isPending,
  parseProgress,
  subtreeIds,
  type FolderId,
} from '~/lib/library'
import type { TableColumn } from '~/lib/table'

definePageMeta({ middleware: 'authed' })

/** How often the list re-reads itself while a parse is in flight. */
const POLL_MS = 2000
/** How long a file refused by the per-user job cap waits before trying again. */
const BACKOFF_MS = 3000

const { t, locale } = useI18n()
const auth = useAuth()
const { resolve } = useApiError()
const { data, pending, errorMessage, refresh } = useAuthedData(() => getLibrary())

const folders = computed<LibraryFolder[]>(() => data.value?.folders ?? [])
const documents = computed<LibraryDocument[]>(() => data.value?.documents ?? [])

// --- where we are ----------------------------------------------------------

const currentFolder = ref<FolderId>(null)
const expanded = ref(new Set<number>())
const crumbs = computed(() => folderPath(folders.value, currentFolder.value))

function openFolder(id: FolderId) {
  currentFolder.value = id
  // Opening a folder opens the path to it: the rail must be able to show where you are.
  for (const folder of folderPath(folders.value, id)) {
    expanded.value.add(folder.id)
  }
}

function toggleFolder(id: number) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
}

/** A folder deleted in another tab would otherwise leave this screen looking at nothing. */
watch(folders, (list) => {
  if (currentFolder.value !== null && !list.some((row) => row.id === currentFolder.value)) {
    currentFolder.value = null
  }
})

// --- rows ------------------------------------------------------------------

/** A file being uploaded exists here before the server has heard of it. */
interface PendingUpload {
  localId: number
  name: string
  size: number
  folderId: FolderId
  file: File
  /** `waiting` covers both "not started" and "refused by the job cap, trying again". */
  state: 'waiting' | 'uploading'
}

type Row =
  | { kind: 'folder'; key: string; folder: LibraryFolder }
  | { kind: 'file'; key: string; document: LibraryDocument }
  | { kind: 'upload'; key: string; upload: PendingUpload }

const queue = ref<PendingUpload[]>([])

/** Folders first, then files, then what is still going up — a file manager's order. */
const rows = computed<Row[]>(() => [
  ...childFolders(folders.value, currentFolder.value).map<Row>((folder) => ({
    kind: 'folder',
    key: `folder-${folder.id}`,
    folder,
  })),
  ...documentsIn(documents.value, currentFolder.value).map<Row>((document) => ({
    kind: 'file',
    key: `file-${document.id}`,
    document,
  })),
  ...queue.value
    .filter((upload) => upload.folderId === currentFolder.value)
    .map<Row>((upload) => ({ kind: 'upload', key: `upload-${upload.localId}`, upload })),
])

const columns = computed<TableColumn<Row>[]>(() => [
  { key: 'name', header: t('files.columnName') },
  { key: 'status', header: t('files.columnStatus'), width: '150px' },
  { key: 'pages', header: t('files.columnPages'), numeric: true, width: '84px' },
  { key: 'size', header: t('files.columnSize'), numeric: true, width: '96px' },
  { key: 'added', header: t('files.columnAdded'), numeric: true, width: '148px' },
  { key: 'actions', header: '', srHeader: t('files.columnActions'), align: 'end', width: '108px' },
])

const STATUS_TONE: Record<JobStatus, 'neutral' | 'info' | 'ok' | 'danger'> = {
  queued: 'neutral',
  running: 'info',
  succeeded: 'ok',
  failed: 'danger',
}

// --- uploading -------------------------------------------------------------

const fileInput = ref<HTMLInputElement | null>(null)
const mutationError = ref<string | null>(null)
const limits = computed(() => auth.me.value?.limits ?? null)
const accept = computed(() => limits.value?.accepted_media_types.join(',') ?? '')

let nextLocalId = 1
let draining = false
/** Set on unmount: a queue retrying against the job cap must not outlive the screen. */
let left = false

function pickFiles() {
  fileInput.value?.click()
}

function onPicked(event: Event) {
  const input = event.target as HTMLInputElement
  addToQueue([...(input.files ?? [])], currentFolder.value)
  // Cleared so picking the same file twice in a row still fires `change`.
  input.value = ''
}

/**
 * A file the server would refuse is refused here, from the server's own numbers
 * (`GET /api/me` § limits) — an upload that cannot succeed should not spend the upload.
 */
function rejected(file: File): string | null {
  const max = limits.value?.upload_max_bytes
  if (max && file.size > max) {
    return t('files.tooLarge', { name: file.name, limit: formatBytes(max, locale.value) })
  }
  const accepted = limits.value?.accepted_media_types ?? []
  // An empty type is what a browser sends for an extension it does not know; the server
  // falls back to the extension too, so it is not this side's place to refuse it.
  if (file.type && accepted.length && !accepted.includes(file.type)) {
    return t('files.unsupported', { name: file.name })
  }
  return null
}

function addToQueue(files: File[], folderId: FolderId) {
  const accepted: PendingUpload[] = []
  for (const file of files) {
    const refusal = rejected(file)
    if (refusal) {
      mutationError.value = refusal
      continue
    }
    accepted.push({
      localId: nextLocalId++,
      name: file.name,
      size: file.size,
      folderId,
      file,
      state: 'waiting',
    })
  }
  if (!accepted.length) {
    return
  }
  // One file on its own is "upload this and read it", so its result opens itself when it
  // lands. A batch does not: five dialogs racing each other is not a feature.
  autoPreviewFor = accepted.length === 1 && !queue.value.length ? -1 : null
  queue.value.push(...accepted)
  void drain()
}

/**
 * Upload the queue, one file at a time.
 *
 * Sequential because the per-user cap on running jobs is real (docs/jobs.md § Concurrency):
 * firing five uploads in parallel would just collect 429s. A 429 here is back-pressure, not
 * a failure — the file stays at the head of the queue and tries again once a job finishes.
 */
async function drain() {
  if (draining) {
    return
  }
  draining = true
  try {
    while (queue.value.length && !left) {
      const item = queue.value[0]!
      item.state = 'uploading'
      try {
        const created = await uploadDocument(item.file, item.folderId)
        queue.value.shift()
        if (autoPreviewFor === -1) {
          autoPreviewFor = created.id
        }
        await refresh()
      } catch (error) {
        if (error instanceof ApiRequestError && error.type === 'rate_limit') {
          item.state = 'waiting'
          await new Promise((done) => setTimeout(done, BACKOFF_MS))
          continue
        }
        queue.value.shift()
        mutationError.value = await resolve(error)
      }
    }
  } finally {
    draining = false
  }
}

// --- live progress ---------------------------------------------------------

const anyPending = computed(() => documents.value.some(isPending))
let poller: ReturnType<typeof setInterval> | undefined

function stopPolling() {
  clearInterval(poller)
  poller = undefined
}

watch(anyPending, (running) => {
  if (!running) {
    stopPolling()
    return
  }
  poller ??= setInterval(() => {
    // Skipped while a read is already in flight, so a slow answer cannot pile requests up.
    if (!pending.value) {
      void refresh()
    }
  }, POLL_MS)
})

onBeforeUnmount(() => {
  left = true
  stopPolling()
})

// --- the result viewer -----------------------------------------------------

const openDocument = ref<LibraryDocument | null>(null)
const results = reactive(new Map<number, JobResult>())
const resultErrors = reactive(new Map<number, string>())
/** Ids with a result request in flight — a set, since the viewer can be reopened on
 *  another file while the first request is still running. */
const loadingResults = reactive(new Set<number>())
/** The single upload whose result should open itself; `-1` while it has no id yet. */
let autoPreviewFor: number | null = null

async function showResult(document: LibraryDocument) {
  openDocument.value = document
  // Reading something by hand settles what the screen is for; a queued auto-preview must
  // not take it away when it finishes.
  autoPreviewFor = null
  if (results.has(document.id) || loadingResults.has(document.id)) {
    return
  }
  loadingResults.add(document.id)
  resultErrors.delete(document.id)
  try {
    results.set(document.id, await getDocumentResult(document.id))
  } catch (error) {
    resultErrors.set(document.id, await resolve(error))
  } finally {
    loadingResults.delete(document.id)
  }
}

/** The upload that just finished parsing opens itself — unless the reader is already
 *  reading something, in which case taking the screen away would be rude. */
watch(documents, (list) => {
  if (autoPreviewFor === null || autoPreviewFor < 0 || openDocument.value) {
    return
  }
  const target = list.find((row) => row.id === autoPreviewFor)
  if (!target || isPending(target)) {
    return
  }
  if (target.status === 'succeeded') {
    void showResult(target)
  } else {
    autoPreviewFor = null
  }
})

// --- create, rename, move, delete ------------------------------------------

/** What a dialog is currently about. One ref per dialog, never a shared "mode". */
const newFolderName = ref('')
const showNewFolder = ref(false)
const renaming = ref<Row | null>(null)
const renameValue = ref('')
const moving = ref<Row | null>(null)
const deleting = ref<Row | null>(null)
const busy = ref(false)

function rowName(row: Row): string {
  if (row.kind === 'folder') return row.folder.name
  if (row.kind === 'file') return row.document.name
  return row.upload.name
}

function openNewFolder() {
  newFolderName.value = t('files.newFolderName')
  mutationError.value = null
  showNewFolder.value = true
}

/** Every mutation is the same three steps: run it, re-read, report what went wrong. */
async function commit(action: () => Promise<unknown>): Promise<boolean> {
  if (busy.value) {
    return false
  }
  busy.value = true
  mutationError.value = null
  try {
    await action()
    await refresh()
    return true
  } catch (error) {
    mutationError.value = await resolve(error)
    return false
  } finally {
    busy.value = false
  }
}

async function submitNewFolder() {
  const name = newFolderName.value.trim()
  if (!name) {
    return
  }
  let created: LibraryFolder | null = null
  const ok = await commit(async () => {
    created = await createFolder({ name, parent_id: currentFolder.value })
  })
  if (ok) {
    showNewFolder.value = false
    if (created) {
      expanded.value.add((created as LibraryFolder).id)
    }
  }
}

function openRename(row: Row) {
  renaming.value = row
  renameValue.value = rowName(row)
  mutationError.value = null
}

async function submitRename() {
  const row = renaming.value
  const name = renameValue.value.trim()
  if (!row || !name || name === rowName(row)) {
    renaming.value = null
    return
  }
  const ok = await commit(() => {
    if (row.kind === 'folder') {
      return updateFolder(row.folder.id, { name })
    }
    return row.kind === 'file' ? updateDocument(row.document.id, { name }) : Promise.resolve()
  })
  if (ok) {
    renaming.value = null
  }
}

/** Where the thing being moved lives now — the destination the dialog opens on. */
const movingFrom = computed<FolderId>(() => {
  const row = moving.value
  if (row?.kind === 'folder') {
    return row.folder.parent_id
  }
  return row?.kind === 'file' ? row.document.folder_id : null
})

/** The subtree a folder may not be moved into — its own. */
const forbiddenTargets = computed(() =>
  moving.value?.kind === 'folder'
    ? subtreeIds(folders.value, moving.value.folder.id)
    : new Set<number>(),
)

async function submitMove(destination: FolderId) {
  const row = moving.value
  if (!row) {
    return
  }
  const ok = await moveRow(row, destination)
  if (ok) {
    moving.value = null
  }
}

function moveRow(row: Row, destination: FolderId): Promise<boolean> {
  if (row.kind === 'folder') {
    return commit(() => updateFolder(row.folder.id, { parent_id: destination }))
  }
  if (row.kind === 'file') {
    return commit(() => updateDocument(row.document.id, { folder_id: destination }))
  }
  return Promise.resolve(false)
}

async function confirmDelete() {
  const row = deleting.value
  if (!row) {
    return
  }
  const ok = await commit(() => {
    if (row.kind === 'folder') {
      return deleteFolder(row.folder.id)
    }
    return row.kind === 'file' ? deleteDocument(row.document.id) : Promise.resolve()
  })
  if (ok) {
    if (row.kind === 'file' && openDocument.value?.id === row.document.id) {
      openDocument.value = null
    }
    deleting.value = null
  }
}

// --- dragging --------------------------------------------------------------

/**
 * Drag state, and the one rule that keeps it honest: `dragover` decides everything.
 *
 * It fires continuously on exactly one innermost element and bubbles to the window, so the
 * handler nearest the pointer claims the event and the window clears whatever went
 * unclaimed (lib/dnd.ts). `dragleave` is deliberately not used anywhere here — it fires for
 * every child element a pointer crosses, so a row made of an icon and a name unlights
 * itself halfway across, and browsers disagree about what `relatedTarget` holds on a drag.
 */

/** What is being dragged inside the page. A drag from the desktop is `fileDrag`. */
const dragItem = ref<Row | null>(null)
/** The folder a drag is over — the one drawn as the target. */
const dropTarget = ref<FolderId | undefined>(undefined)
/** A drag carrying files is somewhere over the window. */
const fileDrag = ref(false)
/** …and it is over the list, so the overlay names where a drop would land. */
const fileOverList = ref(false)

/** How long the page waits for the next drag event before assuming the drag is gone. */
const DRAG_IDLE_MS = 700
let dragWatchdog: ReturnType<typeof setTimeout> | undefined

/**
 * How long an unlit frame has to last before the target really goes out.
 *
 * A pointer crossing the 1px rule between two tree rows lands one `dragover` on the list
 * that holds them, and the browser dispatches the odd frame on a parent during a fast move.
 * Both are single events between two that claim the same row, and unlighting on them makes
 * the target blink all the way down a tree. So the clear is scheduled, and the next claim
 * cancels it.
 */
const TARGET_CLEAR_MS = 80
let clearTargetTimer: ReturnType<typeof setTimeout> | undefined

/**
 * Whether this row can land in this folder. Takes the row rather than reading `dragItem`,
 * because the drop handler has to ask *after* it has let go of the drag — asking about
 * state it just cleared is how a drop silently does nothing.
 */
function canMoveInto(item: Row | null, target: FolderId): boolean {
  if (!item) {
    return false
  }
  if (item.kind === 'folder') {
    return canMoveFolder(folders.value, item.folder, target)
  }
  return item.kind === 'file' && item.document.folder_id !== target
}

/** What the tree asks while a drag is in the air: is this row a live target right now? */
function canDropOn(target: FolderId): boolean {
  return fileDrag.value || canMoveInto(dragItem.value, target)
}

function startDrag(event: DragEvent, row: Row) {
  dragItem.value = row
  if (event.dataTransfer) {
    // Firefox starts no drag at all unless the payload is set, even when the data itself
    // goes unused — the page reads `dragItem`, not the transfer.
    event.dataTransfer.setData('text/plain', rowName(row))
    event.dataTransfer.effectAllowed = 'move'
  }
}

/** A folder dragged out of the rail is the same move as one dragged out of the list. */
function startFolderDrag(folder: LibraryFolder, event: DragEvent) {
  startDrag(event, { kind: 'folder', key: `folder-${folder.id}`, folder })
}

function holdTarget() {
  clearTimeout(clearTargetTimer)
  clearTargetTimer = undefined
}

function releaseTarget() {
  if (clearTargetTimer !== undefined || dropTarget.value === undefined) {
    return
  }
  clearTargetTimer = setTimeout(() => {
    dropTarget.value = undefined
    clearTargetTimer = undefined
  }, TARGET_CLEAR_MS)
}

/** Everything a finished or abandoned drag leaves behind. */
function endDrag() {
  clearTimeout(dragWatchdog)
  dragWatchdog = undefined
  holdTarget()
  dragItem.value = null
  dropTarget.value = undefined
  fileDrag.value = false
  fileOverList.value = false
}

/**
 * A drag from the desktop ends with no event this page can rely on — it can be carried out
 * of the window, and `dragend` fires on the source, which is another application. So the
 * flags a file drag sets expire on their own if drag events stop arriving. `dragItem` is
 * not touched: an internal drag does get a `dragend`, and dropping it after a trip outside
 * the window has to still work.
 */
function dragGoneIdle() {
  fileDrag.value = false
  fileOverList.value = false
  holdTarget()
  dropTarget.value = undefined
}

function onWindowDragOver(event: DragEvent) {
  const claim = dragClaim(event)
  const files = carriesFiles(event.dataTransfer)

  fileDrag.value = files
  fileOverList.value = files && claim === 'list'
  if (claim === 'target') {
    holdTarget()
  } else {
    releaseTarget()
  }
  if (claim === undefined && files) {
    // Nothing on this page wants it. Swallowing it anyway is the point: a file dropped on
    // a page that ignores it becomes a navigation, and the browser would replace the app
    // with the PDF — in the middle of an upload, with a queue still in memory.
    event.preventDefault()
    setDropEffect(event, 'none')
  }

  clearTimeout(dragWatchdog)
  dragWatchdog = setTimeout(dragGoneIdle, DRAG_IDLE_MS)
}

function onWindowDrop(event: DragEvent) {
  // Preventing the default on `dragover` alone is not enough; the drop itself navigates.
  if (!event.defaultPrevented && carriesFiles(event.dataTransfer)) {
    event.preventDefault()
  }
  endDrag()
}

onMounted(() => {
  window.addEventListener('dragover', onWindowDragOver)
  window.addEventListener('drop', onWindowDrop)
  // The row that started the drag can be replaced by a poll while the drag is in the air,
  // and its own `dragend` then never arrives. The window's always does.
  window.addEventListener('dragend', endDrag)
})

onBeforeUnmount(() => {
  window.removeEventListener('dragover', onWindowDragOver)
  window.removeEventListener('drop', onWindowDrop)
  window.removeEventListener('dragend', endDrag)
  clearTimeout(dragWatchdog)
  clearTimeout(clearTargetTimer)
})

/** A drop onto a folder: either the desktop's files land in it, or a row moves into it. */
function dropOn(target: FolderId, event: DragEvent) {
  const files = droppedFiles(event)
  const item = dragItem.value
  endDrag()
  if (files.length) {
    addToQueue(files, target)
    return
  }
  if (canMoveInto(item, target)) {
    void moveRow(item!, target)
  }
}

/**
 * A folder row in the list, and a breadcrumb above it, take rows of this page only. Files
 * dropped on the list go to the folder that is open — that is what the overlay says, and
 * it covers the rows while it is up.
 */
function onTargetDragOver(event: DragEvent, target: FolderId) {
  if (carriesFiles(event.dataTransfer) || !canMoveInto(dragItem.value, target)) {
    return
  }
  event.preventDefault()
  claimDrag(event, 'target')
  setDropEffect(event, 'move')
  holdTarget()
  dropTarget.value = target
}

/** The list itself: where files from the desktop land. */
function onListDragOver(event: DragEvent) {
  if (!carriesFiles(event.dataTransfer)) {
    return
  }
  event.preventDefault()
  claimDrag(event, 'list')
  setDropEffect(event, 'copy')
}

function onListDrop(event: DragEvent) {
  const files = droppedFiles(event)
  endDrag()
  if (files.length) {
    addToQueue(files, currentFolder.value)
  }
}

function rowAttrs(row: Row): Record<string, unknown> {
  if (row.kind === 'upload') {
    return {}
  }
  const base: Record<string, unknown> = {
    draggable: 'true',
    onDragstart: (event: DragEvent) => startDrag(event, row),
    onDragend: endDrag,
  }
  if (row.kind !== 'folder') {
    return base
  }
  return {
    ...base,
    class: { 'drop-target': dropTarget.value === row.folder.id },
    onDragover: (event: DragEvent) => onTargetDragOver(event, row.folder.id),
    onDrop: (event: DragEvent) => {
      event.preventDefault()
      // The list underneath would otherwise treat this as a drop on the open folder.
      event.stopPropagation()
      dropOn(row.folder.id, event)
    },
  }
}
</script>

<template>
  <UiScreen>
    <UiRail>
      <UiPageHeader
        :eyebrow="
          data ? t('files.counts', { folders: folders.length, files: documents.length }) : ''
        "
        :title="t('files.headTitle')"
      />

      <div class="actions">
        <UiButton variant="primary" block @click="pickFiles">
          <template #icon><UiIcon name="upload" /></template>
          {{ t('files.upload') }}
        </UiButton>
        <UiButton variant="secondary" block @click="openNewFolder">
          <template #icon><UiIcon name="plus" /></template>
          {{ t('files.newFolder') }}
        </UiButton>
        <input
          ref="fileInput"
          class="sr-only"
          type="file"
          multiple
          :accept="accept"
          @change="onPicked"
        >
      </div>

      <FolderTree
        :folders="folders"
        :selected="currentFolder"
        :expanded="expanded"
        live
        :can-drop="canDropOn"
        :drop-target="dropTarget"
        @select="openFolder"
        @toggle="toggleFolder"
        @hover="dropTarget = $event"
        @drag-folder="startFolderDrag"
        @drop-on="dropOn"
      />
    </UiRail>

    <UiRegion>
      <!-- The whole data region is a drop target for files from the desktop; the overlay
           says which folder they would land in, and nothing else. -->
      <div class="contents" @dragover="onListDragOver" @drop.prevent="onListDrop">
        <UiPanel lead>
          <template #title>
            <!-- Each crumb is also a drop target: dropping a row on the folder you came
                 from is how a file manager moves something back up a level. -->
            <h2 class="crumbs">
              <button
                type="button"
                class="crumb"
                :class="{ current: !crumbs.length, target: dropTarget === null }"
                :aria-current="!crumbs.length ? 'page' : undefined"
                @click="openFolder(null)"
                @dragover="onTargetDragOver($event, null)"
                @drop.prevent.stop="dropOn(null, $event)"
              >
                {{ t('files.root') }}
              </button>
              <template v-for="(crumb, index) in crumbs" :key="crumb.id">
                <UiIcon class="crumb-sep" name="chevron-right" />
                <button
                  type="button"
                  class="crumb"
                  :class="{ current: index === crumbs.length - 1, target: dropTarget === crumb.id }"
                  :aria-current="index === crumbs.length - 1 ? 'page' : undefined"
                  @click="openFolder(crumb.id)"
                  @dragover="onTargetDragOver($event, crumb.id)"
                  @drop.prevent.stop="dropOn(crumb.id, $event)"
                >
                  {{ crumb.name }}
                </button>
              </template>
            </h2>
          </template>

          <template #meta>
            <span v-if="data">{{ t('files.itemCount', { count: rows.length }) }}</span>
            <UiButton
              variant="ghost"
              size="xs"
              icon-only
              :label="t('common.refresh')"
              :loading="pending"
              @click="refresh"
            >
              <template #icon><UiIcon name="refresh" /></template>
            </UiButton>
          </template>

          <UiBanner v-if="errorMessage" class="state" tone="error">{{ errorMessage }}</UiBanner>
          <UiBanner v-if="mutationError" class="state" tone="error">
            {{ mutationError }}
            <template #actions>
              <UiButton variant="ghost" size="xs" @click="mutationError = null">
                {{ t('common.close') }}
              </UiButton>
            </template>
          </UiBanner>

          <UiSkeleton v-if="!data && !errorMessage" class="state" :rows="6" />

          <UiEmptyState
            v-else-if="data && !rows.length"
            :title="currentFolder === null ? t('files.empty') : t('files.emptyFolder')"
          >
            <template #action>
              <UiButton variant="primary" @click="pickFiles">
                <template #icon><UiIcon name="upload" /></template>
                {{ t('files.upload') }}
              </UiButton>
            </template>
          </UiEmptyState>

          <UiDataTable
            v-else-if="data"
            :columns="columns"
            :rows="rows"
            :row-key="(row) => row.key"
            :row-attrs="rowAttrs"
            :caption="t('files.headTitle')"
          >
            <template #cell-name="{ row }">
              <button
                v-if="row.kind === 'folder'"
                type="button"
                class="entry"
                :title="row.folder.name"
                @click="openFolder(row.folder.id)"
              >
                <UiIcon name="folder" />
                <span class="entry-name">{{ row.folder.name }}</span>
              </button>

              <button
                v-else-if="row.kind === 'file'"
                type="button"
                class="entry"
                :class="{ failed: row.document.status === 'failed' }"
                :title="row.document.name"
                @click="showResult(row.document)"
              >
                <UiIcon :name="row.document.kind === 'image' ? 'image' : 'file-text'" />
                <span class="entry-name link">{{ row.document.name }}</span>
              </button>

              <span v-else class="entry pendingup" :title="row.upload.name">
                <UiSpinner />
                <span class="entry-name">{{ row.upload.name }}</span>
              </span>
            </template>

            <template #cell-status="{ row }">
              <span v-if="row.kind === 'file'" class="state-cell">
                <UiStatusDot
                  :tone="STATUS_TONE[row.document.status]"
                  :label="t(`status.${row.document.status}`)"
                />
                <UiUsageBar
                  v-if="row.document.status === 'running'"
                  class="meter"
                  :share="parseProgress(row.document)"
                  :label="
                    t('files.progress', {
                      done: row.document.pages_done,
                      total: row.document.page_count ?? 0,
                    })
                  "
                />
              </span>
              <span v-else-if="row.kind === 'upload'" class="muted">
                {{ row.upload.state === 'uploading' ? t('files.uploading') : t('files.waiting') }}
              </span>
            </template>

            <template #cell-pages="{ row }">
              <template v-if="row.kind === 'file'">
                {{
                  row.document.page_count
                    ? `${row.document.pages_done}/${row.document.page_count}`
                    : row.document.pages_done || ''
                }}
              </template>
            </template>

            <template #cell-size="{ row }">
              <span class="muted">
                <template v-if="row.kind === 'file'">
                  {{ formatBytes(row.document.size_bytes, locale) }}
                </template>
                <template v-else-if="row.kind === 'upload'">
                  {{ formatBytes(row.upload.size, locale) }}
                </template>
              </span>
            </template>

            <template #cell-added="{ row }">
              <span class="muted">
                <template v-if="row.kind === 'folder'">
                  {{ formatShortDateTime(row.folder.created_at, locale) }}
                </template>
                <template v-else-if="row.kind === 'file'">
                  {{ formatShortDateTime(row.document.created_at, locale) }}
                </template>
              </span>
            </template>

            <template #cell-actions="{ row }">
              <span v-if="row.kind !== 'upload'" class="row-actions">
                <UiButton
                  variant="ghost"
                  size="xs"
                  icon-only
                  :label="
                    row.kind === 'folder'
                      ? `${t('files.renameFolder')}: ${rowName(row)}`
                      : `${t('files.renameFile')}: ${rowName(row)}`
                  "
                  @click="openRename(row)"
                >
                  <template #icon><UiIcon name="edit" /></template>
                </UiButton>
                <UiButton
                  variant="ghost"
                  size="xs"
                  icon-only
                  :label="t('files.moveItem', { name: rowName(row) })"
                  @click="((moving = row), (mutationError = null))"
                >
                  <template #icon><UiIcon name="folder-input" /></template>
                </UiButton>
                <UiButton
                  variant="ghost"
                  size="xs"
                  icon-only
                  :label="
                    row.kind === 'folder'
                      ? `${t('files.deleteFolder')}: ${rowName(row)}`
                      : `${t('files.deleteFile')}: ${rowName(row)}`
                  "
                  @click="((deleting = row), (mutationError = null))"
                >
                  <template #icon><UiIcon name="trash" /></template>
                </UiButton>
              </span>
            </template>
          </UiDataTable>
        </UiPanel>

        <!-- Where the files would land. A destination, not an instruction. -->
        <div v-if="fileOverList" class="dropzone">
          <div class="dropzone-mark">
            <UiIcon name="folder-open" />
            <span>{{ crumbs.length ? crumbs[crumbs.length - 1]!.name : t('files.root') }}</span>
          </div>
        </div>
      </div>
    </UiRegion>

    <UiModal
      v-if="showNewFolder"
      :title="t('files.newFolder')"
      @close="showNewFolder = false"
    >
      <form id="new-folder" @submit.prevent="submitNewFolder">
        <UiField v-slot="{ id }" :label="t('files.nameLabel')">
          <UiTextInput :id="id" v-model="newFolderName" :maxlength="255" required />
        </UiField>
      </form>
      <template #footer>
        <UiButton variant="ghost" :disabled="busy" @click="showNewFolder = false">
          {{ t('common.cancel') }}
        </UiButton>
        <UiButton
          variant="primary"
          type="submit"
          form="new-folder"
          :loading="busy"
          :disabled="!newFolderName.trim()"
        >
          {{ t('common.save') }}
        </UiButton>
      </template>
    </UiModal>

    <UiModal
      v-if="renaming"
      :title="renaming.kind === 'folder' ? t('files.renameFolder') : t('files.renameFile')"
      @close="renaming = null"
    >
      <form id="rename" @submit.prevent="submitRename">
        <UiField v-slot="{ id }" :label="t('files.nameLabel')">
          <UiTextInput :id="id" v-model="renameValue" :maxlength="512" required />
        </UiField>
      </form>
      <template #footer>
        <UiButton variant="ghost" :disabled="busy" @click="renaming = null">
          {{ t('common.cancel') }}
        </UiButton>
        <UiButton
          variant="primary"
          type="submit"
          form="rename"
          :loading="busy"
          :disabled="!renameValue.trim()"
        >
          {{ t('common.save') }}
        </UiButton>
      </template>
    </UiModal>

    <MoveDialog
      v-if="moving"
      :folders="folders"
      :name="rowName(moving)"
      :current="movingFrom"
      :forbidden="forbiddenTargets"
      :pending="busy"
      @move="submitMove"
      @cancel="moving = null"
    />

    <UiConfirmDialog
      v-if="deleting"
      :title="deleting.kind === 'folder' ? t('files.deleteFolder') : t('files.deleteFile')"
      :message="
        deleting.kind === 'folder'
          ? t('files.deleteFolderConfirm', { name: rowName(deleting) })
          : t('files.deleteFileConfirm', { name: rowName(deleting) })
      "
      :confirm-label="t('common.delete')"
      :pending="busy"
      @confirm="confirmDelete"
      @cancel="deleting = null"
    />

    <ResultViewer
      v-if="openDocument"
      :title="openDocument.name"
      :error="openDocument.error"
      :result="results.get(openDocument.id) ?? null"
      :pending="loadingResults.has(openDocument.id)"
      :error-message="resultErrors.get(openDocument.id) ?? null"
      @close="openDocument = null"
    />
  </UiScreen>
</template>

<style scoped>
.actions {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* The drop surface: it has to be the box the panel fills, so the overlay can cover exactly
   the list and nothing else. */
.contents {
  position: relative;
  display: grid;
  grid-template-rows: minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
}

.state {
  margin-top: var(--space-4);
}

/* --- Breadcrumb ----------------------------------------------------------- */

/* The panel's heading, made of the places you can go back to. Same serif and size as any
   other panel title — it is a title that happens to be clickable. */
.crumbs {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
  overflow: hidden;
  font-size: var(--display-sm);
  letter-spacing: normal;
}

.crumb {
  max-width: 22ch;
  padding: 0;
  border: none;
  background: none;
  color: var(--muted);
  font: inherit;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease);
}

.crumb:hover {
  color: var(--accent);
}

.crumb.current {
  color: var(--ink);
}

/* Lit only while a drag is over it. Underlined rather than boxed: a crumb is a word in a
   heading, and a box around one word would jump the line. */
.crumb.target {
  color: var(--accent);
  box-shadow: inset 0 -2px 0 var(--accent);
}

.crumb-sep {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: var(--faint);
}

/* --- Rows ----------------------------------------------------------------- */

/* Not `cell-block`: that is `UiDataTable`'s ellipsis helper for a cell whose content is one
   block, and its `display: block` would flatten this row of icon-and-name. The clipping it
   provides is done here instead, on the name itself. */
.entry {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  max-width: 100%;
  min-width: 0;
  padding: 0;
  border: none;
  background: none;
  color: var(--ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.entry.pendingup {
  cursor: default;
  color: var(--muted);
}

.entry :deep(svg) {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  color: var(--faint);
}

.entry-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* A file opens a dialog, so it is a button — but it is the row's identity and the thing
   worth opening, so it reads as the link it behaves like. */
.entry-name.link {
  border-bottom: 1px solid var(--edge);
  transition:
    color var(--duration-fast) var(--ease),
    border-color var(--duration-fast) var(--ease);
}

.entry:hover .entry-name.link {
  color: var(--accent);
  border-color: var(--accent);
}

.entry.failed .entry-name.link {
  color: var(--danger);
  border-color: var(--danger-edge);
}

.state-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
}

/* Short on purpose: it sits beside the word it qualifies, not instead of it. */
.meter {
  width: 44px;
  flex-shrink: 0;
}

.muted {
  color: var(--muted);
}

.row-actions {
  display: inline-flex;
  gap: var(--space-1);
}

/* A folder row lit up as a drop target. Inset, so accepting a drop does not move the row. */
.contents :deep(tr.drop-target) td {
  background: var(--rail-active);
  box-shadow:
    inset 0 1px 0 var(--accent),
    inset 0 -1px 0 var(--accent);
}

/* --- Dropping files from the desktop -------------------------------------- */

.dropzone {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: grid;
  place-items: center;
  /* Transparent to the pointer: the drop is handled by the region under it, and a solid
     overlay would swallow the `dragover` that keeps the drag alive. */
  pointer-events: none;
  background: var(--paper);
  border: 1px dashed var(--accent);
}

.dropzone-mark {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  color: var(--ink);
  font-size: var(--display-xs);
  font-family: var(--font-display);
}

.dropzone-mark :deep(svg) {
  width: 28px;
  height: 28px;
  color: var(--accent);
}

@media (max-width: 900px) {
  /* The rail is above the list here, so the tree would push everything off the screen. */
  .contents {
    display: block;
  }
}
</style>
