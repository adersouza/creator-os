from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from campaign_factory.reference_video_remix_stage import (
    REQUIRED_CONTENTFORGE_CHECKS,
    run_reference_video_remix_stage,
)
from PIL import Image
from test_core import add_source_asset, make_factory


class FakeStructuralSeams:
    def __init__(
        self,
        *,
        requires_conditioning: bool = True,
        animation_fails: bool = False,
        qc_ok: bool = True,
    ) -> None:
        self.requires_conditioning = requires_conditioning
        self.animation_fails = animation_fails
        self.qc_ok = qc_ok
        self.calls: list[str] = []
        self.reference_id = ""
        self.reservations = 0

    def analyze_motion(self, reference_video: Path, instruction: str) -> dict:
        self.calls.append("gemini")
        self.reference_id = "reference_video_" + _sha256(reference_video)[:16]
        assert self.reference_id in instruction
        return {
            "schema": "reel_factory.reference_video_motion_analysis.v1",
            "analysisId": "analysis_fake_1",
            "referenceId": self.reference_id,
            "provider": "gemini",
            "model": "gemini-fake",
            "status": "ready",
            "source": {
                "durationSeconds": 5.0,
                "shotCount": 1,
                "hasCuts": False,
                "aspectRatio": "9:16",
            },
            "structure": {
                "hookDescription": "Immediate movement with a readable pose change.",
                "firstFrameDescription": "Centered framing before a shoulder turn.",
                "lastFrameDescription": "The same framing after the shoulder turn.",
                "subjectMotion": "A restrained shoulder turn and weight shift.",
                "cameraMotion": "Small handheld drift without a cut.",
                "pacing": "One continuous movement and final hold.",
                "timeline": [
                    {
                        "startSeconds": 0.0,
                        "endSeconds": 5.0,
                        "action": "Turn slowly and settle.",
                        "camera": "Maintain framing.",
                    }
                ],
            },
            "distinctness": {
                "preserveElements": ["pose_arc", "camera_path", "pacing"],
                "transformElements": [
                    "identity",
                    "wardrobe",
                    "setting",
                    "surface_text",
                ],
                "literalCopyRisk": "medium",
            },
            "sourceTextPolicy": {
                "reuseVerbatim": False,
                "transcriptionUsedForMotionOnly": True,
            },
            "motionPrompt": (
                "Create one continuous vertical shot with a slow shoulder turn, "
                "small weight shift, and a stable final hold."
            ),
            "requiresReferenceVideoConditioning": self.requires_conditioning,
        }

    def quote(self, *, operation: str, provider: str, model: str, soul_id: str) -> dict:
        self.calls.append(f"quote:{operation}")
        return {
            "schema": "reel_factory.higgsfield_provider_quote.v1",
            "operation": operation,
            "provider": provider,
            "model": model,
            "amount": 1.0,
            "unit": "higgsfield_credits",
            "secret": "must-not-persist",
        }

    def reserve(self, quote: dict, max_credits: float, idempotency_key: str) -> dict:
        self.calls.append(f"reserve:{quote['operation']}")
        self.reservations += 1
        return {
            "allowed": True,
            "reservation": {"id": f"reservation_{self.reservations}"},
        }

    def consume(self, reservation_id: str) -> bool:
        self.calls.append(f"consume:{reservation_id}")
        return True

    def cancel(self, reservation_id: str) -> bool:
        self.calls.append(f"cancel:{reservation_id}")
        return True

    def generate_soul_endpoint(
        self,
        *,
        role: str,
        source_frame: Path,
        description: str,
        creator: str,
        soul_id: str,
        workspace: Path,
    ) -> dict:
        self.calls.append(f"generate:{role}")
        path = workspace / f"generated_{role}.png"
        Image.new("RGB", (720, 1280), "#bd5b63" if role == "first" else "#375da8").save(
            path
        )
        return {"jobId": f"endpoint_job_{role}", "imagePath": str(path)}

    def verify_endpoint_approval(
        self,
        *,
        approval_id: str,
        role: str,
        endpoint_path: Path,
        endpoint_sha256: str,
    ) -> dict:
        self.calls.append(f"approval:{role}")
        return {
            "ok": True,
            "decision": "approved",
            "approvalId": approval_id,
            "endpointSha256": endpoint_sha256,
        }

    def animate(
        self,
        *,
        provider: str,
        model: str,
        command: list[str],
        workspace: Path,
    ) -> dict:
        self.calls.append(f"animate:{provider}")
        if self.animation_fails:
            raise RuntimeError("simulated animation provider failure")
        video = workspace / f"{provider}_final.mp4"
        video.write_bytes(f"fake-{provider}-video".encode())
        return {
            "provider": provider,
            "model": model,
            "jobId": f"{provider}_job_1",
            "videoPath": str(video),
        }

    def contentforge_qc(
        self,
        *,
        video_path: Path,
        reference_video: Path,
        first_endpoint: Path,
        last_endpoint: Path,
        required_checks: tuple[str, ...],
        workspace: Path,
    ) -> dict:
        self.calls.append("contentforge")
        report = workspace / "contentforge.json"
        checks = {name: self.qc_ok for name in required_checks}
        report.write_text(json.dumps({"checks": checks}), encoding="utf-8")
        return {"ok": self.qc_ok, "checks": checks, "reportPath": str(report)}


