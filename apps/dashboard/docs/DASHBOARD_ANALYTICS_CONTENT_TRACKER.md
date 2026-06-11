# Dashboard + Analytics Content Tracker

This document tracks the product-level content architecture for the shadcn/Nova rebuild of `/dashboard` and `/analytics`.

The visual system target remains Nova/zinc with Juno oxblood actions, but the bigger fix is information architecture: the dashboard should help a user understand today, and analytics should help them investigate performance.

## Source Research

- Dashboard research: daily SaaS dashboard for Threads/Instagram operators.
- Analytics research: analytics workspace for performance diagnosis, post/account comparison, audience/link insights, and decision support.
- Current product direction: fewer internal diagnostics on primary screens, more user-facing metrics such as views, reach, engagement rate, followers, replies, publishing runway, and top content.
- Premium SaaS research: Juno33 should behave more like an operator control tower plus investigation workspace than a component gallery. The references to emulate are Linear for command workflows, Stripe for high-importance overview alerts, PostHog for dashboard-plus-insight narratives, Attio for alternate data views, Sprout for split-pane inbox operations, and Typefully/Later/Metricool for social planning workflows.

## Premium Product Principles

The research reframes "looking premium" as product clarity, not decoration.

### 1. Overview Versus Investigation

- Dashboard is for fast, low-friction understanding.
- Analytics is for deeper comparison, diagnosis, and saved investigation.
- Reliability, account health, logs, and advanced drilldowns should hold internal system detail.
- The primary dashboard should never feel like a backend health report.

### 2. Editorial Clarity

Every primary surface should answer:

1. What changed?
2. Why should I care?
3. What should I do next?

Copy should be plain and cautious. Prefer "worth checking" or "likely driven by" over fake certainty.

### 3. Operational Confidence

Juno33 needs to make work feel inspectable:

- Failed posts should have a direct action.
- Disconnected accounts should be obvious.
- Inbox backlog should show who is waiting and how old it is.
- Publishing runway should show empty days and upcoming scheduled posts.
- Analytics should explain metric movement without exposing raw worker or API internals by default.

### 4. Analytical Depth Without Intimidation

Analytics can be dense, but the first read should still be calm:

- Start with the key KPI row.
- Show one primary trend and one "What changed" narrative.
- Move deeper comparisons into tabs, table panels, or sheets.
- Do not put every available chart on the default view.

## Widget Anatomy Rules

Dashboard and Analytics widgets should use repeatable families instead of one-off cards.

### KPI Cards

- Label.
- Primary value.
- Delta.
- Comparison period.
- One evidence cue, such as a sparkline, ratio, progress rail, or footer note.

### Evidence Cards

- Finding first.
- Metric or chart second.
- One next action or drilldown third.
- Best for Analytics and insight summaries, not for every dashboard tile.

### Action Cards

- Show operational pressure: failed posts, disconnected accounts, approval bottlenecks, inbox backlog, empty schedule days.
- Always include a clear action.
- Avoid passive status-only cards if the user cannot do anything with them.

### Feed/List Cards

- Identity or logo.
- Primary line.
- Meta line.
- Quiet action or overflow menu.
- Best for inbox, content, account health, and posts needing review.

### Chart Cards

- One question per chart.
- Direct labels when possible.
- Neutral secondary series.
- Oxblood only for the highlighted series or selected point.
- Footer explains the time window, comparison, delay, or data caveat.

## Visual And Interaction Rules

- Neutrals carry the app; oxblood carries intent.
- Use oxblood for primary actions, selected tabs, active filters, and one highlighted metric or series.
- Use SVGL/provider logos as identity markers in account, integration, OAuth, and analytics rows. Do not use logos as decoration beside every metric.
- Use sentence case for tabs, table headers, labels, and buttons.
- Use tables with toolbars for global actions; row detail should open in a right-side sheet when the table becomes cramped.
- Use dialogs for confirmations and short finite decisions. Use sheets for post inspection, row detail, replies, account diagnostics, and settings edits.
- Use skeletons for initial card/table/page loading, inline loaders for actions, progress bars for upload/bulk publish, and Dot Matrix only for long-running AI/sync/processing states.
- Chart cards should favor interpretation over novelty: no dual y-axes, no rainbow palettes, use small multiples when too many series overlap, and prefer annotations over decorative legends.

