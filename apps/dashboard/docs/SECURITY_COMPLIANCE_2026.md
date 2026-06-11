# Juno33 security and compliance roadmap for 2026

**Bottom line up front.** Juno33's current posture — AES-256-GCM token encryption, RLS-backed workspaces, HMAC webhooks, 48 Upstash-rate-limited endpoints — is a credible starting point, but six gaps need to close in the next 90 days: a Meta data-deletion callback URL, envelope encryption with an external KEK, pgTAP cross-tenant RLS tests in CI, MFA enforcement for admin roles, a GDPR-grade deletion pipeline covering 27+ vendor surfaces, and a consent banner that honors Global Privacy Control. The 12-month arc layers SOC 2 Type II (Security + Availability + Confidentiality), EAA/WCAG 2.2 AA remediation before German BFSG *Abmahnung* exposure compounds, and enterprise SSO/SCIM via WorkOS. Total first-year cash envelope: **$40–80K** for SOC 2 alone; $15–30K more for accessibility audit and consent tooling. The single biggest existential risk is not encryption — it is the Meta Data Deletion Callback URL; Meta can revoke API access across all 300 connections for callback failures.

---

## Pillar 1 — OAuth token security in 2026

**AES-256-GCM is sufficient; implementation discipline is the whole ballgame.** NIST SP 800-38D approves GCM as an AEAD mode, but a single IV reuse with the same key catastrophically compromises both confidentiality and the GHASH authentication subkey. Meta's Developer Data Use Policy §6.7 treats access tokens as equivalent to app secrets and the Data Protection Assessment (annual, mandatory) expects a token vault with admin-only access, MFA on human access paths, documented 24/7 revocation procedures, and ISO 27001 / SOC 2 Type 2 / GDPR Art. 32-equivalent backing controls.

### Implementation pattern (P0)

Use a 96-bit CSPRNG-generated nonce per encryption, a full 128-bit authentication tag, fail-closed tag verification, and bind associated data (AAD = `tenant_id || account_id || token_type`) so an attacker swapping ciphertext between rows triggers tag failure. Store `[ciphertext | iv | tag | key_version | aad_version]` as a single `bytea` blob. **Never index encrypted columns** and explicitly `log_statement=none` + PGAudit off on any table holding secret writes — Supabase's Vault README flags this as a common plaintext-in-pg_log leak path.

Move to **envelope encryption** with per-row (or per-tenant) Data Encryption Keys wrapped by a Key Encryption Key held in an external KMS. This is the AWS/GCP/Azure internal pattern and reduces KMS API spend ~10,000× versus directly encrypting payloads. Rotate DEKs on each token refresh write (or every 90 days minimum); rotate the KEK annually; never destroy old KEK versions — mark them *deactivated* per NIST SP 800-57 §8 key states so legacy wrapped DEKs remain decryptable during re-wrap.

### Token rotation for 60-day Meta LLATs (P0)

Meta long-lived tokens can be refreshed only when ≥24 hours old AND not yet expired. Run a **6-hour cron scanning for `expires_at − now() ≤ 14 days`**, refresh, and stagger with `hash(account_id) % window_minutes` so 300 accounts don't hit Meta in one minute. Exponential backoff starts at 30s with full jitter, caps at 1 hour, stops at 6 attempts. Classify failures into three buckets with different handling: transient (5xx/429/timeout → retry), token-invalid-user-exists (code 190 subcodes 460/463/467 → flag "re-auth required," email one-click reconnect, keep ciphertext 7 days then purge), permission-revoked (subcode 458 or `/me/permissions` shows *declined* → immediate ciphertext deletion and UI banner).

**Subscribe to Meta's deauthorize callback** in the App Dashboard — Meta POSTs a signed_request whenever a user removes the app. Parse, verify HMAC against `app_secret`, null the ciphertext row immediately. This is the fastest compromise signal you have.

### Incident response playbook (P0)

Detection signals worth instrumenting: 3σ spikes above baseline posts/day per account, ASN anomalies on refresh call source IPs, new scopes appearing in `/me/permissions` responses that Juno33 didn't request, posts on customer accounts not originating from the Juno33 UI, clusters of deauthorize webhooks within an hour (systemic compromise), KMS CloudTrail `Decrypt` calls outside the deploy region or business hours.

Containment order: (1) rotate the KEK in KMS and cut old-version IAM — this is the *immediate* global kill switch; (2) bulk `DELETE /{user-id}/permissions` against affected accounts via Graph API; (3) invalidate Juno33 session cookies and rotate JWT signing keys; (4) rotate DB credentials and Supabase service role JWT; (5) re-encrypt remaining tokens under the new KEK; (6) force customer re-auth.

**GDPR 72-hour clock** starts at "awareness," not when forensics finish. If ciphertext was AES-256-GCM encrypted AND the KEK was not compromised, EDPB Guidelines 9/2022 and Art. 34(3)(a) let you argue the data is "unintelligible" — reducing data-subject notification obligations, but Art. 33(5) documentation duty remains. Enforcement is unforgiving: Ireland's DPC fined Meta €251M in Dec 2024 for a token-theft breach, with €8M specifically for improper notification. Meta's own Global DPA requires 48-hour processor notification for Platform Data incidents — tighter than GDPR's 72 hours.

### Vendor recommendation at 300 tokens

| Option | Monthly cost at Juno33 scale | Verdict |
|---|---|---|
| AWS KMS (FIPS 140-2 L3) | ~$1–3 (1 CMK + envelope pattern keeps API calls in free tier) | **Recommended KEK.** |
| Google Cloud KMS | ~$1–3 equivalent | Only if GCP-native. |
| HashiCorp Vault | $13K–48K/year (HCP Dedicated, post-IBM acquisition) | Over-scaled; avoid. |
| Supabase Vault (pgsodium) | Bundled | Use for the Meta *app secret* singleton, not 300 user tokens. pgsodium is pending deprecation. |

**The hybrid recommendation**: AWS KMS as KEK + application-layer AES-256-GCM with per-row DEKs in Postgres. Under $5/month all-in, scales linearly to 30,000 tokens before pricing matters, gives CloudTrail decrypt forensics, satisfies Meta DPA and Art. 32, and dodges Vault's uncertain roadmap. Revisit dedicated CloudHSM or per-tenant KEKs (AWS XKS) only at ~10,000 tokens or when an enterprise contract mandates BYOK.

