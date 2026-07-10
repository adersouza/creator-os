"""Real-artifact full-chain E2E tests closing seam gaps (audit #1).

Campaign Factory's existing unit tests exercise each pipeline stage in
isolation and, at every stage boundary, hand-build the *input* the downstream
stage would have received (``add_rendered_asset``, ``threadsdash_campaign_factory_metadata``,
raw ``performance_snapshots``/``reference_patterns`` INSERTs). That leaves the
*seams* untested: a shape drift between what an upstream stage emits and what a
downstream stage reads would keep every unit test green while production breaks.

This module drives the REAL upstream stage and feeds its REAL output into the
REAL downstream stage. The only hand-built values are data owned by external
systems (ContentForge/QC verdicts, remote media-host URLs, ThreadsDashboard
metric numbers/timestamps) -- everything crossing a seam under test is produced
by the genuine upstream call.

Seam coverage:
  A. sync_reel_outputs -> export_threadsdash draft (caption spine)
  B. export_threadsdash posts -> sync_performance_snapshots (metric round-trip)
  C. performance_snapshots -> learning_fanout -> reference prompt_post_outcomes
  D. reference learning bank -> import_reference_bank -> recommend_next_batch
  E. full chain A..D, asserting the caption_hash/lineage spine at every hop.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from campaign_factory.adapters import threadsdash as threadsdash_adapter
from campaign_factory.adapters.threadsdash import (
    export_threadsdash,
    sync_performance_snapshots,
)
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory


# --------------------------------------------------------------------------- #
# Environment: the package-level conftest that sets these autouse fixtures lives
# under python_packages/campaign_factory/tests and does not apply here, so we
# replicate the two env fixtures the learning readers depend on.
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _e2e_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    # Cutover before every published_at we use, so the learning eligibility
    # predicate (learning_score.learning_eligible) stays exercised.
    monkeypatch.setenv("LEARNING_LOOP_CUTOVER", "2020-01-01T00:00:00+00:00")
    monkeypatch.setenv("THREADSDASH_ALLOWED_INGEST_HOSTS", "dashboard.example.com")


def make_factory(tmp_path: Path) -> CampaignFactory:
    reel_root = tmp_path / "reel_factory"
    (reel_root / "00_source_videos").mkdir(parents=True, exist_ok=True)
    (reel_root / "01_captions").mkdir(parents=True, exist_ok=True)
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


def set_source_prompt(
    cf: CampaignFactory,
    source_id: str,
    *,
    prompt_id: str,
    reference_id: str,
) -> None:
    """Seed the source asset's source_prompt.

    This is upstream of stage 2 (prompt generation), not part of any seam under
    test; we set it because the prompt-generation stage needs paid providers.
    It carries the promptId/referenceId that the real export_manifest threads
    into generatedAssetLineage.source -- the join the reference learning hop
    keys on.
    """
    source_prompt = {
        "promptId": prompt_id,
        "referenceId": reference_id,
        "generationTool": "manual_finished_video",
        "generatedAssetLineage": {
            "schema": "reel_factory.generated_asset_lineage.v1",
            "pipelineTraceId": f"trace_{prompt_id}",
            "source": {"promptId": prompt_id, "referenceId": reference_id},
            "generation": {"tool": "manual_finished_video"},
            "review": {"humanReviewRequired": True, "status": "draft"},
        },
    }
    cf.conn.execute(
        "UPDATE source_assets SET source_prompt = ? WHERE id = ?",
        (json.dumps(source_prompt, sort_keys=True), source_id),
    )
    cf.conn.commit()


def simulate_reel_render(
    cf: CampaignFactory,
    job: dict[str, Any],
    *,
    caption: str,
    recipe: str = "v01_original",
) -> Path:
    """Stand in for the reel_factory render worker.

    Follows test_core.test_sync_reel_outputs_reads_manifest_and_copies_rendered_asset:
    populate the caption sidecar's ``generation`` block and write a
    manifest.sqlite ``variations`` row + rendered output file. The caption text
    echoes the sidecar prepare_reel_inputs wrote (real upstream), so the
    caption spine flowing into sync_reel_outputs is genuine.
    """
    stem = job["reel_clip_stem"]
    sidecar = cf.settings.reel_factory_root / "01_captions" / f"{stem}.json"
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    data["generation"] = {
        "generation_id": "capgen_e2e",
        "model": "fake",
        "backend": "ollama",
        "prompt_hash": "prompt_hash",
        "caption_hashes": ["caption_hash_1"],
        "quality": [
            {"captionHash": "caption_hash_1", "qualityScore": 95, "warnings": []}
        ],
    }
    sidecar.write_text(json.dumps(data), encoding="utf-8")

    out_dir = cf.settings.reel_factory_root / "02_processed" / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{stem}_h00_{recipe}_9x16_light_deadbeef.mp4"
    out.write_bytes(b"rendered-e2e")

    manifest_db = cf.settings.reel_factory_root / "manifest.sqlite"
    conn = sqlite3.connect(manifest_db)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS variations (
              job_key TEXT, clip TEXT, recipe TEXT, recipe_params_json TEXT,
              caption_text TEXT, output_path TEXT, review_state TEXT, status TEXT,
              encoded_at INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO variations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "job",
                stem,
                recipe,
                json.dumps({"_target_ratio": "9:16"}),
                caption,
                str(out),
                "draft",
                "ok",
                1,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return out


def add_audit_report(
    cf: CampaignFactory,
    rendered_asset_id: str,
    *,
    audit_id: str = "audit_e2e",
) -> None:
    """Inject an approved ContentForge/QC audit report.

    QC/ContentForge is an external subsystem that GATES export; its verdict is
    not part of the caption spine crossing the seam under test (that seam is
    already covered by test_contentforge_handoff.py). Treating the passing
    verdict as an external-boundary stub is equivalent to injecting metric
    numbers. The report's readinessSummary carries visualQc/identity 'passed',
    which surface_handoff.content_trust_status_blockers resolves.
    """
    asset = cf.conn.execute(
        "SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)
    ).fetchone()
    assert asset is not None
    report_path = Path(asset["campaign_path"]).with_suffix(f".{audit_id}.json")
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
        (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score,
         status, layers_json, verdicts_json, overall_verdict, files_analyzed,
         failed_checks_json, warnings_json, created_at)
        VALUES (?, ?, ?, 'run_e2e', ?, 100, 'approved_candidate', '{}', '{}', 'pass',
                1, '[]', '[]', ?)
        """,
        (
            audit_id,
            asset["campaign_id"],
            rendered_asset_id,
            str(report_path),
            "2026-01-01T00:00:00+00:00",
        ),
    )
    cf.conn.commit()


