#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVELOPER_ROOT = REPO_ROOT.parent
REEL_FACTORY_ROOT = DEVELOPER_ROOT / "reel_factory"

sys.path.insert(0, str(REPO_ROOT))
sys.path.append(str(REEL_FACTORY_ROOT))

from campaign_factory.adapters import threadsdash as threadsdash_adapter  # noqa: E402
from campaign_factory.adapters.threadsdash import (  # noqa: E402
    build_draft_payloads,
    sync_performance_snapshots,
)
from campaign_factory.config import Settings  # noqa: E402
from campaign_factory.core import CampaignFactory  # noqa: E402
from campaign_factory.fileops import atomic_write_text
from campaign_factory.reel_ledger_promotion import promote_reel_ledger  # noqa: E402
from reel_pipeline import build_caption_outcome_context  # noqa: E402

CAPTION_TEXT = "Hard launch energy."
CAPTION_HASH = "caption_hash_e2e_proof"
CAMPAIGN_SLUG = "caption-proof"
IG_POST_CAPTION = "Hard launch energy, no warmup. #reels"
CONTEXT_KEYS = [
    "schema",
    "caption_hash",
    "caption_text",
    "caption_bank",
    "caption_banks",
    "creator_mix",
    "creator_model",
    "frame_type",
    "length_class",
    "format_class",
    "caption_fit_version",
    "suitability_decision",
    "suitability_reason",
    "render_recipe",
    "source_clip",
    "rendered_output",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Caption Outcome Tracking v1 end-to-end proof."
    )
    parser.add_argument(
        "--record",
        type=Path,
        default=REPO_ROOT / "CAPTION_OUTCOME_TRACKING_V1_PROOF.json",
        help="Where to write the proof record JSON.",
    )
    args = parser.parse_args()

    # Learning readers fail closed when LEARNING_LOOP_CUTOVER is unset; pin a
    # cutover before the fixture's published_at so the proof snapshot is
    # eligible (matches production deploy config, see learning_score.py).
    os.environ.setdefault("LEARNING_LOOP_CUTOVER", "2026-06-01T00:00:00+00:00")

    with tempfile.TemporaryDirectory(prefix="caption_outcome_e2e_") as tmp:
        proof = run_proof(Path(tmp))

    atomic_write_text(
        args.record,
        json.dumps(proof, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(_summary(proof), indent=2, sort_keys=True))
    print(f"proof_record={args.record}")
    return 0


def run_proof(tmp_path: Path) -> dict[str, Any]:
    cf = _make_factory(tmp_path)
    rows: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url
            self.service_role_key = service_role_key

        def select(self, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            if table == "posts":
                return rows
            if table == "post_metric_history":
                # Learning eligibility requires history_source='metric_history'
                # (see learning_score.LEARNING_ELIGIBLE_SQL); an empty history
                # forces the post_row_fallback path and the snapshot is
                # silently dropped from every report. Mirror each post row as
                # one metric-history observation.
                return [
                    {
                        "id": f"pmh_{post['id']}",
                        "post_id": post["id"],
                        "account_id": post.get("account_id"),
                        "platform": post.get("platform"),
                        "snapshot_at": post.get("updated_at"),
                        "hours_since_publish": 1.5,
                        "views_count": post.get("views"),
                        "likes_count": post.get("likes_count"),
                        "replies_count": post.get("ig_comment_count"),
                        "reposts_count": 0,
                        "quotes_count": 0,
                        "shares_count": post.get("ig_shares"),
                        "saves_count": (
                            (post.get("metadata") or {}).get("metrics", {}).get("saves")
                        ),
                        "reach": (
                            (post.get("metadata") or {}).get("metrics", {}).get("reach")
                        ),
                        "engagement_rate": 0.08,
                    }
                    for post in rows
                ]
            raise AssertionError(f"unexpected table: {table}")

    original_client = threadsdash_adapter.SupabaseRestClient
    threadsdash_adapter.SupabaseRestClient = FakeClient
    try:
        return _run_steps(cf, tmp_path, rows)
    finally:
        threadsdash_adapter.SupabaseRestClient = original_client
        cf.close()


def _run_steps(
    cf: CampaignFactory, tmp_path: Path, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    rendered_output = tmp_path / "rendered_caption_outcome_proof.mp4"
    rendered_output.write_bytes(b"caption outcome proof bytes")
    campaign = cf.upsert_campaign(CAMPAIGN_SLUG, "lola")
    caption_lineage = {
        "schema": "reel_factory.caption_lineage.v1",
        "captionHash": CAPTION_HASH,
        "rawCaptionText": CAPTION_TEXT,
        "sourceBanks": ["launch_hooks"],
        "selectedBanks": ["launch_hooks"],
        "selectedMix": "Lola",
        "creatorModel": "lola",
        "sourceClip": "clip_010",
        "lengthClass": "very_short",
        "formatClass": "single_line",
        "frameType": "mirror_fullbody",
        "captionFitVersion": "v1",
        "suitabilityDecision": "allowed",
        "suitabilityReason": "very_short static caption allowed for mirror_fullbody",
    }
    emitted_context = build_caption_outcome_context(
        caption_text=CAPTION_TEXT,
        caption_lineage=caption_lineage,
        render_recipe="v09_caption_bg",
        source_clip="clip_010",
        rendered_output=str(rendered_output.resolve()),
        creator_model="lola",
    )
    # Publishability v2 gates read these from the stored caption outcome context.
    # They are not part of CONTEXT_KEYS, so the cross-stage fingerprint assertion
    # still proves the canonical context is byte-identical at every stage.
    emitted_context = {
        **emitted_context,
        "captionPlacementPolicy": "focal_safe_v1",
        "captionPlacementDecision": {
            "status": "passed",
            "policy": "focal_safe_v1",
            "lane": "lower_third",
            "checkedAt": "2026-06-05T09:00:00+00:00",
        },
        "instagram_post_caption": IG_POST_CAPTION,
    }
    _write_reel_posting_slot(
        cf,
        campaign_slug=campaign["slug"],
        rendered_output_path=rendered_output,
        lineage={
            "schema": "reel_factory.render_lineage.v1",
            "sourceClip": "clip_010",
            "captionHash": CAPTION_HASH,
            "captionBank": {
                **caption_lineage,
                "captionOutcomeContext": emitted_context,
            },
            "recipe": "v09_caption_bg",
        },
    )

    promotion = promote_reel_ledger(
        cf,
        campaign_id=campaign["slug"],
        reel_factory_root=cf.settings.reel_factory_root,
        apply=True,
    )
    if not promotion.get("applied"):
        raise AssertionError(f"promotion did not apply: {promotion}")
    if promotion.get("summary", {}).get("rowsToCreate") != 1:
        raise AssertionError(
            f"promotion did not produce one create action: {promotion}"
        )

    asset_row = cf.conn.execute(
        "SELECT * FROM rendered_assets WHERE caption_hash = ?", (CAPTION_HASH,)
    ).fetchone()
    if not asset_row:
        promoted_rows = [
            dict(row)
            for row in cf.conn.execute(
                "SELECT id, content_hash, caption_hash, caption_outcome_context_json FROM rendered_assets"
            ).fetchall()
        ]
        raise AssertionError(
            f"promoted asset did not retain caption hash {CAPTION_HASH}: {promoted_rows}"
        )
    asset = dict(asset_row)
    _attach_publishability_evidence(cf, asset)
    asset = dict(
        cf.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (asset["id"],)
        ).fetchone()
    )
    plan = dict(
        cf.conn.execute(
            "SELECT * FROM distribution_plans WHERE rendered_asset_id = ?",
            (asset["id"],),
        ).fetchone()
    )
    draft_payload = build_draft_payloads(
        cf,
        campaign_slug=campaign["slug"],
        user_id="proof_user",
        schedule_mode="preview",
    )
    draft = draft_payload["drafts"][0]
    metadata = draft["metadata"]["campaign_factory"]

    rows.append(_threadsdash_post_row(draft, metadata))
    sync_result = sync_performance_snapshots(
        cf,
        campaign_slug=campaign["slug"],
        user_id="proof_user",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
    )
    snapshot = dict(
        cf.conn.execute(
            "SELECT * FROM performance_snapshots WHERE caption_hash = ?",
            (CAPTION_HASH,),
        ).fetchone()
    )
    report = cf.caption_outcome_report(campaign["slug"])

    contexts = {
        "captionSelected": emitted_context,
        "reelRenderLineage": emitted_context,
        "renderedAssets": json.loads(asset["caption_outcome_context_json"]),
        "distributionPlans": json.loads(plan["caption_outcome_context_json"]),
        "threadsdashDraft": draft["captionOutcomeContext"],
        "threadsdashMetadata": metadata["captionOutcomeContext"],
        "performanceSnapshots": json.loads(snapshot["caption_outcome_context_json"]),
        "captionOutcomeReport": report["byCaptionHash"][0]["captionOutcomeContext"],
    }
    _assert_same_context(contexts)

    return {
        "schema": "campaign_factory.caption_outcome_tracking_v1_e2e_proof.v1",
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "manualReviewOnly": report["manualReviewOnly"],
        "guardrails": {
            "autoLearning": False,
            "winnerBankPromotion": False,
            "captionSelectionChanges": False,
            "bankWeightChanges": False,
            "phase2TimedSegmentation": False,
            "promptGrokKlingAudioChanges": False,
        },
        "campaign": {"id": campaign["id"], "slug": campaign["slug"]},
        "ids": {
            "renderedAssetId": asset["id"],
            "distributionPlanId": plan["id"],
            "threadsdashPostId": rows[0]["id"],
            "performanceSnapshotId": snapshot["id"],
        },
        "syncResult": {
            "inserted": sync_result["inserted"],
            "updated": sync_result["updated"],
            "skipped": sync_result["skipped"],
        },
        "captionHashByStage": {
            stage: context["caption_hash"] for stage, context in contexts.items()
        },
        "contextFingerprintByStage": {
            stage: _context_fingerprint(context) for stage, context in contexts.items()
        },
        "contextsByStage": contexts,
        "reportCoverage": report["coverage"],
    }


def _make_factory(tmp_path: Path) -> CampaignFactory:
    reel_root = tmp_path / "reel_factory"
    return CampaignFactory(
        Settings(
            root=tmp_path,
            db_path=tmp_path / "campaign_factory.sqlite",
            reel_factory_root=reel_root,
            contentforge_root=tmp_path / "contentforge",
            threadsdash_root=tmp_path / "ThreadsDashboard",
            campaigns_dir=tmp_path / "campaigns",
        )
    )


def _attach_publishability_evidence(cf: CampaignFactory, asset: dict[str, Any]) -> None:
    """Attach the evidence the publishability v2 gates require.

    The proof exercises caption-outcome context integrity, not the audit or
    audio pipelines, so this stands in for contentforge (audit report) and the
    operator audio flow (audioIntent) with minimal passing evidence — the same
    shape the publishability unit tests use.
    """
    report_path = Path(asset["campaign_path"]).with_suffix(".audit_proof.json")
    report_payload = {
        "readinessSummary": {
            "uploadReady": True,
            "blockingReasons": [],
            "warnings": [],
            "blockingCodes": [],
            "warningCodes": [],
            "visualQcStatus": "passed",
            "identityVerificationStatus": "passed",
        },
        "visualQcStatus": "passed",
        "identityVerificationStatus": "passed",
        "visualQc": {"status": "passed"},
        "identityVerification": {"status": "passed"},
        "overallVerdict": "pass",
        "warnings": [],
        "failedChecks": [],
        "error": None,
    }
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")
    cf.conn.execute(
        """
        INSERT INTO audit_reports
        (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score, status,
         layers_json, verdicts_json, overall_verdict, files_analyzed, failed_checks_json, warnings_json, created_at)
        VALUES (?, ?, ?, 'run_proof', ?, 100, 'approved_candidate', '{}', '{}', 'pass', 1, '[]', '[]', ?)
        """,
        (
            "audit_proof",
            asset["campaign_id"],
            asset["id"],
            str(report_path),
            "2026-06-05T09:00:00+00:00",
        ),
    )

    caption_generation = json.loads(asset.get("caption_generation_json") or "{}")
    caption_generation["audioIntent"] = {
        "status": "skipped",
        "reason": "proof_fixture_no_audio",
    }
    # Publishability reads the operator post caption and placement QC decision
    # from caption_generation_json (see instagram_post_caption_for_asset and the
    # generatedAssetLineage merge in publishability.py); supply them the same way.
    caption_generation["instagram_post_caption"] = IG_POST_CAPTION
    generated_lineage = caption_generation.get("generatedAssetLineage")
    if not isinstance(generated_lineage, dict):
        generated_lineage = {}
    generated_lineage.setdefault("captionPlacementPolicy", "focal_safe_v1")
    generated_lineage.setdefault(
        "captionPlacementDecision",
        {
            "status": "passed",
            "lane": "lower_third",
            "policy": "focal_safe_v1",
            "checkedAt": "2026-06-05T09:00:00+00:00",
        },
    )
    caption_generation["generatedAssetLineage"] = generated_lineage
    cf.conn.execute(
        "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = ?",
        (json.dumps(caption_generation), asset["id"]),
    )
    cf.conn.commit()


def _write_reel_posting_slot(
    cf: CampaignFactory,
    *,
    campaign_slug: str,
    rendered_output_path: Path,
    lineage: dict[str, Any],
) -> None:
    db_path = cf.settings.reel_factory_root / "manifest.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posting_slots (
                posting_slot_id TEXT PRIMARY KEY,
                account_id TEXT,
                account_handle TEXT,
                platform TEXT,
                campaign_id TEXT,
                date TEXT,
                slot_type TEXT,
                planned_slot_time TEXT,
                rendered_output_path TEXT,
                content_fingerprint TEXT,
                caption TEXT,
                audio_track_id TEXT,
                audio_source TEXT,
                audio_selected_reason TEXT,
                manual_audio_needed INTEGER DEFAULT 0,
                lineage_path TEXT,
                lineage_json TEXT,
                post_status TEXT,
                review_status TEXT,
                post_url TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO posting_slots
            (posting_slot_id, account_id, account_handle, platform, campaign_id, date, slot_type,
             planned_slot_time, rendered_output_path, content_fingerprint, caption, audio_track_id,
             audio_source, audio_selected_reason, manual_audio_needed, lineage_json, post_status, review_status)
            VALUES ('slot_caption_outcome_e2e', 'lola_1', 'lola_1', 'ig', ?, '2026-06-05',
                    'main', '10:00', ?, 'fp_caption_outcome_e2e', ?, 'audio_1',
                    'native_platform_audio', 'proof fixture', 0, ?, 'approved', 'approved')
            """,
            (
                campaign_slug,
                str(rendered_output_path),
                CAPTION_TEXT,
                json.dumps(lineage, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _threadsdash_post_row(
    draft: dict[str, Any], metadata: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": "post_caption_outcome_e2e",
        "status": "published",
        "platform": "instagram",
        "account_id": draft.get("accountId"),
        "instagram_account_id": draft.get("instagramAccountId"),
        "content": draft.get("content"),
        "created_at": "2026-06-05T10:00:00+00:00",
        "updated_at": "2026-06-05T12:00:00+00:00",
        "published_at": "2026-06-05T10:30:00+00:00",
        "permalink": "https://instagram.test/p/caption-outcome-e2e",
        "views": 1400,
        "likes_count": 90,
        "ig_comment_count": 10,
        "ig_shares": 15,
        "metadata": {
            "campaign_factory": metadata,
            "metrics": {"saves": 24, "reach": 1200, "watch_time_seconds": 330.0},
        },
    }


def _assert_same_context(contexts: dict[str, dict[str, Any]]) -> None:
    fingerprints = {
        stage: _context_fingerprint(context) for stage, context in contexts.items()
    }
    if len(set(fingerprints.values())) != 1:
        raise AssertionError(
            f"captionOutcomeContext changed across stages: {fingerprints}"
        )


def _context_fingerprint(context: dict[str, Any]) -> str:
    canonical = {key: context.get(key) for key in CONTEXT_KEYS}
    payload = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _summary(proof: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": proof["schema"],
        "captionHash": next(iter(proof["captionHashByStage"].values())),
        "allCaptionHashesMatch": len(set(proof["captionHashByStage"].values())) == 1,
        "allContextFingerprintsMatch": len(
            set(proof["contextFingerprintByStage"].values())
        )
        == 1,
        "stages": list(proof["captionHashByStage"].keys()),
        "manualReviewOnly": proof["manualReviewOnly"],
        "syncResult": proof["syncResult"],
        "reportCoverage": proof["reportCoverage"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
