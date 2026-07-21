from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from campaign_asset_test_support import (
    add_audit_report,
    add_inventory_parent_fixture,
    add_surface_asset_fixture,
    ensure_exportable_distribution_plan,
    write_surface_image,
)
from campaign_factory.adapters import (
    threadsdash_account_projection as threadsdash_accounts_adapter,
)
from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.adapters import (
    threadsdash_draft_delivery as threadsdash_delivery_adapter,
)
from campaign_factory.adapters import (
    threadsdash_draft_payload as threadsdash_payload_adapter,
)
from campaign_factory.adapters import (
    threadsdash_metrics_ingestion as threadsdash_metrics_adapter,
)
from campaign_factory.adapters.threadsdash_account_projection import (
    summarize_threadsdash_usage,
)
from campaign_factory.adapters.threadsdash_draft_delivery import export_threadsdash
from campaign_factory.adapters.threadsdash_draft_payload import build_draft_payloads
from campaign_factory.adapters.threadsdash_draft_readiness import (
    evaluate_export_readiness,
    preflight_supabase,
    verify_threadsdash_export,
)
from campaign_factory.adapters.threadsdash_metrics_ingestion import (
    sync_performance_snapshots,
)
from campaign_factory.contracts import validate_threadsdash_draft_payload_strict
from campaign_factory.distribution import _normalize_schedule_mode
from campaign_learning_test_support import (
    _approve_asset_for_lifecycle,
    _draft_item,
    _lifecycle_state,
    _manager_report_fixture,
    _slice_rows,
    _threadsdash_lifecycle_post,
    threadsdash_campaign_factory_metadata,
)
from campaign_test_support import (
    add_rendered_asset,
    make_factory,
    set_test_source_prompt,
)


def test_global_kill_switch_blocks_outbound_threadsdash_draft_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREATOR_OS_KILL_SWITCH", "yes")
    with pytest.raises(
        PermissionError, match="ThreadsDashboard draft export blocked.*KILL_SWITCH"
    ):
        export_threadsdash(  # type: ignore[arg-type]
            None,
            campaign_slug="stacey_learning_cohort_v1",
            user_id="operator",
            dry_run=False,
        )


def test_threadsdash_export_uses_dashboard_ingest_by_default(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    captured: dict[str, Any] = {}
    monkeypatch.setenv("THREADSDASH_ALLOWED_INGEST_HOSTS", "dashboard.example.com")
    remote_url = "https://cdn.example.com/campaigns/may/asset_1.mp4"

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"success": True, "postIds": ["post_ingest_1"], "writtenDrafts": 1}
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = {
            key.lower(): value for key, value in request.header_items()
        }
        captured["timeout"] = timeout
        captured["raw_body"] = request.data
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url
            self.service_role_key = service_role_key

        def select(self, table, params):
            assert table == "posts"
            return [
                {
                    "id": "post_ingest_1",
                    "user_id": "user_1",
                    "status": "draft",
                    "campaign_factory_post_key": params[
                        "campaign_factory_post_key"
                    ].removeprefix("eq."),
                    "metadata": {"campaign_factory": {}},
                }
            ]

    monkeypatch.setattr(
        threadsdash_client_adapter, "_open_threadsdash_ingest_request", fake_urlopen
    )
    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    original_build_draft_payloads = threadsdash_payload_adapter.build_draft_payloads

    def build_payloads_with_remote_media(*args, **kwargs):
        payload = original_build_draft_payloads(*args, **kwargs)
        for draft in payload.get("drafts", []):
            for item in draft.get("media", []) or []:
                if isinstance(item, dict):
                    item["url"] = remote_url
            meta = draft.get("metadata", {}).get("campaign_factory", {})
            manifest = meta.get("handoff_manifest")
            if isinstance(manifest, dict):
                manifest["mediaItems"] = [{"type": "video", "url": remote_url}]
        return payload

    monkeypatch.setattr(
        threadsdash_payload_adapter,
        "build_draft_payloads",
        build_payloads_with_remote_media,
    )
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "new post is up",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": False,
                            "status": "not_required",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
        ensure_exportable_distribution_plan(cf)
        result = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="user_1",
            dry_run=False,
            threadsdash_ingest_url="https://dashboard.example.com/api/campaign-factory/drafts/ingest",
            threadsdash_ingest_secret="ingest-secret",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        assert result["dashboardIngest"]["attempted"] is True
        assert result["dashboardIngest"]["postIds"] == ["post_ingest_1"]
        assert result["dashboardIngest"]["reconciled"] is True
        assert result["supabase"]["attempted"] is False
        assert result["supabase"]["disabled"] is True
        assert captured["url"].endswith("/api/campaign-factory/drafts/ingest")
        assert "x-campaign-factory-ingest-secret" not in captured["headers"]
        timestamp = captured["headers"]["x-campaign-factory-timestamp"]
        nonce = captured["headers"]["x-campaign-factory-nonce"]
        assert captured["headers"]["x-campaign-factory-signature"] == (
            threadsdash_client_adapter._threadsdash_ingest_signature(
                captured["raw_body"],
                secret="ingest-secret",
                timestamp=timestamp,
                nonce=nonce,
            )
        )
        assert (
            captured["headers"]["x-idempotency-key"]
            == captured["body"]["drafts"][0]["metadata"]["campaign_factory"]["post_key"]
        )
        assert captured["body"]["dryRun"] is False
        assert captured["body"]["drafts"][0]["instagramPostCaption"]
        assert captured["body"]["drafts"][0]["media"][0]["url"] == remote_url
    finally:
        cf.close()


def test_threadsdash_export_empty_dashboard_post_ids_fail_not_exported(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv("THREADSDASH_ALLOWED_INGEST_HOSTS", "dashboard.example.com")
    remote_url = "https://cdn.example.com/campaigns/may/asset_1.mp4"

    class EmptyPostIdsResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"success": True, "postIds": [], "writtenDrafts": 0}
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append(
            {
                "headers": {
                    key.lower(): value for key, value in request.header_items()
                },
                "timeout": timeout,
                "body": json.loads(request.data.decode("utf-8")),
            }
        )
        return EmptyPostIdsResponse()

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url
            self.service_role_key = service_role_key

        def select(self, table, params):
            assert table == "posts"
            return []

    monkeypatch.setattr(
        threadsdash_client_adapter, "_open_threadsdash_ingest_request", fake_urlopen
    )
    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    monkeypatch.setattr(threadsdash_client_adapter.time, "sleep", lambda _seconds: None)
    original_build_draft_payloads = threadsdash_payload_adapter.build_draft_payloads

    def build_payloads_with_remote_media(*args, **kwargs):
        payload = original_build_draft_payloads(*args, **kwargs)
        for draft in payload.get("drafts", []):
            for item in draft.get("media", []) or []:
                if isinstance(item, dict):
                    item["url"] = remote_url
            meta = draft.get("metadata", {}).get("campaign_factory", {})
            manifest = meta.get("handoff_manifest")
            if isinstance(manifest, dict):
                manifest["mediaItems"] = [{"type": "video", "url": remote_url}]
        return payload

    monkeypatch.setattr(
        threadsdash_payload_adapter,
        "build_draft_payloads",
        build_payloads_with_remote_media,
    )
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "new post is up",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": False,
                            "status": "not_required",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
        ensure_exportable_distribution_plan(cf)

        with pytest.raises(
            ValueError, match="Dashboard draft ingest reconciliation failed"
        ):
            export_threadsdash(
                cf,
                campaign_slug="may",
                user_id="user_1",
                dry_run=False,
                threadsdash_ingest_url="https://dashboard.example.com/api/campaign-factory/drafts/ingest",
                threadsdash_ingest_secret="ingest-secret",
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="service-role",
            )

        assert len(calls) == threadsdash_client_adapter.DASHBOARD_INGEST_MAX_ATTEMPTS
        assert len(
            {call["headers"]["x-campaign-factory-nonce"] for call in calls}
        ) == len(calls)
        assert all(
            "x-campaign-factory-ingest-secret" not in call["headers"] for call in calls
        )
        export_row = cf.conn.execute(
            "SELECT status FROM threadsdash_exports"
        ).fetchone()
        assert export_row["status"] == "failed"
        failed_events = [
            event
            for event in cf.domains.events.events_for_campaign("may")
            if event["eventType"] == "threadsdash_export_created"
            and event["status"] == "failure"
        ]
        assert failed_events
    finally:
        cf.close()


