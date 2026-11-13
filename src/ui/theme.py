from nicegui import ui

from src.ui import pwa

# Shared chart palette for the paper desk. Stamp, moss, brass, and ink
# stay distinguishable on #F3EDE2 without a purple gradient.
CHART_COLORS = [
    '#9c2f24', '#2c5a42', '#8a6830', '#1e1a15', '#c46a3a',
    '#5c554b', '#6e8f78', '#b23a2f', '#3e4a44', '#d3c9b8',
]

METRIC_VALUE_CLASSES = {
    'primary': 'oy-text-ink',
    'secondary': 'oy-text-accent',
    'accent': 'oy-text-blue',
    'info': 'oy-text-blue',
    'positive': 'oy-text-green',
}

# Column ladder for cover-art tiles (storage boxes, set tiles) — the bigger
# siblings of the card grid in collection.py. Two columns on a phone keeps a
# tile ~155px wide at 390px, matching the card grids.
#
# The counts past `lg` look sparse for the viewport because the nav drawer takes
# 234px from every desktop width: at 1280px a tile still gets ~250px of content
# width, which is what the old `repeat(auto-fill, minmax(250px, 1fr))` produced.
TILE_GRID_COLUMNS = 'grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5'

GLOBAL_CSS = """
<meta name="description" content="OpenYuGi es gratis. Crea una cuenta y cataloga tus cartas de Yu-Gi-Oh: set, rareza, idioma, estado y el sitio de cada copia.">
<style>
@font-face {
  font-family: "Fraunces";
  font-style: normal;
  font-weight: 600;
  font-display: swap;
  src: url("/fonts/fraunces-600.woff2") format("woff2");
}
@font-face {
  font-family: "Fraunces";
  font-style: italic;
  font-weight: 400;
  font-display: swap;
  src: url("/fonts/fraunces-400i.woff2") format("woff2");
}
@font-face {
  font-family: "Source Sans 3";
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url("/fonts/source-sans-400.woff2") format("woff2");
}
@font-face {
  font-family: "Source Sans 3";
  font-style: normal;
  font-weight: 500;
  font-display: swap;
  src: url("/fonts/source-sans-500.woff2") format("woff2");
}
@font-face {
  font-family: "Source Sans 3";
  font-style: normal;
  font-weight: 600;
  font-display: swap;
  src: url("/fonts/source-sans-600.woff2") format("woff2");
}
@font-face {
  font-family: "IBM Plex Mono";
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url("/fonts/plex-400.woff2") format("woff2");
}
@font-face {
  font-family: "IBM Plex Mono";
  font-style: normal;
  font-weight: 500;
  font-display: swap;
  src: url("/fonts/plex-500.woff2") format("woff2");
}
:root {
  --oy-bg: #f3ede2;
  --oy-surface: #fbf7f0;
  --oy-surface-2: #e6ddcc;
  --oy-border: #d3c9b8;
  --oy-border-soft: #e4dccb;
  --oy-text: #1e1a15;
  --oy-body-text: #3a342c;
  --oy-muted: #5c554b;
  --oy-faint: #7a7268;
  --oy-soft: #5c554b;
  --oy-placeholder: #8a8174;
  --oy-accent: #9c2f24;
  --oy-accent-deep: #7d261d;
  --oy-blue: #2c5a42;
  --oy-green: #2c5a42;
  --oy-red: #9c2f24;
  --oy-yellow: #8a6830;
  --oy-gold: #8a6830;
  --oy-ink: #fbf7f0;
  --oy-font-display: "Fraunces", "Iowan Old Style", Palatino, "Palatino Linotype", Georgia, serif;
  --oy-font-body: "Source Sans 3", "Segoe UI", "Helvetica Neue", sans-serif;
  --oy-font-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Consolas, monospace;
}

/* ---------- Base canvas ---------- */
body, body.body--dark, body.body--light {
  background: var(--oy-bg) !important;
  font-family: var(--oy-font-body);
  color: var(--oy-body-text);
}
.q-layout, .q-page-container, .q-page { background: transparent !important; }

a { color: var(--oy-accent); }
a:hover { color: var(--oy-accent-deep); }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: #c9bfae;
  border-radius: 2px;
  border: 2px solid transparent;
  background-clip: content-box;
}
::-webkit-scrollbar-thumb:hover { background-color: #8a8174; }

/* ---------- Typography ---------- */
.text-h3, .text-h4, .text-h5 {
  font-family: var(--oy-font-display);
  font-weight: 700;
  color: var(--oy-text);
  letter-spacing: -.3px;
}
.text-h4 { font-size: 2.1rem; line-height: 1.1; }
.text-h5 { font-size: 1.6rem; line-height: 1.15; }
.text-h6 {
  font-family: var(--oy-font-display);
  font-weight: 600;
  color: var(--oy-text);
  letter-spacing: .2px;
}

.oy-h1 {
  font-family: var(--oy-font-display);
  font-size: 2.35rem;
  font-weight: 700;
  line-height: 1.05;
  letter-spacing: -.3px;
  color: var(--oy-text);
}
.oy-sub { font-size: 13px; color: var(--oy-muted); }
.oy-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: var(--oy-muted);
}
.oy-stat {
  font-family: var(--oy-font-display);
  font-size: 2.1rem;
  font-weight: 700;
  line-height: 1.1;
  color: var(--oy-text);
}
.oy-mono { font-family: var(--oy-font-mono); }
.oy-display { font-family: var(--oy-font-display); letter-spacing: -.2px; }
.oy-seclabel {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: var(--oy-blue);
}

/* ---------- Surfaces ---------- */
.q-card, .q-card--dark {
  background: var(--oy-surface);
  border: 1px solid var(--oy-border);
  border-radius: 2px;
  box-shadow: none;
  color: var(--oy-body-text);
}
.oy-card {
  background: var(--oy-surface);
  border: 1px solid var(--oy-border);
  border-radius: 2px;
}
.collection-card { overflow: hidden; border-radius: 10px; }

/* Legacy utility remaps: old pages use gray-* utilities everywhere */
.bg-dark { background: var(--oy-surface) !important; }
.bg-gray-900, .bg-gray-950 { background: rgba(255,255,255,.03) !important; }
.bg-gray-800 { background: rgba(255,255,255,.06) !important; }
.bg-gray-700 { background: rgba(255,255,255,.09) !important; }
.border-gray-600, .border-gray-700, .border-gray-800 { border-color: var(--oy-border) !important; }
.hover\\:bg-gray-800:hover, .hover\\:bg-gray-700:hover { background: rgba(255,255,255,.05) !important; }
.hover\\:border-gray-500:hover, .hover\\:border-gray-600:hover { border-color: rgba(203,166,247,.45) !important; }
.text-gray-300 { color: var(--oy-body-text) !important; }
.text-gray-400, .text-gray-600, .text-grey-4, .text-grey-5 { color: var(--oy-muted) !important; }
.text-gray-500, .text-grey-6 { color: var(--oy-faint) !important; }

/* Semantic accent remaps: set codes gold, prices green, warnings soft */
.text-yellow-500, .text-orange-400 { color: var(--oy-gold) !important; }
.text-yellow-400 { color: var(--oy-yellow) !important; }
.text-green-400, .text-green-500 { color: var(--oy-green) !important; }
.text-red-400, .text-red-500 { color: var(--oy-red) !important; }
.text-blue-300, .text-blue-400 { color: var(--oy-blue) !important; }
.text-purple-400 { color: var(--oy-accent) !important; }
.font-mono { font-family: var(--oy-font-mono) !important; }

/* Semantic utility classes for Python-rendered elements */
.oy-text-accent { color: var(--oy-accent) !important; }
.oy-text-blue { color: var(--oy-blue) !important; }
.oy-text-green { color: var(--oy-green) !important; }
.oy-text-gold { color: var(--oy-gold) !important; }
.oy-text-body { color: var(--oy-body-text) !important; }
.oy-text-muted { color: var(--oy-muted) !important; }
.oy-text-faint { color: var(--oy-faint) !important; }
.oy-text-soft { color: var(--oy-soft) !important; }
.oy-text-placeholder { color: var(--oy-placeholder) !important; }
.oy-interactive-muted { color: var(--oy-muted) !important; }
.oy-interactive-muted:hover { color: var(--oy-text) !important; }
.oy-accent-border-hover:hover { border-color: rgba(203,166,247,.45) !important; }
.oy-metric-card:hover { border-color: rgba(203,166,247,.4) !important; }
.oy-nav-card:hover { border-color: rgba(203,166,247,.45) !important; }
.oy-nav-glow { background: rgba(203,166,247,.1); }
.oy-nav-card:hover .oy-nav-glow { background: rgba(203,166,247,.2); }
.oy-nav-card:hover .oy-nav-card-title { color: var(--oy-accent) !important; }
.oy-add-storage:hover { border-color: rgba(203,166,247,.6) !important; }
.oy-add-storage:hover .oy-add-storage-icon { color: var(--oy-accent) !important; }
.oy-add-storage:hover .oy-add-storage-label { color: var(--oy-text) !important; }

.q-separator { background: var(--oy-border) !important; }

/* ---------- Buttons ---------- */
.q-btn {
  font-family: var(--oy-font-body);
  font-weight: 600;
  letter-spacing: .2px;
  text-transform: none;
}
.q-btn--rectangle { border-radius: 2px; }
.text-white { color: var(--oy-text) !important; }
.oy-text-ink { color: var(--oy-text) !important; }
.q-btn.bg-secondary, .q-btn.bg-accent,
.q-btn.bg-positive, .q-btn.bg-negative, .q-btn.bg-info, .q-btn.bg-warning {
  color: var(--oy-ink) !important;
}
.q-btn.bg-primary { color: var(--oy-ink) !important; }
.q-btn.bg-green { background: var(--oy-green) !important; color: var(--oy-ink) !important; }
.q-btn.bg-red { background: var(--oy-red) !important; color: var(--oy-ink) !important; }
.q-btn.bg-orange { background: var(--oy-gold) !important; color: var(--oy-ink) !important; }

.q-btn.bg-purple { background: var(--oy-accent-deep) !important; color: #fff !important; }
.q-btn.bg-blue { background: var(--oy-blue) !important; color: var(--oy-ink) !important; }

/* ---------- Uploader (drop zones) ---------- */
.q-uploader {
  background: rgba(255,255,255,.03);
  border: 1px dashed rgba(255,255,255,.18);
  border-radius: 12px;
  box-shadow: none;
}
.q-uploader__header {
  background: transparent;
  color: var(--oy-body-text);
}
.q-uploader__list { background: transparent; }

/* Chips on light accent backgrounds need dark ink text */
.q-chip.bg-secondary, .q-chip.bg-accent,
.q-chip.bg-positive, .q-chip.bg-warning {
  color: var(--oy-ink) !important;
}
.q-chip.bg-primary { color: var(--oy-text) !important; }
.q-chip.bg-primary .q-icon { color: var(--oy-text) !important; }
.q-chip.bg-secondary .q-icon,
.q-chip.bg-accent .q-icon, .q-chip.bg-positive .q-icon, .q-chip.bg-warning .q-icon {
  color: var(--oy-ink) !important;
}

/* ---------- Fields ---------- */
.q-field__control {
  background: var(--oy-surface);
  border-radius: 2px;
  box-shadow: inset 0 0 0 1px var(--oy-border);
  padding: 0 12px;
}
.q-field--standard .q-field__control:before,
.q-field--standard .q-field__control:after { display: none; }
.q-field--outlined .q-field__control:before,
.q-field--outlined .q-field__control:after { border: none; }
.q-field--focused .q-field__control { box-shadow: inset 0 0 0 1px var(--oy-accent); }
.q-field__native, .q-field__input, .q-field__prefix, .q-field__suffix {
  color: var(--oy-text) !important;
  font-family: var(--oy-font-body);
}
.q-field__label { color: var(--oy-muted); }
.q-field__marginal { color: var(--oy-muted); }

/* ---------- Tables ---------- */
.q-table__container {
  background: var(--oy-surface) !important;
  border: 1px solid var(--oy-border);
  border-radius: 12px;
}
.q-table thead th {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: .8px;
  text-transform: uppercase;
  color: var(--oy-faint);
}
.q-table tbody td { color: var(--oy-body-text); }
.q-table tbody tr:hover { background: rgba(255,255,255,.03); }
.q-table__bottom { color: var(--oy-muted); }

/* ---------- Tabs ---------- */
.q-tab {
  text-transform: none;
  font-family: var(--oy-font-body);
  font-weight: 600;
  letter-spacing: .2px;
  color: var(--oy-muted);
}
.q-tab--active { color: var(--oy-accent); }
.q-tab__indicator { background: var(--oy-accent); }

/* ---------- Overlays ---------- */
.q-dialog .q-card, .q-menu {
  background: var(--oy-surface);
  border: 1px solid var(--oy-border);
  color: var(--oy-text);
}
.q-menu { border-radius: 12px; color: var(--oy-body-text); }
.q-item__label { color: var(--oy-body-text); }
.q-item--active, .q-manual-focusable--focused { color: var(--oy-accent); }
.q-tooltip {
  background: var(--oy-text);
  color: var(--oy-ink);
  border-radius: 2px;
  font-family: var(--oy-font-body);
}
.q-notification { border-radius: 12px; font-family: var(--oy-font-body); }

/* ---------- Single-card views ---------- */
.oy-single-card-dialog,
.q-dialog .q-card.oy-single-card-dialog {
  background: var(--oy-bg);
  border: 0;
  border-radius: 0;
  color: var(--oy-body-text);
}
.oy-single-card-shell { background: transparent; }
.oy-single-card-art {
  background:
    radial-gradient(circle at 50% 42%, rgba(203,166,247,.13), transparent 42%),
    linear-gradient(155deg, rgba(255,255,255,.035), rgba(0,0,0,.2));
  border-right: 1px solid var(--oy-border);
  overflow: hidden;
}
.oy-single-card-art::after {
  content: '';
  position: absolute;
  inset: 9%;
  border: 1px solid rgba(203,166,247,.08);
  border-radius: 24px;
  pointer-events: none;
}
.oy-single-card-image {
  z-index: 1;
  border-radius: 10px;
  filter: drop-shadow(0 24px 38px rgba(0,0,0,.52));
}
.oy-single-card-content { background: transparent; }
.q-btn.oy-single-card-close {
  background: rgba(10,9,18,.72) !important;
  border: 1px solid rgba(255,255,255,.12);
  color: var(--oy-soft) !important;
  backdrop-filter: blur(10px);
  transition: background .15s, border-color .15s, color .15s;
}
.q-btn.oy-single-card-close:hover {
  background: rgba(203,166,247,.14) !important;
  border-color: rgba(203,166,247,.42);
  color: var(--oy-text) !important;
}
.q-btn.oy-single-card-close .q-btn__content {
  color: var(--oy-text) !important;
  font-family: var(--oy-font-body);
  font-size: 30px;
  font-weight: 400;
  line-height: 1;
}
.oy-single-card-title {
  font-family: var(--oy-font-display);
  color: var(--oy-text);
  font-weight: 700;
  line-height: 1.08;
  letter-spacing: -.45px;
}
.oy-single-card-meta {
  font-family: var(--oy-font-mono);
  color: var(--oy-faint);
  font-size: 11px;
}
.oy-single-card-panel,
.q-card.oy-single-card-panel {
  background: rgba(255,255,255,.032);
  border: 1px solid var(--oy-border);
  border-radius: 14px;
  box-shadow: none;
}
.oy-single-card-stat {
  min-width: 0;
  padding: 13px 14px;
  gap: 4px;
  background: rgba(255,255,255,.028);
  border: 1px solid rgba(255,255,255,.065);
  border-radius: 11px;
}
.oy-single-card-stat-label {
  color: var(--oy-muted);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1.1px;
  line-height: 1.2;
  text-transform: uppercase;
}
.oy-single-card-stat-value {
  color: var(--oy-text);
  font-family: var(--oy-font-display);
  font-size: 17px;
  font-weight: 600;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.oy-single-card-effect {
  color: var(--oy-body-text);
  font-size: 16px;
  line-height: 1.72;
}
.oy-single-card-status .q-chip {
  background: rgba(203,166,247,.11) !important;
  border: 1px solid rgba(203,166,247,.2);
  color: #e8def7 !important;
}
.oy-single-card-status .q-chip .q-icon { color: var(--oy-accent) !important; }
.oy-single-card-owned {
  color: var(--oy-accent);
  font-family: var(--oy-font-display);
  font-weight: 700;
}
.oy-single-card-owned-locations {
  color: var(--oy-muted);
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

/* Storage breakdown: hover shows a tooltip, tap opens the menu. On touch devices
   the tooltip is suppressed so a tap does not fire both at once. */
.oy-storage-chip .oy-storage-chip-caret {
  color: var(--oy-accent) !important;
  opacity: .75;
}
.oy-storage-menu {
  background: var(--oy-surface);
  border: 1px solid var(--oy-border);
  border-radius: 12px;
  color: var(--oy-body-text);
}
@media (hover: none) {
  .oy-storage-tip { display: none !important; }
}
@media (hover: hover) and (pointer: fine) {
  .oy-storage-chip .oy-storage-chip-caret { opacity: .45; }
  .oy-storage-chip:hover .oy-storage-chip-caret { opacity: 1; }
}
.oy-single-card-inventory,
.q-card.oy-single-card-inventory { background: rgba(203,166,247,.035); }
.oy-single-card-set-list { overflow: hidden; }
.oy-single-card-set-header {
  background: rgba(203,166,247,.07);
  border-bottom: 1px solid var(--oy-border);
  color: var(--oy-muted);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.oy-single-card-set-row {
  border-bottom: 1px solid rgba(255,255,255,.055);
  color: var(--oy-body-text);
}
.oy-single-card-set-row:last-child { border-bottom: 0; }
.oy-single-card-set-row:hover { background: rgba(255,255,255,.025); }
.oy-single-card-chart {
  background: rgba(255,255,255,.02);
  border: 1px solid var(--oy-border);
  border-radius: 12px;
  overflow: hidden;
}
.oy-single-card-table-header { background: rgba(203,166,247,.07); }
.oy-single-card-table-row {
  border-bottom: 1px solid rgba(255,255,255,.055);
  transition: background .15s;
}
.oy-single-card-table-row:hover { background: rgba(203,166,247,.055); }

@media (max-width: 639px) {
  /* Collection controls: keep fields and view toggles usable at phone widths. */
  .oy-collection-title-row {
    align-items: flex-start !important;
    flex-wrap: wrap !important;
    gap: 16px;
  }
  .oy-collection-view-toggle {
    display: flex !important;
    width: 100%;
  }
  .oy-collection-view-toggle > .q-btn {
    flex: 1 1 50%;
    min-height: 44px;
    min-width: 0;
  }
  .oy-collection-controls {
    align-items: stretch !important;
    gap: 12px !important;
  }
  .oy-collection-controls > .q-field {
    flex: 1 1 100%;
    width: 100% !important;
    min-width: 0 !important;
  }
  .oy-collection-controls > .nicegui-row {
    max-width: 100%;
    flex-wrap: wrap;
  }
  .oy-collection-controls > .nicegui-row .q-field {
    flex: 1 1 180px;
    min-width: 0;
  }
  .oy-collection-controls > .q-space { display: none; }
  .oy-collection-pagination {
    flex-wrap: wrap;
    gap: 8px;
    padding-inline: 4px !important;
  }

  /* Use a normal block stack so dynamically injected responsive utilities
     cannot leave the details one viewport to the right of the artwork. */
  .oy-single-card-shell {
    display: block !important;
    height: 100% !important;
    min-height: 0 !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
  }
  .oy-single-card-art {
    border-right: 0;
    border-bottom: 1px solid var(--oy-border);
    height: 48dvh !important;
    min-height: 280px;
    max-height: 430px;
    padding: 20px 44px 20px 20px !important;
  }
  .oy-single-card-art::after { inset: 6%; }
  .oy-single-card-image {
    width: auto !important;
    height: 100% !important;
    max-width: 100% !important;
    max-height: 100% !important;
    aspect-ratio: 59 / 86;
  }
  .oy-single-card-image .q-img__container,
  .oy-single-card-image .q-img__image {
    width: 100% !important;
    height: 100% !important;
  }
  .oy-single-card-image .q-img__image { object-fit: contain !important; }
  .oy-single-card-content {
    width: 100% !important;
    height: auto !important;
    overflow-y: visible !important;
  }
  .q-btn.oy-single-card-close {
    position: fixed !important;
    top: max(12px, env(safe-area-inset-top)) !important;
    right: max(12px, env(safe-area-inset-right)) !important;
    width: 48px;
    height: 48px;
    min-width: 48px;
    min-height: 48px;
    background: var(--oy-ink) !important;
    border-color: rgba(203,166,247,.65);
    color: var(--oy-text) !important;
    box-shadow: 0 6px 22px rgba(0,0,0,.55);
    z-index: 10000 !important;
  }
  .q-btn.oy-single-card-close .q-btn__content { font-size: 32px; }
}

@media (max-width: 767px) {
  /* Deck builder: stack the library above the deck and constrain every child. */
  .oy-deck-builder-header {
    align-items: stretch !important;
    flex-wrap: wrap !important;
    gap: 10px !important;
  }
  .oy-deck-builder-header > .nicegui-column { flex: 1 0 100%; }
  .oy-deck-builder-header > .q-field {
    flex: 1 1 230px;
    width: auto;
    min-width: 0 !important;
  }
  .oy-deck-builder-header > .q-space { display: none; }
  .oy-deck-builder-header .q-btn,
  .deck-builder-library-controls .q-btn,
  .deck-builder-deck-area .q-btn {
    min-width: 44px;
    min-height: 44px;
  }
  #deck-builder-container {
    display: flex !important;
    flex-direction: column !important;
    align-items: stretch !important;
    width: 100%;
    min-width: 0;
    overflow: hidden;
  }
  .deck-builder-search-results {
    position: relative !important;
    top: auto !important;
    width: 100% !important;
    height: min(58dvh, 520px) !important;
    min-height: 400px;
    flex: none !important;
  }
  .deck-builder-library-header {
    align-items: stretch !important;
    flex-wrap: wrap !important;
    gap: 8px;
  }
  .deck-builder-library-header > .oy-display { width: 100%; }
  .deck-builder-library-controls {
    width: 100%;
    flex-wrap: wrap !important;
  }
  .deck-builder-library-controls .q-field {
    flex: 1 1 96px;
    width: auto !important;
    min-width: 0;
  }
  .deck-builder-library-controls .q-separator { display: none; }
  #gallery-list {
    grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)) !important;
  }
  .deck-builder-deck-area {
    width: 100%;
    min-width: 0;
    flex: none !important;
  }
  .deck-builder-deck-area > .oy-card { padding: 10px !important; }
  #deck-main, #deck-extra, #deck-side {
    grid-template-columns: repeat(auto-fill, minmax(76px, 1fr)) !important;
    gap: 8px !important;
  }
  .q-dialog__inner--right > .q-card {
    width: min(100vw, 384px) !important;
    max-width: 100vw;
  }
}

/* ---------- Shell (top bar) ---------- */
.q-drawer {
  background: var(--oy-surface);
  border-right: 1px solid var(--oy-border);
}
.q-header, .oy-topbar, .oy-modebar {
  background: var(--oy-bg);
  border-bottom: 1px solid var(--oy-border);
}
.oy-topbar, .oy-modebar {
  width: 100%;
  min-height: 52px;
}
.oy-wordmark {
  font-family: var(--oy-font-display);
  font-size: 18px;
  font-weight: 600;
  color: var(--oy-text);
  letter-spacing: -0.2px;
  cursor: pointer;
}
.oy-mode {
  font-family: var(--oy-font-body);
  font-size: 14px;
  color: var(--oy-muted);
  cursor: pointer;
  padding: 6px 0;
  border-bottom: 2px solid transparent;
}
.oy-mode:hover { color: var(--oy-text); }
.oy-mode.active {
  color: var(--oy-text);
  font-weight: 600;
  border-bottom-color: var(--oy-accent);
}
.oy-collection-tab {
  font-size: 14px;
  color: var(--oy-muted);
  cursor: pointer;
  padding-bottom: 4px;
  border-bottom: 2px solid transparent;
}
.oy-collection-tab.active {
  color: var(--oy-text);
  font-weight: 600;
  border-bottom-color: var(--oy-accent);
}
.oy-search {
  background: var(--oy-surface);
  border: 1px solid var(--oy-border);
  border-radius: 2px;
  min-width: 240px;
}
.oy-phone-nav {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 40;
  background: var(--oy-surface-2);
  border-top: 1px solid var(--oy-border);
  display: none;
}
.oy-stamp {
  background: var(--oy-accent) !important;
  color: var(--oy-ink) !important;
  border-radius: 2px;
}
.oy-page { padding-bottom: 24px; }
@media (max-width: 639px) {
  .oy-desktop-only { display: none !important; }
  .oy-phone-nav { display: flex; }
  .oy-page { padding-bottom: 72px; }
}
@media (min-width: 1024px) {
  .oy-phone-only { display: none !important; }
}

.oy-logo, .oy-wordmark {
  font-family: var(--oy-font-display);
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.2px;
  color: var(--oy-text);
}
.oy-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.oy-mark {
  width: 18px;
  height: 24px;
  display: block;
  flex: none;
}
.oy-form-error {
  min-height: 1.25rem;
  color: var(--oy-accent);
  font-size: 14px;
}
.oy-navlabel {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1.6px;
  color: #6d6784;
  padding: 0 12px;
}
.oy-navrow {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--oy-muted);
  cursor: pointer;
  transition: background .15s, color .15s;
}
.oy-navrow:hover { color: var(--oy-text); background: var(--oy-surface-2); }
.oy-navrow.active {
  background: var(--oy-surface-2);
  color: var(--oy-text);
}
.oy-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--oy-accent);
  box-shadow: 0 0 8px var(--oy-accent);
  flex: none;
}
</style>
"""


