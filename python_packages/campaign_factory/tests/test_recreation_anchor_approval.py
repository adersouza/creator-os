from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from campaign_factory.production_prompts import CREATOR_SOUL_IDS
from campaign_factory.recreation_anchor_approval import approve_recreation_anchor
from campaign_factory.recreation_prompting import (
    PROMPT_BUILDER_VERSION,
    SCHEMA,
    _fingerprint,
)
from PIL import Image


def test_operator_approval_binds_prompt_pack_and_exact_anchor(tmp_path: Path) -> None:
    creator_image = tmp_path / "creator.png"
    anchor = tmp_path / "anchor.png"
    reference = tmp_path / "reference.mp4"
    Image.new("RGB", (360, 640), "purple").save(creator_image)
    Image.new("RGB", (360, 640), "gold").save(anchor)
    reference.write_bytes(b"reference")
    core = {
        "schema": SCHEMA,
        "creator": "stacey",
        "intent": "recreate_reel",
        "creatorImage": {
            "path": str(creator_image),
            "sha256": hashlib.sha256(creator_image.read_bytes()).hexdigest(),
        },
        "referenceVideo": {
            "path": str(reference),
            "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        },
        "anchorPrompt": "Adult woman in a softly lit room, vertical framing.",
        "seedancePrompt": (
            "Use the approved anchor as the exact person with stable natural motion."
        ),
        "klingPrompt": "Use the approved anchor as the exact person.",
        "timeline": [],
        "promptPlanning": {
            "builderVersion": PROMPT_BUILDER_VERSION,
            "requestFingerprint": "a" * 64,
            "responseId": "response-1",
        },
    }
    prompt_pack = {**core, "promptPackFingerprint": _fingerprint(core)}
    prompt_path = tmp_path / "prompt-pack.json"
    prompt_path.write_text(json.dumps(prompt_pack), encoding="utf-8")

    receipt = approve_recreation_anchor(
        creator="stacey",
        anchor_file=anchor,
        anchor_generation_id="generation-1",
        prompt_pack_path=prompt_path,
        selected_composition_frame_sha256="b" * 64,
        approved_by="operator@test",
        output_dir=tmp_path / "approvals",
    )

    assert receipt["soulId"] == CREATOR_SOUL_IDS["stacey"]
    assert (
        receipt["anchorFileSha256"] == hashlib.sha256(anchor.read_bytes()).hexdigest()
    )
    assert Path(receipt["anchorFilePath"]) != anchor
    assert receipt["promptPackFingerprint"] == prompt_pack["promptPackFingerprint"]


def test_operator_approval_accepts_exact_soul_bound_candidate(
    tmp_path: Path,
) -> None:
    anchor = tmp_path / "anchor.png"
    reference = tmp_path / "reference.mp4"
    Image.new("RGB", (360, 640), "gold").save(anchor)
    reference.write_bytes(b"reference")
    soul_core = {
        "schema": "campaign_factory.verified_soul_identity_binding.v1",
        "creatorSlug": "stacey",
        "provider": "higgsfield",
        "soulId": CREATOR_SOUL_IDS["stacey"],
        "identityProfileId": "identity-1",
        "identityProfileVersion": 2,
        "identityProfileFingerprint": "f" * 64,
    }
    soul = {**soul_core, "bindingFingerprint": _fingerprint(soul_core)}
    prompt_core = {
        "schema": SCHEMA,
        "creator": "stacey",
        "intent": "recreate_reel",
        "creatorImage": None,
        "soulIdentity": soul,
        "referenceVideo": {
            "path": str(reference),
            "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        },
        "anchorPrompt": "Adult woman, age 19, with dark hair in a vertical room scene.",
        "seedancePrompt": "Adult woman, age 19, with dark hair follows the scene motion.",
        "klingPrompt": "Adult woman, age 19, with dark hair holds the scene pose.",
        "timeline": [],
        "promptPlanning": {
            "builderVersion": PROMPT_BUILDER_VERSION,
            "requestFingerprint": "a" * 64,
            "responseId": "response-1",
        },
    }
    prompt_pack = {
        **prompt_core,
        "promptPackFingerprint": _fingerprint(prompt_core),
    }
    prompt_path = tmp_path / "prompt-pack-soul.json"
    prompt_path.write_text(json.dumps(prompt_pack), encoding="utf-8")
    rights = {
        "schema": "reference_factory.provider_rights_eligibility.v1",
        "eligible": True,
        "referenceId": "reference-1",
        "provider": "higgsfield",
        "operation": "recreation_generation",
        "sourceSha256": prompt_pack["referenceVideo"]["sha256"],
        "rightsEventId": "rights-1",
        "rightsEvidenceFingerprint": "9" * 64,
        "rightsExpiresAt": "2026-08-04T00:00:00Z",
    }
    lineage = {
        "schema": "campaign_factory.recreation_anchor_candidate.v1",
        "promptPackFingerprint": prompt_pack["promptPackFingerprint"],
        "creatorImageSha256": None,
        "soulIdentity": soul,
        "referenceVideoSha256": prompt_pack["referenceVideo"]["sha256"],
        "anchorSha256": hashlib.sha256(anchor.read_bytes()).hexdigest(),
        "referenceId": "reference-1",
        "recreationPlanFingerprint": "8" * 64,
        "selectedRecreationMode": "structural",
        "referenceClassification": "simple_pose_motion",
        "referenceProviderRights": rights,
    }
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE source_assets (
          id TEXT, content_hash TEXT, media_type TEXT, source_prompt TEXT,
          higgsfield_job_id TEXT, status TEXT, created_at TEXT, updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO source_assets VALUES (?, ?, 'image', ?, ?, 'imported', '', '')",
        (
            "candidate-1",
            lineage["anchorSha256"],
            json.dumps(lineage),
            "generation-1",
        ),
    )
    identity = {
        "creator_slug": "stacey",
        "provider_identity_id": CREATOR_SOUL_IDS["stacey"],
        "id": "identity-1",
        "version": 2,
        "profile_fingerprint": "f" * 64,
    }
    factory = SimpleNamespace(
        conn=conn,
        domains=SimpleNamespace(
            creator_governance=SimpleNamespace(
                active_identity_profile=lambda *_args, **_kwargs: identity
            )
        ),
    )

    receipt = approve_recreation_anchor(
        factory=factory,
        creator="stacey",
        anchor_file=anchor,
        anchor_generation_id="generation-1",
        prompt_pack_path=prompt_path,
        selected_composition_frame_sha256="b" * 64,
        approved_by="operator@test",
        output_dir=tmp_path / "approvals-soul",
    )

    assert receipt["schema"] == "creator_os.recreation_anchor_approval.v3"
    assert receipt["creatorImageSha256"] is None
    assert receipt["soulIdentity"] == soul