def test_threadsdash_dashboard_ingest_rejects_unallowed_url_before_request(monkeypatch):
    calls = 0

    def fake_urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("urlopen should not be called for an unsafe ingest URL")

    monkeypatch.setattr(
        threadsdash_client_adapter, "_open_threadsdash_ingest_request", fake_urlopen
    )

    with pytest.raises(ValueError, match="private or reserved IP"):
        threadsdash_delivery_adapter._post_threadsdash_draft_ingest(
            {"drafts": []},
            ingest_url="https://169.254.169.254/api/campaign-factory/drafts/ingest",
            ingest_secret="ingest-secret",
        )

    assert calls == 0


def test_threadsdash_dashboard_ingest_requires_expected_ingest_path(monkeypatch):
    monkeypatch.setenv("THREADSDASH_ALLOWED_INGEST_HOSTS", "dashboard.example.com")

    with pytest.raises(ValueError, match="/api/campaign-factory/drafts/ingest"):
        threadsdash_delivery_adapter._post_threadsdash_draft_ingest(
            {"drafts": []},
            ingest_url="https://dashboard.example.com/api/internal/proxy",
            ingest_secret="ingest-secret",
        )


def test_threadsdash_ingest_hmac_is_bound_to_body_timestamp_and_nonce() -> None:
    body = b'{"dryRun":false,"drafts":[]}'
    assert (
        threadsdash_client_adapter._threadsdash_ingest_signature(
            body,
            secret="current-secret",
            timestamp="1783675000",
            nonce="nonce_1234567890",
        )
        == "v1=622cfc0c74fb7c5fa11878402496c28f671ef2b291d0cef5584e767c24d92e60"
    )
    signature = threadsdash_client_adapter._threadsdash_ingest_signature(
        body,
        secret="ingest-secret",
        timestamp="1783675000",
        nonce="nonce_1234567890",
    )

    assert signature.startswith("v1=")
    assert len(signature) == 67
    assert signature != threadsdash_client_adapter._threadsdash_ingest_signature(
        body + b" ",
        secret="ingest-secret",
        timestamp="1783675000",
        nonce="nonce_1234567890",
    )
    assert signature != threadsdash_client_adapter._threadsdash_ingest_signature(
        body,
        secret="ingest-secret",
        timestamp="1783675001",
        nonce="nonce_1234567890",
    )
    assert signature != threadsdash_client_adapter._threadsdash_ingest_signature(
        body,
        secret="ingest-secret",
        timestamp="1783675000",
        nonce="nonce_0987654321",
    )


def test_threadsdash_ingest_redirect_handler_never_forwards_authenticated_request():
    request = threadsdash_client_adapter.Request(
        "https://dashboard.example.com/api/campaign-factory/drafts/ingest",
        data=b"{}",
        method="POST",
        headers={"X-Campaign-Factory-Signature": "v1=" + "a" * 64},
    )
    handler = threadsdash_client_adapter._RejectDashboardIngestRedirects()

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {"Location": "https://evil.example/steal"},
        "https://evil.example/steal",
    )

    assert redirected is None


def test_threadsdash_export_blocks_unresolved_dashboard_media_before_post(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    calls: list[dict[str, Any]] = []

    def fake_urlopen(request, timeout):
        calls.append({"url": request.full_url, "timeout": timeout})
        if "/api/campaign-factory/drafts/ingest" in request.full_url:
            raise AssertionError(
                "dashboard ingest should not be called for unresolved media"
            )
        raise OSError("supabase unavailable in unresolved-media regression")

    monkeypatch.setattr(threadsdash_client_adapter, "urlopen", fake_urlopen)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "new post is up",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": False,
                            "status": "not_required",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
        ensure_exportable_distribution_plan(cf)

        with pytest.raises(
            ValueError,
            match="export blocked by handoff manifest: asset_1:media_item_0_remote_url_missing",
        ):
            export_threadsdash(
                cf,
                campaign_slug="may",
                user_id="user_1",
                dry_run=False,
                threadsdash_ingest_url="https://dashboard.example.com/api/campaign-factory/drafts/ingest",
                threadsdash_ingest_secret="ingest-secret",
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="service-role",
            )

        assert not any(
            "/api/campaign-factory/drafts/ingest" in call["url"] for call in calls
        )
        export_row = cf.conn.execute(
            "SELECT status FROM threadsdash_exports"
        ).fetchone()
        assert export_row["status"] == "failed"
    finally:
        cf.close()


def test_threadsdash_draft_notify_defers_required_native_audio_without_unlocking_publish(
    tmp_path: Path, monkeypatch
):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "new post",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": True,
                            "status": "recommended",
                            "platform": "instagram",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )

        payload = build_draft_payloads(
            cf,
            campaign_slug="may",
            user_id="user_1",
            schedule_mode="draft",
            publish_mode="notify",
        )
        draft = payload["drafts"][0]
        metadata = draft["metadata"]["campaign_factory"]
        manifest = metadata["handoff_manifest"]

        assert metadata["asset_state"] == "exportable"
        assert metadata["publishability_failure_reasons"] == ["missing_audio"]
        assert metadata["audio_intent"]["gates"] == {
            "allow_draft_export": True,
            "allow_preview_schedule": False,
            "allow_live_schedule": False,
            "allow_publish": False,
        }
        assert manifest["manifest_version"] == 2
        assert manifest["audio_id"] == "deferred_to_notify_handoff"
        assert manifest["audioDeferredToHandoff"] is True
        assert manifest["surfaceReadiness"] == {
            "canHandoff": True,
            "scheduleSafe": False,
            "blockingReasons": ["missing_audio"],
        }
        validate_threadsdash_draft_payload_strict(payload)

        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
            schedule_mode="draft",
            publish_mode="notify",
        )

        assert not any(
            "campaign_audio_unresolved" in reason
            or reason.endswith("publishability:missing_audio")
            for reason in readiness["blockingReasons"]
        )
        assert any(
            reason.endswith("native_audio_deferred_to_notify_handoff")
            for reason in readiness["warnings"]
        )
    finally:
        cf.close()


def test_export_readiness_blocks_invalid_draft_contract(tmp_path: Path, monkeypatch):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    original_build_draft_payloads = threadsdash_payload_adapter.build_draft_payloads

    def invalid_payload(*args, **kwargs):
        payload = original_build_draft_payloads(*args, **kwargs)
        campaign_meta = payload["drafts"][0]["metadata"]["campaign_factory"]
        campaign_meta.pop("generated_asset_lineage", None)
        return payload

    monkeypatch.setattr(
        threadsdash_payload_adapter, "build_draft_payloads", invalid_payload
    )
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)

        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        assert readiness["liveExportAllowed"] is False
        assert any(
            "draft_payload_contract_invalid" in reason
            for reason in readiness["blockingReasons"]
        )
        assert any(
            "draft_payload_contract_invalid" in reason
            for reason in readiness["assets"][0]["blockingReasons"]
        )
    finally:
        cf.close()


