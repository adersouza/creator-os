# shadcn/Nova Frontend Rebuild Plan

## Summary

Juno33 is moving from an incremental UI-library migration to a real frontend
presentation rebuild. The backend, routes, hooks, services, auth, billing,
analytics fetching, and product behavior stay intact. The visual and component
layer should be rebuilt around shadcn/ui, the Nova/zinc preset direction, and
Juno oxblood as the primary action color.

This document is the source of truth for future frontend rebuild slices. It
exists to prevent the app from accumulating several competing visual systems.

## Fast-Track Replacement Rule

Future slices should prefer replacing route presentation over untangling old
JSX. Build fresh shadcn/Nova route screens, wire the existing hooks/actions/data
back in, then swap the active route to the new screen. Old route/component files
are feature checklists, not markup to preserve. If a page is too tangled or has
poor information hierarchy, nuke the visible frontend and rebuild it around
Nova primitives while keeping backend contracts intact.

The canonical replacement vocabulary is now:

- `NovaScreen` for the route canvas.
- `NovaHeader` for page title, metadata, filters, and actions.
- `NovaSection`, `NovaToolbar`, `NovaCard`, `NovaStat`, `NovaDataPanel`, and
  `NovaEmpty` for route-level screen composition.

These Nova names are a facade over the existing shadcn-backed Juno wrappers, so
new routes can move quickly without bypassing the app-owned wrapper layer.

## Final Library Stack

- **shadcn/ui**: primary component and composition system.
- **Radix UI**: accessibility and interaction primitives under shadcn.
- **Tailwind v4**: tokenized styling layer through `src/index.css`.
- **Lucide React**: default icon system.
- **Recharts + shadcn Chart**: routine analytics and dashboard charts.
- **TanStack Table + TanStack Virtual**: data tables and long lists.
- **Blocks.so**: stats/KPI/card structure reference and selective registry source.
- **EvilCharts**: routine chart pattern reference and selective chart source.
- **SVGL**: local third-party provider logos.
- **Motion**: subtle product transitions.
- **Dot Matrix**: selective long-running AI/sync/processing loaders only.

## Explicit Non-Goals

- Do not add Mantine, MUI, HeroUI, GlueStack, Tamagui, NativeBase, AG Grid, or
  broad Aceternity product UI.
- Do not use paid Untitled UI assets.
- Do not import raw registry files directly into routes.
- Do not keep rebuilding product screens on top of old `operator`, `dv2`,
  `j33`, Raycast-style, or terminal-console surfaces.
- Do not change backend contracts, billing behavior, auth flows, analytics
  fetching, telemetry names, or route URLs as part of visual rebuild work.

## Frontend Rules

- Product routes import Juno-owned wrappers from `src/components/ui/*` and
  `src/components/layout/*`.
- Generated shadcn source stays under `src/components/shadcn/*`.
- Blocks.so, EvilCharts, SVGL, Dot Matrix, and any future registry component
  must be reviewed and wrapped before app use.
- shadcn composition is the default: `CardHeader`, `CardTitle`,
  `CardDescription`, `CardContent`, `CardFooter`, `Field`, `InputGroup`,
  `Table`, `Badge`, `Tabs`, `Command`, `Dialog`, `Sheet`, `DropdownMenu`,
  `Skeleton`, and `Empty`.
- Prefer semantic Tailwind tokens over custom color values.
- Use Nova/zinc surfaces, Juno oxblood for primary/action/selected states, clean
  labels, restrained borders, and clear card anatomy.

## Premium SaaS Product Rules

The research direction is clear: a premium shadcn app is not a gallery of
components. It is a task-shaped product system. Juno33 should feel expensive
because every page answers a real operator question, not because every surface
has more decoration.

### Product Language

- **Editorial clarity:** each screen should make it obvious what changed, why
  it matters, and what to do next.
- **Operational confidence:** publishing state, failed jobs, inbox workload,
  account health, and analytics sync should feel inspectable without dumping
  backend internals into primary screens.
- **Analytical depth without intimidation:** default screens summarize; the next
  interaction explains. Deep diagnostics belong in analytics tabs, detail
  sheets, logs, or advanced views.

### Visual Discipline

- Neutrals carry the app; oxblood carries intent. Use zinc/neutrals for
  background, cards, table rows, separators, and secondary chart series. Reserve
  oxblood for primary actions, selected states, focus, and one highlighted
  metric or entity.
- Use sentence case for tabs, table headers, labels, and buttons. Avoid
  shouty/internal labels unless a real domain term requires it.
- Treat SVGL/provider logos as identity markers, not decoration. Use them in
  account rows, integration cards, OAuth surfaces, and connection badges. Use
  monochrome logos in dense views and full-color logos only when identity is the
  primary content.
- Keep Lucide sizing systematic: navigation icons, inline icons, icon buttons,
  and empty-state icons should not drift independently.

### Widget Anatomy

The app should converge on a small set of repeatable widget shapes:

- **KPI cards:** label, value, delta, comparison period, and one evidence cue
  such as a sparkline, ratio, or concise footer.
- **Evidence cards:** finding first, metric or chart second, next action third.
- **Action cards:** operational pressure such as failed posts, disconnected
  accounts, approval bottlenecks, and inbox backlog.
- **Feed/list cards:** identity, primary line, meta line, and quiet quick
  actions.
- **Chart cards:** one question at a time, direct labels when possible, gray for
  secondary series, oxblood for the highlighted series, and a footer explaining
  time window or comparison logic.
- **Insight panels:** what happened, why it matters, and where to inspect next.

### Interaction Rules

- Tables should use a real toolbar for search, filters, sort state, settings,
  export, and global actions. Row detail should open in a right-side sheet when
  the table would otherwise become cramped.
- Dialogs are for finite decisions and confirmations. Sheets are for
  investigation, row detail, replies, post inspection, and settings edits that
  should preserve page context.
- Tabs are page-level mental models, not a way to hide overflow inside every
  card. Avoid tabs inside cards inside sheets unless the workflow genuinely
  requires it.
- The command surface should unify navigation and current-view actions: switch
  account, schedule post, open failed posts, open inbox filters, generate
  rewrite, jump to account, and switch workspace.
- Loading states should be tiered: skeletons for initial page/card/table loads,
  inline button loaders for saves/actions, progress bars for upload and bulk
  publish, and Dot Matrix only for long-running AI/sync/processing moments.

### Benchmark Behaviors To Emulate

- Linear: contextual command menu, saved views, keyboard-first creation.
- Vercel: clean scope-aware sidebar and commandable project navigation.
- Stripe: overview plus high-importance notifications and inspectable detail.
- Attio: table/kanban/view switching over the same underlying data.
- PostHog: dashboards for reusable views, notebooks/insight panels for
  narrative analysis.
- Supabase and Resend: calm high-level screens with logs and event detail
  available when intentionally opened.
- Typefully, Later, Sprout, and Metricool: focused composer, planning calendar,
  split-pane inbox, and social-specific operational workflows.

## Preset Status

- The project is now formally configured as shadcn `style: nova` in
  `components.json`.
- `npx shadcn@latest apply bcizC7EG --only theme -y` has been run
  successfully.
- The exact preset code `bcizC7EG` decodes to Nova, zinc, red, Lucide, Inter,
  default radius, subtle menu accent, and default menu color.
- Juno intentionally diverges from the exact preset code by replacing preset
  red with Juno oxblood in both shadcn token layers and app token layers.
  Because of that brand override, `npx shadcn@latest info --json` resolves the
  current project as a nearby custom Nova/zinc preset rather than reporting
  `bcizC7EG` verbatim.
- The failed `--only theme,font` run exposed a missing upstream
  `font-inter` registry item for this project style. Font direction is handled
  locally by putting Inter first in the app font stack and keeping Satoshi as a
  fallback.

## Rebuild Order

1. **Foundation**
   - Lock global tokens, app shell layout, and shadcn wrapper contracts.
   - Create or finalize shadcn-first primitives: `AppShell`, `PageHeader`,
     `StatCard`, `DashboardCard`, `EvidenceCard`, `FormSection`, and
     `DataPanel`.

2. **Dashboard + Analytics**
   - Rebuild high-visibility KPI strips, cards, evidence panels, routine charts,
     and tables with the new primitives.
   - Preserve existing hooks, services, URLs, filters, refresh behavior, and
     account scope behavior.
   - Remove route-level dependence on old `operator`, `dv2`, `j33`, and
     Raycast-style visual classes as each surface is rebuilt.

3. **Settings + Billing + Accounts + Inbox**
   - Rebuild operational forms, tables, filters, menus, empty states, loading
     states, and row actions with shadcn-backed wrappers.
   - Preserve billing service calls, account actions, inbox assignment behavior,
     and settings persistence.

4. **Composer + Links + Calendar**
   - Rebuild higher-risk workflow surfaces after the core shell and core product
     screens are stable.
   - Keep publish, scheduling, media, smart-link, drag/drop, and calendar
     behavior unchanged.

5. **Auth + Landing**
   - Rebuild public/auth surfaces with shadcn auth and marketing patterns.
   - Use SVGL-backed provider logos where appropriate.

6. **Cleanup**
   - After each route group is migrated, delete unused old visual wrappers,
     legacy CSS, and abandoned compatibility classes.
   - Do not delete shared behavior helpers or data hooks during visual cleanup.

## First Implementation Slice

- Build or lock the shadcn-first and Nova-facing primitives:
  `AppShell`, `PageHeader`, `StatCard`, `DashboardCard`, `EvidenceCard`,
  `FormSection`, `DataPanel`, `NovaScreen`, `NovaHeader`, `NovaSection`,
  `NovaToolbar`, `NovaCard`, `NovaStat`, `NovaDataPanel`, and `NovaEmpty`.
- Rebuild `/dashboard`, `/analytics`, and `/content` visually around those
  primitives.
- Preserve all data hooks, services, route behavior, URLs, account scope, and
  telemetry.
- Only after the first slice is stable, install or adapt Blocks.so stats blocks
  as references for `StatCard` and dashboard KPI patterns.

## Slice Status

### Fast Track Started: Nova Route-Screen Facade + Content

- Added `NovaScreen` under `src/components/layout/*` and `NovaHeader`,
  `NovaSection`, `NovaToolbar`, `NovaCard`, `NovaStat`, `NovaDataPanel`, and
  `NovaEmpty` under `src/components/ui/*`.
- Restored `/content` as a first-class internal product surface and moved its
  visible route composition onto the Nova facade while preserving the existing
  `useTopPosts`, account/group scope, platform/window filters, composer links,
  content-library links, and post-detail deep links.
- Mobile More no longer exposes Billing as a day-to-day product destination.
  Billing remains routable and available through account/settings flows, but it
  is not part of the primary internal operator surface.
- This marks the strategy shift from incremental shell cleanup to route
  replacement: Composer and Calendar should be rebuilt with fresh Nova screens
  instead of preserving their current presentation.

### In Progress: Approved Library Adapter Pass

- shadcn/Nova remains the primary product UI system. Blocks.so, EvilCharts,
  SVGL, and Dot Matrix are approved supporting sources, but they enter the app
  through Juno-owned adapters instead of raw route-level registry imports.
- `BrandLogo` / `IntegrationLogo` provides local SVGL-style provider logos for
  platform and integration identity. Use it anywhere account, OAuth, analytics,
  billing, or provider context benefits from faster visual scanning.
- `MatrixLoader` is the approved Dot Matrix loader adapter. Use it only for
  long-running AI, sync, and processing states, not as a universal skeleton
  replacement.
- `NovaStat`, `NovaCard`, and `NovaDataPanel` are the Blocks.so-inspired
  stat/card anatomy layer: compact header, strong value hierarchy, badges,
  progress rails, action zones, and footer bands.
- `JunoChartContainer` remains the EvilCharts-inspired routine chart adapter
  on top of Recharts/shadcn chart patterns. Prefer it for routine line, bar,
  mix, source, and trend charts; keep bespoke diagnostic charts custom until
  their behavior can be preserved cleanly.
- Current visible adapter pass: Dashboard platform identity, dashboard refresh
  processing, Analytics investigation processing, Composer AI actions, and
  Links AI enhance now use approved adapters in product surfaces.

### Completed: Slice 1 — Foundation + Dashboard/Analytics Shells

- Added Juno-owned shadcn/Nova primitives under `src/components/ui/*` and
  `src/components/layout/*`:
  `AppScreen`, `PageHeader`, `StatCard`, `DashboardCard`, `EvidenceCard`,
  `FormSection`, and `DataPanel`.
- Replaced route-level `/dashboard` and `/analytics` dependencies on
  `OperatorPageHeader`, `RaycastTag`, `dv2-root`, and `operator-page`.
- Migrated the Analytics KPI strip, insight rail, evidence loading shell, and
  empty evidence shell to the new primitive layer.
- Preserved dashboard and analytics hooks, filters, account/group scope, CSV
  export, refresh behavior, tile error boundaries, and custom chart internals.
- Verification completed:
  `npm run typecheck`, `npm run compat:check`, focused wrapper tests,
  `npx vitest run`, `npm run build`, and local browser checks for `/dashboard`
  and `/analytics`.
- Shared shadcn-backed wrappers are now old-token clean for the active wrapper
  layer: `Field`, `Input`, `Tabs`, `ToggleGroup`, `PillSegmented`, `FilterChip`,
  `DropdownMenu`, `ContextMenu`, `Modal`, `Sheet`, `ConfirmDialog`, `DataTable`,
  `JunoChart`, `Avatar`, `MicroBadge`, `StatusPill`, and related small UI
  primitives no longer depend on old `text-label-*`,
  `var(--color-label-*)`, `color-card-elevated`, or `app-label` vocabulary.
  They now spell out Nova/zinc semantic tokens directly while keeping public
  imports and behavior stable.

