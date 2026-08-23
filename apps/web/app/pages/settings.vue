<script setup lang="ts">
import {
  createConnection,
  createPrompt,
  deleteConnection,
  deleteOpenRouterKey,
  deletePrompt,
  listConnectionModels,
  listConnections,
  listModels,
  listProfiles,
  listPrompts,
  putOpenRouterKey,
  putSettings,
  updateConnection,
  updatePrompt,
  type ConnectionModel,
} from '~/lib/api'
import { formatDateTime } from '~/lib/format'
import { modelLabel, sortModelsRecommendedFirst } from '~/lib/models'

definePageMeta({ middleware: 'authed' })

const { t, locale, locales } = useI18n()
const switchLocalePath = useSwitchLocalePath()
useHead(() => ({ title: t('settings.headTitle') }))

const auth = useAuth()
const { resolve } = useApiError()

const { data: catalog, errorMessage: catalogError } = useAuthedData(async () => {
  const [models, profiles] = await Promise.all([listModels(), listProfiles()])
  return { models: sortModelsRecommendedFirst(models.data), profiles: profiles.data }
})

const recommendedModels = computed(() => catalog.value?.models.filter((model) => model.recommended) ?? [])
const otherModels = computed(() => catalog.value?.models.filter((model) => !model.recommended) ?? [])

// --- providers: OpenRouter + the user's connections -------------------------

const {
  data: connectionsData,
  errorMessage: connectionsError,
  refresh: refreshConnections,
} = useAuthedData(() => listConnections())
const connections = computed(() => connectionsData.value?.connections ?? [])

/** '' is the built-in OpenRouter; otherwise a connection id as the `<select>` string. */
const providerChoice = ref('')
const providerPending = ref(false)
const providerError = ref<string | null>(null)
const providerMessage = ref<string | null>(null)

watch(
  () => auth.me.value?.settings.default_connection_id,
  (id) => {
    providerChoice.value = id == null ? '' : String(id)
  },
  { immediate: true },
)

const selectedConnection = computed(
  () => connections.value.find((row) => String(row.id) === providerChoice.value) ?? null,
)

/** A custom connection is selected but the connections list has not (yet) delivered its
    row — a failed list must not be mistaken for "OpenRouter is active", so the key and
    model controls hold back until the selection resolves. */
const providerUnresolved = computed(
  () => providerChoice.value !== '' && selectedConnection.value === null,
)

/** Provider and model updates write overlapping settings columns, so the two pickers
    disable together — concurrent PUTs could otherwise pair provider B with a model
    picked from provider A's catalog. The provider picker also waits for the connections
    list: switching against an unloaded list would be flying blind. */
const targetBusy = computed(
  () => providerPending.value || defaultsPending.value || !connectionsData.value,
)

/** Switching providers also clears the model/profile pair: it belonged to the old catalog. */
async function applyProvider(value: string) {
  const previous = providerChoice.value
  providerChoice.value = value
  providerPending.value = true
  providerError.value = null
  providerMessage.value = null
  try {
    await putSettings({
      default_connection_id: value ? Number(value) : null,
      default_model: null,
      default_profile: null,
    })
    providerMessage.value = t('settings.providerSaved')
    await auth.refresh()
  } catch (error) {
    providerChoice.value = previous
    providerError.value = await resolve(error)
  } finally {
    providerPending.value = false
  }
}

// --- connection add/edit dialog ---------------------------------------------

/**
 * One dialog, three entry points. The pencil beside the provider picker is
 * context-sensitive: on a custom connection it edits that connection, and on OpenRouter —
 * which has no name or URL to edit — it opens the same dialog as a key-only form. Two
 * separate dialogs for "change the credential of the selected provider" would be the same
 * dialog twice.
 */
const connectionModal = ref<null | { mode: 'create' } | { mode: 'edit'; id: number } | { mode: 'key' }>(null)
const connName = ref('')
const connUrl = ref('')
const connKey = ref('')
const connPending = ref(false)
const connError = ref<string | null>(null)
const confirmingConnectionDelete = ref(false)

function openConnectionCreate() {
  connName.value = ''
  connUrl.value = ''
  connKey.value = ''
  connError.value = null
  connectionModal.value = { mode: 'create' }
}

/** The pencil: edits the selected connection, or the OpenRouter key when that is what is
 *  selected. OpenRouter is `providerChoice === ''` — a *missing* row means the connections
 *  list has not answered yet, and treating that as OpenRouter would open the key dialog
 *  over someone's selected connection. The button is disabled in that window anyway; this
 *  is the second lock. */
function openProviderEdit() {
  connName.value = ''
  connUrl.value = ''
  connKey.value = ''
  connError.value = null

  if (providerChoice.value === '') {
    keyInput.value = ''
    keyError.value = null
    connectionModal.value = { mode: 'key' }
    return
  }
  const row = selectedConnection.value
  if (!row) {
    return
  }
  connName.value = row.name
  connUrl.value = row.base_url
  connectionModal.value = { mode: 'edit', id: row.id }
}

