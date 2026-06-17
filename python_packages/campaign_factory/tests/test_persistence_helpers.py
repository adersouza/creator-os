from __future__ import annotations

from campaign_factory.persistence import json_load, row_to_dict, utc_now


def test_json_load_returns_fallback_for_missing_or_invalid_json() -> None:
    assert json_load(None, fallback={}) == {}
    assert json_load("{bad", fallback=[]) == []


def test_json_load_parses_valid_json() -> None:
    assert json_load('{"ok": true}') == {"ok": True}


def test_row_to_dict_handles_none_and_mapping_rows() -> None:
    assert row_to_dict(None) is None
    assert row_to_dict({"id": "row_1"}) == {"id": "row_1"}


def test_utc_now_returns_timezone_aware_iso_string() -> None:
    assert "+" in utc_now()
