# Juno33 2026 Frontend Pro Master Plan

Last updated: 2026-06-16

## Summary

This is the master execution plan for taking Juno33 from "mostly shadcn/Nova
clean" to a professional 2026 SaaS frontend. The goal is not to add more visual
noise. The goal is to make every user-facing page feel intentional, readable,
fast, responsive, and consistently built from the approved shadcn/Nova system.

The backend stays intact. Hooks, services, auth, billing, publishing,
scheduling, analytics fetching, telemetry names, account/group scope, route
URLs, and workflow actions remain the source of truth. If a screen is messy,
the visible frontend can be rebuilt around existing behavior.

## Source Of Truth

Use these docs together:

- `docs/APP_INFORMATION_ARCHITECTURE.md`: what routes users should see.
- This document: frontend execution order, quality standards, component rules,
  shadcn/Blocks adoption rules, dashboard/content/analytics direction, route
  completion criteria, and final acceptance checks.

Older migration/status docs were intentionally retired after this master plan
became the frontend execution controller. Do not recreate separate frontend
planning trackers unless a future task needs a temporary implementation note.

## Finish Line

This project is "done" when all of these are true:

- Primary routes rate at least **8.5/10** on desktop and mobile in light and dark:
  `/dashboard`, `/content`, `/calendar`, `/composer`, `/inbox`, `/analytics`,
  `/accounts`.
- Secondary/account routes rate at least **8.0/10**: `/links`, `/ideas`,
  `/listening`, `/reports`, `/autopilot`, `/settings`, `/billing`.
- No primary route has document-level horizontal overflow at common mobile,
  tablet, laptop, and desktop widths.
- Light mode uses Nova/zinc substrate: app frame on muted zinc, cards on white,
  semantic foreground/muted/border tokens, Juno oxblood only for intent.
- Dark mode uses Nova/zinc dark surfaces without custom one-off dark overrides.
- shadcn composition is visible everywhere: Card, Field, Table, Chart, Sheet,
  Dialog, Command, Tabs, Badge, Skeleton, Empty, Progress, Tooltip.
- User-facing pages do not expose backend/operator jargon unless behind an
  advanced or contextual route.
- Loading, empty, error, disabled, mobile, and keyboard states are present for
  every major workflow.
- Checks pass: `npm run audit:legacy-ui`, frontend quality audit, `npm run
  typecheck`, `npm run compat:check`, focused tests, and `npm run build`.

## Design System Standard

### Visual Target

- shadcn Nova/zinc with Juno oxblood for primary/action/selected states.
- Match Nova by anatomy, not only colors: 1px borders, compact headers, clear
  values, muted descriptions, calm cards, steady radii, and consistent gaps.
- Final preset lock: Nova/zinc/Lucide/default radius with Inter. Current shadcn
  config resolves Nova/zinc/Lucide, and the product UI uses Inter via
  `@fontsource/inter` imports in `src/main.tsx`.

### Current shadcn Snapshot

Verified on 2026-06-16 with `npx shadcn@latest info --json`:

- Framework: Vite.
- Tailwind: v4.
- Base library: Radix.
- Style/base/theme: Nova, zinc, red theme source with Juno oxblood replacing
  primary/action red in product tokens.
- Icon library: Lucide.
- Radius: default.
- CLI preset metadata currently resolves preset code `bcizC9tQ` with
  `font: "geist"`, but the product frontend lock is Inter to match the user's
  chosen Nova/Inter target. `npm run audit:frontend-quality` requires Inter
  imports in `src/main.tsx` and bans `"Geist Sans"` from `src/index.css`.

### Component Rules

- Product routes import Juno-owned wrappers from `src/components/ui/*` and
  `src/components/layout/*`.
- Generated shadcn source stays under `src/components/shadcn/*`.
- Use full shadcn composition: `CardHeader`, `CardTitle`,
  `CardDescription`, `CardContent`, `CardFooter`, `FieldGroup`, `Field`,
  `Table`, `ChartContainer`, `Sidebar`, `Sheet`, `Tabs`, and `Command`.
- New form work uses the Juno React Hook Form adapters in
  `src/components/ui/Form.tsx`. Use Zod schemas with `zodResolver`, render
  controls through `FormInputField`, `FormTextareaField`, `FormSelectField`,
  `FormSwitchField`, or `FormCheckboxField`, and keep validation states on
  Juno `Field` wrappers. Current migrated forms include Settings API keys,
  Webhooks, Profile, Workspace preferences, and the Reports editor's metadata
  and delivery controls. Composer remains custom until a dedicated behavior
  migration because its publish/media/AI state is not a simple form.
