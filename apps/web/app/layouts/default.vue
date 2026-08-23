<script setup lang="ts">
import type { ComponentPublicInstance } from 'vue'

/**
 * The signed-in frame.
 *
 * A fixed grid, not a scrolling document: the sidebar stays put and the content region is
 * handed a bounded box, which is what lets each screen split it into a narrative rail and a
 * data column that scroll independently (docs/web.md § Design system). Nothing in the
 * signed-in app puts a whole screen on one scrollbar.
 *
 * The account row is the signed-in home of the locale choice: the avatar-and-name button
 * discloses a small popover holding the locale links (real links — the locale lives in
 * the URL). Sign-out stays its own control beside it, never inside the popover
 * (docs/web.md § Rules).
 *
 * Below 900px the rail collapses above the data region (each screen's own stylesheets do
 * that) and the sidebar becomes a drawer behind a menu button. No icon rail and no bottom
 * tab bar: the labels are doing the work, and a tab bar would spend the scarcest axis on a
 * phone.
 */
const { t, locale, locales } = useI18n()
const route = useRoute()
const localePath = useLocalePath()
const switchLocalePath = useSwitchLocalePath()
const auth = useAuth()

const NAV = [
  { icon: 'dashboard', to: '/dashboard', label: 'nav.dashboard' },
  { icon: 'files', to: '/files', label: 'nav.files' },
  { icon: 'history', to: '/history', label: 'nav.history' },
  { icon: 'keys', to: '/keys', label: 'nav.keys' },
  { icon: 'connect', to: '/connect', label: 'nav.connect' },
  { icon: 'settings', to: '/settings', label: 'nav.settings' },
] as const

/** The signed-in identity: the name when Google sent one, the address otherwise. */
const account = computed(() => auth.me.value?.user.name?.trim() || auth.me.value?.user.email || '')
/** The Google avatar; the identity's first letter stands in when there is none (dev
 *  sign-in) or when the image fails to load. */
const picture = computed(() => auth.me.value?.user.picture ?? null)
const pictureFailed = ref(false)
watch(picture, () => {
  pictureFailed.value = false
})
const initial = computed(() => (account.value[0] ?? '?').toUpperCase())

// --- the account popover: where the locale is chosen once signed in ----------

const accountMenuOpen = ref(false)
const accountMenu = ref<HTMLElement | null>(null)
const accountButton = ref<HTMLElement | null>(null)

// A locale link navigates; the route change is what closes the popover.
watch(() => route.path, () => {
  accountMenuOpen.value = false
})

function onAccountPointerDown(event: PointerEvent) {
  if (!accountMenuOpen.value) return
  const target = event.target as Node | null
  if (accountMenu.value?.contains(target) || accountButton.value?.contains(target)) return
  accountMenuOpen.value = false
}

function onAccountKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && accountMenuOpen.value) {
    accountMenuOpen.value = false
    accountButton.value?.focus()
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', onAccountPointerDown)
  document.addEventListener('keydown', onAccountKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onAccountPointerDown)
  document.removeEventListener('keydown', onAccountKeydown)
})

const sidebar = ref<HTMLElement | null>(null)
/** A ref on a component yields its instance; `UiButton` with neither `to` nor `href` roots
 *  a real `<button>`, which is the element focus has to return to. */
const menuButton = ref<ComponentPublicInstance | null>(null)
const drawerOpen = ref(false)

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** Matches the 900px breakpoint in this component's own stylesheet. */
function isDrawerLayout(): boolean {
  return typeof matchMedia !== 'undefined' && matchMedia('(max-width: 900px)').matches
}

// A destination the user just picked is behind the drawer they picked it from.
watch(() => route.path, () => {
  drawerOpen.value = false
})

/**
 * Open, the drawer covers the page behind a scrim — that makes it modal, and modal surfaces
 * owe the same three things a dialog does: focus moves in, Tab stays in, and focus returns
 * to the trigger on close. Without the trap, Tab walks invisibly through the page beneath.
 */
watch(drawerOpen, async (open) => {
  if (!isDrawerLayout()) return
  if (!open) {
    ;(menuButton.value?.$el as HTMLElement | undefined)?.focus()
    return
  }
  await nextTick()
  sidebar.value?.querySelector<HTMLElement>(FOCUSABLE)?.focus()
})

