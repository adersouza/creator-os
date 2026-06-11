# Juno33 UI Library Migration Matrix

Date: 2026-06-03

## Implementation Status

Fast-track replacement started after the slower component-by-component migration
proved too expensive. New route screens should use the Nova facade
(`NovaScreen`, `NovaHeader`, `NovaSection`, `NovaToolbar`, `NovaCard`,
`NovaStat`, `NovaDataPanel`, `NovaEmpty`) and wire existing hooks/actions/data
into fresh shadcn/Nova presentation. `/content` is restored as a first-class
posted-content surface and now uses this facade.

Foundation and P1 are implemented as of 2026-06-03. The app now has
Juno-facing wrappers for shadcn-backed `Button`, `Card`, dialog primitives,
form controls, `DataTable`, `JunoChartContainer`, `Command`, `Avatar`,
`Progress`, `DropdownMenu`, `ContextMenu`, `Popover`, `Tooltip`, `Empty`, and
related low-risk controls. Public app imports remain under
`@/components/ui/*`; route files should not import directly from
`src/components/shadcn/*`.

Completed P1 route surfaces:

- Settings shared form controls and routine tab controls.
- Calendar filters, post detail sheet controls, and calendar command palette.
- Accounts filters, group panel/rail inputs, and account row context menu.
- Inbox search/empty states, reply composer, assignment menu/avatar, and inbox
  command palette.
- Reports list/table search and report editor controls.
- Reliability cards, issue rows, status indicators, progress metrics, and empty
  states.
- Handoff low-risk form/card controls.
- Analytics P1 tables: `FleetAnomalyGrid`, `TopBottomPostsTable`,
  `HashtagPerformanceTable`, `AudienceOverlapTable`.
- Analytics P1 routine charts: `ViewsBySourceChart`, `FormatMixWowTrend`,
  `FollowerFlowTile`, `IGReachSourceMixTile`.

P1 stabilization follow-up completed on 2026-06-03:

- Browser-facing analytics, inbox, and accounts requests no longer serialize
  large account or conversation-key arrays into long URLs on the checked P1
  routes.
- `JunoChartContainer` now owns a stable chart height so Recharts mounts against
  a measurable parent.
- Full Vitest, `compat:check`, `typecheck`, and production build now pass after
  aligning `@/api/*` Vitest aliases, restoring dashboard reliability tiles,
  covering `campaign_factory_post_links` in GDPR export/deletion, and updating
  stale inspiration-service test mocks for the centralized `apiFetch` contract.

P2A operational UI slice completed on 2026-06-03:

- Billing plan cards, current-plan summary, billing-cycle toggle, usage bars,
  loading placeholders, and comparison matrix now use Juno `Card`, `Button`,
  `ToggleGroup`, `Progress`, `Skeleton`, and `StatusPill` wrappers.
- Publishing setup, readiness panels, phone setup checklist, and first-post
  start card now use Juno `Card`, `Button`, `Progress`, `Empty`, and existing
  tag/status primitives while preserving push, telemetry, and navigation
  behavior.
- Attribution controls/loading states and Smart Links analytics now use Juno
  `Select`, `ToggleGroup`, `Skeleton`, `Progress`, `Card`, and `RaycastTag`
  wrappers. The custom confidence ring and bespoke attribution visual classes
  remain intact.
- Focused P2A tests cover publishing actions/readiness states and Smart Links
  loading/ranked/hidden states.

P2B approval queue shell slice completed on 2026-06-03:

- Approval Queue filter shell, status segmented control, search/risk controls,
  loading state, and empty states now use Juno `Card`, `ToggleGroup`, `Input`,
  `Select`, `Skeleton`, and `Empty` wrappers.
- Approval decision, revision, execution, timeline, and payload-editor service
  behavior remains unchanged for a later deeper workflow QA pass.

Visual foundation + P2C dashboard polish slice started on 2026-06-03:

- Added Juno-owned `BrandLogo`/`IntegrationLogo`, `MatrixLoader`, and
  shadcn-backed `StatCard` patterns so SVGL, Dot Matrix, and Blocks.so-inspired
  patterns can be adopted behind stable app APIs.
- Extended `JunoChartContainer` with optional routine chart variants for future
  EvilCharts-inspired chart cleanup.
- Applied the first dashboard polish pass to the processing rail, platform
  identity chips, ops-health metrics, unhealthy account rows, and readiness
  metric cards while preserving dashboard signature atoms.

Explicit P2 deferrals:

- Composer, Links, Auth, Landing, Autopilot, Ideas, Listening,
  Content Library, app shell/sidebar, scheduling grids, and deeper Billing,
  Publishing, Attribution, and Approval Queue workflow redesigns.
- Analytics bespoke visuals: dashboard signature atoms, hero sparklines,
  `SvgSparkline`, `EngagementVelocityChart` box-plot,
  `NonFollowerReachTrendTile` diagnostic band, swimlanes, trajectory panels, and
  other domain-specific visualization layouts.
- Aceternity remains reference-only until a dedicated P3 polish pass. No
  Aceternity dependency or copied animated block is part of P1.

## Scope

This audit maps Juno's current React UI surface to concrete shadcn/ui and
Aceternity migration targets. The intent is not a broad visual redesign. The
safe migration path is to keep Juno tokens and product-specific visuals intact
while replacing brittle primitives, repeated hand-built controls, routine
tables, and routine charts.

## Audit Evidence

- Project context: Vite, React 19, Tailwind v4, shadcn Radix base, lucide icons,
  UI alias `@/src/components/shadcn`.
- shadcn registry coverage checked through the CLI: 363 entries across UI
  primitives, blocks, examples, chart examples, themes, and internal sidebar
  pieces.
- Aceternity registry coverage checked through the CLI: 269 entries across UI
  effects, blocks, auth, pricing, heroes, empty states, illustrations, upload,
  timelines, code, and marketing sections.
- SVGL checked as the canonical source for third-party app/site SVG logos.
- Dot Matrix checked as a shadcn-compatible loader source with 55+ React,
  TypeScript, Tailwind, and shadcn loaders.
- Blocks.so checked as an open-source shadcn/Tailwind block source, including
  15 stats blocks plus AI, command menu, dialog, file upload, form, grid list,
  auth, onboarding, sidebar, and table categories.
- EvilCharts checked as an open-source shadcn/Recharts chart-pattern source
  covering area, line, bar, composed, radar, pie, radial, Sankey, background,
  tooltip, legend, and chart config pages.
- App source scanned: 294 TSX files under `src/pages` and `src/components`.
- Files with replaceable UI patterns: 252 by heuristic scan. The actionable set
  below excludes tests, icon-only SVG helpers, tiny atoms where custom markup is
  intentional, and the new adapters already added.

Heuristic flags included raw `input`/`select`/`textarea`, raw table markup,
custom card/border panels, dialog roles, empty states, skeletons, filter controls,
custom dropdown/popover code, and SVG/Recharts chart surfaces.