### Important Remaining Work From Slice 1

- Dashboard and Analytics still contain bespoke inner tile/chart components,
  but active TSX no longer emits dashboard-v2 `dv2-*` classes or
  `var(--dv2-*)` token references in the cleaned dashboard/analytics surface.
- The legacy `dashboard-v2.css` compatibility stylesheet has been deleted
  after dashboard and analytics imports were removed and focused scans
  confirmed no active TSX references remain.
- `OperatorPageHeader` and `RaycastChrome` no longer have active imports and
  have been deleted. Remaining legacy compatibility is concentrated in
  dashboard/analytics inner tile internals. The shared `Tile`, `MetricCard`,
  `WidgetCard`, and `EmptyState` wrappers have also been removed after their
  active call sites moved to shadcn-backed card/empty composition.

### Completed Checkpoint: Dashboard/Analytics Widget Anatomy Sweep

- `/dashboard` now renders the full `DashboardV2` feature surface again via a
  thin `src/pages/Dashboard.tsx` wrapper. The simplified temporary dashboard
  page was removed from the active route so the All / Threads / Instagram
  views, hero briefing, fundamentals ribbon, live pulse, anomaly feed, ops
  health, readiness cards, scorecards, platform-specific tiles, mobile overview,
  URL state, keyboard shortcuts, composer open behavior, refresh behavior, and
  tile error boundaries are active again.
- Dashboard scorecard widgets now use `DashboardCard` header/action/content
  anatomy instead of a custom `dv2-scorecard-grid` shell and score-bullet
  header classes. The bullet chart itself remains custom because it is a
  compact bespoke visualization, but the surrounding widget presentation is
  shadcn/Nova card composition.
- Dashboard hero briefing now uses `DashboardCard`, `Badge`, and `Button`
  instead of `dv2-tile`, `dv2-briefing-*`, and raw visible buttons while
  preserving the same metric hooks, copy logic, scoped analytics/calendar
  navigation, and platform/timeframe inputs.
- Dashboard mobile overview visible text surfaces now use semantic Nova/zinc
  tokens instead of old `text-label-*` classes, so the restored phone-only
  overview no longer reintroduces the old small-window visual language in its
  touched paths.
- Dashboard readiness tiles now use the shadcn-backed `Button` wrapper and
  inline Nova panels instead of `MetricCard`, raw day buttons,
  `juno-widget-row`, and `space-y-*` presentation in the restored All view.
- Analytics `ViewsBySourceChart` now uses `EvidenceCard`, `Skeleton`, and
  `Empty` for loading, error, empty, and populated states. It no longer imports
  `EvidenceTile`/`EvidenceTileHeader` or emits `dv2-tile`/`dv2-tile-content`
  around the chart.
- Verification completed for this checkpoint:
  `npm run audit:legacy-ui`, `npm run compat:check`, focused widget/rebuild
  tests, and `npm run build`.
- `npm run typecheck` is currently blocked by unrelated dirty backend
  autoposter work in `api/_lib/handlers/auto-post/promptBuilder.ts`; the
  reported errors are competitor-pattern payload typing issues outside the UI
  files touched in this checkpoint.

### Completed Checkpoint: Analytics Routine Widget Sweep

- The analytics-v2 evidence folder no longer has direct `dv2-tile` or
  `dv2-tile-content` populated shells. `AudienceOverlapTable`,
  `PostingCadenceHeatmapTile`, `MatrixCoordinateTile`,
  `ContentMixTernaryTile`, `DistributionInputsPanel`, `TrajectoryPanel`,
  `ConversationSystemPanel`, `EqsForecastCiTile`,
  `AnnotationSwimLanesTile`, `FormatMixWowTrend`, `DiscoveryFunnel`, and
  `CompetitorBenchmarkPanel` now render their populated route-visible frames
  through `EvidenceTile`/`EvidenceCard`. Their hooks, account scope behavior,
  investigate actions, tables, and bespoke chart bodies are unchanged.
- The shared legacy `src/components/ui/EmptyState.tsx` wrapper has been
  deleted after repo scan confirmed no active imports. Remaining `EmptyState`
  names are local helper functions inside dashboard-v2 bespoke tiles and
  should be replaced when those tiles are swept.
- Current source scan still shows active `dv2-tile` islands in larger
  dashboard-v2 platform tile families including `ThreadsTiles`, `IgV2Tiles`,
  and related bespoke dashboard tiles.
- `HookClassLiftTile`, `StoriesFunnelTile`, and
  `ReplyDepthLeadersTile` now use `DashboardCard` shells. Their empty/loading
  states, rows, rank markers, and sort controls use shadcn-backed `Empty`,
  `Skeleton`, `Badge`, `Button`, and `ToggleGroup` wrappers where applicable.
  Data hooks, range state, scoped routes, calendar deep links, and miniature
  chart/SVG bodies are unchanged.
- `HookStrengthTile` and `LiveFirstSixHoursTile` now use `DashboardCard`
  shells with shadcn-backed `Badge`, `Button`, `Empty`, and `Skeleton`
  wrappers for headers, pager controls, loading, empty, and scope-mismatch
  states. Reel watch-time math, live-post queries, median comparisons,
  thumbnail rendering, and miniature chart bodies are unchanged.
- `BioLinkFunnelTile` now uses `DashboardCard`, `Badge`, `Button`, `Empty`,
  and `Skeleton` wrappers for its shell, active-link status, Smart Links CTA,
  and loading/empty states. The bio-link funnel hook, scoped `/links`
  navigation, click/conversion/revenue math, and source breakdown remain
  unchanged.
- `ConversationQualityTile` now uses `DashboardCard`, `Badge`, `Empty`, and
  `Skeleton` wrappers for its shell, range/status header, metric grid, and
  empty/loading states. The reply-depth hook, persisted range, reply tree
  derivation, and bespoke reply-tree visualization remain unchanged, but the
  tile no longer emits `dv2-*` classes or `var(--dv2-*)` tokens.
- `LivePulsePanel` now uses `DashboardCard`, `Badge`, `Button`, `Empty`,
  `Progress`, and `Skeleton` wrappers for the operating pulse shell, live-post
  pager, Smart Links progress, and reach-window rows. The live post query,
  smart-link click goal/summary hooks, audience weekday-hour matrix, calendar
  deep link, and scoped `/links` navigation remain unchanged.
- Verification completed for this checkpoint:
  `npm run audit:legacy-ui`, `npm run compat:check`,
  `npx vitest run src/components/ui/VisualFoundation.test.tsx`, and
  `npm run build`.
- `npm run typecheck` remains blocked by unrelated backend autoposter typing
  errors in `api/_lib/handlers/auto-post/promptBuilder.ts` and
  `api/_lib/handlers/auto-post/stateEvaluator.ts`.

- `FollowerFlowTile` now renders through `EvidenceCard` with shared shadcn
  `Empty` and `Skeleton` states. The Recharts bar body and follower-flow hook
  stay unchanged.
- `IGReachSourceMixTile` now renders through `EvidenceCard` with shadcn
  loading/empty shells and footer metadata instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, and `dv2-tile-content`.
- `HashtagPerformanceTable` now renders through `EvidenceCard`; its sort
  controls use `ToggleGroup` instead of raw visible buttons, and its table
  remains the shared TanStack-backed `DataTable`.
- Verification completed for this checkpoint:
  targeted banned-token scans on touched files, `npm run audit:legacy-ui`,
  `npm run compat:check`, focused `DataTable`/`JunoChart`/rebuild primitive
  tests, and `npm run build`.
- `npm run typecheck` remains blocked by the same unrelated dirty backend
  autoposter typing errors in `api/_lib/handlers/auto-post/promptBuilder.ts`.

### Completed Checkpoint: Fleet Anomaly Grid Shell Sweep

- `FleetAnomalyGrid` now renders through `EvidenceCard` instead of a
  `dv2-tile`/`dv2-tile-content` shell. The anomaly ranking, severity joins,
  account drill-in behavior, and platform-specific TanStack `DataTable`
  columns remain unchanged.
- The anomaly-only control now uses the shared `Button` wrapper instead of
  `FilterChip`, the show-all/collapse control no longer uses a raw visible
  `<button>`, and empty/loading states now use shadcn `Empty` and `Skeleton`.
- Legacy flag labels such as `anom-crit`, `anom-warn`, and `pill-mini` were
  replaced with the shared `Badge` wrapper.
- Verification completed for this checkpoint:
  targeted banned-token scan on `FleetAnomalyGrid`, `npm run audit:legacy-ui`,
  `npm run compat:check`, focused `DataTable`/rebuild primitive tests, and
  `npm run build`.
- `npm run typecheck` remains blocked by the same unrelated dirty backend
  autoposter typing errors in `api/_lib/handlers/auto-post/promptBuilder.ts`.

### Completed Checkpoint: Content Route Restore

- `/content` is restored as a real protected product route for published-post
  review and performance. It is no longer redirected to `/calendar`.
- The route is built as a shadcn/Nova surface using `AppScreen`, `PageHeader`,
  `StatCard`, `DashboardCard`, `Badge`, `Button`, `Tabs`, `Skeleton`, `Empty`,
  and `Separator`.
- The page reuses the existing `useTopPosts` data path, selected account/group
  scope, and calendar deep-link behavior, so no backend API or analytics
  contract changed.
- `/content-library` remains the media/assets library for uploads, assignment,
  and Composer handoff. It is linked from the new `/content` page instead of
  being treated as the only content surface.
- The active legacy UI audit now includes `src/pages/Content.tsx`, including
  raw visible control checks, so the restored page cannot reintroduce old
  `operator`, `dv2`, `j33`, Raycast, or raw-control presentation.
- Verification completed for this checkpoint:
  `npm run audit:legacy-ui`, `npm run compat:check`, and `npm run build`.
- `npm run typecheck` remains blocked by unrelated backend autoposter typing
  errors in `api/_lib/handlers/auto-post/promptBuilder.ts`.

### Completed Checkpoint: Analytics Insight + Post Table Sweep

- `InsightFeedRow` now uses shadcn-backed `Empty` and `Skeleton` states instead
  of local empty-state presentation. Insight feed fallback
  behavior, anomaly filtering, and route drill-in behavior remain unchanged.
- `InsightCard` now renders through `DashboardCard` and `Badge` instead of
  `dv2-tile`, `dv2-tile-content`, `ticker`, `pill-mini`, `text-label-*`, and
  `space-y-*` styling. Click and keyboard activation still route to the same
  account-scoped analytics destinations.
- `TopBottomPostsTable` now renders through `EvidenceCard`, shadcn
  `Empty`/`Skeleton`, and `ToggleGroup` instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, and raw visible toggle buttons. The
  Supabase-backed ranking hook, investigate action, ideas action, DataTable
  columns, row click behavior, and account/group scope inputs remain unchanged.
- `GhostPostQueueTile` now renders through `EvidenceCard`, shadcn
  `Empty`/`Skeleton`, and `Badge` instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, `dv2-tile-content`, `anom-*`, and
  `citation` styling. The Threads-only ghost-post hook, calendar review link,
  investigate action, per-account queue rows, and account scope behavior remain
  unchanged.
- Verification completed for this checkpoint:
  targeted banned-token scans on touched files, focused `DataTable`/rebuild
  primitive tests, `npm run audit:legacy-ui`, `npm run compat:check`, and
  `npm run build`.
- `npm run typecheck` remains blocked by unrelated dirty backend autoposter
  typing errors in `api/_lib/handlers/auto-post/promptBuilder.ts`.

### Completed Checkpoint: Analytics Format + Reply Depth Sweep

- `IGFormatBreakdownTile` now renders through `EvidenceCard` with shadcn
  `Empty` and `Skeleton` states instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, and `dv2-tile-content`. The Instagram
  format breakdown hook, account scoping, format rows, and QWE distribution
  bars remain unchanged. Its remaining `app-label` table header has also been
  replaced with explicit Nova/zinc label hierarchy and the file is now covered
  by the stricter semantic-token audit.
- `ReplyDepthDistributionTile` now renders through `EvidenceCard` with shadcn
  `Empty` and `Skeleton` states instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, `dv2-tile-content`, and `dv2-big-num`.
  The Threads reply-depth hook, investigate action, histogram buckets, and
  account/group scope inputs remain unchanged.
- Verification completed for this checkpoint:
  targeted banned-token scans on touched files plus the standard active UI
  audit, compat check, focused rebuild/DataTable tests, and production build.
- `npm run typecheck` remains blocked by unrelated dirty backend autoposter
  typing errors in `api/_lib/handlers/auto-post/promptBuilder.ts`.

### Completed Checkpoint: Analytics Conversation + Retention Sweep

- `QuoteReplyRatioTile` now renders through `EvidenceCard` with shadcn
  `Empty` and `Skeleton` states instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, `dv2-tile-content`, and `dv2-big-num`.
  The Threads quote/reply ratio hook, account scoping, account leaderboard,
  and investigate action remain unchanged.
- `EngagerRetentionTile` now renders through `EvidenceCard` and shared
  `Skeleton` loading state instead of `EvidenceTile`, `EvidenceTileHeader`,
  `dv2-tile`, and `dv2-tile-content`. The account resolution logic,
  engager-retention hook, stacked returning/new bar, top returning engager
  list, and investigate action remain unchanged.
- Verification completed for this checkpoint:
  targeted banned-token scans on touched files plus the standard active UI
  audit, compat check, focused rebuild/DataTable tests, and production build.
- `npm run typecheck` remains blocked by unrelated dirty backend autoposter
  typing errors in `api/_lib/handlers/auto-post/promptBuilder.ts`.

### Completed Checkpoint: Analytics Quality + Originality Sweep