**Pillar 1 priorities.** *P0:* envelope encryption with AWS KMS KEK, 14-day refresh window with stagger, deauthorize callback handler, incident runbook with pre-drafted supervisory-authority notification, AAD binding on GCM. *P1:* quarterly KEK rotation review, Meta DPA annual submission, forensic log preservation (90 days), per-account anomaly detection. *P2:* SOC 2 Type II evidence for Meta DPA audit, BYOK tier for enterprise, sender-constrained tokens (DPoP) if Meta adds support.

---

## Pillar 2 — European Accessibility Act + WCAG 2.2 AA

The EAA (Directive 2019/882) has been enforceable since **June 28, 2025**. Juno33's self-service sign-up accessible to EU consumers brings the product in scope even if mostly sold B2B. EN 301 549 currently references WCAG 2.1 AA, but the W3C recommends targeting **WCAG 2.2 AA** because EN 301 549 will update, and 2.2 is a strict superset (only SC 4.1.1 was removed).

### The six new WCAG 2.2 A/AA criteria that matter for dashboards

**2.4.11 Focus Not Obscured (AA)** — keyboard focus must not be fully hidden by author content. Juno33 risk zones: sticky topbars, cookie banners, Intercom bubble, sticky "Publish" bars in composer. Fix with CSS `scroll-padding` on scroll containers so Tab pushes focused rows out from under sticky headers.

**2.5.7 Dragging Movements (AA)** — drag operations need a single-pointer alternative. Applies to content-calendar drag reschedule, Kanban approval pipelines, image cropper. Add "Move to…" menus, arrow-key reordering, or explicit date/time pickers.

**2.5.8 Target Size 24×24 CSS px (AA)** — dense table row actions (16×16 edit/delete icons), toast close buttons, pagination ellipses all commonly fail. Enforce 24×24 minimum hit areas; 44×44 on touch surfaces.

**3.2.6 Consistent Help (A)**, **3.3.7 Redundant Entry (A)** — lock Intercom/Help link placement across app areas; auto-populate onboarding/invite/connection wizards from prior steps.

**3.3.8 Accessible Authentication (AA)** — **no cognitive function tests**. Allow password-manager paste, support WebAuthn/passkeys, swap image CAPTCHA for Cloudflare Turnstile or hCaptcha's accessibility cookie flow. This aligns with Pillar 6's MFA recommendations.

### CI testing stack (P0)

