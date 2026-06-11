// Single source of truth for floating-UI z-index stacks.
// Before this, ComposerModal rendered at 80, PostAutopsyModal at 150, and the
// Activity panel at 40 — a toast on top of the Activity panel would render
// under a Composer modal, etc. One ladder, one file.
export const Z = {
  // Page chrome (sticky topbar, sidebar) — substrate level.
  chrome: 20,
  // Floating menus / dropdowns portaled to body (filter chips, saved views).
  // Above page chrome, below slide-overs and modals so an open menu doesn't
  // shine through a modal that opens on top of it.
  popover: 80,
  // Right-side slide-overs (Activity, Account detail).
  sheet: 60,
  sheetBackdrop: 55,
  // Centered modals (Composer, PostAutopsy, destructive confirms).
  modal: 100,
  modalBackdrop: 95,
  // Command palette always sits above modals (Cmd+K from inside a modal is valid).
  palette: 120,
  paletteBackdrop: 115,
  // Transient surfaces — toasts, leader-key indicator.
  toast: 200,
} as const;

export type ZLevel = keyof typeof Z;