function onKeydown(event: KeyboardEvent) {
  // `drawerOpen` only means anything below the breakpoint — above it the sidebar is a static
  // column, and trapping focus in it would strand the user in the nav. The flag can be left
  // true by a resize, so check the layout rather than trusting it alone.
  if (!drawerOpen.value || !isDrawerLayout()) return

  if (event.key === 'Escape') {
    drawerOpen.value = false
    return
  }
  if (event.key !== 'Tab' || !sidebar.value) return

  const items = [...sidebar.value.querySelectorAll<HTMLElement>(FOCUSABLE)]
  if (!items.length) return
  const first = items[0]!
  const last = items[items.length - 1]!
  const active = document.activeElement

  // Also catches focus already outside the drawer — a click on the scrim, say — pulling it
  // back rather than letting Tab continue through the page behind.
  if (event.shiftKey && (active === first || !sidebar.value.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !sidebar.value.contains(active))) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

async function signOut() {
  await auth.signOut()
  await navigateTo(localePath('/'))
}
</script>

<template>
  <div class="shell">
    <a class="skip-link" href="#content">{{ t('app.skipToContent') }}</a>

    <!-- Under the drawer and above the content; clicking it closes. -->
    <div v-if="drawerOpen" class="scrim" @click="drawerOpen = false" />

    <aside ref="sidebar" class="sidebar" :class="{ open: drawerOpen }">
      <div class="sidebar-head">
        <AppBrand :to="localePath('/dashboard')" />
        <UiButton
          class="drawer-close"
          variant="ghost"
          size="sm"
          icon-only
          :label="t('nav.closeMenu')"
          @click="drawerOpen = false"
        >
          <template #icon><UiIcon name="close" /></template>
        </UiButton>
      </div>

      <nav class="nav" :aria-label="t('nav.primary')">
        <NuxtLink
          v-for="item in NAV"
          :key="item.to"
          class="nav-item"
          :to="localePath(item.to)"
          active-class="active"
        >
          <UiIcon :name="item.icon" />
          <span class="nav-label">{{ t(item.label) }}</span>
        </NuxtLink>
      </nav>

      <!-- Who is signed in: the avatar-and-name button discloses the locale popover, and
           the one control that ends the session sits beside it, never inside. -->
      <div class="sidebar-foot">
        <div v-if="accountMenuOpen" ref="accountMenu" class="account-menu">
          <p class="account-menu-title eyebrow">{{ t('nav.language') }}</p>
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
        </div>

        <!-- Rendered even while `GET /api/me` is still in flight: the label is the row's
             only flexible track, and dropping it would slide the button across the foot the
             moment the identity arrives. -->
        <button
          ref="accountButton"
          type="button"
          class="account"
          :title="account || undefined"
          aria-haspopup="true"
          :aria-expanded="accountMenuOpen ? 'true' : 'false'"
          @click="accountMenuOpen = !accountMenuOpen"
        >
          <img
            v-if="picture && !pictureFailed"
            class="avatar"
            :src="picture"
            alt=""
            referrerpolicy="no-referrer"
            @error="pictureFailed = true"
          >
          <span v-else class="avatar avatar-initial" aria-hidden="true">{{ initial }}</span>
          <span class="account-label">{{ account }}</span>
        </button>
        <button type="button" class="sign-out" :title="t('nav.signOut')" :aria-label="t('nav.signOut')" @click="signOut">
          <UiIcon name="sign-out" />
        </button>
      </div>
    </aside>

    <div class="frame">
      <header class="mobile-bar">
        <UiButton
          ref="menuButton"
          variant="ghost"
          size="sm"
          icon-only
          :label="t('nav.openMenu')"
          :aria-expanded="drawerOpen ? 'true' : 'false'"
          @click="drawerOpen = true"
        >
          <template #icon><UiIcon name="menu" /></template>
        </UiButton>
        <AppBrand :to="localePath('/dashboard')" />
      </header>

      <!--
        The content region. Every screen is a `UiScreen` — a rail and a data region, each
        owning its own scroll axis — so this element never scrolls above the breakpoint, and
        below it becomes the single one.
      -->
      <main id="content" class="content" tabindex="-1">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
  /* The frame owns the viewport: the document behind it never scrolls, which is what keeps
     the sidebar put and gives every screen's panels a bounded box to scroll inside. */
  height: 100dvh;
  overflow: hidden;
  background: var(--desk);
}

.skip-link {
  position: absolute;
  top: var(--space-2);
  left: var(--space-2);
  z-index: 80;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  background: var(--accent);
  color: var(--accent-fg);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  transform: translateY(-200%);
}

.skip-link:focus {
  transform: none;
}

/*
 * Only the drawer layout has a scrim, and `drawerOpen` can still be true when the viewport
 * crosses back above the breakpoint — a rotated tablet. Declared hidden here rather than
 * only styled inside the media query: an unstyled `div` is a perfectly good grid child, and
 * it was taking the sidebar's cell and pushing the whole frame one column over.
 */
.scrim {
  display: none;
}

/* --- Sidebar -------------------------------------------------------------- */

.sidebar {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: var(--space-7) var(--space-6);
  background: var(--rail);
  border-right: 1px solid var(--line);
}

.sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-9);
}

/* The close control only exists once the sidebar is a drawer. Qualified by its parent so it
   outranks `UiButton`'s own `display` without depending on stylesheet order. */
