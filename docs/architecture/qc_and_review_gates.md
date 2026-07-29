# QC and Review Gates

This is the canonical Creator OS QC and review contract.

```text
machines produce evidence
→ Campaign Factory aggregates evidence
→ the operator supplies creative authority
```

## Authority

| Component | Produces evidence about | May approve |
| --- | --- | --- |
| Reel Factory | render completion, generated-visual QC, caption placement, caption pixels, lineage | nothing |
| Audio Radar | selected track/segment, AAC embed, stream verification, final-media SHA | nothing |
| ContentForge | exact-subject-SHA collision, distinctness, OCR, readability, safe-zone and watchability findings | nothing |
| Campaign Factory | current-SHA integrity, evidence freshness, publishability, exact draft projection | approval machinery only |
| Operator | identity, anatomy, motion, caption, audio, intent and would-post verdict | the exact reviewed media/text projection |
| ThreadsDashboard | draft ingestion, scheduling, publishing and reconciliation evidence | its separate schedule/publish actions |

`review_candidate` means no configured automated blocker was found. It is not
creative approval.

## Ordered gates

```text
Gate 1 — Provider-output technical validation
Gate 2 — Caption placement/render decision
Gate 3 — Audio fulfillment
Gate 4 — Final artifact integrity and exact SHA
Gate 5 — ContentForge independent audit of that SHA
Gate 6 — Campaign Factory publishability aggregation
Gate 7 — Operator media review and Creative Approval v2
Gate 8 — Draft-only export readiness
```

Gate 1 is generated-visual QC. Gate 4 is final-media QC after every caption,
audio, crop, transcode, repair, or replacement operation. These are not
interchangeable.

## Caption placement

Focal-safe placement has four decisions:

| Decision | Status | Render behavior |
| --- | --- | --- |
| `passed` | passed | burn the selected safe lane |
| `failed_no_safe_lane` | failed | render clean media |
| `insufficient_evidence` | failed | render clean media |
| `legacy_selected` | passed | choose the legacy minimum only when explicitly requested |

`no_safe_caption_lane` and insufficient evidence are clean-fallback decisions,
not operator overrides. The exact approval projection must bind
`burnedCaptionText=null`, the exact Instagram post caption, the clean media SHA,
and the fallback reason.

## Byte changes and evidence freshness

```text
any media-byte change
→ new SHA
→ audit_status=pending
→ review_state=review_ready
→ historical receipts retained but superseded
→ final integrity, ContentForge audit, operator review and approval rerun
```

ContentForge reports store `subjectSha256`. Approval and export require the
latest report subject to equal the current registered asset SHA. The generic
`review_state` and `approval_decisions` row are workflow state; Creative
Approval v2 is the exact-SHA export authority.

## Warning ownership

Campaign Factory classifies observed findings once:

- `advisory`: visible to the operator and nonblocking.
- `operator_overridable`: blocks by default; an export warning-override receipt
  records operator, reason, time, warning codes and payload fingerprint.
- `hard_blocker`: cannot be overridden; repair, replacement, clean fallback, or
  rejection is required.

Exact-SHA mismatch, detector/OCR absence when required, missing identity
evidence, hidden text, safe-zone violations, and face-covered captions are hard
blockers.

## Rejection

```text
operator rejects exact SHA
→ review_state=rejected
→ export, reuse, reservation and learning ineligible
→ active reservations expire
→ no automatic repair or regeneration is authorized
```

Provider completion and technical QC history remain truthful and unchanged.

## Operator diagnosis

`creator-os qc explain --asset <ID>` reports current file SHA verification,
generated-visual QC, placement and overlay evidence, audio receipt, final
integrity, ContentForge subject SHA, Campaign readiness, operator review,
Creative Approval v2, superseded evidence and current blockers.