## Registry Targets

### shadcn/ui

Use as the primary internal app source:

- Primitives: `button`, `button-group`, `card`, `badge`, `separator`, `alert`,
  `empty`, `skeleton`, `spinner`, `progress`, `kbd`.
- Forms: `field`, `form`, `input`, `input-group`, `textarea`, `select`,
  `checkbox`, `switch`, `radio-group`, `slider`, `input-otp`.
- Navigation and layout: `sidebar`, `tabs`, `breadcrumb`, `scroll-area`,
  `resizable`, `accordion`, `collapsible`, `navigation-menu`, `pagination`.
- Overlays: `dialog`, `alert-dialog`, `sheet`, `drawer`, `popover`,
  `hover-card`, `tooltip`, `dropdown-menu`, `context-menu`, `menubar`.
- Data: `table`, `chart`, `avatar`, `carousel`, `command`.
- Blocks/examples: `dashboard-01`, `sidebar-01` through `sidebar-16`,
  `login-01` through `login-05`, `calendar-01` through `calendar-32`,
  `data-table-demo`, chart examples for area/bar/line/pie/radar/radial/tooltip.

### Aceternity

Use selectively where animated polish is valuable and isolated:

- Good app candidates: `file-upload`, `timeline`, `code-block`, `terminal`,
  `stateful-button`, `sticky-banner`, `empty-state-with-cards`,
  `empty-state-with-stacked-cards`, `uptime-status-illustration`,
  `chat-conversation`, `keyboard`, `tooltip-card`.
- Good marketing/auth candidates: `simple-login-with-grid-lines`,
  `login-with-socials-and-email`, `login-signup-minimal`, `hero-with-chat-input`,
  `hero-section-with-tabs`, `bento-grid`, `feature-section-bento-skeletons`,
  `animated-testimonials`, `world-map`, `logo-cloud-*`, `pricing-*`.
- Avoid inside the production app shell unless intentionally isolated:
  WebGL/shader backgrounds, `animated-modal`, Aceternity sidebars/navbars,
  `floating-dock`, `3d-globe`, `webcam-pixel-grid`, heavy parallax, shooting
  star/meteor backgrounds, and decorative hero effects.

### SVGL

Use `https://svgl.app` as the source of truth for third-party brand/app logos
used in product UI and marketing UI:

- Good candidates: Instagram, Threads-adjacent social apps, Meta/Google/GitHub,
  Stripe, Supabase, Vercel, analytics tools, AI providers, and integration
  logos.
- Replace one-off local or manually drawn third-party logo SVGs only after
  checking license/source suitability and light/dark rendering.
- Keep Juno-owned brand assets (`Sigil33`, Juno wordmarks, app-specific glyphs)
  custom.
- Prefer a small internal `BrandLogo`/`IntegrationLogo` mapping so route files
  do not import arbitrary remote SVGs.

### Dot Matrix

Use `https://dotmatrix.zzzzshawn.cloud` as the preferred future source for
matrix-style loading states where a richer loader is useful:

- Candidate command pattern: `npx shadcn@latest add @dotmatrix/[loader-name]`.
- Good candidates: dashboard/analytics long-running refresh states, command
  palette pending states, report generation, AI content generation, publishing
  setup checks, and first-run loading moments.
- Avoid replacing every compact skeleton. For dense tables and cards, keep
  `Skeleton`; use Dot Matrix only where a visible loader improves perceived
  activity without adding noise.
- Selected loaders should be wrapped behind a Juno `MatrixLoader` adapter and
  tokenized before route-level use.

### Blocks.so

Use `https://blocks.so` as a reference and shadcn registry source for stats and
operational blocks. Registry configuration is now present in `components.json`:

```json
"@blocks-so": {
  "url": "https://blocks.so/r/{name}.json"
}
```

Candidate command pattern:

```bash
npx shadcn@latest add @blocks-so/[component-name]
```

High-value block categories:

- Stats: `stats-01` through `stats-15`, especially trending, borders, card
  layout, badges, links, status, circular progress, progress bars, segmented
  progress, usage breakdown, and value breakdown.
- Tables, command menu, dialogs, form layout, onboarding, sidebar, file upload,
  grid list, and auth blocks as reference sources.
- Use Blocks.so blocks as copy-in/reference material. Any installed block must
  be reviewed, tokenized, and adapted behind Juno wrappers before route use.

### EvilCharts

Use `https://evilcharts.com` as a chart-pattern source when its Recharts-based
examples are stronger than current routine analytics visuals:

- It already matches the current stack direction: EvilCharts is built with
  shadcn and Recharts, and this repo already has Recharts installed.
- Candidate command pattern from the docs:

```bash
npx shadcn@latest add @evilcharts/{chart-name}
```

- Best-fit Juno candidates: routine area, line, bar, composed, radar, pie,
  radial, and Sankey charts; tooltip/legend/background treatments; chart config
  examples.
- Keep bespoke diagnostic visuals custom unless an EvilCharts pattern improves
  clarity without losing domain-specific behavior.

## Visual Improvement Backlog

This backlog captures the app-wide visual upgrades requested after the initial
shadcn migration. Treat these as design-quality targets, not permission to
install everything at once. Each item should be implemented through Juno
wrappers/adapters and verified route by route.

### App And Integration Logos

Source: SVGL.

- Create a local `BrandLogo` or `IntegrationLogo` adapter for third-party
  products and services. Candidate names include Instagram, Threads/Meta,
  Google, GitHub, Stripe, Supabase, Vercel, PostHog, OpenAI, Anthropic, and
  other AI/provider/integration logos used in the app.
- Replace inconsistent one-off third-party SVGs in account rows, auth buttons,
  billing/provider surfaces, analytics integrations, settings integrations,
  landing trust rows, and smart-link attribution panels.
- Keep all Juno-owned branding custom. Do not fetch remote SVGs at runtime from
  route components.

### Loader System

Source: Dot Matrix plus existing Juno `Skeleton`.

- Add a Juno `MatrixLoader` adapter for long-running visible work:
  dashboard refresh, analytics refresh, report generation, AI generation,
  publishing setup checks, command-palette async search, import/sync jobs, and
  Smart Links attribution recompute states.
- Keep compact cards, tables, route placeholders, and repeated row placeholders
  on `Skeleton`; Dot Matrix should be used only where motion communicates
  meaningful background work.
- Prefer one or two tokenized Dot Matrix variants across the app rather than a
  different loader on every page.

### Stats And KPI Blocks

Source: Blocks.so stats blocks plus Juno cards/progress/badges.

- Build on the Juno `StatCard`/`DashboardCard` primitives inspired by Blocks.so stats
  layouts: trending delta, bordered metrics, compact card layout, status
  badges, circular progress, progress bars, segmented progress, usage
  breakdown, and value breakdown.