- Use Blocks.so source when it improves stat cards, dense tables, upload zones,
  command menus, pricing/forms, or settings layouts. Promote useful anatomy
  into Juno wrappers before route use.
- Blocks.so adoption is implementation input, not a route-level dependency.
  The current shadcn CLI cannot install selected Blocks items directly because
  the registry resolves a missing Nova button item, so use
  `npx shadcn@latest view @blocks-so/<name>` and adapt the source into Juno
  wrappers. Active adoption now includes Blocks-style usage rows in
  `NovaUsageList`, dense table anatomy in `DataTable`/Content,
  upload/status anatomy in `UploadZone` and `UploadStatusList`, and grouped
  command anatomy in `CommandMenuShell`/`CommandMenuActionRow`.
- Use EvilCharts as a styling reference for routine charts after chart wrappers
  are normalized.
- Use SVGL local logos for providers and platforms.
- Use Dot Matrix only for long-running AI, publish, report, import, sync, or
  investigation jobs.

### Shared KPI Contract

- Dashboard and Analytics must use `src/lib/kpiPresentation.ts` for overlapping
  metric labels, descriptions, compact formatting, percent formatting, delta
  copy, and trend direction.
- Shared labels are locked as: `Views`, `People reached`, `Engagement rate`,
  `Follower growth`, and `Link clicks`.
- `Views` means the best available views/reach value until a dedicated views
  aggregate exists. `People reached` stays reach-backed audience count.
  `Engagement rate` means interactions divided by views/reach.
- Follower percentage movement is always labeled `Follower growth`. Do not call
  it `New followers` or `Net followers` unless the value is a count.
- Dashboard may add daily operator cards such as scheduled posts, attention
  work, publishing runway, top content, and inbox queue. Analytics may add
  investigation cards such as engagements, saves, shares, replies, audience,
  posts, accounts, links, and compare. Overlapping KPIs still use the same
  helper.

## Execution Tracks

### Track 1: System Lock And Audits

Make drift hard to reintroduce.

- Add or wire `audit:frontend-quality`.
- Fail on raw visible colors, fragile fixed rails, route-level raw controls,
  overflow-prone widths, backend copy on primary pages, and direct raw registry
  imports.
- Require shared additions to stay present: RHF form adapters, Blocks-style
  upload/command adapters, TanStack-based virtualization gate, and Storybook
  quality stories.
- Storybook/Chromatic is the visual QA path. `npm run build-storybook` must
  work locally; `npm run chromatic` uploads only when `CHROMATIC_PROJECT_TOKEN`
  exists and otherwise exits cleanly.
- Keep the shadcn info snapshot documented: Vite, Tailwind v4, Radix, Nova,
  zinc, Lucide, installed core primitives.
- Lock the product palette to Nova/zinc + Juno oxblood. Legacy alternate
  palette values are neutralized at first paint, and Appearance no longer
  exposes non-Nova palette choices.
- Browser QA with screenshots for desktop and mobile, light and dark.

### Track 2: Layout, Spacing, And Responsiveness

Make every route feel stable.

- Standardize route padding, content max width, bento gaps, card min heights,
  section rhythm, table containment, and mobile breakpoints.
- Replace fixed side rails with responsive layouts: full-width primary content,
  optional collapsible rails, and sheets/drawers on smaller screens.
- Keep `NovaScreen`, `NovaBentoGrid`, `NovaDataPanel`, `DataTable`, and
  calendar shells as the layout primitives.
- Acceptance: no touching cards, random blank regions, clipped bottom nav,
  squished rails, or document-level horizontal overflow.

### Track 3: Widget Anatomy

Make the app look like a premium shadcn dashboard.

- KPI cards: label, value, delta, comparison, evidence cue.
- Evidence cards: finding first, chart/metric second, next action third.
- Action cards: operational pressure plus a direct action.
- Feed/list cards: identity, primary line, meta line, quiet action.
- Chart cards: one question, direct labels, neutral secondary series, oxblood
  highlight, clear footer caveat.
- Apply first to Dashboard, Content, Analytics, Accounts, Billing, and Reports.

### Track 4: Page IA And Content Quality

Make every page show what users actually care about.

- Dashboard: daily outcomes, attention work, what changed, top content,
  publishing runway, inbox.
- Content: full-width recent posts, post detail sheet, filters, status, post
  performance, follow-up actions.
- Analytics: overview, posts, accounts, audience, links, compare.
- Calendar: readable scheduling workspace, not a metric dashboard.
- Composer: focused creation flow with upload, AI, preview, schedule, publish.
- Inbox: split-pane conversation work, assignment, reply, AI draft, done.
- Accounts: connection, readiness, identity, issues, quick fixes.
- Automation: user-safe controls; debug/run internals behind advanced panels.
- Settings/Billing: account/workspace/admin flows without dashboard clutter.

