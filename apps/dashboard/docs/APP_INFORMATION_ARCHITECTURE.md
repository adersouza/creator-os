# App Information Architecture

Last updated: 2026-06-14

This tracker is the source of truth for what users should see in the internal app shell. Route files can stay available for direct links and support workflows, but broad navigation and command-palette exposure should match this document.

## Primary Product Nav

These are everyday surfaces for social operators and should stay in desktop primary nav, mobile primary tabs or mobile More, and the command palette.

| Route | Status | Why users see it |
| --- | --- | --- |
| `/dashboard` | primary | Daily outcomes, attention work, top content, publishing runway, and inbox work. |
| `/content` | primary | Operational “what was posted and how did it do?” view. |
| `/calendar` | primary | Scheduling workspace for planned, published, failed, and editable posts. |
| `/composer` | primary | Create, adapt, preview, schedule, and publish posts. |
| `/inbox` | primary | Reply, assign, triage, and convert conversations into ideas. |
| `/analytics` | primary | Deeper investigation across posts, accounts, audience, links, and comparisons. |
| `/accounts` | primary | Connection state, readiness, account issues, groups, and platform identity. |

## Secondary More Menu

These are useful but lower-frequency internal product surfaces. They belong in desktop “More,” mobile More, and command palette.

| Route | Status | Why users see it |
| --- | --- | --- |
| `/links` | secondary | Smart links, conversion paths, and link performance. |
| `/ideas` | secondary | Capture, organize, and hand off content ideas. |
| `/autopilot/*` | secondary | Automation controls and publishing status. Visible label is “Automation.” |
| `/listening` | secondary | Mentions, competitor surprises, trends, and idea handoff. |
| `/reports` | secondary | Scheduled reports, share links, and exports. |

## Account Menu

These are account/workspace administration surfaces. They belong in the account menu and Settings/Billing commands, not the main product nav.

| Route | Status | Why users see it |
| --- | --- | --- |
| `/settings` and `/settings/:tab` | account | Profile, workspace, security, integrations, API/webhooks, appearance, and data/privacy controls. Appearance exposes light/dark/system only; the product palette is locked to Nova/zinc + Juno oxblood. Labs, audit log, danger zone, and UX health remain direct-link/contextual panes, not normal Settings tab-list items. |
| `/billing` | account | Plan, usage, checkout, and billing portal. |

## Contextual Or Direct-Link Only

These routes stay routable because product flows and support links depend on them. Do not show them broadly in sidebar, mobile More, or command palette unless a route-specific workflow links to them.

| Route | Status | Why it stays available |
| --- | --- | --- |
| `/reliability` | contextual | Support/admin reliability checks for publishing, tokens, and Meta/API health. |
| `/setup/publishing` | contextual | First-run or recovery publishing setup flow. |
| `/approval-queue` | contextual | Approval/revision execution surface for specific workflows. |
| `/handoff/:postId` | contextual | Post-publish handoff from scheduling/publishing workflows. |
| `/content-library` | contextual | Media and reusable assets, linked from Content/Composer when needed. |
| `/attribution` | contextual | Conversion/attribution details should surface under Analytics or Links, not as a standalone sidebar destination. |

## Public, Auth, And Legal

These are outside the authenticated product shell. They should not appear in internal app navigation.

| Route | Status | Why it exists |
| --- | --- | --- |
| `/` | public | Marketing/landing entry point. |
| `/login` | public | Authentication. |
| `/signup` | public | Account creation. |
| `/welcome` | public | First-run entry. |
| `/reset-password` | public | Password reset. |
| `/invite/*` | public | Invite acceptance. |
| `/auth/*` | public | Auth/OAuth callback handling. |
| `/legal/*` | public | Legal and policy pages. |
| `/shared-report/*` | public | Shared report viewing. |

## Copy Rules

- Primary product surfaces should use user-facing language: views, reach, engagement, scheduled posts, failed posts, account issues, readiness, and replies.
- Backend/operator terms are allowed only in contextual/admin surfaces or advanced panels: queue health, cron, SLO, webhook replay, operator dispatcher, model, payload hash, and diagnostics.
- “Autopilot” is an internal feature name. Navigation and user-facing shell copy should say “Automation.”
