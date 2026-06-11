# Juno33 Internal App IA

Last updated: 2026-06-06

This document audits route exposure for the authenticated Juno33 app. It is an
information architecture plan only: backend APIs, hooks, services, auth,
billing, publishing, analytics, telemetry, route behavior, and workflow actions
must remain unchanged.

## Route Inventory

| Route | Current exposure before cleanup | Recommended exposure | Reason |
| --- | --- | --- | --- |
| `/dashboard` | Desktop primary, mobile tab, command palette | Primary nav | Fleet overview and daily command center. |
| `/content` | Desktop secondary, mobile More, command palette | Primary nav | Answers what was posted and how it performed; core operator review surface. |
| `/calendar` | Desktop primary, mobile tab, command palette | Primary nav | Scheduling and queue operations are daily work. |
| `/composer` | Desktop primary, centered mobile action, command palette | Primary nav / primary action | Creation and publishing entry point. |
| `/inbox` | Desktop primary, mobile More, command palette | Primary nav | Engagement, replies, and suggestions are operational work. |
| `/analytics` | Desktop primary, mobile tab, command palette | Primary nav | Performance diagnosis and evidence rows. |
| `/accounts` | Desktop primary with attention badge, mobile tab, command palette | Primary nav | Account health, tokens, groups, and scope management. |
| `/links` | Desktop secondary, mobile More, command palette | Secondary / Growth | Important growth utility, but not a universal daily surface. |
| `/ideas` | Desktop secondary, mobile More, command palette | Secondary / Publishing | Input and ideation work supports Composer but should not crowd primary nav. |
| `/autopilot/:section?/:runId?` | Desktop secondary via `/autopilot`, mobile More, command palette | Secondary / Publishing automation | Operational automation surface; keep discoverable, not primary. |
| `/listening` | Desktop secondary, mobile More, command palette | Secondary / Growth | Monitoring and trend workflows are specialist operations. |
| `/reports` | Desktop secondary, mobile More, command palette | Secondary / Client reporting | Client/export workflow, not the main analytics surface. |
| `/attribution` | Desktop secondary, mobile More, command palette | Secondary under Analytics / Growth | Conversion evidence complements Analytics but should not be a peer primary page. |
| `/content-library` | Protected route, redirect targets, not sidebar primary | Nested under Content as Media assets | Asset/media utility; keep routable for redirects and deep links. |
| `/approval-queue` | Direct links from dashboard/calendar task flows | Direct-link / workflow only | Contextual review queue; route must stay for task links. |
| `/handoff/:postId` | Direct per-post route | Direct-link / workflow only | Phone/manual publish handoff is stateful and post-specific. |
| `/setup/publishing` | Direct links from notification readiness cards | Settings/onboarding direct link | Device and publishing readiness setup, not a standing product page. |
| `/reliability` | Desktop secondary, dashboard health links | Admin/settings or direct-link only | Diagnostic center for support/admin health checks; keep deep links from health tiles. |
| `/settings` and `/settings/:tab` | Desktop footer, mobile More, command palette | Account/settings | Owns profile, notifications, workspace, developer, advanced, and admin settings. |
| `/billing` | Desktop secondary, mobile Business, command palette | Account/settings | Plan and payment management should not compete with product work surfaces. |
| `/welcome` | Authenticated session route | Onboarding/direct-link only | First-run and reconnect flow; not an app destination. |
| `/share/:token` | Public direct link | Direct-link only | Token-gated public report, intentionally outside authenticated app nav. |
| `/privacy`, `/terms`, `/gdpr-deletion` | Public legal routes | Public footer/legal only | Compliance pages; not internal app nav. |
| `/login`, `/signup` | Public auth routes | Auth only | Entry routes outside internal app IA. |
| `/auth/callback`, `/auth/reset-password`, `/auth/threads/callback`, `/auth/instagram/callback`, `/auth/facebook/callback` | Callback routes | Auth/direct-link only | Protocol callbacks; never nav items. |
| `/invite/:code` | Public/session invite route | Direct-link only | Email/workspace invite flow. |
| `/` | Marketing landing | Public marketing | Outside internal app IA. |
| `/ask` | Redirect to `/dashboard` | Legacy redirect | Keep for old links. |
| `/checkout` | Redirect to `/billing` | Billing redirect | Keep for checkout links. |
| `/posts` | Redirect to `/calendar` | Legacy redirect | Keep for old scheduler links. |
| `/threads-inbox` | Redirect to `/inbox` | Legacy redirect | Keep for old inbox links. |
| `/media-library` | Redirect to `/content-library` | Legacy media redirect | Keep while Content Library remains nested asset route. |
| `/content-pillars` | Redirect to `/content-library` | Legacy content redirect | Keep until a future Content subroute exists. |
| `/groups`, `/account-groups` | Redirect to `/accounts` | Legacy account redirect | Keep for old group links. |
| `/auto-poster` | Redirect to `/autopilot/queue` | Legacy automation redirect | Keep for old automation links. |

## Proposed Hierarchy

### Primary Nav

- Dashboard
- Content
- Calendar
- Composer
- Inbox
- Analytics
- Accounts

### Secondary / More

- Ideas
- Autopilot
- Links
- Listening
- Reports
- Attribution

### Account / Settings / Admin

- Settings
- Billing & plans
- Publishing setup, from notifications/readiness setup contexts
- Reliability, from dashboard health/admin contexts
- Settings advanced tabs: API keys, webhooks, beta labs, UX health, audit log,
  data and privacy, danger zone

### Direct-Link / Onboarding Only

- Welcome
- Handoff
- Approval Queue
- Shared reports
- Legal pages
- Auth and OAuth callbacks
- Invite acceptance
- Legacy redirects

## Implementation Notes

- Desktop sidebar now promotes Content to primary and removes Billing and
  Reliability from product nav.
- Mobile More now starts with primary work surfaces and places Billing under
  Account & settings.
- Command palette now treats primary routes as primary commands, exposes Media
  assets as a nested Content utility, and categorizes Billing with Settings.
- No route definitions, route redirects, API calls, page internals, hooks,
  services, or workflow actions were changed.