def test_audio_segment_and_cover_frame_export_as_campaign_owned_instructions(
    tmp_path: Path, monkeypatch
):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "new post",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": True,
                            "status": "needs_operator_selection",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
        cf.domains.audio_operations.attach_cover_frame_to_rendered_asset(
            "asset_1",
            seconds=1.4,
            cover_image_path="/tmp/stacey-cover.jpg",
            cover_image_url="https://cdn.example.com/stacey-cover.jpg",
            cover_image_hash="cover_hash_1",
            reason="best face and outfit framing",
        )
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_stacey_1"
        )

        cf.domains.audio_operations.attach_audio_to_distribution_plan(
            plan["id"],
            track_id="ig_audio_123",
            track_name="Proof track",
            source="manual",
            selected_reason="operator selected different song section",
            segment_start_seconds=18.5,
            segment_duration_seconds=6.0,
            segment_label="hook section",
            segment_reason="use a different part of the same song",
            operator="tester",
        )

        payload = build_draft_payloads(
            cf, campaign_slug="may", user_id="user_1", schedule_mode="live"
        )
        campaign_meta = payload["drafts"][0]["metadata"]["campaign_factory"]
        manifest = campaign_meta["handoff_manifest"]

        assert campaign_meta["audio_segment"] == {
            "start_seconds": 18.5,
            "duration_seconds": 6.0,
            "label": "hook section",
            "reason": "use a different part of the same song",
        }
        assert manifest["audio_segment"] == campaign_meta["audio_segment"]
        assert campaign_meta["cover_frame"] == {
            "seconds": 1.4,
            "image_path": "/tmp/stacey-cover.jpg",
            "image_url": "https://cdn.example.com/stacey-cover.jpg",
            "image_hash": "cover_hash_1",
            "reason": "best face and outfit framing",
        }
        assert manifest["cover_frame"] == campaign_meta["cover_frame"]
        assert (
            payload["drafts"][0]["media"][0]["thumbnailUrl"]
            == "https://cdn.example.com/stacey-cover.jpg"
        )
        assert (
            payload["drafts"][0]["metadata"]["coverUrl"]
            == "https://cdn.example.com/stacey-cover.jpg"
        )
        assert payload["drafts"][0]["metadata"]["thumbOffset"] == 1.4
    finally:
        cf.close()


