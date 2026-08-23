<script setup lang="ts">
import { getUsage } from '~/lib/api'
import { formatCost, formatCount, formatDay } from '~/lib/format'
import type { TableColumn } from '~/lib/table'
import { summarizeUsage, type UsageRow } from '~/lib/usage'

definePageMeta({ middleware: 'authed' })

const USAGE_DAYS = 30

const { t, locale } = useI18n()

const { data, pending, errorMessage, refresh } = useAuthedData(() => getUsage(USAGE_DAYS))
const summary = computed(() => (data.value ? summarizeUsage(data.value) : null))

/**
 * The per-day table. The meter column carries no visible header — it ranks the cost column
 * beside it — but keeps an accessible name, since a blank `<th>` is an unnamed column to a
 * screen reader reading the table's structure.
 */
const dayColumns = computed<TableColumn<UsageRow>[]>(() => [
  { key: 'label', header: t('dashboard.columnDate') },
  { key: 'share', header: '', srHeader: t('dashboard.columnShare'), width: '120px' },
  { key: 'cost', header: t('dashboard.columnCost'), numeric: true },
  { key: 'prompt', header: t('dashboard.columnPrompt'), numeric: true },
  { key: 'completion', header: t('dashboard.columnCompletion'), numeric: true },
])
</script>

<template>
  <UiScreen>
    <UiRail>
      <UiPageHeader :eyebrow="t('dashboard.period', { days: USAGE_DAYS })" :title="t('dashboard.headTitle')" />

      <!-- Three figures on rules, not in boxes. Cost is the accent and the largest of them:
           it is the number this page exists to answer. -->
      <dl v-if="summary" class="totals">
        <div class="total">
          <dt class="eyebrow">{{ t('dashboard.totalCost') }}</dt>
          <dd class="figure cost tabular">{{ formatCost(summary.totalCost, locale) }}</dd>
        </div>
        <div class="total">
          <dt class="eyebrow">{{ t('dashboard.totalPromptTokens') }}</dt>
          <dd class="figure tabular">{{ formatCount(summary.totalPromptTokens, locale) }}</dd>
        </div>
        <div class="total last">
          <dt class="eyebrow">{{ t('dashboard.totalCompletionTokens') }}</dt>
          <dd class="figure tabular">{{ formatCount(summary.totalCompletionTokens, locale) }}</dd>
        </div>
      </dl>
    </UiRail>

    <!-- Two independent collections, so two panels, each scrolling its own rows: one
         scrollbar dragging both would make the reader scroll past the days to reach the
         models. -->
    <UiRegion split>
      <UiPanel :title="t('dashboard.perDay')" lead>
        <!-- Refresh lives in the header of the panel it reloads: the design has no sticky
             top bar for it to sit in, and both tables come from the one request. -->
        <template #meta>
          <span v-if="summary && !summary.isEmpty">
            {{ t('dashboard.daysRecorded', { count: summary.days.length }) }}
          </span>
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

        <!-- A failed refresh keeps the figures it already has: the banner says what went
             wrong, and blanking the page on top of that helps nobody. -->
        <UiBanner v-if="errorMessage" tone="error">{{ errorMessage }}</UiBanner>

        <UiSkeleton v-if="!summary && !errorMessage" :rows="4" />

        <UiEmptyState
          v-else-if="summary?.isEmpty"
          :title="t('dashboard.empty')"
          :body="t('dashboard.emptyBody')"
        />

        <UiDataTable
          v-else-if="summary"
          :columns="dayColumns"
          :rows="summary.days"
          :row-key="(row) => row.label"
          :caption="t('dashboard.perDay')"
          density="tight"
        >
          <template #cell-label="{ row }">{{ formatDay(row.label, locale) }}</template>
          <template #cell-share="{ row }">
            <UiUsageBar :share="row.costShare" :label="formatDay(row.label, locale)" />
          </template>
          <template #cell-cost="{ row }">{{ formatCost(row.cost, locale) }}</template>
          <template #cell-prompt="{ row }">{{ formatCount(row.promptTokens, locale) }}</template>
          <template #cell-completion="{ row }">
            {{ formatCount(row.completionTokens, locale) }}
          </template>
        </UiDataTable>
      </UiPanel>

      <!-- Not a table: a model id is long and its two token figures are secondary to its
           cost, so each model gets a small block of its own instead of five columns whose
           first one would set the width of all of them. -->
      <UiPanel :title="t('dashboard.perModel')" sunken divided>
        <template v-if="summary?.models.length" #meta>
          {{ t('dashboard.modelsRecorded', { count: summary.models.length }) }}
        </template>

        <ul v-if="summary?.models.length" class="models">
          <li v-for="row in summary.models" :key="row.label" class="model">
            <div class="model-main">
              <!-- Ellipsized to keep the row rhythm, but never lost: two models sharing a
                 long provider prefix must stay tellable apart, and this figure is what
                 attributes the cost beside it. -->
            <p class="model-id mono" :title="row.label">{{ row.label }}</p>
              <UiUsageBar :share="row.costShare" :label="row.label" />
              <p class="model-tokens tabular">
                {{
                  t('dashboard.modelTokens', {
                    prompt: formatCount(row.promptTokens, locale),
                    completion: formatCount(row.completionTokens, locale),
                  })
                }}
              </p>
            </div>
            <p class="model-cost tabular">{{ formatCost(row.cost, locale) }}</p>
          </li>
        </ul>
      </UiPanel>
    </UiRegion>
  </UiScreen>
</template>

<style scoped>
/* Each figure is a band between rules — the last one closes the stack so it does not trail
   off into the rail's whitespace. */
.totals {
  display: flex;
  flex-direction: column;
  margin: 0;
}

.total {
  padding: var(--space-5) 0;
  border-top: 1px solid var(--line);
}

.total.last {
  border-bottom: 1px solid var(--line);
}

.figure {
  margin: var(--space-2) 0 0;
  font-family: var(--font-display);
  font-size: var(--display-lg);
  font-weight: var(--weight-semibold);
  letter-spacing: var(--tracking-tight);
  line-height: 1.1;
}

/* Cost is data, and the largest thing in the rail. */
.figure.cost {
  font-size: var(--display-2xl);
  color: var(--accent);
}

.models {
  list-style: none;
  margin: 0;
  padding: 0;
}

.model {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 96px;
  align-items: baseline;
  gap: var(--space-4);
  padding: var(--space-4) 0;
  border-top: 1px solid var(--hair);
}

.model-main {
  min-width: 0;
}

.model-id {
  margin-bottom: var(--space-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink);
}

.model-tokens {
  margin-top: var(--space-2);
  font-size: var(--text-2xs);
  color: var(--faint);
}

.model-cost {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--display-sm);
  font-weight: var(--weight-semibold);
  text-align: right;
}
</style>
