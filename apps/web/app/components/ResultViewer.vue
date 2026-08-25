<script setup lang="ts">
/**
 * A finished parse, as a document rather than as a blob of JSON.
 *
 * The dialog is the reason a filename is a link on both screens that list parses — Files
 * and History: what a reader actually wants to check is whether the markdown came back
 * right, and a `<pre>` of the whole envelope makes that a reading exercise. The JSON is
 * still one tab away — it is the contract, and nothing here replaces it.
 *
 * It takes a title and a job error rather than a job row, because the two callers hold
 * different shapes of the same thing: a `JobSummary` on History, a `LibraryDocument` on
 * Files. Neither is this component's business — it renders a result.
 *
 * Two scroll axes again: a page rail on the left, one continuous document on the right.
 * They stay in sync in both directions, and the two mechanics that make that not fight each
 * other are worth stating:
 *
 *  - Scrolling sets the active page to the *last* section whose top has passed a reading
 *    line 72px below the pane's top edge — not the first visible one, which flickers between
 *    two pages for the whole length of a page boundary.
 *  - A click sets `scrollTop` from `offsetTop` rather than calling `scrollIntoView`, which
 *    would also scroll the dialog itself inside the viewport, and suppresses the
 *    scroll-driven update briefly so the click's own target wins the race against the
 *    smooth scroll it just started.
 *
 * The element refs are plain variables, not reactive state: they are the DOM, and making
 * them reactive would re-render the document on every scroll frame.
 */
import type { ComponentPublicInstance } from 'vue'
import type { JobResult } from '~/lib/api'
import { cellGroupsToMarkdown, nodesToMarkdown, type OrphanListContext } from '~/lib/copy'
import { formatBbox, parseResultMarkdown, type Bbox, type ResultBlock } from '~/lib/markdown'

const props = withDefaults(
  defineProps<{
    /** The document's name — the dialog's heading and its accessible name. */
    title: string
    result: JobResult | null
    /** Why the parse itself failed, from the job. Outranks everything below it. */
    error?: string | null
    /** The result is still in flight, or failed — the body says so instead of the document. */
    pending?: boolean
    /** Why fetching the result failed, from the client. */
    errorMessage?: string | null
    /** Where this caller's figure crops live (`…/figures`); null hides images entirely. */
    figureBase?: string | null
  }>(),
  { error: null, errorMessage: null, figureBase: null },
)

const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()

const tab = ref<'markdown' | 'json'>('markdown')
const pages = computed(() => (props.result ? parseResultMarkdown(props.result.markdown) : []))

/** A running job's snapshot: pages keep arriving under this one (docs/api.md § Partial). */
const partial = computed(() => props.result?.meta.partial === true)

/** Opens on the first page that has figures — the part of a result worth checking first —
 *  falling back to the first page when none do. The document jumps there too: selecting a
 *  page in the rail without moving the document would just be a lie about where you are.
 *  Once only: a partial result re-renders every poll, and re-jumping would yank the
 *  document out from under whoever is already reading it. */
const activePage = ref(0)
let jumped = false
watch(
  pages,
  async (list) => {
    if (jumped || !list.length) {
      return
    }
    jumped = true
    const first = (list.find((page) => page.figureCount > 0) ?? list[0])?.page ?? 0
    activePage.value = first
    if (!first) {
      return
    }
    await nextTick()
    goToPage(first)
  },
  { immediate: true },
)

/**
 * The JSON tab replaces the whole body, so coming back mounts a fresh scroller at the top
 * while `activePage` still names wherever the reader had got to — the rail would highlight
 * page 5 over a document showing page 1. `pages` has not changed, so its watcher will not
 * do this for us.
 */
watch(tab, async (view) => {
  if (view !== 'markdown' || !activePage.value) {
    return
  }
  await nextTick()
  goToPage(activePage.value)
})

const scroller = ref<HTMLElement | null>(null)
const sections = new Map<number, HTMLElement>()
/** Set while a click-driven scroll is still settling, so `onScroll` does not overrule it. */
let suppressUntil = 0