# ---------- Dark mode ----------
# The light desk above stays exactly as it is. Dark mode only redefines the
# tokens, so every rule that reads var(--oy-*) follows. The choice lives in
# localStorage ('auto', 'light' or 'dark') and is applied in <head> before the
# first paint, so a page never flashes the wrong theme.
THEME_STORAGE_KEY = 'oy-theme'
THEME_MODES = ('auto', 'light', 'dark')

_DARK_TOKENS = """
  color-scheme: dark;
  --oy-bg: #16130f;
  --oy-surface: #1f1b16;
  --oy-surface-2: #2b261f;
  --oy-border: #3b352c;
  --oy-border-soft: #2f2a23;
  --oy-text: #f1ebe0;
  --oy-body-text: #d9d1c3;
  --oy-muted: #a99f90;
  --oy-faint: #8e8576;
  --oy-soft: #a99f90;
  --oy-placeholder: #7b7367;
  --oy-accent: #e07a68;
  --oy-accent-deep: #c9604e;
  --oy-blue: #82b597;
  --oy-green: #82b597;
  --oy-red: #e07a68;
  --oy-yellow: #d3ac64;
  --oy-gold: #d3ac64;
  --oy-ink: #16130f;
"""

# ui.colors() writes Quasar's palette as an inline style on <body>, so the dark
# values need !important to win over it.
_DARK_QUASAR = """
  --q-primary: #f1ebe0 !important;
  --q-secondary: #e07a68 !important;
  --q-accent: #82b597 !important;
  --q-dark: #2b261f !important;
  --q-positive: #82b597 !important;
  --q-negative: #e07a68 !important;
  --q-info: #a99f90 !important;
  --q-warning: #d3ac64 !important;
"""