### Track 5: Feedback, Notifications, And State

Make the app feel alive and trustworthy.

- Standardize sonner toasts: success, error, warning, loading, action, undo.
- Add a notification center for publish results, failed posts, account issues,
  reply backlog, and billing/setup alerts.
- Error states must include the next useful action.
- Loading states must preserve layout height and avoid jumps.
- Empty states must explain what to do next.
- Disabled buttons must explain why via copy, tooltip, or nearby state.

### Track 6: Motion, Haptics, And Premium Loading

Add restraint, not gimmicks.

- Use `MotionReveal`, `MotionList`, and `MotionCard` for bounded first-load
  reveals only.
- Keep control transitions under 200ms and sheets/dialogs around 200-300ms.
- Respect `prefers-reduced-motion`.
- Use Button `haptic` intentionally: selection, success, warning, error.
- Use `ProcessingState`/Dot Matrix only for long-running jobs.
- Current checkpoint: the shared motion wrappers, Button haptic API,
  reduced-motion haptic gate, Composer processing states, Calendar drag/drop
  haptics, and Dashboard bounded reveal/load states are active and guarded by
  `npm run audit:frontend-quality`.

### Track 7: Data Density, Tables, And Detail Sheets

Make dense SaaS surfaces easy to inspect.

- Standardize table toolbar anatomy: search, filters, saved view, sort, export,
  row actions, pagination/virtualization when needed.
- Use `VirtualizedList`/future virtual table wrappers built on the existing
  `@tanstack/react-virtual` dependency before considering `react-virtuoso`.
  Add `react-virtuoso` only if measured variable-height inbox/content lists
  remain hard to tune with TanStack Virtual. Current active adoption starts
  with the desktop Inbox conversation list and the mobile Content recent-post
  list.
- Use row detail sheets for Content, Analytics Posts, Accounts, Inbox, Links,
  Reports, and Approval/Automation detail.
- Mobile tables should become card/list plus sheet detail, not squeezed tables.

### Track 8: Charts And Analytics Polish

Make charts useful before decorative.

- Normalize routine charts through `JunoChartContainer` and shadcn chart
  anatomy.
- Use consistent chart card headers, legends, tooltips, loading, empty, and
  unavailable states.
- Use EvilCharts-style patterns for routine area, line, bar, source mix, and
  comparison charts only after the wrapper is stable.
- Avoid fake zeros for unavailable data.

### Track 9: Performance And Memory

Keep the app fast as polish increases.

- Preserve route lazy loading.
- Ensure FullCalendar only loads on Calendar.
- Lazy-load heavy below-the-fold dashboard and analytics panels.
- Virtualize only tables/lists that can exceed practical page-size rendering.
- Track chunk growth for Calendar, Dashboard, Composer, charts, and global CSS.
- No new large dependency without route-level justification.

## Route Completion Matrix

Each route is complete only when its row passes desktop/mobile, light/dark,
loading/empty/error/populated, and no-overflow QA.