Layer four tools because **automated tooling catches only ~30–40% of real WCAG issues** (Deque cites axe-core at ~57% of axe's own rules; WebAIM independent studies put real-world coverage lower):

- **Storybook addon-a11y** + @storybook/test-runner with `axe-playwright` gates PRs at component isolation with `parameters.a11y.test = 'error'`.
- **Playwright + @axe-core/playwright** against rendered routes, configured with `runOnly: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa','best-practice','EN-301-549']`. Add explicit `page.keyboard.press('Tab')` loops to catch focus traps axe cannot see.
- **eslint-plugin-jsx-a11y** in pre-commit for authoring-time failures.
- **pa11y-ci** for marketing/auth-page smoke audits; Lighthouse CI for per-deploy accessibility budgets.

Automated tools cannot evaluate meaningful alt text, heading hierarchy semantics, 2.4.11 in complex stacking, Consistent Help, Redundant Entry, or live-region timing. Budget quarterly internal manual audits plus a third-party audit (Deque, TPGi, Level Access) before major launches.

### Common violations and fixes

Audit the design-token palette against 4.5:1 (text) and 3:1 (UI components, state indicators). Gray-on-white secondary text at #999/#fff is 2.8:1 — a default failure. Placeholder-as-label fails 1.3.1/3.3.2/4.1.2. Every clickable div must become a `<button>`. Use **Radix UI Dialog or React Aria** for modals — never hand-roll focus traps; use the `inert` attribute on background, never `aria-hidden` on the modal itself. Follow Scott O'Hara's first rule of ARIA: don't use ARIA when native HTML works.

### Screen reader testing for complex widgets

**Charts**: SVG is opaque by default. Highcharts 8+ bundles the Accessibility module (SR region, keyboard series/point navigation, HTML data-table fallback). Recharts has no first-class a11y module — wrap with a visually-hidden `<table>` containing the data, `aria-label` summarizing the takeaway, `role="img"` on the container, and a visible toggle to reveal the table. Known Highcharts gotcha: intermittent `aria-hidden="true"` on chart title during initial React render — verify with NVDA.

**Tables**: native `<table>`/`<th scope="col">`. Sortable columns use `aria-sort="ascending|descending|none"` on the active `<th>` (one column at a time). Sort triggers are `<button>` inside `<th>`, never clickable `<th>`. Filters announce counts in a polite live region ("42 posts matching").

**Date pickers**: do not build. Use **react-aria** `useDatePicker`/`useCalendar` from Adobe — correct WAI-ARIA grid pattern, arrow-key navigation, `aria-label` per cell. Avoid flatpickr for new work.

Test matrix: NVDA+Firefox and NVDA+Chrome (41% of SR users per WebAIM 2024), JAWS+Chrome (35%, common in EU enterprise procurement), VoiceOver+Safari on macOS/iOS, TalkBack+Chrome on Android. Budget 2 hours per flow per pairing.

### Enforcement landscape — Germany and France are the hot zones

**Germany (BFSG)**: fines up to €100K per violation; €10K for inaccurate accessibility statements. The bigger risk is the *Abmahnung* regime — competitors can sue non-compliant peers civilly under UWG and stack legal fees on top of regulatory exposure. Law firms are actively marketing BFSG Abmahnung services.

**France**: multi-agency (ARCOM, DGCCRF, ARCEP, AMF/ACPR). Fines up to €250K for repeated violations; €25K/year for a missing accessibility statement. July 2025 saw disability groups formally notify Carrefour, Auchan, Leclerc, Cora within days of enforcement; emergency injunctions followed by November 2025 — advocacy-driven litigation is the live risk vector.

**Ireland** uniquely includes **criminal sanctions** up to imprisonment. **Spain** has the highest ceiling (€1M for very-serious). **Netherlands** ACM: €900K or 10% of revenue with proactive enforcement. **Italy**: 5% of annual turnover for serious/persistent violations.

**Microenterprise exemption** (Art. 4(5), Recital 70): <10 employees AND ≤€2M turnover *or* balance sheet — both conditions required, applies only to *services* not products, and attaches immediately when either threshold crosses. Plan as if exempt status is temporary.

**Pillar 2 priorities.** *P0:* contrast-token audit, focus management in all modals/drawers, 2.5.8 target-size fixes, drag alternatives for calendar/Kanban, passkey/paste-allowed authentication, Storybook+Playwright+axe in CI with EN-301-549 ruleset, chart data-table fallback, accessibility statements in DE/FR/IT/ES/NL. *P1:* Consistent Help, Redundant Entry, aria-live for async actions, calendar migration to react-aria, quarterly manual NVDA/JAWS/VoiceOver cycles. *P2:* third-party audit, VPAT/ACR for enterprise procurement, WCAG 2.2 AAA stretch (2.4.12, 2.4.13).

---

## Pillar 3 — GDPR and CCPA in 2026

### The 27-surface deletion map

A "delete my account" request touches far more than production Postgres. Map each location to an owner and SLA:

**Primary**: users, workspaces, social_accounts tokens, scheduled_posts, AI content cache, sentiment/analytics tables, RLS audit tables, Supabase Storage objects, `auth.users` identities/refresh tokens, logical replica drift.
**Backups**: Supabase daily backups (Pro 7d / Team 14d / Enterprise 30d), PITR WAL archive, self-run pg_dump exports in S3/Drive.
**Observability**: Vercel build+runtime logs, Sentry events (IP, user.id, breadcrumbs), Vercel Analytics events, Speed Insights, PostHog events/persons/replays, CDN/edge caches.
**Billing**: Stripe customers/invoices/payment_intents — retained for ~7 years US (IRS), 10 years EU member states; Art. 17(3)(b) legal obligation applies, redact the customer object, keep the ledger.
**Comms**: Resend/SendGrid logs (30–90d), Intercom conversations + AI-Fin training corpus, Slack/internal CS notes.
**AI vendors**: OpenAI API logs (30d default; ZDR by contract, incompatible with Responses background/Assistants/Files/vector stores). The July 2025 US magistrate preservation order that forced OpenAI to indefinitely hold output logs **was lifted September 26, 2025**. Anthropic: 30d default; ZDR enterprise-only. pgvector embeddings are stateful and not covered by ZDR.
**Queues**: Upstash Redis/QStash message bodies, Meta webhook receipt logs.

The single highest-leverage item is the **Meta Data Deletion Callback URL** — HTTPS endpoint that receives signed `signed_request` POSTs when a user disconnects, returns a `confirmation_code` + status URL. **Meta can revoke API access across all 300+ connections for callback failures.** This is Platform Terms §3(d)(i) and Developer Data Use Policy enforcement, not optional.

**Put-beyond-use for backups**: EDPB, ICO, and the Danish DPA accept that immutable backups cannot be surgically erased, provided production deletion is logged, retention is documented, and any PITR restore automatically re-runs the privacy queue for affected subjects. Document this reasoning in the RoPA.

### Retention for social media analytics

Art. 5(1)(e) storage limitation requires each category have a documented envelope. Defensible defaults: operational engagement metrics 13 months raw, aggregate to monthly beyond (Meta Graph Insights itself only returns ~2 years); comments/DMs/sentiment 90 days at content level, aggregate sentiment beyond; AI prompts/drafts 30–90 days; security/audit logs with IPs 6–12 months (ICO) with tension against SOC 2 CC7 auditor preference for 12+ months; billing 7 years US / 10 years EU; employment tax 4–10 years. Publish the schedule in the privacy notice.

### EU→US transfers in 2026 — DPF is operational but unsettled

**EU-US Data Privacy Framework remains valid.** The General Court dismissed Philippe Latombe's annulment (Case T-553/23) on September 3, 2025; Latombe appealed to the CJEU in October 2025 and that appeal is pending. EDPB FAQ v2.0 (January 15, 2026) confirms DPF transfers to self-certified US orgs need no additional safeguards. NOYB has signalled a "Schrems III" challenge but has not filed. **The framework rests on Executive Order 14086**, which a future US administration can revoke — plan for DPF withdrawal as an incident scenario.

SCCs (Commission Decision 2021/914) remain the fallback. TIAs are still expected because (a) not all subprocessors are DPF-certified and (b) EDPB Recommendations 01/2020 were never withdrawn. The 2025 *Bindl v. Commission* General Court ruling found the Commission itself liable for a non-compliant EU→US transfer — DPA expectations for private controllers have hardened.

**Juno33 vendor posture**: Vercel (DPF-certified; use fra1/dub1 for EU), Supabase (Singapore entity, not DPF — SCCs + Frankfurt eu-central-1), Stripe (DPF-certified via Stripe Inc.; EU importer Stripe Payments Europe Ltd), OpenAI (DPF-certified; OpenAI Ireland for EU; EU data residency on Responses/Chat Completions), Anthropic (DPF-certified; EU residency on Claude Enterprise), PostHog (use Cloud EU Frankfurt), Sentry (DPF-certified; sentry.io/eu), Intercom (DPF + EU residency), Resend/SendGrid (SendGrid DPF via Twilio), Upstash (EU regions + SCCs in DPA).

### Privacy by design for AI

**EU AI Act timeline**: in force August 1, 2024; prohibited practices + AI literacy from Feb 2, 2025; GPAI obligations from Aug 2, 2025; most high-risk + Article 50 transparency from **Aug 2, 2026**; embedded high-risk from Aug 2, 2027. The Feb 2026 Commission guidance on Art. 6 classification is delayed. Juno33's features (content gen + sentiment) are limited-risk under the Act but Art. 50 transparency still applies from August.

**Content generation**: strip PII from prompts via deterministic redaction before the model call; use placeholders the app re-inserts client-side. Obtain ZDR on both OpenAI and Anthropic enterprise accounts (contractual, not self-serve; incompatible with Responses background mode, Assistants, Files, vector stores, Hosted Containers). Disclaim training in the MSA even though API terms already do by default.

**Sentiment analysis under Article 22**: triggers the prohibition only if (a) *solely* automated and (b) produces legal or similarly significant effects. Sorting comments for a human brand manager to review **does not** meet the threshold. Auto-hiding, blocking, or reporting users based purely on sentiment score **does** — keep a human-in-the-loop before any automated action. Run a DPIA for the sentiment feature (Art. 35 triggers for large-scale profiling with innovative technology).

### Cookie consent and GPC

The European Commission **withdrew the ePrivacy Regulation in February 2025**. The ePrivacy Directive (2002/58/EC) remains controlling — Art. 5(3) requires prior, specific, informed consent for any non-strictly-necessary device storage/access. Reject must be as easy as Accept; legitimate interest is not available for non-essential cookies.

**PostHog**: configuration-dependent. For logged-in product analytics, consent at signup + Cloud EU residency + IP capture disabled for EU + `opt_out_capturing_by_default=true` until consent captured server-side. For marketing, `cookieless_mode: 'on_reject'` and daily-rotating server-side hash. **Session replay is materially more invasive** — separate consent toggle, `maskAllInputs: true`, block-selectors for PII, 30-day retention max. Italian Garante and CNIL have fined session-replay tools capturing form fields without consent.

**Vercel Analytics**: marketed as cookieless (24-hour rotating request hash), but Vercel does not expose CNIL-aligned consent-mode configuration and starts tracking immediately on page load. Treat as consent-required in the EU until Vercel publishes an exemption note; conditional-render after consent for EU visitors.

**CCPA/CPRA revised regulations took effect January 1, 2026** (approved Sept 23, 2025). Key additions: mandatory "Opt-Out Request Honored" confirmation toggle, banner-dismissal-as-consent banned, strict Accept/Reject symmetry, mandatory GPC signal processing. AB 566 (Oct 2025) requires major browsers to ship built-in GPC by Jan 1, 2027. 2025 enforcement: Healthline $1.55M (largest CCPA settlement), Tractor Supply $1.35M (largest CPPA), Honda $632.5K, Todd Snyder $345K. Colorado, Connecticut, and new states effective Jan 1, 2026 also require honoring GPC.

**Pillar 3 priorities.** *P0:* Meta Data Deletion Callback URL with monitoring, 27-vendor erasure pipeline with deletion-log table, RoPA with put-beyond-use documentation, counter-signed DPAs + single Juno33 TIA, consent banner with symmetric buttons + GPC detection + "Opt-Out Request Honored" confirmation + session-replay gated separately, OpenAI+Anthropic ZDR contractually enabled, prompt PII redaction, sentiment DPIA with human-in-loop. *P1:* EU residency defaults across every vendor, PII scrubbing in Sentry/Vercel logs with ≤30d retention, Art. 50 AI-transparency disclosures, Stripe redaction-on-deletion. *P2:* AI-generated-content watermarking per the Mar 3, 2026 Code of Practice draft, privacy metrics dashboard, DPF-withdrawal contingency testing.

---

## Pillar 4 — SOC 2 Type II for a Supabase + Vercel + Upstash + Stripe stack

**Every core vendor already holds current SOC 2 Type 2** (Supabase, Vercel, Upstash, Stripe, Sentry, PostHog). Juno33 inherits a meaningful share of controls; the remaining work is organizational — policies, identity, SDLC, vendor management, logging, and 6-month evidence collection.

### Subprocessor gotchas

Three traps hide in vendor SOC 2 coverage:

- **Upstash's SOC 2 coverage is add-on-gated.** Only the **Prod Pack** (+$200/month/db) or Enterprise plans are in scope. Pay-as-you-go and standard Fixed plans are *not* SOC 2–covered. Upgrade critical production databases or document the compensating control.
- **Vercel's SOC 2 scope explicitly excludes Processing Integrity and Privacy.** If Juno33 ever scopes those TSCs, it cannot fully rely on Vercel's report.
- **Supabase is not ISO 27001 certified** (per GitHub discussions); Enterprise support fills gaps case-by-case, but don't assume ISO inheritance.

Other logging gaps: Vercel Runtime Logs retain only 3 days without a Log Drain; Vercel Audit Logs are Enterprise-only; Supabase Log Drains are Team+ paid. Serverless function logs are ephemeral — auditors will flag for CC7.2 (monitoring) and CC6.8 (logging).

### Trust Services Criteria — scope Security + Availability + Confidentiality

Security is the required baseline (CC1–CC9). Availability adds A1.1–A1.3 — relevant because Juno33 schedules publication; missed windows = customer harm. Confidentiality adds C1.1–C1.2 — strongly recommended since Juno33 holds third-party OAuth tokens and draft content. **Defer Processing Integrity** unless Juno33 markets publication accuracy as a differentiator. **Defer Privacy** — heavy GDPR overlap, duplicate auditor work; add when a specific enterprise prospect requires.

### Timeline and controls

**Pre-audit (months 0–3, P0)**: draft 15 core policies (Information Security, Acceptable Use, Access Control, Password/Auth with MFA, Incident Response, BCP/DR, Data Classification/Retention, Encryption, SDLC, Change Management, Vendor Risk, Backup/Recovery, Risk Assessment, Remote Work/BYOD, Privacy, Code of Conduct). Enforce MFA across Supabase, Vercel, Upstash, Stripe, GitHub, Google Workspace, Sentry, PostHog. Branch protection + required reviews + signed commits on `main`. Sentry PII scrubbing; PostHog session-replay masking. Background checks + security awareness training. MDM on all laptops (Kandji/Rippling/NinjaOne) with full-disk encryption verified. DPAs executed and SOC 2 reports collected from every subprocessor. Log Drains enabled from Vercel and Supabase to Better Stack or Axiom, forwarded to S3 with Object Lock.

**Observation window (months 3–9, P1)**: quarterly access reviews, monthly vulnerability scans with closure SLAs, penetration test in months 4–6 (Cobalt Core ~$8K, NetSPI/Bishop Fox ~$15–25K), one backup-restoration test, one BCP tabletop, continuous change-management evidence, incident log with monthly review showing the channel is monitored, vendor register with annual re-review, risk-assessment refresh, 100% security-training completion tracked.

**Post-audit maturity (months 12–24, P2)**: automated continuous control monitoring, annual Type II refresh on 12-month windows, ISO 27001:2022 expansion (40–60% incremental cost given 80%+ control overlap), HIPAA if healthcare customers enter pipeline, bug bounty on HackerOne/Intigriti, CSA STAR Level 1 for enterprise RFPs.

### Logging gap — Sentry + PostHog is not sufficient

Neither is append-only or tamper-evident, and neither captures the required audit events uniformly. Build an application-level **`audit_events` table** in Supabase with append-only triggers (revoke DELETE and UPDATE from all roles except a rotation process) capturing authentication, authorization decisions, admin actions, data access, configuration changes, security events. Centralize with **Better Stack or Axiom** (~$50–300/mo at Juno33 scale) and forward to S3 with Object Lock for 12+ month retention. SIEM is not required at this scale — structured JSON logging + alerting rules satisfies CC7.2; SIEM appropriate around 1,000+ customers or regulated verticals.

### Compliance platform selection

| Platform | Annual cost | Positioning |
|---|---|---|
| **Vanta** | $7.5–15K base; $15–25K multi-framework | Widest auditor network, 375+ integrations, Supabase itself runs on Vanta. **Recommended default.** |
| Drata | $7.5K Essential / $15K Foundational | Strong for engineering-led teams; OpenAPI for CI/CD; steeper learning curve. |
| Secureframe | $12–20K | White-glove onboarding; pricier for equivalent scope. |
| Sprinto | $7.5–9K base; $2K/extra framework | **Honest runner-up when budget-constrained.** |
| Thoropass | ~$30K total (platform + bundled audit) | Single-vendor platform+audit; less flexibility for custom controls. |
| Oneleet | $15–50K; bundles vCISO + pen test | "Done-for-you" for zero-compliance-headcount teams. |

### Cost and timeline

Realistic first-year cash envelope: platform $10–20K + auditor $15–30K (Security+Availability+Confidentiality on 6-month window; mid-tier firms $20–40K; Big 4 $60K+, avoid) + penetration test $8–20K + training $2–5K + MDM $3–8K + additional tooling $3–10K + Vercel SAML/Upstash Prod Pack/Supabase Team upgrades ~$14–20K = **$40–80K total**. Year-two maintenance drops to ~$25–40K. Internal time: 0.5 FTE across 6 months of intensive prep, 0.1 FTE ongoing.

**Type I at month 3** (end of remediation, start of observation) costs an additional $5–15K but can unblock a specific enterprise deal 4–6 months before Type II issues. Skip if no specific deal is at risk — straight to Type II is the more common 2025–2026 path.

**Pillar 4 priorities.** *P0:* MFA everywhere, 15 core policies adopted, Vanta (or Sprinto) onboarded, all DPAs + SOC 2 reports collected, Log Drains to Axiom/Better Stack + S3 Object Lock, append-only `audit_events` table, Upstash Prod Pack upgraded, branch protection + Snyk/GHAS, Sentry/PostHog PII scrubbing. *P1:* 6-month observation window starts (Security + Availability + Confidentiality), quarterly access reviews, monthly vuln scans, pen test month 4–6, backup restore test, BCP tabletop, published Trust Center + subprocessor list. *P2:* Type II audit issued with quarterly bridge letters, ISO 27001:2022, HIPAA if healthcare opens, Panther-class logging when customers cross ~1000.

---

## Pillar 5 — rate limiting, bot, and abuse prevention

### Is 48 rate-limited endpoints appropriate?

Coverage and tiering matter more than raw count. 48 is defensible if every category below is present with differentiated limits. OWASP API Security Top 10 (API4:2023 Unrestricted Resource Consumption) requires category-specific throttling, not a single global limit.

| Endpoint class | Realistic 2026 limits | Priority |
|---|---|---|
| Auth (login, signup, reset, MFA verify) | 5/min/IP, 20/hr; 5 failures → exponential backoff to 15 min cap (AWS Cognito pattern); signup 3/hr/IP; password-reset 3/hr/email | P0 |
| OAuth callback | 10/min/IP + `state` nonce in Redis (5 min TTL) | P0 |
| Webhook ingestion | Per-signature-identity rate limit, not IP alone; Stripe 100 rps burst, Meta 200 rps | P0 |
| Meta content publishing | Per-page token bucket matching BUC limits (200 calls/hr/user Graph; 100/day IG Content Publishing); queue per workspace | P0 |
| AI/caption endpoints | Token bucket = LLM budget control (Arcjet's explicit framing) | P0 |
| Email-triggering (invites, contact, notifications) | 3/hr/IP, 10/day/account, 50 invites/day/workspace — single largest liability for small SaaS (deliverability + SES cost) | P0 |
| Report generation / export | 5/hr/user, 20/hr/workspace; queue + admission control | P0 |
| Public API (Empire tier) | Per-API-key token bucket with tier quotas; X-RateLimit-* headers | P1 |
| Search / mutation | 30/min/user sliding window; 300/min/workspace | P1 |

Layer tiers: L1 (per-IP) always-on coarse; L2 (per-user-id from Supabase JWT) defeats residential-proxy rotation (OWASP Credential Stuffing flags this as standard attacker behavior in 2025–2026); L3 (per-workspace) blast-radius containment; L4 (per-API-key) only at Empire launch.

### Bot detection — the 2026 landscape

**Vercel BotID** went GA in 2025 — invisible client-side challenge + server-side `checkBotId()`. Basic is free on all plans; Deep Analysis (Kasada-powered) is Pro/Enterprise paid. Deterministic pass/fail. **Vercel Bot Protection Managed Ruleset** (separate) challenges non-browser traffic via WAF; free. **Vercel Protectd** is the always-on platform L3/L4/L7 DDoS mitigation with P50 2.5s / P99 3.5s time-to-mitigate (self-reported).

**Critical architecture constraint**: Vercel's docs state reverse-proxying via Cloudflare degrades BotID/Bot Protection signal fidelity. Pick one primary edge.

**Arcjet** is the platform-agnostic alternative — bot detection + rate limiting + email validation + Shield WAF + PII redaction in one SDK call with <1ms local / 20–30ms cloud latency. Series A $8.3M 2025, local AI model Oct 2025, Next.js-native. Especially compelling when launching AI features because its token-bucket maps onto LLM token budgets directly.

**CAPTCHA fallback**: Cloudflare Turnstile (free to 1M/mo, invisible, GDPR-friendly — but requires Cloudflare account), hCaptcha (privacy-focused, Pro paid, strongest against distributed credential stuffing), Friendly Captcha (EU-based, proof-of-work).

### Webhook hardening

Source IP allowlisting for Stripe/Meta via Vercel WAF custom rules. HMAC verification **before any processing** with `crypto.timingSafeEqual`, never `===`, using the **raw** request body. Stripe's `constructEvent` handles timestamp + constant-time compare automatically; default 5-min tolerance, shorten to 60s for high-value flows. Meta uses `X-Hub-Signature-256` with the App Secret — Meta does not sign a timestamp, so you must add your own replay protection via nonce dedup.

**Two-layer replay protection**: timestamp tolerance ≤5 min + event-id dedup in Redis via `SETNX` with TTL > tolerance window (10 min). Separately, every handler must be **idempotent** — persist `event.id` in a `webhook_events` table with unique index and process side effects in a transaction that conflicts on duplicate. Hookdeck and Stripe both emphasize: idempotency is the ultimate defense because providers operate at-least-once.

Respond 2xx within 3–5 seconds — queue events immediately, process async. Stripe retries with backoff; Meta retries for 24h. Rotate webhook secrets quarterly using Stripe's two-active-secrets "roll secret" grace window pattern.

### DDoS on Vercel — when to add Cloudflare

Built-in: Protectd always-on DDoS mitigation, Attack Challenge Mode (free all plans), WAF custom rules (Pro/Enterprise) with rate-limit actions, Managed Rulesets (Bot Protection, AI Bots, OWASP Core), IP blocking. Pro is sufficient for most early-growth SaaS; Enterprise adds dedicated DDoS support during distributed attacks.

**Add Cloudflare in front only if** (a) volumetric attacks exceed Vercel's auto-mitigation *and* Enterprise support is insufficient, (b) you need zone-level DNS security features not on Vercel, (c) you need WAF rules more granular than Vercel WAF. Below ~50k MAU this is almost never true — Cloudflare reverse-proxying degrades BotID detection signals.

**Rate-limiting algorithm selection**: sliding-window counter (Upstash default) for auth, email, and user-facing endpoints — no boundary burst, one Redis call per check; token bucket for content publishing, AI budgets, and API-key tier quotas — allows bursts with steady refill; fixed window only for cheap coarse edge limits; sliding-window log only for critical low-volume endpoints like password-reset trigger. Always expose `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and `Retry-After` headers.

### Account takeover prevention

Verizon 2025 DBIR: credential compromise is initial access in 22% of breaches; 2025 residential-proxy networks defeat per-IP rate limits. Supabase Auth provides bcrypt hashing, leaked-password protection via HIBP (**Pro+ only, off by default — enable it**), TOTP MFA (free), WebAuthn GA, Phone MFA (warn users about SIM-swap risk).

Gaps to build: velocity/ASN reputation, impossible-travel detection (great-circle distance + MaxMind GeoIP2 or ipinfo; >900 km/h implied velocity = challenge), device fingerprinting for login anomalies (FingerprintJS Pro's stable `visitorId`; free fallback: UA + accept-language + JA3 composite hash), suspicious-login email via Supabase Auth Hook, progressive rate-limiting on failed logins with identical timing+messages for unknown email vs wrong password (prevents enumeration, per OWASP).

**Passkeys by end of 2026**: 2025 data shows ~69% of users have at least one passkey, HubSpot reports 25% higher login success + 4× faster login vs password+2FA, Google reports 4× more successful sign-ins, TikTok 97% passkey success, Apple iOS 26 added auto passkey upgrade on password login. Use SimpleWebAuthn, identifier-first UX, `autocomplete="webauthn"` Conditional UI. Start opt-in after MFA enrollment (highest conversion moment), target passkey-primary by end of 2026.

**Pillar 5 priorities.** *P0:* audit endpoints against category list, switch auth/email to sliding window, Vercel WAF coarse `/api/*` limit as compute backstop, BotID Basic on auth+OAuth+invite+AI, Bot Protection Managed Ruleset in Challenge mode, webhook hardening (IP allowlist + constant-time HMAC + 5-min tolerance + event-id dedup + idempotent DB writes), Supabase HIBP leaked-password protection enabled, progressive backoff on sign-in, TOTP MFA required for admin roles, suspicious-login notifications via Auth Hook, Attack Challenge Mode runbook, Vercel spend-management alerts. *P1:* Arcjet evaluation if launching Empire-tier API, impossible-travel with MaxMind, quarterly webhook secret rotation, audit-log table with 7-yr retention path, refresh-token rotation tightening, Turnstile/hCaptcha fallback on suspicious BotID, tiered API-key quotas. *P2:* passkeys as primary, BotID Deep Analysis, FingerprintJS Pro, HIBP domain monitoring for customer emails, JA3/JA4 denylists, step-up re-auth on destructive actions, evaluate Cloudflare only if volumetric attacks recur.

---

## Pillar 6 — team security and multi-tenant isolation

### RLS is not enough — defense in depth

RLS is the database's last line, not your only one. The production pattern (Makerkit, Supabase docs): resolve `workspace_id` from server-side context never client input, add explicit `where workspace_id = $1` even when RLS would filter identically (forces index path), re-assert membership in application code before mutations, let RLS catch what slips through. Every `public`-schema table must have RLS enabled — **tables without policies are publicly readable via the anon key**. Add a CI lint against `pg_policies` that fails builds when a new `public` table has zero policies.

**Service role containment is non-negotiable**. The `service_role` key always bypasses RLS. Hard rules: server env vars only, never `NEXT_PUBLIC_*`, narrow admin paths only (backfills, webhook handlers, Stripe sync, invite acceptance). Instantiate two server clients — an "acting-as-user" client hydrated from the request JWT, and a separate service-role client — never share. Supabase's SSR clients silently pick up user cookies and swap the Authorization header if misconfigured.

**Common RLS pitfalls to audit**:

- Missing policies on joined/child tables. A secure `posts` with unsecured `post_comments` breaks isolation. Use Supabase's recommended `EXISTS` predicate on the parent for every child, not duplicated tenant_id logic that drifts.
- `SECURITY DEFINER` functions run as owner (usually `postgres`) — bypass RLS. Keep them in a non-exposed schema (`private`), `REVOKE EXECUTE ... FROM anon, authenticated`, `GRANT EXECUTE` only where needed.
- In Postgres 15+, **views use `WITH (security_invoker = true)`** so they honor caller RLS.
- Never trust client-supplied JWT claims. Write sensitive claims (`workspace_id`, `role`, `plan`) via `custom_access_token_hook` from a server-trusted source table. Use `auth.jwt()` in RLS — it reads verified claims.
- **Storage bucket policies**: scope by path — `(storage.foldername(name))[1] = (select workspace_id::text from memberships where user_id = auth.uid())`. Separate public-asset buckets from private.

### RLS testing — pgTAP + Basejump helpers

Minimum viable test suite: schema-level assertion that RLS is enabled on every `public` table, negative tests as anon user (`throws_ok` on INSERT, `is_empty` on SELECT/UPDATE), cross-tenant negative (User A in workspace X cannot access workspace Y), role escalation negative, storage bucket negative. Run via `supabase test db` on every PR in GitHub Actions. Basejump's `basejump-supabase_test_helpers` (via dbdev) provides `tests.create_supabase_user()`, `tests.authenticate_as()`, `tests.rls_enabled('public')`.

### RBAC model

Five roles in a `workspace_memberships` table (not on global users): **Owner** (transfer ownership, delete workspace, billing), **Admin** (members, SSO, integrations, connected accounts), **Editor** (create/schedule/publish content), **Viewer/Analyst** (read-only), **Billing Admin** (invoices and payment only, no content — enterprise procurement explicitly asks for this separation).

Back roles with an enum *and* a permissions table: enum keeps the common path fast, the permissions table lets you iterate granularity without migrations. Inject `workspace_id` + `role` into JWTs via `custom_access_token_hook`. RLS uses `auth.jwt() ->> 'workspace_id'` and a `has_permission(resource, action)` `SECURITY DEFINER` helper in `private`. **Force session revocation on role change** — otherwise a demoted user retains their JWT for up to 1 hour.

Critical distinction frequently muddled: *permissions* answer "can this user do X?"; *tier gating* answers "is this feature available on this workspace's plan?"; *feature flags* answer "should we expose this right now?". Three separate systems. Gate every feature with `plan_allows(workspace, feature) AND role_has_permission(user, workspace, permission) AND flag_enabled(feature, user)`.

**ReBAC (OpenFGA, SpiceDB, Permify, Oso Cloud) is overkill today** but relevant if agency/reseller hierarchies become dominant. OpenFGA achieved CNCF Incubation Oct 2025; Cedar pricing cut 97% in June 2025 to $5/M requests. Stay with RBAC + ABAC guardrails until the object graph genuinely demands relationships.

### SSO/SAML — buy, don't build

Supabase Auth supports SAML 2.0 SSO natively, multi-tenant with `sso_provider_id` in JWT usable in RLS — but **no SCIM**, which serious enterprise buyers require for automated deprovisioning. On hosted, Pro+ with per-SSO-MAU metering ($0.015/MAU above quota).

**Decision tree for Juno33**: (1) Supabase native SAML with JIT provisioning for the first 1–3 enterprise deals if they accept it (P1). (2) **WorkOS** at $125/connection/month SSO + $125/connection/month SCIM + audit logs = recommended pick once closing $2K+ ACV deals — best DX, every IdP, Admin Portal self-serve (P2). (3) BoxyHQ/Ory Polis is free open-source if you have strong DevOps. (4) Stytch B2B offers a generous free tier (10K MAU, 5 SSO/SCIM connections). (5) **Do not build custom SAML** — samlify/saml2-js complexity is why WorkOS exists as a business; XML DSig vulnerabilities keep appearing.

**SCIM is the harder requirement**. SSO without SCIM means offboarded employees retain app access — a SOC 2 / ISO 27001 finding waiting to happen. WorkOS/Stytch/Scalekit provide real-time deprovisioning webhooks; implement the handler to revoke Supabase sessions, remove membership rows, optionally transfer owned resources, write an audit log entry.

**The SSO tax**: don't put basic Google/Microsoft OIDC behind a paywall — that lands you on Rob Chahin's sso.tax Wall of Shame. Reserve the upcharge for **SAML + SCIM + audit logs + custom domain** bundled as an Enterprise tier. Typical trigger: first $2K+ ACV deal with SAML in the security questionnaire.

### Sessions and MFA

**Supabase defaults** are 1-hour JWT + 30-day refresh with rotation and reuse detection — keep them unless you have a specific reason. RFC 9700 (January 2025 OAuth 2.0 BCP) allows up to ~60 minutes for general APIs, tighter (5–15 min) only for regulated data. Preserve reuse-detection semantics if you wrap any of it in Vercel Edge middleware. Handle the multi-tab race with a 5–10 second grace window that returns the same replacement token rather than nuking sessions on benign collisions.

Concurrent session limits (not built-in): add a `user_sessions` table keyed to refresh-token ID with (user_id, workspace_id, device_fingerprint, user_agent, ip, last_seen), cap at 5 concurrent for enterprise, provide "Sign out other sessions" UI, force global signout on password change, MFA change, or role revocation. Build a **"revoke all sessions platform-wide" kill switch now** — you don't want to improvise during an incident.

**MFA hierarchy per NIST SP 800-63B-4 (August 2025 final)**: (1) WebAuthn/passkeys — phishing-resistant, cannot be proxied by AiTM, the gold standard; syncable OK for AAL2, device-bound for AAL3; (2) TOTP — baseline, free on all Supabase projects; (3) **SMS downgraded to "restricted authenticator"** — allowed with conditions but informing users of SIM-swap/SS7 risks is required; (4) email magic links — weakest, recovery only.

**Enforcement matrix for Juno33**: Owner/Admin/Billing Admin **mandatory** MFA, `aal2` required for destructive operations via `getAuthenticatorAssuranceLevel()` and RLS predicates like `auth.jwt() ->> 'aal' = 'aal2'` gating `billing`, `workspace_settings`, `social_oauth_tokens` tables. Editors strongly encouraged with 14-day grace after signup. Step-up re-authentication within last 5 minutes for billing changes, member removal, disconnecting a social account, workspace deletion. **Internal Juno33 production access uses WebAuthn/hardware keys**, not TOTP, per CISA phishing-resistant MFA guidance for admins.

**Recovery codes**: Supabase does not provide built-in recovery codes; the docs recommend a second factor. Build your own — generate 10 single-use codes on enrollment, hash with argon2id, store in `user_recovery_codes` with RLS limited to the owner, verify via an Edge Function that calls `auth.admin`. Pair with verified-email-required flow that re-enrolls MFA after recovery (NIST rule: recovery cannot undercut target AAL).

**Pillar 6 priorities.** *P0:* RLS on every public table + CI lint, service-role containment + two-client pattern, SECURITY DEFINER audit + move to `private` + views `security_invoker=true`, Storage RLS scoped by workspace path, OAuth tokens encrypted in `private` schema via Vault/pgsodium, pgTAP cross-tenant suite in CI, five-role RBAC with JWT hook, force session revocation on password/role/MFA change + global kill switch, MFA mandatory for Owner/Admin/Billing Admin with `aal2` gating, hardware-key MFA for Juno33 team production access. *P1:* permissions table for per-feature granularity, tier-gating and feature-flag systems separated, workspace-level "require MFA for all members" toggle, WebAuthn/passkey enrollment in UI, self-built recovery codes, device tracking + impossible-travel alerts, session-list UI, Enterprise-tier productization bundling SAML+SCIM+audit logs+custom domain, Supabase native SAML for first enterprise deals. *P2:* WorkOS (or Scalekit/Stytch after bake-off), SCIM deprovisioning webhook handler, customer-defined custom roles for Enterprise tier, optional dedicated-schema tier for regulated customers, ReBAC (OpenFGA/SpiceDB) if agency hierarchy becomes dominant, DPoP/mTLS token binding when mobile/partner API appears, continuous session monitoring per NIST SP 800-63B-4 §5.3 with SIEM integration.

---

## Consolidated 12-month roadmap

### Next 30–90 days (P0 — the can't-wait list)

Deploy the **Meta Data Deletion Callback URL** with HMAC verification and monitoring — this is the single highest-leverage action because callback failure can revoke API access across all 300+ connections. Migrate token encryption to **envelope encryption with AWS KMS as KEK** while maintaining AES-256-GCM with unique nonces, 128-bit tags, and AAD binding. Ship the **27-vendor erasure pipeline** with a deletion-log table, counter-signed DPAs, and a Juno33 TIA. Deploy the consent banner with GPC detection, symmetric Accept/Reject, session-replay gated separately, and the January 2026 "Opt-Out Request Honored" confirmation. Enforce **MFA mandatory for Owner/Admin/Billing Admin roles** with `aal2` gating on destructive operations, plus hardware keys for internal production access. Onboard a compliance platform (Vanta recommended) and adopt 15 core policies. Enable Supabase HIBP leaked-password protection. Ship pgTAP cross-tenant RLS tests in CI with a `pg_policies` lint. Wire Storybook + Playwright + axe with EN-301-549 rules. Remediate WCAG 2.2 AA basics: contrast, focus management, 2.5.8 target size, 2.5.7 drag alternatives, 3.3.8 paste-allowed authentication.

### Next quarter (P1 — competitive parity)

Begin the **6-month SOC 2 observation window** scoped to Security + Availability + Confidentiality with quarterly access reviews, monthly vuln scans, pen test in months 4–6, backup restore test, BCP tabletop. Set **EU residency defaults** on every vendor (Supabase Frankfurt, Vercel fra1, PostHog Cloud EU, Sentry EU, Intercom EU). Ship **WebAuthn/passkey enrollment**, self-built recovery codes, device tracking with impossible-travel alerts, session-list UI, workspace-level "require MFA for all members" toggle. Migrate date pickers to react-aria; add aria-live for async actions; publish accessibility statements in DE/FR/IT/ES/NL. Quarterly webhook secret rotation. Stripe redaction-on-deletion with documented legal-hold justification. Article 50 AI-transparency disclosures prepared for August 2026. Productize the Enterprise tier bundling SAML + SCIM + audit logs + custom domain. Evaluate Arcjet if launching Empire-tier public API.

### 6–12 months (P2 — enterprise and maturity)

**SOC 2 Type II report issued** with quarterly bridge letters. **WorkOS** (or Scalekit/Stytch after bake-off) for SAML + SCIM + Admin Portal + audit logs with a SCIM deprovisioning webhook. ISO 27001:2022 expansion (40–60% incremental cost). Third-party accessibility audit + VPAT/ACR. Passkeys as primary auth. BotID Deep Analysis + FingerprintJS Pro. HIBP domain monitoring for customer emails. AI-generated content watermarking per the March 3, 2026 Code of Practice draft. Customer-defined custom roles for Enterprise tier. DPF-withdrawal contingency rehearsal tied to the Latombe appeal. Reserve dedicated-schema optionality for a regulated-customer tier. Consider ReBAC only if agency/reseller hierarchies materialize.

## Cost envelope

The 12-month cash outlay lands around **$80–130K total**: $40–80K for SOC 2 Type II (platform + auditor + pen test + MDM + misc tooling + Vercel SAML/Upstash Prod Pack/Supabase Team upgrades), $15–30K for accessibility (third-party audit + consent management platform + remediation engineering), $10–15K for WorkOS when enterprise deals materialize, and under $1K/year for AWS KMS + related KEK infrastructure. Year-two maintenance drops to roughly $40–60K as the compliance machine runs on rails.

## The unifying insight

Juno33's hardest near-term work is not encryption — the AES-256-GCM foundation is sound — nor is it technical infrastructure, which Supabase + Vercel + Upstash + Stripe already carries most of. The hardest work is **operational plumbing across vendor boundaries**: a callback URL that Meta will enforce against, a deletion pipeline that reaches 27 systems within a month, a consent signal that respects GPC, an `audit_events` table that satisfies CC7.2 auditors, and an MFA policy that actually gets enforced on admin accounts. The most expensive mistake is underinvesting in the first 90 days — the Meta callback gap alone is existential, the EAA German *Abmahnung* vector is already live, and the January 2026 CCPA enforcement cycle targets precisely the patterns a hurried implementation tends to miss. Get the P0 list done, and the P1/P2 arc becomes evolutionary rather than reactive.