/**
 * Closes the dialog and drops every draft it held — the key above all.
 *
 * The key-only mode edits the same `keyInput` the always-mounted API Key form below binds
 * to, so a cancelled dialog would otherwise leave a typed credential sitting in a form the
 * user can no longer see themselves having filled, one Save away from being submitted.
 * Every close path goes through here: the button, the overlay, and Escape.
 */
function closeConnectionModal() {
  connectionModal.value = null
  connName.value = ''
  connUrl.value = ''
  connKey.value = ''
  connError.value = null
  keyInput.value = ''
  keyError.value = null
}

/**
 * What Escape, the overlay and Cancel do — as opposed to `closeConnectionModal`, which is
 * how a *successful* save puts the dialog away.
 *
 * A save in flight refuses dismissal: those two paths bypass the disabled Cancel button,
 * and a dialog dismissed mid-save can be reopened on a fresh draft that the original
 * request's completion would then close, wiping a key the user had just typed.
 */
function dismissConnectionModal() {
  if (connPending.value || keyPending.value) {
    return
  }
  closeConnectionModal()
}

async function submitConnection() {
  const modal = connectionModal.value
  if (!modal || connPending.value) {
    return
  }
  // The key-only mode writes the OpenRouter key, which has its own endpoint and its own
  // validation — it is the same dialog, not the same request.
  if (modal.mode === 'key') {
    await saveOpenRouterKey(closeConnectionModal)
    return
  }
  connPending.value = true
  connError.value = null
  try {
    if (modal.mode === 'create') {
      const created = await createConnection({
        name: connName.value.trim(),
        base_url: connUrl.value.trim(),
        api_key: connKey.value.trim(),
      })
      closeConnectionModal()
      await refreshConnections()
      // A freshly added provider is what the user came to use — select it right away.
      await applyProvider(String(created.id))
    } else {
      await updateConnection(modal.id, {
        name: connName.value.trim(),
        base_url: connUrl.value.trim(),
        ...(connKey.value.trim() ? { api_key: connKey.value.trim() } : {}),
      })
      closeConnectionModal()
      await refreshConnections()
      connectionModels.value = null
      await loadConnectionModels()
    }
    providerMessage.value = t('settings.connectionSaved')
  } catch (error) {
    connError.value = await resolve(error)
  } finally {
    connPending.value = false
  }
}

async function removeConnection() {
  const row = selectedConnection.value
  if (!row) {
    return
  }
  connPending.value = true
  providerError.value = null
  try {
    await deleteConnection(row.id)
    confirmingConnectionDelete.value = false
    await Promise.all([refreshConnections(), auth.refresh()])
  } catch (error) {
    providerError.value = await resolve(error)
  } finally {
    connPending.value = false
  }
}

// --- model choice on a custom connection ------------------------------------

const connectionModels = ref<ConnectionModel[] | null>(null)
const connectionModelsPending = ref(false)
const connectionModelsError = ref<string | null>(null)
/** Request generation: an id alone cannot tell a pre-edit request from the reload after
    an edit of the same connection, so every load bumps this and stale answers drop. */
let connectionModelsSeq = 0

async function loadConnectionModels() {
  const row = selectedConnection.value
  if (!row) {
    connectionModels.value = null
    return
  }
  const requestedId = row.id
  const seq = ++connectionModelsSeq
  connectionModelsPending.value = true
  connectionModelsError.value = null
  try {
    const data = (await listConnectionModels(requestedId)).data
    // Only the newest request for the still-selected connection may fill the picker —
    // a slow answer from before a switch or an edit would show the wrong catalog.
    if (seq === connectionModelsSeq && selectedConnection.value?.id === requestedId) {
      connectionModels.value = data
    }
  } catch (error) {
    if (seq === connectionModelsSeq && selectedConnection.value?.id === requestedId) {
      connectionModelsError.value = await resolve(error)
    }
  } finally {
    if (seq === connectionModelsSeq && selectedConnection.value?.id === requestedId) {
      connectionModelsPending.value = false
    }
  }
}

watch(selectedConnection, (row, previous) => {
  if (row?.id !== previous?.id) {
    connectionModels.value = null
    if (row) {
      loadConnectionModels()
    }
  }
})

const connectionModelChoice = ref('')
watch(
  [() => auth.me.value?.settings.default_model, selectedConnection],
  ([model, row]) => {
    connectionModelChoice.value = row ? (model ?? '') : ''
  },
  { immediate: true },
)

const defaultsPending = ref(false)
const defaultsError = ref<string | null>(null)
const defaultsMessage = ref<string | null>(null)

async function applyConnectionModel(value: string) {
  const previous = connectionModelChoice.value
  connectionModelChoice.value = value
  defaultsPending.value = true
  defaultsError.value = null
  defaultsMessage.value = null
  try {
    await putSettings({ default_model: value || null, default_profile: null })
    defaultsMessage.value = t('settings.saved')
    await auth.refresh()
  } catch (error) {
    connectionModelChoice.value = previous
    defaultsError.value = await resolve(error)
  } finally {
    defaultsPending.value = false
  }
}