- `VanityQualityGapTile` now renders through `EvidenceCard` with shadcn
  `Empty` and `Skeleton` states instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, `dv2-tile-content`, and `dv2-big-num`.
  The vanity-account hook, normalized period selection, quality-action bars,
  and investigate action remain unchanged. Its remaining old label and
  `var(--color-label-*)` rail colors have been replaced with semantic
  Nova/zinc tokens and the file is now covered by the stricter
  semantic-token audit.
- `OriginalityRiskTile` now renders through `EvidenceCard`, shadcn
  `Empty`/`Skeleton`, and `Badge` instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, `dv2-tile-content`, `dv2-big-num`, and
  old label classes. The originality-risk hook, risk dial SVG, closest-match
  comparison, account scope, and investigate action remain unchanged. Its
  closest-match and metric labels now use explicit Nova/zinc hierarchy and the
  file is now covered by the stricter semantic-token audit.
- `IGReachSourceMixTile` kept its existing `EvidenceCard`/`JunoChartContainer`
  shell while replacing its remaining old `var(--color-label-secondary)` axis
  tick token with `--color-muted-foreground`. The source-mix hook, chart data,
  tooltip, and row summaries remain unchanged, and the file is now covered by
  the stricter semantic-token audit.
- `TrajectoryPanel` now renders through direct `EvidenceCard` composition
  instead of the old `EvidenceTile`/`EvidenceTileHeader` bridge, and its final
  `var(--color-label-tertiary)` fallback uses the semantic muted-foreground
  token. The EQS trend, forecast band SVG, annotation lanes, discovery split,
  and investigate action remain unchanged. This closes the current
  evidence-folder scan for old evidence headers, `app-label`, and
  `var(--color-label-*)` tokens.
- Verification completed for this checkpoint:
  targeted banned-token scans on touched files plus the standard active UI
  audit, compat check, focused rebuild/DataTable tests, and production build.
- `npm run typecheck` remains blocked by unrelated dirty backend autoposter
  typing errors in `api/_lib/handlers/auto-post/promptBuilder.ts`.

### Completed Checkpoint: Analytics Reels + Topic Lift Sweep

- `ReelsSkipRateHistogram` now renders through `EvidenceCard` with shadcn
  `Empty` and `Skeleton` states instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, `dv2-tile-content`, and `citation`
  styling. The skip-rate alerts hook, histogram math, platform scope guard,
  and investigate action remain unchanged.
- `TopicTagLiftCurves` now renders through `EvidenceCard` with shadcn
  `Empty` and `Skeleton` states instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, `dv2-tile-content`, and old label
  classes. The topic-lift hook, diverging bar visual, scope compatibility
  behavior, and investigate action remain unchanged.
- Verification completed for this checkpoint:
  targeted banned-token scans on touched files. Standard audit, compat,
  focused tests, and build were rerun after the following analytics evidence
  batch.

### Completed Checkpoint: Analytics Velocity + Discovery Sweep

- `EngagementVelocityChart` now renders through `EvidenceCard` with shadcn
  `Empty` and `Skeleton` states instead of `EvidenceTile`,
  `EvidenceTileHeader`, `dv2-tile`, `dv2-tile-content`, `citation`, and old
  label classes. The first-hour velocity hook, box-plot math, sample lists,
  and investigate action remain unchanged.
- `NonFollowerReachTrendTile` now renders through `EvidenceCard` with shadcn
  `Empty` state instead of `EvidenceTile`, `EvidenceTileHeader`, `dv2-tile`,
  `dv2-tile-content`, `dv2-big-num`, and old label classes. The
  non-follower-reach hook, threshold-band diagnostic, status logic, and
  investigate action remain unchanged.
- Verification completed for this checkpoint:
  targeted banned-token scans on touched files, `npm run audit:legacy-ui`,
  `npm run compat:check`, focused `DataTable`/rebuild primitive tests, and
  `npm run build`.
- `npm run typecheck` remains blocked outside the UI slice by unrelated dirty
  backend/publishing work: `promptBuilder.ts` optional-property typing issues
  plus `publishPost.ts` guard-result narrowing errors.

### Completed Checkpoint: Auth + Legal Control Strip

- Legal pages now use shadcn-backed `Button` controls for desktop/mobile table
  of contents interactions and no longer carry active `operator-*`, `.card`,
  raw button, or `space-y-*` presentation in `src/pages/legal/LegalPage.tsx`.
- Auth invite, OAuth callback, reset-password, login, signup, and welcome
  onboarding surfaces now route visible controls through Juno-owned
  shadcn-backed wrappers (`Button`, `Input`, `Select`, `Field`, and
  `FieldGroup`) instead of raw visible buttons, inputs, or selects.
- `scripts/check-active-legacy-ui.mjs` now audits the cleaned auth/legal files
  alongside the active product surfaces.
- Verification completed for this checkpoint:
  `npm run audit:legacy-ui`, `npm run typecheck`, focused UI wrapper tests, and
  `npm run build`.
- `npm run compat:check` is currently blocked by an unrelated stale
  `pipeline_contracts` snapshot drift:
  `schemas/campaign_draft_payload.v1.schema.json` differs from the local
  `pipeline_contracts/schemas/campaign_draft_payload.v1.schema.json`.
  Resolve or resync that contract before treating the whole branch as green.

### Completed Checkpoint: Landing React Rebuild

- `src/pages/Landing.tsx` no longer injects `landingContent.html`, loads
  `public/landing.css`, executes `public/landingScript.js`, or mounts the
  Raycast/WebGL landing preview. The route now renders a React/shadcn landing
  surface using `AppScreen`, `PageHeader`, `DashboardCard`, `StatCard`,
  `Button`, `Badge`, `Input`, `Progress`, and `Separator`.
- The public `/` route still checks Supabase session state and redirects
  authenticated users to `/dashboard`, preserving the route contract while
  replacing the old static marketing frontend.
- `scripts/check-active-legacy-ui.mjs` now audits `src/pages/Landing.tsx`
  alongside auth/legal and product surfaces.
- `src/pages/SharedReport.tsx` now uses `AppScreen`, `DashboardCard`,
  `StatCard`, `Empty`, `Skeleton`, `Badge`, and `Button` for loading,
  missing/expired, and ready states. The Supabase share-token lookup,
  expiry handling, and best-effort view-count update are unchanged.
- Dead shared legacy components and CSS remain in the repository until every
  active import is gone and final deletion is safe.

## Next Implementation Slice

### Slice 2A — Settings + Billing Foundation

Start the next phase with Settings and Billing before Accounts/Inbox. They are
medium-risk operational routes with forms, plan cards, tables, and loading
states, but fewer high-frequency interaction workflows than Inbox or Accounts.

Scope:

- Replace route-level legacy page shells and old visual header/card patterns
  in Settings and Billing with `AppScreen`, `PageHeader`, `DashboardCard`,
  `FormSection`, `DataPanel`, `StatCard`, `Badge`, `Button`, `Skeleton`,
  `Empty`, and existing form wrappers.
- Preserve settings persistence, billing service calls, Stripe checkout,
  customer portal behavior, pending plan state, URL/search-param behavior,
  and all route URLs.
- Do not rebuild Accounts, Inbox, Composer, Links, Calendar, Auth, Landing, or
  App Shell in this slice.
- Do not install Blocks.so components yet. Use Blocks.so as a reference only
  until the shadcn-first product primitives prove reusable on Settings/Billing.

Current progress:

- Billing now uses `AppScreen` and `PageHeader` at the route level.
- Billing's pending-plan notice, current-plan summary, and recommended-plan
  summary have started moving to `DashboardCard`.
- Billing plan cards now use `DashboardCard`, `Badge`, `Button`, `Separator`,
  and `StatCard` instead of old `operator-*` card/action classes.
- Billing's capability comparison matrix now uses `DataPanel` instead of the
  old thick card shell.
- Settings now uses `AppScreen` and `PageHeader` at the route level.
- Settings' in-file Autopilot and Danger Zone panes now use `FormSection`,
  `DashboardCard`, `Button`, `Separator`, and the Juno `Switch` wrapper.
- Settings imported tab bodies are intentionally not fully rebuilt yet; each
  tab should be migrated with its own form/save-flow coverage.

Acceptance criteria:

- Settings and Billing no longer depend on old route-level `operator`,
  Raycast-style, or raw ad hoc card shells where replacements land.
- Existing forms, tabs, billing cycle controls, checkout buttons, portal
  buttons, usage/progress rows, and comparison tables still render and behave.
- Focused tests and the standard gate pass:
  `npm run typecheck`, `npm run compat:check`, focused tests, `npx vitest run`,
  and `npm run build`.

### Slice 2A Remaining Work

- Rebuild Settings imported tab components under `src/components/settings/*`,
  starting with Profile, Workspace, Security, API, Webhooks, Connections, and
  Voice profiles. These still contain older `.card`, raw button, raw input, and
  Raycast-style sub-surfaces.
- Browser-QA Billing in an authenticated session for checkout buttons, portal
  buttons, billing-cycle toggle, plan selection, usage loading, and comparison
  table scroll behavior.
- Browser-QA Settings in an authenticated session for tab keyboard navigation,
  mobile tab rail, switch persistence, danger confirmations, and form save
  flows.

## Following Implementation Slice

### Slice 2B — Settings Component Sweep, Then Accounts/Inbox

Finish Settings component internals before moving to Accounts and Inbox.
Settings is still the safest place to convert forms, panels, status rows,
empty states, API key lists, webhooks, connection cards, and voice-profile
editors to shadcn-backed wrappers because the workflows are important but
isolated.

Scope:

- Convert Settings child components to `FormSection`, `DashboardCard`,
  `DataPanel`, `Badge`, `Button`, `Input`, `Textarea`, `Select`, `Switch`,
  `Tabs`, `Empty`, `Skeleton`, and `Separator`.
- Replace remaining route-visible `RaycastTag` usage inside Settings with
  `Badge`.
- Preserve all settings persistence, Supabase calls, API key generation,
  webhook creation, connection display, and voice-profile save behavior.
- After Settings internals are clean, continue to Accounts and Inbox shells:
  filters, context menus, assignment menus, search states, list rows, empty
  states, and low-risk panels.

Current progress:

- Settings shared `Panel` now routes through `FormSection`, so many Settings
  tabs inherit shadcn/Nova card anatomy without changing save behavior.
- Profile now uses shadcn-backed `Avatar`, `Input`, `Button`, and `Separator`
  wrappers while preserving avatar upload and auth metadata persistence.
- Connections and Voice Profile account lists now use `DashboardCard`, `Badge`,
  `Empty`, and `Skeleton` instead of `Tile`, `RaycastTag`, and raw `.card`
  loading/empty states.
- API keys now use `Input`, `Checkbox`, `Button`, `Badge`, `Empty`, `Skeleton`,
  and `Modal` wrappers while preserving create/revoke/copy behavior.
- Webhooks now use `Input`, `Checkbox`, `Button`, `Empty`, and `Skeleton`
  wrappers while preserving add/test/delete behavior.

Remaining Slice 2B Settings work:

- Workspace and White-label tabs still contain raw upload/preview panels and
  buttons.
- Security still contains custom MFA panels, raw inputs/buttons, and list rows.
- Appearance still contains custom theme option cards.
- Data export, cohort sharing, legacy voice editor internals, and advanced admin
  tabs still need the same shadcn wrapper sweep.

### Slice 2C — Links Route Shell Started

The user has explicitly asked to remove the old custom frontend, so the rebuild
is now allowed to be more aggressive as long as backend, hook, service, routing,
and persistence behavior stays intact.

### Slice 3 — Full Legacy Frontend Strip In Progress

The current direction is no longer "preserve the Juno visual language." The
new direction is: preserve backend/data/workflow behavior, but strip the old
frontend presentation and rebuild product surfaces around shadcn/Nova with
Juno oxblood as the primary action color.

Completed in this strip pass:

- Inbox route shell now uses `AppScreen`; inbox child panes no longer import
  `OperatorPageHeader`, `RaycastTag`, `EmptyState`, or old `.card` shells.
- Ideas route now uses `AppScreen`, `PageHeader`, `DashboardCard`, `Badge`,
  `Button`, `Input`, `Select`, `Textarea`, and shadcn `Empty`.
- Autopilot route shell no longer imports `RaycastChrome`,
  `OperatorPageHeader`, or `EmptyState`; route-level `.card` and `dv2` action
  tokens were removed from the page.
- Auth/legal/public-adjacent pages had obvious old `operator-material`,
  `operator-action`, and raw `.card` presentation classes converted to
  shadcn/Nova-style semantic surfaces.
- Static landing class names that used `operator-*` naming were renamed to
  product-neutral names so old visual language does not leak into public
  markup.
- Accounts, Calendar, Content Library, Publishing setup, and Smart Links
  analytics child components had top-level `OperatorPageHeader`, `RaycastTag`,
  `EmptyState`, `WidgetCard`, and old operator action classes replaced with
  `PageHeader`, `Badge`, `Button`, `Empty`, `DashboardCard`, and semantic
  panels where this pass touched them.
- Accounts and Inbox active route/support files now also avoid the old
  `text-label-*` and `color-card-elevated` semantic token vocabulary. The
  active audit enforces this alongside the raw-control and legacy-wrapper bans.
- Routine analytics child panels had old `.card material-regular` shells
  mechanically converted to Nova-style `border/bg-card/shadow-sm` surfaces.

Remaining full-strip work:

- **Dashboard V2 internals are the largest remaining old frontend body.** The
  route shell is shadcn-first, but many tile internals still use `dv2-*`
  classes, custom tile wrappers, and old dashboard-specific CSS.
- **Mobile dashboard overview** still has `dv2-root`, old `.card` rows, and
  `EmptyState` usage.
