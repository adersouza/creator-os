from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from campaign_factory.source_governance import (
    apply_lifecycle_transition,
    plan_lifecycle_transition,
)
from campaign_factory.source_intake import classify_source
from campaign_test_support import make_factory


def test_import_rejects_symlinked_input_directory(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "source.mp4").write_bytes(b"video")
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="symlink"):
            cf.domains.asset_import.import_folder(
                linked, campaign_slug="campaign", model_slug="stacey"
            )
        assert cf.conn.execute("SELECT COUNT(*) FROM source_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_probe_failure_is_cataloged_as_quarantine_not_silently_trusted(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "fake.mp4"
    source.write_bytes(b"not actually a video")
    classification = classify_source(source)
    assert classification["classificationAuthority"] == "extension_fallback"
    assert classification["quarantineReason"] == "media_probe_failed"

    cf = make_factory(tmp_path)
    try:
        result = cf.domains.asset_import.import_folder(
            inputs, campaign_slug="campaign", model_slug="stacey"
        )
        source_id = result["imported"][0]["id"]
        lifecycle = cf.conn.execute(
            "SELECT * FROM source_asset_lifecycle WHERE source_asset_id = ?",
            (source_id,),
        ).fetchone()
        assert lifecycle["lifecycle_state"] == "quarantined"
        assert lifecycle["classification_authority"] == "extension_fallback"
        assert result["quarantined"] == [
            {"sourceAssetId": source_id, "reason": "media_probe_failed"}
        ]
    finally:
        cf.close()


def test_global_duplicate_awareness_is_recorded_without_cross_campaign_aliasing(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "same.mp4"
    source.write_bytes(b"same bytes")
    cf = make_factory(tmp_path)
    try:
        first = cf.domains.asset_import.import_folder(
            inputs, campaign_slug="first", model_slug="stacey"
        )
        second = cf.domains.asset_import.import_folder(
            inputs, campaign_slug="second", model_slug="stacey"
        )
        lifecycle = cf.conn.execute(
            "SELECT metadata_json FROM source_asset_lifecycle WHERE source_asset_id = ?",
            (second["imported"][0]["id"],),
        ).fetchone()
        assert json.loads(lifecycle["metadata_json"])["duplicateSourceAssetIds"] == [
            first["imported"][0]["id"]
        ]
    finally:
        cf.close()


def test_archive_and_delete_are_tombstoned_events_not_file_deletion(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "source.mp4"
    source.write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        imported = cf.domains.asset_import.import_folder(
            inputs, campaign_slug="campaign", model_slug="stacey"
        )["imported"][0]
        archive = plan_lifecycle_transition(
            cf.conn,
            creator="stacey",
            source=imported["id"],
            new_state="archived",
            operator="operator",
            reason="retention archive requested",
        )
        apply_lifecycle_transition(cf.conn, archive)
        delete = plan_lifecycle_transition(
            cf.conn,
            creator="stacey",
            source=imported["id"],
            new_state="deleted",
            operator="operator",
            reason="approved tombstone request",
        )
        apply_lifecycle_transition(cf.conn, delete)

        assert Path(imported["stored_path"]).is_file()
        lifecycle = cf.conn.execute(
            "SELECT * FROM source_asset_lifecycle WHERE source_asset_id = ?",
            (imported["id"],),
        ).fetchone()
        assert lifecycle["lifecycle_state"] == "deleted"
        assert lifecycle["tombstoned_at"]
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM source_asset_lifecycle_events "
                "WHERE source_asset_id = ?",
                (imported["id"],),
            ).fetchone()[0]
            == 3
        )
        with pytest.raises(Exception, match="immutable"):
            cf.conn.execute("DELETE FROM source_asset_lifecycle_events")
        with pytest.raises(sqlite3.IntegrityError, match="terminal"):
            cf.conn.execute(
                """
                UPDATE source_asset_lifecycle SET metadata_json = '{}'
                WHERE source_asset_id = ?
                """,
                (imported["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            cf.conn.execute(
                "DELETE FROM source_asset_lifecycle WHERE source_asset_id = ?",
                (imported["id"],),
            )
    finally:
        cf.close()


def test_database_rejects_illegal_lifecycle_transition(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "source.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        source_id = cf.domains.asset_import.import_folder(
            inputs, campaign_slug="campaign", model_slug="stacey"
        )["imported"][0]["id"]

        with pytest.raises(sqlite3.IntegrityError, match="invalid source lifecycle"):
            cf.conn.execute(
                """
                UPDATE source_asset_lifecycle SET lifecycle_state = 'deleted'
                WHERE source_asset_id = ?
                """,
                (source_id,),
            )
    finally:
        cf.close()


def test_lifecycle_transition_compare_and_swap_rejects_stale_plan(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "source.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        source_id = cf.domains.asset_import.import_folder(
            inputs, campaign_slug="campaign", model_slug="stacey"
        )["imported"][0]["id"]
        plan = plan_lifecycle_transition(
            cf.conn,
            creator="stacey",
            source=source_id,
            new_state="archived",
            operator="operator",
            reason="archive reviewed source",
        )
        cf.conn.execute(
            """
            UPDATE source_asset_lifecycle
            SET version = version + 1
            WHERE source_asset_id = ?
            """,
            (source_id,),
        )
        cf.conn.commit()

        with pytest.raises(RuntimeError, match="lifecycle changed after preview"):
            apply_lifecycle_transition(cf.conn, plan)

        row = cf.conn.execute(
            """
            SELECT s.status, l.lifecycle_state
            FROM source_assets s
            JOIN source_asset_lifecycle l ON l.source_asset_id = s.id
            WHERE s.id = ?
            """,
            (source_id,),
        ).fetchone()
        assert tuple(row) == ("imported", "quarantined")
    finally:
        cf.close()