// --- model choice on OpenRouter (profiles + custom model) -------------------

/**
 * One choice, not two: a parsing default is a model *and* the format it is prompted for,
 * so the dropdown lists preset profiles (which pair them) plus at most one custom model.
 * Encoded as `profile:<id>` / `model:<id>` / '' so the `<select>` can carry either kind.
 */
const selection = ref('')
/** The custom entry the dropdown shows — the stored default, or one just picked. */
const customModel = ref<string | null>(null)

const addingCustom = ref(false)
const customChoice = ref('')

watch(
  () => auth.me.value?.settings,
  (settings) => {
    if (settings?.default_connection_id != null) {
      return
    }
    const profile = settings?.default_profile
    const model = settings?.default_model
    selection.value = profile ? `profile:${profile}` : model ? `model:${model}` : ''
    if (model) {
      customModel.value = model
    }
  },
  { immediate: true },
)

const customOptionLabel = computed(() => {
  if (!customModel.value) {
    return ''
  }
  const entry = catalog.value?.models.find((model) => model.id === customModel.value)
  return entry ? modelLabel(entry) : customModel.value
})

/** Saves on selection, reverting the dropdown when the server refuses — a picker whose
    display disagrees with the stored default would be lying. */
async function applySelection(value: string) {
  const previous = selection.value
  selection.value = value
  defaultsPending.value = true
  defaultsError.value = null
  defaultsMessage.value = null
  try {
    await putSettings({
      default_model: value.startsWith('model:') ? value.slice('model:'.length) : null,
      default_profile: value.startsWith('profile:') ? value.slice('profile:'.length) : null,
    })
    defaultsMessage.value = t('settings.saved')
    await auth.refresh()
  } catch (error) {
    selection.value = previous
    defaultsError.value = await resolve(error)
  } finally {
    defaultsPending.value = false
  }
}

function openCustom() {
  customChoice.value = customModel.value ?? ''
  addingCustom.value = true
}

async function submitCustom() {
  const choice = customChoice.value
  if (!choice || defaultsPending.value) {
    return
  }
  customModel.value = choice
  addingCustom.value = false
  await applySelection(`model:${choice}`)
}

// --- OpenRouter key ---------------------------------------------------------

const openrouterKey = computed(() => auth.me.value?.openrouter_key ?? null)
const keyInput = ref('')
const keyPending = ref(false)
const keyError = ref<string | null>(null)
const keyMessage = ref<string | null>(null)
const confirmingDelete = ref(false)

/**
 * Saves the stored OpenRouter key. `onSaved` is what the key-only dialog passes to close
 * itself, so the dialog stays open — with the error shown in it — when the backend refuses
 * the key.
 */
async function saveOpenRouterKey(onSaved?: () => void) {
  const candidate = keyInput.value.trim()
  if (!candidate || keyPending.value) {
    return
  }
  keyPending.value = true
  keyError.value = null
  connError.value = null
  keyMessage.value = null
  let saved = false
  try {
    await putOpenRouterKey(candidate)
    keyInput.value = ''
    keyMessage.value = t('settings.openrouterSaved')
    await auth.refresh()
    saved = true
  } catch (error) {
    const message = await resolve(error)
    keyError.value = message
    connError.value = message
  } finally {
    keyPending.value = false
  }
  // After the flag clears, never inside the `try`: the callback closes the dialog, and a
  // dialog cannot be put away while its own save still reads as pending.
  if (saved) {
    onSaved?.()
  }
}

async function removeOpenRouterKey() {
  keyPending.value = true
  keyError.value = null
  keyMessage.value = null
  try {
    await deleteOpenRouterKey()
    confirmingDelete.value = false
    await auth.refresh()
  } catch (error) {
    keyError.value = await resolve(error)
  } finally {
    keyPending.value = false
  }
}

// --- the rail's live summary -------------------------------------------------

/**
 * What is in effect right now, as three lines in the rail. It reads the same state the
 * controls on the right write, so it changes as they do — that is the point of putting it
 * opposite them rather than under each group as a "currently: …" line.
 */
const summaryProvider = computed(() => {
  // Same rule as the controls: a *missing* row is a connections list that has not answered,
  // not OpenRouter. Reporting configuration the backend never returned is exactly the
  // fabrication the rail is here to avoid.
  if (providerUnresolved.value) {
    return t('common.loading')
  }
  return selectedConnection.value?.name ?? t('settings.providerOpenRouter')
})

const summaryModel = computed(() => {
  if (providerUnresolved.value) {
    return t('common.loading')
  }
  if (selectedConnection.value) {
    return connectionModelChoice.value || t('common.notSet')
  }
  if (selection.value.startsWith('model:')) {
    return selection.value.slice('model:'.length)
  }
  if (selection.value.startsWith('profile:')) {
    const id = selection.value.slice('profile:'.length)
    const profile = catalog.value?.profiles.find((entry) => entry.id === id)
    if (profile) {
      return profile.model ?? profile.name
    }
    // A stored profile the catalog has not described yet. "Not set" here would be the same
    // fabrication as calling an unresolved provider OpenRouter: a choice *is* stored.
    return t('common.loading')
  }
  return t('common.notSet')
})