- **Analytics V2 evidence components** still contain `dv2-*` tile internals,
  but the active `EliteEmptyState` wrappers have been removed.
- **Composer no longer has active raw visible controls or old semantic token
  vocabulary in the scanned route/support files;** remaining Composer work is
  higher-order Nova anatomy polish.
- **Content-library internals** still need a deeper visual-anatomy pass after
  the current route group.
- **Settings residual tabs** still include older raw panels and list rows.
- **Old shared wrappers/CSS cannot be deleted yet** until repo audit returns
  zero references outside intentionally deferred dashboard/chart internals.

Current acceptance gate for every strip batch:

- `npm run typecheck`
- `npm run compat:check`
- focused route/component tests where practical
- `npx vitest run`
- `npm run build`
- Browser QA on the touched routes at desktop and mobile widths.

### Slice 3 — Full shadcn/Nova Strip

Current goal: remove old frontend presentation from the entire app, not just
incrementally style around it. Backend APIs, hooks, services, auth, billing,
publishing, analytics fetching, telemetry names, and route behavior remain
intact.

Completed in the current strip batch:

- Shared `Card` no longer emits the old `.card`/`j33-*` compatibility classes
  internally. Its legacy `material` prop is retained as a compatibility API but
  now maps to Nova/zinc shadcn card surfaces.
- App shell work started:
  - desktop topbar/breadcrumb controls moved toward shadcn `Button` and Nova
    card surfaces;
  - mobile top bar and mobile section shells moved to `DashboardCard`;
  - mobile page shell no longer emits `operator-material`;
  - command palette no longer uses Raycast tags/kbd for its visible command
    shell.
- Composer route no longer has route-level `operator-*`, `.card`,
  `OperatorPageHeader`, `RaycastTag`, `RaycastKbd`, or raw textarea usage.
  It now uses `AppScreen`, `PageHeader`, `DashboardCard`, `Badge`, `Button`,
  `Input`, `Select`, `Textarea`, and `Kbd` for the migrated shell/panels.
- Content Library route no longer uses `operator-page`, `operator-material`,
  `EmptyState`, or `.card` for its route shell/loading/empty states.
- Publishing Setup route no longer uses `OperatorPageHeader`, `RaycastTag`,
  `operator-page`, `operator-material`, or `operator-action-primary`.
- Accounts route shell no longer uses `OperatorPageHeader`, `operator-page`,
  `operator-material`, `.card` filter wrapper, or `operator-action-primary`.
  Accounts route/support files also no longer use `text-label-*` or
  `color-card-elevated` tokens, and this is now enforced by
  `npm run audit:legacy-ui`.
- Reports route shell no longer uses `OperatorPageHeader`, `RaycastTag`,
  `RaycastKbdHintStrip`, `EmptyState`, `operator-page`, `operator-material`,
  or `.card` for the main reports table/template wrappers.
- Attribution route shell no longer uses `OperatorPageHeader`, `RaycastTag`,
  `EmptyState`, `operator-page`, `operator-material`, or `j33-ribbon` at the
  route level.
- Calendar route shell no longer uses `OperatorPageHeader`, `RaycastTag`,
  `RaycastKbdHintStrip`, `EmptyState`, `operator-page`, `operator-material`,
  `.card`, or route-level old action classes. Scheduling mechanics, drag/drop,
  command actions, and post mutations are preserved.
- Approval Queue route no longer uses `OperatorPageHeader`, `operator-page`,
  `operator-material`, `operator-card-standard`, old action classes, or raw
  textarea/select/input controls in the approval payload editor.
- Listening route no longer uses `OperatorPageHeader`, `RaycastTag`,
  `EmptyState`, `operator-page`, `operator-material`, `operator-action-*`, or
  `j33-ribbon`.
- Dashboard empty-wrapper path, Auth shell, Shortcuts help overlay, and
  Analytics first-run empty state have been moved off obvious legacy wrappers.

Still remaining for the full strip:

- Highest-risk large routes still remaining: `Autopilot`, `Ideas`, and
  `Inbox`.
- Auth/public/legal surfaces: `InviteAccept`, `OAuthCallback`,
  `ResetPassword`, `Welcome`, `LegalPage`, `Landing`, and `SharedReport`
  have been moved onto shadcn-backed route presentation and are covered by the
  active legacy UI audit.
- Nested dashboard/analytics internals still include bespoke `dv2-*` and
  custom analytics tile components. These should be rebuilt after the route
  shells and workflow-heavy routes are stable.
- Several feature component folders may still emit old classes from inside
  child components even when their parent route is clean. Run the legacy audit
  before each batch and clean child components only when the parent workflow can
  be browser-QA'd.

Current verification checkpoint:

- `npm run typecheck` passes after the shell, Composer, Content Library,
  Publishing Setup, Accounts, Reports, Attribution, Calendar, Approval Queue,
  and Listening strip work.
- `npm run compat:check` passes at this checkpoint.
- Before committing or claiming completion, still run `npm run compat:check`,
  focused route tests, `npx vitest run`, and `npm run build`.

Recommended next route order:

1. Inbox shell/list empty states and assignment/reply panels.
2. Ideas shells/panels.
3. Autopilot last among authenticated routes because it has the most legacy
   card density and the largest interaction surface.
4. Auth/legal/public-adjacent pages.

Current progress:

- `/links` now uses `AppScreen` and `PageHeader` instead of `operator-page`,
  `operator-material`, `OperatorPageHeader`, and `operator-action-primary`.
- The Smart Links click-goal and link-health panels now use `DashboardCard`,
  `Progress`, `Button`, `Badge`, and `StatCard` instead of `WidgetCard`,
  `MetricCard`, and `operator-card-standard`.
- The link list shell now uses `DataPanel` instead of a raw `.card` wrapper.
- Empty states now use the shadcn-backed `Empty` wrapper instead of
  `EmptyState` or ad hoc empty markup.
- The old `RaycastKbdHintStrip` dependency has been removed from `/links` and
  replaced with a compact shadcn/Nova badge row.

Remaining Slice 2C Links work:

- `LinkDetailPane`, `LinkRow`, preview panels, smart-link skeletons, and nested
  editor controls still need a deeper shadcn wrapper pass.
- Remove residual `links-material-*` and old smart-link CSS only after nested
  components are migrated and browser QA confirms no layout regressions.
- Keep smart-link creation, update, delete/undo, copy, UTM, preview, tab, and
  analytics behavior unchanged.

### Slice 2D — Reliability Route Shell Started

Current progress:

- `/reliability` now uses `AppScreen` and `PageHeader` instead of
  `operator-page` and `OperatorPageHeader`.
- Reliability cards now use `DashboardCard` and `StatCard` instead of
  `WidgetCard`, `WidgetPanel`, `WidgetRow`, and `MetricCard`.
- Recovery actions now use the shadcn-backed `Button` wrapper instead of
  `operator-action-secondary`.
- Issue rows and token-risk rows now use shadcn-backed button/badge anatomy
  instead of old `juno-widget-row` and `StatusPill` markup.
- Reliability API fetching, snapshot fallback, refresh behavior, and recovery
  navigation routes are unchanged.

Remaining Slice 2D Reliability work:

- Browser-QA authenticated `/reliability` for loading/fallback/error states and
  recovery navigation.
- Consider replacing inline severity color helpers with shared semantic badge
  mapping once the remaining operations routes use the same pattern.

### Slice 2E — Handoff Route Shell Started

Current progress:

- `/handoff/:postId` loading, error, main content, and checklist surfaces now
  use `AppScreen`, `DashboardCard`, `Badge`, and the shadcn-backed `Button`
  wrapper instead of `operator-page`, raw `.card` shells, `RaycastTag`, and raw
  `<button>` markup.
- Caption copy, media share/download, Instagram open, mark-posted,
  follow-up-save, calendar navigation, and composer navigation behavior are
  unchanged.
- The post-publish follow-up form now uses shared `Field`, `Input`, and
  `Textarea` wrappers instead of route-local control styling, so Handoff no
  longer carries visible raw-control presentation in its active route scan.

Remaining Slice 2E Handoff work:

- Browser-QA authenticated handoff links on mobile dimensions because the
  route is phone-workflow heavy.
- Replace remaining inline micro-layout classes with shared form/list
  primitives once the mobile flow is verified.

Current follow-up:

- `Handoff.tsx` no longer uses the old `text-label-*` semantic token
  vocabulary. The checklist, media-empty state, captions label, and follow-up
  labels now use Nova/zinc semantic tokens.
- Accounts and Inbox route groups were re-scanned after the wrapper cleanup.
  `AccountsHero`, `ConversationListPane`, and `SentimentBadge` no longer use
  old `app-label` or `var(--color-label-*)` residue; account and inbox hooks,
  filters, assignment, reply, and conversation behavior are unchanged.
- `scripts/check-active-legacy-ui.mjs` now enforces semantic-token cleanup for
  `Handoff.tsx` in addition to its existing raw-control and legacy-wrapper
  checks.
- Handoff loading, post fetch, caption copy, media share/download, Instagram
  open, mark-posted, follow-up-save, calendar navigation, and composer
  navigation behavior remain unchanged.

### Aggressive Rebuild Rule

For new slices, old custom frontend wrappers should be removed rather than
preserved where a shadcn-backed primitive exists. This includes route-level
uses of `OperatorPageHeader`, `RaycastChrome`, `RaycastTag`, `Tile`,
`WidgetCard`, `MetricCard`, `.card` shells, `operator-*`, `dv2-*`, and `j33-*`
visual classes. The only exceptions are bespoke chart internals, scheduling
grids, and workflow-specific editors that need a separate behavior-preserving
rewrite.

### Slice 3A — Dashboard Responsive + Shell Strip

Current progress:

- Small-window `/dashboard` no longer renders the old desktop dashboard-v2
  tile stack through `MobileOverview`.
- `MobileOverview` no longer imports dashboard-v2 tiles, `EmptyState`,
  `dv2-root`, old `.card` shells, or `localOperatorMaterial`.
- Mobile account pulse now uses shadcn/Nova `DashboardCard`, `Badge`,
  `Button`, and `Empty` wrappers while preserving fleet totals, system status,
  attention counts, next-up posts, top-post rows, pull refresh, and navigation.
- Desktop `DashboardV2` grid wrappers no longer use `dv2-band`,
  `dv2-span-*`, `dv2-thread-ops-*`, or `dv2-processing-*` classes.
- Desktop dashboard processing rail now uses semantic card/badge/button
  classes and `Badge` for phase state.
- `FollowsTodayTile` and `OpsHealthTile` no longer depend on `WidgetCard`,
  `WidgetPanel`, `MetricCard`, `dv2-*` classes, or `var(--dv2-*)` token
  references.
- `AnomalyFeedTile` now uses shadcn/Nova `DashboardCard`, `Badge`, `Button`,
  `Empty`, and `Skeleton` wrappers for the alert shell, investigate action,
  empty/loading states, row actions, and category tags while preserving the
  anomaly hook, scoped investigate navigation, source-workflow resolve PATCH,
  toast behavior, and refetch behavior.
- `ThreadsTiles` no longer emits `dv2-tile`, `dv2-tile-content`,
  `dv2-widget-action`, or `var(--dv2-*)` styling. The source-distribution
  strip, conversation winner, held-replies queue, and suppression watch now
  use `DashboardCard`, `Badge`, `Button`, `Empty`, and `Skeleton` wrappers
  while keeping the existing Threads source, reply-depth, quote/reply, held
  queue, reach-anomaly, scoped inbox, account-detail, and external permalink
  behavior unchanged.
- `HookClassLiftTile` and `StoriesFunnelTile` had their remaining old
  `dv2-*` numeric/label micro-classes removed after their earlier
  `DashboardCard` migration. Hook-class lift, story sequence retention,
  exit-frame, and story navigation data contracts remain unchanged.
- The first IG-specific dashboard cards now render with shadcn/Nova shells:
  `SendsPerReachBulletDarkTile`, `WatchPerViewTile`,
  `SendsPerReachLeadersTile`, `QualitySignalBulletsTile`, and
  `VanityFlagTile` use
  `DashboardCard`, `Badge`, `Empty`, and `Skeleton` states while preserving
  `useFleetMetrics`, `useReelWatchTimeLeaders`, `useSendsPerReachLeaders`,
  `useSaveRateLeaders`, `useVanityAccounts`, the existing bullet chart
  signal, scoped calendar navigation, scope labels, ranking rows, top
  contributor rows, likes-to-quality ratio semantics, and Mosseri
  share-rate/quality-signal semantics.
- `SaveRateTopBottomTile` now uses a shadcn/Nova `DashboardCard`, tokenized
  ranked post rows, shared `Empty`, and shared `Skeleton` sections while
  preserving `useSaveRateLeaders`, top/bottom post ranking, thumbnail
  fallbacks, and calendar post deep links.
- `ContentMixHealthTile` now uses a shadcn/Nova `DashboardCard`, Juno
  `Button` CTA, `Badge`, shared `Empty`, shared `Skeleton`, tokenized
  summary/reach rows, and a local semantic ternary plot while preserving
  `useContentMixHealth`, composer deep-link routing, reach-weighted mix
  calculations, weekly shift calculations, and reel-drought/rebalance
  decision logic.
- Shared dashboard atoms `BulletChart`, `RangeChip`, `TrafficDot`,
  `DeltaPill`, dashboard `Avatar`, `CohortBadge`, `Sparkline`, and
  `DonutRing` no longer emit `dv2-*` classes or `var(--dv2-*)` tokens.
  `BulletChart` renders semantic tokenized bands directly, `RangeChip`
  composes the Juno `ToggleGroup` wrapper while keeping its old
  `value/onChange` API, `TrafficDot` uses semantic status tokens, dashboard
  `Avatar` composes the shadcn-backed avatar wrapper, and the SVG atoms use
  Nova/zinc + oxblood tokens while preserving existing caller APIs.
