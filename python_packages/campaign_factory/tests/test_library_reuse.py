from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from campaign_factory.adapters import threadsdash_draft_payload
from campaign_factory.generation_workflow import run_generation_workflow
from campaign_factory.library_reuse import LibraryReuseError
from campaign_test_support import make_factory


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_library(folder: Path, count: int) -> list[Path]:
    folder.mkdir()
    paths = []
    for index in range(count):
        path = folder / f"selected_{index:03d}.mp4"
        path.write_bytes(f"owned-library-mp4-{index:03d}".encode())
        paths.append(path)
    return paths


def _stub_audit(cf: Any) -> None:
    def audit(**kwargs: Any) -> dict[str, Any]:
        return {
            "reports": [
                {
                    "renderedAssetId": asset_id,
                    "failedChecks": [],
                    "warnings": [],
                    "overallVerdict": "pass",
                }
                for asset_id in kwargs["rendered_asset_ids"]
            ]
        }

    cf.domains.library_reuse._audit_campaign = audit


def _run(cf: Any, folder: Path, *, campaign: str = "may") -> dict[str, Any]:
    return run_generation_workflow(
        cf,
        mode="library_reuse",
        campaign_slug=campaign,
        library_folder=folder,
        model_slug="model",
        output_format="reel",
        variant_count=20,
        workers=3,
        dry_run=False,
        apply=True,
    )


