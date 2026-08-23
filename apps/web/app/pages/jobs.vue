<script setup lang="ts">
import { getJobResult, listJobs, type JobResult, type JobStatus, type JobSummary } from '~/lib/api'
import type { TableColumn } from '~/lib/table'

definePageMeta({ middleware: 'authed' })

const JOB_LIMIT = 50

const { t, locale } = useI18n()
useHead(() => ({ title: t('jobs.headTitle') }))

const { data, pending, errorMessage, refresh } = useAuthedData(() => listJobs(JOB_LIMIT))
const { resolve } = useApiError()

/** The row whose result is open. A parsed document is a document, so it gets a dialog rather
    than a row that grows to twenty lines and pushes every other job off the screen. */
const openJob = ref<JobSummary | null>(null)
const results = reactive(new Map<string, JobResult>())
const resultErrors = reactive(new Map<string, string>())
/**
 * Job ids with a result request in flight. A set, not one shared "currently loading" id:
 * the viewer can be closed and reopened on a different job while the first request is
 * still running, and a single id cannot say which of them is pending. It also makes a
 * reopen cheap — the job is already being fetched, so no second request is started.
 */
const inFlight = reactive(new Set<string>())

/** Never color alone: each tone ships with the status word beside it. Succeeded is the
    accent — a finished job is the data this page is about — and running sits outside the
    danger family, because a job in flight is not a problem. */
const STATUS_TONE: Record<JobStatus, 'neutral' | 'info' | 'ok' | 'danger'> = {
  queued: 'neutral',
  running: 'info',
  succeeded: 'ok',
  failed: 'danger',
}

const STATUSES = ['succeeded', 'running', 'queued', 'failed'] as const

/** The rail's tally. Every status is listed even at zero: an absent row would read as a
    status this account cannot produce. */
const tally = computed(() =>
  STATUSES.map((status) => ({
    status,
    tone: STATUS_TONE[status],
    count: data.value?.jobs.filter((job) => job.status === status).length ?? 0,
  })),
)

/**
 * `MMM d, h:mm AM` — the shorter form, because the year is redundant on a job from this
 * year and was the widest thing in the column.
 *
 * It comes back for anything older. "Last 50 jobs" is a count, not a window: an account
 * that parses a document a year would otherwise show two jobs from different years with
 * identical timestamps.
 */