// --- prompt presets ---------------------------------------------------------

const {
  data: promptsData,
  errorMessage: promptsError,
  refresh: refreshPrompts,
} = useAuthedData(() => listPrompts())
const prompts = computed(() => promptsData.value?.prompts ?? [])

/** What "default" means right now — shown as the starting point for a new prompt. */
const defaultPrompt = computed(() => auth.me.value?.defaults.system_prompt ?? '')

/** '' is the shipped default; otherwise a preset id as the `<select>` string. */
const promptChoice = ref('')
const promptPending = ref(false)
const promptError = ref<string | null>(null)
const promptMessage = ref<string | null>(null)
const confirmingPromptDelete = ref(false)

watch(
  () => auth.me.value?.settings.prompt_preset_id,
  (id) => {
    promptChoice.value = id == null ? '' : String(id)
  },
  { immediate: true },
)

const selectedPrompt = computed(
  () => prompts.value.find((row) => String(row.id) === promptChoice.value) ?? null,
)

/** Same rule again: a stored preset whose row has not arrived is unresolved, not the
 *  default prompt. */
const promptUnresolved = computed(
  () => promptChoice.value !== '' && selectedPrompt.value === null,
)

const summaryPrompt = computed(() => {
  if (promptUnresolved.value) {
    return t('common.loading')
  }
  return selectedPrompt.value?.name ?? t('settings.promptDefaultOption')
})

async function applyPromptChoice(value: string) {
  const previous = promptChoice.value
  promptChoice.value = value
  promptPending.value = true
  promptError.value = null
  promptMessage.value = null
  try {
    await putSettings({ prompt_preset_id: value ? Number(value) : null })
    promptMessage.value = t('settings.promptSelected')
    await auth.refresh()
  } catch (error) {
    promptChoice.value = previous
    promptError.value = await resolve(error)
  } finally {
    promptPending.value = false
  }
}

const promptModal = ref<null | { mode: 'create' } | { mode: 'edit'; id: number }>(null)
const promptName = ref('')
const promptText = ref('')
const promptModalPending = ref(false)
const promptModalError = ref<string | null>(null)

function openPromptCreate() {
  promptName.value = ''
  // The shipped default is the honest starting point for a custom prompt.
  promptText.value = defaultPrompt.value
  promptModalError.value = null
  promptModal.value = { mode: 'create' }
}

function openPromptEdit() {
  const row = selectedPrompt.value
  if (!row) {
    return
  }
  promptName.value = row.name
  promptText.value = row.text
  promptModalError.value = null
  promptModal.value = { mode: 'edit', id: row.id }
}

async function submitPrompt() {
  const modal = promptModal.value
  if (!modal || promptModalPending.value) {
    return
  }
  promptModalPending.value = true
  promptModalError.value = null
  try {
    if (modal.mode === 'create') {
      const created = await createPrompt({
        name: promptName.value.trim(),
        text: promptText.value.trim(),
      })
      promptModal.value = null
      await refreshPrompts()
      await applyPromptChoice(String(created.id))
    } else {
      await updatePrompt(modal.id, {
        name: promptName.value.trim(),
        text: promptText.value.trim(),
      })
      promptModal.value = null
      await refreshPrompts()
    }
    promptMessage.value = t('settings.promptSaved')
  } catch (error) {
    promptModalError.value = await resolve(error)
  } finally {
    promptModalPending.value = false
  }
}