- Apply first to medium-risk but high-value surfaces:
  `DashboardV2`, `Billing`, `Reliability`, `Analytics`, `Attribution`,
  `Reports`, `PublishingSetup`, `Autopilot`, and `Links`.
- Replace manually assembled stat rows where they repeat the same structure:
  label, value, trend, status, progress, action link. Keep bespoke dashboard
  signature atoms where the visual is domain-specific.

### Charts And Analytical Visuals

Source: EvilCharts, shadcn chart patterns, Recharts, and existing
`JunoChartContainer`.

- Review EvilCharts area, line, bar, composed, radar, pie, radial, Sankey,
  tooltip, legend, background, and chart config pages before each chart slice.
- Add optional Juno chart variants inspired by EvilCharts:
  `routine-area`, `routine-line`, `routine-bar`, `source-mix`, `radial-score`,
  `funnel-flow`, and `sankey-flow` if the source patterns improve clarity.
- Candidate replacements:
  `ViewsBySourceChart`, `FollowerFlowTile`, `IGReachSourceMixTile`,
  `FormatMixWowTrend`, `ContentMixHealthTile`, `DiscoveryFunnel`,
  `SmartLinksAnalytics`, report charts, billing usage charts, and reliability
  SLO charts.
- `FormatMixWowTrend` has completed the first shadcn/Nova shell pass: its
  populated routine bar chart now uses direct `EvidenceCard` composition and
  semantic chart/text tokens while preserving the existing Recharts comparison
  and analytics hook. A later EvilCharts-inspired pass can refine chart styling
  once the surrounding route is fully clean.
- `CompetitorBenchmarkPanel` has completed the first shadcn/Nova shell pass:
  its populated benchmark state now uses direct `EvidenceCard` composition and
  semantic peer-stat/bullet-marker tokens while preserving the existing
  competitor benchmark hook, account resolution, listening deep-link, and
  investigate action.
- `ContentMixTernaryTile` has completed the first shadcn/Nova shell pass: its
  populated drift plot now uses direct `EvidenceCard` composition and semantic
  summary/SVG label tokens while preserving the existing content-mix hook,
  Instagram fallback behavior, rebalance action, investigate action, and custom
  ternary SVG math.
- `PostingCadenceHeatmapTile` has completed the first shadcn/Nova shell pass:
  its populated heatmap now uses direct `EvidenceCard` composition and shared
  `Badge` metadata while preserving the published-post query, account/group
  scoping, calendar deep-link, historical account hydration, and heatmap cell
  intensity math.
- `EqsForecastCiTile` has completed the first shadcn/Nova shell pass: its
  populated forecast now uses direct `EvidenceCard` composition, semantic
  forecast/source/legend labels, and the shared `Tooltip` wrapper while
  preserving the scoped EQS trend hook, forecast computation, confidence slider
  state, SVG forecast band, outlier detection, and investigate action.
- `DiscoveryFunnel` has completed the first shadcn/Nova shell pass: both
  populated branches now use direct `EvidenceCard` composition, a local
  semantic `FunnelBars` renderer, shared `Badge` correlation metadata, and
  Nova/zinc source/stat labels while preserving the fleet KPI hook, funnel
  correlation hook, account resolution, post-level converter list, and
  investigate actions.
- `ViewsBySourceChart` has completed the first shadcn/Nova shell pass: its
  `EvidenceCard`/`JunoChartContainer` routine area chart now uses semantic
  Nova/zinc axis tokens while preserving the source-mix hook, 100%-stacked
  normalization, tooltip adapter, and investigate action.
- Keep custom when the chart is diagnostic or signature: dashboard hero
  sparklines, `SvgSparkline`, `EngagementVelocityChart` box plot,
  `NonFollowerReachTrendTile`, swimlanes, trajectory panels, and scheduling
  grids.

### Dashboard Visual Polish

Sources: Blocks.so stats, EvilCharts, Dot Matrix, SVGL.

- Dashboard is already touched for P1 stabilization, but it still needs a
  dedicated visual-polish pass.
- Improve dashboard KPI/readiness tiles with Blocks.so-inspired stat structure:
  clearer trend deltas, status badges, progress states, and action links.
- Use EvilCharts only for routine mini charts that are not signature Juno atoms.
- Use Dot Matrix for refresh/processing states only if it improves perceived
  live activity without distracting from operational scanning.
- Add SVGL-backed provider/account logos where platform identity improves scan
  speed.

### Auth, Landing, And First-Run Polish

Sources: SVGL, Blocks.so auth/onboarding blocks, Aceternity marketing/auth
blocks.

- Auth pages can use SVGL logos for OAuth/provider buttons and shadcn/Blocks.so
  auth block structure while preserving existing auth contracts.
- Landing can use SVGL logo clouds and Aceternity/Blocks.so marketing blocks
  only in isolated sections. Avoid heavy WebGL/background effects unless the
  asset is clearly worth the cost.
- First-run/zero-data pages can use Aceternity empty-state blocks or Blocks.so
  onboarding layouts after they are tokenized and checked in dark mode.

### Product Surface Polish

Sources: shadcn, Blocks.so, Dot Matrix, Aceternity selectively.

- Composer: use shadcn forms/tabs/command, Dot Matrix for AI-generation waits,
  and Aceternity `file-upload` only if it fits the existing media workflow.
- Links: use Blocks.so stats/table ideas for link analytics and shadcn form
  controls for the editor; use Aceternity `link-preview`/`code-block` only
  behind local wrappers.
- Approval Queue: use Aceternity `timeline` and `code-block` for review history
  and payload diffs only after the decision/revision workflow has browser QA.
- Autopilot/Ideas/Listening: use Blocks.so stats/status patterns, shadcn
  forms/cards, and Dot Matrix only for async AI/operator states.

### Visual Guardrails

- Keep Juno tokens in `src/index.css` as the source of truth.
- Do not import registry components directly in route files. Adapt them behind
  `src/components/ui/*`, `src/components/analytics-*`, or another Juno-owned
  namespace first.
- Do not replace dense operational UIs with decorative marketing blocks.
- Every visual source import needs dark-mode, mobile, loading, empty, and
  authenticated-route browser QA.

## Phase Legend

- P0: Foundation adapters. Do first so route migrations are small and reversible.
- P1: Low-risk high-volume cleanup. Mostly forms, tables, menus, empty states.
- P2: Medium-risk product surfaces. Needs route-level QA and workflow checks.
- P3: Marketing/onboarding polish. Isolated, visual, and optional.
- Keep: Preserve custom implementation; only borrow lower-level primitives.

## Foundation Matrix