function registerSection(page: number, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLElement) {
    sections.set(page, el)
  } else {
    sections.delete(page)
  }
}

function goToPage(page: number) {
  const box = scroller.value
  const section = sections.get(page)
  activePage.value = page
  if (!box || !section) {
    return
  }
  suppressUntil = Date.now() + 120
  box.scrollTop = section.offsetTop - box.offsetTop
}

const READING_LINE = 72

function onScroll() {
  const box = scroller.value
  if (!box || Date.now() < suppressUntil) {
    return
  }
  const line = box.scrollTop + READING_LINE
  let current = activePage.value
  for (const page of pages.value) {
    const section = sections.get(page.page)
    if (section && section.offsetTop - box.offsetTop <= line) {
      current = page.page
    }
  }
  activePage.value = current
}

const meta = computed(() => {
  const result = props.result
  if (!result) {
    return ''
  }
  return t('viewer.meta', {
    model: result.meta.model,
    pages: result.pages.length,
    bbox: result.meta.bbox_format,
  })
})

/** The live "x of y pages" line a partial result carries; empty once the job is done. */
const progress = computed(() => {
  const result = props.result
  if (!result || !partial.value) {
    return ''
  }
  const total = result.meta.page_count
  const done = result.meta.pages_done ?? pages.value.length
  return total ? t('viewer.parsing', { done, total }) : t('viewer.parsingSimple')
})

// --- figures ---------------------------------------------------------------

/** Crops that answered 404 — old results, or a crop that failed — drawn as the dashed
 *  placeholder instead of a broken image. */
const failedCrops = reactive(new Set<string>())

/** A partial result can expose a placeholder a beat before the worker has written its
 *  crop (billing is persisted first, docs/parsing.md), so its request 404s. Each new
 *  snapshot forgets past failures and retries — the image appears as soon as the file
 *  exists, instead of staying hidden until the viewer is reopened. */
watch(
  () => props.result,
  () => {
    failedCrops.clear()
  },
)

function figureKey(page: number, bbox: Bbox): string {
  return `${page}/${bbox.join(',')}`
}

function figureUrl(page: number, bbox: Bbox): string {
  return `${props.figureBase}/${figureKey(page, bbox)}`
}

/** The placeholder + caption this figure was rendered from — what a copy hands back. */
function figureSource(page: number, block: ResultBlock & { kind: 'fig' }): string {
  const placeholder = `![${block.id}](sightread://p${page}/${block.bbox.join(',')})`
  return block.caption ? `${placeholder}\n${block.caption}` : placeholder
}

// --- copy as markdown ------------------------------------------------------

/**
 * What the cloned fragment can no longer say about a list selection: the clone drops the
 * range's common ancestor, so an all-inside-one-list selection arrives as bare `li` runs.
 * The live range still knows the list — its kind, and the number the first selected item
 * carries — and hands both to the serializer.
 */
function orphanListContext(range: Range): OrphanListContext | undefined {
  const container = range.commonAncestorContainer
  const element = container instanceof Element ? container : container.parentElement
  const list = element?.closest('.md-list')
  if (!list) {
    return undefined
  }
  if (list.tagName !== 'OL') {
    return { ordered: false, start: 1 }
  }
  const start = Number.parseInt(list.getAttribute('start') ?? '1', 10) || 1
  const startNode = range.startContainer
  const startElement = startNode instanceof Element ? startNode : startNode.parentElement
  const item = startElement?.closest('li')
  const items = Array.from(list.children).filter((child) => child.tagName === 'LI')
  const offset = item ? Math.max(0, items.indexOf(item)) : 0
  return { ordered: true, start: start + offset }
}

/**
 * Firefox reports a table-region selection as one range per selected cell. Serialized
 * range by range that becomes a stack of one-cell tables, so when every range sits in a
 * cell of the same table, the live cells are grouped by their row and serialized as the
 * one table the user actually selected. Any other multi-range selection falls through to
 * the per-range path.
 */