async function removePrompt() {
  const row = selectedPrompt.value
  if (!row) {
    return
  }
  promptPending.value = true
  promptError.value = null
  try {
    await deletePrompt(row.id)
    confirmingPromptDelete.value = false
    await Promise.all([refreshPrompts(), auth.refresh()])
  } catch (error) {
    promptError.value = await resolve(error)
  } finally {
    promptPending.value = false
  }
}
</script>
<template>
  <UiScreen>
    <UiRail>
      <UiPageHeader :eyebrow="t('settings.eyebrow')" :title="t('settings.headTitle')" />

      <!-- What is in effect, opposite the controls that set it. It updates as they do. -->
      <dl class="summary">
        <div class="summary-row">
          <dt class="eyebrow">{{ t('settings.providerTitle') }}</dt>
          <dd>{{ summaryProvider }}</dd>
        </div>
        <div class="summary-row">
          <dt class="eyebrow">{{ t('settings.summaryModel') }}</dt>
          <dd class="mono">{{ summaryModel }}</dd>
        </div>
        <div class="summary-row last">
          <dt class="eyebrow">{{ t('settings.summaryPrompt') }}</dt>
          <dd>{{ summaryPrompt }}</dd>
        </div>
      </dl>
    </UiRail>

    <UiRegion>
      <UiPanel section>
        <div class="groups">
          <!-- Provider ------------------------------------------------------ -->
          <section class="group">
            <h2 class="group-title">{{ t('settings.providerTitle') }}</h2>

            <UiBanner v-if="connectionsError" class="group-banner" tone="error">
              {{ connectionsError }}
            </UiBanner>

            <div class="controls">
              <UiField v-slot="{ id }" class="grow" :label="t('settings.providerLabel')" label-hidden>
                <UiSelect
                  :id="id"
                  :model-value="providerChoice"
                  :disabled="targetBusy"
                  @update:model-value="applyProvider"
                >
                  <option value="">{{ t('settings.providerOpenRouter') }}</option>
                  <option v-for="row in connections" :key="row.id" :value="String(row.id)">
                    {{ row.name }}
                  </option>
                </UiSelect>
              </UiField>

              <!-- Kept on one line beside the picker: at a wider basis the two buttons wrap
                   onto a line of their own and stop reading as this control's actions. -->
              <div class="control-buttons">
                <UiButton
                  icon-only
                  :label="t('settings.addProvider')"
                  :disabled="providerPending"
                  @click="openConnectionCreate"
                >
                  <template #icon><UiIcon name="plus" /></template>
                </UiButton>
                <UiButton
                  icon-only
                  :label="
                    providerChoice === ''
                      ? t('settings.keyDialogTitle')
                      : t('settings.connectionEditTitle')
                  "
                  :disabled="providerPending || connPending || keyPending || providerUnresolved"
                  @click="openProviderEdit"
                >
                  <template #icon><UiIcon name="edit" /></template>
                </UiButton>
              </div>
            </div>

            <!-- A custom connection carries its own address, its own catalog and its own
                 deletion. None of that exists for OpenRouter. -->
            <template v-if="selectedConnection">
              <p class="state">
                {{
                  t('settings.connectionState', {
                    url: selectedConnection.base_url,
                    masked: selectedConnection.masked,
                  })
                }}
              </p>

              <!-- With no retry here a transient /models failure leaves the picker gone
                   for good: nothing else calls this until the selected connection changes,
                   and switching away clears the stored model. -->
              <UiBanner v-if="connectionModelsError" class="group-banner" tone="error">
                {{ connectionModelsError }}
                <template #actions>
                  <UiButton
                    size="sm"
                    :loading="connectionModelsPending"
                    @click="loadConnectionModels"
                  >
                    <template #icon><UiIcon name="refresh" /></template>
                    {{ t('common.retry') }}
                  </UiButton>
                </template>
              </UiBanner>
              <UiSkeleton v-if="connectionModelsPending && !connectionModels" :rows="1" />

              <div class="controls">
                <UiField
                  v-if="connectionModels"
                  v-slot="{ id }"
                  class="grow"
                  :label="t('settings.connectionModelLabel')"
                  label-hidden
                >
                  <UiSelect
                    :id="id"
                    :model-value="connectionModelChoice"
                    :disabled="targetBusy"
                    @update:model-value="applyConnectionModel"
                  >
                    <option value="">{{ t('common.notSet') }}</option>
                    <option v-for="model in connectionModels ?? []" :key="model.id" :value="model.id">
                      {{ model.name ? `${model.name} · ${model.id}` : model.id }}
                    </option>
                  </UiSelect>
                </UiField>
                <UiButton
                  v-if="connectionModels"
                  icon-only
                  :label="t('settings.connectionModelReload')"
                  :loading="connectionModelsPending"
                  @click="loadConnectionModels"
                >
                  <template #icon><UiIcon name="refresh" /></template>
                </UiButton>
                <UiButton
                  variant="danger"
                  :disabled="connPending"
                  @click="confirmingConnectionDelete = true"
                >
                  {{ t('settings.connectionDelete') }}
                </UiButton>
              </div>
            </template>

            <UiBanner v-if="providerError" class="group-banner" tone="error">{{ providerError }}</UiBanner>
            <UiBanner v-else-if="providerMessage" class="group-banner" tone="ok">{{ providerMessage }}</UiBanner>
          </section>

          <!-- API key — OpenRouter only. A connection's key lives in its dialog. --------- -->
          <section v-if="!selectedConnection && !providerUnresolved" class="group">
            <h2 class="group-title">{{ t('settings.keyDialogTitle') }}</h2>

            <!-- Only the stored state is worth a line. Absence explains itself: the field is
                 empty and asks to be filled. -->
            <p v-if="openrouterKey?.present && openrouterKey.updated_at" class="state">
              {{
                t('settings.openrouterStored', {
                  masked: openrouterKey.masked,
                  updated: formatDateTime(openrouterKey.updated_at, locale),
                })
              }}
            </p>

            <form class="controls" @submit.prevent="saveOpenRouterKey()">
              <UiField v-slot="{ id }" class="grow" :label="t('settings.openrouterLabel')">
                <UiTextInput
                  :id="id"
                  v-model="keyInput"
                  type="password"
                  autocomplete="off"
                  :placeholder="t('settings.openrouterPlaceholder')"
                  required
                />
              </UiField>
              <UiButton
                variant="primary"
                type="submit"
                :loading="keyPending"
                :disabled="!keyInput.trim()"
              >
                {{ t('common.save') }}
              </UiButton>
              <!-- Keeps its word: it destroys a credential the user has to fetch from
                   OpenRouter again, which is not something a bare glyph should be able to do. -->
              <UiButton
                v-if="openrouterKey?.present"
                variant="danger"
                :disabled="keyPending"
                @click="confirmingDelete = true"
              >
                {{ t('settings.openrouterDelete') }}
              </UiButton>
            </form>

            <UiBanner v-if="keyError" class="group-banner" tone="error">{{ keyError }}</UiBanner>
            <UiBanner v-else-if="keyMessage" class="group-banner" tone="ok">{{ keyMessage }}</UiBanner>
          </section>

          <!-- Parsing default — OpenRouter only, mirroring the mutual exclusivity between
               preset profiles and a connection's own model list. ------------------------- -->
          <section v-if="!selectedConnection && !providerUnresolved" class="group">
            <h2 class="group-title">{{ t('settings.defaultsTitle') }}</h2>

            <UiBanner v-if="catalogError" class="group-banner" tone="error">{{ catalogError }}</UiBanner>
            <UiSkeleton v-else-if="!catalog" :rows="1" />

            <div v-else class="controls">
              <UiField v-slot="{ id }" class="grow" :label="t('settings.defaultLabel')" label-hidden>
                <UiSelect
                  :id="id"
                  :model-value="selection"
                  :disabled="targetBusy"
                  @update:model-value="applySelection"
                >
                  <option value="">{{ t('common.notSet') }}</option>
                  <optgroup :label="t('settings.recommendedGroup')">
                    <option
                      v-for="profile in catalog.profiles"
                      :key="profile.id"
                      :value="`profile:${profile.id}`"
                      :disabled="!profile.available"
                    >
                      {{
                        profile.available
                          ? `${profile.name} · ${profile.model}`
                          : t('settings.profileUnavailable', { name: profile.name })
                      }}
                    </option>
                  </optgroup>
                  <optgroup v-if="customModel" :label="t('settings.customGroup')">
                    <option :value="`model:${customModel}`">{{ customOptionLabel }}</option>
                  </optgroup>
                </UiSelect>
              </UiField>

              <UiButton :disabled="defaultsPending" @click="openCustom">
                <template #icon><UiIcon name="plus" /></template>
                {{ t('settings.addCustom') }}
              </UiButton>
            </div>

            <UiBanner v-if="defaultsError" class="group-banner" tone="error">{{ defaultsError }}</UiBanner>
            <UiBanner v-else-if="defaultsMessage" class="group-banner" tone="ok">{{ defaultsMessage }}</UiBanner>
          </section>

          <!-- A selected connection whose row has not arrived (list failed or loading) must
               not fall through to the OpenRouter controls. -->
          <UiSkeleton v-if="providerUnresolved" :rows="2" />

          <!-- System prompt ------------------------------------------------- -->
          <section class="group">
            <h2 class="group-title">{{ t('settings.promptTitle') }}</h2>

            <UiBanner v-if="promptsError" class="group-banner" tone="error">{{ promptsError }}</UiBanner>

            <div class="controls">
              <UiField v-slot="{ id }" class="grow" :label="t('settings.promptLabel')" label-hidden>
                <UiSelect
                  :id="id"
                  :model-value="promptChoice"
                  :disabled="promptPending"
                  @update:model-value="applyPromptChoice"
                >
                  <option value="">{{ t('settings.promptDefaultOption') }}</option>
                  <option v-for="row in prompts" :key="row.id" :value="String(row.id)">
                    {{ row.name }}
                  </option>
                </UiSelect>
              </UiField>

              <UiButton :disabled="promptPending" @click="openPromptCreate">
                <template #icon><UiIcon name="plus" /></template>
                {{ t('settings.promptAdd') }}
              </UiButton>
              <UiButton
                v-if="selectedPrompt"
                icon-only
                :label="t('settings.promptEditTitle')"
                :disabled="promptPending"
                @click="openPromptEdit"
              >
                <template #icon><UiIcon name="edit" /></template>
              </UiButton>
              <UiButton
                v-if="selectedPrompt"
                variant="danger"
                :disabled="promptPending"
                @click="confirmingPromptDelete = true"
              >
                {{ t('settings.promptDelete') }}
              </UiButton>
            </div>

            <UiBanner v-if="promptError" class="group-banner" tone="error">{{ promptError }}</UiBanner>
            <UiBanner v-else-if="promptMessage" class="group-banner" tone="ok">{{ promptMessage }}</UiBanner>
          </section>

          <!-- Language --------------------------------------------------- -->
          <!--
            The signed-in home for the locale choice. The sign-in footer is where a visitor
            picks it, but that page is unreachable once you are in, and the shell's account
            popover — which used to carry this — is gone. Real links, since the locale lives
            in the URL and the choice should stay bookmarkable.
          -->
          <section class="group">
            <h2 class="group-title">{{ t('nav.language') }}</h2>
            <nav class="locales" :aria-label="t('nav.language')">
              <NuxtLink
                v-for="option in locales"
                :key="option.code"
                class="locale"
                :class="{ active: option.code === locale }"
                :to="switchLocalePath(option.code)"
                :aria-current="option.code === locale ? 'true' : undefined"
              >
                {{ option.name }}
              </NuxtLink>
            </nav>
          </section>
        </div>
      </UiPanel>
    </UiRegion>
    <!-- One dialog, three titles: a new connection, an existing one, or the OpenRouter key
         on its own. Name and Base URL only exist for a connection. -->
    <UiModal
      v-if="connectionModal"
      size="md"
      :title="
        connectionModal.mode === 'create'
          ? t('settings.connectionCreateTitle')
          : connectionModal.mode === 'edit'
            ? t('settings.connectionEditTitle')
            : t('settings.keyDialogTitle')
      "
      @close="dismissConnectionModal"
    >
      <form id="connection-form" class="modal-form" @submit.prevent="submitConnection">
        <template v-if="connectionModal.mode !== 'key'">
          <UiField v-slot="{ id }" :label="t('settings.connectionNameLabel')">
            <UiTextInput :id="id" v-model="connName" required />
          </UiField>
          <UiField v-slot="{ id }" :label="t('settings.connectionUrlLabel')">
            <UiTextInput
              :id="id"
              v-model="connUrl"
              :placeholder="t('settings.connectionUrlPlaceholder')"
              required
            />
          </UiField>
        </template>

        <UiField v-slot="{ id }" :label="t('settings.connectionKeyLabel')">
          <UiTextInput
            v-if="connectionModal.mode === 'key'"
            :id="id"
            v-model="keyInput"
            type="password"
            autocomplete="off"
            :placeholder="t('settings.openrouterPlaceholder')"
            required
          />
          <UiTextInput
            v-else
            :id="id"
            v-model="connKey"
            type="password"
            autocomplete="off"
            :required="connectionModal.mode === 'create'"
          />
        </UiField>

        <p v-if="connectionModal.mode === 'edit'" class="note">
          {{ t('settings.connectionKeyKeepNote') }}
        </p>
        <p v-if="connectionModal.mode !== 'key'" class="note">{{ t('settings.connectionUrlNote') }}</p>

        <UiBanner v-if="connError" tone="error">{{ connError }}</UiBanner>
      </form>
      <template #footer>
        <UiButton variant="ghost" :disabled="connPending || keyPending" @click="dismissConnectionModal">
          {{ t('common.cancel') }}
        </UiButton>
        <UiButton
          variant="primary"
          type="submit"
          form="connection-form"
          :loading="connPending || keyPending"
          :disabled="
            connectionModal.mode === 'key'
              ? !keyInput.trim()
              : !connName.trim() ||
                !connUrl.trim() ||
                (connectionModal.mode === 'create' && !connKey.trim())
          "
        >
          {{ t('common.save') }}
        </UiButton>
      </template>
    </UiModal>

    <UiModal
      v-if="promptModal"
      size="md"
      :title="
        promptModal.mode === 'create' ? t('settings.promptCreateTitle') : t('settings.promptEditTitle')
      "
      @close="promptModal = null"
    >
      <form id="prompt-form" class="modal-form" @submit.prevent="submitPrompt">
        <UiField v-slot="{ id }" :label="t('settings.promptNameLabel')">
          <UiTextInput :id="id" v-model="promptName" required />
        </UiField>
        <UiField v-slot="{ id }" :label="t('settings.promptTextLabel')">
          <textarea
            :id="id"
            v-model="promptText"
            class="prompt-input"
            rows="12"
            spellcheck="false"
            :disabled="promptModalPending"
          />
        </UiField>
        <!-- The placeholders and what a custom prompt overrides belong here, beside the text
             being written — not on the settings page, where they explained a dropdown. -->
        <p class="note">{{ t('settings.promptNote') }}</p>
        <UiBanner v-if="promptModalError" tone="error">{{ promptModalError }}</UiBanner>
      </form>
      <template #footer>
        <UiButton variant="ghost" :disabled="promptModalPending" @click="promptModal = null">
          {{ t('common.cancel') }}
        </UiButton>
        <UiButton
          variant="primary"
          type="submit"
          form="prompt-form"
          :loading="promptModalPending"
          :disabled="!promptName.trim() || !promptText.trim()"
        >
          {{ t('common.save') }}
        </UiButton>
      </template>
    </UiModal>

    <UiModal v-if="addingCustom" size="md" :title="t('settings.customTitle')" @close="addingCustom = false">
      <form id="custom-model" class="modal-form" @submit.prevent="submitCustom">
        <UiField v-slot="{ id }" :label="t('settings.customModelLabel')">
          <UiSelect :id="id" v-model="customChoice">
            <option value="" disabled>{{ t('common.notSet') }}</option>
            <optgroup v-if="recommendedModels.length" :label="t('settings.recommendedGroup')">
              <option v-for="model in recommendedModels" :key="model.id" :value="model.id">
                {{ modelLabel(model) }}
              </option>
            </optgroup>
            <optgroup v-if="otherModels.length" :label="t('settings.otherModelsGroup')">
              <option v-for="model in otherModels" :key="model.id" :value="model.id">
                {{ modelLabel(model) }}
              </option>
            </optgroup>
          </UiSelect>
        </UiField>
        <p class="note">{{ t('settings.customNote') }}</p>
      </form>
      <template #footer>
        <UiButton variant="ghost" :disabled="defaultsPending" @click="addingCustom = false">
          {{ t('common.cancel') }}
        </UiButton>
        <UiButton variant="primary" type="submit" form="custom-model" :disabled="!customChoice">
          {{ t('settings.customUse') }}
        </UiButton>
      </template>
    </UiModal>

    <UiConfirmDialog
      v-if="confirmingDelete"
      :title="t('settings.openrouterDelete')"
      :message="t('settings.openrouterDeleteConfirm')"
      :confirm-label="t('common.delete')"
      :pending="keyPending"
      @confirm="removeOpenRouterKey"
      @cancel="confirmingDelete = false"
    />

    <UiConfirmDialog
      v-if="confirmingConnectionDelete"
      :title="t('settings.connectionDelete')"
      :message="t('settings.connectionDeleteConfirm')"
      :confirm-label="t('common.delete')"
      :pending="connPending"
      @confirm="removeConnection"
      @cancel="confirmingConnectionDelete = false"
    />

    <UiConfirmDialog
      v-if="confirmingPromptDelete"
      :title="t('settings.promptDelete')"
      :message="t('settings.promptDeleteConfirm')"
      :confirm-label="t('common.delete')"
      :pending="promptPending"
      @confirm="removePrompt"
      @cancel="confirmingPromptDelete = false"
    />
  </UiScreen>
