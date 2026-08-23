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

const { t, locale } = useI18n()
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

const connectionModal = ref<null | { mode: 'create' } | { mode: 'edit'; id: number }>(null)
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

function openConnectionEdit() {
  const row = selectedConnection.value
  if (!row) {
    return
  }
  connName.value = row.name
  connUrl.value = row.base_url
  connKey.value = ''
  connError.value = null
  connectionModal.value = { mode: 'edit', id: row.id }
}

async function submitConnection() {
  const modal = connectionModal.value
  if (!modal || connPending.value) {
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
      connectionModal.value = null
      await refreshConnections()
      // A freshly added provider is what the user came to use — select it right away.
      await applyProvider(String(created.id))
    } else {
      await updateConnection(modal.id, {
        name: connName.value.trim(),
        base_url: connUrl.value.trim(),
        ...(connKey.value.trim() ? { api_key: connKey.value.trim() } : {}),
      })
      connectionModal.value = null
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

async function loadConnectionModels() {
  const row = selectedConnection.value
  if (!row) {
    connectionModels.value = null
    return
  }
  const requestedId = row.id
  connectionModelsPending.value = true
  connectionModelsError.value = null
  try {
    const data = (await listConnectionModels(requestedId)).data
    // A slow answer for a connection that is no longer selected must not fill the
    // current picker with the wrong catalog — drop it.
    if (selectedConnection.value?.id === requestedId) {
      connectionModels.value = data
    }
  } catch (error) {
    if (selectedConnection.value?.id === requestedId) {
      connectionModelsError.value = await resolve(error)
    }
  } finally {
    if (selectedConnection.value?.id === requestedId) {
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

async function saveOpenRouterKey() {
  const candidate = keyInput.value.trim()
  if (!candidate || keyPending.value) {
    return
  }
  keyPending.value = true
  keyError.value = null
  keyMessage.value = null
  try {
    await putOpenRouterKey(candidate)
    keyInput.value = ''
    keyMessage.value = t('settings.openrouterSaved')
    await auth.refresh()
  } catch (error) {
    keyError.value = await resolve(error)
  } finally {
    keyPending.value = false
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
  <div class="page">
    <UiPageHeader :title="t('settings.headTitle')" />

    <div class="stack">
      <UiCard :title="t('settings.providerTitle')">
        <div class="section">
          <UiBanner v-if="connectionsError" tone="error">{{ connectionsError }}</UiBanner>

          <div class="control-row">
            <UiField v-slot="{ id }" class="grow" :label="t('settings.providerLabel')">
              <UiSelect
                :id="id"
                :model-value="providerChoice"
                :disabled="providerPending"
                @update:model-value="applyProvider"
              >
                <option value="">{{ t('settings.providerOpenRouter') }}</option>
                <option v-for="row in connections" :key="row.id" :value="String(row.id)">
                  {{ row.name }}
                </option>
              </UiSelect>
            </UiField>

            <UiButton :disabled="providerPending" @click="openConnectionCreate">
              <template #icon><UiIcon name="plus" /></template>
              {{ t('settings.addProvider') }}
            </UiButton>
          </div>

          <template v-if="selectedConnection">
            <p class="state">
              {{
                t('settings.connectionState', {
                  url: selectedConnection.base_url,
                  masked: selectedConnection.masked,
                })
              }}
            </p>
            <div class="control-row">
              <UiButton :disabled="connPending" @click="openConnectionEdit">
                <template #icon><UiIcon name="edit" /></template>
                {{ t('common.edit') }}
              </UiButton>
              <UiButton
                variant="danger"
                :disabled="connPending"
                @click="confirmingConnectionDelete = true"
              >
                <template #icon><UiIcon name="trash" /></template>
                {{ t('settings.connectionDelete') }}
              </UiButton>
            </div>
          </template>

          <UiBanner v-if="providerError" tone="error">{{ providerError }}</UiBanner>
          <UiBanner v-else-if="providerMessage" tone="ok">{{ providerMessage }}</UiBanner>
        </div>
      </UiCard>

      <UiCard v-if="!selectedConnection" :title="t('settings.openrouterTitle')">
        <div class="section">
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

          <form class="control-row" @submit.prevent="saveOpenRouterKey">
            <UiField v-slot="{ id }" class="grow" :label="t('settings.openrouterLabel')">
              <UiTextInput
                :id="id"
                v-model="keyInput"
                type="password"
                autocomplete="off"
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
            <!-- Keeps its word: it destroys a credential the user has to fetch from OpenRouter
                 again, which is not something a bare glyph should be able to do. -->
            <UiButton
              v-if="openrouterKey?.present"
              variant="danger"
              :disabled="keyPending"
              @click="confirmingDelete = true"
            >
              <template #icon><UiIcon name="trash" /></template>
              {{ t('settings.openrouterDelete') }}
            </UiButton>
          </form>

          <UiBanner v-if="keyError" tone="error">{{ keyError }}</UiBanner>
          <UiBanner v-else-if="keyMessage" tone="ok">{{ keyMessage }}</UiBanner>
        </div>
      </UiCard>

      <UiCard :title="t('settings.defaultsTitle')">
        <div class="section">
          <!-- Model choice on a custom connection: its own live catalog, default prompts. -->
          <template v-if="selectedConnection">
            <UiBanner v-if="connectionModelsError" tone="error">
              {{ connectionModelsError }}
            </UiBanner>
            <UiSkeleton v-else-if="connectionModelsPending && !connectionModels" :rows="2" />

            <div v-else class="control-row">
              <UiField v-slot="{ id }" class="grow" :label="t('settings.connectionModelLabel')">
                <UiSelect
                  :id="id"
                  :model-value="connectionModelChoice"
                  :disabled="defaultsPending"
                  @update:model-value="applyConnectionModel"
                >
                  <option value="">{{ t('common.notSet') }}</option>
                  <option v-for="model in connectionModels ?? []" :key="model.id" :value="model.id">
                    {{ model.name ? `${model.name} · ${model.id}` : model.id }}
                  </option>
                </UiSelect>
              </UiField>
              <UiButton
                :disabled="connectionModelsPending"
                :label="t('common.refresh')"
                @click="loadConnectionModels"
              >
                <template #icon><UiIcon name="refresh" /></template>
              </UiButton>
            </div>
            <p class="custom-note">{{ t('settings.connectionModelNote') }}</p>
          </template>

          <!-- Model choice on OpenRouter: preset profiles + at most one custom model. -->
          <template v-else>
            <UiBanner v-if="catalogError" tone="error">{{ catalogError }}</UiBanner>
            <UiSkeleton v-else-if="!catalog" :rows="2" />

            <div v-else class="control-row">
              <UiField v-slot="{ id }" class="grow" :label="t('settings.defaultLabel')">
                <UiSelect
                  :id="id"
                  :model-value="selection"
                  :disabled="defaultsPending"
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
          </template>

          <UiBanner v-if="defaultsError" tone="error">{{ defaultsError }}</UiBanner>
          <UiBanner v-else-if="defaultsMessage" tone="ok">{{ defaultsMessage }}</UiBanner>
        </div>
      </UiCard>

      <UiCard :title="t('settings.promptTitle')">
        <div class="section">
          <UiBanner v-if="promptsError" tone="error">{{ promptsError }}</UiBanner>

          <p class="state">
            {{
              selectedPrompt
                ? t('settings.promptStateCustom', { name: selectedPrompt.name })
                : t('settings.promptStateDefault')
            }}
          </p>

          <div class="control-row">
            <UiField v-slot="{ id }" class="grow" :label="t('settings.promptLabel')">
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
            <UiButton v-if="selectedPrompt" :disabled="promptPending" @click="openPromptEdit">
              <template #icon><UiIcon name="edit" /></template>
              {{ t('common.edit') }}
            </UiButton>
            <UiButton
              v-if="selectedPrompt"
              variant="danger"
              :disabled="promptPending"
              @click="confirmingPromptDelete = true"
            >
              <template #icon><UiIcon name="trash" /></template>
              {{ t('settings.promptDelete') }}
            </UiButton>
          </div>

          <p class="custom-note">{{ t('settings.promptNote') }}</p>

          <UiBanner v-if="promptError" tone="error">{{ promptError }}</UiBanner>
          <UiBanner v-else-if="promptMessage" tone="ok">{{ promptMessage }}</UiBanner>
        </div>
      </UiCard>
    </div>

    <UiModal
      v-if="connectionModal"
      :title="
        connectionModal.mode === 'create'
          ? t('settings.connectionCreateTitle')
          : t('settings.connectionEditTitle')
      "
      @close="connectionModal = null"
    >
      <form id="connection-form" class="modal-form" @submit.prevent="submitConnection">
        <UiField v-slot="{ id }" :label="t('settings.connectionNameLabel')">
          <UiTextInput :id="id" v-model="connName" required />
        </UiField>
        <UiField v-slot="{ id }" :label="t('settings.connectionUrlLabel')">
          <UiTextInput
            :id="id"
            v-model="connUrl"
            placeholder="https://proxy.example.com/openai/v1"
            required
          />
        </UiField>
        <p class="custom-note">{{ t('settings.connectionUrlNote') }}</p>
        <UiField v-slot="{ id }" :label="t('settings.connectionKeyLabel')">
          <UiTextInput
            :id="id"
            v-model="connKey"
            type="password"
            autocomplete="off"
            :required="connectionModal.mode === 'create'"
          />
        </UiField>
        <p v-if="connectionModal.mode === 'edit'" class="custom-note">
          {{ t('settings.connectionKeyKeepNote') }}
        </p>
        <UiBanner v-if="connError" tone="error">{{ connError }}</UiBanner>
      </form>
      <template #footer>
        <UiButton variant="ghost" :disabled="connPending" @click="connectionModal = null">
          {{ t('common.cancel') }}
        </UiButton>
        <UiButton
          variant="primary"
          type="submit"
          form="connection-form"
          :loading="connPending"
          :disabled="!connName.trim() || !connUrl.trim() || (connectionModal.mode === 'create' && !connKey.trim())"
        >
          {{ t('common.save') }}
        </UiButton>
      </template>
    </UiModal>

    <UiModal
      v-if="promptModal"
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
        <p class="custom-note">{{ t('settings.promptNote') }}</p>
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

    <UiModal v-if="addingCustom" :title="t('settings.customTitle')" @close="addingCustom = false">
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
        <p class="custom-note">{{ t('settings.customNote') }}</p>
      </form>
      <template #footer>
        <UiButton variant="ghost" :disabled="defaultsPending" @click="addingCustom = false">
          {{ t('common.cancel') }}
        </UiButton>
        <UiButton
          variant="primary"
          type="submit"
          form="custom-model"
          :disabled="!customChoice"
        >
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
  </div>
</template>

<style scoped>
/* No gap on the page itself: UiPageHeader carries its own bottom margin. Forms also read
   better in a column than stretched across a desktop's full width — the tables on the other
   pages are what --content-max is for. */
.page {
  display: flex;
  flex-direction: column;
  max-width: 56rem;
  width: 100%;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.section {
  display: grid;
  gap: var(--space-4);
}

.state {
  color: var(--text-secondary);
  max-width: 72ch;
  overflow-wrap: anywhere;
}

.modal-form {
  display: grid;
  gap: var(--space-3);
}

/* Same skin as UiTextInput's `.control`, sized for a prompt instead of one line. */
.prompt-input {
  width: 100%;
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  font-family: var(--mono);
  font-size: var(--text-xs);
  line-height: 1.6;
  resize: vertical;
  outline: none;
  transition:
    border-color var(--duration-fast) var(--ease),
    box-shadow var(--duration-fast) var(--ease);
}

.prompt-input:focus {
  border-color: var(--ring-border);
  box-shadow: var(--ring);
  outline: none;
}

.prompt-input:disabled {
  background: var(--surface-2);
  color: var(--muted);
  cursor: not-allowed;
}

@media (pointer: coarse) {
  .prompt-input {
    font-size: var(--text-md);
  }
}

.custom-note {
  color: var(--muted);
  font-size: var(--text-sm);
  max-width: 60ch;
}

/*
 * One row of controls that are all the same height: the fields' labels sit above them, so
 * the row aligns on its baseline edge and the buttons meet the bottom of the inputs. Every
 * control's height comes from --control-height, so nothing here re-states a pixel value.
 */
.control-row {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.grow {
  flex: 1 1 18rem;
  min-width: 0;
}
</style>