## Dashboard Goal

`/dashboard` should answer six daily questions:

1. Are we getting seen?
2. Are we growing?
3. What content is working?
4. Is anything broken?
5. Are replies under control?
6. Is enough content scheduled?

The dashboard is not the place for deep diagnostics, API health, internal scoring mechanics, or broad evidence walls. Those can move into analytics, reliability, account health, or drill-down pages.

## Dashboard Target Layout

### 1. Global Controls

Keep this lightweight and persistent:

- Account or group scope.
- Platform selector: All, Threads, Instagram.
- Date range, defaulting to last 7 days vs previous 7 days.
- Refresh action.

Use plain labels and shadcn/Nova controls.

### 2. Daily KPI Strip

Primary cards:

- Views
- People reached
- Engagement rate
- New followers
- Profile visits or Link clicks, depending on workspace setup
- Scheduled posts this week or failed posts when operational pressure is high

Rules:

- Avoid static all-time counts as primary dashboard KPIs.
- Avoid abstract internal scores unless they explain an action.
- Show unavailable data separately from zero.
- Use prior-period deltas when available.

### 3. Action Needed

This should be one of the highest areas on the page.

Items:

- Failed posts
- Disconnected or expiring accounts
- Manual publish or approval needed
- High-priority inbox conversations
- Empty publishing days
- Sudden spike or drop worth reviewing

Each item should have a direct action button.

### 4. What Changed

Purpose:

- Explain movement in views, reach, interactions, followers, or link clicks.
- Show a compact trend chart.
- Include 1-3 plain-English driver notes.
- Link to Analytics when the explanation needs a deeper comparison.

Copy should use cautious language: "likely driven by", "correlated with", "worth checking", not fake certainty.

### 5. Top Content

Bring back the useful content-performance context the old content page provided.

Show:

- Top posts by views, engagement rate, saves, replies, or link clicks.
- Preview, account, platform, publish date, and key metric.
- Mature-content guardrail so brand-new posts are not labeled as losers too early.

### 6. Publishing Runway

Show:

- Next 7 days scheduled.
- Empty days.
- Failed items.
- Best posting time hint.
- Quick create/schedule action.

Do not show queue internals or low-level job health on the dashboard.

### 7. Inbox Queue

Show:

- Waiting for reply.
- Oldest waiting item.
- Unassigned count.
- Reply speed or SLA only if phrased in user-facing language.

### 8. Optional Role-Based Module

Use one based on workspace setup:

- Smart links users: Link results.
- Agencies or many accounts: Accounts needing attention.

## Dashboard Page Shape From Research

The recommended premium layout is:

1. Scope and controls.
2. Operational alerts if anything is urgent.
3. KPI row: views/reach, engagement rate, quality actions, follower movement, link clicks, scheduled/failed posts.
4. One primary performance chart.
5. What needs attention.
6. Top content.
7. Publishing runway.
8. Inbox queue.

This makes Dashboard a daily control tower, not a report builder.

## Dashboard Demotions

Move off the primary dashboard or hide behind drill-downs:

- Queue health.
- Sync success rate.
- Webhook health.
- API/token internals.
- AI/system usage stats.
- Raw anomaly feeds.
- Evidence walls.
- Quality classifier internals.
- Hook-class lift as a default dashboard card.
- Stories/reels diagnostics unless platform-specific view needs them.
- Competitor benchmarking.
- Demographic breakdowns.
- Normalization, maturity, telemetry, and internal scoring labels.

## Dashboard Plain-Language Labels

Prefer:

- Views
- People reached
- Engagement rate
- New followers
- Profile visits
- Link clicks
- Top posts
- Waiting for reply
- Posts scheduled this week
- Failed posts
- Days with no posts scheduled
- What needs attention
- Best time to post

Avoid:

- Fleet reach
- EQS
- Classifier-backed read
- Evidence queue
- Queue health
- Sync lane
- Webhook lane
- Normalization
- Maturity window, except in analytics detail copy

## Analytics Goal

`/analytics` should answer:

