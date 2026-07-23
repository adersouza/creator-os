# Creative approval and AI-disclosure evidence

Campaign Factory treats generated-motion approval and AI disclosure as one
exact, fail-closed evidence chain. Neither a review-state flag nor a generation
blocker string is sufficient by itself.

## Creative Approval v2

`campaign_factory.creative_approval.v2` is the only writable approval contract.
It binds the exact campaign, rendered asset, input/output hashes, creator and
intent, generation recipe, Router decision, execution evidence, trusted QC,
review manifest, export projection, caption/audio semantics, operator, and HMAC
attestation.

Historical v1 JSON remains readable for audit purposes, but it cannot authorize
publishability. V1 lacks the v2 campaign, rendered-asset, generation, Router,
execution, exact-export, and operator-attestation bindings. The approval store's
legacy inventory therefore classifies v1 records as non-operational and not
automatically migratable. The correct recovery is a fresh v2 review of the
current exact asset; missing evidence is never inferred from a historical v1
record.

## AI disclosure

Local model lineage can require intelligible AI-generated-media disclosure.
Campaign Factory derives that requirement from immutable motion-generation
metadata and the original generation blocker. It appends the canonical plain
text `AI-generated media.` to the Instagram post caption when an equivalent
disclosure is not already present.

Appending text does not resolve the gate. Resolution requires a valid Creative
Approval v2 whose authenticated content semantics bind the exact resulting
Instagram caption and whose export projection binds its exact caption hash.
Changed or missing caption evidence, a legacy approval, or an unapproved asset
remains blocked with `ai_generated_media_disclosure_required`.

This policy supplies the intelligible caption disclosure required by current
local-model lineage. It does not claim that a platform-native AI label has been
set, and it must not be used as evidence for one.