function tableRegionMarkdown(selection: Selection): string | null {
  if (selection.rangeCount < 2) {
    return null
  }
  const cells: Element[] = []
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const node = selection.getRangeAt(index).startContainer
    const element = node instanceof Element ? node : node.parentElement
    const cell = element?.closest('td, th')
    if (!cell) {
      return null
    }
    cells.push(cell)
  }
  const table = cells[0]?.closest('table')
  if (!table || !cells.every((cell) => cell.closest('table') === table)) {
    return null
  }
  // Ranges arrive in document order, so insertion order groups rows top to bottom.
  const rows = new Map<Element, Element[]>()
  for (const cell of cells) {
    const row = cell.closest('tr')
    if (!row) {
      return null
    }
    const group = rows.get(row) ?? []
    group.push(cell)
    rows.set(row, group)
  }
  return cellGroupsToMarkdown([...rows.values()])
}

/** Ctrl+C inside the document copies markdown, tables included (docs/web.md). */
function onCopy(event: ClipboardEvent) {
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || !event.clipboardData) {
    return
  }
  const region = tableRegionMarkdown(selection)
  const fragments: string[] = []
  if (region) {
    fragments.push(region)
  } else {
    for (let index = 0; index < selection.rangeCount; index += 1) {
      const range = selection.getRangeAt(index)
      // A selection confined to a code or math block copies verbatim: the clone is a bare
      // text node whose whitespace the serializer would collapse, and in a <pre> the line
      // breaks and indentation are the content.
      const container = range.commonAncestorContainer
      const element = container instanceof Element ? container : container.parentElement
      if (element?.closest('pre')) {
        fragments.push(range.toString())
        continue
      }
      const markdown = nodesToMarkdown(range.cloneContents().childNodes, orphanListContext(range))
      if (markdown) {
        fragments.push(markdown)
      }
    }
  }
  if (!fragments.length) {
    return
  }
  event.preventDefault()
  event.clipboardData.setData('text/plain', fragments.join('\n'))
}

const json = computed(() => (props.result ? JSON.stringify(props.result, null, 2) : ''))

/**
 * Pages the pipeline could not transcribe. A job with some pages failed still finishes as
 * `succeeded` and simply omits them from the markdown (docs/jobs.md), so without this the
 * document reads as complete and the only evidence is in the JSON tab.
 */
const failedPages = computed(() => props.result?.errors ?? [])
</script>

