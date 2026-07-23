"""Durable, single-machine admission control for local video generation.

This is deliberately a synchronous lease/admission journal, not an executable
background queue. It does not import a model runtime, provider client, Campaign
Factory, or publishing code. Callers submit fully fingerprinted local work and
execute the exact same request while holding ``worker_session``.

State is an append-only, fsync'd JSONL event journal.  A single advisory
``flock`` lease prevents multiple local model workers from competing for unified
memory.  If a process exits without a terminal event, the next lease holder
records the abandoned job as interrupted before admitting new work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import socket
import subprocess
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

from .fileops import atomic_write_json, file_lock

JOURNAL_SCHEMA: Final = "reel_factory.local_generation_journal.v1"
HARDWARE_SCHEMA: Final = "reel_factory.local_hardware_fingerprint.v1"


class LocalQueueError(RuntimeError):
    """Base class for local generation queue failures."""


class JournalCorruptionError(LocalQueueError):
    """Raised when unacknowledged malformed journal records are present."""


class WorkerLeaseUnavailable(LocalQueueError):
    """Raised when another process owns the machine-local generation lease."""


class InvalidJobTransition(LocalQueueError):
    """Raised when a requested job transition is not valid."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def fingerprint(value: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 for a JSON-compatible mapping."""

    return hashlib.sha256(_canonical_json(value)).hexdigest()


class SerializableEvidenceRecord(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


EvidenceRecord = Mapping[str, Any] | SerializableEvidenceRecord


def evidence_record_payload(record: EvidenceRecord) -> dict[str, Any]:
    """Return one canonical record mapping without importing its owner package."""

    payload = dict(record) if isinstance(record, Mapping) else record.to_dict()
    if not isinstance(payload, dict):
        raise ValueError("benchmark_evidence_record_must_serialize_to_mapping")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _physical_memory_bytes() -> int | None:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, TypeError, ValueError):
        return None
    total = pages * page_size
    return total if total > 0 else None


