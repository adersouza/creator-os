"""A repaired caption must be repaired everywhere, not just where it was found.

`banks.json` records the pre-repair text under `ocr_repair.repairedFrom`. If any
sidecar still holds that text, `CaptionBankStore.build()` reintroduces it as a
SEPARATE entry (the strings now hash differently), quietly resurrecting damaged
copy the moment the bank is rebuilt.

This is not hypothetical: the original repair fixed clip_009.json and banks.json
but missed clip_010.json, which carried the same caption at a different index.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _repaired_from() -> set[str]:
    banks = json.loads((ROOT / "caption_banks" / "banks.json").read_text("utf-8"))
    out: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            repair = node.get("ocr_repair")
            if isinstance(repair, dict) and repair.get("repairedFrom"):
                out.add(str(repair["repairedFrom"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(banks)
    return out


class CaptionRepairIntegrityTests(unittest.TestCase):
    def test_no_sidecar_still_holds_a_repaired_caption(self):
        damaged = _repaired_from()
        if not damaged:
            self.skipTest("no OCR repairs recorded")

        offenders = []
        for sidecar in sorted((ROOT / "01_captions").glob("*.json")):
            text = sidecar.read_text("utf-8")
            offenders += [
                f"{sidecar.name}: {frag!r}" for frag in damaged if frag in text
            ]
        self.assertEqual(
            offenders, [], f"pre-repair caption text still on disk: {offenders}"
        )

    def test_repaired_text_is_what_the_banks_actually_carry(self):
        banks = (ROOT / "caption_banks" / "banks.json").read_text("utf-8")
        for frag in _repaired_from():
            # Allowed only inside the audit record itself, never as live `text`.
            self.assertNotIn(f'"text": "{frag}', banks)


if __name__ == "__main__":
    unittest.main()
