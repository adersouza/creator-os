from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Protocol

from creator_os_core.fileops import atomic_write_text

STACEY_SOUL_ID = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"
ACCEPTANCE_COHORT_ID = "stacey_learning_cohort_v1"


class RealProviderAcceptanceSeams(Protocol):
    def verify_soul(self, soul_id: str) -> dict[str, Any]: ...

    def quote(self, soul_id: str) -> dict[str, Any]: ...

    def reserve(self, quote: dict[str, Any], max_credits: float) -> dict[str, Any]: ...

    def consume(self, reservation_id: str) -> bool: ...

    def cancel(self, reservation_id: str) -> bool: ...

    def generate(self, soul_id: str, workspace: Path) -> dict[str, Any]: ...

    def render_static_mp4(
        self, image_path: Path, workspace: Path
    ) -> dict[str, Any]: ...

    def reel_qc(self, mp4_path: Path, lineage: dict[str, Any]) -> dict[str, Any]: ...

    def contentforge_qc(self, mp4_path: Path) -> dict[str, Any]: ...

    def hmac_ingest_preview_draft(
        self, mp4_path: Path, lineage: dict[str, Any]
    ) -> dict[str, Any]: ...

    def verify_draft(
        self, ingest: dict[str, Any], lineage: dict[str, Any]
    ) -> dict[str, Any]: ...