- `ReplyDepthLeadersTile` no longer emits old `dv2-*` row, ticker, skeleton,
  and SVG token styling. The tile keeps the same reply-depth hook, persisted
  range, sort behavior, calendar deep link, scoped analytics link, and mini
  tree chart internals while using shadcn/Nova rows, badges, skeletons, and
  semantic SVG colors.
- `FundamentalsRibbon` now renders the All / Threads / Instagram KPI strip
  through shadcn/Nova card-stat anatomy with shared `Skeleton` loading bars,
  semantic borders, muted captions, and oxblood lead rules. The underlying
  fleet metrics, follower attribution, quote/reply, ghost-post, story activity,
  follower total, and thread fallback hooks are unchanged. The dead
  `dv2-ribbon-*` compatibility CSS block was removed from `dashboard-v2.css`.
- `DashboardV2` no longer imports `dashboard-v2.css` or the old
  `.dv2-tile` keyboard navigation hook. The active dashboard now relies on
  explicit shadcn/Nova grid/card composition instead of the deleted
  dashboard-v2 stylesheet.
- Analytics `EvidenceRows` no longer imports `dashboard-v2.css`; bridge-loaded
  dashboard evidence widgets now stand on their shadcn/Nova wrappers. The
  remaining `EqsForecastCiTile` `dv2-big-num` class and raw visible range
  input were replaced with tokenized text and the shared `Slider` wrapper.

Remaining Slice 3A dashboard work:

- Convert remaining dashboard-v2 tile families one at a time:
  `FleetDotGrid`, `SmallTiles`, and `StreakTile`. `IgV2Tiles.tsx` no longer
  contains active `dv2-*` classes or `var(--dv2-*)` token references.
- Continue focused scans for dashboard-v2 tile internals. The current
  dashboard atom and tile focused scan is clean except for the non-visual
  `"operator-task"` analytics source query parameter in
  `OperatorTaskQueueTile`.
- Browser-QA `/dashboard` at desktop, tablet, and mobile widths after each
  dashboard tile family is converted.

### Slice 3H — Dashboard Mobile + Fleet Grid Strip

Current progress:

- `MobileOverview` mobile queue and top-performing actions now use the
  shadcn-backed `Button` wrapper instead of raw visible `<button>` controls.
- `FleetDotGrid` no longer emits `dv2-fleet-status-*`, `dv2-dotgrid`, or
  `cell` visual classes for its status matrix, loading cells, legend, and
  overflow marker.
- `FleetDotGrid` status colors now use semantic Nova/zinc and Juno oxblood
  tokens instead of dashboard-v2 token classes.
- `MobileOverview` and `FleetDotGrid` are now covered by
  `npm run audit:legacy-ui`.
- Fleet totals, account scope filtering, status sorting, critical-account
  navigation, mobile queue navigation, and top-post analytics navigation are
  unchanged.

Remaining Slice 3H dashboard work:

- `OperatorTaskQueueTile` task rows now use the local `Button` wrapper, but the
  file is not yet in the strict audit because the current audit flags semantic
  strings such as `operator-task` and legacy component names such as `Tile`.
- Continue dashboard-v2 cleanup by renaming/removing legacy tile components
  only when their active imports are replaced by shadcn/Nova component names.
- Large bespoke dashboard-v2 diagnostic tiles may still contain custom chart
  internals, but they no longer depend on `dashboard-v2.css`; keep replacing
  bespoke presentation with shadcn/Nova wrappers as each route group is swept.

### Slice 3I — Route Skeleton Strip

Current progress:

- `PageSkeletons.tsx` now uses shared Nova/zinc `pageShellClass`,
  `densePageShellClass`, `composerPageShellClass`, `panelClass`, and
  `panelOverflowClass` helpers instead of old `.card`, `operator-page`,
  `operator-material`, `settings-page`, and `space-y-*` loading markup.
- Dashboard, Analytics, Composer, Calendar, Accounts, Inbox, Settings, Billing,
  Content Library, Reports, Links, Autopilot, Attribution, Welcome, and Auth
  fallback skeletons now share shadcn/Nova loading surfaces.
- The local dashboard skeleton helper was renamed from `BentoTile` to
  `BentoPanel` so the strict audit can keep treating `Tile` as legacy UI debt.
- `PageSkeletons.tsx` is now covered by `npm run audit:legacy-ui`.
- Route lazy-loading behavior, primary data loading timing, skeleton structure,
  and route URLs are unchanged.

Remaining Slice 3I skeleton work:

- Browser-QA lazy route fallback transitions after larger route groups are
  complete, especially Composer, Calendar, Inbox, and Analytics.
- If a route's rebuilt layout changes substantially, update its skeleton shape
  immediately so the loading-to-content swap does not introduce layout shift.

### Slice 3B — App Shell Activity Panel Strip

Current progress:

- The active authenticated app shell uses the shadcn-backed `Sidebar`,
  `SidebarInset`, `SidebarMenu`, `Breadcrumb`, `Button`, `Separator`,
  `DropdownMenu`, `TooltipProvider`, `Toaster`, and command/composer dialog
  wiring from `src/components/layout/Layout.tsx`.
- `ActivityPanel` is now included in `npm run audit:legacy-ui`, so the
  notifications drawer is covered by the active legacy UI guardrail.
- Activity filter chips and the collapsible yesterday section now use the
  shadcn-backed `Button` wrapper instead of raw visible `<button>` markup.
- The activity toolbar divider now uses `Separator`.
- `IconTooltipButton` now composes the shadcn-backed `Button` wrapper behind
  Radix Tooltip instead of rendering its own raw styled button.
- The dead old `src/components/layout/Sidebar.tsx` implementation was removed
  after source search confirmed the active app shell imports the shadcn-backed
  sidebar primitives from `src/components/ui/Sidebar`.
- Activity subscriptions, notification read/delete state, keyboard filter
  shortcuts, panel open/close behavior, and route navigation are unchanged.
- `ActivityPanel` no longer uses the old `text-label-*` semantic token
  vocabulary. The notifications drawer now uses Nova/zinc semantic text and
  decoration utilities for event copy, timestamps, empty/loading states, icon
  buttons, filters, and section headers.
- `MobileTopBar`, `MobileSection`, `MobileSegmented`, and `ShortcutsHelp`
  no longer use the old `text-label-*` semantic token vocabulary. They now use
  Nova/zinc semantic tokens while preserving their existing props, mobile
  section composition, segmented-control behavior, and keyboard-shortcuts
  dialog behavior.
- `npm run audit:legacy-ui` now includes the cleaned activity/mobile helper
  files and enforces the stricter semantic-token ban for them.

Remaining Slice 3B app-shell work:

- Continue expanding `audit:legacy-ui` to shared shell helpers as they are
  cleaned.
- Browser-QA notifications open/close, mark read, clear visible, filter
  switching, and narrow/mobile layout.

### Slice 3C — Settings Appearance + Cohort Sharing Strip

Current progress:

- `AppearanceTabContent` theme and palette cards now use the local
  shadcn-backed `Button` wrapper instead of raw visible `<button>` cards.
- `AppearanceTabContent` removed `space-y-*` stack usage in favor of
  flex/gap layout.
- `CohortSharingCard` now uses the local shadcn-backed `Switch` wrapper
  instead of importing Radix Switch directly.
- `CohortSharingCard` niche selection now uses the local `Select` wrapper
  instead of raw route-level `<select>` markup.
- `CohortSharingCard` list spacing now uses flex/gap instead of `space-y-*`.
- Both settings components are now covered by `npm run audit:legacy-ui`.
- Theme choice, palette persistence, cohort opt-in/out, niche update,
  analytics tracking, and toast behavior are unchanged.

Remaining Slice 3C settings work:

- Continue adding settings sub-tabs to `audit:legacy-ui` after each raw
  control/legacy-wrapper cleanup.
- Highest remaining settings offenders: `AdminTabsContent`,
  `DeletionStatusTab`, `SecurityTabContent`, `DataExportCard`, and
  `VoiceProfileEditor`.

### Slice 3D — Settings Data Export Strip

Current progress:

- `DataExportCard` no longer imports or renders the legacy `Tile` wrapper.
- The export panel now uses shadcn-backed `Card` and `CardContent`
  composition.
- The request/download action now uses the local shadcn-backed `Button`
  wrapper instead of raw visible `<button>` markup.
- `DataExportCard` is now covered by `npm run audit:legacy-ui`.
- Workspace export payload assembly, Supabase reads, generated JSON blob,
  object URL revocation, download filename, status labels, and toast behavior
  are unchanged.

Remaining Slice 3D settings work:

- Highest remaining settings offenders after this checkpoint:
  `AdminTabsContent`, `DeletionStatusTab`, `SecurityTabContent`, and
  `VoiceProfileEditor`.

### Slice 3E — Settings Security Strip

Current progress:

- `SecurityTabContent` now uses the local shadcn-backed `Button` wrapper for
  MFA backup-code regeneration, secret copy, enrollment cancel, and backup-code
  dismiss actions instead of raw visible `<button>` markup.
- The authenticator verification code entry now uses the local shadcn-backed
  `Input` wrapper instead of a raw visible `<input>`.
- The top-level settings security stack now uses flex/gap layout instead of
  `space-y-*`.
- `SecurityTabContent` is now covered by `npm run audit:legacy-ui`.
- Supabase MFA enrollment, verification, backup-code regeneration/copy/download,
  sign-out-other-sessions, confirmation dialogs, and toast behavior are
  unchanged.

Remaining Slice 3E settings work:

- Highest remaining settings offenders after this checkpoint:
  `AdminTabsContent`, `DeletionStatusTab`, `NotificationsTabContent`,
  `WebhooksTabContent`, `APITabContent`, and `VoiceProfileEditor`.

### Slice 3F — Settings Labs + Deletion Status Strip

Current progress:

- `BetaProgramTab` now uses flex/gap layout and the local shadcn-backed `Badge`
  wrapper instead of a custom beta pill.
- `DeletionStatusTab` now uses `StatCard`, `DashboardCard`, and `Badge`
  primitives for status stats and informational cards instead of hand-built
  custom card markup.
- Both tabs are now covered by `npm run audit:legacy-ui`.
- The Labs empty state, deletion workflow copy, and informational compliance
  behavior are unchanged.

Remaining Slice 3F settings work:

- Highest remaining settings offenders after this checkpoint:
  `AdminTabsContent`, `NotificationsTabContent`, `WebhooksTabContent`,
  `APITabContent`, `ConnectionsTabContent`, and `VoiceProfileEditor`.

### Slice 3G — Settings Developer, Notifications, Connections, Voice Strip

Current progress:

- `NotificationsTabContent`, `WebhooksTabContent`, `APITabContent`,
  `AdminTabsContent`, and `ConnectionsTabContent` now use flex/gap layout
  instead of `space-y-*` stacks.
- Developer API key and webhook panels continue to use shadcn-backed `Input`,
  `Checkbox`, `Button`, `Empty`, `Skeleton`, and `Modal` primitives.
- `VoiceProfileEditor` now uses shadcn-backed `Textarea`, `Input`,
  `ToggleGroup`, `Button`, and `DashboardCard` primitives instead of raw
  visible textareas, inputs, segmented buttons, chip remove buttons, and
  custom extraction panel markup.
- These Settings components are now covered by `npm run audit:legacy-ui`.
- Settings route/tab files and Billing now also avoid the old `text-label-*`
  and `color-card-elevated` semantic token vocabulary. The active audit
  enforces this stricter token clean set for Settings and Billing alongside the
  raw-control and legacy-wrapper bans.
- The final visible Settings `app-label` helpers in the desktop side-tab
  groups, provider connection metadata, appearance palette captions, and admin
  activity bullets have been replaced with Nova/zinc label classes and semantic
  muted tokens. The remaining raw inputs in Settings are only hidden/sr-only
  avatar and workspace-logo file inputs for upload plumbing.
- Billing's final route-level `app-label` helpers and old
  `var(--color-label-tertiary)` fallbacks were replaced with explicit
  Nova/zinc label classes and semantic muted-foreground tokens in the pending
  plan banner, upgrade section, plan-card checks, comparison matrix, and usage
  limit rows. Stripe checkout, portal, pricing, selected-plan state, and usage
  calculations remain unchanged.
- Notification preference persistence, push subscribe/test behavior, API key
  creation/revocation, webhook create/test/delete, connection navigation/OAuth
  handoff, voice extraction, chip editing, and voice profile save behavior are
  unchanged.

Remaining Slice 3G settings work:

- Settings source scan now only reports hidden file inputs in Profile and
  Workspace upload plumbing, which are allowed by the audit.
- Billing source scan no longer reports old label/elevated-card tokens.
- Continue browser-QA Settings on desktop/mobile after broader route groups are
  batched, especially API key modal, webhook actions, and voice profile editor.

### Slice 3H — Analytics Control Strip

Current progress:

- `ExportCsvButton` now uses the shadcn-backed Juno `Button` wrapper for all
  dropdown actions instead of raw menu buttons.
- `SavedViewsMenu` now uses shadcn-backed `Button`, `Input`, `ToggleGroup`, and
  `Empty` primitives for saving, loading, deleting, scheduling, and closing
  saved views.
- `InvestigateButton` now uses the shadcn-backed `Button` and `Kbd` wrappers
  while preserving the existing keyboard shortcut and investigate panel wiring.
- `ContentInsightsPanel` has started its control cleanup: top-decile pattern
  navigation rows now use the Juno `Button` wrapper.