<template>
  <UiModal :title="title" size="lg" tall flush @close="emit('close')">
    <template #title>
      <h2 class="doc-title">{{ title }}</h2>
      <p v-if="meta" class="doc-meta mono">{{ meta }}</p>
    </template>

    <!-- A segmented pair, not two loose buttons: they are two views of one thing, and the
         shared border is what says so. -->
    <template #actions>
      <div class="tabs" role="tablist" :aria-label="t('viewer.views')">
        <button
          v-for="view in (['markdown', 'json'] as const)"
          :key="view"
          type="button"
          role="tab"
          class="tab"
          :class="{ active: tab === view }"
          :aria-selected="tab === view ? 'true' : 'false'"
          @click="tab = view"
        >
          {{ t(`viewer.view.${view}`) }}
        </button>
      </div>
    </template>

    <div class="body">
      <UiBanner v-if="error" class="state" tone="error">{{ error }}</UiBanner>
      <UiBanner v-else-if="errorMessage" class="state" tone="error">{{ errorMessage }}</UiBanner>
      <UiSkeleton v-else-if="pending" class="state" :rows="5" />

      <pre v-else-if="tab === 'json'" class="json mono">{{ json }}</pre>

      <UiEmptyState
        v-else-if="!pages.length && !partial"
        class="state"
        :title="t('viewer.empty')"
        :body="t('viewer.emptyBody')"
      />

      <div v-else class="markdown" :class="{ degraded: failedPages.length > 0 || partial }">
        <!-- Spans both columns: facts about the whole document, not about one page. Both
             can hold at once — a page can fail while the rest is still parsing, and the
             failure must not silence the live progress. -->
        <div v-if="failedPages.length || partial" class="doc-notes">
          <UiBanner v-if="failedPages.length" class="degraded-note" tone="error">
            {{
              t('viewer.degraded', {
                count: failedPages.length,
                pages: failedPages.map((entry) => entry.page).join(', '),
              })
            }}
          </UiBanner>
          <!-- The parse is still running; pages below are what exists so far
               (docs/api.md § Partial results). -->
          <div v-if="partial" class="parsing-note">
            <UiSpinner />
            <span>{{ progress }}</span>
          </div>
        </div>

        <nav class="page-rail" :aria-label="t('viewer.pagesLabel')">
          <p class="eyebrow sm page-rail-label">{{ t('viewer.pagesLabel') }}</p>
          <button
            v-for="page in pages"
            :key="page.page"
            type="button"
            class="page-button"
            :class="{ active: page.page === activePage }"
            :aria-current="page.page === activePage ? 'true' : undefined"
            @click="goToPage(page.page)"
          >
            <span>{{ t('viewer.pageN', { page: page.page }) }}</span>
            <span v-if="page.figureCount" class="page-figures">
              {{ t('viewer.figureCount', { count: page.figureCount }) }}
            </span>
          </button>
        </nav>

        <div ref="scroller" class="document" @scroll="onScroll" @copy="onCopy">
          <section
            v-for="page in pages"
            :key="page.page"
            :ref="(el) => registerSection(page.page, el)"
            class="page"
          >
            <p class="eyebrow sm page-marker" :class="{ current: page.page === activePage }">
              {{ t('viewer.pageN', { page: page.page }) }}
            </p>
            <article class="prose">
              <template v-for="(block, index) in page.blocks" :key="index">
                <h3 v-if="block.kind === 'h2'" class="md-h2" :data-level="block.level">
                  <MdInline :text="block.text" />
                </h3>
                <h4 v-else-if="block.kind === 'h3'" class="md-h3" :data-level="block.level">
                  <MdInline :text="block.text" />
                </h4>
                <p v-else-if="block.kind === 'p'" class="md-p"><MdInline :text="block.text" /></p>

                <!-- Whitespace preserved: the line breaks are the formula. -->
                <pre v-else-if="block.kind === 'math'" class="md-math">{{ block.text }}</pre>

                <pre
                  v-else-if="block.kind === 'code'"
                  class="md-math"
                ><code :class="block.lang ? `language-${block.lang}` : undefined">{{ block.text }}</code></pre>

                <component
                  :is="block.ordered ? 'ol' : 'ul'"
                  v-else-if="block.kind === 'list'"
                  class="md-list"
                  :start="block.start"
                >
                  <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
                    <MdInline :text="item" />
                  </li>
                </component>

                <!-- Its own scroll axis: a table wider than the reading measure slides in
                     place instead of stretching the page (docs/web.md § Result viewer). -->
                <div v-else-if="block.kind === 'table'" class="md-table-wrap">
                  <table class="md-table">
                    <thead>
                      <tr>
                        <th v-for="(cell, column) in block.header" :key="column" scope="col">
                          <MdInline :text="cell" />
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
                        <td v-for="(cell, column) in row" :key="column">
                          <MdInline :text="cell" />
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <!-- The stored crop when one exists; the dashed frame when it does not
                     (old results, failed crop). `data-md` is what a copy hands back. -->
                <figure v-else class="md-figure" :data-md="figureSource(page.page, block)">
                  <img
                    v-if="figureBase && !failedCrops.has(figureKey(page.page, block.bbox))"
                    class="figure-image"
                    :src="figureUrl(page.page, block.bbox)"
                    :alt="block.caption || block.id"
                    loading="lazy"
                    @error="failedCrops.add(figureKey(page.page, block.bbox))"
                  >
                  <div v-else class="figure-frame">
                    <UiIcon name="scan-text" />
                    <span>{{ t('viewer.figurePending') }}</span>
                  </div>
                  <figcaption class="figure-caption mono">
                    <span><MdInline :text="block.caption || block.id" /></span>
                    <span>{{ formatBbox(block.bbox) }}</span>
                  </figcaption>
                </figure>
              </template>
            </article>
          </section>

          <!-- Where the next page will land, while the parse is still running. -->
          <section v-if="partial" class="page" aria-hidden="true">
            <UiSkeleton class="page-skeleton" :rows="4" />
          </section>
        </div>
      </div>
    </div>
  </UiModal>