def mark_publishable_qc(cf: CampaignFactory, rendered_asset_id: str) -> None:
    """Record the caption-placement-QC pass and audio-intent resolution.

    Caption-placement QC and audio-intent resolution are downstream QC/audio
    subsystems that GATE reel publishability. We stamp their verdicts here (only
    the QC decision status + audio-intent status), leaving caption_hash /
    caption_text -- the spine crossing the seam under test -- exactly as
    sync_reel_outputs produced them.
    """
    row = cf.conn.execute(
        "SELECT caption_outcome_context_json, caption_generation_json FROM rendered_assets WHERE id = ?",
        (rendered_asset_id,),
    ).fetchone()
    context = json.loads(row["caption_outcome_context_json"] or "{}")
    context["captionPlacementPolicy"] = "focal_safe_v1"
    context["captionPlacementDecision"] = {
        "status": "passed",
        "selectedLane": "top",
        "reason": "e2e external caption-placement QC pass",
    }
    generation = json.loads(row["caption_generation_json"] or "{}")
    generation["audioIntent"] = {
        "schema": "pipeline.audio_intent.v1",
        "mode": "native_platform_audio",
        "required": False,
        "status": "not_required",
    }
    cf.conn.execute(
        "UPDATE rendered_assets SET caption_outcome_context_json = ?, caption_generation_json = ? WHERE id = ?",
        (
            json.dumps(context, ensure_ascii=False, sort_keys=True),
            json.dumps(generation, ensure_ascii=False, sort_keys=True),
            rendered_asset_id,
        ),
    )
    cf.conn.commit()