- `AutoInsightsFeed`, `DailyNarrativeStrip`, `EQSTrendChart`,
  `FollowerMetricsPanel`, `SavedViewsMenu`, `SelfCompareDeepDive`, and
  `SmartLinksAnalytics` no longer use the old `text-label-*` or
  `color-card-elevated` semantic-token vocabulary.
- `analyticsShared` lifespan chart reference data no longer emits old
  `var(--color-label-*)` chart colors; the visible lifespan curves now resolve
  through Nova/zinc semantic muted/chart tokens and are covered by the active
  legacy UI audit.
- `EQSTrendChart` and `InvestigatePanel` no longer emit their remaining
  `app-label` helper classes. AI-summary provenance labels, account row
  metadata, and select pills now use explicit Nova/zinc hierarchy while the
  underlying chart, investigation stream, account selection, and rerun behavior
  remain unchanged.
- `InvestigatePanel` now uses the shared shadcn-backed `Modal`, `Button`,
  `Input`, and `Textarea` wrappers instead of its previous hand-rolled
  backdrop, close button, account row buttons, search input, and hypothesis
  textarea. Investigation hooks, account selection, rerun behavior, streaming
  state, and result rendering are unchanged.
- `PlatformSpecificWidgets` no longer uses raw visible `<button>` controls or
  the old `text-label-*` semantic-token vocabulary. Account leaderboard rows,
  the "view all accounts" action, and vanity-engagement account rows now use
  the shared shadcn-backed `Button` wrapper while keeping their existing
  account navigation targets.
- `ContentInsightsPanel` no longer uses raw visible `<button>` controls or the
  old `text-label-*` semantic-token vocabulary. Posting heatmap cells now use
  the shared shadcn-backed `Button` wrapper while preserving the existing
  calendar drill-down URL behavior.
- The unused legacy `analytics-v2/StatTile` component was deleted after repo
  search confirmed it had no active imports.
- The cleaned analytics controls are now covered by `npm run audit:legacy-ui`
  where they no longer contain raw visible controls or banned legacy tokens.

Remaining Slice 3H analytics work:

- Remaining analytics legacy clusters include `FleetAnomalyGrid`,
  `InsightFeedRow`, `LoadingEvidenceTile`, and the remaining `analytics-v2`
  evidence bridge components.

### Slice 3I — Analytics Evidence Shell Strip

Current progress:

- `EvidenceRows` no longer wraps dashboard-imported evidence components with
  the old `dv2-root dv2-elite-material analytics-bridge-tile` shell. The bridge
  now uses the shadcn/Nova-backed `EvidenceCard` primitive.
- `EvidenceRows` deferred loading skeletons now use `EvidenceCard` and
  shadcn-backed `Skeleton` bars instead of custom Nova/dv2-style placeholder
  markup and `space-y-*` layout.
- `LoadingEvidenceTile` list/table skeleton stacks now use flex/gap layout
  instead of `space-y-*`.
- `EvidenceTile` and `EmptyEvidenceTile` render through the shadcn-backed
  `EmptyEvidenceTile`/`Empty` path.

Remaining Slice 3I analytics work:

- `EvidenceRows` no longer imports `dashboard-v2.css`; continue focused scans
  for raw visible controls and legacy visual names in nested analytics widgets.
- Highest-value next widgets: `FleetAnomalyGrid`, `InsightFeedRow`,
  `FollowerFlowTile`, `ViewsBySourceChart`, `IGReachSourceMixTile`,
  `TopBottomPostsTable`, `HashtagPerformanceTable`, and the dashboard tile
  bridges for Stories/BioLink/Quality/Hook class.

### Slice 3J — Content Library + Smart Links Nested Strip

Current progress:

- Content Library support components now use shadcn/Nova wrappers for recent
  strips, stat cells, unavailable states, tags, muted metadata, and upload
  helper copy. The remaining native file input in `MediaUploadZone` is hidden
  upload plumbing and is intentionally allowed.
- The final old `var(--color-label-secondary)` fallback in the shared content
  type pill has been replaced with semantic `--color-muted-foreground`, so the
  Content Library support scan now reports only the intentionally hidden upload
  input exception.
- The shared `Empty` wrapper now uses semantic Nova tokens for descriptions and
  media icons, so route-level empty states no longer inherit old `text-label`
  styling.
- Smart Links nested presentation is mostly swept:
  `LinkRow`, `EmptyDetail`, `AIEnhancePanel`, `BlockListEditor`,
  `PixelExtensionsPanel`, `LinkPagePreview`, and much of `LinkDetailPane` now
  use semantic Nova tokens, shadcn-backed `Badge`, `Empty`, `Button`, `Input`,
  `Textarea`, `Select`, and `Checkbox` wrappers, and compact row/card anatomy.
- `LinkDetailPane` still keeps native hidden file inputs only for avatar/gallery
  upload plumbing. Visible editor, UTM, preview, analytics, and destination
  breakdown surfaces no longer report old `text-label`, `color-card-elevated`,
  raw-control, or legacy wrapper tokens in targeted scan.
- The remaining Smart Links `app-label` helpers in the click-goal controls,
  row click-count labels, and interstitial preview eyebrow have been replaced
  with explicit Nova/zinc label hierarchy. The analytics delta fallback now
  uses semantic muted-foreground instead of old `var(--color-label-*)` tokens.
  Click-goal save behavior, row actions, preview launching, analytics range
  calculations, and avatar/gallery upload behavior are unchanged.
- `Links`, `LinkRow`, `EmptyDetail`, Content Library support components, and
  the restored `/content` route are covered by `npm run audit:legacy-ui`.
- Links, Content Library, and Reports route/support files now also avoid the
  old `text-label-*` and `color-card-elevated` semantic token vocabulary. The
  active audit enforces this stricter clean set for those files. The only raw
  controls reported in this group are hidden file inputs for media/avatar/
  gallery upload plumbing, which are explicitly allowed by the rebuild goal.
- `Links.tsx` no longer mounts the old `links-material-page` scope, the
  search input no longer opts into the legacy `td-control-shadow` helper, and
  dead Links-specific material override selectors were removed from
  `src/index.css`. The click-goal controls and editor grid now carry their
  mobile sizing/min-width behavior directly through route-local Tailwind
  classes.
- `Links.tsx`, `LinkDetailPane`, and `BlockListEditor` now route their visible
  search, click-goal, UTM, appearance, block-setting, and checkbox-row fields
  through the shared shadcn-backed `Field`/`FieldLabel` wrappers instead of
  local label helpers and native visible label scaffolding. Hidden upload file
  inputs remain as allowed plumbing.
- `Reports` and `ReportEditor` remain wired to the current report list,
  editor, preview, send, save, and template behaviors while sharing the same
  raw-control/token-clean audit coverage as Links and Content Library.

Remaining Slice 3J work:

- Finish the remaining Link Detail deep polish by reviewing the QR/metadata
  blocks, interstitial preview, and media-library picker for final
  spacing/density against the Nova preset.
- Browser QA `/links` on desktop and mobile for drag reorder, edit/save,
  avatar/gallery uploads, AI Enhance, UTM copy/apply, analytics range controls,
  and mobile preview overlay.
- Browser QA `/content-library`, `/content`, and `/reports` on desktop/mobile
  for media upload/use-in-Composer actions, content list/filter states, report
  table overflow, editor focus/close behavior, preview/send/save states, and
  template creation.

### Slice 3K — Reports Nested Strip

Current progress:

- Reports table rows, recipient metadata, row actions, template cards, empty
  states, error copy, and keyboard hints now use semantic Nova/zinc tokens and
  shadcn-backed `Button`, `Badge`, `Empty`, `Input`, `DataTable`, and `Kbd`
  wrappers instead of old label/card/action styling.
- `ReportEditor` now routes visible report fields through the shared Juno
  `Field`, `Input`, `Select`, and `Button` wrappers instead of local raw field
  labels and visible raw controls.
- `ReportEditor` now uses the shared shadcn-backed `Sheet` wrapper instead of
  its custom motion overlay, fixed side panel, local close button, and
  route-local focus trap. Preview, send, save, recipient, date range, account,
  group, metric, section, and schedule behavior remain unchanged.
- The targeted Reports scan no longer reports old `text-label`,
  `color-card-elevated`, raw visible controls, `operator-*`, `dv2-*`, `j33-*`,
  or legacy wrapper tokens in `Reports.tsx` or `ReportEditor.tsx`.
- Report create, search/filter, row selection, PDF download, share-link copy,
  retry delivery, duplicate/delete, editor preview/send/save, account/group
  scope, and recurring schedule behavior are unchanged.

Remaining Slice 3K work:

- Browser QA `/reports` on desktop and mobile for table overflow, row actions,
  editor focus/close behavior, preview/send/save states, and template creation.
- Consider tightening the editor's checkbox-grid density with a shared
  button-group or toggle-list primitive after browser QA confirms behavior.
- Consider replacing the custom alert styling with the shared `Alert` wrapper
  once the current route batch is verified.

### Slice 3L — Inbox Nested Strip Started

Current progress:

- The active Inbox route shell now uses the Nova route facade:
  `NovaScreen`, `NovaDataPanel`, and `NovaSection` in `Inbox.tsx`, and
  `NovaHeader`, `NovaToolbar`, `NovaDataPanel`, and `NovaEmpty` in
  `InboxChrome`. The desktop split-pane, loading pane, and empty states no
  longer import `AppScreen`, `PageHeader`, `DashboardCard`, or route-level
  `motion/react`.
- The Inbox audit now bans those old shell imports/JSX in both
  `src/pages/Inbox.tsx` and `src/components/inbox/InboxChrome.tsx` while still
  checking for raw visible controls and old semantic tokens.
- `AssignmentChip`, `ConversationRow`, `ConversationListPane`, the route-local
  Inbox command palette, `ContextRail`, `ReplyComposer`, `ThreadDetailPane`,
  `ThreadMessages`, `InboxChrome`, `TogglePill`, and Inbox helper primitives
  now use semantic shadcn/Nova tokens for muted text, active states, focus
  borders, icon sizing, keyboard hints, and compact row metadata instead of the
  old `text-label-*` and elevated-card token vocabulary.
- Inbox visible controls remain routed through Juno-owned wrappers:
  `Button`, `Badge`, `Textarea`, `Command`, `NovaHeader`, `PillSegmented`,
  `TogglePill`, `Skeleton`, and `Empty`.
- Conversation selection, search, platform/tab filters, account scope chips,
  assignment changes, AI draft use/regeneration, quick replies, send actions,
  like/done/convert-to-idea callbacks, keyboard command behavior, and mobile
  detail/list behavior are unchanged.
- The targeted Inbox scan now only reports intentional sizing on `Skeleton`
  placeholders plus a false-positive `min-h/min-w` class in the reply composer;
  it no longer reports active old label tokens, raw visible controls,
  `operator-*`, `dv2-*`, `j33-*`, or legacy wrapper names in `src/components/inbox`.
- The active legacy UI audit now includes Inbox route/support files in the
  stricter semantic-token clean set, so `text-label-*` and
  `color-card-elevated` cannot be reintroduced there.

Remaining Slice 3L work:

- Review the Inbox shell against the Nova preset for final density and spacing
  after the larger app shell/nav cleanup lands.

### Slice 3M — Composer Semantic Token Strip

Current progress:

- Composer route and support components no longer use the old `text-label-*`
  classes or `--color-card-elevated` token vocabulary. The visible Composer
  labels, helper copy, keyboard hints, preview metadata, mobile controls,
  media grid details, account selector metadata, options panels, critique
  panels, slash menu, and modal chrome now use semantic shadcn/Nova tokens such
  as `text-muted-foreground`, `text-foreground`, `bg-muted`, `bg-card`, and
  `border-border`.
- The Composer `Gauge` icon import was restored so the health panel compiles
  under the current route presentation.
- The local audit now includes additional active Composer support components
  and enforces a scoped ban on `text-label-*` and `color-card-elevated` for the
  cleaned Composer files.
- The remaining raw `<input>` in `MediaGrid` is a hidden file picker used only
  for upload plumbing, which is allowed by the rebuild goal.
- Composer publish, schedule, queue, account picker, media upload, AI actions,
  voice context, push setup, preview, draft, and modal behaviors are unchanged.
- `SampleDraftPanel`, `PhoneSetupPanel`, `MediaOptimizationPanel`, and
  `ActivityPanel` now use the shared `FormSection`/shadcn card composition
  instead of local one-off card headers, footer bands, and empty/list shells.
  Phone setup push actions now live in the card footer slot, and activity
  empty state rendering uses the shared shadcn-backed `Empty` wrapper.
- Composer support panels touched in this pass now use flex `gap-*` layout and
  `data-icon` button/icon placement where they were converted.
- `CritiquePanel` now renders through `DashboardCard`, `Progress`, `Skeleton`,
  and `Empty` instead of a custom card section, hand-rolled progress rail,
  pulse blocks, and dashed empty message. Its scoring, prediction, and
  reasoning data flow remain unchanged.
- `VariantsLab` and `CrossPostDiffResolver` now use nested shadcn-backed
  `Card` composition for repeated variant/diff records instead of custom
  `article` cardlets. Existing generate, promote, edit, accept, and revert
  actions are unchanged.
- `MediaGrid` drag/drop handling now lives directly on the shadcn-backed
  `DashboardCard` instead of an extra custom section wrapper; upload, reorder,
  alt text, and vision-scoring behavior are unchanged.
- The route-local Composer command palette now uses the shared
  shadcn-backed `CommandDialog`, `CommandInput`, `CommandList`, `CommandGroup`,
  `CommandItem`, `CommandEmpty`, and `CommandShortcut` wrappers instead of a
  hand-built fixed overlay, focus timer, Escape listener, raw input, and custom
  dialog body. The command filtering and action execution behavior remain
  unchanged.