| Scope | Current files | Replace/adapt with | Phase | Risk | Notes |
|---|---|---|---:|---|---|
| Button primitive | `src/components/ui/Button.tsx`, repeated raw buttons in pages | shadcn `button` API adapted to Juno variants | P0 | Medium | Public variants/sizes preserved; old label-token usage removed from the shared button wrapper. |
| Card primitive | `src/components/ui/Card.tsx`, `.card` classes across routes | shadcn `card` composition adapted to Nova/zinc card anatomy | P0 | Medium | Route-level `.card`, `j33-*`, and `operator-*` usage should not be preserved in rebuilt surfaces. Keep public composition exports stable. |
| Dialog primitives | `Modal`, `Sheet`, `ConfirmDialog` | shadcn `dialog`, `sheet`, `alert-dialog` wrappers | P0 | Low | Internals are Radix/shadcn-backed; helper text and close affordances now use semantic muted tokens. |
| Dropdown/menu primitives | `DropdownMenu.tsx`, `ContextMenu.tsx`, `Popover.tsx`, `PortalDropdown.tsx` | shadcn `dropdown-menu`, `context-menu`, `popover`, `tooltip` | P0 | Medium | Preserve z-index strategy and portal behavior. Menu labels/items are old-token clean; replace `PortalDropdown` after verifying clipped-menu cases. |
| Form primitives | `Input.tsx`, `settings/shared.tsx`, raw route controls | shadcn `field`, `input`, `input-group`, `textarea`, `select`, `checkbox`, `switch`, `radio-group`, `slider` | P0 | Medium | Shared `Field`/`Input` wrappers are old-token clean and keep iOS 16px input sizing behavior. |
| Option sets | `PillSegmented.tsx`, `TogglePill.tsx`, manual filter pills | shadcn `toggle-group`, `tabs`, `button-group`, `select` | P0 | Medium | Use `ToggleGroup` for 2-7 choices, `Tabs` for page sections, `Select` for long lists. |
| Empty states | Repeated no-data panels and remaining local dashboard empty helpers | shadcn `empty`; Aceternity empty-state blocks for hero blanks only | P0/P3 | Low | Shared `EmptyState.tsx` and `EliteEmptyState.tsx` have been deleted. Keep compact shadcn empty variants for tables; use Aceternity only for first-run/marketing-like blanks. |
| Skeletons | `Skeleton.tsx`, `PageSkeletons.tsx`, repeated route skeletons | shadcn `skeleton`, `spinner` | P0 | Low | Keep route-specific skeleton layouts, normalize primitive class API. |
| Tables | `DataTable.tsx`, raw tables in analytics/calendar | shadcn `table` plus TanStack `data-table-demo` patterns | P0/P1 | Medium | `DataTable` adapter is old-token clean. Keep it as Juno API; migrate raw table call sites, not signature grids. |
| Charts | `JunoChart.tsx`, analytics SVG/Recharts tiles | shadcn `chart` patterns on Recharts | P0/P1 | Medium | Keep custom hero sparklines, dashboard atoms, and highly bespoke SVGs. |
| Brand/app logos | third-party logo SVGs and integration glyphs | SVGL-backed local logo mapping | P1/P2 | Low | Normalize Instagram, Meta, Google, GitHub, Stripe, Supabase, Vercel, AI/integration logos. Keep Juno brand assets custom. |
| Matrix loaders | repeated large loading states and long-running AI/report/publish loaders | Dot Matrix loaders behind a Juno `MatrixLoader` adapter | P2 | Medium | Do not replace compact table/card skeletons globally. Use for visible long-running states only. |
| Stats blocks | KPI/stat cards and usage summaries | Blocks.so stats blocks adapted behind Juno cards/progress/badges | P2 | Medium | Use as reference for dashboard, billing, reliability, analytics, attribution, and reports stats. |
| Toasts | `appToast`, `sonner` dependency | shadcn `sonner` | P1 | Low | Normalize action/error styling, leave service API unchanged. |
| Keyboard hints | scattered shortcut UI | shadcn `kbd` | P1 | Low | Useful in command palette, shortcut help, composer. |

## Route And Feature Matrix