def run_real_provider_acceptance(
    *,
    workspace: Path,
    target_environment: str,
    paid_confirmation: bool,
    max_credits: float,
    seams: RealProviderAcceptanceSeams,
) -> dict[str, Any]:
    if not paid_confirmation:
        raise ValueError("explicit paid confirmation is required")
    if target_environment not in {"preview", "production"}:
        raise ValueError("target_environment must be preview or production")
    if (
        isinstance(max_credits, bool)
        or not isinstance(max_credits, (int, float))
        or not math.isfinite(float(max_credits))
        or float(max_credits) <= 0
    ):
        raise ValueError("max_credits must be finite and positive")
    workspace = Path(workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    reservation_id: str | None = None
    consumed = False
    try:
        soul = seams.verify_soul(STACEY_SOUL_ID)
        if str(soul.get("id") or soul.get("soulId") or "") != STACEY_SOUL_ID:
            raise RuntimeError("Stacey Soul ID verification mismatch")
        quote = seams.quote(STACEY_SOUL_ID)
        quote_amount = _positive_credits(quote)
        if quote_amount > float(max_credits):
            raise RuntimeError("provider quote exceeds acceptance max credits")
        reservation = seams.reserve(quote, float(max_credits))
        if not reservation.get("allowed"):
            raise RuntimeError(
                str(reservation.get("blockingReason") or "credit reservation blocked")
            )
        reservation_id = _reservation_id(reservation)
        if not seams.consume(reservation_id):
            raise RuntimeError("failed to consume provider reservation")
        consumed = True

        generation = seams.generate(STACEY_SOUL_ID, workspace)
        image_path = Path(str(generation.get("imagePath") or ""))
        if not image_path.is_file():
            raise RuntimeError("provider generation did not produce an image")
        image_hash = _sha256(image_path)
        lineage = {
            "schema": "campaign_factory.real_provider_acceptance_lineage.v1",
            "creator": "Stacey",
            "soulId": STACEY_SOUL_ID,
            "providerJobId": generation.get("jobId"),
            "providerQuote": _redacted_quote(quote),
            "providerReservationId": reservation_id,
            "imageSha256": image_hash,
            "targetEnvironment": target_environment,
            "cohortId": ACCEPTANCE_COHORT_ID,
            "scheduleMode": "draft",
            "publishRequested": False,
        }
        render = seams.render_static_mp4(image_path, workspace)
        mp4_path = Path(str(render.get("mp4Path") or ""))
        if not mp4_path.is_file():
            raise RuntimeError("static MP4 render missing")
        lineage["mp4Sha256"] = _sha256(mp4_path)
        reel_qc = seams.reel_qc(mp4_path, lineage)
        contentforge_qc = seams.contentforge_qc(mp4_path)
        if not reel_qc.get("ok") or not contentforge_qc.get("ok"):
            raise RuntimeError("Reel Factory or ContentForge QC failed")
        ingest = seams.hmac_ingest_preview_draft(mp4_path, lineage)
        verification = seams.verify_draft(ingest, lineage)
        if not verification.get("ok"):
            raise RuntimeError("preview draft verification failed")

        artifact = {
            "schema": "campaign_factory.real_provider_acceptance.v1",
            "ok": True,
            "targetEnvironment": target_environment,
            "paidConfirmation": True,
            "maxCredits": float(max_credits),
            "quote": _redacted_quote(quote),
            "reservation": {
                "id": reservation_id,
                "status": "consumed",
                "amount": quote_amount,
                "unit": "higgsfield_credits",
            },
            "provider": {
                "jobId": generation.get("jobId"),
                "imageSha256": image_hash,
            },
            "render": {
                "mp4Sha256": lineage["mp4Sha256"],
                "static": True,
                "audioBurned": False,
            },
            "qc": {"reelFactory": reel_qc, "contentforge": contentforge_qc},
            "lineage": lineage,
            "hmacIngest": _safe_ingest_summary(ingest),
            "draftVerification": verification,
            "scheduleRequested": False,
            "publishRequested": False,
        }
        artifact_path = workspace / "real_provider_acceptance.redacted.json"
        atomic_write_text(
            artifact_path,
            json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {**artifact, "artifactPath": str(artifact_path)}
    except Exception:
        if reservation_id and not consumed:
            seams.cancel(reservation_id)
        raise


class JsonCommandAcceptanceSeams:
    """Production seam adapter for an operator-reviewed JSON phase driver.

    The driver command is local, inherits secrets through its environment, and
    receives no credentials in argv or JSON. Each call receives a phase and
    redacted phase inputs on stdin and must return one JSON object on stdout.
    """

    def __init__(self, command: str | None = None) -> None:
        command = command or os.environ.get("CREATOR_OS_ACCEPTANCE_DRIVER")
        if not command:
            raise ValueError(
                "CREATOR_OS_ACCEPTANCE_DRIVER is required for a real-provider run"
            )
        self.command = shlex.split(command)

    def _call(self, phase: str, **payload: Any) -> dict[str, Any]:
        completed = subprocess.run(
            self.command,
            input=json.dumps({"phase": phase, **payload}, sort_keys=True),
            text=True,
            capture_output=True,
            check=False,
            timeout=900,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"acceptance driver phase failed: {phase}")
        try:
            value = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"acceptance driver returned invalid JSON: {phase}"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"acceptance driver returned non-object JSON: {phase}")
        return value

    def verify_soul(self, soul_id: str) -> dict[str, Any]:
        return self._call("verify_soul", soulId=soul_id)

    def quote(self, soul_id: str) -> dict[str, Any]:
        return self._call("quote", soulId=soul_id)

    def reserve(self, quote: dict[str, Any], max_credits: float) -> dict[str, Any]:
        return self._call(
            "reserve", quote=_redacted_quote(quote), maxCredits=max_credits
        )

    def consume(self, reservation_id: str) -> bool:
        return bool(self._call("consume", reservationId=reservation_id).get("ok"))

    def cancel(self, reservation_id: str) -> bool:
        return bool(self._call("cancel", reservationId=reservation_id).get("ok"))

    def generate(self, soul_id: str, workspace: Path) -> dict[str, Any]:
        return self._call("generate", soulId=soul_id, workspace=str(workspace))

    def render_static_mp4(self, image_path: Path, workspace: Path) -> dict[str, Any]:
        return self._call(
            "render_static_mp4", imagePath=str(image_path), workspace=str(workspace)
        )

    def reel_qc(self, mp4_path: Path, lineage: dict[str, Any]) -> dict[str, Any]:
        return self._call("reel_qc", mp4Path=str(mp4_path), lineage=lineage)

    def contentforge_qc(self, mp4_path: Path) -> dict[str, Any]:
        return self._call("contentforge_qc", mp4Path=str(mp4_path))

    def hmac_ingest_preview_draft(
        self, mp4_path: Path, lineage: dict[str, Any]
    ) -> dict[str, Any]:
        return self._call(
            "hmac_ingest_preview_draft", mp4Path=str(mp4_path), lineage=lineage
        )

    def verify_draft(
        self, ingest: dict[str, Any], lineage: dict[str, Any]
    ) -> dict[str, Any]:
        return self._call(
            "verify_draft", ingest=_safe_ingest_summary(ingest), lineage=lineage
        )


def _positive_credits(quote: dict[str, Any]) -> float:
    amount = quote.get("amount")
    if (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(float(amount))
        or float(amount) <= 0
        or quote.get("unit") != "higgsfield_credits"
    ):
        raise RuntimeError("provider quote must contain positive Higgsfield credits")
    return float(amount)


def _reservation_id(reservation: dict[str, Any]) -> str:
    detail = reservation.get("reservation")
    value = detail.get("id") if isinstance(detail, dict) else None
    if not isinstance(value, str) or not value:
        raise RuntimeError("credit reservation did not return an id")
    return value


def _redacted_quote(quote: dict[str, Any]) -> dict[str, Any]:
    return {
        key: quote.get(key)
        for key in ("schema", "provider", "model", "amount", "unit")
        if quote.get(key) is not None
    }


def _safe_ingest_summary(ingest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ingest.get(key)
        for key in ("statusCode", "postIds", "attempts", "draftKey")
        if ingest.get(key) is not None
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