- The shared `CommandDialog` wrapper now provides an accessible hidden dialog
  title/description and its command pieces use Nova semantic muted tokens
  instead of old `text-label-*` classes.
- `SlashMenu` now renders as a positioned shadcn-backed `Command` surface with
  `CommandList`, `CommandGroup`, `CommandItem`, `CommandEmpty`, and
  `CommandShortcut` instead of a raw `role="dialog"` card and repeated visible
  buttons. Existing typed slash filtering, arrow-key selection, Enter-to-run,
  Escape close, and outside-pointer close behavior are unchanged.
- Composer now renders through the fast-track Nova route layer:
  `NovaScreen`, `NovaHeader`, `NovaSection`, `NovaToolbar`, and `NovaCard`.
  The edit kept `useComposer`, media upload, draft persistence, AI actions,
  schedule/publish payloads, readiness checks, URL/session handoffs, and
  modal entry behavior intact.
- Composer mobile preview/schedule/check sheets now delegate directly to the
  shared shadcn-backed `Sheet` wrapper instead of a local portal, fixed dialog
  shell, backdrop, Escape listener, drag layer, and close button. Existing
  mobile sheet state and content remain unchanged.
- Composer's mobile sticky action rail now renders through a route-local
  shadcn-backed `Button` helper instead of the deleted
  `ComposerMobileControls` module. Existing preview, schedule, draft,
  readiness, and publish actions remain unchanged.
- Composer's desktop preview tabs no longer import route-level `motion/react`
  or render the custom animated underline; active selection now uses standard
  shadcn/Nova button state.
- Account picker, drafts, and group mobile popovers now share a local
  `MobilePopoverSheet` adapter backed by the shared shadcn `Sheet` wrapper
  instead of three duplicated portal/backdrop/motion bottom-sheet branches.
  Desktop anchored popovers and all account/draft/group selection behavior are
  unchanged.
- `ComposerModal` now delegates to the shared shadcn-backed `Modal` wrapper
  instead of owning its own portal, backdrop, `role="dialog"` shell, focus trap,
  Escape listener, and motion panel. The lazy Composer import, close behavior,
  body scroll lock, focus restore, and modal route entry remain intact.
- The current broad Composer route/support scan reports no active banned
  legacy presentation patterns except the allowed hidden upload input in
  `MediaGrid`. Visible Composer controls are already routed through
  shadcn-backed Juno wrappers, so the next Composer work should focus on
  higher-order anatomy polish rather than raw-control replacement.
- The targeted Composer route scan now reports no `motion/react`,
  `MobileActionBar`, `MobileSheet`, `DashboardCard`, `AppScreen`,
  `PageHeader`, `operator-*`, `dv2-*`, `j33-*`, `.card`, or raw visible
  controls in `src/pages/Composer.tsx`. The only remaining raw input in the
  Composer support surface is the allowed hidden media file input in
  `MediaGrid`.

Remaining Slice 3M work:

- Continue replacing remaining Composer support-component internals with shared
  `FormSection`, `DataPanel`, `NovaCard`, `Field`, `InputGroup`,
  `ToggleGroup`, `Tabs`, `Popover`, `Command`, `Sheet`, and `Empty`
  composition where the Nova anatomy is still weaker than the target preset.
  This is now a visual-anatomy pass, not a raw-control strip.
- Review icon sizing against the shadcn rule that button icons should rely on
  `data-icon` and component CSS rather than explicit sizing classes.
- Browser QA `/composer` desktop and mobile for account selection, upload,
  caption editing, slash commands, AI generation, scheduling, publish/queue,
  modal dirty guard, and preview tabs.

### Slice 3N — Calendar Control Surface Strip

Current progress:

- The active `/calendar` route shell now uses the Nova route facade:
  `NovaScreen`, `NovaHeader`, `NovaSection`, `NovaToolbar`, `NovaStat`,
  `NovaDataPanel`, and `NovaCard`. FullCalendar remains the scheduling engine,
  and date/view/platform/group URL state, account scope, drag/drop reschedule,
  empty-slot Composer handoff, duplicate/delete, refresh, and post detail sheet
  behavior are unchanged.
- The active Calendar route audit now bans the old `AppScreen`, `PageHeader`,
  `DashboardCard`, `DataPanel`, and `StatCard` shell imports/JSX in
  `src/pages/Calendar.tsx` while continuing to check that route for raw visible
  controls.
- `CalendarFilterBar` now renders through `DashboardCard`, `Badge`, and
  `Separator` instead of a local card shell, custom divider, and terminal-style
  draft-review label.
- Campaign Factory filter fields now let the shared shadcn-backed `Input`
  wrapper own control styling and mobile-safe sizing. The route only supplies
  width constraints.
- `RescheduleHistoryPanel` now delegates to the shared shadcn-backed `Sheet`
  wrapper instead of a local fixed `motion.aside` dialog shell and custom close
  chrome. The Supabase history query, user scoping, and close behavior are
  unchanged.
- `CalendarHero` now uses semantic muted tokens in its `PageHeader` filter
  metadata instead of the old `text-label-*` vocabulary.
- `PostDetailSlideOver` no longer uses `space-y-*` stack classes in active
  detail/history/analysis sections, and its comment theme chips now use the
  shared shadcn-backed `Badge` wrapper instead of custom pill spans. Post
  editing, audio history, autopsy, sentiment scanning, retry, duplicate, delete,
  and Composer handoff behavior are unchanged.
- `PostDetailSlideOver` is also old-token clean for Calendar-local scans: the
  verdict fallback, character counter fallback, header controls, metadata
  labels, analysis rows, asset diagnostics, and empty/detail copy now use
  semantic muted tokens, and the slide-over panel uses the shared `bg-card`
  surface instead of bespoke white/dark backgrounds.
- The focused Calendar route/control scan now reports no raw visible controls,
  `space-y-*`/`space-x-*`, legacy wrapper names, or active
  `operator-*`/`dv2-*`/`j33-*` classes in the cleaned Calendar route and
  filter/control surfaces.
- `TimezoneGutter`, `MonthViewGrid`, and `PortfolioMatrix` no longer use old
  `text-label-*`, `var(--color-label-*)`, or `color-card-elevated` tokens.
  Their timezone labels, month legend/day metadata, and portfolio matrix table
  headers/cells now use semantic shadcn/Nova muted tokens while preserving
  scheduling navigation, capacity requests, and sticky grid/table behavior.
- `WeekViewGrid` day headers and overflow day drawer now use semantic
  `text-muted-foreground`, `bg-card`, and `border-border` tokens instead of
  old label tiers, custom white/dark surfaces, and `color-card-elevated`
  borders. Drag/drop, overflow drawer, and post-card interactions are
  unchanged.
- `DBSyncVisualizer` now uses semantic muted tokens for its sync status,
  labels, row metadata, and close affordance while preserving the Supabase
  polling/realtime comparison behavior.
- `PostCardRow` and its hover preview no longer use old `text-label-*`,
  `color-card-elevated`, or hardcoded white/dark preview surfaces. Platform
  metadata, quick-move menu labels, campaign tags, preview section labels, and
  meta-grid labels now use semantic shadcn/Nova muted tokens and `bg-card`
  while preserving drag, quick-move, hover preview, campaign metadata, and
  selection behavior.
- The route-local Calendar `CommandPalette` now uses a solid `bg-card`,
  `border-border`, semantic placeholders, muted preview metadata, and a muted
  preview panel instead of the old black/white command shell and `text-label-*`
  hierarchy. Natural-language parsing, Gemini preview, fill-gap action,
  diff rendering, and confirm behavior are unchanged.
- `PostingStreakMatrix` no longer uses old `text-label-*` or
  `var(--color-label-*)` tokens. Header copy, summary labels, sticky table
  headers, account metadata, heatmap fallback text, empty rails, and leader rows
  now use semantic muted tokens while preserving month navigation, scoped
  account routing, compose-for-date behavior, and heatmap cell mechanics.
- Calendar group, platform, gap, best-hours, travel-timezone, history, and
  Campaign Factory filter behavior are unchanged.

Remaining Slice 3N work:

- Continue replacing lower-priority custom table/grid and sheet/detail anatomy
  in Calendar list/detail surfaces with shadcn/Nova primitives.
  `PostingStreakMatrix` still needs optional shadcn table/grid anatomy polish,
  and `PostDetailSlideOver` still needs optional `Sheet`/section composition
  polish, but their old-token cleanup is complete.
- Preserve custom scheduling grid mechanics while migrating surrounding
  headers, sheets, popovers, rows, empty states, labels, and footer zones.
- Browser QA `/calendar` desktop and mobile for filters, post detail sheet,
  drag/reschedule, command palette, portfolio/streak views, and empty states.

### Slice 3O — Reliability, Publishing, And Attribution Token Strip

Current progress:

- `Reliability.tsx`, `PublishingSetup.tsx`, `Attribution.tsx`, and the active
  publishing cards/checklists now use semantic Nova/zinc text tokens instead of
  the old `text-label-*` vocabulary in touched presentation.
- `PhoneSetupChecklist` and `PublishingReadinessPanel` render through
  `DashboardCard`, `Badge`, `Button`, `Empty`, and `ListRow` composition instead
  of old direct `Card material=*` shells and dense row cards.
- Attribution no longer uses `app-label` or `attribution-material-row` in the
  active conversion journey, path/source rows, confidence reasons, top-post
  rows, or top-day rows. The remaining `attribution-*` classes are layout hooks
  for journey/table responsiveness and should be replaced in a dedicated
  `DataPanel`/`Table` pass.
- `npm run audit:legacy-ui` now enforces the semantic-token cleanup for
  Reliability, Publishing Setup, Attribution, and active publishing components.
- Reliability refresh, recovery navigation, Publishing push/PWA/test
  notification behavior, Attribution account/period controls, confidence ring,
  hooks, and analytics fetching are unchanged.

Remaining Slice 3O work:

- Replace Attribution's remaining custom `attribution-table` and
  `attribution-journey` layout helpers with shadcn/Nova `DataPanel`, `Table`,
  and card-grid composition after responsive QA.
- Continue polishing Reliability API usage rows and Publishing setup panels
  toward full Nova card anatomy, but the active raw-control/token strip is now
  audit-enforced.
- Browser QA `/reliability`, `/setup/publishing`, and `/attribution` desktop
  and mobile for refresh/recovery actions, push/test controls, filters,
  confidence ring layout, and chart/table sizing.

### Slice 3P — Autopilot, Ideas, Listening, And Approval Queue Token Strip

Current progress:

- `Autopilot.tsx`, `AutopilotModePages.tsx`, `Ideas.tsx`, `Listening.tsx`, and
  `ApprovalQueue.tsx` now use semantic Nova/zinc text tokens instead of the old
  `text-label-*` vocabulary in active presentation.
- The Autopilot avatar overlap stack no longer uses `space-x-*`; it preserves
  the same visible overlap with explicit negative margins.
- The focused route-group scan now reports no old wrapper names,
  `operator-*`/`dv2-*`/`j33-*` classes, `space-y-*`/`space-x-*`, or raw visible
  controls. The only raw-control hit is Ideas' hidden screenshot file input,
  which remains allowed upload plumbing.
- `npm run audit:legacy-ui` now enforces semantic-token cleanup for Autopilot,
  Autopilot mode pages, Ideas, Listening, and Approval Queue.
- Autopilot service calls, replay/retry behavior, Ideas local/remote merge and
  Composer handoff, Listening workflow persistence, and Approval Queue
  decide/revise/execute API behavior are unchanged.
- `/ideas` now uses the Nova route facade: `NovaScreen`, `NovaHeader`,
  `NovaSection`, `NovaCard`, `NovaDataPanel`, `NovaToolbar`, and `NovaEmpty`.
  Route-level `motion/react`, direct `AppScreen`, `PageHeader`, and
  `DashboardCard` usage are removed from the active Ideas route. The hidden
  screenshot file input remains as allowed upload plumbing.
- `npm run audit:legacy-ui` now enforces the Ideas shell replacement so old
  bridge imports or JSX cannot return in `src/pages/Ideas.tsx`.
- `/autopilot` now uses the Nova route facade: `NovaScreen`, `NovaHeader`,
  `NovaSection`, `NovaToolbar`, and `NovaDataPanel`. Route-level
  `motion/react`, direct `AppScreen`, `PageHeader`, `DashboardCard`, and the
  old reveal bridge are removed from the active Autopilot route and mode pages.
- `npm run audit:legacy-ui` now enforces the Autopilot shell replacement in
  `src/pages/Autopilot.tsx` and `src/components/autopilot/AutopilotModePages.tsx`.
- `/listening` now uses the Nova route facade: `NovaScreen`, `NovaHeader`,
  `NovaSection`, `NovaStat`, `NovaToolbar`, and `NovaDataPanel`. Route-level
  `motion/react`, direct `AppScreen`, `PageHeader`, `DashboardCard`, and the old
  analytics KPI ribbon classes are removed from the active Listening route.
- `npm run audit:legacy-ui` now enforces the Listening shell replacement in
  `src/pages/Listening.tsx`.

Remaining Slice 3P work:

- Autopilot shell and mode panels are Nova-replaced; remaining work is browser
  QA, density polish, and deeper table/row anatomy only where health and replay
  diagnostics still read as too custom.
- Replace Approval Queue payload editor, diff/timeline, and detail cards with
  shadcn/Nova `Field`, `Textarea`, `Select`, `DataPanel`, `Accordion`, and
  code/diff wrappers while preserving idempotent action behavior.
- Polish Ideas internals only where needed after browser QA; its route shell,
  capture panel, generated queue, inspector, status shelves, and empty states
  now use Nova card/data-panel anatomy. Listening shell, KPI strip, monitor
  form, signal sections, and side panels now use Nova anatomy; remaining work is
  only deeper signal-row density and browser QA.