1. How are we doing now?
2. What changed?
3. What content drove the change?
4. Which accounts or platforms drove the change?
5. What should we do next?

Analytics can be deeper than the dashboard, but it should still be organized around user decisions.

## Analytics Target Structure

Use one analytics shell with sticky global filters and six tabs:

1. Overview
2. Posts
3. Accounts
4. Audience
5. Links
6. Compare

### Global Filters

- Date range.
- Platform.
- Account or group.
- Content type.
- Campaign or tag.
- Maturity window when relevant.

### Overview Tab

Primary KPI row:

- Views
- Reach
- Engagements
- Engagement rate
- Saves
- Shares
- Replies
- Net followers

Secondary optional KPIs:

- Link clicks.
- Profile activity.
- Posts published.
- Content mix.

Primary chart:

- Trend line with metric selector.
- Prior-period overlay.
- Clear latest-stable-date messaging when data is delayed.
- Neutral comparison series with oxblood only on the selected/highlighted series.

Narrative:

- A "What changed" card with 1-3 likely drivers.
- Avoid pretending correlation is causation.

Comparison:

- Compact account/platform/content-type comparison.
- Best and worst mature posts strip.

### Posts Tab

This should become the main content performance surface.

Columns:

- Preview.
- Publish date.
- Account.
- Platform.
- Content type.
- Campaign or tag.
- Views.
- Reach.
- Engagements.
- Engagement rate.
- Saves.
- Shares.
- Replies or comments.
- Follower impact.
- Link clicks.

Rules:

- Use TanStack Table via Juno `DataTable`.
- Use a maturity rule before labeling bottom performers.
- Allow sort, filter, and row-level drilldown.
- Default to table-first because this is an operational library, not a decorative gallery.
- Row detail should open in a sheet for preview, metrics, actions, and publish history.

### Accounts Tab

Columns:

- Account.
- Platform.
- Followers.
- Net follower change.
- Posts published.
- Views.
- Reach.
- Engagements.
- Engagement rate.
- Saves.
- Shares.
- Replies.
- Link clicks.
- Top post.

### Audience Tab

Use only when platform data is available and meaningful.

Show:

- Demographics if API thresholds are met.
- Active time windows.
- Audience overlap where useful.

Show "Unavailable" states clearly instead of zeros.

### Links Tab

Columns:

- Link title or slug.
- Destination.
- Campaign or tag.
- Page views.
- Clicks.
- CTR.
- Posts using link.
- Top post.
- Last active.

### Compare Tab

Comparison modes:

- Period vs period.
- Platform vs platform.
- Account vs account.
- Content type vs content type.
- Campaign vs campaign.

## Analytics Page Shape From Research

The recommended premium layout is:

1. Sticky global filters: account/group, platform, date range, content type, campaign/tag, and compare.
2. Narrative summary with the three most important changes.
3. Primary trend chart.
4. Supporting comparisons by account, content type, platform, or campaign.
5. Ranked content table.
6. Audience, inbox, and link drilldowns where the data exists.

Analytics should feel layered: overview first, then tabs and sheets for deeper investigation.

## Analytics Demotions

Move out of default overview:

- Impressions as hero metric; use Views instead.
- Story taps/exits/retention except in detail views.
- Quote/repost ratio as standalone top-level metric.
- Watch-time leaders from the main overview.
- Raw evidence walls.
- Formula taxonomies and internal metric naming.
- Audience micro-breakdowns unless useful and available.

## Data State Rules

- Distinguish zero from unavailable.
- Show latest stable date when platform data is delayed.
- Show platform limitation copy where APIs do not expose a metric.
- If Instagram metric definitions change across the selected range, show a comparison warning.

## Visual Rules

- Use shadcn/Nova card anatomy: header, description, action slot, content, optional footer.
- Use zinc surfaces, 1px borders, subtle inner panels, and oxblood only for selected/action states.
- Prefer readable charts and tables over decorative dashboards.
- Use Lucide icons only where they improve scan speed.
- Use Blocks.so-inspired stat layout patterns for KPI cards.
- Use EvilCharts-inspired routine chart patterns only through Juno chart wrappers.
- Do not reintroduce old `operator-*`, `dv2-*`, `j33-*`, terminal labels, or Raycast-style chrome.
- Use a small number of widget shapes repeatedly. If a new dashboard card cannot be described as a KPI, evidence card, action card, feed/list card, chart card, or insight panel, reconsider whether it belongs.