</template>

<style scoped>
.body {
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

/* The states that replace the document rather than sitting inside it. */
.state {
  margin: var(--space-6);
}

.doc-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--display-sm);
  letter-spacing: normal;
}

.doc-meta {
  margin-top: var(--space-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--faint);
  font-size: var(--text-2xs);
}

/* --- Tabs ----------------------------------------------------------------- */

/*
 * No `overflow: hidden` to round the children: the focus ring is an outline at a 2px
 * offset, and a clipping ancestor eats most of it on a control that sits flush against the
 * edge. The buttons carry the corners themselves instead — one pixel less than the border's
 * radius, since the border sits outside them.
 */
.tabs {
  display: inline-flex;
  flex-shrink: 0;
  border: 1px solid var(--edge);
  border-radius: var(--radius);
}

.tab {
  height: var(--control-height-sm);
  padding: 0 var(--space-3);
  border: none;
  background: var(--paper);
  color: var(--ink);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition:
    background var(--duration-fast) var(--ease),
    color var(--duration-fast) var(--ease);
}

.tab:first-child {
  border-radius: calc(var(--radius) - 1px) 0 0 calc(var(--radius) - 1px);
}

.tab:last-child {
  border-radius: 0 calc(var(--radius) - 1px) calc(var(--radius) - 1px) 0;
}

.tab + .tab {
  border-left: 1px solid var(--edge);
}

.tab:hover:not(.active) {
  background: var(--rail);
}

.tab.active {
  background: var(--accent);
  color: var(--accent-fg);
}

/* --- Markdown view -------------------------------------------------------- */

.markdown {
  display: grid;
  grid-template-columns: 132px minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  min-height: 0;
  height: 100%;
}

/* A warning about the whole document sits above both columns and pushes them down, rather
   than scrolling away inside one of them. */
.markdown.degraded {
  grid-template-rows: auto minmax(0, 1fr);
}

.doc-notes {
  grid-column: 1 / -1;
}

.degraded-note {
  border-inline: none;
  border-top: none;
}

/* A fact about the whole document — it is still growing. */
.parsing-note {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--line);
  color: var(--muted);
  font-size: var(--text-xs);
}

.page-rail {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: var(--space-4) var(--space-3);
  background: var(--rail);
  border-right: 1px solid var(--line);
}

.page-rail-label {
  padding: 0 var(--space-2) var(--space-2);
}

.page-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-shrink: 0;
  height: var(--control-height-sm);
  padding: 0 var(--space-2);
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: var(--muted);
  font-size: var(--text-xs);
  text-align: left;
  cursor: pointer;
  transition:
    background var(--duration-fast) var(--ease),
    color var(--duration-fast) var(--ease);
}

.page-button:hover:not(.active) {
  background: var(--rail-active);
  color: var(--ink);
}

.page-button.active {
  background: var(--rail-active);
  color: var(--ink);
  font-weight: var(--weight-semibold);
}

.page-figures {
  flex-shrink: 0;
  font-size: var(--text-3xs);
  font-weight: var(--weight-normal);
  color: var(--faint);
}

/* One continuous scroll of every page — the rail selects, it does not filter. A reader
   comparing two pages should not have to click between them. */
.document {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding: 0 var(--space-10) var(--space-12);
}

.page {
  padding: var(--space-7) 0 var(--space-1);
  border-top: 1px solid var(--line);
}

/* Only the page you are reading is marked in the accent — that is what makes it a position
   indicator rather than a repeated decoration down the document. */
.page-marker {
  margin-bottom: 18px;
}

.page-marker.current {
  color: var(--accent);
}

/* A reading measure, not the pane's width: 60ch is where a 14px line stops being a line and
   starts being a paragraph you lose your place in. */
