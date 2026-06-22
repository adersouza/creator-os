from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from .persistence import json_load


class AudioOperationsRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        sanitize_for_storage: Callable[[Any], Any],
        utc_now: Callable[[], str],
        video_exts: set[str],
        probe_video_metadata: Callable[[Any], dict[str, Any]],
        rendered_asset: Callable[[str], dict[str, Any]],
        record_event: Callable[..., str],
        recommendation_item_row: Callable[[str], dict[str, Any]],
        recommendation_item_campaign: Callable[[dict[str, Any]], dict[str, Any]],
        recommendation_item: Callable[[str], dict[str, Any]],
        audio_catalog_payload: Callable[[dict[str, Any]], dict[str, Any]],
        audio_catalog_recommendation: Callable[[dict[str, Any]], dict[str, Any]],
        graph_id_for: Callable[..., str],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., str | None],
        ensure_graph_edge_strict: Callable[..., str | None],
        resolve_exception: Callable[..., dict[str, Any]],
        performance_snapshot_payload: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._sanitize_for_storage = sanitize_for_storage
        self._utc_now = utc_now
        self._video_exts = video_exts
        self._probe_video_metadata = probe_video_metadata
        self._rendered_asset = rendered_asset
        self._record_event = record_event
        self._recommendation_item_row = recommendation_item_row
        self._recommendation_item_campaign = recommendation_item_campaign
        self._recommendation_item = recommendation_item
        self._audio_catalog_payload = audio_catalog_payload
        self._audio_catalog_recommendation = audio_catalog_recommendation
        self._graph_id_for = graph_id_for
        self._ensure_graph_node = ensure_graph_node
        self._ensure_graph_edge = ensure_graph_edge
        self._ensure_graph_edge_strict = ensure_graph_edge_strict
        self._resolve_exception = resolve_exception
        self._performance_snapshot_payload = performance_snapshot_payload


    def attach_audio_to_distribution_plan(
            self,
            distribution_plan_id: str,
            *,
            track_id: str | None = None,
            track_name: str | None = None,
            source: str | None = None,
            audio_url: str | None = None,
            native_audio_id: str | None = None,
            local_winner_audio_id: str | None = None,
            selected_reason: str | None = None,
            segment_start_seconds: float | None = None,
            segment_duration_seconds: float | None = None,
            segment_label: str | None = None,
            segment_reason: str | None = None,
            operator: str | None = None,
            notes: str | None = None,
        ) -> dict[str, Any]:
            plan_row = self.conn.execute("SELECT * FROM distribution_plans WHERE id = ?", (distribution_plan_id,)).fetchone()
            if not plan_row:
                raise ValueError(f"distribution plan not found: {distribution_plan_id}")
            plan = dict(plan_row)
            if not any(str(value or "").strip() for value in (track_id, audio_url, native_audio_id, local_winner_audio_id)):
                raise ValueError("track_id, audio_url, native_audio_id, or local_winner_audio_id is required")
            source_value = str(source or "manual").strip() or "manual"
            now = self._utc_now()
            asset = self._rendered_asset(plan["rendered_asset_id"])
            caption_generation = json_load(asset.get("caption_generation_json"), {})
            if not isinstance(caption_generation, dict):
                caption_generation = {}
            existing_intent = caption_generation.get("audioIntent") if isinstance(caption_generation.get("audioIntent"), dict) else {}
            audio_id = str(track_id or native_audio_id or local_winner_audio_id or audio_url or "").strip()
            selection = {
                "track_id": str(track_id).strip() if track_id else None,
                "audio_id": audio_id,
                "audio_title": str(track_name).strip() if track_name else None,
                "track_name": str(track_name).strip() if track_name else None,
                "platform_audio_id": str(native_audio_id or track_id).strip() if (native_audio_id or track_id) else None,
                "native_audio_id": str(native_audio_id).strip() if native_audio_id else None,
                "platform_url": str(audio_url).strip() if audio_url else None,
                "native_audio_url": str(audio_url).strip() if audio_url else None,
                "local_winner_audio_id": str(local_winner_audio_id).strip() if local_winner_audio_id else None,
                "selected_at": now,
                "attached_at": now,
                "selected_by": operator,
                "attached_by": operator,
                "selected_reason": str(selected_reason).strip() if selected_reason else None,
                "selection_source": source_value,
                "source": source_value,
                "notes": notes,
            }
            audio_segment = self.normalize_audio_segment({
                "start_seconds": segment_start_seconds,
                "duration_seconds": segment_duration_seconds,
                "label": segment_label,
                "reason": segment_reason,
            })
            if audio_segment:
                selection["audio_segment"] = audio_segment
                selection["segment_start_seconds"] = audio_segment.get("start_seconds")
                if audio_segment.get("duration_seconds") is not None:
                    selection["segment_duration_seconds"] = audio_segment.get("duration_seconds")
                if audio_segment.get("label"):
                    selection["segment_label"] = audio_segment.get("label")
                if audio_segment.get("reason"):
                    selection["segment_reason"] = audio_segment.get("reason")
            selection = {key: value for key, value in selection.items() if value is not None and value != ""}
            audio_intent = {
                **existing_intent,
                "schema": existing_intent.get("schema") or "pipeline.audio_intent.v1",
                "mode": existing_intent.get("mode") or "native_platform_audio",
                "required": True,
                "status": "attached",
                "platform": existing_intent.get("platform") or "instagram",
                "operator_selection": selection,
                "gates": {
                    **(existing_intent.get("gates") if isinstance(existing_intent.get("gates"), dict) else {}),
                    "allow_draft_export": True,
                    "allow_preview_schedule": True,
                    "allow_live_schedule": True,
                    "allow_publish": False,
                },
            }
            caption_generation["audioIntent"] = audio_intent
            self.conn.execute(
                "UPDATE rendered_assets SET caption_generation_json = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(self._sanitize_for_storage(caption_generation), ensure_ascii=False, sort_keys=True),
                    now,
                    plan["rendered_asset_id"],
                ),
            )
            self.conn.execute("UPDATE distribution_plans SET updated_at = ? WHERE id = ?", (now, distribution_plan_id))
            selection_id = f"audsel_{hashlib.sha256(f'{distribution_plan_id}:{audio_id}:{source_value}'.encode('utf-8')).hexdigest()[:12]}"
            selection_payload = {
                "schema": "campaign_factory.attached_audio.v1",
                "distributionPlanId": distribution_plan_id,
                "renderedAssetId": plan["rendered_asset_id"],
                "trackId": track_id,
                "trackName": track_name,
                "source": source_value,
                "audioUrl": audio_url,
                "nativeAudioId": native_audio_id,
                "localWinnerAudioId": local_winner_audio_id,
                "audioSegment": audio_segment,
                "selectedReason": selected_reason,
                "operator": operator,
                "notes": notes,
                "selectedAt": now,
                "attachedAt": now,
            }
            self.conn.execute(
                """
                INSERT INTO audio_selections (
                  id, campaign_id, rendered_asset_id, status, proof_note, selected_by,
                  selected_at, payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, 'attached', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  status = 'attached',
                  proof_note = excluded.proof_note,
                  selected_by = excluded.selected_by,
                  selected_at = COALESCE(audio_selections.selected_at, excluded.selected_at),
                  payload_json = excluded.payload_json,
                  updated_at = excluded.updated_at
                """,
                (
                    selection_id,
                    plan["campaign_id"],
                    plan["rendered_asset_id"],
                    notes,
                    operator,
                    now,
                    json.dumps(self._sanitize_for_storage(selection_payload), ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            self._record_event(
                "campaign_audio_attached",
                campaign_id=plan["campaign_id"],
                rendered_asset_id=plan["rendered_asset_id"],
                status="success",
                message=f"Campaign audio attached for distribution plan {distribution_plan_id}",
                metadata={
                    "distributionPlanId": distribution_plan_id,
                    "selectionId": selection_id,
                    "trackId": track_id,
                    "source": source_value,
                    "audioSegment": audio_segment,
                },
                commit=False,
            )
            self.conn.commit()
            return {
                "schema": "campaign_factory.attach_audio_result.v1",
                "distributionPlanId": distribution_plan_id,
                "renderedAssetId": plan["rendered_asset_id"],
                "audioSelectionId": selection_id,
                "audioIntent": audio_intent,
            }

    def attach_cover_frame_to_rendered_asset(
            self,
            rendered_asset_id: str,
            *,
            seconds: float,
            cover_image_path: str | None = None,
            cover_image_url: str | None = None,
            cover_image_hash: str | None = None,
            reason: str | None = None,
            operator: str | None = None,
        ) -> dict[str, Any]:
            asset = self._rendered_asset(rendered_asset_id)
            caption_generation = json_load(asset.get("caption_generation_json"), {})
            if not isinstance(caption_generation, dict):
                caption_generation = {}
            cover_frame = self.normalize_cover_frame({
                "seconds": seconds,
                "cover_image_path": cover_image_path,
                "cover_image_url": cover_image_url,
                "cover_image_hash": cover_image_hash,
                "reason": reason,
            })
            if not cover_frame:
                raise ValueError("valid cover frame seconds are required")
            now = self._utc_now()
            cover_frame["selected_at"] = now
            if operator:
                cover_frame["selected_by"] = operator
            caption_generation["coverFrame"] = cover_frame
            self.conn.execute(
                "UPDATE rendered_assets SET caption_generation_json = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(self._sanitize_for_storage(caption_generation), ensure_ascii=False, sort_keys=True),
                    now,
                    rendered_asset_id,
                ),
            )
            self._record_event(
                "campaign_cover_frame_attached",
                campaign_id=asset.get("campaign_id"),
                rendered_asset_id=rendered_asset_id,
                status="success",
                message=f"Campaign cover frame attached for rendered asset {rendered_asset_id}",
                metadata={
                    "coverFrame": cover_frame,
                },
                commit=False,
            )
            self.conn.commit()
            return {
                "schema": "campaign_factory.attach_cover_frame_result.v1",
                "renderedAssetId": rendered_asset_id,
                "coverFrame": cover_frame,
            }

    def select_audio_for_recommendation(
            self,
            recommendation_item_id: str,
            audio_id: str,
            *,
            operator: str | None = None,
            notes: str | None = None,
        ) -> dict[str, Any]:
            row = self._recommendation_item_row(recommendation_item_id)
            campaign = self._recommendation_item_campaign(row)
            audio = self.audio_catalog_row(audio_id)
            payload = self._audio_catalog_payload(audio)
            now = self._utc_now()
            audio_catalog_id = str(audio["id"])
            selection_key = f"{recommendation_item_id}:{audio_catalog_id}"
            selection_id = f"audsel_{hashlib.sha256(selection_key.encode('utf-8')).hexdigest()[:12]}"
            selection_payload = {
                "recommendationItemId": recommendation_item_id,
                "audio": self._audio_catalog_recommendation({**payload, "matchScore": 100}),
                "operator": operator,
                "notes": notes,
                "status": "selected",
                "selectedAt": now,
            }
            self.conn.execute(
                """
                INSERT INTO audio_selections (
                  id, recommendation_item_id, campaign_id, rendered_asset_id, audio_catalog_id,
                  status, selected_by, selected_at, payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'selected', ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  status = 'selected',
                  selected_by = excluded.selected_by,
                  selected_at = COALESCE(audio_selections.selected_at, excluded.selected_at),
                  payload_json = excluded.payload_json,
                  updated_at = excluded.updated_at
                """,
                (
                    selection_id,
                    recommendation_item_id,
                    campaign["id"],
                    row.get("rendered_asset_id"),
                    audio["id"],
                    operator,
                    now,
                    json.dumps(self._sanitize_for_storage(selection_payload), ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            self.link_audio_selection_graph(
                selection_id=selection_id,
                recommendation_item_id=recommendation_item_id,
                recommendation_graph_id=row.get("recommendation_graph_id"),
                audio_catalog_id=audio["id"],
                campaign_id=campaign["id"],
            )
            output = json_load(row.get("output_json"), {})
            output["selectedAudio"] = selection_payload["audio"]
            output["audioSelectionStatus"] = "selected"
            output.setdefault("evidence", {}).setdefault("audio", {})["selectionId"] = selection_id
            if row.get("rendered_asset_id"):
                asset_row = self.conn.execute("SELECT caption_generation_json FROM rendered_assets WHERE id = ?", (row["rendered_asset_id"],)).fetchone()
                caption_generation = json_load(asset_row["caption_generation_json"], {}) if asset_row else {}
                audio_intent = caption_generation.get("audioIntent") if isinstance(caption_generation.get("audioIntent"), dict) else {}
                recommendations = (output.get("audioRecommendations") or {}).get("recommendations") or []
                audio_intent.update({
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": True,
                    "status": "selected",
                    "platform": payload.get("platform") or "instagram",
                    "recommendations": recommendations,
                    "operator_selection": {
                        "audio_title": payload.get("title"),
                        "artist_name": payload.get("artistName"),
                        "platform_audio_id": payload.get("nativeAudioId"),
                        "platform_url": payload.get("nativeAudioUrl"),
                        "catalog_audio_id": audio["id"],
                        "audio_memory_graph_id": payload.get("audioMemoryGraphId"),
                        "selected_at": now,
                        "selected_by": operator,
                        "selection_source": "campaign_factory_audio_memory",
                        "notes": notes,
                    },
                    "gates": {
                        "allow_draft_export": True,
                        "allow_preview_schedule": True,
                        "allow_live_schedule": False,
                        "allow_publish": False,
                    },
                })
                caption_generation["audioIntent"] = audio_intent
                caption_generation["audioRecommendations"] = output.get("audioRecommendations") or {}
                self.conn.execute(
                    "UPDATE rendered_assets SET caption_generation_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(self._sanitize_for_storage(caption_generation), ensure_ascii=False, sort_keys=True), now, row["rendered_asset_id"]),
                )
            self.conn.execute(
                "UPDATE recommendation_items SET output_json = ?, evidence_json = ? WHERE id = ?",
                (
                    json.dumps(self._sanitize_for_storage(output), ensure_ascii=False, sort_keys=True),
                    json.dumps(self._sanitize_for_storage(output.get("evidence") or json_load(row.get("evidence_json"), {})), ensure_ascii=False, sort_keys=True),
                    recommendation_item_id,
                ),
            )
            self._record_event(
                "audio_selected",
                campaign_id=campaign["id"],
                rendered_asset_id=row.get("rendered_asset_id"),
                status="success",
                message=f"Audio selected for recommendation {recommendation_item_id}",
                metadata={"selectionId": selection_id, "audioCatalogId": audio["id"], "operator": operator},
                commit=False,
            )
            self.conn.commit()
            return {"schema": "campaign_factory.audio_selection.v1", "selection": self.audio_selection_payload(selection_id), "recommendation": self._recommendation_item(recommendation_item_id)}

    def verify_audio_for_post(
            self,
            post_id: str,
            *,
            proof_url: str,
            proof_note: str | None = None,
            operator: str | None = None,
        ) -> dict[str, Any]:
            row = self.conn.execute(
                "SELECT * FROM performance_snapshots WHERE post_id = ? ORDER BY snapshot_at DESC, created_at DESC LIMIT 1",
                (post_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"performance snapshot not found for post: {post_id}")
            snapshot = dict(row)
            raw = json_load(snapshot.get("raw_json"), {})
            meta = ((raw.get("metadata") or {}).get("campaign_factory") or {}) if isinstance(raw, dict) else {}
            intent = meta.get("audio_intent") if isinstance(meta, dict) else {}
            selection = intent.get("operator_selection") if isinstance(intent, dict) and isinstance(intent.get("operator_selection"), dict) else {}
            audio_id = (
                selection.get("catalog_audio_id")
                or selection.get("catalogAudioId")
                or selection.get("platform_audio_id")
                or selection.get("native_audio_id")
                or selection.get("audio_id")
            )
            if not audio_id:
                raise ValueError("post metadata does not contain selected audio")
            audio = self.audio_catalog_row(str(audio_id), allow_locator=True)
            recommendation_item_id = meta.get("recommendation_item_id") or meta.get("recommendationItemId")
            now = self._utc_now()
            audio_catalog_id = str(audio["id"])
            selection_key = f"{post_id}:{audio_catalog_id}"
            selection_id = f"audsel_{hashlib.sha256(selection_key.encode('utf-8')).hexdigest()[:12]}"
            self.conn.execute(
                """
                INSERT INTO audio_selections (
                  id, recommendation_item_id, campaign_id, rendered_asset_id, post_id, audio_catalog_id,
                  status, proof_url, proof_note, selected_by, selected_at, verified_at,
                  payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'verified', ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  post_id = excluded.post_id,
                  status = 'verified',
                  proof_url = excluded.proof_url,
                  proof_note = excluded.proof_note,
                  verified_at = excluded.verified_at,
                  payload_json = excluded.payload_json,
                  updated_at = excluded.updated_at
                """,
                (
                    selection_id,
                    recommendation_item_id,
                    snapshot["campaign_id"],
                    snapshot.get("rendered_asset_id"),
                    post_id,
                    audio["id"],
                    proof_url,
                    proof_note,
                    operator,
                    selection.get("selected_at") or now,
                    now,
                    json.dumps({"postId": post_id, "proofUrl": proof_url, "proofNote": proof_note, "operatorSelection": selection}, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            self.link_audio_selection_graph(
                selection_id=selection_id,
                recommendation_item_id=recommendation_item_id,
                recommendation_graph_id=self._graph_id_for("recommendation_items", recommendation_item_id, entity_type="recommendation_item") if recommendation_item_id else None,
                audio_catalog_id=audio["id"],
                post_id=post_id,
                performance_snapshot_id=snapshot["id"],
                campaign_id=snapshot["campaign_id"],
            )
            if recommendation_item_id:
                self.resolve_audio_exception_for_recommendation(recommendation_item_id, operator=operator, proof_url=proof_url)
            self.record_audio_performance_snapshot(snapshot, commit=False)
            self.conn.commit()
            return {"schema": "campaign_factory.audio_verification.v1", "selection": self.audio_selection_payload(selection_id)}

    def audio_catalog_row(self, audio_id: str, *, allow_locator: bool = False) -> dict[str, Any]:
            row = self.conn.execute("SELECT * FROM audio_catalog WHERE id = ?", (audio_id,)).fetchone()
            if not row and allow_locator:
                row = self.conn.execute(
                    "SELECT * FROM audio_catalog WHERE native_audio_id = ? OR source_audio_id = ?",
                    (audio_id, audio_id),
                ).fetchone()
            if not row:
                raise ValueError(f"audio catalog record not found: {audio_id}")
            return dict(row)

    def audio_selection_payload(self, selection_id: str) -> dict[str, Any]:
            row = self.conn.execute("SELECT * FROM audio_selections WHERE id = ?", (selection_id,)).fetchone()
            if not row:
                raise ValueError(f"audio selection not found: {selection_id}")
            payload = dict(row)
            payload["payload"] = json_load(payload.pop("payload_json"), {})
            payload["graphId"] = self._graph_id_for("audio_selections", selection_id, entity_type="audio_selection", payload=payload["payload"])
            return payload

    def link_audio_selection_graph(
            self,
            *,
            selection_id: str,
            recommendation_item_id: str | None = None,
            recommendation_graph_id: str | None = None,
            audio_catalog_id: str,
            post_id: str | None = None,
            performance_snapshot_id: str | None = None,
            campaign_id: str | None = None,
        ) -> None:
            selection_graph_id = self._ensure_graph_node("audio_selection", local_table="audio_selections", local_id=selection_id, payload={"selectionId": selection_id})
            audio_graph_id = self._graph_id_for("audio_catalog", audio_catalog_id, entity_type="audio_memory")
            audio_rec_graph_id = None
            if recommendation_item_id:
                audio_rec_id = f"audiorec_{hashlib.sha256(f'{recommendation_item_id}:{audio_catalog_id}'.encode('utf-8')).hexdigest()[:12]}"
                audio_rec_graph_id = self._ensure_graph_node(
                    "audio_recommendation",
                    local_table="audio_selections",
                    local_id=f"recommendation:{audio_rec_id}",
                    payload={"recommendationItemId": recommendation_item_id, "audioCatalogId": audio_catalog_id},
                )
                self._ensure_graph_edge_strict(
                    recommendation_graph_id,
                    audio_rec_graph_id,
                    "recommendation_item_to_audio_recommendation",
                    campaign_id=campaign_id,
                    recommendation_item_id=recommendation_item_id,
                    source_operation="audio_selection",
                )
                self._ensure_graph_edge(audio_rec_graph_id, selection_graph_id, "audio_recommendation_to_audio_selection")
            self._ensure_graph_edge(audio_graph_id, selection_graph_id, "audio_memory_to_audio_selection")
            if post_id:
                post_graph_id = self._ensure_graph_node("threadsdash_post", external_system="threadsdash.posts", external_id=post_id, payload={"postId": post_id})
                self._ensure_graph_edge(selection_graph_id, post_graph_id, "audio_selection_to_threadsdash_post")
            if performance_snapshot_id:
                perf_graph_id = self._graph_id_for("performance_snapshots", performance_snapshot_id, entity_type="performance_snapshot")
                self._ensure_graph_edge(selection_graph_id, perf_graph_id, "audio_selection_to_performance_snapshot")

    def resolve_audio_exception_for_recommendation(self, recommendation_item_id: str, *, operator: str | None, proof_url: str | None) -> None:
            rows = self.conn.execute(
                """
                SELECT id FROM trust_exceptions
                WHERE recommendation_item_id = ? AND status = 'open' AND reason_code = 'unresolved_native_audio'
                """,
                (recommendation_item_id,),
            ).fetchall()
            for row in rows:
                self._resolve_exception(row["id"], resolution=f"Native audio verified: {proof_url or 'proof recorded'}", operator=operator)

    def record_audio_performance_snapshot(self, snapshot: dict[str, Any], *, commit: bool = True) -> dict[str, Any] | None:
            raw = json_load(snapshot.get("raw_json"), {})
            meta = ((raw.get("metadata") or {}).get("campaign_factory") or {}) if isinstance(raw, dict) else {}
            intent = meta.get("audio_intent") if isinstance(meta, dict) else {}
            selection = intent.get("operator_selection") if isinstance(intent, dict) and isinstance(intent.get("operator_selection"), dict) else {}
            recommendations = intent.get("recommendations") if isinstance(intent, dict) and isinstance(intent.get("recommendations"), list) else []
            candidate = selection or next((item for item in recommendations if isinstance(item, dict)), {})
            audio_id = (
                candidate.get("catalog_audio_id")
                or candidate.get("catalogAudioId")
                or candidate.get("platform_audio_id")
                or candidate.get("platformAudioId")
                or candidate.get("native_audio_id")
                or candidate.get("nativeAudioId")
                or candidate.get("audio_id")
                or candidate.get("audioId")
            )
            title = candidate.get("audio_title") or candidate.get("audioTitle") or candidate.get("title")
            artist = candidate.get("artist_name") or candidate.get("artistName") or candidate.get("artist")
            if not audio_id and not title:
                return None
            platform = str(candidate.get("platform") or snapshot.get("platform") or "instagram").strip().lower()
            audio_row = None
            if audio_id:
                audio_row = self.conn.execute(
                    "SELECT * FROM audio_catalog WHERE id = ? OR native_audio_id = ? OR source_audio_id = ?",
                    (audio_id, audio_id, audio_id),
                ).fetchone()
            audio_catalog_id = audio_row["id"] if audio_row else None
            audio_key = f"{platform}:{audio_id}" if audio_id else f"{platform}:{self._slugify(str(title))}:{self._slugify(str(artist or ''))}"
            score = self.performance_snapshot_score(snapshot)
            rollup_key = f"{snapshot['campaign_id']}:{snapshot.get('account_id')}:{snapshot.get('instagram_account_id')}:{audio_key}"
            rollup_id = f"audperf_{hashlib.sha256(rollup_key.encode('utf-8')).hexdigest()[:12]}"
            existing = self.conn.execute("SELECT * FROM audio_performance_rollups WHERE id = ?", (rollup_id,)).fetchone()
            prior_stats = json_load(existing["stats_json"], {}) if existing else {}
            post_ids = set(prior_stats.get("postIds") or [])
            if snapshot.get("post_id"):
                post_ids.add(snapshot["post_id"])
            stats = {
                "postIds": sorted(post_ids),
                "lastPostId": snapshot.get("post_id"),
                "lastStatus": snapshot.get("status"),
                "selectedAudio": selection,
                "recommendedAudioCount": len(recommendations),
            }
            self.conn.execute(
                """
                INSERT INTO audio_performance_rollups (
                  id, campaign_id, account_id, instagram_account_id, audio_catalog_id, audio_key,
                  post_count, view_count, like_count, save_count, share_count, score,
                  last_snapshot_at, stats_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  audio_catalog_id = COALESCE(excluded.audio_catalog_id, audio_performance_rollups.audio_catalog_id),
                  post_count = excluded.post_count,
                  view_count = excluded.view_count,
                  like_count = excluded.like_count,
                  save_count = excluded.save_count,
                  share_count = excluded.share_count,
                  score = excluded.score,
                  last_snapshot_at = excluded.last_snapshot_at,
                  stats_json = excluded.stats_json,
                  updated_at = excluded.updated_at
                """,
                (
                    rollup_id,
                    snapshot["campaign_id"],
                    snapshot.get("account_id"),
                    snapshot.get("instagram_account_id"),
                    audio_catalog_id,
                    audio_key,
                    len(post_ids),
                    int(snapshot.get("views") or 0),
                    int(snapshot.get("likes") or 0),
                    int(snapshot.get("saves") or 0),
                    int(snapshot.get("shares") or 0),
                    score,
                    snapshot.get("snapshot_at"),
                    json.dumps(stats, ensure_ascii=False, sort_keys=True),
                    self._utc_now(),
                ),
            )
            if audio_catalog_id:
                audio_graph_id = self._graph_id_for("audio_catalog", audio_catalog_id, entity_type="audio_memory")
                perf_graph_id = self._graph_id_for("performance_snapshots", snapshot.get("id"), entity_type="performance_snapshot", payload=self._performance_snapshot_payload(snapshot))
                self._ensure_graph_edge(audio_graph_id, perf_graph_id, "audio_memory_to_performance_snapshot", evidence={"audioKey": audio_key})
            if commit:
                self.conn.commit()
            return {"audioKey": audio_key, "audioCatalogId": audio_catalog_id, "score": score}

    def performance_snapshot_score(self, snapshot: dict[str, Any]) -> float:
            views = int(snapshot.get("views") or 0)
            likes = int(snapshot.get("likes") or 0)
            saves = int(snapshot.get("saves") or 0)
            shares = int(snapshot.get("shares") or 0)
            comments = int(snapshot.get("comments") or 0)
            if views <= 0:
                return 0.0
            engagement = ((likes * 1.0) + (comments * 2.0) + (shares * 3.0) + (saves * 4.0)) / max(views, 1)
            return round(min(100.0, max(0.0, 50.0 + engagement * 1000.0)), 3)

    def audio_workflow_summary(self, rendered: list[dict[str, Any]]) -> dict[str, Any]:
            counts = {
                "needs_audio": 0,
                "selected_not_attached": 0,
                "blocked": 0,
                "ready": 0,
            }
            tasks = {
                "open": 0,
                "selected": 0,
                "proof_missing": 0,
                "blocked": 0,
                "needs_review": 0,
                "completed": 0,
                "not_required": 0,
            }
            top: dict[str, dict[str, Any]] = {}
            for asset in rendered:
                intent = self.dashboard_audio_intent_for_asset(asset)
                status = str(intent.get("status") or "needs_operator_selection").strip().lower()
                task = intent.get("task") if isinstance(intent.get("task"), dict) else {}
                task_status = str(task.get("status") or "open").strip().lower()
                if task_status in tasks:
                    tasks[task_status] += 1
                required = intent.get("required") is not False
                if not required or status in {"attached", "verified", "skipped", "not_required"}:
                    counts["ready"] += 1
                elif status == "selected":
                    counts["selected_not_attached"] += 1
                elif status == "blocked":
                    counts["blocked"] += 1
                else:
                    counts["needs_audio"] += 1
                for rec in intent.get("recommendations") or []:
                    if not isinstance(rec, dict):
                        continue
                    key = "|".join([
                        str(rec.get("platform_audio_id") or rec.get("audioId") or ""),
                        str(rec.get("audio_title") or rec.get("audioTitle") or rec.get("title") or "Untitled audio"),
                        str(rec.get("artist_name") or rec.get("artistName") or ""),
                    ])
                    item = top.setdefault(key, {
                        "audio_title": rec.get("audio_title") or rec.get("audioTitle") or rec.get("title"),
                        "artist_name": rec.get("artist_name") or rec.get("artistName"),
                        "platform_audio_id": rec.get("platform_audio_id") or rec.get("audioId"),
                        "platform_url": rec.get("platform_url") or rec.get("platformUrl"),
                        "freshness": rec.get("freshness") or rec.get("trendStatus"),
                        "confidence": rec.get("confidence"),
                        "count": 0,
                        "rendered_asset_ids": [],
                    })
                    item["count"] += 1
                    item["rendered_asset_ids"].append(asset.get("id"))
            return {
                "schema": "campaign_factory.audio_workflow_summary.v1",
                "counts": counts,
                "taskCounts": tasks,
                "topRecommendedAudio": sorted(
                    top.values(),
                    key=lambda item: (-int(item["count"]), str(item.get("audio_title") or "")),
                )[:10],
            }

    def dashboard_audio_intent_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
            caption_generation = asset.get("captionGeneration") or {}
            reference_pattern = asset.get("referencePattern") or {}
            existing = (
                caption_generation.get("audioIntent")
                or caption_generation.get("audio_intent")
                or reference_pattern.get("audioIntent")
                or reference_pattern.get("audio_intent")
            )
            recommendations = asset.get("audioRecommendations") or {}
            recommendation_items = recommendations.get("recommendations") if isinstance(recommendations, dict) else []
            if isinstance(existing, dict):
                intent = self.embedded_audio_intent(existing)
                intent.setdefault("required", True)
                intent.setdefault("status", "recommended" if recommendation_items else "needs_operator_selection")
                intent.setdefault("recommendations", recommendation_items if isinstance(recommendation_items, list) else [])
                if isinstance(recommendations, dict) and recommendations.get("decision"):
                    intent.setdefault("decision", recommendations.get("decision"))
                intent["task"] = self.audio_task_for_dashboard_intent(intent)
                return intent
            intent = {
                "schema": "pipeline.audio_intent.v1",
                "mode": "native_platform_audio",
                "required": True,
                "status": "recommended" if recommendation_items else "needs_operator_selection",
                "recommendations": recommendation_items if isinstance(recommendation_items, list) else [],
                "decision": recommendations.get("decision") if isinstance(recommendations, dict) else None,
            }
            intent["task"] = self.audio_task_for_dashboard_intent(intent)
            return intent

    def embedded_audio_intent(self, intent: dict[str, Any]) -> dict[str, Any]:
            normalized = dict(intent)
            selection = normalized.get("audio_selection") if isinstance(normalized.get("audio_selection"), dict) else {}
            source = str(selection.get("source") or normalized.get("source") or "").strip().lower()
            mode = str(normalized.get("mode") or "").strip().lower()
            if mode != "licensed_music" or source != "local_audio":
                return normalized
            now = self._utc_now()
            path = str(selection.get("path") or "").strip()
            audio_id = selection.get("audio_id") or (hashlib.sha256(path.encode("utf-8")).hexdigest()[:12] if path else "embedded_licensed_audio")
            operator_selection = normalized.get("operator_selection") if isinstance(normalized.get("operator_selection"), dict) else {}
            operator_selection = {
                **operator_selection,
                "audio_id": str(audio_id),
                "track_id": str(audio_id),
                "source": "local_audio",
                "selection_source": "embedded_licensed_audio",
                "selected_at": operator_selection.get("selected_at") or now,
                "attached_at": operator_selection.get("attached_at") or now,
                "notes": operator_selection.get("notes") or "Licensed local audio is muxed into the MP4.",
            }
            normalized.update({
                "schema": "pipeline.audio_intent.v1",
                "mode": "licensed_music",
                "required": True,
                "status": "attached",
                "operator_selection": operator_selection,
                "source": "embedded_licensed_audio",
            })
            return normalized

    def audio_task_for_dashboard_intent(self, intent: dict[str, Any]) -> dict[str, Any]:
            existing = intent.get("task") if isinstance(intent.get("task"), dict) else {}
            status = str(intent.get("status") or "needs_operator_selection").strip().lower()
            safe = status in {"skipped", "not_required"}
            if status in {"attached", "verified"}:
                selection = intent.get("operator_selection") if isinstance(intent.get("operator_selection"), dict) else {}
                final_key = "verified_at" if status == "verified" else "attached_at"
                safe = bool(
                    any(isinstance(selection.get(key), str) and selection.get(key).strip() for key in ("platform_audio_id", "platform_url", "native_audio_id", "native_audio_url", "audio_id"))
                    and isinstance(selection.get("selected_at"), str)
                    and selection.get("selected_at").strip()
                    and isinstance(selection.get(final_key), str)
                    and selection.get(final_key).strip()
                )
            task_status = {
                "not_required": "not_required",
                "recommended": "open",
                "needs_operator_selection": "open",
                "selected": "selected",
                "attached": "completed" if safe else "proof_missing",
                "verified": "completed" if safe else "proof_missing",
                "skipped": "completed",
                "blocked": "blocked",
                "needs_review": "needs_review",
                "burned": "blocked",
            }.get(status, "open")
            return {
                **existing,
                "schema": existing.get("schema") or "pipeline.audio_task.v1",
                "status": task_status,
                "proof_required": bool(intent.get("required", False) and status in {"attached", "verified"}),
                "assignee": existing.get("assignee"),
                "due_at": existing.get("due_at"),
                "created_at": existing.get("created_at"),
                "updated_at": existing.get("updated_at"),
                "completed_at": existing.get("completed_at"),
            }

    def normalize_seconds(self, value: Any) -> float | None:
            if value is None or value == "":
                return None
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            if numeric < 0:
                return None
            return round(numeric, 3)

    def first_metadata_value(self, payload: dict[str, Any], *keys: str) -> Any:
            for key in keys:
                value = payload.get(key)
                if value is not None and value != "":
                    return value
            return None

    def normalize_audio_segment(self, payload: Any) -> dict[str, Any] | None:
            if not isinstance(payload, dict):
                return None
            nested = payload.get("audio_segment") or payload.get("audioSegment")
            if isinstance(nested, dict):
                payload = {**payload, **nested}
            start_seconds = self.normalize_seconds(
                self.first_metadata_value(
                    payload,
                    "start_seconds",
                    "startSeconds",
                    "segment_start_seconds",
                    "segmentStartSeconds",
                    "audio_segment_start_seconds",
                    "audioSegmentStartSeconds",
                )
            )
            if start_seconds is None:
                return None
            duration_seconds = self.normalize_seconds(
                self.first_metadata_value(
                    payload,
                    "duration_seconds",
                    "durationSeconds",
                    "segment_duration_seconds",
                    "segmentDurationSeconds",
                    "audio_segment_duration_seconds",
                    "audioSegmentDurationSeconds",
                )
            )
            label = next(
                (
                    str(value).strip()
                    for value in (
                        payload.get("label"),
                        payload.get("segment_label"),
                        payload.get("segmentLabel"),
                        payload.get("audio_segment_label"),
                        payload.get("audioSegmentLabel"),
                    )
                    if isinstance(value, str) and value.strip()
                ),
                None,
            )
            reason = next(
                (
                    str(value).strip()
                    for value in (
                        payload.get("reason"),
                        payload.get("segment_reason"),
                        payload.get("segmentReason"),
                        payload.get("audio_segment_reason"),
                        payload.get("audioSegmentReason"),
                        payload.get("selected_reason"),
                        payload.get("selectedReason"),
                    )
                    if isinstance(value, str) and value.strip()
                ),
                None,
            )
            result: dict[str, Any] = {"start_seconds": start_seconds}
            if duration_seconds is not None:
                result["duration_seconds"] = duration_seconds
            if label:
                result["label"] = label
            if reason:
                result["reason"] = reason
            return result

    def audio_segment_for_asset(self, audio_intent: dict[str, Any]) -> dict[str, Any] | None:
            if not isinstance(audio_intent, dict):
                return None
            selection = audio_intent.get("operator_selection") if isinstance(audio_intent.get("operator_selection"), dict) else {}
            for payload in (selection, audio_intent):
                normalized = self.normalize_audio_segment(payload)
                if normalized:
                    return normalized
            return None

    def normalize_cover_frame(self, payload: Any) -> dict[str, Any] | None:
            if not isinstance(payload, dict):
                return None
            nested = payload.get("cover_frame") or payload.get("coverFrame")
            if isinstance(nested, dict):
                payload = {**payload, **nested}
            seconds = self.normalize_seconds(
                self.first_metadata_value(
                    payload,
                    "seconds",
                    "cover_frame_seconds",
                    "coverFrameSeconds",
                    "timestamp_seconds",
                    "timestampSeconds",
                    "time_seconds",
                    "timeSeconds",
                )
            )
            if seconds is None:
                return None
            image_path = next(
                (
                    str(value).strip()
                    for value in (
                        payload.get("image_path"),
                        payload.get("imagePath"),
                        payload.get("cover_image_path"),
                        payload.get("coverImagePath"),
                    )
                    if isinstance(value, str) and value.strip()
                ),
                None,
            )
            image_url = next(
                (
                    str(value).strip()
                    for value in (
                        payload.get("image_url"),
                        payload.get("imageUrl"),
                        payload.get("cover_image_url"),
                        payload.get("coverImageUrl"),
                        payload.get("cover_url"),
                        payload.get("coverUrl"),
                    )
                    if isinstance(value, str) and value.strip()
                ),
                None,
            )
            image_hash = next(
                (
                    str(value).strip()
                    for value in (
                        payload.get("image_hash"),
                        payload.get("imageHash"),
                        payload.get("cover_image_hash"),
                        payload.get("coverImageHash"),
                    )
                    if isinstance(value, str) and value.strip()
                ),
                None,
            )
            reason = next(
                (
                    str(value).strip()
                    for value in (
                        payload.get("reason"),
                        payload.get("cover_frame_reason"),
                        payload.get("coverFrameReason"),
                    )
                    if isinstance(value, str) and value.strip()
                ),
                None,
            )
            result: dict[str, Any] = {"seconds": seconds}
            if image_path:
                result["image_path"] = image_path
            if image_url:
                result["image_url"] = image_url
            if image_hash:
                result["image_hash"] = image_hash
            if reason:
                result["reason"] = reason
            return result

    def cover_frame_for_asset(self, asset: dict[str, Any], caption_context: dict[str, Any] | None = None) -> dict[str, Any] | None:
            caption_generation = asset.get("captionGeneration")
            if not isinstance(caption_generation, dict):
                caption_generation = json_load(asset.get("caption_generation_json"), {})
            if not isinstance(caption_generation, dict):
                caption_generation = {}
            for payload in (caption_generation, caption_context or {}, asset):
                normalized = self.normalize_cover_frame(payload)
                if normalized:
                    return normalized
            return None

    def audio_selection_for_asset(self, asset: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
            caption_generation = asset.get("captionGeneration")
            if not isinstance(caption_generation, dict):
                caption_generation = json_load(asset.get("caption_generation_json"), {})
            if not isinstance(caption_generation, dict):
                caption_generation = {}
            audio_intent = caption_generation.get("audioIntent") or caption_generation.get("audio_intent") or {}
            if not isinstance(audio_intent, dict):
                return {}, None
            audio_intent = self.embedded_audio_intent(audio_intent)
            selection = audio_intent.get("operator_selection")
            if not isinstance(selection, dict):
                selection = {}
            audio_id = next(
                (
                    str(value).strip()
                    for value in (
                        selection.get("audio_id"),
                        selection.get("track_id"),
                        selection.get("platform_audio_id"),
                        selection.get("native_audio_id"),
                        selection.get("local_winner_audio_id"),
                        selection.get("platform_url"),
                        selection.get("native_audio_url"),
                    )
                    if isinstance(value, str) and value.strip()
                ),
                None,
            )
            return audio_intent, audio_id

    def audio_intent_is_attached(self, audio_intent: dict[str, Any], audio_id: str | None) -> bool:
            status = str(audio_intent.get("status") or "").strip().lower()
            if status in {"skipped", "not_required"}:
                return True
            if status not in {"attached", "verified"} or not audio_id:
                return False
            selection = audio_intent.get("operator_selection") if isinstance(audio_intent.get("operator_selection"), dict) else {}
            selected_at = isinstance(selection.get("selected_at"), str) and bool(selection.get("selected_at").strip())
            final_key = "verified_at" if status == "verified" else "attached_at"
            final_at = isinstance(selection.get(final_key), str) and bool(selection.get(final_key).strip())
            return selected_at and final_at

    def audio_intent_claims_embedded_media(self, audio_intent: dict[str, Any]) -> bool:
            selection = audio_intent.get("operator_selection") if isinstance(audio_intent.get("operator_selection"), dict) else {}
            probe_values = [
                audio_intent.get("source"),
                audio_intent.get("mode"),
                selection.get("source"),
                selection.get("selection_source"),
                selection.get("notes"),
                selection.get("selected_reason"),
            ]
            haystack = " ".join(str(value or "").lower() for value in probe_values)
            return "embedded" in haystack or "muxed" in haystack or "burned_audio" in haystack

    def embedded_audio_verified(self, output_path: str) -> bool | None:
            if not output_path:
                return None
            path = Path(output_path)
            if path.suffix.lower() not in self._video_exts or not path.exists():
                return None
            metadata = self._probe_video_metadata(path)
            if not metadata.get("ok"):
                return None
            return bool(metadata.get("audioPresent"))