| Area | Files | Current replaceable patterns | shadcn target | Aceternity target | Phase | Risk |
|---|---|---|---|---|---:|---|
| App shell | `Layout.tsx`, `ActivityPanel.tsx`, `Sidebar.tsx`, `MobileTabBar.tsx`, `mobile/*` | `ActivityPanel`, `MobileTopBar`, `MobileSection`, `MobileSegmented`, and `ShortcutsHelp` token strip complete; coordinated nav cleanup remains | `sidebar`, `scroll-area`, `tooltip`, `dropdown-menu`, `sheet`, `badge`, `separator` | Avoid Aceternity sidebar/nav | P2 partial | High |
| Command surfaces | `layout/CommandPalette.tsx`, `calendar/CommandPalette.tsx`, `inbox/CommandPalette.tsx`, `SlashMenu.tsx` | calendar command shell is old-token/surface clean; remaining command work is global/inbox/composer anatomy polish | `command`, `dialog`, `kbd`, `scroll-area`, `badge` | `terminal` only for marketing/demo | P1/P2 polish | Medium |
| Dashboard V2 | `DashboardV2.tsx`, `dashboard-v2/tiles/*`, `dashboard-v2/atoms/*` | cards, skeletons, custom charts, chips | `card`, `badge`, `empty`, `skeleton`, selective `chart` | Do not use animated blocks inside dashboard | Keep/P2 | High |
| Dashboard route skeletons | `skeletons/PageSkeletons.tsx` | 393 skeleton primitive usages | `skeleton`, `card` adapter | None | P1 | Low |
| Analytics shell | `Analytics.tsx`, `analytics-v2/ShellRow.tsx`, `HeroTile.tsx`, `InsightsRail.tsx`, `EvidenceTile*`, analytics support widgets | key support widgets token-clean; `analyticsShared` chart colors, `EQSTrendChart`, `InvestigatePanel`, `PlatformSpecificWidgets`, and `ContentInsightsPanel` raw/legacy controls replaced; shared `EvidenceTile*` shell, `HeroTile`, `InsightsRail`, export/date/cohort controls, hero sparkline fallback, `AudienceOverlapTable`, `MatrixCoordinateTile`, and `AnnotationSwimLanesTile` now semantic-token audited | `tabs`, `toggle-group`, `tooltip`, `empty`, `skeleton`, `card`, `badge`, `button`, `input`, `textarea` | None | P1/P2 partial | Medium |
| Analytics tables | `HashtagPerformanceTable.tsx`, `AudienceOverlapTable.tsx`, `TopBottomPostsTable.tsx`, `FleetAnomalyGrid.tsx` | `AudienceOverlapTable` populated state now uses direct `EvidenceCard` + `DataTable`; remaining tables need final bridge/semantic sweeps | `DataTable`, shadcn `table`, TanStack sorting | None | P1/P2 partial | Medium |
| Analytics routine charts | `ViewsBySourceChart.tsx`, `EngagementVelocityChart.tsx`, `NonFollowerReachTrendTile.tsx`, `EqsForecastCiTile.tsx`, `FollowerFlowTile.tsx`, `IGReachSourceMixTile.tsx` | `ViewsBySourceChart` and `IGReachSourceMixTile` are now semantic-token audited; remaining routine charts need chart-shell/style cleanup | `JunoChartContainer`, shadcn `chart` tooltip/legend patterns | None | P1/P2 partial | Medium |
| Analytics conversation/retention widgets | `QuoteReplyRatioTile.tsx`, `EngagerRetentionTile.tsx`, `ReplyDepthDistributionTile.tsx`, `GhostPostQueueTile.tsx`, `ConversationSystemPanel.tsx` | `QuoteReplyRatioTile`, `EngagerRetentionTile`, `ReplyDepthDistributionTile`, and `GhostPostQueueTile` are now semantic-token audited; `ConversationSystemPanel` shell/inner panels are shadcn/Nova clean | `EvidenceCard`, `Empty`, `Skeleton`, semantic list/stat rows | None | P2 partial | Medium |
| Analytics bespoke visuals | `HeroSparkline.tsx`, dashboard atom `Sparkline.tsx`, `DonutRing.tsx`, `BulletChart.tsx`, `TrajectoryPanel.tsx`, `DistributionInputsPanel.tsx`, `ConversationSystemPanel.tsx`, `AnnotationSwimLanesTile.tsx`, `OriginalityRiskTile.tsx`, `VanityQualityGapTile.tsx`, `IGFormatBreakdownTile.tsx` | custom SVG/positioned analytical visuals; `TrajectoryPanel`, `AnnotationSwimLanesTile`, `DistributionInputsPanel`, `ConversationSystemPanel`, `OriginalityRiskTile`, `VanityQualityGapTile`, and `IGFormatBreakdownTile` are now shadcn/Nova shell and semantic-token clean | Keep custom internals; use `card`, `tooltip`, `empty`, `skeleton` shells | None | Keep/P2 partial | High |
| Calendar route shell | `Calendar.tsx` | active route now uses `NovaScreen`, `NovaHeader`, `NovaSection`, `NovaToolbar`, `NovaStat`, `NovaDataPanel`, and `NovaCard`; FullCalendar remains the scheduling engine and URL/filter/drag/drop behavior is unchanged | shadcn/Nova screen/card/stat/data-panel composition around FullCalendar | None | P2 shell done / grid polish | Medium |
| Calendar filters | `CalendarFilterBar.tsx`, `CalendarHero.tsx` | raw-control strip complete; remaining work is final Nova density and date-picker polish | `calendar`, `popover`, `select`, `toggle-group`, `tabs`, `button-group` | None | P1 done / polish | Medium |
| Calendar detail/edit | `PostDetailSlideOver.tsx`, `RescheduleDiffCard.tsx`, `BulkActionBar.tsx` | raw-control/spacing/old-token strip complete in active slide-over; action menu/dialog and optional `Sheet` section composition polish remains | `sheet`, `field`, `select`, `input`, `textarea`, `dropdown-menu`, `alert-dialog` | None | P1 done / polish | Medium |
| Calendar matrices | `PostingStreakMatrix.tsx`, `PortfolioMatrix.tsx`, `MonthViewGrid.tsx`, `WeekViewGrid.tsx` | `PortfolioMatrix`, `MonthViewGrid`, `PostingStreakMatrix`, and WeekViewGrid header/day drawer are old-token clean; remaining matrix work is shadcn table/grid anatomy polish while preserving sticky grid and heatmap mechanics | shadcn `table` internals where possible | None | P2/Keep | High |
| Calendar post cards | `PostCardRow.tsx` | post card, quick-move menu, and hover preview are old-token/surface clean; remaining work is optional command/menu anatomy polish | `tooltip`, `dropdown-menu`, `card`, `badge` | None | P2 polish | Medium |
| Composer route | `Composer.tsx` | active route now uses `NovaScreen`/`NovaHeader`/`NovaSection`/`NovaCard`, shadcn `Sheet` mobile panels, and shadcn-backed mobile action buttons; route-level motion and old Composer mobile chrome removed | `field`, `input-group`, `textarea`, `select`, `toggle-group`, `tabs`, `card`, `button`, `sheet` | None | P2 shell done / support polish | High |
| Composer account picker | `AccountSelector.tsx` | popover + search + custom list rows | `combobox` pattern via `command` + `popover`, `avatar`, `badge` | None | P1 | Medium |
| Composer media | `MediaGrid.tsx`, `MediaUploadZone.tsx`, `VoiceContextFile.tsx` | file input, upload states, drag/drop, textarea | shadcn `input`, `textarea`, `progress`, `dialog` | `file-upload` for upload zone only | P2 | Medium |
| Composer option panels | `ThreadsOptionsPanel.tsx`, `InstagramOptionsPanel.tsx`, `SchedulingOptions.tsx`, `ComposerFormControls.tsx`, `VariantsLab.tsx`, `CritiquePanel.tsx`, `CrossPostDiffResolver.tsx` | form rows, popovers, segmented state, cards | `field`, `switch`, `checkbox`, `select`, `popover`, `card`, `separator`, `badge` | None | P2 | Medium |
| Inbox shell | `Inbox.tsx`, `InboxChrome.tsx`, `ConversationListPane.tsx`, `ThreadDetailPane.tsx`, `ThreadMessages.tsx`, `ContextRail.tsx` | route shell now uses `NovaScreen`, `NovaHeader`, `NovaDataPanel`, `NovaSection`, `NovaToolbar`, and `NovaEmpty`; raw-control/token strip complete and remaining work is final split-pane density/list anatomy | `resizable`, `scroll-area`, `input-group`, `empty`, `avatar`, `badge`, `tabs` | None | P2 shell done / polish | High |
| Inbox actions | `ReplyComposer.tsx`, `AssignmentChip.tsx`, `ConversationRow.tsx`, `ActionIconButton.tsx` | raw-control/token strip complete; interaction polish remains | `textarea`, `dropdown-menu`, `popover`, `tooltip`, `button`, `badge` | None | P1 done / polish | Medium |
| Accounts route | `Accounts.tsx`, `AccountListView.tsx`, `MobileAccounts.tsx`, `AccountsFilterBar.tsx`, `AccountsHero.tsx` | raw-control/token strip complete; filter hero label residue is old-token clean; remaining work is table/list anatomy and mobile density | `input-group`, `select`, `toggle-group`, `table`, `empty`, `skeleton`, `badge`, `avatar` | `empty-state-with-cards` for zero-account first-run | P1/P2 polish | Medium |
| Account modals | `AccountDetailSlideOver.tsx`, `AccountReconnectModal.tsx`, `AccountMoveGroupModal.tsx`, `AccountGroupsPanel.tsx`, `AccountGroupsRail.tsx`, `AccountRowContextMenu.tsx` | raw-control/token strip complete; sheet/dialog anatomy polish remains | `sheet`, `dialog`, `alert-dialog`, `field`, `input`, `dropdown-menu`, `context-menu` | None | P1 done / polish | Medium |
| Settings shell | `Settings.tsx` | raw-control/token strip complete; side-tab anatomy polish remains | `tabs`, `sidebar` section primitives, `scroll-area`, `badge` | None | P1/P2 polish | Medium |
| Settings forms | `ProfileTabContent.tsx`, `WorkspaceTabContent.tsx`, `SecurityTabContent.tsx`, `APITabContent.tsx`, `WebhooksTabContent.tsx`, `VoiceProfileEditor.tsx`, `VoiceProfilesEditorTab.tsx`, `CohortSharingCard.tsx`, `NotificationsTabContent.tsx`, `AppearanceTabContent.tsx`, `DataExportCard.tsx`, `DeletionStatusTab.tsx` | raw visible controls/token strip complete; only hidden avatar/workspace-logo file inputs remain as upload plumbing; form/card anatomy polish remains | `field`, `input`, `input-group`, `textarea`, `select`, `switch`, `checkbox`, `alert`, `separator`, `alert-dialog`, `card` | None | P1 done / polish | Medium |
| Billing | `Billing.tsx` | raw-control/token strip complete; pricing/comparison density polish remains | `card`, `badge`, `button-group`, `tabs`, `progress`, `table`, `separator`, `tooltip` | Aceternity `pricing-*` only as reference, not direct app block | P2 polish | Medium |
| Links route | `Links.tsx`, `LinkDetailPane.tsx`, `BlockListEditor.tsx`, `LinkRow.tsx`, `LinkPagePreview.tsx`, `AIEnhancePanel.tsx`, `PixelExtensionsPanel.tsx`, `EmptyDetail.tsx` | raw-control/token strip complete; old Links material page scope removed; shared `Field`/`FieldLabel` now owns visible editor labels; link editor anatomy polish remains | `field`, `input-group`, `select`, `textarea`, `tabs`, `dropdown-menu`, `card`, `empty`, `tooltip`, `table` | `link-preview`, `code-block`, `empty-state-with-stacked-cards` | P2 polish | High |
| Reports | `Reports.tsx`, `ReportEditor.tsx` | raw-control/token strip complete; editor now uses shared `Sheet`; table/editor density polish remains | `DataTable`, `input-group`, `select`, `sheet`, `field`, `tabs`, `dropdown-menu`, `empty` | `timeline` for report run history if added | P1/P2 polish | Medium |
| Approval queue | `ApprovalQueue.tsx` | raw-control/token strip complete; payload editor, diff/timeline, and detail-card anatomy remain | `tabs`, `input-group`, `select`, `textarea`, `field`, `card`, `badge`, `alert-dialog`, `scroll-area`, `accordion` | `timeline`, `code-block` for payload diffs | P2 polish | High |
| Autopilot | `Autopilot.tsx`, `AutopilotModePages.tsx` | route shell, mode frame, replay/agent/queue/conditions/health panels now use `NovaScreen`, `NovaHeader`, `NovaSection`, `NovaToolbar`, and `NovaDataPanel`; service calls, replay/retry, queue settings, and shortcuts are preserved; remaining work is density/browser QA and deeper table polish | `tabs`, `field`, `input`, `select`, `textarea`, `card`, `empty`, `skeleton`, `badge`, `progress`, `table` | `timeline`, `stateful-button`, `sticky-banner` for run status | P2 shell done / polish | High |
| Ideas | `Ideas.tsx` | route shell now uses `NovaScreen`, `NovaHeader`, `NovaCard`, `NovaDataPanel`, `NovaSection`, `NovaToolbar`, and `NovaEmpty`; capture panel, generated queue, inspector, status shelves, hidden screenshot upload plumbing, and Composer handoff are behavior-preserved; remaining work is only deeper form/column density QA | `field`, `input-group`, `select`, `textarea`, `tabs`, `card`, `empty`, `badge` | `bento-grid` only for inspiration gallery if isolated | P2 shell done / polish | Medium |
| Listening | `Listening.tsx` | route shell now uses `NovaScreen`, `NovaHeader`, `NovaSection`, `NovaStat`, `NovaToolbar`, and `NovaDataPanel`; KPI strip, monitor form, signal sections, side panels, workflow actions, user-setting persistence, and Ideas handoff are behavior-preserved; remaining work is density/browser QA | `field`, `input-group`, `select`, `textarea`, `tabs`, `card`, `empty`, `badge`, `alert` | None | P2 shell done / polish | Medium |
| Attribution | `Attribution.tsx`, `analytics/widgets/system/SmartLinksAnalytics.tsx` | active token/material-row strip complete; remaining work is custom journey/table layout anatomy | `select`, `JunoChart`, `card`, `empty`, `skeleton`, `DataPanel`, `table` | None | P2 polish | Medium |
| Reliability | `Reliability.tsx` | raw-control/token strip complete; remaining work is API usage row/table anatomy polish | `card`, `badge`, `progress`, `alert`, `table`, `button` | `uptime-status-illustration` only for marketing/status explanation | P1 done / polish | Low |
| Handoff | `Handoff.tsx` | raw controls and old semantic tokens stripped; follow-up form now uses shared `Field`/`Input`/`Textarea`; remaining work is mobile workflow QA and form/list anatomy polish | `field`, `input`, `textarea`, `button`, `card`, `alert`, `separator` | None | P1 strip done / polish | Low |
| Publishing setup | `PublishingSetup.tsx`, `PublishingReadinessPanel.tsx`, `PhoneSetupChecklist.tsx`, `PublishingStartCard.tsx` | raw-control/token strip complete; readiness/checklist cards now use DashboardCard/ListRow anatomy; setup panel polish remains | `card`, `progress`, `button`, `badge`, `alert`, `accordion` | `stateful-button` if carefully adapted | P2 polish | Medium |
| Content library | `ContentLibrary.tsx`, `MediaView.tsx`, `ContentHero.tsx`, `RecentStrip.tsx`, `UnavailablePanel.tsx`, `shared.tsx` | raw-control/token strip complete except hidden upload input plumbing; media-card density and upload/empty-state polish remain | `card`, `aspect-ratio`, `carousel`, `empty`, `skeleton`, `select`, `input-group` | `file-upload`, `empty-state-with-pictures`, `empty-state-with-cards` | P2 polish | Medium |
| Auth | `Login.tsx`, `Signup.tsx`, `ResetPassword.tsx`, `InviteAccept.tsx`, `Welcome.tsx`, `OAuthCallback.tsx`, `AuthCallback.tsx`, `AuthLayout.tsx` | old `auth-*` visual classes and raw visible controls stripped; final shadcn auth-block polish and SVGL provider logos remain | shadcn `login-03`/`login-04`, `field`, `input`, `button`, `card`, `alert`, `input-otp` | `simple-login-with-grid-lines`, `login-signup-minimal`, avoid `premium-auth-split` WebGL | P3 strip done / polish | Medium |
| Landing/legal/shared report | `Landing.tsx`, `LegalPage.tsx`, `SharedReport.tsx` | landing/legal token strip done; `LegalPage` no longer uses `legal-prose`; shared report polish remains | shadcn `card`, `accordion`, `navigation-menu`, `button` | `hero-with-chat-input`, `hero-section-with-tabs`, `bento-grid`, `animated-testimonials`, `logo-cloud-*`, `faqs-*` | P3 strip done / polish | Medium |

