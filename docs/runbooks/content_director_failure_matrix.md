# Content Director Failure Matrix

| Failure | Detected state | Safe retry/reconciliation | Retained evidence | Operator action | Replan |
|---|---|---|---|---|---|
| Plan apply interrupted | missing/incomplete version transaction | rerun identical apply; fingerprint is idempotent | prior versions | inspect plan list | no unless inputs changed |
| Duplicate plan apply | existing input fingerprint | return existing version | exact original | none | no |
| Execution interrupted | item remains GENERATING/RECONCILING | reconcile provider request before retry | request and item receipt | resolve ambiguity | sometimes |
| Submission ambiguous | RECONCILING | never blind retry | request fingerprint/receipt | provider reconciliation | no |
| Partial generation | mixed REVIEW_READY/BLOCKED | execute only uncompleted items | successful outputs | review successes | maybe |
| Source unavailable | BLOCKED | do not substitute silently | prior source lineage | approve replacement | yes |
| Audio unavailable | finishing blocked | rerank eligible cache without changing video | video and audio receipt | approve/retry audio | no |
| Account unhealthy | BLOCKED assignment | wait for valid projection | creative score unchanged | repair account | yes |
| Export mismatch | BLOCKED | compare HMAC/final SHA | exact approval/media | rebuild exact export | no |
| Schedule conflict | proposal blocked | ThreadsDashboard resolves | creative lineage | choose window | maybe |
| Publication ambiguous | RECONCILING | reconcile Instagram identity before retry | platform request evidence | inspect platform | no |
| Metric missing | MISSING | observe later; never write zero | publication identity | wait/inspect sync | no |
| Recommendation expires/revokes | deterministic fallback | refresh/review evidence | prior decision receipt | approve current evidence | yes |
| Experiment loses variant | BLOCKED interpretation | do not declare winner | surviving item/outcome | rerun comparable test | yes |
| Runtime changes | version mismatch warning | verify supported runtime | plan version/implementation SHA | promote or replan | maybe |

Completed and published work remains valid unless its own lineage fails.