def _dark_rules(root: str) -> str:
    return f"""
{root} {{{_DARK_TOKENS}}}
{root} body {{{_DARK_QUASAR}}}
{root} ::-webkit-scrollbar-thumb {{ background-color: #4a4338; }}
{root} ::-webkit-scrollbar-thumb:hover {{ background-color: #6b6255; }}
{root} .q-chip.bg-primary, {root} .q-chip.bg-primary .q-icon {{ color: var(--oy-ink) !important; }}
{root} .oy-navlabel {{ color: var(--oy-faint); }}
{root} .border-gray-300 {{ border-color: var(--oy-border); }}
/* Quasar's .text-white is !important inside @layer quasar, and a layered
   !important beats an unlayered one. Only an earlier layer (base) can win, so
   filled buttons get dark ink on the bright dark-mode colours from there. */
@layer base {{
  {root} .q-btn.bg-primary, {root} .q-btn.bg-secondary, {root} .q-btn.bg-accent,
  {root} .q-btn.bg-positive, {root} .q-btn.bg-negative, {root} .q-btn.bg-info,
  {root} .q-btn.bg-warning, {root} .q-chip.bg-primary, {root} .q-chip.bg-secondary {{
    color: var(--oy-ink) !important;
  }}
}}
"""


_THEME_SCRIPT = """
<script>
(function () {
  var KEY = '%(key)s';
  var MODES = ['auto', 'light', 'dark'];
  function read() {
    try {
      var value = localStorage.getItem(KEY);
      return MODES.indexOf(value) >= 0 ? value : 'auto';
    } catch (error) {
      return 'auto';
    }
  }
  function sync(mode) {
    document.querySelectorAll('.oy-theme-switch [data-mode]').forEach(function (button) {
      button.setAttribute('aria-checked', String(button.getAttribute('data-mode') === mode));
    });
  }
  function apply(mode) {
    document.documentElement.setAttribute('data-oy-theme', mode);
    sync(mode);
  }
  window.oySetTheme = function (mode) {
    if (MODES.indexOf(mode) < 0) mode = 'auto';
    try { localStorage.setItem(KEY, mode); } catch (error) {}
    apply(mode);
  };
  apply(read());
  document.addEventListener('DOMContentLoaded', function () { sync(read()); });
  window.addEventListener('load', function () { sync(read()); });
  window.addEventListener('storage', function (event) {
    if (event.key === KEY) apply(read());
  });
})();
</script>
""" % {'key': THEME_STORAGE_KEY}