</template>

<style scoped>
/* --- Rail ----------------------------------------------------------------- */

.summary {
  display: flex;
  flex-direction: column;
  margin: 0;
}

.summary-row {
  padding: var(--space-4) 0;
  border-top: 1px solid var(--line);
}

.summary-row.last {
  border-bottom: 1px solid var(--line);
}

.summary-row dd {
  margin: var(--space-2) 0 0;
  color: var(--ink);
  font-size: var(--text-base);
  overflow-wrap: anywhere;
}

.summary-row dd.mono {
  font-size: var(--text-xs);
}

/* --- Groups --------------------------------------------------------------- */

/* A reading column, not the region's full width: these are forms, and a control row
   stretched across a desktop puts its button a screen away from its field. */
.groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
  max-width: 52rem;
}

.group {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* The rule under a heading is what bounds the group — there is no card to do it. */
.group-title {
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--hair);
  font-size: var(--display-sm);
  letter-spacing: normal;
}

/*
 * One row of controls that are all the same height. The fields render label-less here, so
 * the row aligns on its baseline edge and every control's height comes from
 * `--control-height` — nothing here re-states a pixel value.
 */
.controls {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: var(--space-4);
}

/* 12rem, not 18rem: at the wider basis the icon buttons beside the picker wrapped to a line
   of their own on a normal laptop. */