.prose {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 60ch;
}

.md-h2 {
  font-size: var(--display-md);
  letter-spacing: var(--tracking-heading);
}

.md-h3 {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--display-xs);
  font-weight: var(--weight-semibold);
  line-height: 1.3;
}

.md-p {
  color: var(--ink-soft);
  font-size: var(--text-base);
  line-height: 1.75;
  text-wrap: pretty;
}

/* A formula is read, not scanned, so it keeps the body's colour and size — but it scrolls
   sideways rather than wrapping, because a re-wrapped equation is a different equation. */
.md-math {
  margin: 0;
  overflow-x: auto;
  color: var(--ink-soft);
  font-family: var(--mono);
  font-size: var(--text-sm);
  line-height: 1.7;
  white-space: pre;
}

/* Markers stay outside the measure, so the text edge lines up with the paragraphs above
   and below it rather than being indented away from them. */
.md-list {
  margin: 0;
  padding-left: var(--space-5);
  color: var(--ink-soft);
  font-size: var(--text-base);
  line-height: 1.75;
}

.md-list li + li {
  margin-top: var(--space-2);
}

/* The table's own scroll axis: wider than the reading measure, it slides in place rather
   than stretching the page — the prose column's width is fixed (docs/web.md). */
.md-table-wrap {
  max-width: 100%;
  overflow-x: auto;
  overscroll-behavior-x: contain;
}

.md-table {
  width: max-content;
  min-width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

/* Long prose cells still wrap; the cap is what keeps one wordy cell from dragging the
   whole table out to a single unreadable line. */
.md-table th,
.md-table td {
  max-width: 36ch;
}

.md-table th {
  padding: var(--cell-y-tight) var(--space-4) var(--cell-y-tight) 0;
  text-align: left;
  font-size: var(--text-3xs);
  font-weight: var(--weight-semibold);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--faint);
  border-bottom: 1px solid var(--line-soft);
}

.md-table td {
  padding: var(--cell-y-tight) var(--space-4) var(--cell-y-tight) 0;
  border-bottom: 1px solid var(--line-soft);
  color: var(--ink-soft);
}

.md-table tbody tr:last-child td {
  border-bottom: none;
}

.md-figure {
  margin: 0;
}

/* The stored crop, at the width the prose gives it and never more. */
.figure-image {
  display: block;
  max-width: 100%;
  border: 1px solid var(--line-soft);
  background: var(--paper);
}

/* Dashed, because it is a frame around something that is not there yet. */
.figure-frame {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  height: 210px;
  border: 1px dashed var(--edge);
  background: var(--rail);
  color: var(--faint);
  font-size: var(--text-xs);
}

.figure-frame :deep(svg) {
  width: 22px;
  height: 22px;
}

.figure-caption {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
  margin-top: var(--space-2);
  font-size: var(--text-2xs);
  color: var(--faint);
}

.figure-caption span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Where the next page will land while the parse runs. */
.page-skeleton {
  max-width: 60ch;
}

/* Inline math keeps the body's colour; the serif face is what marks it as notation. */
.prose :deep(.md-inline-math) {
  font-family: var(--font-display);
  font-style: italic;
}

.prose :deep(.md-inline-math sup),
.prose :deep(.md-inline-math sub) {
  font-style: normal;
  line-height: 1;
}

/* --- JSON view ------------------------------------------------------------ */

/* The contract, not a document: it keeps its own line breaks and scrolls both ways rather
   than being re-wrapped into something that no longer matches the response. */
.json {
  margin: 0;
  height: 100%;
  overflow: auto;
  padding: var(--space-6);
  background: var(--paper-sunken);
  color: var(--muted);
  line-height: 1.7;
  white-space: pre;
}

@media (max-width: 640px) {
  /* No room for a rail beside the document on a phone: the page markers in the document
     itself are the navigation. */
  .markdown {
    grid-template-columns: minmax(0, 1fr);
  }

  .page-rail {
    display: none;
  }

  .document {
    padding: 0 var(--space-5) var(--space-10);
  }
}
</style>
