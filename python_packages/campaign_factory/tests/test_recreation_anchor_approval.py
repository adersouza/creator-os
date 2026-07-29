from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