## File-Level Candidate Appendix

The following are the highest-signal file candidates from the scan. Files not
listed here either have only tiny atom-level styling, tests, icon SVGs, or
intentional custom visuals that should not drive migration sequencing.

### P1: Low-Risk Operational Replacements

| File | Replaceable surface | Target |
|---|---|---|
| `src/components/calendar/CalendarFilterBar.tsx` | raw-control strip complete; date/filter polish remains | `calendar`, `popover`, `input`, `select`, `toggle-group` |
| `src/components/calendar/PostDetailSlideOver.tsx` | raw-control/spacing/old-token strip complete; action/dialog and `Sheet` composition polish remains | `sheet`, `field`, `select`, `input`, `textarea` |
| `src/components/calendar/CommandPalette.tsx` | old-token/surface strip complete; command list density polish remains | `command`, `dialog`, `kbd` |
| `src/components/accounts/AccountsFilterBar.tsx` | search and filters | `input-group`, `select`, `toggle-group` |
| `src/components/accounts/AccountGroupsPanel.tsx` | inputs, confirm actions | `field`, `input`, `alert-dialog`, `button` |
| `src/components/accounts/AccountGroupsRail.tsx` | group list controls | `input`, `button`, `empty`, `badge` |
| `src/components/accounts/AccountRowContextMenu.tsx` | context actions | `context-menu`, `dropdown-menu` |
| `src/components/inbox/AssignmentChip.tsx` | assignment menu | `dropdown-menu`, `avatar`, `badge` |
| `src/components/inbox/ReplyComposer.tsx` | reply textarea/actions | `textarea`, `button`, `tooltip`, `dropdown-menu` |
| `src/components/inbox/ConversationListPane.tsx` | search, empty states | `input-group`, `empty`, `scroll-area` |
| `src/components/settings/ProfileTabContent.tsx` | profile form | `field`, `input`, `button` |
| `src/components/settings/WorkspaceTabContent.tsx` | workspace form/selects/theme controls | `field`, `select`, `input`, `button-group`, `card` |
| `src/components/settings/SecurityTabContent.tsx` | confirm dialogs and security rows | `alert-dialog`, `button`, `badge`, `alert` |
| `src/components/settings/APITabContent.tsx` | API key controls | `field`, `input`, `dialog`, `alert` |
| `src/components/settings/WebhooksTabContent.tsx` | endpoint form and toggles | `field`, `input`, `checkbox`, `button`, `table` |
| `src/components/settings/VoiceProfileEditor.tsx` | modal form | `dialog`, `field`, `textarea`, `input`, `tabs` |
| `src/components/settings/VoiceProfilesEditorTab.tsx` | textarea and action buttons | `textarea`, `button`, `card` |
| `src/pages/Handoff.tsx` | input/textarea/action cards | `field`, `input`, `textarea`, `card`, `button` |
| `src/pages/Reliability.tsx` | SLO cards and issue rows | `card`, `alert`, `progress`, `badge` |
| `src/pages/Reports.tsx` | list table, filters, empty state | `DataTable`, `input-group`, `select`, `empty` |
| `src/components/reports/ReportEditor.tsx` | shared `Sheet` report editor; checkbox-grid density polish remains | `sheet`, `field`, `input`, `select`, `button-group` |

