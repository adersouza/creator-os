from __future__ import annotations

import json
from pathlib import Path

from reference_factory.db import connect
from reference_factory.knowledge_pack import export_knowledge_pack

from pipeline_contracts import validate_reference_factory_knowledge_pack


def test_export_knowledge_pack_is_gold_first_versioned_and_measured(tmp_path: Path):
    conn = connect(tmp_path / "reference.sqlite")
    try:
        _insert_reference(conn, "ref_gold", label="gold")
        _insert_reference(conn, "ref_maybe", label="maybe")
        _insert_pattern(conn, "pattern_gold", "ref_gold")
        _insert_pattern(conn, "pattern_maybe", "ref_maybe")
        _insert_prompt(conn, "prompt_gold", "ref_gold")
        _insert_prompt(conn, "prompt_maybe", "ref_maybe")
        for index in range(3):
            _insert_outcome(conn, "prompt_gold", f"post_{index}", index)
        _insert_outcome(conn, "prompt_maybe", "post_excluded", 0)
        _insert_caption(conn, "caption_gold", "ref_gold")
        _insert_caption(conn, "caption_maybe", "ref_maybe")
        _insert_audio(conn)
        conn.commit()

        output_path = tmp_path / "knowledge_pack.json"
        pack = export_knowledge_pack(
            conn,
            output_path=output_path,
            generated_at="2026-07-15T15:00:00Z",
        )

        validate_reference_factory_knowledge_pack(pack)
        assert json.loads(output_path.read_text(encoding="utf-8")) == pack
        assert pack["schema"] == "reference_factory.knowledge_pack.v1"
        assert pack["packId"].startswith("kp_")
        assert pack["policy"] == {
            "humanGoldLabelsAuthoritative": True,
            "measuredFactsSource": "campaign_factory.performance_snapshots",
            "minimumMeasuredExamplesForRecommendation": 3,
        }
        assert [item["referenceId"] for item in pack["goldReferences"]] == ["ref_gold"]
        assert [item["id"] for item in pack["promptCards"]] == ["prompt_gold"]
        assert [item["id"] for item in pack["patternCards"]] == ["pattern_gold"]
        assert [item["id"] for item in pack["captionPatterns"]] == ["caption_gold"]
        pattern = pack["patternCards"][0]
        assert pattern["recommendationStatus"] == "eligible"
        assert pattern["measuredExampleCount"] == 3
        assert {item["postId"] for item in pattern["measuredOutcomeProvenance"]} == {
            "post_0",
            "post_1",
            "post_2",
        }
        assert all(
            item["outcome"]["performanceSnapshotId"].startswith("snapshot_")
            for item in pattern["measuredOutcomeProvenance"]
        )
        assert pack["summary"]["eligiblePatternCount"] == 1
        assert pack["summary"]["advisoryPatternCount"] == 0
    finally:
        conn.close()


def test_export_knowledge_pack_keeps_under_three_examples_advisory(tmp_path: Path):
    conn = connect(tmp_path / "reference.sqlite")
    try:
        _insert_reference(conn, "ref_gold", label="gold")
        _insert_pattern(conn, "pattern_gold", "ref_gold")
        _insert_prompt(conn, "prompt_gold", "ref_gold")
        _insert_outcome(conn, "prompt_gold", "post_1", 1)
        _insert_outcome(conn, "prompt_gold", "post_2", 2)
        conn.commit()

        first = export_knowledge_pack(conn, generated_at="2026-07-15T15:00:00Z")
        second = export_knowledge_pack(conn, generated_at="2026-07-16T15:00:00Z")

        assert first["patternCards"][0]["recommendationStatus"] == "advisory"
        assert first["summary"]["advisoryPatternCount"] == 1
        assert first["packId"] == second["packId"]
        assert first["sourceFingerprint"] == second["sourceFingerprint"]
        assert first["generatedAt"] != second["generatedAt"]
    finally:
        conn.close()


