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
 * The account row is a plain row, not a menu. Language lives on the sign-in footer — a
 * popover in the sidebar foot was three destinations behind one unlabelled disclosure.
 *
 * Below 900px the rail collapses above the data region (each screen's own stylesheets do
 * that) and the sidebar becomes a drawer behind a menu button. No icon rail and no bottom
 * tab bar: the labels are doing the work, and a tab bar would spend the scarcest axis on a
 * phone.
 */
const { t } = useI18n()
const route = useRoute()
const localePath = useLocalePath()
const auth = useAuth()

const NAV = [
  { icon: 'dashboard', to: '/dashboard', label: 'nav.dashboard' },
  { icon: 'jobs', to: '/jobs', label: 'nav.jobs' },
  { icon: 'keys', to: '/keys', label: 'nav.keys' },
  { icon: 'connect', to: '/connect', label: 'nav.connect' },
  { icon: 'settings', to: '/settings', label: 'nav.settings' },
] as const

/** The signed-in identity: the name when Google sent one, the address otherwise. */
const account = computed(() => auth.me.value?.user.name?.trim() || auth.me.value?.user.email || '')
/** The avatar glyph: the backend sends no picture, so the identity's first letter stands in. */
const initial = computed(() => (account.value[0] ?? '?').toUpperCase())

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

      <!-- Who is signed in, and the one control that ends it. Nothing else: a destination
           hidden behind an account disclosure is a destination nobody finds. -->
      <div class="sidebar-foot">
        <span class="avatar" aria-hidden="true">{{ initial }}</span>
        <!-- Rendered even while `GET /api/me` is still in flight: the label is the row's
             only flexible track, and dropping it would slide the button across the foot the
             moment the identity arrives. -->
        <span class="account-label" :title="account || undefined">{{ account }}</span>
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

/* Pinned to the bottom, divided by a rule: the session's own row. */
.sidebar-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: auto;
  padding-top: var(--space-4);
  border-top: 1px solid var(--line-strong);
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