def test_library_reuse_preserves_one_mp4_without_render_or_paid_activity(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "library"
    source = _write_library(folder, 1)[0]
    cf = make_factory(tmp_path)
    try:
        _stub_audit(cf)
        result = _run(cf, folder)["result"]

        assert result["status"] == "validated"
        assert result["providerCalls"] == 0
        assert result["paidGeneration"] is False
        assert result["renderingPerformed"] is False
        assert result["captionSidecarsWritten"] == 0
        assert result["distributionDefaults"] == {
            "surface": "regular_reel",
            "instagramTrialReels": False,
            "shareToFeed": True,
            "collaborators": [],
        }
        mapping = result["mappings"][0]
        output = Path(mapping["outputPath"])
        assert output.read_bytes() == source.read_bytes()
        assert mapping["sourceSha256"] == mapping["storedSha256"]
        assert mapping["storedSha256"] == mapping["outputSha256"]
        assert mapping["mediaIdentity"] == f"sha256:{_sha256(source)}"
        assert mapping["captionBurned"] is False
        assert (
            cf.conn.execute("SELECT COUNT(*) AS c FROM render_jobs").fetchone()["c"]
            == 0
        )
    finally:
        cf.close()


def test_library_reuse_preserves_30_distinct_mp4s_one_to_one(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "library"
    sources = _write_library(folder, 30)
    cf = make_factory(tmp_path)
    try:
        _stub_audit(cf)
        result = _run(cf, folder)["result"]
        mappings = result["mappings"]

        assert len(mappings) == 30
        assert len({item["sourceAssetId"] for item in mappings}) == 30
        assert len({item["renderedAssetId"] for item in mappings}) == 30
        assert len({item["outputPath"] for item in mappings}) == 30
        assert [item["sourcePath"] for item in mappings] == [
            str(path.absolute()) for path in sources
        ]
        for source, mapping in zip(sources, mappings, strict=True):
            assert Path(mapping["outputPath"]).read_bytes() == source.read_bytes()
            assert mapping["sourceSha256"] == _sha256(source)
            assert mapping["outputSha256"] == _sha256(source)
    finally:
        cf.close()


@pytest.mark.parametrize("kind", ["missing_folder", "empty_folder"])
def test_library_reuse_fails_closed_when_input_is_missing(
    tmp_path: Path, kind: str
) -> None:
    folder = tmp_path / "library"
    if kind == "empty_folder":
        folder.mkdir()
    cf = make_factory(tmp_path)
    try:
        code = (
            "library_reuse_input_folder_missing"
            if kind == "missing_folder"
            else "library_reuse_input_missing"
        )
        with pytest.raises(LibraryReuseError, match=code):
            _run(cf, folder)
        assert (
            cf.conn.execute("SELECT COUNT(*) AS c FROM source_assets").fetchone()["c"]
            == 0
        )
    finally:
        cf.close()


def test_library_reuse_fails_closed_on_unreadable_input(tmp_path: Path) -> None:
    folder = tmp_path / "library"
    source = _write_library(folder, 1)[0]
    cf = make_factory(tmp_path)
    try:
        original = cf.domains.library_reuse._sha256_file

        def unreadable(path: Path) -> str:
            if Path(path) == source:
                raise PermissionError("simulated unreadable MP4")
            return original(path)

        cf.domains.library_reuse._sha256_file = unreadable
        with pytest.raises(LibraryReuseError, match="library_reuse_input_unreadable"):
            _run(cf, folder)
    finally:
        cf.close()


def test_library_reuse_fails_closed_when_source_hash_changes_after_selection(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "library"
    source = _write_library(folder, 1)[0]
    cf = make_factory(tmp_path)
    try:
        original = cf.domains.library_reuse._upsert_campaign

        def mutate_after_selection(*args: Any, **kwargs: Any) -> dict[str, Any]:
            campaign = original(*args, **kwargs)
            source.write_bytes(b"substituted-after-selection")
            return campaign

        cf.domains.library_reuse._upsert_campaign = mutate_after_selection
        with pytest.raises(
            LibraryReuseError, match="library_reuse_source_hash_mismatch"
        ):
            _run(cf, folder)
        job = cf.conn.execute(
            "SELECT * FROM pipeline_jobs WHERE job_type = 'library_reuse'"
        ).fetchone()
        assert job["status"] == "failed"
    finally:
        cf.close()


def test_library_reuse_rejects_duplicate_source_selection(tmp_path: Path) -> None:
    folder = tmp_path / "library"
    folder.mkdir()
    (folder / "first.mp4").write_bytes(b"same-owned-media")
    (folder / "second.mp4").write_bytes(b"same-owned-media")
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(
            LibraryReuseError, match="library_reuse_duplicate_source_selection"
        ):
            _run(cf, folder)
        assert (
            cf.conn.execute("SELECT COUNT(*) AS c FROM source_assets").fetchone()["c"]
            == 0
        )
    finally:
        cf.close()


def test_library_reuse_rejects_existing_output_collision(tmp_path: Path) -> None:
    folder = tmp_path / "library"
    _write_library(folder, 1)
    cf = make_factory(tmp_path)
    try:
        selection = cf.domains.library_reuse.plan(folder)[0]
        output = (
            tmp_path
            / "campaigns"
            / "model"
            / "may"
            / "02_rendered"
            / "library_reuse"
            / selection.output_filename
        )
        output.parent.mkdir(parents=True)
        output.write_bytes(b"colliding-unrelated-output")
        with pytest.raises(LibraryReuseError, match="library_reuse_output_collision"):
            _run(cf, folder)
        assert output.read_bytes() == b"colliding-unrelated-output"
        assert (
            cf.conn.execute("SELECT COUNT(*) AS c FROM rendered_assets").fetchone()["c"]
            == 0
        )
    finally:
        cf.close()


def test_interrupted_library_reuse_records_recoverable_partial_state(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "library"
    _write_library(folder, 2)
    cf = make_factory(tmp_path)
    try:
        _stub_audit(cf)
        cf.domains.library_reuse._mapping_payload = lambda *_args, **_kwargs: (
            _ for _ in ()
        ).throw(KeyboardInterrupt("simulated interruption after DB commit"))
        with pytest.raises(KeyboardInterrupt, match="simulated interruption"):
            _run(cf, folder)

        manifests = list(
            (tmp_path / "campaigns/model/may/01_reel_inputs/library_reuse_runs").glob(
                "*.json"
            )
        )
        assert len(manifests) == 1
        manifest = json.loads(manifests[0].read_text())
        assert manifest["status"] == "interrupted"
        assert manifest["recoverable"] is True
        assert manifest["completedCount"] == 1
        assert manifest["remainingCount"] == 1
        assert len(manifest["mappings"]) == 1
        assert Path(manifest["mappings"][0]["outputPath"]).exists()
        job = cf.conn.execute(
            "SELECT * FROM pipeline_jobs WHERE job_type = 'library_reuse'"
        ).fetchone()
        assert job["status"] == "failed"
    finally:
        cf.close()


def test_library_reuse_never_uses_clip_009_or_mutates_caption_sidecars(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "library"
    source = _write_library(folder, 1)[0]
    cf = make_factory(tmp_path)
    try:
        legacy_clip = cf.settings.reel_factory_root / "00_source_videos/clip_009.mp4"
        legacy_sidecar = cf.settings.reel_factory_root / "01_captions/clip_009.json"
        legacy_clip.write_bytes(b"legacy-clip-009")
        legacy_sidecar.write_text('{"hooks":["legacy"]}')
        before = {
            path: path.read_bytes()
            for path in cf.settings.reel_factory_root.rglob("*")
            if path.is_file()
        }

        def forbidden(*_args: Any, **_kwargs: Any) -> Any:
            pytest.fail("generic Reel Factory/provider path must not be called")

        cf.domains.make_batch_repo._prepare_reel_inputs = forbidden
        cf.domains.make_batch_repo._run_reel_factory = forbidden
        cf.domains.make_batch_repo._subprocess_run = forbidden
        _stub_audit(cf)
        result = _run(cf, folder)["result"]

        output = Path(result["mappings"][0]["outputPath"])
        assert output.read_bytes() == source.read_bytes()
        assert output.read_bytes() != legacy_clip.read_bytes()
        assert "clip_009" not in str(output)
        after = {
            path: path.read_bytes()
            for path in cf.settings.reel_factory_root.rglob("*")
            if path.is_file()
        }
        assert after == before
        assert result["providerCalls"] == 0
        assert result["paidGeneration"] is False
        assert result["renderingPerformed"] is False
        assert result["captionSidecarsWritten"] == 0
    finally:
        cf.close()


def test_library_reuse_preserves_exact_fingerprint_and_provenance_in_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "library"
    source = _write_library(folder, 1)[0]
    cf = make_factory(tmp_path)
    try:
        _stub_audit(cf)
        result = _run(cf, folder)["result"]
        mapping = result["mappings"][0]
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'review_ready' WHERE id = ?",
            (mapping["renderedAssetId"],),
        )
        cf.conn.commit()

        exported = cf.domains.export_summary.export_manifest(
            campaign_slug="may", review_only=True
        )["assets"]
        assert len(exported) == 1
        asset = exported[0]
        digest = _sha256(source)
        assert asset["contentHash"] == digest
        assert asset["sourceContentHash"] == digest
        assert _sha256(Path(asset["filePath"])) == digest
        assert asset["caption"] == ""
        assert asset["captionGeneration"]["burnedCaption"] is False
        assert asset["captionGeneration"]["captionSidecarPath"] is None
        lineage = asset["generatedAssetLineage"]
        assert lineage["schema"] == "reel_factory.generated_asset_lineage.v2"
        assert lineage["contentFingerprint"] == digest
        assert lineage["mediaIdentity"] == f"sha256:{digest}"
        assert lineage["source"]["originalPath"] == str(source.absolute())
        assert lineage["source"]["sha256"] == digest
        assert lineage["reuse"]["outputSha256"] == digest
        assert lineage["generation"] == {
            "tool": "library_reuse",
            "providerGenerated": False,
            "providerCalls": 0,
            "paidGeneration": False,
            "renderingPerformed": False,
        }
        assert lineage["caption"]["burned"] is False
        assert lineage["distributionDefaults"] == {
            "surface": "regular_reel",
            "instagramTrialReels": False,
            "shareToFeed": True,
            "collaborators": [],
        }

        monkeypatch.setattr(
            threadsdash_draft_payload,
            "_draft_destinations_for_asset",
            lambda *_args, **_kwargs: [
                {
                    "accountId": "unassigned",
                    "instagramAccountId": None,
                    "distributionSurface": "regular_reel",
                    "contentSurface": "reel",
                    "instagramTrialReels": False,
                    "trialGraduationStrategy": None,
                    "accountEligibility": {"allowed": True},
                }
            ],
        )
        draft = threadsdash_draft_payload.build_draft_payloads(
            cf,
            campaign_slug="may",
            user_id="user_test",
            review_only=True,
        )["drafts"][0]
        assert draft["distributionSurface"] == "regular_reel"
        assert draft["instagramTrialReels"] is False
        assert draft["trialGraduationStrategy"] is None
        assert draft["shareToFeed"] is True
        assert not draft.get("collaborators")
        assert draft["burnedCaptionText"] == ""
        assert draft["burnedCaptionHash"] is None
    finally:
        cf.close()
