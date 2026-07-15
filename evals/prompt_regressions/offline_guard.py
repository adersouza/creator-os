from __future__ import annotations

import json
from pathlib import Path

CONFIG = Path(__file__).with_name("promptfooconfig.json")


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    providers = config.get("providers") if isinstance(config, dict) else None
    if providers != [
        {"id": "file://local_provider.py", "label": "local-captured-fixture-provider"}
    ]:
        raise SystemExit("offline prompt config may use only local_provider.py")
    assertions = (config.get("defaultTest") or {}).get("assert") or []
    if assertions != [{"type": "python", "value": "file://assertions.py"}]:
        raise SystemExit(
            "offline prompt config may use only deterministic Python assertions"
        )
    if config.get("sharing") is not False:
        raise SystemExit("offline prompt config must disable sharing")


if __name__ == "__main__":
    main()