### P1/P2: DataTable And Chart Expansion

| File | Replaceable surface | Target |
|---|---|---|
| `src/components/analytics-v2/evidence/HashtagPerformanceTable.tsx` | raw table | `DataTable`, shadcn `table` |
| `src/components/analytics-v2/evidence/AudienceOverlapTable.tsx` | raw table | `DataTable`, shadcn `table` |
| `src/components/calendar/PortfolioMatrix.tsx` | old-token strip complete; wide raw table anatomy remains | shadcn `table` internals; keep sticky grid behavior |
| `src/components/calendar/PostingStreakMatrix.tsx` | old-token strip complete; wide sticky raw table anatomy remains | shadcn `table` internals; keep custom heatmap cells |
| `src/components/analytics-v2/evidence/EngagementVelocityChart.tsx` | routine chart | `JunoChart`, shadcn `chart` pattern |
| `src/components/analytics-v2/evidence/NonFollowerReachTrendTile.tsx` | routine trend chart | `JunoChart`, shadcn `chart` pattern |
| `src/components/analytics-v2/evidence/EqsForecastCiTile.tsx` | forecast controls/chart | `JunoChart`, `input`, `tooltip` |
| `src/components/analytics-v2/evidence/FollowerFlowTile.tsx` | routine flow chart | `JunoChart` |
| `src/components/analytics-v2/evidence/IGReachSourceMixTile.tsx` | routine source mix | `JunoChart` |
| `src/components/analytics/ContentInsightsPanel.tsx` | older analytics cards and charts | `card`, `JunoChart`, `empty` |
| `src/components/analytics/widgets/explorer/SelfCompareDeepDive.tsx` | comparison bars/skeletons | `card`, `skeleton`, `JunoChart` if generalized |
| `src/components/analytics/widgets/system/SmartLinksAnalytics.tsx` | cards/skeleton bars | `card`, `skeleton`, `progress` |

### P2: High-Volume Product Surfaces