THEME_HEAD = _THEME_SCRIPT + f"""
<style>
html {{ color-scheme: light; }}
{_dark_rules('html[data-oy-theme="dark"]')}
@media (prefers-color-scheme: dark) {{
{_dark_rules('html[data-oy-theme="auto"]')}
}}

/* ---------- Theme switch ---------- */
.oy-theme-switch {{
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  background: var(--oy-surface);
  border: 1px solid var(--oy-border);
  border-radius: 2px;
  flex: none;
}}
.oy-theme-switch button {{
  all: unset;
  box-sizing: border-box;
  width: 34px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 2px;
  color: var(--oy-muted);
  cursor: pointer;
  transition: background .15s, color .15s;
}}
.oy-theme-switch button:hover {{ color: var(--oy-text); }}
.oy-theme-switch button:focus-visible {{ outline: 2px solid var(--oy-accent); outline-offset: 1px; }}
.oy-theme-switch svg {{ width: 16px; height: 16px; display: block; }}
.oy-theme-menu-row {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 16px;
  min-height: 48px;
}}
html[data-oy-theme="auto"] .oy-theme-switch [data-mode="auto"],
html[data-oy-theme="light"] .oy-theme-switch [data-mode="light"],
html[data-oy-theme="dark"] .oy-theme-switch [data-mode="dark"] {{
  background: var(--oy-surface-2);
  color: var(--oy-text);
}}
</style>
"""

