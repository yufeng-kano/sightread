<script setup lang="ts">
/**
 * A finished parse, as a document rather than as a blob of JSON.
 *
 * The dialog is the reason the Jobs filename is a link: what a caller actually wants to
 * check is whether the markdown came back right, and a `<pre>` of the whole envelope makes
 * that a reading exercise. The JSON is still one tab away — it is the contract, and nothing
 * here replaces it.
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
import type { JobResult, JobSummary } from '~/lib/api'
import { formatBbox, parseResultMarkdown } from '~/lib/markdown'

const props = defineProps<{
  job: JobSummary
  result: JobResult | null
  /** The result is still in flight, or failed — the body says so instead of the document. */
  pending?: boolean
  errorMessage?: string | null
}>()

const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()

const tab = ref<'markdown' | 'json'>('markdown')
const pages = computed(() => (props.result ? parseResultMarkdown(props.result.markdown) : []))

/** Opens on the first page that has figures — the part of a result worth checking first —
 *  falling back to the first page when none do. The document jumps there too: selecting a
 *  page in the rail without moving the document would just be a lie about where you are. */
const activePage = ref(0)
watch(
  pages,
  async (list) => {
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
  return t('jobs.resultMeta', {
    model: result.meta.model,
    pages: result.pages.length,
    bbox: result.meta.bbox_format,
  })
})

const json = computed(() => (props.result ? JSON.stringify(props.result, null, 2) : ''))

/**
 * Pages the pipeline could not transcribe. A job with some pages failed still finishes as
 * `succeeded` and simply omits them from the markdown (docs/jobs.md), so without this the
 * document reads as complete and the only evidence is in the JSON tab.
 */
const failedPages = computed(() => props.result?.errors ?? [])
</script>

<template>
  <UiModal :title="job.filename" size="lg" tall flush @close="emit('close')">
    <template #title>
      <h2 class="doc-title">{{ job.filename }}</h2>
      <p v-if="meta" class="doc-meta mono">{{ meta }}</p>
    </template>

    <!-- A segmented pair, not two loose buttons: they are two views of one thing, and the
         shared border is what says so. -->
    <template #actions>
      <div class="tabs" role="tablist" :aria-label="t('jobs.resultViews')">
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
          {{ t(`jobs.view.${view}`) }}
        </button>
      </div>
    </template>

    <div class="body">
      <UiBanner v-if="job.error" class="state" tone="error">{{ job.error }}</UiBanner>
      <UiBanner v-else-if="errorMessage" class="state" tone="error">{{ errorMessage }}</UiBanner>
      <UiSkeleton v-else-if="pending" class="state" :rows="5" />

      <pre v-else-if="tab === 'json'" class="json mono">{{ json }}</pre>

      <UiEmptyState
        v-else-if="!pages.length"
        class="state"
        :title="t('jobs.resultEmpty')"
        :body="t('jobs.resultEmptyBody')"
      />

      <div v-else class="markdown" :class="{ degraded: failedPages.length > 0 }">
        <!-- Spans both columns: it is a fact about the document, not about one page. -->
        <UiBanner v-if="failedPages.length" class="degraded-note" tone="error">
          {{
            t('jobs.resultDegraded', {
              count: failedPages.length,
              pages: failedPages.map((entry) => entry.page).join(', '),
            })
          }}
        </UiBanner>

        <nav class="page-rail" :aria-label="t('jobs.pagesLabel')">
          <p class="eyebrow sm page-rail-label">{{ t('jobs.pagesLabel') }}</p>
          <button
            v-for="page in pages"
            :key="page.page"
            type="button"
            class="page-button"
            :class="{ active: page.page === activePage }"
            :aria-current="page.page === activePage ? 'true' : undefined"
            @click="goToPage(page.page)"
          >
            <span>{{ t('jobs.pageN', { page: page.page }) }}</span>
            <span v-if="page.figureCount" class="page-figures">
              {{ t('jobs.figureCount', { count: page.figureCount }) }}
            </span>
          </button>
        </nav>

        <div ref="scroller" class="document" @scroll="onScroll">
          <section
            v-for="page in pages"
            :key="page.page"
            :ref="(el) => registerSection(page.page, el)"
            class="page"
          >
            <p class="eyebrow sm page-marker" :class="{ current: page.page === activePage }">
              {{ t('jobs.pageN', { page: page.page }) }}
            </p>
            <article class="prose">
              <template v-for="(block, index) in page.blocks" :key="index">
                <h3 v-if="block.kind === 'h2'" class="md-h2">{{ block.text }}</h3>
                <h4 v-else-if="block.kind === 'h3'" class="md-h3">{{ block.text }}</h4>
                <p v-else-if="block.kind === 'p'" class="md-p">{{ block.text }}</p>

                <component
                  :is="block.ordered ? 'ol' : 'ul'"
                  v-else-if="block.kind === 'list'"
                  class="md-list"
                >
                  <li v-for="(item, itemIndex) in block.items" :key="itemIndex">{{ item }}</li>
                </component>

                <table v-else-if="block.kind === 'table'" class="md-table">
                  <thead>
                    <tr>
                      <th v-for="(cell, column) in block.header" :key="column" scope="col">
                        {{ cell }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
                      <td v-for="(cell, column) in row" :key="column">{{ cell }}</td>
                    </tr>
                  </tbody>
                </table>

                <!-- The crop itself does not exist yet: the pipeline stores the bbox, not a
                     cropped image (docs/web.md § Result viewer). The frame, the caption and
                     the sizing are the ones an <img> will take when it does. -->
                <figure v-else class="md-figure">
                  <div class="figure-frame">
                    <UiIcon name="scan-text" />
                    <span>{{ t('jobs.figurePending') }}</span>
                  </div>
                  <figcaption class="figure-caption mono">
                    <span>{{ block.caption || block.id }}</span>
                    <span>{{ formatBbox(block.bbox) }}</span>
                  </figcaption>
                </figure>
              </template>
            </article>
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

.tabs {
  display: inline-flex;
  flex-shrink: 0;
  border: 1px solid var(--edge);
  border-radius: var(--radius);
  overflow: hidden;
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

.degraded-note {
  grid-column: 1 / -1;
  border-inline: none;
  border-top: none;
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

.md-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
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