.sidebar-head .drawer-close {
  display: none;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
  overflow-y: auto;
  /* As a drawer this sits over the content region; scrolling it to its end must not chain
     through to the page behind. */
  overscroll-behavior: contain;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: var(--control-height-sm);
  padding: 0 var(--space-2) 0 10px;
  border-radius: var(--radius);
  color: var(--muted);
  font-size: var(--text-sm);
  overflow: hidden;
  transition:
    background var(--duration-fast) var(--ease),
    color var(--duration-fast) var(--ease);
}

.nav-item:hover {
  background: var(--rail-active);
  color: var(--ink);
}

/*
 * Active is a fill *and* a step up in weight, and nothing else — no left accent bar, no
 * vertical rule. The accent belongs to data (docs/web.md § Design system), and the fill on
 * its own is a couple of percent of luminance and reads as noise without the weight.
 */
.nav-item.active {
  background: var(--rail-active);
  color: var(--ink);
  font-weight: var(--weight-semibold);
}

.nav-item :deep(svg) {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  pointer-events: none;
}

.nav-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Pinned to the bottom, divided by a rule: the session's own row. The popover anchors
   to it, so it owns a positioning context. */
.sidebar-foot {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: auto;
  padding-top: var(--space-4);
  border-top: 1px solid var(--line-strong);
}

/* The disclosure: the avatar and name are one button, styled as the plain row they
   replace — borderless, with the same hover shift the nav rows use. */
.account {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.avatar {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-full);
  background: var(--paper);
  object-fit: cover;
}

.avatar-initial {
  color: var(--faint);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
}

.account-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-xs);
  color: var(--muted);
  transition: color var(--duration-fast) var(--ease);
}

.account:hover .account-label {
  color: var(--ink);
}

/* Above the row it discloses from, on the panel surface. A border bounds it — the one
   shadow stays reserved for dialogs and the drawer (docs/web.md § Design system). */
.account-menu {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + var(--space-2));
  padding: var(--space-4);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  background: var(--paper);
}

.account-menu-title {
  margin: 0 0 var(--space-3);
}

.locales {
  display: inline-flex;
  gap: var(--space-5);
}

.locale {
  color: var(--muted);
  white-space: nowrap;
  font-size: var(--text-sm);
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

/* Borderless and small — it sits in a row of text, not in a row of controls, so a bordered
   button here would read as the row's primary action. */
.sign-out {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--faint);
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease);
}

/*
 * The glyph stays 24px on a touch screen — it is a quiet control in a row of text — but the
 * box you press grows to the same target as every other control there. Negative margins
 * keep the taller hit area from pushing the foot row apart, so the design does not change,
 * only what counts as a tap.
 */
@media (pointer: coarse) {
  .sign-out {
    width: var(--control-height);
    height: var(--control-height);
    margin: calc((var(--control-height) - 24px) / -2);
  }
}

.sign-out:hover {
  color: var(--ink);
}

.sign-out :deep(svg) {
  width: 15px;
  height: 15px;
}

/* --- Content -------------------------------------------------------------- */

.frame {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.mobile-bar {
  display: none;
}

/*
 * A single bounded row for the screen inside it. `minmax(0, 1fr)` is what hands `UiScreen`
 * a height it can be shorter than, which is what its panels scroll within.
 */
.content {
  display: grid;
  grid-template-rows: minmax(0, 1fr);
  flex: 1;
  min-width: 0;
  min-height: 0;
  background: var(--paper);
}

/* --- Responsive ----------------------------------------------------------- */

@media (max-width: 900px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .scrim {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 40;
    background: var(--overlay);
    overscroll-behavior: contain;
    animation: fade var(--duration) var(--ease-enter);
  }

  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 50;
    width: var(--sidebar-width);
    transform: translateX(-100%);
    box-shadow: var(--shadow-dialog);
    /* Off-screen *and* inert: a translated-away drawer is still focusable, so Tab would walk
       into a menu nobody can see. `visibility` fixes that, but it is not interpolable —
       applied plainly it would snap to hidden on the first frame and eat the slide-out.
       Hence the `0s` step delayed by the transform's own duration on close, undelayed on
       open. */
    visibility: hidden;
    transition:
      transform var(--duration) var(--ease-exit),
      visibility 0s linear var(--duration);
  }

  .sidebar.open {
    transform: none;
    visibility: visible;
    transition:
      transform var(--duration-slow) var(--ease-enter),
      visibility 0s;
  }

  .sidebar-head .drawer-close {
    display: inline-flex;
  }

  .mobile-bar {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: var(--space-12);
    flex-shrink: 0;
    padding: var(--space-2) var(--space-4);
    background: var(--rail);
    border-bottom: 1px solid var(--line);
  }

  /* One scroll axis: the screen's rail collapses above its data region, and this becomes
     the only thing that scrolls. */
  .content {
    display: block;
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  @keyframes fade {
    from {
      opacity: 0;
    }
  }
}
</style>