| File | Replaceable surface | Target |
|---|---|---|
| `src/pages/Composer.tsx` | visible raw controls cleaned; remaining polish is larger card/form anatomy | `field`, `input-group`, `textarea`, `select`, `toggle-group`, `tabs`, `card` |
| `src/components/composer/AccountSelector.tsx` | popover search and list | `command`, `popover`, `avatar`, `badge` |
| `src/components/composer/MediaGrid.tsx` | media action controls | `button`, `textarea`, `dropdown-menu`, `tooltip` |
| `src/components/composer/MediaUploadZone.tsx` | upload form/drop area | Aceternity `file-upload` plus shadcn `progress` |
| `src/components/composer/ThreadsOptionsPanel.tsx` | platform options | `field`, `switch`, `input`, `popover` |
| `src/components/composer/InstagramOptionsPanel.tsx` | platform options | `field`, `switch`, `input`, `popover` |
| `src/components/composer/SchedulingOptions.tsx` | date/time fields | `calendar`, `popover`, `input`, `field` |
| `src/components/composer/ComposerFormControls.tsx` | input/select | `field`, `input`, `select` |
| `src/components/composer/SlashMenu.tsx` | slash command UI | `command`, `popover` or `dialog` |
| `src/pages/Links.tsx` | smart-link table/search/filters | `DataTable`, `input-group`, `empty`, `card` |
| `src/components/links/LinkDetailPane.tsx` | large editor form | `field`, `input`, `textarea`, `tabs`, `card` |
| `src/components/links/BlockListEditor.tsx` | many raw inputs/selects/textareas | `field`, `input`, `select`, `textarea`, `accordion` |
| `src/components/links/LinkRow.tsx` | dropdown actions | `dropdown-menu`, `tooltip`, `badge` |
| `src/components/links/AIEnhancePanel.tsx` | dialog/action card | `dialog`, `button`, `card` |
| `src/components/links/PixelExtensionsPanel.tsx` | input/card panel | `field`, `input`, `card` |
| `src/pages/ApprovalQueue.tsx` | review filters, payload editor | `tabs`, `field`, `select`, `textarea`, `code-block`, Aceternity `timeline` |
| `src/pages/Autopilot.tsx` | mode controls/cards/skeletons | `tabs`, `field`, `select`, `card`, `progress`, `empty` |
| `src/components/autopilot/AutopilotModePages.tsx` | mode forms | `field`, `input`, `card`, `button` |
| `src/pages/Ideas.tsx` | form controls and gallery cards | `field`, `select`, `textarea`, `card`, `empty` |
| `src/pages/Listening.tsx` | filters/forms/cards | `field`, `select`, `textarea`, `alert`, `empty` |
| `src/pages/Billing.tsx` | token strip complete; pricing cards/comparison table polish remains | `card`, `badge`, `progress`, `table`, `tabs`, `button-group` |
| `src/pages/ContentLibrary.tsx` | token strip complete; skeleton/empty-state polish remains | `skeleton`, `empty`, Aceternity empty-state blocks |
| `src/components/content-library/MediaView.tsx` | token strip complete; filter/media-card polish remains | `input-group`, `select`, `aspect-ratio`, `card` |
| `src/components/content-library/shared.tsx` | old label-token fallback stripped; only semantic Nova tokens remain | `badge`, `empty`, `StatCard` |

### P3: Marketing, Auth, And First-Run Polish

| File | Replaceable surface | Target |
|---|---|---|
| `src/pages/auth/Login.tsx` | raw login form | shadcn `login-03` or Aceternity `simple-login-with-grid-lines` |
| `src/pages/auth/Signup.tsx` | raw signup form | shadcn `login-04` adapted to signup |
| `src/pages/auth/ResetPassword.tsx` | password form | shadcn `field`, `input`, `button`, `alert` |
| `src/pages/auth/Welcome.tsx` | onboarding controls | shadcn `tabs`, `field`, `select`; Aceternity `multi-illustration-bento` only if isolated |
| `src/pages/auth/InviteAccept.tsx` | invite card/actions | shadcn `card`, `button`, `alert` |
| `src/components/layout/AuthLayout.tsx` | auth shell visual | shadcn auth block structure; avoid heavy WebGL |
| `src/pages/Landing.tsx` | marketing page | Aceternity hero/bento/testimonial/logo/FAQ blocks; shadcn nav/buttons |
| `src/pages/legal/LegalPage.tsx` | legal nav/content cards | shadcn `accordion`, `card`, `breadcrumb`, `scroll-area` |
| `src/pages/SharedReport.tsx` | public report cards | shadcn `card`, `badge`, `separator` |

### Keep Custom Or Adapter-Only

| File/family | Reason | Allowed replacement |
|---|---|---|
| `dashboard-v2/atoms/*` | Signature dashboard micro-visuals and compact analytics atoms | Only `tooltip`, `badge`, `empty`, `skeleton` where ergonomic |
| `analytics-v2/hero/HeroSparkline.tsx` | Signature custom sparkline | Keep custom |
| `analytics-v2/evidence/TrajectoryPanel.tsx` | Bespoke trajectory layout | Keep custom; use `card`/`tooltip` only |
| `analytics-v2/evidence/DistributionInputsPanel.tsx` | Bespoke distribution calculations and comparison layout; shell/inner panels now use `EvidenceCard` and semantic Nova/zinc card/list anatomy | Keep hook/calculation internals |
| `analytics-v2/evidence/ConversationSystemPanel.tsx` | Bespoke conversation-health scoring and dial visualization; shell/inner panels now use `EvidenceCard` and semantic Nova/zinc card/list/chart anatomy | Keep hook/scoring/dial internals |
| `analytics-v2/evidence/AnnotationSwimLanesTile.tsx` | Custom timeline lane visualization; shell/loading/empty states now use `EvidenceCard`/`Empty`/`Skeleton` | Keep custom lane internals |
| `calendar/MonthViewGrid.tsx`, `WeekViewGrid.tsx` | Scheduling grid is domain-specific | Keep grid; use shadcn overlays/menus |
| `components/ui/Sigil33.tsx`, `icons/BrandIcons.tsx`, `ui/icons/sf.tsx` | Brand/icons | Keep custom |
| `components/charts/SvgSparkline.tsx` | Tiny inline sparkline utility | Keep custom |
| `dashboard/polish.tsx` | Shared Juno polish/brand atoms | Keep; only bridge to shadcn if duplication becomes painful |

## Execution Plan

1. Install shadcn source components in small batches with `--dry-run` first:
   `button card badge separator alert empty skeleton spinner field input
   input-group textarea select checkbox switch radio-group slider tabs
   toggle-group dropdown-menu popover tooltip table pagination command
   scroll-area sheet dialog alert-dialog`.
2. Review generated source files and adapt tokens to Juno instead of adopting
   stock shadcn styling verbatim.
3. Update foundation wrappers first. Public imports should remain stable:
   `@/components/ui/Button`, `Card`, `Modal`, `Sheet`, `ConfirmDialog`,
   `FilterSelect`, `PillSegmented`, `DataTable`, `JunoChart`.
4. Migrate P1 files by category: settings forms, filters, menus, empty states,
   raw analytics tables, routine charts.
5. Migrate P2 route surfaces one product workflow at a time with browser QA.
6. Add Aceternity only after source review and dependency review. Place copied
   app-safe Aceternity components under a clearly named local namespace, not in
   the shadcn primitive folder.

## Verification Per Phase

- `npm run compat:check`
- focused tests for touched wrappers/routes
- `npx vitest run` and document unrelated existing failures if still present
- `npm run build`
- Browser QA for each migrated route in light and dark mode
- Explicit overlay checks: Escape, backdrop click, focus restore, clipping,
  mobile drawer behavior, and row action menus
