from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable


class AutonomyPolicyRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        autonomy_levels: set[str],
        default_autonomy_level: str,
        json_load: Callable[[Any, Any], Any],
        utc_now: Callable[[], str],
    ) -> None:
        self.conn = conn
        self._autonomy_levels = autonomy_levels
        self._default_autonomy_level = default_autonomy_level
        self._json_load = json_load
        self._utc_now = utc_now

    def autonomy_level(self) -> str:
        row = self.conn.execute("SELECT value_json FROM trust_settings WHERE key = 'autonomy_level'").fetchone()
        payload = self._json_load(row["value_json"], {}) if row else {}
        level = str(payload.get("level") or self._default_autonomy_level)
        return level if level in self._autonomy_levels else self._default_autonomy_level

    def set_autonomy_level(self, level: str) -> dict[str, Any]:
        if level not in self._autonomy_levels:
            raise ValueError(f"autonomy level must be one of {sorted(self._autonomy_levels)}")
        now = self._utc_now()
        payload = {"level": level, "updatedAt": now}
        self.conn.execute(
            """
            INSERT INTO trust_settings (key, value_json, updated_at)
            VALUES ('autonomy_level', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
            """,
            (json.dumps(payload, ensure_ascii=False, sort_keys=True), now),
        )
        self.conn.commit()
        return {"schema": "campaign_factory.autonomy_policy.v1", **payload}

    def autonomy_policy(self) -> dict[str, Any]:
        return {
            "schema": "campaign_factory.autonomy_policy.v1",
            "level": self.autonomy_level(),
            "levels": [
                {"level": "level_1", "label": "Recommendations only", "publishesAutomatically": False},
                {"level": "level_2", "label": "Accepted recommendations auto-execute generation/render/audit", "publishesAutomatically": False},
                {"level": "level_3", "label": "Reserved for future auto-approval", "publishesAutomatically": False, "reserved": True},
            ],
        }
