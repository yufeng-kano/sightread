<script setup lang="ts">
/**
 * The app's glyphs, inlined.
 *
 * One Lucide set on Lucide's own 24 grid (1.75 stroke, round caps and joins) so a Copy in a
 * panel header, a Revoke row and a destination in the sidebar read as one family. Inline
 * rather than an icon package: a dozen glyphs do not justify a dependency, and a remote
 * sprite would be a render-blocking request for chrome that must paint immediately.
 *
 * Size is the call site's — every consumer sets width and height on the element — because
 * this design uses the same glyph at 13, 15, 16 and 22px.
 *
 * Always decorative. An icon-only control carries its name in `UiButton`'s `label` (which
 * becomes both the accessible name and the tooltip) and a nav item in the word beside it,
 * never in the glyph — so this is unconditionally `aria-hidden`.
 */
defineProps<{
  name:
    | 'refresh'
    | 'copy'
    | 'check'
    | 'plus'
    | 'edit'
    | 'trash'
    | 'close'
    | 'sign-out'
    | 'menu'
    | 'dashboard'
    | 'keys'
    | 'jobs'
    | 'connect'
    | 'settings'
    | 'scan-text'
}>()
</script>

<template>
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <!-- scan-text: the brand mark's glyph — a page being read inside scan corners. Also
         the figure placeholder's mark in the result viewer. -->
    <template v-if="name === 'scan-text'">
      <path d="M3 7V5a2 2 0 0 1 2-2h2" />
      <path d="M17 3h2a2 2 0 0 1 2 2v2" />
      <path d="M21 17v2a2 2 0 0 1-2 2h-2" />
      <path d="M7 21H5a2 2 0 0 1-2-2v-2" />
      <path d="M7 8h8M7 12h10M7 16h6" />
    </template>

    <!-- chart-column (Usage): bars on a baseline — the page is cost and tokens over time. -->
    <template v-else-if="name === 'dashboard'">
      <path d="M3 3v16a2 2 0 0 0 2 2h16" />
      <path d="M18 17V9M13 17V5M8 17v-3" />
    </template>

    <!-- history (Jobs): a clock with a rewind arrow — the record of what already ran. -->
    <template v-else-if="name === 'jobs'">
      <path d="M3 12a9 9 0 1 0 3.13-6.82" />
      <path d="M3 4.5V9h4.5" />
      <path d="M12 7.5V12l3.5 2" />
    </template>

    <!-- key-round (API keys): the bit end of a key. -->
    <template v-else-if="name === 'keys'">
      <path
        d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z"
      />
      <circle cx="16.5" cy="7.5" r=".5" fill="currentColor" />
    </template>

    <!-- plug (MCP Connector): prongs up, waiting to be plugged in. -->
    <template v-else-if="name === 'connect'">
      <path d="M9 2v6M15 2v6" />
      <path d="M6 8h12v3a6 6 0 0 1-12 0V8z" />
      <path d="M12 17v5" />
    </template>

    <!-- sliders-horizontal (Settings): a gear's teeth turn to mush at this size. -->
    <template v-else-if="name === 'settings'">
      <path d="M3 6h11M18 6h3" />
      <circle cx="16" cy="6" r="2" />
      <path d="M3 18h5M12 18h9" />
      <circle cx="10" cy="18" r="2" />
    </template>

    <!-- plus: create. -->
    <template v-else-if="name === 'plus'">
      <path d="M12 5v14M5 12h14" />
    </template>

    <!-- pencil: edit the thing beside it. -->
    <template v-else-if="name === 'edit'">
      <path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" />
      <path d="m15 5 4 4" />
    </template>

    <!-- trash: delete a stored value. Paired with a visible word wherever it destroys
         something the user would have to re-create. -->
    <template v-else-if="name === 'trash'">
      <path d="M3 6h18" />
      <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
      <path d="M19 6l-.867 12.142A2 2 0 0 1 16.138 20H7.862a2 2 0 0 1-1.995-1.858L5 6" />
      <path d="M10 11v6M14 11v6" />
    </template>

    <!-- copy: two offset sheets. -->
    <template v-else-if="name === 'copy'">
      <rect x="8" y="8" width="14" height="14" rx="2" />
      <path d="M4 16a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2" />
    </template>

    <!-- x: dismiss one thing. -->
    <template v-else-if="name === 'close'">
      <path d="M18 6 6 18M6 6l12 12" />
    </template>

    <!-- log-out: leave through the door. -->
    <template v-else-if="name === 'sign-out'">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="m16 17 5-5-5-5" />
      <path d="M21 12H9" />
    </template>

    <!-- menu: opens the sidebar drawer below the shell breakpoint. -->
    <template v-else-if="name === 'menu'">
      <path d="M4 6h16M4 12h16M4 18h16" />
    </template>

    <!-- refresh-cw: the gap and the arrowhead are what distinguish it from the spinner it
         is replaced by while a refresh is in flight. -->
    <template v-else-if="name === 'refresh'">
      <path d="M21 12a9 9 0 0 1-9 9 9 9 0 0 1-6.36-2.64L3 16" />
      <path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 6.36 2.64L21 8" />
      <path d="M21 3v5h-5M3 21v-5h5" />
    </template>

    <!-- check: the confirmation a copy swaps to. -->
    <template v-else>
      <path d="M20 6 9 17l-5-5" />
    </template>
  </svg>
</template>