# IconKit outline icons (monitor, sun, moon), inlined so the switch needs no request.
_THEME_ICONS = {
    'auto': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M9 20h6M12 16v4"/></svg>',
    'light': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9 6.7 6.7M17.3 17.3l1.8 1.8M4.9 19.1 6.7 17.3M17.3 6.7l1.8-1.8"/></svg>',
    'dark': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11.5 3A8.5 8.5 0 0 0 20 14.5 8.5 8.5 0 1 1 11.5 3Z"/></svg>',
}
_THEME_LABELS = {'auto': 'Sistema', 'light': 'Claro', 'dark': 'Oscuro'}

THEME_SWITCH_HTML = (
    '<div class="oy-theme-switch" role="radiogroup" aria-label="Tema">'
    + ''.join(
        f'<button type="button" role="radio" aria-checked="false" data-mode="{mode}" '
        f'title="{_THEME_LABELS[mode]}" aria-label="{_THEME_LABELS[mode]}" '
        f'onclick="window.oySetTheme(\'{mode}\')">{_THEME_ICONS[mode]}</button>'
        for mode in THEME_MODES
    )
    + '</div>'
)


def theme_switch():
    """Three-way theme switch: system, light, dark. It works in the browser only."""
    return ui.html(THEME_SWITCH_HTML, sanitize=False)

def apply_theme():
    """Applies the paper-and-ink desk. Stamp red is the only loud color."""
    ui.colors(
        primary='#1e1a15',
        secondary='#9c2f24',
        accent='#2c5a42',
        dark='#e6ddcc',
        positive='#2c5a42',
        negative='#9c2f24',
        info='#5c554b',
        warning='#8a6830',
    )
    ui.dark_mode().disable()


def install_global_styles() -> None:
    """Install the design system once for all NiceGUI pages."""
    ui.add_head_html(GLOBAL_CSS, shared=True)
    ui.add_head_html(THEME_HEAD, shared=True)
    ui.add_head_html(pwa.HEAD_HTML, shared=True)


def page_header(title: str, subtitle: str | None = None):
    """Standard oversized editorial page heading."""
    header = ui.column().classes('gap-1')
    with header:
        ui.label(title).classes('oy-h1')
        if subtitle:
            ui.label(subtitle).classes('oy-sub')
    return header