def test_fake_provider_e2e_runs_full_structural_chain_and_records_lineage(
    tmp_path: Path,
) -> None:
    reference = _reference_video(tmp_path)
    factory = make_factory(tmp_path)
    seams = FakeStructuralSeams(requires_conditioning=True)
    try:
        add_source_asset(factory, tmp_path)
        result = run_reference_video_remix_stage(
            factory,
            campaign_slug="may",
            reference_video_path=reference,
            creator="Stacey",
            soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
            workspace=tmp_path,
            operator_selected=True,
            rights_confirmed=True,
            first_frame_approval_id="approval_first",
            last_frame_approval_id="approval_last",
            paid_confirmation=True,
            max_credits=3.0,
            seams=seams,
        )

        assert result["plan"]["animation"]["provider"] == "seedance"
        assert result["creditsSpent"] == 3.0
        assert result["staticFallback"]["paidGeneration"] is False
        assert result["staticFallback"]["render"]["audioBurned"] is False
        assert result["registeredAsset"]["recipe"] == "reference_video_remix"
        assert result["registeredAsset"]["review_state"] == "review_ready"
        assert result["handoffStatus"] == "blocked_pending_final_human_review"
        assert result["schedulingAllowed"] is False
        assert result["publishingAllowed"] is False
        assert seams.calls.count("gemini") == 1
        assert seams.calls.count("approval:first") == 1
        assert seams.calls.count("approval:last") == 1
        assert "animate:seedance" in seams.calls
        assert "contentforge" in seams.calls
        assert len([call for call in seams.calls if call.startswith("reserve:")]) == 3
        lineage_text = Path(result["lineagePath"]).read_text(encoding="utf-8")
        lineage = json.loads(lineage_text)
        assert "must-not-persist" not in lineage_text
        assert lineage["staticFallback"]["lockedStatic"] is True
        assert set(lineage["contentForge"]["checks"]) == set(
            REQUIRED_CONTENTFORGE_CHECKS
        )
        assert lineage["review"]["finalHumanReviewRequired"] is True
    finally:
        factory.close()


def test_structural_chain_routes_kling_when_conditioning_is_not_required(
    tmp_path: Path,
) -> None:
    reference = _reference_video(tmp_path)
    factory = make_factory(tmp_path)
    seams = FakeStructuralSeams(requires_conditioning=False)
    try:
        add_source_asset(factory, tmp_path)
        result = run_reference_video_remix_stage(
            factory,
            campaign_slug="may",
            reference_video_path=reference,
            creator="Stacey",
            soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
            workspace=tmp_path,
            operator_selected=True,
            rights_confirmed=True,
            first_frame_approval_id="approval_first",
            last_frame_approval_id="approval_last",
            paid_confirmation=True,
            max_credits=3.0,
            seams=seams,
        )
        assert result["plan"]["animation"]["provider"] == "kling"
        assert "animate:kling" in seams.calls
    finally:
        factory.close()


@pytest.mark.parametrize("failure", ["provider", "qc"])
def test_structural_failures_preserve_static_fallback_and_block_handoff(
    tmp_path: Path, failure: str
) -> None:
    reference = _reference_video(tmp_path)
    factory = make_factory(tmp_path)
    seams = FakeStructuralSeams(
        animation_fails=failure == "provider", qc_ok=failure != "qc"
    )
    try:
        add_source_asset(factory, tmp_path)
        with pytest.raises(RuntimeError):
            run_reference_video_remix_stage(
                factory,
                campaign_slug="may",
                reference_video_path=reference,
                creator="Stacey",
                soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
                workspace=tmp_path,
                operator_selected=True,
                rights_confirmed=True,
                first_frame_approval_id="approval_first",
                last_frame_approval_id="approval_last",
                paid_confirmation=True,
                max_credits=3.0,
                seams=seams,
            )
        static = factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE recipe = 'static_mp4'"
        ).fetchone()
        assert static is not None
        assert Path(static["output_path"]).is_file()
        assert (
            factory.conn.execute(
                "SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'reference_video_remix'"
            ).fetchone()[0]
            == 0
        )
        job = factory.conn.execute(
            "SELECT status FROM pipeline_jobs WHERE job_type = 'reference_video_remix'"
        ).fetchone()
        assert job["status"] == "failed"
    finally:
        factory.close()


def test_structural_paid_run_fails_before_any_seam_without_both_approvals(
    tmp_path: Path,
) -> None:
    seams = FakeStructuralSeams()
    factory = make_factory(tmp_path)
    try:
        add_source_asset(factory, tmp_path)
        with pytest.raises(ValueError, match="last_frame_approval_id"):
            run_reference_video_remix_stage(
                factory,
                campaign_slug="may",
                reference_video_path=_reference_video(tmp_path),
                creator="Stacey",
                soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
                workspace=tmp_path,
                operator_selected=True,
                rights_confirmed=True,
                first_frame_approval_id="approval_first",
                last_frame_approval_id="",
                paid_confirmation=True,
                max_credits=3.0,
                seams=seams,
            )
        assert seams.calls == []
    finally:
        factory.close()


@pytest.mark.parametrize("max_credits", [0.0, -1.0, float("nan"), float("inf")])
def test_structural_paid_run_requires_finite_positive_credit_cap(
    tmp_path: Path, max_credits: float
) -> None:
    seams = FakeStructuralSeams()
    factory = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="finite and positive"):
            run_reference_video_remix_stage(
                factory,
                campaign_slug="may",
                reference_video_path=tmp_path / "missing.mp4",
                creator="Stacey",
                soul_id="soul",
                workspace=tmp_path,
                operator_selected=True,
                rights_confirmed=True,
                first_frame_approval_id="first",
                last_frame_approval_id="last",
                paid_confirmation=True,
                max_credits=max_credits,
                seams=seams,
            )
        assert seams.calls == []
    finally:
        factory.close()


def _reference_video(tmp_path: Path) -> Path:
    path = tmp_path / "reference.mp4"
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=180x320:rate=2:duration=5",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
