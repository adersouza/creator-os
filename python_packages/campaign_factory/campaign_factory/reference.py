from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_reference_factory_knowledge_pack

from .config import Settings
from .persistence import json_load


class ReferenceRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        new_id: Callable[[str], str],
        utc_now: Callable[[], str],
        record_event: Callable[..., dict[str, Any]],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        prepare_reel_inputs: Callable[..., dict[str, Any]],
        discoverability_safe_content_contract: Callable[..., dict[str, Any]],
        reference_hook_fallbacks: tuple[str, ...],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._new_id = new_id
        self._utc_now = utc_now
        self._record_event = record_event
        self._campaign_by_slug = campaign_by_slug
        self._prepare_reel_inputs = prepare_reel_inputs
        self._discoverability_safe_content_contract = (
            discoverability_safe_content_contract
        )
        self._reference_hook_fallbacks = reference_hook_fallbacks

    def import_reference_bank(
        self,
        bank_path: Path,
        prompt_pack_path: Path | None = None,
        *,
        dry_run: bool = False,
        campaign_slug: str | None = None,
        require_local_paths: bool = False,
        replace_campaign_links: bool = False,
    ) -> dict[str, Any]:
        bank_path = Path(bank_path).expanduser().resolve()
        if not bank_path.exists():
            raise FileNotFoundError(f"reference bank not found: {bank_path}")
        bank = json_load(bank_path.read_text(encoding="utf-8"), {})
        knowledge_pack = (
            bank
            if isinstance(bank, dict)
            and bank.get("schema") == "reference_factory.knowledge_pack.v1"
            else None
        )
        if knowledge_pack is not None:
            validate_reference_factory_knowledge_pack(knowledge_pack)
            self._validate_knowledge_pack_fingerprint(knowledge_pack)
            bank = self._knowledge_pack_as_reference_bank(knowledge_pack)
        clusters = bank.get("clusters") if isinstance(bank, dict) else None
        if not isinstance(clusters, list):
            raise ValueError("reference bank must contain a clusters array")
        prompt_by_key = self.reference_prompt_pack_by_cluster(prompt_pack_path)
        now = self._utc_now()
        campaign = self._campaign_by_slug(campaign_slug) if campaign_slug else None
        created = 0
        updated = 0
        unchanged = 0
        linked = 0
        unlinked = 0
        imported_pattern_ids: set[str] = set()
        missing_paths: list[str] = []
        for idx, cluster in enumerate(clusters, 1):
            cluster_key = str(
                cluster.get("clusterKey") or cluster.get("label") or f"cluster_{idx}"
            )
            prompt = prompt_by_key.get(cluster_key) or {}
            pattern_id = (
                "refpat_" + hashlib.sha256(cluster_key.encode("utf-8")).hexdigest()[:16]
            )
            existing = self.conn.execute(
                "SELECT id, raw_json FROM reference_patterns WHERE cluster_key = ?",
                (cluster_key,),
            ).fetchone()
            if existing:
                pattern_id = existing["id"]
            imported_pattern_ids.add(pattern_id)
            reference_ids = (
                cluster.get("referenceIds") or prompt.get("referenceIds") or []
            )
            local_paths = (
                cluster.get("localPaths") or cluster.get("referenceFiles") or []
            )
            local_paths = [
                str(Path(os.path.expandvars(str(path))).expanduser())
                for path in local_paths
            ]
            for local_path in local_paths:
                if not Path(local_path).exists():
                    missing_paths.append(local_path)
            public_urls = prompt.get("publicUrls") or []
            prompt_template = cluster.get("promptTemplate") or {}
            higgsfield_json = prompt.get("higgsfieldJson") or {}
            caption_formulas = prompt.get("captionFormulas") or []
            audio_recommendations = (
                cluster.get("audioRecommendations")
                or prompt.get("audioRecommendations")
                or {}
            )
            source_payload = {"bank": cluster, "prompt": prompt}
            source_hash = hashlib.sha256(
                json.dumps(source_payload, ensure_ascii=False, sort_keys=True).encode(
                    "utf-8"
                )
            ).hexdigest()
            previous_raw = json_load(existing["raw_json"], {}) if existing else {}
            previous_hash = previous_raw.get("sourceHash")
            change = (
                "unchanged"
                if previous_hash == source_hash
                else ("updated" if existing else "created")
            )
            if change == "created":
                created += 1
            elif change == "updated":
                updated += 1
            else:
                unchanged += 1
            raw_payload = {
                **source_payload,
                "sourceHash": source_hash,
                "sourceRunId": bank.get("runId") or bank.get("run_id"),
            }
            if not dry_run and change != "unchanged":
                self.conn.execute(
                    """
                INSERT INTO reference_patterns (
                  id, cluster_key, rank, label, visual_format, hook_type, caption_archetype,
                  reference_ids_json, local_paths_json, public_urls_json, prompt_template_json,
                  higgsfield_json, caption_formulas_json, audio_recommendations_json, raw_json, imported_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_key) DO UPDATE SET
                  rank = excluded.rank,
                  label = excluded.label,
                  visual_format = excluded.visual_format,
                  hook_type = excluded.hook_type,
                  caption_archetype = excluded.caption_archetype,
                  reference_ids_json = excluded.reference_ids_json,
                  local_paths_json = excluded.local_paths_json,
                  public_urls_json = excluded.public_urls_json,
                  prompt_template_json = excluded.prompt_template_json,
                  higgsfield_json = excluded.higgsfield_json,
                  caption_formulas_json = excluded.caption_formulas_json,
                  audio_recommendations_json = excluded.audio_recommendations_json,
                  raw_json = excluded.raw_json,
                  updated_at = excluded.updated_at
                """,
                    (
                        pattern_id,
                        cluster_key,
                        cluster.get("clusterRank") or cluster.get("rank") or idx,
                        cluster.get("label") or cluster_key.replace("::", " / "),
                        cluster.get("visualFormat"),
                        cluster.get("hookType"),
                        cluster.get("captionArchetype"),
                        json.dumps(reference_ids, ensure_ascii=False),
                        json.dumps(local_paths, ensure_ascii=False),
                        json.dumps(public_urls, ensure_ascii=False),
                        json.dumps(prompt_template, ensure_ascii=False, sort_keys=True),
                        json.dumps(higgsfield_json, ensure_ascii=False, sort_keys=True),
                        json.dumps(
                            caption_formulas, ensure_ascii=False, sort_keys=True
                        ),
                        json.dumps(
                            audio_recommendations, ensure_ascii=False, sort_keys=True
                        ),
                        json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
            if campaign:
                plan = self.conn.execute(
                    """
                    SELECT id FROM campaign_reference_plans
                    WHERE campaign_id = ? AND reference_pattern_id = ?
                    LIMIT 1
                    """,
                    (campaign["id"], pattern_id),
                ).fetchone()
                if not plan:
                    linked += 1
                    if not dry_run:
                        self.conn.execute(
                            """
                            INSERT INTO campaign_reference_plans
                            (id, campaign_id, reference_pattern_id, variant_count, notes, created_at, updated_at)
                            VALUES (?, ?, ?, 5, ?, ?, ?)
                            """,
                            (
                                self._new_id("refplan"),
                                campaign["id"],
                                pattern_id,
                                f"Imported from {bank_path.name}",
                                now,
                                now,
                            ),
                        )
        if require_local_paths and missing_paths:
            if not dry_run:
                self.conn.rollback()
            raise ValueError(
                "reference bank contains missing local paths: "
                + ", ".join(sorted(set(missing_paths))[:10])
            )
        if replace_campaign_links:
            if campaign is None:
                raise ValueError("replace_campaign_links requires a campaign")
            if not imported_pattern_ids:
                raise ValueError(
                    "refusing to replace campaign links from an empty bank"
                )
            existing_links = self.conn.execute(
                """SELECT id, reference_pattern_id FROM campaign_reference_plans
                WHERE campaign_id = ?""",
                (campaign["id"],),
            ).fetchall()
            stale_link_ids = [
                row["id"]
                for row in existing_links
                if row["reference_pattern_id"] not in imported_pattern_ids
            ]
            unlinked = len(stale_link_ids)
            if not dry_run and stale_link_ids:
                self.conn.executemany(
                    "DELETE FROM campaign_reference_plans WHERE id = ?",
                    [(link_id,) for link_id in stale_link_ids],
                )
        if not dry_run:
            if knowledge_pack is not None:
                self._store_knowledge_pack(knowledge_pack, now=now)
            self.conn.commit()
        if not dry_run and (created or updated or linked):
            self._record_event(
                "reference_bank_imported",
                status="success",
                message=f"Reference bank imported: {created} created, {updated} updated",
                metadata={
                    "bankPath": str(bank_path),
                    "promptPackPath": str(prompt_pack_path)
                    if prompt_pack_path
                    else None,
                    "created": created,
                    "updated": updated,
                    "unchanged": unchanged,
                    "campaignLinks": linked,
                },
            )
        return {
            "schema": (
                "campaign_factory.knowledge_pack_import.v1"
                if knowledge_pack is not None
                else "campaign_factory.reference_bank_import.v1"
            ),
            "bankPath": str(bank_path),
            "promptPackPath": str(prompt_pack_path) if prompt_pack_path else None,
            "dryRun": dry_run,
            "wouldWrite": bool(created or updated or linked or unlinked),
            "patternsImported": created + updated,
            "patternsCreated": created,
            "patternsUpdated": updated,
            "patternsUnchanged": unchanged,
            "campaignLinksCreated": linked,
            "campaignLinksRemoved": unlinked,
            "campaign": campaign_slug,
            "missingLocalPaths": sorted(set(missing_paths)),
            "knowledgePackId": (
                knowledge_pack.get("packId") if knowledge_pack is not None else None
            ),
            "knowledgePackSourceFingerprint": (
                knowledge_pack.get("sourceFingerprint")
                if knowledge_pack is not None
                else None
            ),
        }

    def _knowledge_pack_as_reference_bank(self, pack: dict[str, Any]) -> dict[str, Any]:
        gold_by_id = {str(item["referenceId"]): item for item in pack["goldReferences"]}
        prompt_by_id = {str(item["id"]): item for item in pack["promptCards"]}
        caption_by_id = {str(item["id"]): item for item in pack["captionPatterns"]}
        audio_by_id = {str(item["id"]): item for item in pack["audioPatterns"]}
        clusters = []
        for card in pack["patternCards"]:
            reference_ids = [str(item) for item in card["referenceIds"]]
            prompt_cards = [
                prompt_by_id[item]
                for item in card["promptCardIds"]
                if item in prompt_by_id
            ]
            caption_patterns = [
                caption_by_id[item]
                for item in card["captionPatternIds"]
                if item in caption_by_id
            ]
            audio_patterns = [
                audio_by_id[item]
                for item in card["audioPatternIds"]
                if item in audio_by_id
            ]
            clusters.append(
                {
                    "clusterKey": card["clusterKey"],
                    "clusterRank": card["rank"],
                    "label": card["label"],
                    "visualFormat": card["visualFormat"],
                    "hookType": card["hookType"],
                    "captionArchetype": card["captionArchetype"],
                    "referenceIds": reference_ids,
                    "localPaths": [
                        gold_by_id[reference_id]["localPath"]
                        for reference_id in reference_ids
                        if reference_id in gold_by_id
                        and gold_by_id[reference_id].get("localPath")
                    ],
                    "promptTemplate": (
                        prompt_cards[0]["prompt"] if prompt_cards else {}
                    ),
                    "higgsfieldJson": next(
                        (
                            prompt["prompt"]
                            for prompt in prompt_cards
                            if str(prompt["targetTool"]).startswith("higgsfield")
                        ),
                        {},
                    ),
                    "captionFormulas": [
                        {
                            "formula": item["normalizedText"],
                            "exampleCaptions": [item["normalizedText"]],
                            "sourceCaptionPatternId": item["id"],
                        }
                        for item in caption_patterns
                        if item.get("normalizedText")
                    ],
                    "audioRecommendations": {
                        "schema": "reference_factory.knowledge_pack.audio_patterns.v1",
                        "sourcePatternIds": [item["id"] for item in audio_patterns],
                        "items": audio_patterns,
                    },
                    "knowledge": {
                        "packId": pack["packId"],
                        "sourceFingerprint": pack["sourceFingerprint"],
                        "patternCardId": card["id"],
                        "recommendationStatus": card["recommendationStatus"],
                        "measuredExampleCount": card["measuredExampleCount"],
                        "measuredOutcomeProvenance": card["measuredOutcomeProvenance"],
                        "policy": pack["policy"],
                    },
                }
            )
        return {
            "schema": "reference_factory.knowledge_pack.v1",
            "runId": pack["packId"],
            "clusters": clusters,
        }

    def _validate_knowledge_pack_fingerprint(self, pack: dict[str, Any]) -> None:
        core = {
            key: value
            for key, value in pack.items()
            if key not in {"schema", "packId", "sourceFingerprint", "generatedAt"}
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                core,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if pack["sourceFingerprint"] != fingerprint:
            raise ValueError("knowledge pack sourceFingerprint does not match payload")
        if pack["packId"] != f"kp_{fingerprint[:16]}":
            raise ValueError("knowledge pack packId does not match sourceFingerprint")

    def _store_knowledge_pack(self, pack: dict[str, Any], *, now: str) -> None:
        self.conn.execute(
            """
            INSERT INTO reference_knowledge_packs (
              id, schema_version, source_fingerprint, generated_at, policy_json,
              summary_json, payload_json, imported_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              schema_version = excluded.schema_version,
              source_fingerprint = excluded.source_fingerprint,
              generated_at = excluded.generated_at,
              policy_json = excluded.policy_json,
              summary_json = excluded.summary_json,
              payload_json = excluded.payload_json,
              updated_at = excluded.updated_at
            """,
            (
                pack["packId"],
                pack["schema"],
                pack["sourceFingerprint"],
                pack["generatedAt"],
                json.dumps(pack["policy"], ensure_ascii=False, sort_keys=True),
                json.dumps(pack["summary"], ensure_ascii=False, sort_keys=True),
                json.dumps(pack, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )

    def reference_prompt_pack_by_cluster(
        self, prompt_pack_path: Path | None
    ) -> dict[str, dict[str, Any]]:
        if prompt_pack_path is None:
            default = (
                self.settings.reference_reels_root
                / "learning"
                / "higgsfield_prompt_pack_top300.json"
            )
            prompt_pack_path = default if default.exists() else None
        if prompt_pack_path is None:
            return {}
        prompt_pack_path = Path(prompt_pack_path).expanduser().resolve()
        if not prompt_pack_path.exists():
            return {}
        payload = json_load(prompt_pack_path.read_text(encoding="utf-8"), {})
        prompts = payload.get("prompts") if isinstance(payload, dict) else None
        if not isinstance(prompts, list):
            return {}
        return {
            str(item.get("clusterKey")): item
            for item in prompts
            if item.get("clusterKey")
        }

    def reference_patterns(self, limit: int = 50) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT * FROM reference_patterns ORDER BY COALESCE(rank, 999999), label LIMIT ?",
            (max(1, min(limit, 1000)),),
        ).fetchall()
        return {
            "schema": "campaign_factory.reference_patterns.v1",
            "count": len(rows),
            "patterns": [self.reference_pattern_payload(dict(row)) for row in rows],
        }

    def reference_pattern_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        raw = json_load(row.get("raw_json") or "{}", {})
        bank = raw.get("bank") if isinstance(raw, dict) else {}
        knowledge = (bank or {}).get("knowledge") or {}
        return {
            "id": row["id"],
            "clusterKey": row["cluster_key"],
            "rank": row["rank"],
            "label": row["label"],
            "visualFormat": row["visual_format"],
            "hookType": row["hook_type"],
            "captionArchetype": row["caption_archetype"],
            "referenceIds": json_load(row["reference_ids_json"], []),
            "localPaths": json_load(row["local_paths_json"], []),
            "publicUrls": json_load(row["public_urls_json"], []),
            "promptTemplate": json_load(row["prompt_template_json"], {}),
            "higgsfieldJson": json_load(row["higgsfield_json"], {}),
            "captionFormulas": json_load(row["caption_formulas_json"], []),
            "audioRecommendations": json_load(
                row.get("audio_recommendations_json"), {}
            ),
            "suggestedFormats": (bank or {}).get("suggestedFormats") or ["reel"],
            "suggestedVariantRecipes": (bank or {}).get("suggestedVariantRecipes")
            or [],
            "raw": raw,
            "knowledge": knowledge,
            "recommendationStatus": knowledge.get("recommendationStatus"),
            "measuredExampleCount": int(knowledge.get("measuredExampleCount") or 0),
            "importedAt": row["imported_at"],
            "updatedAt": row["updated_at"],
        }

    def select_reference_pattern(
        self,
        campaign_slug: str,
        *,
        cluster_key: str | None = None,
        reference_pattern_id: str | None = None,
        variant_count: int = 5,
        notes: str | None = None,
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        if reference_pattern_id:
            pattern_row = self.conn.execute(
                "SELECT * FROM reference_patterns WHERE id = ?", (reference_pattern_id,)
            ).fetchone()
        elif cluster_key:
            pattern_row = self.conn.execute(
                "SELECT * FROM reference_patterns WHERE cluster_key = ?", (cluster_key,)
            ).fetchone()
        else:
            pattern_row = self.conn.execute(
                "SELECT * FROM reference_patterns ORDER BY COALESCE(rank, 999999), label LIMIT 1"
            ).fetchone()
        if not pattern_row:
            raise ValueError(
                "reference pattern not found; run import-reference-bank first"
            )
        now = self._utc_now()
        plan_id = self._new_id("refplan")
        self.conn.execute(
            """
            INSERT INTO campaign_reference_plans
            (id, campaign_id, reference_pattern_id, variant_count, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                campaign["id"],
                pattern_row["id"],
                max(1, variant_count),
                notes,
                now,
                now,
            ),
        )
        self.conn.commit()
        pattern = self.reference_pattern_payload(dict(pattern_row))
        self._record_event(
            "reference_pattern_selected",
            campaign_id=campaign["id"],
            status="success",
            message=f"Reference pattern selected: {pattern['label']}",
            metadata={
                "referencePatternId": pattern["id"],
                "clusterKey": pattern["clusterKey"],
                "variantCount": variant_count,
                "notes": notes,
            },
        )
        return {
            "schema": "campaign_factory.reference_pattern_selection.v1",
            "campaign": campaign["slug"],
            "planId": plan_id,
            "variantCount": max(1, variant_count),
            "pattern": pattern,
            "hooks": self.reference_hooks(pattern, count=max(1, variant_count)),
        }

    def campaign_reference_plan(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        rows = self.conn.execute(
            """
            SELECT
              crp.id AS plan_id, crp.variant_count, crp.notes, crp.created_at AS plan_created_at,
              rp.*
            FROM campaign_reference_plans crp
            JOIN reference_patterns rp ON rp.id = crp.reference_pattern_id
            WHERE crp.campaign_id = ?
            ORDER BY crp.created_at DESC
            """,
            (campaign["id"],),
        ).fetchall()
        plans = []
        for row in rows:
            row_dict = dict(row)
            pattern = self.reference_pattern_payload(row_dict)
            plans.append(
                {
                    "planId": row_dict["plan_id"],
                    "variantCount": row_dict["variant_count"],
                    "notes": row_dict["notes"],
                    "createdAt": row_dict["plan_created_at"],
                    "pattern": pattern,
                    "hooks": self.reference_hooks(
                        pattern, count=row_dict["variant_count"]
                    ),
                }
            )
        return {
            "schema": "campaign_factory.reference_plan.v1",
            "campaign": campaign["slug"],
            "plans": plans,
        }

    def prepare_reel_from_reference(
        self,
        *,
        campaign_slug: str,
        cluster_key: str | None = None,
        reference_pattern_id: str | None = None,
        variant_count: int = 5,
        recipes: list[str] | None = None,
        caption_color: str | None = "auto",
        notes: str | None = None,
        force_new: bool = True,
    ) -> dict[str, Any]:
        selection = self.select_reference_pattern(
            campaign_slug,
            cluster_key=cluster_key,
            reference_pattern_id=reference_pattern_id,
            variant_count=variant_count,
            notes=notes,
        )
        pattern = selection["pattern"]
        hooks = selection["hooks"]
        if recipes is None:
            raw_bank = (pattern.get("raw") or {}).get("bank") or {}
            recipes = raw_bank.get("suggestedVariantRecipes") or None
        prepare = self._prepare_reel_inputs(
            campaign_slug=campaign_slug,
            hooks=hooks,
            recipes=recipes,
            caption_color=caption_color,
            notes=notes or f"reference pattern: {pattern['label']}",
            force_new=force_new,
        )
        return {
            "schema": "campaign_factory.prepare_from_reference.v1",
            "campaign": campaign_slug,
            "selection": selection,
            "prepare": prepare,
        }

    def active_reference_pattern_for_campaign(
        self, campaign_id: str
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT rp.*
            FROM campaign_reference_plans crp
            JOIN reference_patterns rp ON rp.id = crp.reference_pattern_id
            WHERE crp.campaign_id = ?
            ORDER BY crp.created_at DESC
            LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
        return self.reference_pattern_payload(dict(row)) if row else None

    def reference_hooks(
        self, pattern: dict[str, Any], count: int = 5
    ) -> list[dict[str, Any]]:
        formulas = pattern.get("captionFormulas") or []
        if not formulas:
            formulas = [
                {
                    "formula": (pattern.get("promptTemplate") or {}).get("captionBrief")
                    or "short original hook"
                }
            ]
        candidates: list[tuple[str, int, str]] = []
        seen: set[str] = set()
        for formula_index, formula in enumerate(formulas):
            for example in formula.get("exampleCaptions") or []:
                text = str(example).strip()
                normalized = " ".join(text.lower().split())
                if text and normalized not in seen:
                    seen.add(normalized)
                    candidates.append((text, formula_index, "example_caption"))
            text = str(formula.get("formula") or "").strip()
            normalized = " ".join(text.lower().split())
            if text and normalized not in seen:
                seen.add(normalized)
                candidates.append((text, formula_index, "caption_formula"))
        safe_candidates = [
            item for item in candidates if self.reference_hook_is_schedule_safe(item[0])
        ]
        if safe_candidates:
            candidates = safe_candidates
        if not candidates:
            for fallback in self._reference_hook_fallbacks:
                candidates.append((fallback, 0, "simple_native_fallback"))
        hooks = []
        for idx in range(count):
            text, formula_index, candidate_kind = candidates[idx % len(candidates)]
            hooks.append(
                {
                    "text": text,
                    "referenceClusterKey": pattern["clusterKey"],
                    "referenceLabel": pattern["label"],
                    "hookType": pattern.get("hookType"),
                    "captionArchetype": pattern.get("captionArchetype"),
                    "audioRecommendations": pattern.get("audioRecommendations") or {},
                    "formulaIndex": formula_index,
                    "candidateKind": candidate_kind,
                    "source": "reference_factory",
                }
            )
        return hooks

    def reference_hook_is_schedule_safe(self, text: str) -> bool:
        normalized = " ".join(str(text or "").strip().split())
        if not normalized:
            return False
        if "{" in normalized or "}" in normalized:
            return False
        if len(normalized) > 42:
            return False
        plain = (
            normalized.replace("’", "'")
            .replace("‘", "'")
            .replace("“", '"')
            .replace("”", '"')
            .replace("–", "-")
            .replace("—", "-")
        )
        if any(ord(char) > 127 for char in plain):
            return False
        if len(plain.split()) > 7:
            return False
        if normalized.count("!") > 1:
            return False
        letters = [char for char in normalized if char.isalpha()]
        if letters:
            upper_ratio = sum(1 for char in letters if char.isupper()) / len(letters)
            if upper_ratio >= 0.75:
                return False
        if re.search(
            r"\b(go\s+)?live\b|\bsubscribe\b|\bvip\b|\btonight\b|\bcan't resist\b|\bcant resist\b|\bgood boy\b|\btake it off\b",
            normalized,
            re.IGNORECASE,
        ):
            return False
        if (
            self._discoverability_safe_content_contract(normalized).get(
                "discoverabilitySafe"
            )
            is not True
        ):
            return False
        return True
