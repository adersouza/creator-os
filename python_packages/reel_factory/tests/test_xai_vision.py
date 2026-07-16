from __future__ import annotations

import base64
import json
from pathlib import Path

from reel_factory.xai_vision import (
    build_xai_payload,
    data_uri,
    load_xai_api_key,
    response_text,
    strip_json_fence,
)


def test_xai_vision_payload_keeps_images_inline_and_disables_storage(
    tmp_path: Path,
) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(b"png-bytes")

    payload = build_xai_payload(
        model="grok-test", frames=[image], instruction="inspect anatomy"
    )

    assert payload["store"] is False
    content = payload["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "inspect anatomy"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"] == data_uri(image)
    assert base64.b64decode(content[1]["image_url"].split(",", 1)[1]) == b"png-bytes"


def test_xai_vision_response_parsing_preserves_old_qc_wire_shape() -> None:
    payload = {
        "output": [
            {"content": [{"type": "output_text", "text": '```json\n{"ok":true}\n```'}]}
        ]
    }

    assert json.loads(strip_json_fence(response_text(payload))) == {"ok": True}


def test_xai_api_key_prefers_environment_without_writing_state(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "test-key")

    assert load_xai_api_key(tmp_path) == "test-key"
    assert list(tmp_path.iterdir()) == []