- Browser QA `/autopilot`, `/ideas`, `/listening`, and `/approval-queue`
  desktop/mobile for mode switching, capture forms, filters, replay/retry,
  add-to-ideas, approve/revise/execute, and empty/loading states.

### Slice 3Q — Auth, Welcome, Legal, And Landing Token Strip

Current progress:

- `AuthLayout` no longer depends on the old `auth-*` command-panel/product
  preview CSS. It now uses shadcn-backed `Card`, `Badge`, and semantic
  Nova/zinc utility classes while preserving the same auth route outlet.
- `Login`, `Signup`, `ResetPassword`, `InviteAccept`, `OAuthCallback`,
  `AuthCallback`, and `Welcome` no longer use the old `auth-panel`,
  `auth-field`, `auth-primary-action`, `auth-secondary-action`,
  `auth-divider-label`, `auth-legal-copy`, or `auth-plan-strip` visual classes.
- `LegalPage` no longer uses the route-local `legal-prose`/`underline-link`
  style island; legal links, lists, and strong text now use semantic tokenized
  utility classes.
- Dead `auth-*` CSS for the previous auth visual system was removed from
  `src/index.css`.
- `npm run audit:legacy-ui` now covers `AuthLayout`, all active auth pages,
  legal, and landing, and bans the removed auth/legal presentation tokens from
  those files.
- Auth sign-in, sign-up, reset, MFA, OAuth callback, invite accept, onboarding,
  legal navigation, and landing route behavior are unchanged.

Remaining Slice 3Q work:

- Rebuild auth pages more fully around shadcn auth block anatomy and SVGL
  provider logos; the current checkpoint is a token/control strip, not final
  marketing-grade auth polish.
- Browser QA `/login`, `/signup`, `/auth/reset-password`, `/welcome`,
  `/privacy`, `/terms`, `/gdpr-deletion`, and `/` in desktop/mobile and
  dark/light states.
- Public shared-report polish remains separate from this auth/legal/landing
  checkpoint.

### Slice 3R — Analytics Evidence Primitive Ratchet

Current progress:

- `EvidenceTileHeader` now uses semantic Nova/zinc muted text for hint and
  data-quality rows instead of the old `text-label-*` token vocabulary.
- `EvidenceRows` section headers now use semantic muted text while preserving
  the existing evidence grouping, lazy section loading, account scope, and
  analytics tile composition.
- `scripts/check-active-legacy-ui.mjs` now includes
  `EvidenceRows`, `EvidenceTile`, `EvidenceTileHeader`, `EmptyEvidenceTile`,
  and `LoadingEvidenceTile` in the strict semantic-token clean set. That makes
  the shared analytics evidence shell a ratcheted surface: future changes
  cannot reintroduce `text-label-*` or `color-card-elevated` there without
  failing `npm run audit:legacy-ui`.
- `ExportCsvButton`, `CohortChip`, `DateRangeChip`, and
  `hero/HeroSparkline` are now in the strict semantic-token clean set. Export
  menu hints, cohort opt-in help copy, hero sparkline fallback badges, and
  sparkline captions now use shadcn/Nova semantic tokens and the shared `Badge`
  wrapper where appropriate.
- `InsightsRail` is now in the strict semantic-token clean set. The 24h
  anomaly states, anomaly severity chips, evidence queue row metadata, and
  snapshot rows use semantic Nova/zinc tokens and shared `Badge` styling while
  preserving anomaly drill-in, account scope updates, and evidence anchors.
- `HeroTile` is now in the strict semantic-token clean set. The analytics hero
  narrative copy, investigation path subtitle, scope/date chip, command-row
  captions, recommended-action panel, and reach-trace labels now use semantic
  Nova/zinc tokens and shared `Badge` styling while preserving narrative
  generation, fleet metrics, anomaly counts, investigate actions, evidence
  scroll targets, and custom reach-trace SVG math.
- `AudienceOverlapTable` now renders its populated table state through direct
  `EvidenceCard` composition instead of the `EvidenceTile` data bridge. Its
  shared-count column and provenance footer now use Nova/zinc semantic tokens,
  while the TanStack `DataTable`, audience-overlap hook, account scoping, and
  investigate action remain unchanged. Empty/loading states still use the
  already-audited shared evidence primitives.
- `MatrixCoordinateTile` now renders its populated matrix state through direct
  `EvidenceCard` composition instead of the `EvidenceTile` data bridge. Header
  cells now use semantic Nova/zinc muted text, while the account metric rows,
  heat coloring, metric formatting, and empty-state behavior remain unchanged.
- `FormatMixWowTrend` now renders its populated routine bar-chart state through
  direct `EvidenceCard` composition instead of the `EvidenceTile` data bridge.
  The chart tick labels, format delta rows, and neutral/no-baseline values now
  use Nova/zinc semantic tokens while the content-type trend hook, Instagram
  scope filtering, investigate action, and Recharts bar comparison remain
  unchanged.
- `CompetitorBenchmarkPanel` now renders its populated peer-percentile state
  through direct `EvidenceCard` composition instead of the `EvidenceTile` data
  bridge. The headline percentile copy, bullet-chart tick labels, peer stat
  rows, and marker chrome use Nova/zinc semantic tokens while the competitor
  benchmark hook, account resolution, listening deep-link, investigate action,
  and bullet-chart math remain unchanged.
- `ContentMixTernaryTile` now renders its populated drift plot through direct
  `EvidenceCard` composition instead of the `EvidenceTile` data bridge. The
  summary panels, mix-stat labels, and SVG axis labels now use Nova/zinc
  semantic tokens while the `useContentMixHealth` hook, Instagram account
  fallback behavior, composer rebalance action, investigate action, and ternary
  SVG math remain unchanged.
- `PostingCadenceHeatmapTile` now renders its populated cadence heatmap through
  direct `EvidenceCard` composition instead of the `EvidenceTile` data bridge.
  The action row uses shared `Badge` metadata and semantic Nova/zinc labels
  while the Supabase published-post query, account/group scoping, calendar
  deep-link, historical account hydration, and heatmap cell-intensity math
  remain unchanged.
- `EqsForecastCiTile` now renders its populated forecast state through direct
  `EvidenceCard` composition instead of the `EvidenceTile` data bridge. The
  latest-score copy, summary labels, confidence slider label, explanatory
  source note, legend labels, and EQS helper tooltip now use semantic Nova/zinc
  tokens and the shared `Tooltip` wrapper while the scoped EQS trend hook,
  forecast computation, confidence slider state, SVG forecast band, outlier
  detection, and investigate action remain unchanged.
- `DiscoveryFunnel` now renders both populated branches through direct
  `EvidenceCard` composition instead of the `EvidenceTile` data bridge. The
  fleet aggregate funnel and account-specific funnel now share a local
  Nova/zinc `FunnelBars` renderer, semantic stat/source/correlation labels, and
  shared `Badge` metadata while the Instagram fleet KPI hook, funnel correlation
  hook, account resolution, aggregate scope labeling, post-level converter list,
  and investigate actions remain unchanged.
- `ViewsBySourceChart` is now in the strict semantic-token clean set. Its
  Recharts axis tick labels use Nova/zinc semantic muted tokens while the
  Threads source-mix hook, 100%-stacked normalization, Recharts area series,
  shadcn/Nova `EvidenceCard` shell, tooltip adapter, and investigate action
  remain unchanged.
- `AnnotationSwimLanesTile` now renders its loading, empty, and populated
  swim-lane states through direct `EvidenceCard`, `Empty`, and `Skeleton`
  composition instead of `EvidenceTile`/`EvidenceTileHeader`. The lane labels,
  footer copy, and panel chrome now use Nova/zinc semantic tokens while the
  chart-annotation hook, lane assignment, event positioning, and custom
  swim-lane visualization remain unchanged.
- `DistributionInputsPanel` now renders directly through `EvidenceCard`
  instead of `EvidenceTile`/`EvidenceTileHeader`, and no longer depends on the
  old `analytics-distribution-*`, `analytics-rank-*`, `analytics-surface-*`,
  `analytics-skip-*`, or `analytics-muted-*` presentation classes. Its mini
  KPI strip, format bars, audience surface rows, hashtag rows, friction list,
  and empty state now use Nova/zinc semantic card/list/progress anatomy while
  preserving all existing distribution hooks, account/group scope resolution,
  investigate action, format/surface/hashtag/skip/discovery calculations, and
  data contracts.
- `ConversationSystemPanel` now renders directly through `EvidenceCard`
  instead of `EvidenceTile`/`EvidenceTileHeader`, and no longer depends on the
  old `analytics-conversation-*`, `analytics-depth-*`, `analytics-quote-*`,
  `analytics-account-mini-list`, `analytics-ghost-*`, or
  `analytics-originality-*` presentation classes. Its system-state card,
  reply-depth bars, quote/reply metric pills, suppression queue, originality
  risk strip, and empty account list now use Nova/zinc semantic card/list/chart
  anatomy while preserving the reply-depth, quote/reply, ghost-post, and
  originality hooks, scoped inbox action, investigate action, score formula,
  and dial SVG.
- `QuoteReplyRatioTile` and `EngagerRetentionTile` are now in the strict
  semantic-token clean set. Their remaining `app-label` microtypography has
  been replaced with explicit Nova/zinc muted uppercase labels while their
  existing `EvidenceCard` shells, loading/empty states, quote/reply ratio
  hook, engager-retention hook, account resolution, account/engager lists, and
  investigate actions remain unchanged.
- `GhostPostQueueTile` and `ReplyDepthDistributionTile` are now in the strict
  semantic-token clean set. Their remaining `app-label` microtypography has
  been replaced with explicit Nova/zinc muted uppercase labels while their
  existing `EvidenceCard` shells, loading/empty states, ghost-post queue hook,
  reply-depth hook, scoped calendar/investigate actions, stat rows, account
  queue rows, and histogram bars remain unchanged.

### Completed Checkpoint: Analytics Audience + Compare Product Pass

- `/analytics?tab=audience` now renders real Nova/shadcn panels instead of a
  placeholder: follower movement, non-follower reach availability, and
  scoped-account demographics from `useAudienceDemographics` when Meta returns
  real buckets. All-account and group scopes clearly explain that demographic
  reads require a single account.
- `/analytics?tab=compare` now renders a prior-period comparison workspace
  using existing fleet KPI and fleet metric aggregates, plus platform split and
  account mover panels. Peer, cohort, and year-over-year modes are explicit
  unavailable states until deeper source data exists.
- The Dashboard/Analytics content tracker marks Audience, Links, and Compare
  as implemented for the first pass, with cohort overlap, campaign/tag filters,
  and richer compare dimensions kept as data-source follow-ups.

### Completed Checkpoint: Dashboard Diagnostic Language Pass

- `/dashboard` now replaces visible internal labels such as Evidence, Ops
  health, Fleet capacity, AI evals, classifier-backed reads, Hook-class lift,
  and scorecard with operator-facing copy such as Insights, Account issues,
  Posting coverage, AI readiness, Content patterns, Performance summary,
  Conversation leaders, Performance leaders, and What to review.
- The pass preserves DashboardV2 feature composition, tile error boundaries,
  hooks, URL/platform state, refresh behavior, and navigation while reducing
  primary-dashboard diagnostic language.
- The Dashboard/Analytics content tracker marks diagnostic relocation as in
  progress. Remaining relocation targets are deeper specialist diagnostics
  that should move to Reliability, Accounts, Analytics detail, or be removed
  after product review.

### Completed Checkpoint: Dashboard Widget Anatomy Pass

- The primary All dashboard KPI strip now uses richer Nova-style stat cards
  with icon wells, dominant values, trend rails, and footer metadata while
  preserving the existing fleet KPI and fleet metric hooks.
- The attention, trend, top-content, publishing runway, and inbox cards now
  use clearer action/footer zones and content-performance rows that surface
  account, platform, views, and engagement totals directly.
- The pass keeps DashboardV2 URL state, platform switching, refresh behavior,
  account/group scope, composer actions, and specialist drilldowns unchanged.

Remaining Slice 3R work:

- Continue replacing `EvidenceTile`/`EvidenceTileHeader` imports inside
  individual analytics-v2 evidence widgets with direct `EvidenceCard`,
  `DashboardCard`, `DataPanel`, `Empty`, and `Skeleton` composition where each
  tile is touched.
- Continue converting individual analytics-v2 evidence widgets from
  `EvidenceTile`/`EvidenceTileHeader` bridge shells to direct `EvidenceCard`,
  `DataPanel`, `Empty`, and `Skeleton` composition.
- Preserve custom analytical SVG/chart internals unless the shell itself is the
  legacy surface.

## Public Interfaces

- Backend APIs, services, hooks, auth, billing, analytics fetching, and routing
  remain stable.
- New frontend-facing primitives live under `src/components/ui/*` or
  `src/components/layout/*`.
- Generated shadcn primitives remain under `src/components/shadcn/*`.
- Registry-derived components are never used directly in product routes.

## Test Plan

For the doc-only step, no code tests are required.

For every rebuild slice:

- `npm run typecheck`
- `npm run compat:check`
- focused Vitest tests for touched wrappers/routes
- `npm run build`
- browser QA in dark and light mode
- browser QA on desktop and mobile widths
- verify no clipped overlays, broken focus states, blank charts, horizontal
  overflow, or major layout shifts

## Assumptions

- The goal is a real frontend rebuild, not incremental styling.
- shadcn/Nova is the primary design system.
- Blocks.so and EvilCharts are secondary pattern sources.
- Juno oxblood remains the primary action/accent color.
- Old Juno visual language should be removed from rebuilt routes, not preserved.