## Implementation Slices

### Slice 1: Dashboard Content IA

- Replace current top-level dashboard composition with daily KPI strip, Action Needed, What Changed, Top Content, Publishing Runway, and Inbox Queue.
- Preserve existing hooks where possible.
- Move low-value diagnostics below the fold or out of the dashboard.
- Use existing Nova primitives.

Status: In progress. The default All dashboard now prioritizes daily KPIs, attention work, trend/context, top posts, publishing runway, and inbox queue using existing hooks. The first widget-anatomy pass gives KPI cards stronger Nova-style hierarchy, trend rails, footer metadata, clearer action bands, and top-content rows with views plus engagement totals. Remaining follow-up: verify live data, refine copy, and decide which demoted diagnostics should move to analytics or dedicated drilldowns.

### Slice 2: Content Performance Restoration

- Restore a useful content-performance surface in the product.
- Either rebuild `/content` as a first-class route or make Dashboard Top Content link to a full Posts analytics table.
- Include preview, date, account, platform, views, engagement rate, saves, replies, and link clicks.

Status: Partially complete. `/content` is restored as a first-class internal route for posted-content operations and remains linked from Dashboard/Analytics. Remaining follow-up: add richer table controls and row detail sheets where the operational content page still needs deeper inspection.

### Slice 3: Analytics Overview Rebuild

- Add sticky analytics filter bar.
- Add Overview tab KPIs and main trend chart.
- Add What Changed narrative card.
- Add best/worst mature post strip.

Status: Implemented. `/analytics` now has URL-backed tabs for Overview, Posts, Accounts, Audience, Links, and Compare. Overview leads with Views, People reached, Engagements, Engagement rate, Saves, Shares, Replies, and Net followers; adds a What Changed card; and shows best posts plus mature posts to review.

### Slice 4: Analytics Posts + Accounts Tabs

- Build Posts table with maturity guardrail.
- Build Accounts table with performance comparison.
- Keep row actions and existing analytics hooks stable.

Status: Implemented for the first table pass. Posts now renders a native Analytics `DataTable` using existing published-post hooks, maturity-guarded review labels, row navigation to post detail, and a secondary `/content` link. Accounts owns the account rollup table with user-facing columns instead of default Overview placement. Remaining follow-up: campaign/tag/content-type columns when source data is ready.

### Slice 5: Analytics Audience, Links, Compare

- Add conditional audience view.
- Add smart links analytics.
- Add comparison mode.

Status: Implemented for the first pass. Links renders the existing Smart Links analytics widget when data is available. Audience now shows follower movement, non-follower reach availability, and scoped-account demographics when Meta returns real buckets. Compare now shows prior-period metric comparisons, platform split, and account movers from existing fleet aggregates. Remaining follow-ups: audience overlap/cohorts, richer campaign/tag filters, and peer/year/cohort compare modes once source data exists.

### Slice 6: Remove Or Relocate Diagnostics

- Move deep diagnostics to dedicated detail views, reliability, account health, or drilldowns.
- Remove abandoned dashboard widgets.
- Tighten audit rules once old active surfaces are gone.

Status: In progress. The dashboard language pass removed or demoted visible internal labels such as Evidence, Ops health, Fleet capacity, AI evals, classifier-backed reads, and Hook-class lift from active dashboard copy. Those surfaces now use operator-facing labels such as Account issues, Posting coverage, AI readiness, Content patterns, Conversation leaders, Performance leaders, and What to review. Remaining follow-up: decide permanent homes for deeper diagnostics in Reliability, Accounts, Analytics detail, or removal.

## Acceptance Criteria

- Dashboard can be understood in under 30 seconds by a non-technical social operator.
- Dashboard shows content performance and action items before diagnostics.
- Analytics has a clear Overview, Posts, Accounts, Audience, Links, and Compare structure.
- No primary card uses internal-only language.
- Unavailable data never looks like a real zero.
- The app keeps the Nova/shadcn visual target while showing more useful product information.