function shortDateTime(iso: string): string {
  const at = new Date(iso)
  return new Intl.DateTimeFormat(locale.value, {
    year: at.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(at)
}

const columns = computed<TableColumn<JobSummary>[]>(() => [
  { key: 'file', header: t('jobs.columnFile') },
  { key: 'status', header: t('jobs.columnStatus') },
  { key: 'model', header: t('jobs.columnModel') },
  { key: 'pages', header: t('jobs.columnPages'), numeric: true, width: '80px' },
  { key: 'created', header: t('jobs.columnCreated'), numeric: true },
])

async function showResult(job: JobSummary) {
  openJob.value = job
  if (results.has(job.job_id) || inFlight.has(job.job_id)) {
    return
  }
  inFlight.add(job.job_id)
  resultErrors.delete(job.job_id)
  try {
    results.set(job.job_id, await getJobResult(job.job_id))
  } catch (error) {
    resultErrors.set(job.job_id, await resolve(error))
  } finally {
    inFlight.delete(job.job_id)
  }
}
</script>

<template>
  <UiScreen>
    <UiRail>
      <UiPageHeader :eyebrow="t('jobs.recent', { limit: JOB_LIMIT })" :title="t('jobs.headTitle')" />

      <dl v-if="data" class="tally">
        <div v-for="row in tally" :key="row.status" class="tally-row" :class="row.tone">
          <dt>
            <span class="dot" aria-hidden="true" />
            {{ t(`jobs.status.${row.status}`) }}
          </dt>
          <dd class="tabular">{{ row.count }}</dd>
        </div>
      </dl>
    </UiRail>

    <UiRegion>
      <!--
        One panel filling the region, rows scrolling inside it under a sticky header, so the
        page itself never grows past the viewport.

        A failed refresh keeps the rows it already has — the banner says what went wrong, and
        blanking the page on top of that helps nobody.
      -->
      <UiPanel :title="t('jobs.listTitle')" lead>
        <template #meta>
          <span>{{ t('jobs.newestFirst') }}</span>
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

          <!-- Not just `!data`: a failed first load leaves data null with `pending` back to
             false, and an animated skeleton beside a terminal error says the page is still
             working when it has stopped. -->
        <UiSkeleton v-if="!data && !errorMessage" class="state" :rows="6" />

        <UiEmptyState
          v-else-if="data && !data.jobs.length"
          :title="t('jobs.empty')"
          :body="t('jobs.emptyBody')"
        />

        <UiDataTable
          v-else-if="data"
          :columns="columns"
          :rows="data.jobs"
          :row-key="(job) => job.job_id"
          :caption="t('jobs.listTitle')"
        >
          <!-- The filename is the affordance: it is the row's identity and the thing worth
               opening, so it carries the underline rather than a separate icon button at the
               far end of the row. -->
          <template #cell-file="{ row }">
            <button
              type="button"
              class="filename cell-block"
              :class="{ failed: row.status === 'failed' }"
              :title="row.filename"
              @click="showResult(row)"
            >
              {{ row.filename }}
            </button>
          </template>
          <template #cell-status="{ row }">
            <UiStatusDot :tone="STATUS_TONE[row.status]" :label="t(`jobs.status.${row.status}`)" />
          </template>
          <template #cell-model="{ row }">
            <span class="model mono">{{ row.model }}</span>
          </template>
          <template #cell-pages="{ row }">
            {{ row.page_count ? `${row.pages_done}/${row.page_count}` : row.pages_done }}
          </template>
          <template #cell-created="{ row }">
            <span class="created">{{ shortDateTime(row.created_at) }}</span>
          </template>
        </UiDataTable>
      </UiPanel>
    </UiRegion>
    <ResultViewer
      v-if="openJob"
      :job="openJob"
      :result="results.get(openJob.job_id) ?? null"
      :pending="inFlight.has(openJob.job_id)"
      :error-message="resultErrors.get(openJob.job_id) ?? null"
      @close="openJob = null"
    />
  </UiScreen>
</template>

<style scoped>
.tally {
  display: flex;
  flex-direction: column;
  margin: 0;
}

.tally-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) 0;
  border-top: 1px solid var(--line);
}

.tally-row:last-child {
  border-bottom: 1px solid var(--line);
}

.tally-row dt {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--ink);
}

.tally-row dd {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--display-sm);
  font-weight: var(--weight-semibold);
}

.dot {
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--queued);
}

.tally-row.ok .dot {
  background: var(--accent);
}

.tally-row.info .dot {
  background: var(--running);
}

/* Failed is the one state a reader scans for, so it colours the word and the figure too,
   not only the dot. */
.tally-row.danger .dot {
  background: var(--danger);
}

.tally-row.danger dt,
.tally-row.danger dd {
  color: var(--danger);
}

.state {
  margin-top: var(--space-4);
}

/* A link that happens to be a button: it opens a dialog, so it is a button, but it reads as
   the filename it is with the underline this design gives a link. */
.filename {
  padding: 0;
  border: none;
  border-bottom: 1px solid var(--edge);
  background: none;
  color: var(--ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    color var(--duration-fast) var(--ease),
    border-color var(--duration-fast) var(--ease);
}

.filename:hover {
  color: var(--accent);
  border-color: var(--accent);
}

.filename.failed {
  color: var(--danger);
  border-color: var(--danger-edge);
}

.model {
  color: var(--muted);
  white-space: nowrap;
}

.created {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
</style>