# --------------------------------------------------------------------------- #
# Stateful fake ThreadsDashboard: a closure-shared post store. Export's
# reconcile and sync_performance_snapshots each construct a *fresh*
# SupabaseRestClient(url, key), so the store cannot live on the instance -- both
# clients close over the same dashboard object.
# --------------------------------------------------------------------------- #
class _FakeDashboard:
    """Materializes ThreadsDashboard `posts` from the REAL ingest body."""

    def __init__(self) -> None:
        self.posts: dict[str, dict[str, Any]] = {}
        self.metric_history: dict[str, list[dict[str, Any]]] = {}

    def ingest(self, payload: dict[str, Any]) -> list[str]:
        post_ids: list[str] = []
        for draft in payload.get("drafts", []):
            meta = draft.get("metadata") or {}
            cf_meta = meta.get("campaign_factory") or {}
            post_key = cf_meta.get("post_key") or draft.get("campaignFactoryPostKey")
            existing = next(
                (
                    p
                    for p in self.posts.values()
                    if p["campaign_factory_post_key"] == post_key
                ),
                None,
            )
            if existing is not None:
                post_ids.append(existing["id"])
                continue
            post_id = f"post_e2e_{len(self.posts) + 1}"
            # metadata is the REAL draft metadata (the spine). status/published_at
            # /account are the dashboard's own state, filled by publish().
            self.posts[post_id] = {
                "id": post_id,
                "user_id": draft.get("userId"),
                "status": "draft",
                "platform": "instagram",
                "media_type": "video",
                "ig_media_type": None,
                "content_surface": draft.get("contentSurface"),
                "account_id": draft.get("accountId"),
                "instagram_account_id": draft.get("instagramAccountId"),
                "created_at": "2026-01-02T00:00:00+00:00",
                "updated_at": "2026-01-02T00:00:00+00:00",
                "scheduled_for": None,
                "published_at": None,
                "permalink": None,
                "instagram_post_id": None,
                "content": draft.get("content"),
                "campaign_factory_post_key": post_key,
                "metadata": meta,
            }
            post_ids.append(post_id)
        return post_ids

    def publish(
        self,
        post_id: str,
        *,
        instagram_account_id: str,
        published_at: str,
        permalink: str,
    ) -> None:
        post = self.posts[post_id]
        post["status"] = "published"
        post["published_at"] = published_at
        post["permalink"] = permalink
        post["instagram_account_id"] = instagram_account_id

    def add_metric_history(self, post_id: str, rows: list[dict[str, Any]]) -> None:
        for idx, row in enumerate(rows):
            row.setdefault("id", f"hist_{post_id}_{idx}")
            row.setdefault("post_id", post_id)
        self.metric_history.setdefault(post_id, []).extend(rows)


def _make_fake_client(dashboard: _FakeDashboard):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url
            self.service_role_key = service_role_key

        def select(self, table: str, params: dict[str, str]):
            offset = int(params.get("offset", "0"))
            limit = int(params.get("limit", "1000"))
            if table == "posts":
                user_id = str(params.get("user_id", "")).removeprefix("eq.")
                rows = [
                    dict(p)
                    for p in dashboard.posts.values()
                    if p["user_id"] == user_id
                ]
                post_key = params.get("campaign_factory_post_key")
                if post_key is not None:
                    key = str(post_key).removeprefix("eq.")
                    rows = [
                        r for r in rows if r["campaign_factory_post_key"] == key
                    ]
                return rows[offset : offset + limit]
            if table == "post_metric_history":
                raw = str(params.get("post_id", ""))
                ids = (
                    raw.removeprefix("in.(").rstrip(")").split(",")
                    if raw.startswith("in.(")
                    else [raw.removeprefix("eq.")]
                )
                ids = [i for i in ids if i]
                rows: list[dict[str, Any]] = []
                for pid in ids:
                    rows.extend(dashboard.metric_history.get(pid, []))
                rows.sort(key=lambda r: r["snapshot_at"])
                return rows[offset : offset + limit]
            raise AssertionError(f"unexpected table {table!r}")

    return FakeClient


def _patch_remote_media(monkeypatch: pytest.MonkeyPatch, remote_url: str) -> None:
    """Stamp remote media-host URLs on the real draft payload.

    Remote media hosting is an external boundary; the established export tests
    inject it the same way so _upload_media_for_dashboard_ingest short-circuits
    and the handoff-manifest media-URL check passes.
    """
    original = threadsdash_adapter.build_draft_payloads

    def build_with_remote_media(*args, **kwargs):
        payload = original(*args, **kwargs)
        for draft in payload.get("drafts", []):
            for item in draft.get("media", []) or []:
                if isinstance(item, dict):
                    item["url"] = remote_url
            meta = draft.get("metadata", {}).get("campaign_factory", {})
            manifest = meta.get("handoff_manifest")
            if isinstance(manifest, dict):
                manifest["mediaItems"] = [{"type": "video", "url": remote_url}]
            # metadata is recomputed downstream from the draft mirror; keep the
            # top-level draft manifest in sync too.
            hm = draft.get("handoffManifest")
            if isinstance(hm, dict):
                hm["mediaItems"] = [{"type": "video", "url": remote_url}]
        return payload

    monkeypatch.setattr(
        threadsdash_adapter, "build_draft_payloads", build_with_remote_media
    )


_SUPABASE_KW = dict(
    supabase_url="https://example.supabase.co",
    supabase_service_role_key="service-role",
)
_INGEST_URL = "https://dashboard.example.com/api/campaign-factory/drafts/ingest"