def _insert_reference(conn, reference_id: str, *, label: str) -> None:
    timestamp = "2026-07-15T12:00:00Z"
    conn.execute(
        """
        INSERT INTO source_files (
          reference_id, path, account, file_name, extension, kind, size_bytes,
          mtime, path_hash, content_hash, created_at, updated_at
        ) VALUES (?, ?, 'stacey', ?, '.mp4', 'video', 100, ?, ?, ?, ?, ?)
        """,
        (
            reference_id,
            f"/portable/{reference_id}.mp4",
            f"{reference_id}.mp4",
            timestamp,
            f"path_{reference_id}",
            f"hash_{reference_id}",
            timestamp,
            timestamp,
        ),
    )
    conn.execute(
        """
        INSERT INTO review_labels (
          id, reference_id, label, tags_json, notes, created_at, updated_at
        ) VALUES (?, ?, ?, '["mirror"]', 'operator label', ?, ?)
        """,
        (f"label_{reference_id}", reference_id, label, timestamp, timestamp),
    )


def _insert_pattern(conn, pattern_id: str, reference_id: str) -> None:
    timestamp = "2026-07-15T12:00:00Z"
    conn.execute(
        """
        INSERT INTO reference_patterns (
          id, reference_id, public_post_id, rank, provider, model,
          analyzer_version, suggested_label, visual_format, hook_type,
          caption_archetype, quality_score, pattern_json, created_at, updated_at
        ) VALUES (?, ?, NULL, 1, 'heuristic', NULL, 'v1', 'Mirror curiosity',
                  'mirror', 'curiosity', 'question', 91, ?, ?, ?)
        """,
        (
            pattern_id,
            reference_id,
            json.dumps(
                {
                    "clusterKey": "mirror::curiosity::question",
                    "visualFormat": "mirror",
                    "hookType": "curiosity",
                    "captionArchetype": "question",
                }
            ),
            timestamp,
            timestamp,
        ),
    )


def _insert_prompt(conn, prompt_id: str, reference_id: str) -> None:
    timestamp = "2026-07-15T12:00:00Z"
    conn.execute(
        """
        INSERT INTO generated_video_prompts (
          id, analysis_job_id, reference_id, target_tool, model_profile,
          prompt_json, status, created_at, updated_at
        ) VALUES (?, NULL, ?, 'kling_3', 'Stacey', ?, 'prompt_ready', ?, ?)
        """,
        (
            prompt_id,
            reference_id,
            json.dumps({"mainPrompt": "subtle motion"}),
            timestamp,
            timestamp,
        ),
    )


def _insert_outcome(conn, prompt_id: str, post_id: str, index: int) -> None:
    timestamp = f"2026-07-15T1{index}:00:00Z"
    conn.execute(
        """
        INSERT INTO prompt_post_outcomes (
          prompt_id, post_id, reward_score, confidence, source_snapshot_at,
          scoring_version, baseline_provenance_json, outcome_json, created_at, updated_at
        ) VALUES (?, ?, ?, 0.8, ?, 'learning_score.v1', ?, ?, ?, ?)
        """,
        (
            prompt_id,
            post_id,
            0.5 + index,
            timestamp,
            json.dumps({"accountId": "ig_1"}),
            json.dumps({"performanceSnapshotId": f"snapshot_{post_id}"}),
            timestamp,
            timestamp,
        ),
    )


def _insert_caption(conn, caption_id: str, reference_id: str) -> None:
    conn.execute(
        """
        INSERT INTO caption_patterns (
          caption_hash, reference_id, normalized_text, raw_text, first_line,
          line_count, char_count, avg_confidence, placement_json, created_at
        ) VALUES (?, ?, 'pick one', 'pick one', 'pick one', 1, 8, 0.9, '{}',
                  '2026-07-15T12:00:00Z')
        """,
        (caption_id, reference_id),
    )


def _insert_audio(conn) -> None:
    conn.execute(
        """
        INSERT INTO audio_patterns (
          id, platform, audio_id, audio_title, artist_name, usage_type,
          visual_format, hook_type, caption_archetype, post_count, total_plays,
          median_plays, top_accounts_json, example_posts_json, recommendation_json,
          created_at, updated_at
        ) VALUES (
          'audio_1', 'instagram', 'native_1', 'Audio', 'Artist', 'native_trending',
          'mirror', 'curiosity', 'question', 2, 1000, 500, '[]', '[]', '{}',
          '2026-07-15T12:00:00Z', '2026-07-15T12:00:00Z'
        )
        """
    )