def _macos_available_memory_bytes() -> int | None:
    """Return a conservative current-memory estimate from macOS ``vm_stat``."""

    if platform.system() != "Darwin":
        return None
    try:
        completed = subprocess.run(
            ["/usr/bin/vm_stat"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    lines = completed.stdout.splitlines()
    if not lines:
        return None
    page_size = 4096
    marker = "page size of "
    if marker in lines[0]:
        try:
            page_size = int(lines[0].split(marker, 1)[1].split(" bytes", 1)[0])
        except (IndexError, ValueError):
            return None
    counts: dict[str, int] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        label, raw = line.split(":", 1)
        try:
            counts[label.strip()] = int(raw.strip().rstrip("."))
        except ValueError:
            continue
    available_pages = sum(
        counts.get(label, 0)
        for label in (
            "Pages free",
            "Pages inactive",
            "Pages speculative",
        )
    )
    available = available_pages * page_size
    return available if available > 0 else None


def hardware_identity() -> dict[str, Any]:
    """Describe and fingerprint hardware without exposing the hostname."""

    payload: dict[str, Any] = {
        "schema": HARDWARE_SCHEMA,
        "machine": platform.machine() or "unknown",
        "processor": platform.processor() or "unknown",
        "system": platform.system() or "unknown",
        "release": platform.release() or "unknown",
        "physicalMemoryBytes": _physical_memory_bytes(),
        "hostFingerprint": hashlib.sha256(socket.gethostname().encode()).hexdigest(),
    }
    payload["fingerprint"] = fingerprint(payload)
    return payload


def _local_cost_observation() -> dict[str, Any]:
    """Describe local compute cost honestly when no meter is installed."""

    return {
        "available": False,
        "currency": "USD",
        "reason": "local_compute_cost_not_metered",
        "value": None,
    }


def _failure_class(error: BaseException) -> str:
    """Return a stable local-execution failure class without hiding details."""

    message = str(error)
    if isinstance(error, subprocess.TimeoutExpired):
        return "subprocess_timeout"
    if isinstance(error, MemoryError):
        return "memory_exhausted"
    if isinstance(error, OSError):
        return "operating_system_error"
    if message.startswith("local_video_generation_failed"):
        return "model_process_nonzero_exit"
    if message.startswith("local_video_output_missing"):
        return "generated_output_missing"
    if "validation" in message or "probe" in message or "duration" in message:
        return "generated_output_validation_failed"
    return "local_generation_runtime_error"


def _optional_execution_measurement(
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if value is None:
        return {
            "available": False,
            "reason": "execution_measurement_unavailable",
        }
    try:
        wall_time = float(value["wallTimeSeconds"])
        peak_memory = int(value["peakMemoryBytes"])
        method = str(value["memoryMeasurementMethod"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("execution_measurement_invalid") from exc
    if (
        not math.isfinite(wall_time)
        or wall_time <= 0
        or peak_memory <= 0
        or not method.strip()
    ):
        raise ValueError("execution_measurement_invalid")
    return {
        "available": True,
        "wallTimeSeconds": wall_time,
        "peakMemoryBytes": peak_memory,
        "memoryMeasurementMethod": method,
    }


@dataclass(frozen=True)
class JournalIssue:
    line_number: int
    line_sha256: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "lineNumber": self.line_number,
            "lineSha256": self.line_sha256,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class JournalRead:
    events: tuple[dict[str, Any], ...]
    issues: tuple[JournalIssue, ...]


class AppendOnlyJournal:
    """Fsync'd, hash-chained JSONL journal with explicit corruption recovery."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._coordination_path = self.path.with_suffix(
            self.path.suffix + ".coordination"
        )

    def read(self, *, allow_unacknowledged_issues: bool = False) -> JournalRead:
        if not self.path.exists():
            return JournalRead(events=(), issues=())
        events: list[dict[str, Any]] = []
        issues: list[JournalIssue] = []
        acknowledged: set[str] = set()
        previous_hash: str | None = None
        expected_sequence = 1
        with self.path.open("rb") as handle:
            for number, raw_line in enumerate(handle, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                digest = hashlib.sha256(stripped).hexdigest()
                try:
                    event = json.loads(stripped)
                    if not isinstance(event, dict):
                        raise ValueError("event is not a JSON object")
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                    issues.append(
                        JournalIssue(
                            line_number=number,
                            line_sha256=digest,
                            reason=type(exc).__name__,
                        )
                    )
                    continue
                claimed_hash = event.get("eventHash")
                hash_payload = dict(event)
                hash_payload.pop("eventHash", None)
                integrity_error: str | None = None
                if event.get("schema") != JOURNAL_SCHEMA:
                    integrity_error = "unexpected_schema"
                elif event.get("sequence") != expected_sequence:
                    integrity_error = "non_contiguous_sequence"
                elif event.get("previousEventHash") != previous_hash:
                    integrity_error = "previous_event_hash_mismatch"
                elif claimed_hash != fingerprint(hash_payload):
                    integrity_error = "event_hash_mismatch"
                if integrity_error is not None:
                    issues.append(
                        JournalIssue(
                            line_number=number,
                            line_sha256=digest,
                            reason=integrity_error,
                        )
                    )
                    continue
                events.append(event)
                previous_hash = str(claimed_hash)
                expected_sequence += 1
                if event.get("eventType") == "journal_recovery_recorded":
                    recovered = event.get("payload", {}).get(
                        "recoveredIssueDigests", []
                    )
                    if isinstance(recovered, list):
                        acknowledged.update(str(item) for item in recovered)
        unresolved = tuple(
            issue for issue in issues if issue.line_sha256 not in acknowledged
        )
        if unresolved and not allow_unacknowledged_issues:
            raise JournalCorruptionError(
                f"local_generation_journal_corrupt:{len(unresolved)}_unacknowledged_record(s)"
            )
        return JournalRead(events=tuple(events), issues=unresolved)

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        allow_unacknowledged_issues: bool = False,
    ) -> dict[str, Any]:
        if not event_type.strip():
            raise ValueError("event_type must be non-empty")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self._coordination_path):
            read = self.read(allow_unacknowledged_issues=allow_unacknowledged_issues)
            previous_hash = (
                str(read.events[-1].get("eventHash")) if read.events else None
            )
            event: dict[str, Any] = {
                "schema": JOURNAL_SCHEMA,
                "sequence": len(read.events) + 1,
                "eventId": str(uuid.uuid4()),
                "eventType": event_type,
                "occurredAt": _utc_now(),
                "previousEventHash": previous_hash,
                "payload": dict(payload),
            }
            event["eventHash"] = fingerprint(event)
            encoded = _canonical_json(event) + b"\n"
            flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
            descriptor = os.open(self.path, flags, 0o600)
            try:
                if os.path.getsize(self.path) > 0:
                    with self.path.open("rb") as check:
                        check.seek(-1, os.SEEK_END)
                        if check.read(1) != b"\n":
                            os.write(descriptor, b"\n")
                written = os.write(descriptor, encoded)
                if written != len(encoded):
                    raise OSError("short append to local generation journal")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return event

    def acknowledge_corruption(self) -> dict[str, Any] | None:
        """Preserve malformed records and append an explicit recovery marker."""

        read = self.read(allow_unacknowledged_issues=True)
        if not read.issues:
            return None
        return self.append(
            "journal_recovery_recorded",
            {
                "recoveredIssueDigests": [issue.line_sha256 for issue in read.issues],
                "issues": [issue.as_dict() for issue in read.issues],
                "recoveryPolicy": "preserve_malformed_record_and_skip_during_replay",
            },
            allow_unacknowledged_issues=True,
        )


@dataclass(frozen=True)
class LocalGenerationJob:
    job_id: str
    model_id: str
    model_fingerprint: str
    task_kind: str
    task_fingerprint: str
    input_fingerprint: str
    requested_memory_bytes: int
    params_fingerprint: str
    owned_artifact_paths: tuple[str, ...] = ()
    creator_identity_profile_id: str | None = None
    creator_identity_profile_fingerprint: str | None = None
    content_intent_id: str | None = None
    content_intent_fingerprint: str | None = None
    benchmark_recipe_id: str | None = None
    benchmark_recipe_fingerprint: str | None = None
    analyzer_registry_id: str | None = None
    analyzer_registry_fingerprint: str | None = None
    runtime_binding: Mapping[str, Any] | None = None
    runtime_binding_fingerprint: str | None = None
    license_policy: Mapping[str, Any] | None = None
    license_policy_fingerprint: str | None = None
    router_decision_id: str | None = None
    router_decision_fingerprint: str | None = None
    router_capability_cohort: str | None = None
    router_cohort_fingerprint: str | None = None
    arena_summary_fingerprint: str | None = None
    arena_plan_fingerprint: str | None = None
    local_motion_admission_fingerprint: str | None = None
    selected_model_fingerprint: str | None = None
    model_deep_verification_fingerprint: str | None = None
    promotion_approval_event_id: str | None = None
    promotion_approval_event_hash: str | None = None
    promotion_hardware_fingerprint: str | None = None
    promotion_evidence_fingerprint: str | None = None
    promotion_benchmark_ids_fingerprint: str | None = None

    def __post_init__(self) -> None:
        record_linkage = (
            self.creator_identity_profile_id,
            self.creator_identity_profile_fingerprint,
            self.content_intent_id,
            self.content_intent_fingerprint,
        )
        if any(value is not None for value in record_linkage) and not all(
            value is not None for value in record_linkage
        ):
            raise ValueError("job_identity_intent_linkage_must_be_complete")
        if self.creator_identity_profile_id is not None:
            if (
                not self.creator_identity_profile_id.strip()
                or self.content_intent_id is None
                or not self.content_intent_id.strip()
            ):
                raise ValueError("job_identity_intent_linkage_ids_must_be_non_empty")
            for value in (
                self.creator_identity_profile_fingerprint,
                self.content_intent_fingerprint,
            ):
                if (
                    value is None
                    or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)
                ):
                    raise ValueError(
                        "job_identity_intent_linkage_fingerprints_must_be_sha256"
                    )
        linkage = (
            self.benchmark_recipe_id,
            self.benchmark_recipe_fingerprint,
            self.analyzer_registry_id,
            self.analyzer_registry_fingerprint,
        )
        if any(value is not None for value in linkage) and not all(
            value is not None for value in linkage
        ):
            raise ValueError("benchmark_evidence_linkage_must_be_complete")
        if self.benchmark_recipe_id is not None:
            if (
                not self.benchmark_recipe_id.strip()
                or self.analyzer_registry_id is None
                or not self.analyzer_registry_id.strip()
            ):
                raise ValueError("benchmark_evidence_linkage_ids_must_be_non_empty")
            for value in (
                self.benchmark_recipe_fingerprint,
                self.analyzer_registry_fingerprint,
            ):
                if (
                    value is None
                    or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)
                ):
                    raise ValueError(
                        "benchmark_evidence_linkage_fingerprints_must_be_sha256"
                    )
        execution_evidence = (
            self.runtime_binding,
            self.runtime_binding_fingerprint,
            self.license_policy,
            self.license_policy_fingerprint,
        )
        if any(value is not None for value in execution_evidence) and not all(
            value is not None for value in execution_evidence
        ):
            raise ValueError("job_runtime_license_evidence_must_be_complete")
        if self.runtime_binding is not None:
            if (
                not isinstance(self.runtime_binding, Mapping)
                or not isinstance(self.license_policy, Mapping)
                or fingerprint(self.runtime_binding) != self.runtime_binding_fingerprint
                or fingerprint(self.license_policy) != self.license_policy_fingerprint
            ):
                raise ValueError("job_runtime_license_evidence_invalid")
        router_linkage = (
            self.router_decision_id,
            self.router_decision_fingerprint,
            self.router_capability_cohort,
            self.router_cohort_fingerprint,
            self.arena_summary_fingerprint,
            self.arena_plan_fingerprint,
            self.local_motion_admission_fingerprint,
            self.selected_model_fingerprint,
            self.model_deep_verification_fingerprint,
            self.promotion_approval_event_id,
            self.promotion_approval_event_hash,
            self.promotion_hardware_fingerprint,
            self.promotion_evidence_fingerprint,
            self.promotion_benchmark_ids_fingerprint,
        )
        if any(value is not None for value in router_linkage) and not all(
            value is not None for value in router_linkage
        ):
            raise ValueError("job_router_promotion_linkage_must_be_complete")
        if self.router_decision_id is not None:
            if (
                not self.router_decision_id.strip()
                or self.router_capability_cohort is None
                or not self.router_capability_cohort.strip()
                or self.promotion_approval_event_id is None
                or not self.promotion_approval_event_id.strip()
                or self.selected_model_fingerprint != self.model_fingerprint
            ):
                raise ValueError("job_router_promotion_linkage_ids_must_be_non_empty")
            for value in (
                self.router_decision_fingerprint,
                self.router_cohort_fingerprint,
                self.arena_summary_fingerprint,
                self.arena_plan_fingerprint,
                self.local_motion_admission_fingerprint,
                self.selected_model_fingerprint,
                self.model_deep_verification_fingerprint,
                self.promotion_approval_event_hash,
                self.promotion_hardware_fingerprint,
                self.promotion_evidence_fingerprint,
                self.promotion_benchmark_ids_fingerprint,
            ):
                if (
                    value is None
                    or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)
                ):
                    raise ValueError(
                        "job_router_promotion_linkage_fingerprints_must_be_sha256"
                    )

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        model_id: str,
        model_revision: str,
        model_manifest_sha256: str,
        task_kind: str,
        input_sha256: str,
        requested_memory_bytes: int,
        params: Mapping[str, Any],
        cohort: Mapping[str, Any] | None = None,
        owned_artifact_paths: Sequence[Path] = (),
        benchmark_recipe: EvidenceRecord | None = None,
        analyzer_registry: EvidenceRecord | None = None,
        creator_identity_profile: EvidenceRecord | None = None,
        content_intent: EvidenceRecord | None = None,
        runtime_binding: Mapping[str, Any] | None = None,
        license_policy: Mapping[str, Any] | None = None,
        router_promotion_linkage: Mapping[str, Any] | None = None,
    ) -> LocalGenerationJob:
        for name, value in {
            "job_id": job_id,
            "model_id": model_id,
            "model_revision": model_revision,
            "task_kind": task_kind,
        }.items():
            if not value.strip():
                raise ValueError(f"{name} must be non-empty")
        for name, value in {
            "model_manifest_sha256": model_manifest_sha256,
            "input_sha256": input_sha256,
        }.items():
            if len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if requested_memory_bytes <= 0:
            raise ValueError("requested_memory_bytes must be positive")
        model_fp = fingerprint(
            {
                "modelId": model_id,
                "modelRevision": model_revision,
                "modelManifestSha256": model_manifest_sha256,
            }
        )
        params_fp = fingerprint(params)
        recipe_payload: dict[str, Any] = {}
        registry_payload: dict[str, Any] = {}
        profile_payload: dict[str, Any] = {}
        intent_payload: dict[str, Any] = {}
        if (creator_identity_profile is None) != (content_intent is None):
            raise ValueError("identity_intent_evidence_records_must_be_paired")
        if creator_identity_profile is not None and content_intent is not None:
            profile_payload = evidence_record_payload(creator_identity_profile)
            intent_payload = evidence_record_payload(content_intent)
            if (
                profile_payload.get("schema")
                != "creator_os.creator_identity_profile.v1"
            ):
                raise ValueError("creator_identity_profile_schema_mismatch")
            if intent_payload.get("schema") != "creator_os.content_intent.v1":
                raise ValueError("content_intent_schema_mismatch")
            if (
                not str(profile_payload.get("profileId") or "").strip()
                or not str(intent_payload.get("intentId") or "").strip()
            ):
                raise ValueError("identity_intent_evidence_ids_missing")
            if intent_payload.get("creatorIdentityProfileId") != profile_payload.get(
                "profileId"
            ):
                raise ValueError("content_intent_creator_profile_mismatch")
        if (benchmark_recipe is None) != (analyzer_registry is None):
            raise ValueError("benchmark_evidence_records_must_be_paired")
        if benchmark_recipe is not None and analyzer_registry is not None:
            recipe_payload = evidence_record_payload(benchmark_recipe)
            registry_payload = evidence_record_payload(analyzer_registry)
            if recipe_payload.get("schema") != "creator_os.benchmark_recipe.v1":
                raise ValueError("benchmark_recipe_schema_mismatch")
            if registry_payload.get("schema") != "creator_os.analyzer_registry.v1":
                raise ValueError("analyzer_registry_schema_mismatch")
            if recipe_payload.get("expectedProviderCalls") != 0:
                raise ValueError("benchmark_recipe_provider_calls_must_be_zero")
            if recipe_payload.get("productionWritesAllowed") is not False:
                raise ValueError("benchmark_recipe_production_writes_must_be_false")
            if recipe_payload.get("taskKind") != task_kind:
                raise ValueError("benchmark_recipe_task_kind_mismatch")
            if not str(recipe_payload.get("recipeId") or "").strip():
                raise ValueError("benchmark_recipe_id_missing")
            if not str(registry_payload.get("registryId") or "").strip():
                raise ValueError("analyzer_registry_id_missing")
            raw_registrations = registry_payload.get("analyzers")
            raw_requirements = recipe_payload.get("requiredAnalyzers")
            if not isinstance(raw_registrations, list) or not raw_registrations:
                raise ValueError("analyzer_registry_registrations_missing")
            if not isinstance(raw_requirements, list) or not raw_requirements:
                raise ValueError("benchmark_recipe_required_analyzers_missing")
            registered = {
                (str(registration["analyzerId"]), str(registration["analyzerVersion"]))
                for registration in raw_registrations
                if isinstance(registration, dict)
                and registration.get("analyzerId")
                and registration.get("analyzerVersion")
            }
            required = {
                (str(requirement["analyzerId"]), str(requirement["analyzerVersion"]))
                for requirement in raw_requirements
                if isinstance(requirement, dict)
                and requirement.get("analyzerId")
                and requirement.get("analyzerVersion")
            }
            if len(registered) != len(raw_registrations):
                raise ValueError("analyzer_registry_registration_invalid")
            if len(required) != len(raw_requirements):
                raise ValueError("benchmark_recipe_analyzer_requirement_invalid")
            if not required.issubset(registered):
                raise ValueError("benchmark_recipe_required_analyzer_unregistered")
        if (runtime_binding is None) != (license_policy is None):
            raise ValueError("runtime_license_evidence_must_be_paired")
        runtime_payload = dict(runtime_binding) if runtime_binding is not None else {}
        license_payload = dict(license_policy) if license_policy is not None else {}
        if runtime_binding is not None:
            if not str(runtime_payload.get("runtimeId") or "").strip():
                raise ValueError("runtime_binding_id_missing")
            if not str(license_payload.get("licenseId") or "").strip():
                raise ValueError("license_policy_id_missing")
            if license_payload.get("commercialUseAllowed") is not True:
                raise ValueError("license_policy_commercial_use_not_allowed")
        cohort_payload = (
            dict(cohort)
            if cohort is not None
            else {"inputSha256": input_sha256, "params": dict(params)}
        )
        task_fp = fingerprint({"taskKind": task_kind, "cohort": cohort_payload})
        resolved_artifacts = tuple(
            str(Path(path).expanduser().resolve()) for path in owned_artifact_paths
        )
        if len(resolved_artifacts) != len(set(resolved_artifacts)):
            raise ValueError("owned_artifact_paths must be distinct")
        router_linkage: dict[str, Any] = {}
        if router_promotion_linkage is not None:
            router_linkage = dict(router_promotion_linkage)
            expected_router_keys = {
                "routerDecisionId",
                "routerDecisionFingerprint",
                "capabilityCohort",
                "cohortKeyFingerprint",
                "arenaSummaryFingerprint",
                "arenaPlanFingerprint",
                "admissionFingerprint",
                "selectedModelFingerprint",
                "modelDeepVerificationFingerprint",
                "promotionApprovalEventId",
                "promotionApprovalEventHash",
                "promotionHardwareFingerprint",
                "promotionEvidenceFingerprint",
                "promotionBenchmarkIdsFingerprint",
            }
            if set(router_linkage) != expected_router_keys:
                raise ValueError("router_promotion_linkage_shape_invalid")
        return cls(
            job_id=job_id,
            model_id=model_id,
            model_fingerprint=model_fp,
            task_kind=task_kind,
            task_fingerprint=task_fp,
            input_fingerprint=input_sha256,
            requested_memory_bytes=requested_memory_bytes,
            params_fingerprint=params_fp,
            owned_artifact_paths=resolved_artifacts,
            creator_identity_profile_id=(
                str(profile_payload["profileId"])
                if creator_identity_profile is not None
                else None
            ),
            creator_identity_profile_fingerprint=(
                fingerprint(profile_payload)
                if creator_identity_profile is not None
                else None
            ),
            content_intent_id=(
                str(intent_payload["intentId"]) if content_intent is not None else None
            ),
            content_intent_fingerprint=(
                fingerprint(intent_payload) if content_intent is not None else None
            ),
            benchmark_recipe_id=(
                str(recipe_payload["recipeId"])
                if benchmark_recipe is not None
                else None
            ),
            benchmark_recipe_fingerprint=(
                fingerprint(recipe_payload) if benchmark_recipe is not None else None
            ),
            analyzer_registry_id=(
                str(registry_payload["registryId"])
                if analyzer_registry is not None
                else None
            ),
            analyzer_registry_fingerprint=(
                fingerprint(registry_payload) if analyzer_registry is not None else None
            ),
            runtime_binding=(runtime_payload if runtime_binding is not None else None),
            runtime_binding_fingerprint=(
                fingerprint(runtime_payload) if runtime_binding is not None else None
            ),
            license_policy=(license_payload if license_policy is not None else None),
            license_policy_fingerprint=(
                fingerprint(license_payload) if license_policy is not None else None
            ),
            router_decision_id=(
                str(router_linkage["routerDecisionId"])
                if router_promotion_linkage is not None
                else None
            ),
            router_decision_fingerprint=(
                str(router_linkage["routerDecisionFingerprint"])
                if router_promotion_linkage is not None
                else None
            ),
            router_capability_cohort=(
                str(router_linkage["capabilityCohort"])
                if router_promotion_linkage is not None
                else None
            ),
            router_cohort_fingerprint=(
                str(router_linkage["cohortKeyFingerprint"])
                if router_promotion_linkage is not None
                else None
            ),
            arena_summary_fingerprint=(
                str(router_linkage["arenaSummaryFingerprint"])
                if router_promotion_linkage is not None
                else None
            ),
            arena_plan_fingerprint=(
                str(router_linkage["arenaPlanFingerprint"])
                if router_promotion_linkage is not None
                else None
            ),
            local_motion_admission_fingerprint=(
                str(router_linkage["admissionFingerprint"])
                if router_promotion_linkage is not None
                else None
            ),
            selected_model_fingerprint=(
                str(router_linkage["selectedModelFingerprint"])
                if router_promotion_linkage is not None
                else None
            ),
            model_deep_verification_fingerprint=(
                str(router_linkage["modelDeepVerificationFingerprint"])
                if router_promotion_linkage is not None
                else None
            ),
            promotion_approval_event_id=(
                str(router_linkage["promotionApprovalEventId"])
                if router_promotion_linkage is not None
                else None
            ),
            promotion_approval_event_hash=(
                str(router_linkage["promotionApprovalEventHash"])
                if router_promotion_linkage is not None
                else None
            ),
            promotion_hardware_fingerprint=(
                str(router_linkage["promotionHardwareFingerprint"])
                if router_promotion_linkage is not None
                else None
            ),
            promotion_evidence_fingerprint=(
                str(router_linkage["promotionEvidenceFingerprint"])
                if router_promotion_linkage is not None
                else None
            ),
            promotion_benchmark_ids_fingerprint=(
                str(router_linkage["promotionBenchmarkIdsFingerprint"])
                if router_promotion_linkage is not None
                else None
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "jobId": self.job_id,
            "modelId": self.model_id,
            "modelFingerprint": self.model_fingerprint,
            "taskKind": self.task_kind,
            "taskFingerprint": self.task_fingerprint,
            "inputFingerprint": self.input_fingerprint,
            "requestedMemoryBytes": self.requested_memory_bytes,
            "paramsFingerprint": self.params_fingerprint,
            "ownedArtifactPaths": list(self.owned_artifact_paths),
        }
        if self.benchmark_recipe_id is not None:
            payload.update(
                {
                    "benchmarkRecipeId": self.benchmark_recipe_id,
                    "benchmarkRecipeFingerprint": self.benchmark_recipe_fingerprint,
                    "analyzerRegistryId": self.analyzer_registry_id,
                    "analyzerRegistryFingerprint": self.analyzer_registry_fingerprint,
                }
            )
        if self.creator_identity_profile_id is not None:
            payload.update(
                {
                    "creatorIdentityProfileId": self.creator_identity_profile_id,
                    "creatorIdentityProfileFingerprint": self.creator_identity_profile_fingerprint,
                    "contentIntentId": self.content_intent_id,
                    "contentIntentFingerprint": self.content_intent_fingerprint,
                }
            )
        if self.runtime_binding is not None:
            payload.update(
                {
                    "runtimeBinding": dict(self.runtime_binding),
                    "runtimeBindingFingerprint": self.runtime_binding_fingerprint,
                    "licensePolicy": dict(self.license_policy or {}),
                    "licensePolicyFingerprint": self.license_policy_fingerprint,
                }
            )
        if self.router_decision_id is not None:
            payload.update(
                {
                    "routerDecisionId": self.router_decision_id,
                    "routerDecisionFingerprint": self.router_decision_fingerprint,
                    "routerCapabilityCohort": self.router_capability_cohort,
                    "routerCohortFingerprint": self.router_cohort_fingerprint,
                    "arenaSummaryFingerprint": self.arena_summary_fingerprint,
                    "arenaPlanFingerprint": self.arena_plan_fingerprint,
                    "localMotionAdmissionFingerprint": self.local_motion_admission_fingerprint,
                    "selectedModelFingerprint": self.selected_model_fingerprint,
                    "modelDeepVerificationFingerprint": self.model_deep_verification_fingerprint,
                    "promotionApprovalEventId": self.promotion_approval_event_id,
                    "promotionApprovalEventHash": self.promotion_approval_event_hash,
                    "promotionHardwareFingerprint": self.promotion_hardware_fingerprint,
                    "promotionEvidenceFingerprint": self.promotion_evidence_fingerprint,
                    "promotionBenchmarkIdsFingerprint": self.promotion_benchmark_ids_fingerprint,
                }
            )
        return payload


@dataclass(frozen=True)
class JobState:
    job: LocalGenerationJob
    status: str
    last_event: Mapping[str, Any]


@dataclass(frozen=True)
class WorkerLease:
    token: str
    pid: int
    hardware: Mapping[str, Any]


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    job_id: str | None
    reason: str | None
    requested_memory_bytes: int | None
    resource_limit_bytes: int


@dataclass(frozen=True)
class InterruptedRecovery:
    """Evidence-preserving recovery result for one interrupted job."""

    state: JobState
    recovery_id: str
    manifest_path: Path
    artifacts: tuple[Mapping[str, Any], ...]


def _job_from_payload(payload: Mapping[str, Any]) -> LocalGenerationJob:
    return LocalGenerationJob(
        job_id=str(payload["jobId"]),
        model_id=str(payload["modelId"]),
        model_fingerprint=str(payload["modelFingerprint"]),
        task_kind=str(payload["taskKind"]),
        task_fingerprint=str(payload["taskFingerprint"]),
        input_fingerprint=str(payload["inputFingerprint"]),
        requested_memory_bytes=int(payload["requestedMemoryBytes"]),
        params_fingerprint=str(payload["paramsFingerprint"]),
        owned_artifact_paths=tuple(
            str(value) for value in payload.get("ownedArtifactPaths", [])
        ),
        creator_identity_profile_id=(
            str(payload["creatorIdentityProfileId"])
            if payload.get("creatorIdentityProfileId") is not None
            else None
        ),
        creator_identity_profile_fingerprint=(
            str(payload["creatorIdentityProfileFingerprint"])
            if payload.get("creatorIdentityProfileFingerprint") is not None
            else None
        ),
        content_intent_id=(
            str(payload["contentIntentId"])
            if payload.get("contentIntentId") is not None
            else None
        ),
        content_intent_fingerprint=(
            str(payload["contentIntentFingerprint"])
            if payload.get("contentIntentFingerprint") is not None
            else None
        ),
        benchmark_recipe_id=(
            str(payload["benchmarkRecipeId"])
            if payload.get("benchmarkRecipeId") is not None
            else None
        ),
        benchmark_recipe_fingerprint=(
            str(payload["benchmarkRecipeFingerprint"])
            if payload.get("benchmarkRecipeFingerprint") is not None
            else None
        ),
        analyzer_registry_id=(
            str(payload["analyzerRegistryId"])
            if payload.get("analyzerRegistryId") is not None
            else None
        ),
        analyzer_registry_fingerprint=(
            str(payload["analyzerRegistryFingerprint"])
            if payload.get("analyzerRegistryFingerprint") is not None
            else None
        ),
        runtime_binding=(
            dict(payload["runtimeBinding"])
            if isinstance(payload.get("runtimeBinding"), dict)
            else None
        ),
        runtime_binding_fingerprint=(
            str(payload["runtimeBindingFingerprint"])
            if payload.get("runtimeBindingFingerprint") is not None
            else None
        ),
        license_policy=(
            dict(payload["licensePolicy"])
            if isinstance(payload.get("licensePolicy"), dict)
            else None
        ),
        license_policy_fingerprint=(
            str(payload["licensePolicyFingerprint"])
            if payload.get("licensePolicyFingerprint") is not None
            else None
        ),
        router_decision_id=(
            str(payload["routerDecisionId"])
            if payload.get("routerDecisionId") is not None
            else None
        ),
        router_decision_fingerprint=(
            str(payload["routerDecisionFingerprint"])
            if payload.get("routerDecisionFingerprint") is not None
            else None
        ),
        router_capability_cohort=(
            str(payload["routerCapabilityCohort"])
            if payload.get("routerCapabilityCohort") is not None
            else None
        ),
        router_cohort_fingerprint=(
            str(payload["routerCohortFingerprint"])
            if payload.get("routerCohortFingerprint") is not None
            else None
        ),
        arena_summary_fingerprint=(
            str(payload["arenaSummaryFingerprint"])
            if payload.get("arenaSummaryFingerprint") is not None
            else None
        ),
        arena_plan_fingerprint=(
            str(payload["arenaPlanFingerprint"])
            if payload.get("arenaPlanFingerprint") is not None
            else None
        ),
        local_motion_admission_fingerprint=(
            str(payload["localMotionAdmissionFingerprint"])
            if payload.get("localMotionAdmissionFingerprint") is not None
            else None
        ),
        selected_model_fingerprint=(
            str(payload["selectedModelFingerprint"])
            if payload.get("selectedModelFingerprint") is not None
            else None
        ),
        model_deep_verification_fingerprint=(
            str(payload["modelDeepVerificationFingerprint"])
            if payload.get("modelDeepVerificationFingerprint") is not None
            else None
        ),
        promotion_approval_event_id=(
            str(payload["promotionApprovalEventId"])
            if payload.get("promotionApprovalEventId") is not None
            else None
        ),
        promotion_approval_event_hash=(
            str(payload["promotionApprovalEventHash"])
            if payload.get("promotionApprovalEventHash") is not None
            else None
        ),
        promotion_hardware_fingerprint=(
            str(payload["promotionHardwareFingerprint"])
            if payload.get("promotionHardwareFingerprint") is not None
            else None
        ),
        promotion_evidence_fingerprint=(
            str(payload["promotionEvidenceFingerprint"])
            if payload.get("promotionEvidenceFingerprint") is not None
            else None
        ),
        promotion_benchmark_ids_fingerprint=(
            str(payload["promotionBenchmarkIdsFingerprint"])
            if payload.get("promotionBenchmarkIdsFingerprint") is not None
            else None
        ),
    )


class LocalGenerationQueue:
    """Append-only job queue with one machine-wide local generation worker."""

    def __init__(
        self,
        root: Path,
        *,
        resource_limit_bytes: int,
        memory_reserve_bytes: int = 0,
    ) -> None:
        if resource_limit_bytes <= 0:
            raise ValueError("resource_limit_bytes must be positive")
        self.root = root.resolve()
        self.resource_limit_bytes = resource_limit_bytes
        physical = _physical_memory_bytes()
        if physical is not None and resource_limit_bytes > physical:
            raise ValueError("resource_limit_bytes cannot exceed physical memory")
        if memory_reserve_bytes < 0:
            raise ValueError("memory_reserve_bytes cannot be negative")
        self.journal = AppendOnlyJournal(self.root / "jobs.jsonl")
        self._worker_path = self.root / "machine_worker"
        self._mutation_path = self.root / "queue_mutation"
        self._active_leases: set[str] = set()
        self.memory_reserve_bytes = memory_reserve_bytes

    def states(self) -> dict[str, JobState]:
        states: dict[str, JobState] = {}
        for event in self.journal.read().events:
            payload = event.get("payload", {})
            if not isinstance(payload, dict) or "jobId" not in payload:
                continue
            job_id = str(payload["jobId"])
            event_type = event.get("eventType")
            if event_type == "job_submitted":
                job = _job_from_payload(payload)
                if job_id in states:
                    raise JournalCorruptionError(f"duplicate_job_submission:{job_id}")
                states[job_id] = JobState(job=job, status="queued", last_event=event)
                continue
            prior = states.get(job_id)
            if prior is None:
                raise JournalCorruptionError(f"job_event_without_submission:{job_id}")
            status = prior.status
            if event_type == "job_started":
                if status != "queued":
                    raise JournalCorruptionError(
                        f"invalid_job_transition:{job_id}:{status}:running"
                    )
                status = "running"
            elif event_type == "job_succeeded":
                if status != "running":
                    raise JournalCorruptionError(
                        f"invalid_job_transition:{job_id}:{status}:succeeded"
                    )
                status = "succeeded"
            elif event_type == "job_failed":
                if status != "running":
                    raise JournalCorruptionError(
                        f"invalid_job_transition:{job_id}:{status}:failed"
                    )
                status = "failed"
            elif event_type == "job_interrupted":
                if status != "running":
                    raise JournalCorruptionError(
                        f"invalid_job_transition:{job_id}:{status}:interrupted"
                    )
                status = "interrupted"
            elif event_type == "job_recovered_succeeded":
                if status != "interrupted":
                    raise JournalCorruptionError(
                        f"invalid_job_transition:{job_id}:{status}:succeeded"
                    )
                status = "succeeded"
            elif event_type == "job_cancelled":
                if status not in {"queued", "interrupted"}:
                    raise JournalCorruptionError(
                        f"invalid_job_transition:{job_id}:{status}:cancelled"
                    )
                status = "cancelled"
            elif event_type == "job_requeued":
                if status != "interrupted":
                    raise JournalCorruptionError(
                        f"invalid_job_transition:{job_id}:{status}:queued"
                    )
                status = "queued"
            elif event_type == "job_admission_blocked":
                if status != "queued":
                    raise JournalCorruptionError(
                        f"invalid_job_transition:{job_id}:{status}:admission_blocked"
                    )
            elif event_type == "job_artifacts_verified":
                if status != "running":
                    raise JournalCorruptionError(
                        f"invalid_job_transition:{job_id}:{status}:artifacts_verified"
                    )
            elif event_type in {
                "job_artifact_recovery_planned",
                "job_artifacts_quarantined",
                "job_empty_interruption_recovered",
            }:
                if status != "interrupted":
                    raise JournalCorruptionError(
                        f"invalid_job_transition:{job_id}:{status}:artifacts_quarantined"
                    )
            elif isinstance(event_type, str) and event_type.startswith("job_"):
                raise JournalCorruptionError(f"unknown_job_event:{event_type}")
            states[job_id] = JobState(job=prior.job, status=status, last_event=event)
        return states

    def execution_evidence(self, job_id: str) -> dict[str, Any]:
        """Project append-only execution facts without inventing measurements."""

        state = self.states().get(job_id)
        if state is None:
            raise LocalQueueError(f"unknown_job:{job_id}")
        events = [
            event
            for event in self.journal.read().events
            if event.get("payload", {}).get("jobId") == job_id
        ]
        starts = [event for event in events if event.get("eventType") == "job_started"]
        admission_blocks = [
            event
            for event in events
            if event.get("eventType") == "job_admission_blocked"
        ]
        terminal = next(
            (
                event
                for event in reversed(events)
                if event.get("eventType")
                in {
                    "job_succeeded",
                    "job_recovered_succeeded",
                    "job_failed",
                    "job_interrupted",
                    "job_cancelled",
                }
            ),
            None,
        )
        terminal_payload = (
            dict(terminal.get("payload", {})) if terminal is not None else {}
        )
        attempt_count = len(starts)
        failure_class = terminal_payload.get("failureClass")
        if failure_class is None and admission_blocks and state.status == "queued":
            failure_class = "resource_admission_blocked"
        measurement = terminal_payload.get("executionMeasurement")
        if not isinstance(measurement, dict):
            measurement = {
                "available": False,
                "reason": "execution_measurement_unavailable",
            }
        local_cost = terminal_payload.get("localCost")
        if not isinstance(local_cost, dict):
            local_cost = _local_cost_observation()
        return {
            "status": state.status,
            "attemptCount": attempt_count,
            "retryCount": max(0, attempt_count - 1),
            "admissionBlockCount": len(admission_blocks),
            "failureClass": failure_class,
            "executionMeasurement": measurement,
            "localCost": local_cost,
        }

    def _attempt_metadata(self, job_id: str) -> dict[str, int]:
        attempt_count = sum(
            1
            for event in self.journal.read().events
            if event.get("eventType") == "job_started"
            and event.get("payload", {}).get("jobId") == job_id
        )
        if attempt_count <= 0:
            raise JournalCorruptionError("job_start_event_missing")
        return {
            "attemptNumber": attempt_count,
            "retryCount": attempt_count - 1,
        }

    def submit(self, job: LocalGenerationJob) -> JobState:
        with file_lock(self._mutation_path):
            existing = self.states().get(job.job_id)
            if existing is not None:
                if existing.job != job:
                    raise LocalQueueError(f"job_id_fingerprint_conflict:{job.job_id}")
                return existing
            self.journal.append(
                "job_submitted",
                {
                    **job.as_dict(),
                    "hardwareFingerprint": hardware_identity()["fingerprint"],
                },
            )
            return self.states()[job.job_id]

    def submit_and_start_exact(
        self, lease: WorkerLease, job: LocalGenerationJob
    ) -> AdmissionDecision:
        """Atomically admit only the job owned by the active invocation.

        A synchronous generator cannot safely execute an older queued job
        because it does not own that job's full runtime request. Any backlog is
        therefore an explicit recovery condition, never an implicit FIFO run.
        """
        self._require_active_lease(lease)
        with file_lock(self._mutation_path):
            states = self.states()
            prior = states.get(job.job_id)
            if prior is not None:
                if prior.job != job:
                    raise LocalQueueError(f"job_id_fingerprint_conflict:{job.job_id}")
                if prior.status != "queued":
                    raise InvalidJobTransition(
                        f"job_requires_explicit_recovery:{job.job_id}:{prior.status}"
                    )
            queued_other = sorted(
                job_id
                for job_id, state in states.items()
                if state.status == "queued" and job_id != job.job_id
            )
            if queued_other:
                raise LocalQueueError(
                    "local_generation_queue_backlog_requires_operator_recovery:"
                    + ",".join(queued_other)
                )
            if prior is None:
                self.journal.append(
                    "job_submitted",
                    {
                        **job.as_dict(),
                        "hardwareFingerprint": hardware_identity()["fingerprint"],
                    },
                )
            decision = self._start_next_locked(lease)
            if not decision.admitted or decision.job_id != job.job_id:
                raise LocalQueueError(
                    "local_generation_exact_admission_failed:"
                    + str(decision.reason or decision.job_id or "unknown")
                )
            return decision

    def recover_interrupted(
        self, job_id: str, *, lineage_path: Path, reason: str
    ) -> InterruptedRecovery:
        """Quarantine exact owned artifacts, then requeue an interrupted job.

        The recovery directory and manifest are deterministic for the exact
        interruption event. A crash during recovery can therefore resume safely:
        already moved artifacts are verified at their quarantine destination and
        remaining sources are moved without overwriting anything. No evidence is
        deleted and no unrelated path from the lineage is trusted.
        """

        if not reason.strip():
            raise ValueError("reason must be non-empty")
        supplied_lineage = lineage_path.expanduser().resolve()
        with file_lock(self._mutation_path):
            state = self._require_state(job_id)
            if state.status != "interrupted":
                raise InvalidJobTransition(
                    f"job_not_interrupted:{job_id}:{state.status}"
                )
            journal_events = self.journal.read().events
            interruptions = [
                event
                for event in journal_events
                if event.get("eventType") == "job_interrupted"
                and event.get("payload", {}).get("jobId") == job_id
            ]
            interruption_hash = str(
                interruptions[-1].get("eventHash") if interruptions else ""
            )
            if not interruption_hash:
                raise JournalCorruptionError("interrupted_job_event_hash_missing")
            recovery_id = fingerprint(
                {
                    "jobId": job_id,
                    "interruptionEventHash": interruption_hash,
                    "lineagePath": str(supplied_lineage),
                }
            )[:24]
            recovery_root = self.root / "recovery" / recovery_id
            manifest_path = recovery_root / "plan.json"
            completed_path = recovery_root / "completed.json"
            if manifest_path.exists():
                manifest = self._read_recovery_manifest(
                    manifest_path,
                    job=state.job,
                    interruption_hash=interruption_hash,
                    lineage_path=supplied_lineage,
                )
                planned_events = [
                    event
                    for event in self.journal.read().events
                    if event.get("eventType") == "job_artifact_recovery_planned"
                    and event.get("payload", {}).get("recoveryId") == recovery_id
                ]
                if len(planned_events) != 1:
                    raise JournalCorruptionError(
                        f"artifact_recovery_plan_not_recorded_exactly_once:{recovery_id}"
                    )
                if planned_events[0]["payload"].get("planSha256") != sha256_file(
                    manifest_path
                ):
                    raise JournalCorruptionError(
                        f"artifact_recovery_plan_hash_mismatch:{recovery_id}"
                    )
            else:
                manifest = self._plan_interrupted_recovery(
                    job=state.job,
                    interruption_hash=interruption_hash,
                    recovery_id=recovery_id,
                    lineage_path=supplied_lineage,
                    recovery_root=recovery_root,
                    reason=reason,
                )
                recovery_root.mkdir(parents=True, exist_ok=False)
                atomic_write_json(manifest_path, manifest)
                self.journal.append(
                    "job_artifact_recovery_planned",
                    {
                        "jobId": job_id,
                        "recoveryId": recovery_id,
                        "interruptionEventHash": interruption_hash,
                        "planPath": str(manifest_path),
                        "planSha256": sha256_file(manifest_path),
                        "artifactCount": len(manifest["artifacts"]),
                    },
                )

            artifacts = tuple(dict(item) for item in manifest["artifacts"])
            for artifact in artifacts:
                source = Path(str(artifact["sourcePath"]))
                destination = Path(str(artifact["quarantinePath"]))
                expected_sha256 = str(artifact["sha256"])
                if source.exists() and destination.exists():
                    raise LocalQueueError(
                        f"recovery_source_and_destination_both_exist:{artifact['kind']}"
                    )
                if destination.exists():
                    if (
                        not destination.is_file()
                        or sha256_file(destination) != expected_sha256
                    ):
                        raise LocalQueueError(
                            f"recovery_quarantine_mismatch:{artifact['kind']}"
                        )
                    continue
                if not source.is_file() or source.is_symlink():
                    raise LocalQueueError(
                        f"recovery_source_missing_or_unsafe:{artifact['kind']}"
                    )
                if sha256_file(source) != expected_sha256:
                    raise LocalQueueError(
                        f"recovery_source_sha256_mismatch:{artifact['kind']}"
                    )
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, destination)
                if sha256_file(destination) != expected_sha256:
                    raise LocalQueueError(
                        f"recovery_move_verification_failed:{artifact['kind']}"
                    )

            completed_manifest = {
                "schema": "reel_factory.local_generation_recovery_completion.v1",
                "recoveryId": recovery_id,
                "jobId": job_id,
                "planPath": str(manifest_path),
                "planSha256": sha256_file(manifest_path),
                "artifacts": artifacts,
            }
            if completed_path.exists():
                try:
                    existing_completion = json.loads(
                        completed_path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeDecodeError, ValueError) as exc:
                    raise LocalQueueError(
                        "interrupted_recovery_completion_invalid"
                    ) from exc
                if existing_completion != completed_manifest:
                    raise LocalQueueError("interrupted_recovery_completion_mismatch")
            else:
                atomic_write_json(completed_path, completed_manifest)
            prior = [
                event
                for event in self.journal.read().events
                if event.get("eventType") == "job_artifacts_quarantined"
                and event.get("payload", {}).get("recoveryId") == recovery_id
            ]
            if len(prior) > 1:
                raise JournalCorruptionError(
                    f"duplicate_artifact_recovery_event:{recovery_id}"
                )
            if prior and prior[0]["payload"].get("completionSha256") != sha256_file(
                completed_path
            ):
                raise JournalCorruptionError(
                    f"artifact_recovery_completion_hash_mismatch:{recovery_id}"
                )
            if not prior:
                self.journal.append(
                    "job_artifacts_quarantined",
                    {
                        "jobId": job_id,
                        "recoveryId": recovery_id,
                        "interruptionEventHash": interruption_hash,
                        "planPath": str(manifest_path),
                        "planSha256": sha256_file(manifest_path),
                        "completionPath": str(completed_path),
                        "completionSha256": sha256_file(completed_path),
                        "artifactCount": len(artifacts),
                    },
                )
            self.journal.append(
                "job_requeued",
                {
                    "jobId": job_id,
                    "reason": reason,
                    "recoveryId": recovery_id,
                    "recoveryPlanPath": str(manifest_path),
                },
            )
            return InterruptedRecovery(
                state=self.states()[job_id],
                recovery_id=recovery_id,
                manifest_path=manifest_path,
                artifacts=artifacts,
            )

    def recover_empty_interruption(
        self, job_id: str, *, lineage_path: Path, reason: str
    ) -> JobState:
        """Requeue a crash-before-lineage job only when every owned path is absent."""

        if not reason.strip():
            raise ValueError("reason must be non-empty")
        supplied_lineage = lineage_path.expanduser().resolve()
        with file_lock(self._mutation_path):
            state = self._require_state(job_id)
            if state.status != "interrupted":
                raise InvalidJobTransition(
                    f"job_not_interrupted:{job_id}:{state.status}"
                )
            owned = tuple(Path(value) for value in state.job.owned_artifact_paths)
            if not owned:
                raise LocalQueueError("empty_interruption_owned_paths_missing")
            if str(supplied_lineage) not in state.job.owned_artifact_paths:
                raise LocalQueueError("empty_interruption_lineage_path_mismatch")
            present = [
                str(path) for path in owned if path.exists() or path.is_symlink()
            ]
            if present:
                raise LocalQueueError(
                    "empty_interruption_artifacts_present_requires_quarantine:"
                    + ",".join(present)
                )
            journal_events = self.journal.read().events
            interruptions = [
                event
                for event in journal_events
                if event.get("eventType") == "job_interrupted"
                and event.get("payload", {}).get("jobId") == job_id
            ]
            interruption_hash = str(
                interruptions[-1].get("eventHash") if interruptions else ""
            )
            if not interruption_hash:
                raise JournalCorruptionError("interrupted_job_event_hash_missing")
            self.journal.append(
                "job_empty_interruption_recovered",
                {
                    "jobId": job_id,
                    "interruptionEventHash": interruption_hash,
                    "jobFingerprint": fingerprint(state.job.as_dict()),
                    "lineagePath": str(supplied_lineage),
                    "verifiedAbsentPaths": [str(path) for path in owned],
                    "reason": reason,
                },
            )
            self.journal.append(
                "job_requeued",
                {
                    "jobId": job_id,
                    "reason": reason,
                    "recoveryId": None,
                    "recoveryPolicy": "journal_only_no_artifacts_present",
                },
            )
            return self.states()[job_id]

    def recover_completed_interruption(
        self, job_id: str, *, lineage_path: Path, reason: str
    ) -> JobState:
        """Finalize a crash-after-artifact job without rerunning inference."""

        if not reason.strip():
            raise ValueError("reason must be non-empty")
        supplied_lineage = lineage_path.expanduser().resolve()
        with file_lock(self._mutation_path):
            state = self._require_state(job_id)
            if state.status != "interrupted":
                raise InvalidJobTransition(
                    f"job_not_interrupted:{job_id}:{state.status}"
                )
            if str(supplied_lineage) not in state.job.owned_artifact_paths:
                raise LocalQueueError("completed_interruption_lineage_path_mismatch")
            try:
                lineage = json.loads(supplied_lineage.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                raise LocalQueueError("completed_interruption_lineage_invalid") from exc
            if not isinstance(lineage, dict) or lineage.get("status") != "completed":
                raise LocalQueueError("completed_interruption_lineage_not_completed")
            journal_events = self.journal.read().events
            interruptions = [
                event
                for event in journal_events
                if event.get("eventType") == "job_interrupted"
                and event.get("payload", {}).get("jobId") == job_id
            ]
            interruption_hash = str(
                interruptions[-1].get("eventHash") if interruptions else ""
            )
            if not interruption_hash:
                raise JournalCorruptionError("interrupted_job_event_hash_missing")
            interruption_index = journal_events.index(interruptions[-1])
            start_indices = [
                index
                for index, event in enumerate(journal_events[:interruption_index])
                if event.get("eventType") == "job_started"
                and event.get("payload", {}).get("jobId") == job_id
            ]
            if not start_indices:
                raise JournalCorruptionError(
                    "completed_interruption_start_event_missing"
                )
            start_index = start_indices[-1]
            verified_events = [
                event
                for event in journal_events[start_index + 1 : interruption_index]
                if event.get("eventType") == "job_artifacts_verified"
                and event.get("payload", {}).get("jobId") == job_id
            ]
            if len(verified_events) != 1:
                raise LocalQueueError(
                    "completed_interruption_requires_exactly_one_artifact_verification"
                )
            verified_event = verified_events[-1]
            verified = verified_event.get("payload", {})
            if verified.get("jobFingerprint") != fingerprint(state.job.as_dict()):
                raise LocalQueueError(
                    "completed_interruption_artifact_job_fingerprint_mismatch"
                )
            # Reuse the exact lineage/job fingerprint verifier without moving
            # artifacts. It validates model, inputs, task, parameters and all
            # owned path derivations before the recovered terminal event.
            self._plan_interrupted_recovery(
                job=state.job,
                interruption_hash=interruption_hash,
                recovery_id="validation-only",
                lineage_path=supplied_lineage,
                recovery_root=self.root / "validation-only",
                reason=reason,
            )
            output_value = verified.get("outputPath")
            output = Path(str(output_value or "")).expanduser().resolve()
            output_sha256 = str(verified.get("outputSha256") or "")
            if (
                not output.is_file()
                or output.is_symlink()
                or not output_sha256
                or sha256_file(output) != output_sha256
            ):
                raise LocalQueueError("completed_interruption_output_mismatch")
            if str(output) not in state.job.owned_artifact_paths:
                raise LocalQueueError("completed_interruption_output_path_mismatch")
            if (
                lineage.get("outputPath") != str(output)
                or lineage.get("outputSha256") != output_sha256
            ):
                raise LocalQueueError("completed_interruption_lineage_output_mismatch")
            output_probe = verified.get("outputProbe")
            if (
                not isinstance(output_probe, dict)
                or lineage.get("outputProbe") != output_probe
            ):
                raise LocalQueueError("completed_interruption_output_probe_missing")
            measurement = verified.get("executionMeasurement")
            if (
                not isinstance(measurement, dict)
                or lineage.get("executionMeasurement") != measurement
            ):
                raise LocalQueueError(
                    "completed_interruption_execution_measurement_mismatch"
                )
            partials = [
                path
                for path in state.job.owned_artifact_paths
                if ".partial" in Path(path).name
            ]
            if any(Path(path).exists() or Path(path).is_symlink() for path in partials):
                raise LocalQueueError("completed_interruption_partial_artifact_present")
            audio = lineage.get("audio")
            if isinstance(audio, dict) and audio.get("mode") != "none":
                sidecar = Path(str(verified.get("audioPath") or "")).resolve()
                sidecar_sha = str(verified.get("audioSha256") or "")
                if (
                    str(sidecar) not in state.job.owned_artifact_paths
                    or audio.get("sidecarPath") != str(sidecar)
                    or audio.get("sidecarSha256") != sidecar_sha
                    or not sidecar.is_file()
                    or sidecar.is_symlink()
                    or sha256_file(sidecar) != sidecar_sha
                ):
                    raise LocalQueueError(
                        "completed_interruption_audio_sidecar_mismatch"
                    )
            self.journal.append(
                "job_recovered_succeeded",
                {
                    "jobId": job_id,
                    "interruptionEventHash": interruption_hash,
                    "artifactVerificationEventHash": verified_event.get("eventHash"),
                    "jobFingerprint": fingerprint(state.job.as_dict()),
                    "lineagePath": str(supplied_lineage),
                    "lineageSha256": sha256_file(supplied_lineage),
                    "outputPath": str(output),
                    "outputSha256": output_sha256,
                    "outputProbe": output_probe,
                    "executionMeasurement": measurement,
                    "reason": reason,
                    **self._attempt_metadata(job_id),
                    "failureClass": None,
                    "localCost": _local_cost_observation(),
                },
            )
            return self.states()[job_id]

    def cancel_queued(self, job_id: str, *, reason: str) -> JobState:
        """Explicitly retire a queued admission record without deleting it."""

        if not reason.strip():
            raise ValueError("reason must be non-empty")
        with file_lock(self._mutation_path):
            state = self._require_state(job_id)
            if state.status != "queued":
                raise InvalidJobTransition(f"job_not_queued:{job_id}:{state.status}")
            self.journal.append(
                "job_cancelled",
                {"jobId": job_id, "reason": reason, "automatic": False},
            )
            return self.states()[job_id]

    @staticmethod
    def _read_recovery_manifest(
        manifest_path: Path,
        *,
        job: LocalGenerationJob,
        interruption_hash: str,
        lineage_path: Path,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise LocalQueueError("interrupted_recovery_manifest_invalid") from exc
        if not isinstance(payload, dict):
            raise LocalQueueError("interrupted_recovery_manifest_invalid")
        expected = {
            "schema": "reel_factory.local_generation_recovery.v1",
            "jobId": job.job_id,
            "interruptionEventHash": interruption_hash,
            "lineagePath": str(lineage_path),
            "jobFingerprint": fingerprint(job.as_dict()),
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                raise LocalQueueError(f"interrupted_recovery_manifest_mismatch:{key}")
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise LocalQueueError("interrupted_recovery_manifest_missing_artifacts")
        return payload

    @staticmethod
    def _plan_interrupted_recovery(
        *,
        job: LocalGenerationJob,
        interruption_hash: str,
        recovery_id: str,
        lineage_path: Path,
        recovery_root: Path,
        reason: str,
    ) -> dict[str, Any]:
        if not lineage_path.is_file() or lineage_path.is_symlink():
            raise LocalQueueError("interrupted_recovery_lineage_missing_or_unsafe")
        try:
            lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise LocalQueueError("interrupted_recovery_lineage_invalid") from exc
        if not isinstance(lineage, dict):
            raise LocalQueueError("interrupted_recovery_lineage_invalid")
        queue_payload = lineage.get("queue")
        if (
            not isinstance(queue_payload, dict)
            or queue_payload.get("jobId") != job.job_id
        ):
            raise LocalQueueError("interrupted_recovery_lineage_job_mismatch")
        output_value = lineage.get("outputPath")
        if not isinstance(output_value, str) or not output_value.strip():
            raise LocalQueueError("interrupted_recovery_output_path_missing")
        output = Path(output_value).expanduser().resolve()
        expected_lineage = output.with_suffix(output.suffix + ".local_video.json")
        if expected_lineage != lineage_path:
            raise LocalQueueError("interrupted_recovery_lineage_path_mismatch")
        inputs = {
            "image": lineage.get("input"),
            "audio": lineage.get("sourceAudio"),
            "lastImage": lineage.get("lastImage"),
            "lora": lineage.get("lora"),
        }
        if "executionBinding" in lineage:
            inputs["executionBinding"] = lineage.get("executionBinding")
        if "sourceVideo" in lineage:
            inputs["sourceVideo"] = lineage.get("sourceVideo")
        request = lineage.get("request")
        command = lineage.get("command")
        if not isinstance(request, dict) or not isinstance(command, list):
            raise LocalQueueError("interrupted_recovery_lineage_request_invalid")
        params = {
            "command": command,
            "outputPath": str(output),
            "task": request.get("task"),
            "durationSeconds": request.get("durationSeconds"),
            "seed": request.get("seed"),
        }
        if "executionContext" in lineage or "executionBinding" in lineage:
            params.update(
                {
                    "executionContext": lineage.get("executionContext"),
                    "executionBindingFingerprint": (
                        lineage.get("executionBinding", {}).get("bindingFingerprint")
                        if isinstance(lineage.get("executionBinding"), dict)
                        else None
                    ),
                }
            )
        isolation = lineage.get("executionIsolation")
        if isinstance(isolation, dict):
            params["executionIsolationFingerprint"] = isolation.get(
                "isolationFingerprint"
            )
        cohort_inputs = {
            "image": inputs["image"],
            "audio": inputs["audio"],
            "lastImage": inputs["lastImage"],
        }
        if "sourceVideo" in inputs:
            cohort_inputs["sourceVideo"] = inputs["sourceVideo"]
        cohort_input_sha = fingerprint(cohort_inputs)
        cohort = {
            "sourceInputSha256": cohort_input_sha,
            "task": request.get("task"),
            "prompt": request.get("prompt"),
            "durationSeconds": request.get("durationSeconds"),
            "seed": request.get("seed"),
            "audioMode": (
                lineage.get("audio", {}).get("mode")
                if isinstance(lineage.get("audio"), dict)
                else None
            ),
        }
        if "executionContext" in lineage or "executionBinding" in lineage:
            cohort.update(
                {
                    "executionContext": lineage.get("executionContext"),
                    "executionBindingFingerprint": (
                        lineage.get("executionBinding", {}).get("bindingFingerprint")
                        if isinstance(lineage.get("executionBinding"), dict)
                        else None
                    ),
                }
            )
        if isinstance(isolation, dict):
            cohort["executionIsolationFingerprint"] = isolation.get(
                "isolationFingerprint"
            )
        model_fingerprint = fingerprint(
            {
                "modelId": lineage.get("modelId"),
                "modelRevision": lineage.get("modelRevision"),
                "modelManifestSha256": lineage.get("modelManifestSha256"),
            }
        )
        expected_fingerprints = {
            "model": (job.model_fingerprint, model_fingerprint),
            "input": (job.input_fingerprint, fingerprint(inputs)),
            "params": (job.params_fingerprint, fingerprint(params)),
            "task": (
                job.task_fingerprint,
                fingerprint({"taskKind": job.task_kind, "cohort": cohort}),
            ),
        }
        if request.get("task") != job.task_kind:
            raise LocalQueueError("interrupted_recovery_task_kind_mismatch")
        for label, (expected, actual) in expected_fingerprints.items():
            if expected != actual:
                raise LocalQueueError(
                    f"interrupted_recovery_{label}_fingerprint_mismatch"
                )
        expected_paths = (
            ("output", output),
            ("partial_output", output.with_suffix(".partial" + output.suffix)),
            ("audio_sidecar", output.with_suffix(output.suffix + ".audio.wav")),
            (
                "partial_audio",
                output.with_suffix(output.suffix + ".audio.wav").with_suffix(
                    ".partial.wav"
                ),
            ),
            ("lineage", lineage_path),
        )
        artifacts: list[dict[str, Any]] = []
        for index, (kind, source) in enumerate(expected_paths):
            if not source.exists():
                continue
            if not source.is_file() or source.is_symlink():
                raise LocalQueueError(f"interrupted_recovery_artifact_unsafe:{kind}")
            suffix = "".join(source.suffixes)
            destination = recovery_root / f"{index:02d}_{kind}{suffix}"
            artifacts.append(
                {
                    "kind": kind,
                    "sourcePath": str(source),
                    "quarantinePath": str(destination),
                    "sha256": sha256_file(source),
                    "sizeBytes": source.stat().st_size,
                }
            )
        if not artifacts or artifacts[-1]["kind"] != "lineage":
            raise LocalQueueError("interrupted_recovery_lineage_not_preserved")
        return {
            "schema": "reel_factory.local_generation_recovery.v1",
            "recoveryId": recovery_id,
            "jobId": job.job_id,
            "jobFingerprint": fingerprint(job.as_dict()),
            "interruptionEventHash": interruption_hash,
            "lineagePath": str(lineage_path),
            "reason": reason,
            "status": "planned",
            "plannedAt": _utc_now(),
            "artifacts": artifacts,
        }

    @contextmanager
    def worker_session(self, *, blocking: bool = False) -> Iterator[WorkerLease]:
        try:
            lock_context = file_lock(self._worker_path, blocking=blocking)
            with lock_context:
                lease = WorkerLease(
                    token=str(uuid.uuid4()),
                    pid=os.getpid(),
                    hardware=hardware_identity(),
                )
                self._active_leases.add(lease.token)
                self._record_abandoned_running_jobs(lease)
                try:
                    yield lease
                finally:
                    self._active_leases.discard(lease.token)
        except BlockingIOError as exc:
            raise WorkerLeaseUnavailable("local_generation_worker_busy") from exc

    def start_next(self, lease: WorkerLease) -> AdmissionDecision:
        self._require_active_lease(lease)
        with file_lock(self._mutation_path):
            return self._start_next_locked(lease)

    def _start_next_locked(self, lease: WorkerLease) -> AdmissionDecision:
        states = self.states()
        running = [state for state in states.values() if state.status == "running"]
        if running:
            raise LocalQueueError("running_job_present_while_worker_lease_held")
        queued = [state for state in states.values() if state.status == "queued"]
        if not queued:
            return AdmissionDecision(
                admitted=False,
                job_id=None,
                reason="queue_empty",
                requested_memory_bytes=None,
                resource_limit_bytes=self.resource_limit_bytes,
            )
        state = next(
            (
                candidate
                for candidate in queued
                if candidate.job.requested_memory_bytes <= self.resource_limit_bytes
            ),
            None,
        )
        if state is None:
            blocked = queued[0]
            requested = blocked.job.requested_memory_bytes
            self.journal.append(
                "job_admission_blocked",
                {
                    "jobId": blocked.job.job_id,
                    "reason": "requested_memory_exceeds_resource_limit",
                    "requestedMemoryBytes": requested,
                    "resourceLimitBytes": self.resource_limit_bytes,
                },
            )
            return AdmissionDecision(
                admitted=False,
                job_id=blocked.job.job_id,
                reason="requested_memory_exceeds_resource_limit",
                requested_memory_bytes=requested,
                resource_limit_bytes=self.resource_limit_bytes,
            )
        requested = state.job.requested_memory_bytes
        current_available = _macos_available_memory_bytes()
        if platform.system() == "Darwin" and current_available is None:
            self.journal.append(
                "job_admission_blocked",
                {
                    "jobId": state.job.job_id,
                    "reason": "available_memory_measurement_unavailable",
                    "requestedMemoryBytes": requested,
                    "memoryReserveBytes": self.memory_reserve_bytes,
                },
            )
            return AdmissionDecision(
                admitted=False,
                job_id=state.job.job_id,
                reason="available_memory_measurement_unavailable",
                requested_memory_bytes=requested,
                resource_limit_bytes=self.resource_limit_bytes,
            )
        if current_available is not None:
            usable_memory = max(0, current_available - self.memory_reserve_bytes)
            if requested > usable_memory:
                self.journal.append(
                    "job_admission_blocked",
                    {
                        "jobId": state.job.job_id,
                        "reason": "insufficient_current_available_memory",
                        "requestedMemoryBytes": requested,
                        "currentAvailableMemoryBytes": current_available,
                        "memoryReserveBytes": self.memory_reserve_bytes,
                        "usableMemoryBytes": usable_memory,
                    },
                )
                return AdmissionDecision(
                    admitted=False,
                    job_id=state.job.job_id,
                    reason="insufficient_current_available_memory",
                    requested_memory_bytes=requested,
                    resource_limit_bytes=self.resource_limit_bytes,
                )
        self.journal.append(
            "job_started",
            {
                "jobId": state.job.job_id,
                "workerToken": lease.token,
                "workerPid": lease.pid,
                "hardware": dict(lease.hardware),
                "resourceLimitBytes": self.resource_limit_bytes,
                "requestedMemoryBytes": requested,
                "currentAvailableMemoryBytes": current_available,
                "memoryReserveBytes": self.memory_reserve_bytes,
                "attemptNumber": sum(
                    1
                    for event in self.journal.read().events
                    if event.get("eventType") == "job_started"
                    and event.get("payload", {}).get("jobId") == state.job.job_id
                )
                + 1,
            },
        )
        return AdmissionDecision(
            admitted=True,
            job_id=state.job.job_id,
            reason=None,
            requested_memory_bytes=requested,
            resource_limit_bytes=self.resource_limit_bytes,
        )

    def succeed(
        self,
        lease: WorkerLease,
        job_id: str,
        *,
        output_sha256: str,
        output_path: Path,
        execution_measurement: Mapping[str, Any] | None = None,
    ) -> JobState:
        if len(output_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in output_sha256
        ):
            raise ValueError("output_sha256 must be a lowercase SHA-256")
        with file_lock(self._mutation_path):
            self._require_running_for_lease(lease, job_id)
            state = self._require_state(job_id)
            resolved_output = output_path.resolve()
            if not resolved_output.is_file():
                raise LocalQueueError(f"job_output_missing:{resolved_output}")
            actual_sha256 = sha256_file(resolved_output)
            if actual_sha256 != output_sha256:
                raise LocalQueueError(
                    "job_output_sha256_mismatch:"
                    f"expected={output_sha256}:actual={actual_sha256}"
                )
            measurement: dict[str, Any] | None = None
            if execution_measurement is not None:
                try:
                    wall_time = float(execution_measurement["wallTimeSeconds"])
                    peak_memory = int(execution_measurement["peakMemoryBytes"])
                    method = str(execution_measurement["memoryMeasurementMethod"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("execution_measurement_invalid") from exc
                if (
                    not math.isfinite(wall_time)
                    or wall_time <= 0
                    or peak_memory <= 0
                    or not method.strip()
                ):
                    raise ValueError("execution_measurement_invalid")
                measurement = {
                    "wallTimeSeconds": wall_time,
                    "peakMemoryBytes": peak_memory,
                    "memoryMeasurementMethod": method,
                }
            if state.job.owned_artifact_paths:
                events = self.journal.read().events
                start_indices = [
                    index
                    for index, event in enumerate(events)
                    if event.get("eventType") == "job_started"
                    and event.get("payload", {}).get("jobId") == job_id
                ]
                if not start_indices:
                    raise JournalCorruptionError("job_start_event_missing")
                verified_events = [
                    event
                    for event in events[start_indices[-1] + 1 :]
                    if event.get("eventType") == "job_artifacts_verified"
                    and event.get("payload", {}).get("jobId") == job_id
                ]
                if len(verified_events) != 1:
                    raise LocalQueueError(
                        "job_success_requires_exactly_one_artifact_verification"
                    )
                verified = verified_events[0].get("payload", {})
                if (
                    verified.get("jobFingerprint") != fingerprint(state.job.as_dict())
                    or verified.get("outputPath") != str(resolved_output)
                    or verified.get("outputSha256") != output_sha256
                    or verified.get("executionMeasurement") != measurement
                ):
                    raise LocalQueueError("job_success_artifact_verification_mismatch")
            self.journal.append(
                "job_succeeded",
                {
                    "jobId": job_id,
                    "workerToken": lease.token,
                    "outputSha256": output_sha256,
                    "outputPath": str(resolved_output),
                    "executionMeasurement": measurement,
                    **self._attempt_metadata(job_id),
                    "failureClass": None,
                    "localCost": _local_cost_observation(),
                },
            )
            return self.states()[job_id]

    def verify_generated_artifacts(
        self,
        lease: WorkerLease,
        job_id: str,
        *,
        partial_output_path: Path,
        final_output_path: Path,
        output_probe: Mapping[str, Any],
        execution_measurement: Mapping[str, Any],
        partial_audio_path: Path | None = None,
        final_audio_path: Path | None = None,
    ) -> dict[str, Any]:
        """Journal exact validated artifacts before atomic final promotion."""

        with file_lock(self._mutation_path):
            self._require_running_for_lease(lease, job_id)
            state = self._require_state(job_id)
            partial = partial_output_path.expanduser().resolve()
            final = final_output_path.expanduser().resolve()
            if (
                str(partial) not in state.job.owned_artifact_paths
                or str(final) not in state.job.owned_artifact_paths
            ):
                raise LocalQueueError("verified_artifact_path_not_owned_by_job")
            if not partial.is_file() or partial.is_symlink():
                raise LocalQueueError("verified_partial_output_missing_or_unsafe")
            if not isinstance(output_probe, Mapping) or not output_probe:
                raise ValueError("verified_output_probe_invalid")
            try:
                wall_time = float(execution_measurement["wallTimeSeconds"])
                peak_memory = int(execution_measurement["peakMemoryBytes"])
                method = str(execution_measurement["memoryMeasurementMethod"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("execution_measurement_invalid") from exc
            if (
                not math.isfinite(wall_time)
                or wall_time <= 0
                or peak_memory <= 0
                or not method.strip()
            ):
                raise ValueError("execution_measurement_invalid")
            payload: dict[str, Any] = {
                "jobId": job_id,
                "workerToken": lease.token,
                "jobFingerprint": fingerprint(state.job.as_dict()),
                "partialOutputPath": str(partial),
                "outputPath": str(final),
                "outputSha256": sha256_file(partial),
                "outputProbe": dict(output_probe),
                "executionMeasurement": {
                    "wallTimeSeconds": wall_time,
                    "peakMemoryBytes": peak_memory,
                    "memoryMeasurementMethod": method,
                },
                "partialAudioPath": None,
                "audioPath": None,
                "audioSha256": None,
            }
            if (partial_audio_path is None) != (final_audio_path is None):
                raise ValueError("verified_audio_paths_must_be_supplied_together")
            if partial_audio_path is not None and final_audio_path is not None:
                partial_audio = partial_audio_path.expanduser().resolve()
                final_audio = final_audio_path.expanduser().resolve()
                if (
                    str(partial_audio) not in state.job.owned_artifact_paths
                    or str(final_audio) not in state.job.owned_artifact_paths
                ):
                    raise LocalQueueError("verified_audio_path_not_owned_by_job")
                if not partial_audio.is_file() or partial_audio.is_symlink():
                    raise LocalQueueError("verified_partial_audio_missing_or_unsafe")
                payload.update(
                    {
                        "partialAudioPath": str(partial_audio),
                        "audioPath": str(final_audio),
                        "audioSha256": sha256_file(partial_audio),
                    }
                )
            event = self.journal.append("job_artifacts_verified", payload)
            return dict(event["payload"])

    def fail(
        self,
        lease: WorkerLease,
        job_id: str,
        *,
        error: BaseException,
        execution_measurement: Mapping[str, Any] | None = None,
        failure_class: str | None = None,
    ) -> JobState:
        message = str(error).strip() or type(error).__name__
        classified = failure_class or _failure_class(error)
        if not classified.strip():
            raise ValueError("failure_class must be non-empty")
        with file_lock(self._mutation_path):
            self._require_running_for_lease(lease, job_id)
            self.journal.append(
                "job_failed",
                {
                    "jobId": job_id,
                    "workerToken": lease.token,
                    "errorType": type(error).__name__,
                    "errorMessage": message[:1000],
                    "failureClass": classified,
                    "executionMeasurement": _optional_execution_measurement(
                        execution_measurement
                    ),
                    **self._attempt_metadata(job_id),
                    "localCost": _local_cost_observation(),
                },
            )
            return self.states()[job_id]

    def interrupt(self, lease: WorkerLease, job_id: str, *, reason: str) -> JobState:
        if not reason.strip():
            raise ValueError("reason must be non-empty")
        with file_lock(self._mutation_path):
            self._require_running_for_lease(lease, job_id)
            self.journal.append(
                "job_interrupted",
                {
                    "jobId": job_id,
                    "workerToken": lease.token,
                    "reason": reason,
                    "failureClass": "execution_interrupted",
                    "executionMeasurement": _optional_execution_measurement(None),
                    **self._attempt_metadata(job_id),
                    "localCost": _local_cost_observation(),
                },
            )
            return self.states()[job_id]

    def _record_abandoned_running_jobs(self, lease: WorkerLease) -> None:
        with file_lock(self._mutation_path):
            for state in self.states().values():
                if state.status != "running":
                    continue
                prior_payload = state.last_event.get("payload", {})
                self.journal.append(
                    "job_interrupted",
                    {
                        "jobId": state.job.job_id,
                        "workerToken": lease.token,
                        "reason": "previous_worker_released_without_terminal_event",
                        "abandonedWorkerToken": prior_payload.get("workerToken"),
                        "abandonedWorkerPid": prior_payload.get("workerPid"),
                        "failureClass": "worker_lease_abandoned",
                        "executionMeasurement": _optional_execution_measurement(None),
                        **self._attempt_metadata(state.job.job_id),
                        "localCost": _local_cost_observation(),
                    },
                )

    def _require_state(self, job_id: str) -> JobState:
        state = self.states().get(job_id)
        if state is None:
            raise LocalQueueError(f"unknown_job:{job_id}")
        return state

    def _require_active_lease(self, lease: WorkerLease) -> None:
        if lease.pid != os.getpid() or lease.token not in self._active_leases:
            raise WorkerLeaseUnavailable("worker_lease_not_active_in_this_process")

    def _require_running_for_lease(self, lease: WorkerLease, job_id: str) -> None:
        self._require_active_lease(lease)
        state = self._require_state(job_id)
        if state.status != "running":
            raise InvalidJobTransition(f"job_not_running:{job_id}:{state.status}")
        payload = state.last_event.get("payload", {})
        if payload.get("workerToken") != lease.token:
            raise WorkerLeaseUnavailable("job_owned_by_different_worker_lease")


def default_local_generation_queue(root: Path | None = None) -> LocalGenerationQueue:
    selected = root or os.environ.get("CREATOR_OS_LOCAL_GENERATION_QUEUE_ROOT")
    queue_root = (
        Path(selected).expanduser().resolve()
        if selected
        else (Path.home() / ".creator-os/state/reel_factory/local_generation").resolve()
    )
    physical = _physical_memory_bytes() or 64 * 1024**3
    memory_reserve_bytes = int(
        os.environ.get(
            "CREATOR_OS_LOCAL_GENERATION_MEMORY_RESERVE_BYTES",
            str(6 * 1024**3),
        )
    )
    # Keep the 8 GiB lower target on ordinary Macs, but never claim a queue
    # ceiling larger than the machine itself. Small CI/dev hosts must still be
    # able to inspect and reconcile the journal even though no video model will
    # pass their live-memory admission gate.
    resource_limit_bytes = min(
        physical,
        max(8 * 1024**3, physical - memory_reserve_bytes),
    )
    return LocalGenerationQueue(
        queue_root,
        resource_limit_bytes=resource_limit_bytes,
        memory_reserve_bytes=memory_reserve_bytes,
    )


def _state_payload(state: JobState) -> dict[str, Any]:
    return {
        **state.job.as_dict(),
        "status": state.status,
        "lastEventType": state.last_event.get("eventType"),
        "lastEventAt": state.last_event.get("occurredAt"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the local generation lease journal or recover exact work."
    )
    parser.add_argument("--root", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    recover = sub.add_parser("recover-interrupted")
    recover.add_argument("--job-id", required=True)
    recover.add_argument("--lineage", required=True, type=Path)
    recover.add_argument("--reason", required=True)
    recover_empty = sub.add_parser("recover-empty-interruption")
    recover_empty.add_argument("--job-id", required=True)
    recover_empty.add_argument("--lineage", required=True, type=Path)
    recover_empty.add_argument("--reason", required=True)
    recover_completed = sub.add_parser("recover-completed-interruption")
    recover_completed.add_argument("--job-id", required=True)
    recover_completed.add_argument("--lineage", required=True, type=Path)
    recover_completed.add_argument("--reason", required=True)
    cancel = sub.add_parser("cancel-queued")
    cancel.add_argument("--job-id", required=True)
    cancel.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    queue = default_local_generation_queue(args.root)
    payload: dict[str, Any]
    try:
        if args.command == "recover-interrupted":
            recovery = queue.recover_interrupted(
                args.job_id, lineage_path=args.lineage, reason=args.reason
            )
            payload = {
                "schema": "reel_factory.local_generation_queue_action.v1",
                "action": "recover_interrupted",
                "job": _state_payload(recovery.state),
                "recoveryId": recovery.recovery_id,
                "manifestPath": str(recovery.manifest_path),
                "artifacts": [dict(item) for item in recovery.artifacts],
            }
        elif args.command == "recover-empty-interruption":
            state = queue.recover_empty_interruption(
                args.job_id, lineage_path=args.lineage, reason=args.reason
            )
            payload = {
                "schema": "reel_factory.local_generation_queue_action.v1",
                "action": "recover_empty_interruption",
                "job": _state_payload(state),
            }
        elif args.command == "recover-completed-interruption":
            state = queue.recover_completed_interruption(
                args.job_id, lineage_path=args.lineage, reason=args.reason
            )
            payload = {
                "schema": "reel_factory.local_generation_queue_action.v1",
                "action": "recover_completed_interruption",
                "job": _state_payload(state),
            }
        elif args.command == "cancel-queued":
            state = queue.cancel_queued(args.job_id, reason=args.reason)
            payload = {
                "schema": "reel_factory.local_generation_queue_action.v1",
                "action": "cancel_queued",
                "job": _state_payload(state),
            }
        else:
            states = queue.states()
            payload = {
                "schema": "reel_factory.local_generation_queue_status.v1",
                "root": str(queue.root),
                "resourceLimitBytes": queue.resource_limit_bytes,
                "memoryReserveBytes": queue.memory_reserve_bytes,
                "currentAvailableMemoryBytes": _macos_available_memory_bytes(),
                "jobs": [_state_payload(states[job_id]) for job_id in sorted(states)],
            }
    except (LocalQueueError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