def _wire_dashboard(monkeypatch: pytest.MonkeyPatch, dashboard: _FakeDashboard):
    """Patch urlopen (ingest) + SupabaseRestClient (reconcile/read) at the seam."""
    remote_url = "https://cdn.example.com/campaigns/e2e/asset.mp4"
    _patch_remote_media(monkeypatch, remote_url)
    monkeypatch.setattr(
        threadsdash_adapter, "SupabaseRestClient", _make_fake_client(dashboard)
    )
    monkeypatch.setattr(threadsdash_adapter.time, "sleep", lambda _s: None)

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return json.dumps(
                {"success": True, "postIds": self.post_ids, "writtenDrafts": len(self.post_ids)}
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        post_ids = dashboard.ingest(body)
        resp = _Resp()
        resp.post_ids = post_ids
        return resp

    monkeypatch.setattr(threadsdash_adapter, "urlopen", fake_urlopen)


def drive_real_render_and_sync(
    cf: CampaignFactory,
    tmp_path: Path,
    *,
    campaign_slug: str = "may",
    caption: str = "red or pink ?",
    prompt_id: str = "prompt_e2e_1",
    reference_id: str = "reference_e2e_1",
) -> dict[str, Any]:
    """Run the REAL stage-1..3 chain, return the synced rendered_asset row."""
    folder = tmp_path / f"inputs_{campaign_slug}"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source-e2e")
    cf.import_folder(
        folder,
        campaign_slug=campaign_slug,
        model_slug="model",
        account_handles=["ig_1"],
    )
    source = cf.assets_for_campaign(cf.campaign_by_slug(campaign_slug)["id"])[0]
    set_source_prompt(cf, source["id"], prompt_id=prompt_id, reference_id=reference_id)

    job = cf.prepare_reel_inputs(
        campaign_slug=campaign_slug, hooks=[caption], recipes=["v01_original"]
    )["prepared"][0]
    simulate_reel_render(cf, job, caption=caption)
    result = cf.sync_reel_outputs(campaign_slug=campaign_slug)
    assert len(result["synced"]) == 1, result
    asset_id = result["synced"][0]["id"] if "id" in result["synced"][0] else None
    if asset_id is None:
        asset_id = cf.dashboard(campaign_slug)["rendered"][0]["id"]
    return dict(
        cf.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    )


def export_real_asset(
    cf: CampaignFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dashboard: _FakeDashboard,
    *,
    caption: str = "red or pink ?",
    prompt_id: str = "prompt_e2e_1",
    reference_id: str = "reference_e2e_1",
) -> dict[str, Any]:
    """Drive render -> sync -> QC -> approve -> plan -> real export.

    Returns ``{asset, synced_caption_hash, synced_context, export}``.
    """
    asset = drive_real_render_and_sync(
        cf, tmp_path, caption=caption, prompt_id=prompt_id, reference_id=reference_id
    )
    synced_caption_hash = asset["caption_hash"]
    synced_context = json.loads(asset["caption_outcome_context_json"])
    add_audit_report(cf, asset["id"])
    mark_publishable_qc(cf, asset["id"])
    cf.review_rendered_asset(asset["id"], decision="approved")
    cf.create_distribution_plan(
        asset["id"],
        instagram_account_id="ig_1",
        planned_window_start="2026-01-02T10:00:00+00:00",
        planned_window_end="2026-01-02T10:30:00+00:00",
    )
    _wire_dashboard(monkeypatch, dashboard)
    export = export_threadsdash(
        cf,
        campaign_slug="may",
        user_id="user_1",
        dry_run=False,
        threadsdash_ingest_url=_INGEST_URL,
        threadsdash_ingest_secret="ingest-secret",
        **_SUPABASE_KW,
    )
    return {
        "asset": asset,
        "synced_caption_hash": synced_caption_hash,
        "synced_context": synced_context,
        "export": export,
    }


def publish_with_metrics(
    dashboard: _FakeDashboard,
    *,
    published_at: str = "2026-01-02T09:00:00+00:00",
    instagram_account_id: str = "ig_1",
) -> str:
    """Simulate the external ThreadsDashboard publishing + metric collection.

    Only the metric numbers/timestamps/publish-state are hand-built here (they
    are the external system's own data). The post's campaign_factory metadata
    -- the spine -- is the REAL exported draft metadata already stored on the
    post by the ingest.
    """
    post_id = next(iter(dashboard.posts))
    dashboard.publish(
        post_id,
        instagram_account_id=instagram_account_id,
        published_at=published_at,
        permalink=f"https://instagram.test/p/{post_id}",
    )
    dashboard.add_metric_history(
        post_id,
        [
            {
                "account_id": "acct_1",
                "platform": "instagram",
                "snapshot_at": "2026-01-02T10:00:00+00:00",
                "hours_since_publish": 1,
                "views_count": 120,
                "likes_count": 9,
                "replies_count": 1,
                "reposts_count": 0,
                "quotes_count": 0,
                "shares_count": 2,
                "saves_count": 3,
                "reach": 110,
                "engagement_rate": 0.12,
            },
            {
                "account_id": "acct_1",
                "platform": "instagram",
                "snapshot_at": "2026-01-03T09:00:00+00:00",
                "hours_since_publish": 24,
                "views_count": 1500,
                "likes_count": 95,
                "replies_count": 11,
                "reposts_count": 0,
                "quotes_count": 0,
                "shares_count": 18,
                "saves_count": 24,
                "reach": 1400,
                "engagement_rate": 0.11,
            },
        ],
    )
    return post_id


# --------------------------------------------------------------------------- #
# Seam A: sync_reel_outputs -> export_threadsdash draft (caption spine)
# --------------------------------------------------------------------------- #
def test_seam_a_sync_output_flows_into_export_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    dashboard = _FakeDashboard()
    try:
        driven = export_real_asset(cf, tmp_path, monkeypatch, dashboard)
        asset = driven["asset"]
        synced_caption_hash = driven["synced_caption_hash"]
        synced_context = driven["synced_context"]
        result = driven["export"]
        assert synced_caption_hash
        assert synced_context["caption_hash"] == synced_caption_hash

        assert result["dashboardIngest"]["attempted"] is True
        assert result["dashboardIngest"]["reconciled"] is True
        drafts = json.loads(Path(result["path"]).read_text())["payload"]["drafts"]
        assert len(drafts) == 1
        draft_meta = drafts[0]["metadata"]["campaign_factory"]
        # THE seam assertion: the exported draft's caption spine equals the
        # rendered_asset produced by sync_reel_outputs.
        assert draft_meta["caption_hash"] == synced_caption_hash
        assert (
            draft_meta["caption_outcome_context"]["caption_hash"]
            == synced_caption_hash
        )
        assert (
            draft_meta["caption_outcome_context"]["caption_text"]
            == synced_context["caption_text"]
        )
        # and a real post landed in the dashboard carrying the same spine
        assert len(dashboard.posts) == 1
        post = next(iter(dashboard.posts.values()))
        assert post["metadata"]["campaign_factory"]["caption_hash"] == synced_caption_hash
    finally:
        cf.close()


# --------------------------------------------------------------------------- #
# Seam B: export_threadsdash posts -> sync_performance_snapshots round-trip
# --------------------------------------------------------------------------- #
def test_seam_b_exported_posts_round_trip_into_performance_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    dashboard = _FakeDashboard()
    try:
        driven = export_real_asset(cf, tmp_path, monkeypatch, dashboard)
        asset = driven["asset"]
        synced_caption_hash = driven["synced_caption_hash"]
        post_id = publish_with_metrics(dashboard)

        result = sync_performance_snapshots(
            cf, campaign_slug="may", user_id="user_1", **_SUPABASE_KW
        )
        assert result["postsScanned"] == 1
        assert result["campaignFactoryPostsScanned"] == 1
        assert result["metricHistoryRowsScanned"] == 2
        assert result["inserted"] == 2

        rows = [
            dict(r)
            for r in cf.conn.execute(
                """
                SELECT post_id, rendered_asset_id, caption_hash, snapshot_at, views,
                       metrics_eligible, history_source, lineage_v2_valid
                FROM performance_snapshots ORDER BY snapshot_at
                """
            ).fetchall()
        ]
        assert len(rows) == 2
        for row in rows:
            # THE seam assertion: snapshots link back to the SAME rendered asset
            # and caption spine that sync_reel_outputs produced.
            assert row["post_id"] == post_id
            assert row["rendered_asset_id"] == asset["id"]
            assert row["caption_hash"] == synced_caption_hash
            assert row["metrics_eligible"] == 1
            assert row["history_source"] == "metric_history"
            assert row["lineage_v2_valid"] == 1
        assert [row["views"] for row in rows] == [120, 1500]
    finally:
        cf.close()


# --------------------------------------------------------------------------- #
# Seam C: performance_snapshots -> learning_fanout -> reference outcomes
# --------------------------------------------------------------------------- #
import importlib.util  # noqa: E402

from campaign_factory.learning_score import (  # noqa: E402
    account_reward_baselines,
    learning_eligible,
    snapshot_normalized_reward,
)
from reference_factory.db import connect as connect_reference_db  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE_PATH = _REPO_ROOT / "scripts" / "learning_fanout.py"


def load_bridge_module():
    spec = importlib.util.spec_from_file_location("learning_fanout", _BRIDGE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setup_reference_db(
    reference_db: Path, *, prompt_id: str, reference_id: str
) -> None:
    """Seed the reference DB with the prompt/reference the lineage points at.

    This is the reference-side upstream artifact (a generated prompt bound to a
    reference). The fanout resolves the snapshot's lineage.source.promptId to
    this row and writes the measured outcome onto it.
    """
    now = "2026-01-01T00:00:00+00:00"
    conn = connect_reference_db(reference_db)
    try:
        conn.execute(
            """
            INSERT INTO source_files (
              reference_id, path, file_name, extension, kind, size_bytes, mtime,
              path_hash, created_at, updated_at
            ) VALUES (?, ?, 'reference.mp4', '.mp4', 'video', 1, ?, ?, ?, ?)
            """,
            (
                reference_id,
                str(reference_db.parent / "reference.mp4"),
                now,
                f"path_hash_{reference_id}",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO generated_video_prompts (
              id, reference_id, target_tool, model_profile, prompt_json,
              status, created_at, updated_at
            ) VALUES (?, ?, 'higgsfield', ?, '{}', 'approved', ?, ?)
            """,
            (prompt_id, reference_id, prompt_id, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _expected_reference_reward(campaign_db: Path, module) -> dict[str, float]:
    """Recompute the reward fanout will stamp, using the exact fanout path."""
    conn = sqlite3.connect(campaign_db)
    conn.row_factory = sqlite3.Row
    try:
        snapshots = module._load_snapshots(conn, "may")
    finally:
        conn.close()
    publics = [module._public_snapshot(dict(row)) for row in snapshots]
    eligible = [
        (row, public)
        for row, public in zip(snapshots, publics)
        if learning_eligible(public)
    ]
    baselines = account_reward_baselines([public for _, public in eligible])
    latest: dict[str, dict[str, Any]] = {}
    for row, public in eligible:
        latest[str(dict(row)["post_id"])] = public
    return {
        post_id: snapshot_normalized_reward(public, baselines)
        for post_id, public in latest.items()
    }


def test_seam_c_snapshots_fan_out_to_reference_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt_id = "prompt_e2e_1"
    reference_id = "reference_e2e_1"
    cf = make_factory(tmp_path)
    dashboard = _FakeDashboard()
    campaign_db = cf.settings.db_path
    reel_root = cf.settings.reel_factory_root
    reference_db = tmp_path / "references" / "reference_factory.sqlite"
    try:
        export_real_asset(
            cf,
            tmp_path,
            monkeypatch,
            dashboard,
            prompt_id=prompt_id,
            reference_id=reference_id,
        )
        post_id = publish_with_metrics(dashboard)
        sync_performance_snapshots(
            cf, campaign_slug="may", user_id="user_1", **_SUPABASE_KW
        )
    finally:
        cf.close()

    setup_reference_db(reference_db, prompt_id=prompt_id, reference_id=reference_id)
    module = load_bridge_module()
    expected = _expected_reference_reward(campaign_db, module)
    assert post_id in expected

    first = module.fanout_learning_snapshots(
        campaign_factory_db=campaign_db,
        reel_factory_root=reel_root,
        reference_factory_db=reference_db,
        campaign="may",
    )
    assert first["fanout"]["reference"]["done"] >= 1

    ref_conn = connect_reference_db(reference_db)
    try:
        outcome = ref_conn.execute(
            "SELECT prompt_id, post_id, reward_score FROM prompt_post_outcomes"
        ).fetchone()
        assert outcome is not None
        assert outcome["prompt_id"] == prompt_id
        assert outcome["post_id"] == post_id
        assert outcome["reward_score"] == pytest.approx(expected[post_id])
        prompt_reward = ref_conn.execute(
            "SELECT outcome_reward_score, outcome_sample_count FROM generated_video_prompts WHERE id = ?",
            (prompt_id,),
        ).fetchone()
        assert prompt_reward["outcome_reward_score"] == pytest.approx(expected[post_id])
    finally:
        ref_conn.close()

    # Idempotency: a second fanout run is a no-op.
    second = module.fanout_learning_snapshots(
        campaign_factory_db=campaign_db,
        reel_factory_root=reel_root,
        reference_factory_db=reference_db,
        campaign="may",
    )
    assert second["fanout"]["reference"]["done"] == 0
    assert second["fanout"]["campaign"]["done"] == 0
    assert second["fanout"]["reel"]["done"] == 0


# --------------------------------------------------------------------------- #
# Seam D: reference learning bank -> import_reference_bank -> recommend_next_batch
#
# NOTE ON THE STAGE MAP: the audit brief named reference_factory.patterns
# export_patterns as the producer feeding import_reference_bank. In the code as
# it stands those two do NOT compose: export_patterns emits the
# `reference_factory.pattern_cards.v1` schema (a `cards` array), while
# import_reference_bank strictly requires a `campaign_reference_bank.v1` bank (a
# `clusters` array). The REAL producer of the bank that import_reference_bank
# consumes -- and the one that folds the measured prompt outcomes into the
# clusters that get ranked -- is reference_factory.learning.build_learning_system
# (_write_learning_outputs -> campaign_reference_bank.json). This test drives
# that real producer->consumer pair. Reported as a stage-map correction, not a
# skip, because the seam IS drivable end-to-end without live services.
# --------------------------------------------------------------------------- #
from reference_factory.learning import build_learning_system  # noqa: E402


def seed_reference_pattern(reference_db: Path, *, reference_id: str) -> str:
    """Seed the analyzed reference_pattern row (upstream analyzer artifact).

    build_learning_system reads reference_patterns; the fanout's
    refresh_measured_outcomes_for_references folds the measured reward onto the
    row bound to this reference_id.
    """
    cluster_key = "caption_led_visual::question_hook::question_hook"
    pattern_json = {
        "visualFormat": "caption_led_visual",
        "hookType": "question_hook",
        "captionArchetype": "question_hook",
        "captionFormulas": [
            {"formula": "{q}?", "exampleCaptions": ["red or pink ?"]}
        ],
        "metrics": {},
        "higgsfieldJsonTemplate": {"scene": "caption-led vertical reel"},
        "promptTemplate": {"captionBrief": "short direct question"},
        "topExamples": [
            {
                "referenceId": reference_id,
                "localPath": str(reference_db.parent / "reference.mp4"),
            }
        ],
    }
    now = "2026-01-01T00:00:00+00:00"
    conn = connect_reference_db(reference_db)
    try:
        conn.execute(
            """
            INSERT INTO reference_patterns (
              id, reference_id, public_post_id, rank, provider, model,
              analyzer_version, suggested_label, visual_format, hook_type,
              caption_archetype, quality_score, pattern_json, created_at, updated_at
            ) VALUES ('refpat_e2e', ?, NULL, 1, 'auto', 'model', 'v1', 'gold',
                      'caption_led_visual', 'question_hook', 'question_hook', 80, ?, ?, ?)
            """,
            (reference_id, json.dumps(pattern_json), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return cluster_key


def run_chain_through_fanout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """Render -> sync -> export -> metrics -> sync_perf -> fanout (all real).

    Seeds the reference prompt/reference/pattern first so the fanout's measured
    outcome lands on a real reference pattern. Returns everything the bank
    export + recommend hop needs, plus the caption/lineage spine values.
    """
    prompt_id = "prompt_e2e_1"
    reference_id = "reference_e2e_1"
    cf = make_factory(tmp_path)
    dashboard = _FakeDashboard()
    campaign_db = cf.settings.db_path
    reel_root = cf.settings.reel_factory_root
    reference_db = tmp_path / "references" / "reference_factory.sqlite"
    try:
        driven = export_real_asset(
            cf,
            tmp_path,
            monkeypatch,
            dashboard,
            prompt_id=prompt_id,
            reference_id=reference_id,
        )
        drafts = json.loads(Path(driven["export"]["path"]).read_text())["payload"][
            "drafts"
        ]
        export_meta = drafts[0]["metadata"]["campaign_factory"]
        export_caption_hash = export_meta["caption_hash"]
        export_lineage_prompt_id = (
            (export_meta.get("generated_asset_lineage") or {}).get("source") or {}
        ).get("promptId")
        post_id = publish_with_metrics(dashboard)
        sync_performance_snapshots(
            cf, campaign_slug="may", user_id="user_1", **_SUPABASE_KW
        )
        snapshot_caption_hash = cf.conn.execute(
            "SELECT caption_hash FROM performance_snapshots LIMIT 1"
        ).fetchone()[0]
    finally:
        cf.close()

    setup_reference_db(reference_db, prompt_id=prompt_id, reference_id=reference_id)
    cluster_key = seed_reference_pattern(reference_db, reference_id=reference_id)
    module = load_bridge_module()
    module.fanout_learning_snapshots(
        campaign_factory_db=campaign_db,
        reel_factory_root=reel_root,
        reference_factory_db=reference_db,
        campaign="may",
    )
    return {
        "campaign_db": campaign_db,
        "reel_root": reel_root,
        "reference_db": reference_db,
        "tmp_path": tmp_path,
        "post_id": post_id,
        "prompt_id": prompt_id,
        "reference_id": reference_id,
        "cluster_key": cluster_key,
        "synced_caption_hash": driven["synced_caption_hash"],
        "export_caption_hash": export_caption_hash,
        "export_lineage_prompt_id": export_lineage_prompt_id,
        "snapshot_caption_hash": snapshot_caption_hash,
    }


def _reopen_factory(chain: dict[str, Any]) -> CampaignFactory:
    tmp_path = chain["tmp_path"]
    return CampaignFactory(
        Settings(
            root=tmp_path,
            db_path=chain["campaign_db"],
            reel_factory_root=chain["reel_root"],
            contentforge_root=tmp_path / "contentforge",
            threadsdash_root=tmp_path / "ThreadsDashboard",
            campaigns_dir=tmp_path / "campaigns",
        )
    )


def test_seam_d_reference_bank_imports_and_ranks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = run_chain_through_fanout(tmp_path, monkeypatch)
    reference_db = chain["reference_db"]
    cluster_key = chain["cluster_key"]

    # The fanout stamped a measured outcome onto the reference pattern.
    ref_conn = connect_reference_db(reference_db)
    try:
        pattern_json = json.loads(
            ref_conn.execute(
                "SELECT pattern_json FROM reference_patterns WHERE id = 'refpat_e2e'"
            ).fetchone()[0]
        )
    finally:
        ref_conn.close()
    measured = (pattern_json.get("metrics") or {}).get("measuredOutcome")
    assert measured and measured.get("sampleCount", 0) >= 1

    # REAL reference-side bank export (the producer import_reference_bank reads).
    learning_dir = reference_db.parent / "learning"
    ref_conn = connect_reference_db(reference_db)
    try:
        export = build_learning_system(
            ref_conn, limit=10, output_dir=learning_dir, embedding_clusters=False
        )
    finally:
        ref_conn.close()
    bank_path = Path(export["campaignReferenceBankPath"])
    bank = json.loads(bank_path.read_text())
    assert bank["schema"] == "reference_factory.campaign_reference_bank.v1"
    assert any(c["clusterKey"] == cluster_key for c in bank["clusters"])

    cf = _reopen_factory(chain)
    try:
        imported = cf.import_reference_bank(bank_path)
        assert imported["patternsImported"] >= 1
        cluster_keys = {
            p["clusterKey"] for p in cf.reference_patterns()["patterns"]
        }
        assert cluster_key in cluster_keys

        recommendation = cf.recommend_next_batch("may", count=3)
        # THE seam assertion: recommend_next_batch surfaces the imported pattern
        # (populated only via import_reference_bank, no raw reference_patterns SQL).
        selected_keys = {
            (item.get("referencePattern") or {}).get("clusterKey")
            for item in recommendation["items"]
        }
        assert cluster_key in selected_keys
    finally:
        cf.close()


# --------------------------------------------------------------------------- #
# Seam E: full chain, spine identical at every hop
# --------------------------------------------------------------------------- #
def test_seam_e_full_chain_spine_is_identical_at_every_hop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = run_chain_through_fanout(tmp_path, monkeypatch)
    prompt_id = chain["prompt_id"]
    post_id = chain["post_id"]
    cluster_key = chain["cluster_key"]

    # --- caption_hash spine: rendered -> export draft -> performance snapshot ---
    caption_hash = chain["synced_caption_hash"]
    assert caption_hash
    assert chain["export_caption_hash"] == caption_hash
    assert chain["snapshot_caption_hash"] == caption_hash

    # --- lineage/promptId spine: source_prompt -> export lineage -> reference outcome ---
    assert chain["export_lineage_prompt_id"] == prompt_id
    ref_conn = connect_reference_db(chain["reference_db"])
    try:
        outcome = ref_conn.execute(
            "SELECT prompt_id, post_id FROM prompt_post_outcomes"
        ).fetchone()
        assert outcome["prompt_id"] == prompt_id
        assert outcome["post_id"] == post_id
    finally:
        ref_conn.close()

    # --- reference bank export -> import -> recommend surfaces the same pattern ---
    learning_dir = chain["reference_db"].parent / "learning"
    ref_conn = connect_reference_db(chain["reference_db"])
    try:
        export = build_learning_system(
            ref_conn, limit=10, output_dir=learning_dir, embedding_clusters=False
        )
    finally:
        ref_conn.close()
    bank_path = Path(export["campaignReferenceBankPath"])
    assert any(
        c["clusterKey"] == cluster_key
        for c in json.loads(bank_path.read_text())["clusters"]
    )

    cf = _reopen_factory(chain)
    try:
        # caption_hash is still the same on the persisted rendered asset + snapshot
        rendered_caption_hash = cf.conn.execute(
            "SELECT caption_hash FROM rendered_assets LIMIT 1"
        ).fetchone()[0]
        snapshot_caption_hash = cf.conn.execute(
            "SELECT caption_hash FROM performance_snapshots LIMIT 1"
        ).fetchone()[0]
        assert rendered_caption_hash == caption_hash
        assert snapshot_caption_hash == caption_hash

        cf.import_reference_bank(bank_path)
        recommendation = cf.recommend_next_batch("may", count=3)
        selected_keys = {
            (item.get("referencePattern") or {}).get("clusterKey")
            for item in recommendation["items"]
        }
        assert cluster_key in selected_keys
    finally:
        cf.close()