.grow {
  flex: 1 1 12rem;
  min-width: 0;
}

.control-buttons {
  display: flex;
  gap: var(--space-2);
  flex-wrap: nowrap;
  flex-shrink: 0;
}

.state {
  color: var(--muted);
  max-width: 72ch;
  overflow-wrap: anywhere;
}

.group-banner {
  max-width: 72ch;
}

.locales {
  display: inline-flex;
  gap: var(--space-5);
}

.locale {
  color: var(--muted);
  white-space: nowrap;
  transition: color var(--duration-fast) var(--ease);
}

.locale:hover {
  color: var(--accent);
}

/* The same treatment as the sign-in footer: ink and a weight step, underlined in the
   accent — the accent's one navigational use. */
.locale.active {
  color: var(--ink);
  font-weight: var(--weight-semibold);
  padding-bottom: 2px;
  border-bottom: 1px solid var(--accent);
}

/* --- Dialogs -------------------------------------------------------------- */

.modal-form {
  display: grid;
  gap: var(--space-4);
}

.note {
  color: var(--muted);
  font-size: var(--text-sm);
  line-height: 1.7;
  max-width: 60ch;
}

/* Same skin as UiTextInput's `.control`, sized for a prompt instead of one line. */
.prompt-input {
  width: 100%;
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--edge);
  border-radius: var(--radius);
  background: var(--paper);
  color: var(--ink);
  font-family: var(--mono);
  font-size: var(--text-xs);
  line-height: 1.6;
  resize: vertical;
  transition: border-color var(--duration-fast) var(--ease);
}

.prompt-input:disabled {
  background: var(--paper-sunken);
  color: var(--muted);
  cursor: not-allowed;
}

@media (pointer: coarse) {
  .prompt-input {
    font-size: 16px;
  }
}
</style>