| Route | Target outcome | Main work left |
| --- | --- | --- |
| Dashboard | Daily operator control tower | Overlapping KPIs now use the shared Dashboard/Analytics KPI contract, including `Follower growth` for percent movement; platform drilldowns use balanced Nova insight columns with no measured desktop/mobile overflow; primary paired bento rows stretch cards to avoid dead frame gaps. Remaining follow-ups are chart/list card polish and deeper first-screen widget refinement. |
| Content | Operational post-performance page | Recent Posts is dominant with a full desktop table, compact 2x2 mobile overview stats, virtualized mobile card/list rows, bounded long-list scrolling, and no measured desktop/mobile overflow in latest QA; follow-up signal/action/mix cards now sit in a balanced three-card row instead of a squeezed rail or spanning gap. Remaining follow-ups are post-sheet refinement and deeper campaign/tag enrichment when data exists. |
| Calendar | Readable scheduling workspace | Week grid uses compact route chrome, wider internal day columns, taller time slots, clearer event cards with account context, desktop-safe canvas breakpoints, contained mobile horizontal scrolling, and a mobile scroll cue; drag/drop now has explicit visual feedback; mobile status metrics live inside the calendar card instead of crowding the header; agenda view is internally contained instead of stretching the document; post-detail actions fit cleanly on desktop and mobile. Remaining follow-up is deeper event-density tuning after real schedule volume grows. |
| Composer | Premium creation workspace | Mobile action bar now keeps Preview, timing, Save, Checks, and Post labels readable without horizontal overflow; desktop rail now prioritizes Preview -> Schedule -> Readiness so the primary workflow stays visible; media dropzone, bulk upload status rows, Composer command palette, and slash menu now use Blocks-style adapters behind Juno wrappers. Remaining follow-ups are AI generation states, preview detail density, and deeper upload QA. |
| Inbox | Modern support-style inbox | Conversation list density, clearer filters, AI-ready row states, virtualized desktop conversation scrolling, support-style split pane, AI draft preview, and mobile detail drawer spacing are active. Remaining follow-up is richer notification surfacing and assignment analytics when source data is available. |
| Analytics | Investigation workspace | Overview and Compare now use the shared Dashboard/Analytics KPI contract for overlapping metric labels, descriptions, formatters, and deltas; mobile investigation tabs wrap into a discoverable two-row Nova tab group; Audience explains profile/non-follower availability instead of implying zeros. Remaining work is deeper chart grammar, persisted saved views, richer audience cohorts, and peer/cohort compare when source data exists. |
| Accounts | Connection/readiness table | First-screen table, group rail, detail sheet, and reconnect modal now have provider logos, calmer row density, contained horizontal scroll, action-oriented fix guidance, clearer connection state copy, and remediation-first issue rows; remaining follow-up is deeper account history when data allows. |
| Links | Conversion workspace | Link table, stats, detail sheet, preview/debug panels. |
| Ideas | Capture and handoff | Simpler board, stronger capture form, sheet details. |
| Listening | Signal triage | Better signal cards, less backend language, handoff actions. |
| Reports | Export/share workspace | Table/detail sheets, report builder states, scheduled report clarity; the editor metadata and delivery controls now use the Juno RHF adapters while behavior-heavy group/account/metric toggles remain local. |
| Automation | User-safe automation controls | Primary shell now uses Assistant, Schedule plan, Rules, Run history, and action-oriented issue/status copy; remaining work is deeper advanced run-detail polish and hiding any debug-only details behind explicit advanced affordances. |
| Settings | Admin/account control | Normal tab rail now keeps user/admin account controls prominent and hides labs, audit, danger-zone, and UX health as contextual direct-link panes; Appearance now locks the product to Nova/zinc + Juno oxblood and removes legacy palette switching. Remaining work is deeper field composition polish across older tab bodies. |
| Billing | Plan and usage control | Billing now uses a real Blocks.so stats pattern adapted into `NovaUsageList` for workspace headroom and current-plan usage rows. Remaining work is pricing-card polish, comparison table density, and Stripe state microcopy. |
| Content Library | Media operations | Upload modal now uses `UploadZone` and `UploadStatusList` adapted from Blocks upload anatomy while preserving Supabase storage registration, account/group assignment, 50MB validation, and cache invalidation. Remaining work is grid/card density and upload success/error QA across large media. |
| Auth/Welcome | Public conversion/auth flow | `login-04` anatomy, provider logos, OTP, clean legal copy. |

## Final Route QA Scorecard

Score each route after browser QA using the same rubric so the finish line is
not subjective. Primary routes must score **8.5/10+**; secondary/account routes
must score **8.0/10+**.

Closure sweep on 2026-06-15 covered 14 routes across desktop `1440x900`,
mobile `390x844`, light mode, and dark mode. Follow-up QA on 2026-06-16
re-ran the same 56 route/theme/viewport checks after the RHF/virtualization
system pass. The stable browser sweep found zero document-level overflow, zero
blank route bodies after loaded-state waits, and zero backend-jargon hits on
the approved route list.