def test_export_readiness_blocks_missing_audit_rejected_failed_and_published(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return rows

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        rows.append(
            {
                "id": "post_1",
                "status": "published",
                "platform": "instagram",
                "media_type": "reel",
                "ig_media_type": "REELS",
                "content_surface": "reel",
                "account_id": None,
                "instagram_account_id": None,
                "created_at": "2026-01-03T00:00:00+00:00",
                "metadata": {
                    "campaign_factory": {
                        "campaign_id": "may",
                        "source_asset_id": source["id"],
                        "rendered_asset_id": "asset_1",
                        "content_hash": "hash_1",
                        "source_content_hash": source["content_hash"],
                        "caption_hash": "caption_hash_1",
                    }
                },
            }
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'"
        )
        cf.conn.commit()
        add_audit_report(
            cf, failed=["forensics"], overall_verdict="fail", upload_ready=False
        )
        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        assert readiness["liveExportAllowed"] is False
        row = readiness["assets"][0]
        assert "upload_readiness:forensics" in row["blockingReasons"]
        assert "contentforge_verdict:fail" in row["blockingReasons"]
        assert "exact_render_published" in row["blockingReasons"]
        assert any(
            reason.endswith("exact_render_published")
            for reason in readiness["blockingReasons"]
        )

        cf.domains.finished_video.review_rendered_asset("asset_1", decision="rejected")
        rejected = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        assert rejected["expectedDraftCount"] == 0
        assert "no_approved_assets" in rejected["blockingReasons"]
    finally:
        cf.close()


def test_export_readiness_warns_on_already_drafted_render(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return rows

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        rows.append(
            {
                "id": "post_1",
                "status": "draft",
                "platform": "instagram",
                "account_id": None,
                "instagram_account_id": None,
                "created_at": "2026-01-03T00:00:00+00:00",
                "content": "caption",
                "metadata": {
                    "campaign_factory": {
                        "campaign_id": "may",
                        "source_asset_id": source["id"],
                        "rendered_asset_id": "asset_1",
                        "content_hash": "hash_1",
                        "source_content_hash": source["content_hash"],
                        "caption_hash": "caption_hash_1",
                    }
                },
            }
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'"
        )
        cf.conn.commit()
        add_audit_report(cf, overall_verdict="warn", warnings=["compression"])
        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        assert readiness["liveExportAllowed"] is True
        row = readiness["assets"][0]
        assert row["state"] == "warning"
        assert "exact_render_already_queued" in row["warnings"]
        assert "contentforge_verdict:warn" in row["warnings"]
        assert "caption_reuse" in row["warnings"]
    finally:
        cf.close()


def test_export_readiness_warns_on_batch_calendar_guardrails(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, first_path = add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        for idx in (2, 3):
            rendered_path = tmp_path / f"ok_{idx}.mp4"
            rendered_path.write_bytes(f"rendered {idx}".encode())
            now = "2026-01-01T00:00:00+00:00"
            cf.conn.execute(
                """
                INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'caption', 'v01_original', 'approved_candidate', 'approved', ?, ?)
                """,
                (
                    f"asset_{idx}",
                    source["campaign_id"],
                    source["id"],
                    f"hash_{idx}",
                    str(rendered_path),
                    str(rendered_path),
                    rendered_path.name,
                    now,
                    now,
                ),
            )
            cf.conn.commit()
            add_audit_report(
                cf, rendered_asset_id=f"asset_{idx}", audit_id=f"audit_{idx}"
            )
        readiness = evaluate_export_readiness(cf, campaign_slug="may", user_id="user_1")
        warnings = {
            warning for row in readiness["assets"] for warning in row["warnings"]
        }
        assert "account_batch_volume_review" in warnings
        assert "same_caption_in_batch" in warnings
        assert "source_family_batch_volume_review" in warnings
        assert all(isinstance(row["operatorScore"], int) for row in readiness["assets"])
    finally:
        cf.close()


def test_live_export_blocks_same_rendered_asset_to_same_account_batch(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return rows

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        cf.domains.distribution.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_lola_1",
            planned_window_start="2026-06-05T10:00:00+00:00",
            reason_code="proof_slot_1",
        )
        cf.domains.distribution.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_lola_1",
            planned_window_start="2026-06-06T10:00:00+00:00",
            reason_code="proof_slot_2",
        )

        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
            schedule_mode="live",
        )

        assert readiness["liveExportAllowed"] is False
        assert readiness["expectedDraftCount"] == 2
        assert (
            "asset_1:same_rendered_asset_in_account_batch"
            in readiness["blockingReasons"]
        )
    finally:
        cf.close()


def test_threadsdash_export_preserves_existing_caption_outcome_context_nulls(
    tmp_path: Path,
):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="stacey", account_handles=["ig_a"]
        )
        source = cf.domains.asset_import.assets_for_campaign(
            cf.domains.campaign_by_slug("may")["id"]
        )[0]
        set_test_source_prompt(cf, source["id"])
        rendered_path = tmp_path / "ok.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": "caption_hash_1",
            "caption_text": "caption",
            "caption_bank": "shared_girl_next_door",
            "caption_banks": ["shared_girl_next_door"],
            "creator_mix": "Stacey",
            "creator_model": None,
            "frame_type": "closeup",
            "length_class": "short",
            "format_class": "singleline",
            "caption_fit_version": "v1",
            "suitability_decision": "allowed",
            "suitability_reason": "test",
            "render_recipe": "v01_original",
            "source_clip": "clip_001",
            "rendered_output": str(rendered_path),
        }
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
             caption, recipe, audit_status, review_state, caption_generation_json,
             caption_hash, caption_outcome_context_json, created_at, updated_at)
            VALUES ('asset_1', ?, ?, 'hash_1', ?, ?, 'ok.mp4',
             'caption', 'v01_original', 'approved_candidate', 'approved', '{}',
             'caption_hash_1', ?, ?, ?)
            """,
            (
                source["campaign_id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
                json.dumps(context, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        cf.conn.commit()

        payload = build_draft_payloads(
            cf, campaign_slug="may", user_id="user_1", rendered_asset_ids=["asset_1"]
        )
        exported_context = payload["drafts"][0]["captionOutcomeContext"]
        metadata_context = payload["drafts"][0]["metadata"]["campaign_factory"][
            "captionOutcomeContext"
        ]
        for key, value in context.items():
            assert exported_context[key] == value
            assert metadata_context[key] == value
        assert exported_context["overlaySemanticQc"]["passed"] is True
        assert (
            metadata_context["overlaySemanticQc"]
            == exported_context["overlaySemanticQc"]
        )
        assert (
            exported_context["overlay_semantic_qc"]
            == exported_context["overlaySemanticQc"]
        )
        assert exported_context["creator_model"] is None
    finally:
        cf.close()


def test_threadsdash_audio_live_gate_accepts_embedded_licensed_audio():
    assert (
        threadsdash_payload_adapter._audio_intent_allows_live(
            {
                "schema": "pipeline.audio_intent.v1",
                "mode": "licensed_music",
                "required": True,
                "status": "attached",
                "operator_selection": {
                    "audio_id": "embedded_audio_1",
                    "source": "local_audio",
                    "selection_source": "embedded_licensed_audio",
                    "selected_at": "2026-06-22T00:00:00+00:00",
                    "attached_at": "2026-06-22T00:00:00+00:00",
                },
            }
        )
        is True
    )


def test_surface_handoff_readiness_blocks_discoverability_unsafe_feed_caption(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_feed_unsafe_caption",
            content_surface="feed_single",
            media_type="image",
            instagram_post_caption="link in bio",
        )

        report = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey",
            rendered_asset_id="asset_feed_unsafe_caption",
        )

        assert report["assets"][0]["canHandoff"] is False
        assert report["assets"][0]["discoverabilitySafe"] is False
        assert "discoverability_safety_failed" in report["assets"][0]["blockingReasons"]
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_handoff_readiness_blocks_unavailable_visual_qc_and_identity(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        asset = add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_missing_trust",
            content_surface="feed_single",
            media_type="image",
            instagram_post_caption="new post",
        )
        caption_context = json.loads(asset["caption_outcome_context_json"])
        caption_context["visualQcStatus"] = "unavailable"
        caption_context["identityVerificationStatus"] = "failed"
        caption_context["visualQc"] = {"status": "unavailable"}
        caption_context["identityVerification"] = {"status": "failed"}
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ? WHERE id = ?",
            (
                json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
                asset["id"],
            ),
        )
        cf.conn.commit()

        report = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey", rendered_asset_id=asset["id"]
        )
        readiness = report["assets"][0]

        assert readiness["canHandoff"] is False
        assert readiness["visualQcStatus"] == "unavailable"
        assert readiness["identityVerificationStatus"] == "failed"
        assert "visual_qc_unavailable" in readiness["blockingReasons"]
        assert "identity_verification_failed" in readiness["blockingReasons"]
        assert readiness["handoffManifestV2"] is None
    finally:
        cf.close()


def test_surface_handoff_readiness_validates_surfaces_differently(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(
            cf,
            tmp_path,
            asset_id="asset_reel_ready",
            campaign_slug="stacey_surface_inventory_20260606",
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET content_surface = 'reel', media_type = 'video' WHERE id = 'asset_reel_ready'"
        )
        cf.domains.distribution.create_distribution_plan(
            "asset_reel_ready", surface="reel", instagram_account_id="ig_stacey_1"
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_ready",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_single_ready",
            content_surface="feed_single",
            media_type="image",
            instagram_post_caption="tap for more",
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_single_blocked",
            content_surface="feed_single",
            media_type="image",
            instagram_post_caption="",
        )
        carousel = add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_carousel_ready",
            content_surface="feed_carousel",
            media_type="image",
            instagram_post_caption="pick one",
        )
        for index in range(2):
            component_path = tmp_path / f"carousel_{index}.jpg"
            component_path.write_bytes(f"carousel-{index}".encode())
            cf.conn.execute(
                """
                INSERT INTO asset_components
                (id, asset_id, component_index, media_path, media_hash, media_type, aspect_ratio,
                 alt_text, publishability_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'image', '1:1', ?, 'passed', '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
                """,
                (
                    f"comp_{index}",
                    carousel["id"],
                    index,
                    str(component_path),
                    f"hash_comp_{index}",
                    f"slide {index}",
                ),
            )
        cf.conn.commit()

        report = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey"
        )
        by_asset = {item["assetId"]: item for item in report["assets"]}

        assert by_asset["asset_reel_ready"]["canHandoff"] is True
        assert by_asset["asset_story_ready"]["canHandoff"] is True
        assert by_asset["asset_story_ready"]["igMediaType"] == "STORIES"
        assert by_asset["asset_single_ready"]["canHandoff"] is True
        assert by_asset["asset_single_blocked"]["canHandoff"] is False
        assert (
            "instagram_post_caption_missing"
            in by_asset["asset_single_blocked"]["blockingReasons"]
        )
        assert by_asset["asset_carousel_ready"]["canHandoff"] is True
        assert by_asset["asset_carousel_ready"]["igMediaType"] == "CAROUSEL"
        assert (
            len(by_asset["asset_carousel_ready"]["handoffManifestV2"]["mediaItems"])
            == 2
        )
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_handoff_readiness_explains_missing_reel_audio_proof(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(
            cf,
            tmp_path,
            asset_id="asset_reel_audio_missing_proof",
            campaign_slug="stacey_surface_inventory_20260606",
            audio_required=True,
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_reel_audio_missing_proof'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "new post is up",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": True,
                            "status": "attached",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
        cf.domains.distribution.create_distribution_plan(
            "asset_reel_audio_missing_proof",
            surface="regular_reel",
            instagram_account_id="ig_stacey_1",
        )

        report = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey", rendered_asset_id="asset_reel_audio_missing_proof"
        )
        readiness = report["assets"][0]

        assert readiness["canHandoff"] is False
        assert "missing_audio" in readiness["blockingReasons"]
        assert readiness["audioReadiness"] == {
            "required": True,
            "status": "attached",
            "taskStatus": "proof_missing",
            "audioId": None,
            "nativeProofValid": False,
            "blockingReasons": ["missing_audio"],
        }
    finally:
        cf.close()


def test_surface_handoff_readiness_explains_reel_caption_quality_failure(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(
            cf,
            tmp_path,
            asset_id="asset_reel_caption_quality_failed",
            campaign_slug="stacey_surface_inventory_20260606",
        )
        long_caption = (
            "this caption is too long and keeps going because it is not the simple native style "
            "we want under Instagram posts when the asset should be safe for scheduling and it "
            "keeps adding more unnecessary words"
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_reel_caption_quality_failed'",
            (json.dumps({"instagram_post_caption": long_caption}),),
        )
        cf.conn.commit()
        cf.domains.distribution.create_distribution_plan(
            "asset_reel_caption_quality_failed",
            surface="regular_reel",
            instagram_account_id="ig_stacey_1",
        )

        report = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey", rendered_asset_id="asset_reel_caption_quality_failed"
        )
        readiness = report["assets"][0]

        assert readiness["canHandoff"] is False
        assert "instagram_post_caption_quality_failed" in readiness["blockingReasons"]
        assert readiness["captionReadiness"] == {
            "present": True,
            "qualityPassed": False,
            "policy": "simple_ig_post_caption_v1",
            "reasons": ["instagram_post_caption_too_long"],
            "blockingReasons": ["instagram_post_caption_quality_failed"],
        }
    finally:
        cf.close()


def test_surface_handoff_readiness_blocks_carousel_without_ordered_components(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_carousel_gap",
            content_surface="feed_carousel",
            media_type="image",
            instagram_post_caption="pick one",
        )
        component_path = tmp_path / "carousel_gap_1.jpg"
        component_path.write_bytes(b"carousel-gap")
        cf.conn.execute(
            """
            INSERT INTO asset_components
            (id, asset_id, component_index, media_path, media_hash, media_type, aspect_ratio,
             alt_text, publishability_state, created_at, updated_at)
            VALUES ('comp_gap_1', 'asset_carousel_gap', 1, ?, 'hash_gap_1', 'image', '1:1',
                    'slide 1', 'passed', '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
            """,
            (str(component_path),),
        )
        cf.conn.commit()

        report = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey"
        )
        item = next(
            asset
            for asset in report["assets"]
            if asset["assetId"] == "asset_carousel_gap"
        )

        assert item["canHandoff"] is False
        assert "carousel_requires_2_to_10_components" in item["blockingReasons"]
        assert "carousel_components_not_ordered" in item["blockingReasons"]
        assert item["wouldWrite"] is False
    finally:
        cf.close()


def test_feed_single_caption_family_uses_surface_handoff_readiness(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "feed_caption_family.png")
        registered = cf.domains.surface_registration.register_surface_asset(
            input_path=image,
            surface="feed_single",
            creator="Stacey",
            campaign_slug="stacey_feed_single_proof",
            instagram_post_caption="soft launch today",
        )

        parent = cf.domains.variant_lineage.register_parent_reel(
            registered["renderedAssetId"], operator="tester"
        )
        created = cf.domains.caption_family.caption_family_create(
            creator="Stacey",
            parent_asset_id=registered["renderedAssetId"],
            requested_caption_versions=3,
            style="ig_short",
        )

        assert parent["parentAssetId"] == registered["renderedAssetId"]
        assert created["createdCaptionVersions"] == 3
        assert created["canProceed"] is True
        assert all(
            version["instagramPostCaption"] for version in created["plannedVersions"]
        )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM caption_versions WHERE caption_family_id = ?",
                (created["captionFamilyId"],),
            ).fetchone()[0]
            == 3
        )
    finally:
        cf.close()


def test_notify_publish_resolves_only_audio_handoff_metric_blockers(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "notify_metrics.png")
        registered = cf.domains.surface_registration.register_surface_asset(
            input_path=image,
            surface="feed_single",
            creator="Stacey",
            campaign_slug="stacey_notify_metrics_proof",
            instagram_post_caption="soft launch today",
        )
        asset = cf.domains.rendered_asset(registered["renderedAssetId"])
        manifest = cf.domains.surface_handoff.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_notify_metrics_proof",
            rendered_asset_id=registered["renderedAssetId"],
        )["drafts"][0]["handoffManifestV2"]
        row = {
            "id": "post_notify_metrics",
            "status": "published",
            "platform": "instagram",
            "publish_mode": "notify",
            "handoff_status": "completed",
            "manual_publish_confirmed_at": "2026-07-11T19:14:41Z",
            "instagram_post_id": "ig_media_1",
            "permalink": "https://www.instagram.com/reel/example/",
        }
        meta = {
            "rendered_asset_id": asset["id"],
            "source_asset_id": asset["source_asset_id"],
            "content_hash": asset["content_hash"],
            "caption_hash": asset["caption_hash"],
            "asset_state": "exportable",
            "handoff_manifest": manifest,
            "publishability_failure_reasons": [
                "embedded_audio_missing",
                "missing_audio",
            ],
        }

        resolved = threadsdash_metrics_adapter._metrics_eligibility_for_threadsdash_row(
            cf, row=row, meta=meta
        )
        assert resolved["eligible"] is True

        meta["publishability_failure_reasons"].append("identity_verification_failed")
        unsafe = threadsdash_metrics_adapter._metrics_eligibility_for_threadsdash_row(
            cf, row=row, meta=meta
        )
        assert unsafe["eligible"] is False
        assert "publishability_failure_reasons_present" in unsafe["blockingReasons"]
    finally:
        cf.close()


def test_live_export_blocks_without_passing_readiness(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        try:
            export_threadsdash(
                cf,
                campaign_slug="may",
                user_id="user_1",
                dry_run=False,
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="service-role",
                schedule_mode="live",
            )
        except ValueError as exc:
            assert "missing_audit" in str(exc)
        else:
            raise AssertionError("live export should block without an audit")
    finally:
        cf.close()


def test_threadsdash_usage_summarizes_existing_campaign_posts(
    tmp_path: Path, monkeypatch
):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "posts"
            assert params["user_id"] == "eq.user_1"
            rows = [
                {
                    "id": "post_1",
                    "status": "published",
                    "platform": "instagram",
                    "media_type": "reel",
                    "ig_media_type": "REELS",
                    "account_id": None,
                    "instagram_account_id": "ig_1",
                    "created_at": "2026-01-02T00:00:00+00:00",
                    "metadata": {
                        "campaign_factory": {
                            "campaign_id": "may",
                            "source_asset_id": "src_1",
                            "rendered_asset_id": "asset_1",
                            "content_hash": "hash_1",
                            "source_content_hash": "source_hash_1",
                        }
                    },
                },
                {
                    "id": "post_2",
                    "status": "draft",
                    "platform": "instagram",
                    "media_type": "story",
                    "ig_media_type": "STORIES",
                    "account_id": None,
                    "instagram_account_id": "ig_2",
                    "created_at": "2026-01-03T00:00:00+00:00",
                    "metadata": {
                        "campaign_factory": {
                            "campaign_id": "may",
                            "source_asset_id": "src_1",
                            "rendered_asset_id": "other_asset",
                            "content_hash": "other_hash",
                            "source_content_hash": "source_hash_1",
                        }
                    },
                },
            ]
            return _slice_rows(rows, params)

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        imported = cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        source = imported["imported"][0]
        cf.conn.execute(
            "UPDATE source_assets SET id = 'src_1', content_hash = 'source_hash_1' WHERE id = ?",
            (source["id"],),
        )
        set_test_source_prompt(cf, "src_1")
        rendered_path = tmp_path / "ok.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_1', ?, 'src_1', 'hash_1', ?, ?, 'ok.mp4', 'caption', 'v01_original', 'approved_candidate', 'approved', ?, ?)
            """,
            (source["campaign_id"], str(rendered_path), str(rendered_path), now, now),
        )
        cf.conn.commit()

        usage = summarize_threadsdash_usage(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        asset = usage["assets"][0]
        assert asset["usage"]["published"] == 1
        assert usage["sourceUsage"]["src_1"]["total"] == 2
        assert usage["contentHashUsage"]["hash_1"]["published"] == 1
        assert usage["accountUsage"]["ig_1"]["published"] == 1
        assert usage["surfaceUsage"]["reel"]["published"] == 1
        assert usage["surfaceUsage"]["story"]["draft"] == 1
        assert asset["usage"]["posts"][0]["surface"] == "reel"
        assert any(w["type"] == "exact_render_published" for w in usage["warnings"])
        assert any(w["type"] == "source_family_reuse" for w in usage["warnings"])
    finally:
        cf.close()


def test_sync_threadsdash_instagram_accounts_imports_real_stacey_roster_idempotently(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "instagram_accounts"
            return [
                {
                    "id": "ig_stacey_1",
                    "username": "stacey_ben.x",
                    "display_name": "Stacey",
                    "is_active": True,
                    "status": "active",
                    "needs_reauth": False,
                    "sync_cohort": "hot",
                    "oauth_granted_scopes": [
                        "instagram_content_publish",
                        "instagram_basic",
                    ],
                    "oauth_scopes_verified_at": "2026-07-15T03:00:00+00:00",
                    "trial_reels_capability": "eligible",
                    "trial_reels_capability_checked_at": "2026-07-15T04:00:00+00:00",
                    "trial_reels_capability_reason": "meta_trial_reel_publish_succeeded",
                },
                {
                    "id": "ig_stacey_2",
                    "username": "bennett.lovee",
                    "display_name": "Stacey",
                    "is_active": True,
                    "status": "active",
                    "needs_reauth": False,
                    "sync_cohort": "warm",
                    "oauth_granted_scopes": None,
                    "oauth_scopes_verified_at": None,
                    "trial_reels_capability": "denied",
                    "trial_reels_capability_checked_at": "2026-07-15T05:00:00+00:00",
                    "trial_reels_capability_reason": "Meta code 10",
                },
                {
                    "id": "ig_stacey_blocked",
                    "username": "stacey_blocked",
                    "display_name": "Stacey",
                    "is_active": False,
                    "status": "needs_reauth",
                    "needs_reauth": True,
                    "sync_cohort": "warm",
                },
                {
                    "id": "ig_lola_1",
                    "username": "lola_main",
                    "display_name": "Lola",
                    "is_active": True,
                    "status": "active",
                    "needs_reauth": False,
                    "sync_cohort": "hot",
                },
            ]

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        first = threadsdash_accounts_adapter.sync_threadsdash_instagram_accounts(
            cf,
            creator="Stacey",
            match="stacey",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        second = threadsdash_accounts_adapter.sync_threadsdash_instagram_accounts(
            cf,
            creator="Stacey",
            match="stacey",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        rows = [
            dict(row)
            for row in cf.conn.execute(
                """
                SELECT handle, external_id, oauth_granted_scopes_json,
                       oauth_scopes_verified_at, trial_reels_capability,
                       trial_reels_capability_checked_at,
                       trial_reels_capability_reason
                FROM accounts ORDER BY handle
                """
            ).fetchall()
        ]
        assert first["imported"] == 2
        assert first["created"] == 2
        assert first["skipReasons"]["not_eligible"] == 1
        assert first["skipReasons"]["creator_match_failed"] == 1
        assert second["imported"] == 2
        assert second["created"] == 0
        assert rows == [
            {
                "handle": "bennett.lovee",
                "external_id": "ig_stacey_2",
                "oauth_granted_scopes_json": None,
                "oauth_scopes_verified_at": None,
                "trial_reels_capability": "denied",
                "trial_reels_capability_checked_at": "2026-07-15T05:00:00+00:00",
                "trial_reels_capability_reason": "Meta code 10",
            },
            {
                "handle": "stacey_ben.x",
                "external_id": "ig_stacey_1",
                "oauth_granted_scopes_json": json.dumps(
                    ["instagram_basic", "instagram_content_publish"]
                ),
                "oauth_scopes_verified_at": "2026-07-15T03:00:00+00:00",
                "trial_reels_capability": "eligible",
                "trial_reels_capability_checked_at": "2026-07-15T04:00:00+00:00",
                "trial_reels_capability_reason": "meta_trial_reel_publish_succeeded",
            },
        ]
        assert second["accounts"][0]["trialCapability"]["status"] == "eligible"
        assert second["accounts"][1]["trialCapability"]["status"] == "denied"
    finally:
        cf.close()


@pytest.mark.parametrize(
    ("row", "meta", "expected"),
    [
        (
            {
                "watch_time_seconds": 14.5,
                "ig_reels_video_view_total_time": 99_000,
            },
            {},
            14.5,
        ),
        ({"ig_reels_video_view_total_time": 14_500}, {}, 14.5),
        ({"ig_reels_avg_watch_time": 7_250, "views_count": 2}, {}, 14.5),
        ({"ig_reels_avg_watch_time": 7_250}, {}, None),
    ],
)
def test_threadsdash_watch_time_is_normalized_to_total_seconds(
    row: dict, meta: dict, expected: float | None
) -> None:
    assert threadsdash_metrics_adapter._watch_time_seconds(row, meta) == expected


def test_sync_performance_snapshots_imports_threadsdash_metric_history(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    post_rows = []
    history_rows = []
    select_calls: list[tuple[str, dict]] = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            select_calls.append((table, dict(params)))
            if table == "posts":
                assert params["user_id"] == "eq.user_1"
                return _slice_rows(post_rows, params)
            if table == "post_metric_history":
                assert params["post_id"] == "in.(post_history_1)"
                return _slice_rows(history_rows, params)
            raise AssertionError(table)

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        post_rows.append(
            {
                "id": "post_history_1",
                "status": "published",
                "platform": "instagram",
                "account_id": None,
                "instagram_account_id": "ig_1",
                "created_at": "2026-01-02T00:00:00+00:00",
                "updated_at": "2026-01-03T00:00:00+00:00",
                "published_at": "2026-01-02T01:00:00+00:00",
                "permalink": "https://instagram.test/p/history",
                "views": 900,
                "likes_count": 60,
                "metadata": {
                    "campaign_factory": threadsdash_campaign_factory_metadata(source),
                },
            }
        )
        history_rows.extend(
            [
                {
                    "id": "hist_1h",
                    "post_id": "post_history_1",
                    "account_id": "acct_1",
                    "platform": "instagram",
                    "snapshot_at": "2026-01-02T02:00:00+00:00",
                    "hours_since_publish": 1,
                    "views_count": 100,
                    "likes_count": 8,
                    "replies_count": 1,
                    "reposts_count": 0,
                    "quotes_count": 0,
                    "shares_count": 2,
                    "saves_count": 3,
                    "reach": 90,
                    "engagement_rate": 0.155,
                    "created_at": "2026-01-02T02:00:00+00:00",
                },
                {
                    "id": "hist_24h",
                    "post_id": "post_history_1",
                    "account_id": "acct_1",
                    "platform": "instagram",
                    "snapshot_at": "2026-01-03T01:00:00+00:00",
                    "hours_since_publish": 24,
                    "views_count": 1200,
                    "likes_count": 80,
                    "replies_count": 9,
                    "reposts_count": 0,
                    "quotes_count": 0,
                    "shares_count": 14,
                    "saves_count": 22,
                    "reach": 1100,
                    "engagement_rate": 0.113,
                    "created_at": "2026-01-03T01:00:00+00:00",
                },
            ]
        )

        result = sync_performance_snapshots(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        snapshots = [
            dict(row)
            for row in cf.conn.execute(
                "SELECT post_id, snapshot_at, views, likes, comments, shares, saves, reach FROM performance_snapshots ORDER BY snapshot_at"
            ).fetchall()
        ]
        # Clamp-safe paginator issues one trailing empty-page read per table
        # (short non-empty pages are not trusted as end-of-data).
        assert [table for table, _ in select_calls] == [
            "posts",
            "posts",
            "post_metric_history",
            "post_metric_history",
        ]
        assert result["postsScanned"] == 1
        assert result["campaignFactoryPostsScanned"] == 1
        assert result["metricHistoryRowsScanned"] == 2
        assert result["campaignFactorySnapshotsScanned"] == 2
        assert result["inserted"] == 2
        assert snapshots == [
            {
                "post_id": "post_history_1",
                "snapshot_at": "2026-01-02T02:00:00+00:00",
                "views": 100,
                "likes": 8,
                "comments": 1,
                "shares": 2,
                "saves": 3,
                "reach": 90,
            },
            {
                "post_id": "post_history_1",
                "snapshot_at": "2026-01-03T01:00:00+00:00",
                "views": 1200,
                "likes": 80,
                "comments": 9,
                "shares": 14,
                "saves": 22,
                "reach": 1100,
            },
        ]
    finally:
        cf.close()


def test_lifecycle_report_derives_threadsdash_schedule_states(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )

        draft = cf.domains.lifecycle_reporting.lifecycle_report(
            "may", threadsdash_posts=[_threadsdash_lifecycle_post(plan_id=plan["id"])]
        )
        assert _lifecycle_state(draft) == "platform_draft_validated"

        future = cf.domains.lifecycle_reporting.lifecycle_report(
            "may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(
                    status="scheduled",
                    scheduled_for="2099-01-01T00:00:00+00:00",
                    plan_id=plan["id"],
                )
            ],
        )
        assert _lifecycle_state(future) == "scheduled"
        assert future["rows"][0]["blockingReason"] == "awaiting_publish"

        past_due = cf.domains.lifecycle_reporting.lifecycle_report(
            "may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(
                    status="scheduled",
                    scheduled_for="2026-01-01T00:00:00+00:00",
                    plan_id=plan["id"],
                )
            ],
        )
        assert _lifecycle_state(past_due) == "past_due_schedule"
        assert (
            past_due["rows"][0]["nextOperatorAction"] == "reschedule_or_manual_publish"
        )
    finally:
        cf.close()


def test_lifecycle_report_marks_resolved_past_due_draft_without_rescheduling(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        report = cf.domains.lifecycle_reporting.lifecycle_report(
            "may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(
                    post_id="8ee460e1-4f4e-4298-9597-462223b3f5cb",
                    status="draft",
                    scheduled_for=None,
                    plan_id=plan["id"],
                    metadata_extra={
                        "past_due_schedule": True,
                        "previous_scheduled_for": "2026-06-04T14:00:00+00:00",
                    },
                )
            ],
        )
        assert _lifecycle_state(report) == "platform_draft_validated"
        assert report["rows"][0]["evidence"]["pastDueScheduleResolved"] is True
        assert (
            report["rows"][0]["threadsDashboardPostId"]
            == "8ee460e1-4f4e-4298-9597-462223b3f5cb"
        )
    finally:
        cf.close()


def test_supabase_preflight_checks_bucket_and_required_schema(monkeypatch):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def get_storage_bucket(self, bucket):
            assert bucket == "media"
            return {"id": "media", "name": "media", "public": True}

        def select(self, table, params):
            assert table in {"posts", "media"}
            assert "select" in params
            return []

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    result = preflight_supabase(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
        supabase_storage_bucket="media",
    )
    assert result["ok"] is True
    assert {check["name"] for check in result["checks"]} == {
        "auth_posts_read",
        "media_bucket_exists",
        "media_schema",
        "posts_schema",
    }


def test_verify_threadsdash_export_blocks_non_draft_posts(monkeypatch):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            if table == "media":
                return [
                    {
                        "id": "media_1",
                        "file_type": "video",
                        "file_url": "https://example/media.mp4",
                        "storage_url": "https://example/media.mp4",
                        "storage_path": "user/media.mp4",
                    }
                ]
            if table == "posts":
                return [
                    {
                        "id": "post_1",
                        "platform": "instagram",
                        "status": "scheduled",
                        "scheduled_for": "2026-01-02T00:00:00+00:00",
                        "media_type": "reel",
                        "ig_media_type": "REELS",
                        "metadata": {
                            "campaign_factory": {"rendered_asset_id": "asset_1"}
                        },
                    }
                ]
            return []

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    result = verify_threadsdash_export(
        export_result_or_path={
            "campaign": "may",
            "supabase": {
                "media": [{"id": "media_1"}],
                "posts": [{"id": "post_1"}],
            },
        },
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
    )
    assert result["ok"] is False
    assert any(
        "post_status:scheduled" in reason for reason in result["blockingReasons"]
    )
    assert any(
        "scheduled_for_not_null" in reason for reason in result["blockingReasons"]
    )


def test_export_can_target_one_rendered_asset(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        second_path = tmp_path / "second.mp4"
        second_path.write_bytes(b"rendered 2")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_2', ?, ?, 'hash_2', ?, ?, 'second.mp4', 'caption two', 'v01_original', 'approved_candidate', 'approved', ?, ?)
            """,
            (
                source["campaign_id"],
                source["id"],
                str(second_path),
                str(second_path),
                now,
                now,
            ),
        )
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf, rendered_asset_id="asset_2", audit_id="audit_2")
        cf.conn.commit()
        result = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="user_1",
            dry_run=True,
            rendered_asset_ids=["asset_2"],
        )
        assert result["draftCount"] == 1
        assert result["payload"]["drafts"][0]["renderedAssetId"] == "asset_2"
    finally:
        cf.close()


def test_creator_os_daily_plan_blocks_draft_missing_instagram_post_caption(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_1",
                "username": "stacey_one",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
        ]

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 1,
                "items": [
                    _draft_item("post_no_caption", "ig_1", instagram_post_caption="")
                ],
            },
        )

        account = plan["accounts"][0]
        assert account["eligibleDrafts"] == []
        assert (
            account["variantCooldowns"][0]["reason"] == "missing_instagram_post_caption"
        )
        assert account["needsPostToday"] is True
        assert plan["creators"][0]["managerDecision"] == "needs_reel_factory_inventory"
    finally:
        cf.close()


def test_creator_os_daily_plan_reports_draft_exclusion_breakdown(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": f"ig_{idx}",
                "username": f"stacey_{idx}",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            }
            for idx in range(1, 7)
        ]

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 99,
                "items": [
                    _draft_item("post_no_caption", "ig_1", instagram_post_caption=""),
                    _draft_item("post_no_manifest", "ig_2", handoff_manifest_ok=False),
                    _draft_item(
                        "post_not_validated", "ig_3", platform_draft_validated=False
                    ),
                    _draft_item("post_quarantined", "ig_4", quarantined=True),
                    _draft_item("post_failed", "ig_5", publishability_state="blocked"),
                    _draft_item(
                        "post_cooldown",
                        "ig_6",
                        variant_family_id="vfam_1",
                        variant_id="var_1",
                        cooldown="same_variant_family_within_14_days",
                    ),
                ],
            },
        )

        stacey = plan["creators"][0]
        assert stacey["validatedDraftsAvailable"] == 0
        assert stacey["scheduleSafeDraftsAvailable"] == 0
        assert stacey["inventoryShortfall"] == 6
        assert stacey["draftsExcluded"] == {
            "missingInstagramPostCaption": 1,
            "missingHandoffManifest": 1,
            "notPlatformDraftValidated": 1,
            "quarantined": 1,
            "publishabilityFailed": 1,
            "variantCooldownBlocked": 1,
        }
        assert stacey["managerDecision"] == "needs_reel_factory_inventory"
        assert all(not row["eligibleDrafts"] for row in plan["accounts"])
    finally:
        cf.close()


def test_creator_os_daily_plan_uses_threadsdash_surface_needs_when_no_requirements(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_surface",
                        "username": "stacey_surface",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": False,
                        "surfaceNeeds": {"story": 1, "feed_single": {"remaining": 1}},
                    }
                ]
            ),
            schedule_plan={"creator": "Stacey", "items": []},
        )

        stacey = plan["creators"][0]
        assert stacey["accountsNeedingReels"] == 0
        assert stacey["accountsNeedingStories"] == 1
        assert stacey["accountsNeedingFeedSingles"] == 1
        assert plan["accounts"][0]["surfaceNeeds"]["story"]["needed"] is True
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_draft_inventory_gap_reports_local_assets_not_exported(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_local_safe")
        cf.domains.distribution.create_distribution_plan(
            "asset_local_safe", instagram_account_id="ig_1"
        )
        before = cf.conn.total_changes

        gap = cf.domains.draft_inventory_gap.creator_os_draft_inventory_gap(
            creator="Stacey",
            schedule_plan={
                "schema": "threadsdashboard.campaign_schedule_plan.v1",
                "items": [],
            },
        )

        assert cf.conn.total_changes == before
        assert gap["schema"] == "creator_os.draft_inventory_gap.v1"
        assert gap["localScheduleSafeAssets"] == 1
        assert gap["threadDashValidatedDrafts"] == 0
        assert gap["notExportedYet"][0]["renderedAssetId"] == "asset_local_safe"
        assert gap["blockedReasons"] == {"not_exported_to_threadsdash": 1}
        assert gap["nextSafeAction"] == "export_validated_drafts"
        assert gap["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_draft_inventory_gap_reports_exported_but_not_validated(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        gap = cf.domains.draft_inventory_gap.creator_os_draft_inventory_gap(
            creator="Stacey",
            schedule_plan={
                "schema": "threadsdashboard.campaign_schedule_plan.v1",
                "items": [
                    _draft_item(
                        "post_unvalidated", "ig_1", platform_draft_validated=False
                    ),
                ],
            },
        )

        assert cf.conn.total_changes == before
        assert gap["localScheduleSafeAssets"] == 0
        assert gap["threadDashValidatedDrafts"] == 0
        assert gap["exportedButNotValidated"] == [
            {
                "draftPostId": "post_unvalidated",
                "renderedAssetId": "asset_post_unvalidated",
                "distributionPlanId": "dist_post_unvalidated",
                "reason": "notPlatformDraftValidated",
                "wouldWrite": False,
            }
        ]
        assert gap["blockedReasons"] == {"platform_draft_not_validated": 1}
        assert gap["nextSafeAction"] == "fix_validation"
        assert gap["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_draft_inventory_gap_reports_validated_but_not_schedule_safe(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        gap = cf.domains.draft_inventory_gap.creator_os_draft_inventory_gap(
            creator="Stacey",
            schedule_plan={
                "schema": "threadsdashboard.campaign_schedule_plan.v1",
                "items": [
                    _draft_item("post_no_caption", "ig_1", instagram_post_caption=""),
                    _draft_item(
                        "post_cooldown",
                        "ig_2",
                        variant_family_id="vfam_1",
                        variant_id="var_1",
                        cooldown="same_variant_family_within_14_days",
                    ),
                ],
            },
        )

        assert cf.conn.total_changes == before
        assert gap["localScheduleSafeAssets"] == 0
        assert gap["threadDashValidatedDrafts"] == 0
        reasons = {
            row["draftPostId"]: row["reason"]
            for row in gap["validatedButNotScheduleSafe"]
        }
        assert reasons == {
            "post_no_caption": "missing_instagram_post_caption",
            "post_cooldown": "same_variant_family_within_14_days",
        }
        assert gap["blockedReasons"] == {
            "missing_instagram_post_caption": 1,
            "same_variant_family_within_14_days": 1,
        }
        assert gap["nextSafeAction"] == "fix_validation"
        assert gap["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_daily_plan_includes_draft_inventory_gap(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_local_safe")
        cf.domains.distribution.create_distribution_plan(
            "asset_local_safe", instagram_account_id="ig_1"
        )

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_1",
                        "username": "safe",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": True,
                    },
                ]
            ),
            schedule_plan={
                "schema": "threadsdashboard.campaign_schedule_plan.v1",
                "items": [],
            },
        )

        gap = plan["creators"][0]["draftInventoryGap"]
        assert gap["localScheduleSafeAssets"] == 1
        assert gap["threadDashValidatedDrafts"] == 0
        assert gap["nextSafeAction"] == "export_validated_drafts"
        assert gap["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_unsafe_draft_contracts(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": f"ig_{idx}",
                "username": f"stacey_{idx}",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            }
            for idx in range(1, 6)
        ]
        items = [
            _draft_item("post_no_caption", "ig_1", instagram_post_caption=""),
            _draft_item("post_no_manifest", "ig_2", handoff_manifest_ok=False),
            _draft_item("post_not_validated", "ig_3", platform_draft_validated=False),
            _draft_item("post_quarantined", "ig_4", quarantined=True),
            _draft_item("post_failed", "ig_5", publishability_state="blocked"),
        ]

        result = cf.domains.execution_readiness.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=5,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "requestedCount": 5,
                "status": "ready",
                "validatedDraftsAvailable": 5,
                "items": items,
            },
            time_plan={
                "creator": "Stacey",
                "requestedCount": 5,
                "status": "ready",
                "items": items,
            },
        )

        assert result["managerDecision"] == "needs_inventory"
        assert result["scheduleSafeDraftsAvailable"] == 0
        assert result["preCommitChecklist"]["draftReadiness"] == "fail"
        assert result["preCommitChecklist"]["captionContractReadiness"] == "fail"
        assert "missing_instagram_post_caption" in result["blockers"]
        assert "missing_handoff_manifest" in result["blockers"]
        assert "platform_draft_not_validated" in result["blockers"]
        assert "quarantined_draft_present" in result["blockers"]
        assert "publishability_failed_draft_present" in result["blockers"]
        details = {item["code"]: item for item in result["blockerDetails"]}
        assert details["missing_handoff_manifest"]["category"] == "draft_contract"
        assert (
            details["missing_handoff_manifest"]["nextAction"]
            == "create_or_export_schedule_safe_drafts"
        )
        assert "handoff" in details["missing_handoff_manifest"]["explanation"]
        assert details["insufficient_schedule_safe_drafts"]["observed"] == 0
        assert details["insufficient_schedule_safe_drafts"]["required"] == 5
    finally:
        cf.close()


def test_schedule_mode_rejects_unknown_non_empty_value() -> None:
    assert _normalize_schedule_mode(None) == "draft"
    assert _normalize_schedule_mode("") == "draft"
    assert _normalize_schedule_mode("preview") == "preview"
    with pytest.raises(ValueError, match="unknown schedule mode"):
        _normalize_schedule_mode("surprise")


def test_threadsdash_export_preview_failure_writes_no_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        cf.domains.models.upsert_model("model", "Model")
        cf.domains.models.upsert_campaign("may", "model")

        def fail_payload(*_args, **_kwargs):
            raise RuntimeError("payload exploded")

        monkeypatch.setattr(
            threadsdash_payload_adapter, "build_draft_payloads", fail_payload
        )
        export_count = cf.conn.execute(
            "SELECT COUNT(*) FROM threadsdash_exports"
        ).fetchone()[0]
        job_count = cf.conn.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[0]
        event_count = cf.conn.execute(
            "SELECT COUNT(*) FROM activity_events"
        ).fetchone()[0]

        with pytest.raises(RuntimeError, match="payload exploded"):
            export_threadsdash(
                cf,
                campaign_slug="may",
                user_id="user_1",
                dry_run=True,
            )

        assert (
            cf.conn.execute("SELECT COUNT(*) FROM threadsdash_exports").fetchone()[0]
            == export_count
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[0]
            == job_count
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0]
            == event_count
        )
    finally:
        cf.close()


def test_upload_media_inserts_media_row_without_invalid_upsert(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    inserted: list[tuple[str, dict[str, object]]] = []

    class FakeClient:
        url = "https://example.supabase.co"

        def select(self, table, params):
            return []

        def upload_storage_object(
            self, bucket, storage_path, file_path, content_type, *, upsert=False
        ):
            assert upsert is True

        def insert_with_fallback(self, table, row, fallback_remove):
            inserted.append((table, row))
            assert fallback_remove == ["url"]
            return {"id": "media_1", **row}

    result = threadsdash_delivery_adapter._upload_media(
        FakeClient(),
        bucket="media",
        user_id="user_1",
        local_path=media,
        tags=["campaign_factory"],
    )

    assert result["id"] == "media_1"
    assert [table for table, _row in inserted] == ["media"]


def test_upload_media_reuses_existing_row_without_writes(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")

    class FakeClient:
        url = "https://example.supabase.co"

        def select(self, table, params):
            return [
                {
                    "id": "media_existing",
                    "file_name": "already-there.mp4",
                    "storage_url": "https://cdn.example/existing.mp4",
                }
            ]

        def upload_storage_object(self, *_args, **_kwargs):
            raise AssertionError("existing media must not be uploaded again")

        def insert_with_fallback(self, *_args, **_kwargs):
            raise AssertionError("existing media must not be inserted again")

    result = threadsdash_delivery_adapter._upload_media(
        FakeClient(),
        bucket="media",
        user_id="user_1",
        local_path=media,
        tags=["campaign_factory"],
    )

    assert result["id"] == "media_existing"
    assert result["publicUrl"] == "https://cdn.example/existing.mp4"
    assert result["storagePath"].startswith("campaign_factory/user_1/")
    assert result["fileName"] == "already-there.mp4"
    assert result["reused"] is True


def test_upload_media_fails_closed_when_initial_read_fails(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")

    class FakeClient:
        url = "https://example.supabase.co"

        def select(self, table, params):
            raise RuntimeError("database unavailable")

        def upload_storage_object(self, *_args, **_kwargs):
            raise AssertionError("failed read must stop before upload")

        def insert_with_fallback(self, *_args, **_kwargs):
            raise AssertionError("failed read must stop before insert")

    with pytest.raises(RuntimeError, match="database unavailable"):
        threadsdash_delivery_adapter._upload_media(
            FakeClient(),
            bucket="media",
            user_id="user_1",
            local_path=media,
            tags=["campaign_factory"],
        )


def test_upload_media_recovers_ambiguous_insert_with_exact_read(
    tmp_path: Path,
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    reads = 0
    inserts = 0

    class FakeClient:
        url = "https://example.supabase.co"

        def select(self, table, params):
            nonlocal reads
            reads += 1
            if reads == 1:
                return []
            return [{"id": "media_committed", "file_name": "clip.mp4"}]

        def upload_storage_object(self, *_args, **_kwargs):
            return None

        def insert_with_fallback(self, *_args, **_kwargs):
            nonlocal inserts
            inserts += 1
            raise RuntimeError("connection closed after commit")

    result = threadsdash_delivery_adapter._upload_media(
        FakeClient(),
        bucket="media",
        user_id="user_1",
        local_path=media,
        tags=["campaign_factory"],
    )

    assert result["id"] == "media_committed"
    assert result["reused"] is True
    assert reads == 2
    assert inserts == 1


def test_upload_media_does_not_retry_uncommitted_insert_failure(
    tmp_path: Path,
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    reads = 0
    inserts = 0

    class FakeClient:
        url = "https://example.supabase.co"

        def select(self, table, params):
            nonlocal reads
            reads += 1
            return []

        def upload_storage_object(self, *_args, **_kwargs):
            return None

        def insert_with_fallback(self, *_args, **_kwargs):
            nonlocal inserts
            inserts += 1
            raise RuntimeError("insert rejected")

    with pytest.raises(RuntimeError, match="insert rejected"):
        threadsdash_delivery_adapter._upload_media(
            FakeClient(),
            bucket="media",
            user_id="user_1",
            local_path=media,
            tags=["campaign_factory"],
        )

    assert reads == 2
    assert inserts == 1
