# Canonical Data Owners

Exports, sidecars, caches, and UI metadata are not automatically systems of
record. The primary owner is the component allowed to create and update the
object.

| Object | Primary owner | Canonical state | Important downstream copies |
|---|---|---|---|
| campaign and creative plan | Campaign Factory | configured Campaign SQLite and campaign directories | Reel generation inputs, draft metadata |
| platform account | ThreadsDashboard | Supabase account tables | Campaign assignment metadata |
| reference corpus and labels | Reference Factory | configured Reference SQLite/data root | pattern cards, prompt packs, Campaign reference bank |
| generation prompt and reference | Reel Factory | direct-reference lineage sidecar | Campaign asset metadata |
| direct Soul still | Reel Factory | provider result plus direct-reference lineage | static MP4, optional Kling, Campaign import |
| rendered reel | Reel Factory until Campaign intake; Campaign Factory after intake | Reel output/lineage and Campaign `rendered_assets` | ContentForge evidence, draft media |
| overlay caption | Reel Factory | caption bank selection plus placement/render metadata | rendered MP4 and lineage |
| Instagram post caption | Campaign Factory until handoff; ThreadsDashboard after handoff | Campaign draft payload then Supabase post | platform post and learning context |
| audio intent | Reel Factory plus Pipeline Contracts schema | `<output>.audio_intent.json` | Campaign readiness and ThreadsDashboard native-audio proof |
| QC verdict | ContentForge | audit report/evidence | Campaign readiness decision |
| campaign asset approval | Campaign Factory | Campaign approval/review state | draft eligibility |
| product post approval | ThreadsDashboard | Supabase post approval state | schedule/publish gate |
| actual schedule and post | ThreadsDashboard | Supabase `posts` and publishing services | performance history |
| performance observation | ThreadsDashboard | post metric history | Campaign performance snapshots and learning fan-out |
| shared payload shape | Pipeline Contracts | canonical JSON schemas | generated TypeScript and immutable consumer package releases |

Rules:

- ContentForge judges media; it does not own campaign policy.
- Reel Factory owns generation evidence; it does not own platform accounts or
  publishing.
- Campaign Factory owns local campaign decisions and draft construction; it
  does not own real schedules or published posts.
- ThreadsDashboard owns product data, approval, scheduling, publishing, and raw
  platform metrics.
- Pipeline Contracts owns shape, never business state.