| Route | Target | Current score | Required final checks |
| --- | ---: | ---: | --- |
| `/dashboard` | 8.5+ | 8.1 | 2026-06-15 browser sweep: no desktop/mobile document overflow; first-screen KPI/content/action hierarchy is active. Needs chart card grammar, platform-card density, and one more bento polish pass. |
| `/content` | 8.5+ | 8.1 | 2026-06-16 system pass: mobile Recent Posts now uses the TanStack-backed `VirtualizedList`; prior sweep had no document overflow and Recent Posts is the main surface. Needs post detail sheet density and campaign/tag enrichment only when real data exists. |
| `/calendar` | 8.5+ | 8.0 | 2026-06-15 closure pass: event cards gained clearer density/account context, week rows were expanded, drag/drop feedback is visible, and narrow-screen side panels remain sheet-based. Needs event-density tuning against populated schedules. |
| `/composer` | 8.5+ | 8.0 | 2026-06-15 browser sweep: mobile upload helper overhang fixed; no document overflow. Needs AI generation state, preview density, and mixed-media upload QA. |
| `/inbox` | 8.5+ | 8.1 | 2026-06-16 system pass: desktop conversation list now uses the TanStack-backed `VirtualizedList`; no document overflow from prior sweep. Needs notification surfacing and assignment analytics when data exists. |
| `/analytics` | 8.5+ | 8.0 | 2026-06-15 browser sweep: no document overflow; KPI contract and posts/audience/compare surfaces are active. Needs chart grammar and saved-view affordances. |
| `/accounts` | 8.5+ | 8.0 | 2026-06-15 closure pass: detail sheet hierarchy, provider identity, connection copy, and remediation-first issue rows were tightened. Needs deeper account-history polish when data allows. |
| `/links` | 8.0+ | 8.0 | 2026-06-16 Links polish: desktop/mobile QA stayed overflow-free, the link table now owns the primary width, the detail editor is a contextual rail, and the smart-link preview uses Nova tokens instead of hard-coded dark colors. Needs richer conversion attribution only when source data exists. |
| `/ideas` | 8.0+ | 7.6 | 2026-06-15 browser sweep: no document overflow. Needs capture/detail sheet polish and sharper composer handoff states. |
| `/listening` | 8.0+ | 7.6 | 2026-06-15 browser sweep: no document overflow. Needs signal-card hierarchy and stronger handoff action grouping. |
| `/reports` | 8.0+ | 7.7 | 2026-06-16 system pass: report editor metadata and delivery controls now use RHF adapters while existing send/preview/schedule behavior stays intact. Needs browser QA rescore plus detail/export/share state polish. |
| `/autopilot` | 8.0+ | 7.6 | 2026-06-15 browser sweep: no document overflow. Needs deeper advanced run-detail containment and action-state polish. |
| `/settings` | 8.0+ | 7.8 | 2026-06-16 system pass: API, Webhooks, Profile, and Workspace preferences now use the Juno RHF adapters. Needs remaining older tab-body Field/Card cleanup and browser QA rescore. |
| `/billing` | 8.0+ | 8.0 | 2026-06-16 Billing polish: current-plan, usage, payment-method, and highest-tier states now have clearer Stripe microcopy and no giant empty recommendation panel; desktop/mobile QA stayed overflow-free. Comparison matrix intentionally scrolls inside its frame on mobile. |

## Verification Loop

Run after each coherent slice:

```bash
npm run audit:legacy-ui
npm run audit:frontend-quality
npm run typecheck
npm run compat:check
npx vitest run <focused test files>
npm run build
```

Browser QA:

- Viewports: mobile 390px, tablet/narrow desktop, desktop 1440px+.
- Themes: light and dark.
- Routes: the changed route plus Dashboard, Content, Calendar, Analytics when
  layout primitives change.
- Checks: no horizontal overflow, no clipped controls, no blank card regions,
  no framework overlay, no relevant console errors, controls respond, sheets
  and menus fit, table/chart loading states do not jump.

## Implementation Rules For Future Goals

- Work in slices. Do not mix frontend polish with backend/autopost changes.
- Prefer replacing messy route presentation with a fresh Nova screen wired to
  existing hooks.
- Keep old route files as behavior checklists, not markup to preserve.
- Do not delete contextual/admin routes; hide or demote them according to IA.
- Do not spread a new Blocks/shadcn pattern until it is promoted into a Juno
  wrapper and verified in both themes.
- Every slice must report: what is now clean, what remains, screenshots used,
  checks run, and next route/track.
- New high-risk primitives need Storybook coverage with light/dark and mobile
  or desktop variants before being spread across routes.

## Final Acceptance Checklist

- [ ] All primary routes score 8.5/10 or higher.
- [ ] All secondary/account routes score 8.0/10 or higher.
- [x] No document-level mobile overflow on approved route list.
- [x] Light mode matches Nova/zinc substrate/card contrast.
- [x] Dark mode matches Nova/zinc contrast without one-off overrides.
- [ ] Global nav and commands match `APP_INFORMATION_ARCHITECTURE`.
- [ ] Dashboard/Content/Analytics match their tracker goals.
- [ ] Tables, charts, forms, sheets, toasts, loading, and empty states use
      shared shadcn/Nova wrappers. RHF form adapters, Storybook visual QA
      fixtures, and the TanStack virtualization gate are active; remaining
      work is route-by-route form migration and wider story coverage.
- [x] Backend/operator language is absent from primary pages.
- [x] Motion/haptics/loading are restrained and reduced-motion safe.
- [x] Build, Storybook build, visual smoke, typecheck, compat, legacy UI audit,
      frontend quality audit, focused tests, and full `npx vitest run` pass for
      the current frontend checkpoint.
