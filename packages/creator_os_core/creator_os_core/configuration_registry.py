"""Typed, redaction-safe configuration governance for Creator OS.

The registry is intentionally metadata-only: it never reads dotenv files and it
never persists secret values. Validation is scoped to the operation being
attempted so harmless read-only commands do not require provider credentials.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any


class ConfigType(StrEnum):
    STRING = "string"
    STRING_LIST = "string_list"
    BOOLEAN = "boolean"
    POSITIVE_FLOAT = "positive_float"
    NONNEGATIVE_FLOAT = "nonnegative_float"
    POSITIVE_INTEGER = "positive_integer"
    NONNEGATIVE_INTEGER = "nonnegative_integer"
    ABSOLUTE_PATH = "absolute_path"
    HTTPS_URL = "https_url"
    UUID = "uuid"
    SHA256 = "sha256"


class FailBehavior(StrEnum):
    CLOSED = "fail_closed"
    OPEN_READ_ONLY = "fail_open_read_only"


@dataclass(frozen=True, slots=True)
class ConfigSpec:
    name: str
    owner: str
    purpose: str
    value_type: ConfigType
    sensitive: bool
    required_environments: tuple[str, ...]
    default: str | int | float | bool | tuple[str, ...] | None
    validation: str
    fail_behavior: FailBehavior
    rotation: str
    redaction: str
    change_impact: str
    source: str = "environment"


class ConfigurationValidationError(PermissionError):
    """Raised with names/reasons only; configuration values are never included."""

    def __init__(self, operation: str, issues: Sequence[Mapping[str, str]]) -> None:
        self.operation = operation
        self.issues = tuple(dict(issue) for issue in issues)
        summary = ",".join(
            f"{issue['name']}:{issue['reason']}" for issue in self.issues
        )
        super().__init__(f"configuration_blocked:{operation}:{summary}")


_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})
_PRODUCTION = ("production",)
_ALL_RUNTIME = ("development", "test", "production")
PROCESS_ENVIRONMENT_VARIABLES = frozenset(
    {
        "DYLD_FALLBACK_LIBRARY_PATH",
        "GITHUB_PATH",
        "HOME",
        "PATH",
        "RUNNER_TEMP",
        "TMPDIR",
        "USER",
        "VIRTUAL_ENV",
    }
)


def _spec(
    name: str,
    owner: str,
    purpose: str,
    value_type: ConfigType = ConfigType.STRING,
    *,
    sensitive: bool = False,
    required: tuple[str, ...] = (),
    default: str | int | float | bool | tuple[str, ...] | None = None,
    validation: str = "nonempty when configured",
    fail: FailBehavior = FailBehavior.OPEN_READ_ONLY,
    rotation: str = "change through reviewed runtime configuration",
    redaction: str | None = None,
    impact: str = "takes effect for the next operation",
    source: str = "environment",
) -> ConfigSpec:
    return ConfigSpec(
        name=name,
        owner=owner,
        purpose=purpose,
        value_type=value_type,
        sensitive=sensitive,
        required_environments=required,
        default=default,
        validation=validation,
        fail_behavior=fail,
        rotation=rotation,
        redaction=redaction or ("full" if sensitive else "none"),
        change_impact=impact,
        source=source,
    )


_SPECS = [
    _spec(
        "CREATOR_OS_ENVIRONMENT",
        "creator_os_core",
        "Select development, test, or production safety policy.",
        default="development",
        validation="development|test|production",
        impact="changes operation-specific required configuration",
    ),
    _spec(
        "CREATOR_OS_KILL_SWITCH",
        "creator_os_core",
        "Emergency stop for paid and outbound writes.",
        ConfigType.BOOLEAN,
        required=_PRODUCTION,
        validation="explicit boolean; production has no implicit inactive default",
        fail=FailBehavior.CLOSED,
        impact="immediately blocks or permits state-changing operations",
    ),
    _spec(
        "CREATOR_OS_API_TOKEN",
        "creator_os_core",
        "Authenticate the local Creator OS API.",
        sensitive=True,
        required=_PRODUCTION,
        validation="at least 24 characters",
        fail=FailBehavior.CLOSED,
        rotation="rotate after exposure and at least every 90 days",
        impact="invalidates local API clients",
    ),
    _spec(
        "CREATOR_OS_API_ROLE",
        "creator_os_core",
        "Default authenticated local API role.",
        default="operator",
        validation="nonempty role name",
        impact="changes local API authorization scope",
    ),
    _spec(
        "ALLOW_INSECURE_LOCAL",
        "creator_os_core",
        "Explicit loopback-only development authentication bypass.",
        ConfigType.BOOLEAN,
        default=False,
        validation="boolean; forbidden for production startup",
        fail=FailBehavior.CLOSED,
        impact="changes local API trust boundary",
    ),
    _spec(
        "CREATOR_OS_EVIDENCE_AUTH_SECRET",
        "creator_os_core",
        "Sign and verify evidence attestations.",
        sensitive=True,
        required=_PRODUCTION,
        validation="at least 32 characters",
        fail=FailBehavior.CLOSED,
        rotation="versioned rotation retaining historical verification keys",
        impact="changes evidence signing identity; historical verification required",
    ),
    _spec(
        "CREATOR_OS_SPEND_AUTH_SECRET",
        "campaign_factory",
        "Sign paid-provider authorizations.",
        sensitive=True,
        required=_PRODUCTION,
        validation="at least 32 characters",
        fail=FailBehavior.CLOSED,
        rotation="rotate with outstanding authorization reconciliation",
        impact="invalidates unconsumed paid-action authorizations",
    ),
]

for name, purpose in (
    ("CREATOR_OS_ROOT", "Creator OS source checkout root."),
    ("CREATOR_OS_RUNTIME_ROOT", "Protected runtime root."),
    ("CREATOR_OS_STATE_ROOT", "Persistent state root."),
    ("CREATOR_OS_ARTIFACT_ROOT", "Retained artifact root."),
    ("CREATOR_OS_MODEL_ROOT", "Local model-byte root."),
    ("CREATOR_OS_LOG_ROOT", "Runtime log root."),
    ("CAMPAIGN_FACTORY_ROOT", "Campaign Factory package root."),
    ("REEL_FACTORY_ROOT", "Reel Factory package root."),
    ("REFERENCE_FACTORY_ROOT", "Reference Factory package root."),
    ("CONTENTFORGE_ROOT", "ContentForge package root."),
    ("THREADSDASH_ROOT", "ThreadsDashboard checkout root."),
    ("REFERENCE_FACTORY_DATA_ROOT", "Reference Factory retained data root."),
    ("REFERENCE_REELS_ROOT", "Reference-Reel retained data root."),
    ("CAMPAIGN_FACTORY_DB", "Campaign Factory SQLite path."),
    ("REFERENCE_FACTORY_DB", "Reference Factory SQLite path."),
    ("REEL_FACTORY_MANIFEST_DB", "Reel Factory manifest SQLite path."),
    ("REEL_FACTORY_RENDER_QUEUE_DB", "Reel Factory render-queue SQLite path."),
    ("CAMPAIGN_FACTORY_CAMPAIGNS", "Campaign artifact root."),
    ("CAMPAIGN_FACTORY_CREATIVE_APPROVALS", "Creative approval receipt root."),
    ("CREATOR_OS_LOCAL_MODELS_ROOT", "Local model inventory root."),
    ("CREATOR_OS_LOCAL_MLX_RUNTIME", "Local MLX runtime root."),
    ("CREATOR_OS_LOCAL_MLX_VLM_RUNTIME", "Local MLX VLM runtime root."),
    ("CREATOR_OS_LOCAL_LTX_RUNTIME", "Local LTX runtime root."),
    ("CREATOR_OS_LOCAL_LONGCAT_RUNTIME", "Local LongCat runtime root."),
    ("CREATOR_OS_LOCAL_MODEL_BENCHMARK_ROOT", "Local model benchmark root."),
    ("CREATOR_OS_LOCAL_GENERATION_QUEUE_ROOT", "Local generation queue root."),
    ("REEL_FACTORY_IDENTITY_MODEL_ROOT", "Identity detector model root."),
    ("REEL_FACTORY_IDENTITY_REFERENCE_SET", "Approved identity reference set."),
    ("CAMPAIGN_REFERENCE_BANK", "Campaign reference bank path."),
    ("HIGGSFIELD_PROMPT_PACK", "Approved Higgsfield prompt-pack path."),
    ("CREATOR_OS_EMBEDDED_AUDIO_FIXTURE", "Explicit embedded-audio fixture."),
    ("CREATOR_OS_TD_SNAPSHOT", "ThreadsDashboard evidence snapshot path."),
    ("CREATOR_OS_UI_PROOF", "Operator UI-proof artifact path."),
    (
        "CONTENTFORGE_APPLE_VISION_SCRIPT",
        "ContentForge Apple Vision OCR helper path.",
    ),
):
    _SPECS.append(
        _spec(
            name,
            "runtime_paths",
            purpose,
            ConfigType.ABSOLUTE_PATH,
            validation="absolute path after expansion",
            impact="requires path-rebinding and backup coverage review",
        )
    )

for name, owner, purpose in (
    ("OPENAI_API_KEY", "campaign_factory", "Authorize OpenAI provider calls."),
    ("HIGGSFIELD_API_KEY", "reel_factory", "Authorize Higgsfield provider calls."),
    ("GEMINI_API_KEY", "reference_factory", "Authorize Gemini provider calls."),
    ("GOOGLE_API_KEY", "reference_factory", "Gemini credential alias."),
    ("XAI_API_KEY", "reference_factory", "Authorize xAI provider calls."),
    ("GROK_API_KEY", "reference_factory", "xAI credential alias."),
    ("WAVESPEED_API_KEY", "campaign_factory", "Authorize WaveSpeed provider calls."),
    (
        "CAMPAIGN_FACTORY_INGEST_SECRET",
        "campaign_factory",
        "Authenticate the ThreadsDashboard draft handoff.",
    ),
    (
        "SUPABASE_SERVICE_ROLE_KEY",
        "campaign_factory",
        "Authorize privileged Supabase operations.",
    ),
    ("SUPABASE_SERVICE_KEY", "campaign_factory", "Legacy Supabase service-key alias."),
    ("SUPABASE_SECRET_KEY", "campaign_factory", "Supabase secret-key alias."),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            sensitive=True,
            validation="nonempty secret; at least 16 characters",
            fail=FailBehavior.CLOSED,
            rotation="rotate after exposure and according to provider policy",
            impact="blocks or invalidates provider/external integration calls",
        )
    )

for name, owner, purpose in (
    ("SUPABASE_URL", "campaign_factory", "Canonical Supabase project URL."),
    ("VITE_SUPABASE_URL", "campaign_factory", "Legacy public Supabase URL alias."),
    (
        "THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL",
        "campaign_factory",
        "ThreadsDashboard authenticated ingest endpoint.",
    ),
    (
        "CAMPAIGN_FACTORY_DRAFT_INGEST_URL",
        "campaign_factory",
        "Legacy ThreadsDashboard ingest endpoint alias.",
    ),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            ConfigType.HTTPS_URL,
            validation="public HTTPS URL",
            fail=FailBehavior.CLOSED,
            impact="changes the external data destination",
        )
    )

for name, owner, purpose, bool_default in (
    (
        "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS",
        "campaign_factory",
        "Enable scheduled campaign synchronization.",
        False,
    ),
    (
        "CAMPAIGN_FACTORY_AUDIO_FIT",
        "campaign_factory",
        "Enable optional visual/audio-fit signal.",
        False,
    ),
    (
        "CAMPAIGN_FACTORY_ALLOW_LOCAL_THREADSDASH_INGEST",
        "campaign_factory",
        "Allow explicit local ThreadsDashboard ingest.",
        False,
    ),
    (
        "REEL_FACTORY_GI_ENV_READY",
        "reel_factory",
        "Declare prepared local GI caption-render environment.",
        False,
    ),
    ("HF_HUB_OFFLINE", "reel_factory", "Force offline Hugging Face access.", False),
    (
        "CONTENTFORGE_ASSUME_DRAWTEXT",
        "contentforge",
        "Override drawtext capability detection for a prepared runtime.",
        False,
    ),
    (
        "CONTENTFORGE_DEBUG_OCR_BOXES",
        "contentforge",
        "Include OCR debug boxes in local diagnostic output.",
        False,
    ),
    (
        "HIGGSFIELD_ACCOUNT_EXCLUSIVE_BALANCE_DELTAS",
        "campaign_factory",
        "Permit balance-delta reconciliation only for an exclusive account run.",
        False,
    ),
    (
        "REQUIRE_SECRET_SCANNER",
        "tooling",
        "Fail verification when the configured secret scanner is unavailable.",
        False,
    ),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            ConfigType.BOOLEAN,
            default=bool_default,
            validation="explicit boolean",
            impact="changes the next scoped runtime operation",
        )
    )

for name, owner, purpose in (
    (
        "LEARNING_FANOUT_MAX_ATTEMPTS",
        "campaign_factory",
        "Bound learning fanout retries.",
    ),
    (
        "REFERENCE_BANK_ACCOUNT_CAP",
        "reference_factory",
        "Bound reference-bank account sampling.",
    ),
    (
        "CONTENTFORGE_VARIANT_PACK_TIMEOUT_SECONDS",
        "contentforge",
        "Bound ContentForge variant-pack execution time.",
    ),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            ConfigType.POSITIVE_INTEGER,
            validation="integer greater than zero",
            impact="changes bounded capacity or timeout behavior",
        )
    )

for name, owner, purpose in (
    (
        "CREATOR_OS_AUDIO_REFRESH_MAX_NEW",
        "audio_radar",
        "Bound new audio candidates per refresh.",
    ),
    (
        "CREATOR_OS_DAILY_ORCHESTRATOR_PROVIDER_CAP",
        "campaign_factory",
        "Bound paid provider jobs per daily run.",
    ),
    (
        "CREATOR_OS_LOCAL_GENERATION_MEMORY_RESERVE_BYTES",
        "reel_factory",
        "Reserve host memory from local generation admission.",
    ),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            ConfigType.NONNEGATIVE_INTEGER,
            validation="integer greater than or equal to zero",
            impact="changes bounded runtime capacity",
        )
    )

for name, owner, purpose in (
    (
        "CREATOR_OS_AUDIO_REFRESH_MAX_ACTIVE",
        "audio_radar",
        "Bound active audio inventory retained after refresh.",
    ),
    (
        "CREATOR_OS_DAILY_ORCHESTRATOR_MAX_ITEMS",
        "campaign_factory",
        "Bound items in one daily orchestration run.",
    ),
    (
        "CREATOR_OS_DAILY_ORCHESTRATOR_PER_CAMPAIGN",
        "campaign_factory",
        "Bound daily items per campaign.",
    ),
    (
        "CREATOR_OS_DAILY_ORCHESTRATOR_PER_CREATOR",
        "campaign_factory",
        "Bound daily items per creator.",
    ),
    ("GITLEAKS_TIMEOUT_SECONDS", "tooling", "Bound local gitleaks execution time."),
    (
        "HIGGSFIELD_KLING_DAILY_MAX_GENERATIONS",
        "campaign_factory",
        "Bound daily Kling generations.",
    ),
    (
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "campaign_factory",
        "Bound generated assets per provider run.",
    ),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            ConfigType.POSITIVE_INTEGER,
            validation="integer greater than zero",
            impact="changes bounded runtime capacity",
        )
    )

for name, owner, purpose in (
    (
        "CREATOR_OS_GEMINI_ANALYSIS_QUOTE_USD",
        "campaign_factory",
        "Authorize the configured upper-bound quote for reference analysis.",
    ),
    (
        "HIGGSFIELD_COHORT_MAX_CREDITS",
        "campaign_factory",
        "Bound total credits for a generation cohort.",
    ),
    (
        "HIGGSFIELD_DAILY_BUDGET_CREDITS",
        "campaign_factory",
        "Bound daily Higgsfield credits.",
    ),
    (
        "HIGGSFIELD_MONTHLY_BUDGET_CREDITS",
        "campaign_factory",
        "Bound monthly Higgsfield credits.",
    ),
    (
        "HIGGSFIELD_RUN_MAX_CREDITS",
        "campaign_factory",
        "Bound credits per Higgsfield run.",
    ),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            ConfigType.POSITIVE_FLOAT,
            validation="finite number greater than zero",
            fail=FailBehavior.CLOSED,
            impact="changes paid-action authorization capacity",
        )
    )

for name, owner, purpose in (
    (
        "CONTENTFORGE_AUDIT_HISTORY_DIR",
        "contentforge",
        "Retained ContentForge audit-history root.",
    ),
    ("CONTENTFORGE_OUTPUT_DIR", "contentforge", "Run-scoped ContentForge output root."),
    (
        "CONTENTFORGE_REAL_SAMPLE_MANIFEST",
        "contentforge",
        "Explicit real-media audit manifest.",
    ),
    ("CONTENTFORGE_SSCD_MODEL_PATH", "contentforge", "ContentForge SSCD model path."),
    ("SSCD_MODEL_PATH", "reel_factory", "Reel Factory SSCD model path alias."),
    ("CREATOR_OS_AUDIO_CACHE", "audio_radar", "Downloaded audio-byte cache root."),
    ("CREATOR_OS_AUDIO_RECEIPTS", "audio_radar", "Audio refresh receipt root."),
    (
        "CREATOR_OS_AUDIO_REFRESH_ENV",
        "audio_radar",
        "Private Audio Radar refresh environment file.",
    ),
    (
        "CREATOR_OS_AUDIO_REFRESH_LOCK",
        "audio_radar",
        "Audio refresh mutual-exclusion lock path.",
    ),
    (
        "CREATOR_OS_AUDIO_REFRESH_REPORT_DIR",
        "audio_radar",
        "Audio refresh report root.",
    ),
    (
        "CREATOR_OS_GENERATION_ENV",
        "campaign_factory",
        "Private generation policy environment file.",
    ),
    ("CREATOR_OS_LEARNING_STATE", "campaign_factory", "Learning refresh state path."),
    (
        "CREATOR_OS_PERFORMANCE_SYNC_ENV",
        "campaign_factory",
        "Private performance-sync environment file.",
    ),
    (
        "PROMPT_REGRESSION_PYTHON",
        "tooling",
        "Python executable used for prompt-regression checks.",
    ),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            ConfigType.ABSOLUTE_PATH,
            validation="absolute path after expansion",
            impact="changes the next scoped operation's byte or state location",
        )
    )

for name, owner, purpose in (
    ("CONTENTFORGE_OCR_ENGINE", "contentforge", "Select the configured OCR engine."),
    (
        "CONTENTFORGE_PYTHON",
        "contentforge",
        "Python command used by ContentForge helpers.",
    ),
    (
        "CREATOR_OS_AUDIO_REFRESH_REGION",
        "audio_radar",
        "Region used for audio discovery.",
    ),
    (
        "CREATOR_OS_DAILY_ORCHESTRATOR_MODE",
        "campaign_factory",
        "Select preview, plan, or execute orchestration behavior.",
    ),
    (
        "CREATOR_OS_DAILY_ORCHESTRATOR_RUN_KEY",
        "campaign_factory",
        "Idempotency key for a daily orchestration run.",
    ),
    (
        "CREATOR_OS_GEMINI_ANALYSIS_MODEL",
        "campaign_factory",
        "Pinned Gemini reference-analysis model.",
    ),
    (
        "CREATOR_OS_GEMINI_ANALYSIS_PRICING_VERSION",
        "campaign_factory",
        "Pricing evidence version for Gemini analysis.",
    ),
    (
        "CREATOR_OS_IDEMPOTENCY_KEY",
        "campaign_factory",
        "Operator mutation idempotency key.",
    ),
    (
        "CREATOR_OS_RUNTIME_SHA",
        "creator_os_core",
        "Exact runtime Git commit recorded in operational evidence.",
    ),
    ("REDDIT_USER_AGENT", "campaign_factory", "Reddit research client user agent."),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            validation="nonempty when configured",
            impact="changes the next scoped operation or evidence identity",
        )
    )

for name, owner, purpose in (
    ("REDDIT_CLIENT_ID", "campaign_factory", "Authorize Reddit research API access."),
    (
        "REDDIT_CLIENT_SECRET",
        "campaign_factory",
        "Authorize Reddit research API access.",
    ),
    ("SOCIALCRAWL_API_KEY", "audio_radar", "Authorize SocialCrawl audio discovery."),
    ("TIKLIVE_API_KEY", "audio_radar", "Authorize TikLive audio discovery."),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            sensitive=True,
            validation="nonempty secret; at least 16 characters",
            fail=FailBehavior.CLOSED,
            rotation="rotate after exposure and according to provider policy",
            impact="blocks or invalidates the owning external integration",
        )
    )

_SPECS.extend(
    (
        _spec(
            "HIGGSFIELD_MIN_BALANCE_CREDITS",
            "campaign_factory",
            "Minimum provider balance required before generation.",
            ConfigType.NONNEGATIVE_FLOAT,
            default=0.0,
            validation="finite number greater than or equal to zero",
            fail=FailBehavior.CLOSED,
            impact="changes provider-spend admission",
        ),
        _spec(
            "REFERENCE_BANK_CAPTION_SHARE",
            "reference_factory",
            "Reference-bank caption sampling share.",
            ConfigType.NONNEGATIVE_FLOAT,
            validation="finite number between zero and one",
            impact="changes reference sampling composition",
        ),
        _spec(
            "CREATOR_OS_SOURCE_SHA",
            "creator_os_core",
            "Exact source commit recorded in migration and render evidence.",
            ConfigType.SHA256,
            validation="64 lowercase hexadecimal characters",
            fail=FailBehavior.CLOSED,
            impact="changes runtime/evidence source attribution",
        ),
    )
)

for name, owner, purpose in (
    (
        "CREATOR_OS_OPENAI_PROMPT_MODEL",
        "campaign_factory",
        "Pinned OpenAI prompt model.",
    ),
    (
        "CREATOR_OS_ACCEPTANCE_DRIVER",
        "campaign_factory",
        "Explicit real-provider acceptance driver command.",
    ),
    ("VERIFICATION_BASE_REF", "tooling", "Git base ref for affected verification."),
    (
        "THREADSDASH_ALLOWED_INGEST_HOSTS",
        "campaign_factory",
        "Allowlisted ThreadsDashboard ingest hosts.",
    ),
    ("THREADSDASH_USER_ID", "campaign_factory", "ThreadsDashboard operator user ID."),
    (
        "THREADSDASH_WORKSPACE_ID",
        "campaign_factory",
        "ThreadsDashboard workspace identifier.",
    ),
    ("SUPABASE_STORAGE_BUCKET", "campaign_factory", "Supabase media bucket."),
    (
        "CREATOR_OS_EMBEDDED_AUDIO_FIXTURE_TITLE",
        "campaign_factory",
        "Explicit embedded-audio fixture label.",
    ),
):
    _SPECS.append(
        _spec(
            name,
            owner,
            purpose,
            validation="nonempty when configured",
            impact="changes the next scoped operation or evidence label",
        )
    )

for name in (
    "CREATOR_OS_PAID_DAILY_CAP_USD",
    "CREATOR_OS_PAID_MONTHLY_CAP_USD",
    "CREATOR_OS_CREATOR_DAILY_CAP_USD",
    "CREATOR_OS_CAMPAIGN_DAILY_CAP_USD",
    "CREATOR_OS_OPENAI_DAILY_CAP_USD",
    "CREATOR_OS_GEMINI_DAILY_CAP_USD",
    "CREATOR_OS_XAI_DAILY_CAP_USD",
    "CREATOR_OS_WAVESPEED_DAILY_CAP_USD",
    "CREATOR_OS_HIGGSFIELD_DAILY_CAP_USD",
    "CREATOR_OS_OPENAI_PROMPT_QUOTE_USD",
):
    _SPECS.append(
        _spec(
            name,
            "campaign_factory",
            "Bound paid-provider quote or spend capacity.",
            ConfigType.POSITIVE_FLOAT,
            required=_PRODUCTION,
            validation="finite number greater than zero",
            fail=FailBehavior.CLOSED,
            impact="changes paid-action authorization capacity",
        )
    )

for name, purpose in (
    ("CREATOR_OS_SOUL_ID_STACEY", "Stacey canonical Soul identity."),
    ("CREATOR_OS_SOUL_ID_STACEY1", "Stacey1 canonical Soul identity."),
    ("CREATOR_OS_SOUL_ID_LARISSA", "Larissa canonical Soul identity."),
    ("CREATOR_OS_SOUL_ID_LOLA", "Lola canonical Soul identity."),
):
    _SPECS.append(
        _spec(
            name,
            "campaign_factory",
            purpose,
            ConfigType.UUID,
            validation="UUID bound to an approved creator identity version",
            fail=FailBehavior.CLOSED,
            impact="invalidates generation plans for the prior identity version",
        )
    )

for name, purpose, project_default in (
    ("reel_factory.workers", "Local render-worker count.", 3),
    ("reel_factory.caption_renderer", "Caption renderer selection.", "pillow"),
    ("reel_factory.placement_mode", "Caption placement policy.", "source"),
    (
        "reel_factory.output_profile",
        "FFmpeg/platform output profile.",
        "mac_h264_videotoolbox",
    ),
    ("reel_factory.target_ratios", "Permitted output aspect ratios.", ("9:16",)),
    ("reel_factory.audio_enabled", "Local project audio switch.", False),
    ("reel_factory.strict_preflight", "Local project strict-preflight switch.", False),
    ("reel_factory.dailyBudgetUsd", "Local project daily budget.", 10.0),
    ("reel_factory.perRunMaxAssets", "Local project per-run asset cap.", 2),
    ("reel_factory.minimumBalanceUsd", "Local project minimum balance.", 5.0),
):
    value_type = (
        ConfigType.BOOLEAN
        if isinstance(project_default, bool)
        else ConfigType.POSITIVE_INTEGER
        if isinstance(project_default, int)
        else ConfigType.POSITIVE_FLOAT
        if isinstance(project_default, float)
        else ConfigType.STRING_LIST
        if isinstance(project_default, tuple)
        else ConfigType.STRING
    )
    _SPECS.append(
        _spec(
            name,
            "reel_factory",
            purpose,
            value_type,
            default=project_default,
            validation="typed Reel Factory project setting",
            impact="changes subsequent local render planning",
            source="reel_factory.toml",
        )
    )


if len({spec.name for spec in _SPECS}) != len(_SPECS):
    raise RuntimeError("duplicate Creator OS configuration registry name")
CONFIG_REGISTRY: Mapping[str, ConfigSpec] = MappingProxyType(
    {spec.name: spec for spec in _SPECS}
)

_COMMON_PAID = (
    ("CREATOR_OS_SPEND_AUTH_SECRET",),
    ("CREATOR_OS_PAID_DAILY_CAP_USD",),
    ("CREATOR_OS_PAID_MONTHLY_CAP_USD",),
    ("CREATOR_OS_CREATOR_DAILY_CAP_USD",),
    ("CREATOR_OS_CAMPAIGN_DAILY_CAP_USD",),
)
OPERATION_REQUIREMENTS: Mapping[str, tuple[tuple[str, ...], ...]] = MappingProxyType(
    {
        "read_only": (),
        "backup": (),
        "restore_drill": (),
        "state_change": (("CREATOR_OS_KILL_SWITCH",),),
        "production_startup": (
            ("CREATOR_OS_KILL_SWITCH",),
            ("CREATOR_OS_API_TOKEN",),
            ("CREATOR_OS_EVIDENCE_AUTH_SECRET",),
        ),
        "paid_openai": _COMMON_PAID
        + (("OPENAI_API_KEY",), ("CREATOR_OS_OPENAI_DAILY_CAP_USD",)),
        "paid_higgsfield": _COMMON_PAID
        + (("HIGGSFIELD_API_KEY",), ("CREATOR_OS_HIGGSFIELD_DAILY_CAP_USD",)),
        "paid_gemini": _COMMON_PAID
        + (("GEMINI_API_KEY", "GOOGLE_API_KEY"), ("CREATOR_OS_GEMINI_DAILY_CAP_USD",)),
        "paid_xai": _COMMON_PAID
        + (("XAI_API_KEY", "GROK_API_KEY"), ("CREATOR_OS_XAI_DAILY_CAP_USD",)),
        "paid_wavespeed": _COMMON_PAID
        + (("WAVESPEED_API_KEY",), ("CREATOR_OS_WAVESPEED_DAILY_CAP_USD",)),
        "threadsdash_handoff": (
            ("CREATOR_OS_KILL_SWITCH",),
            ("CAMPAIGN_FACTORY_INGEST_SECRET",),
            (
                "THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL",
                "CAMPAIGN_FACTORY_DRAFT_INGEST_URL",
            ),
        ),
    }
)


def parse_config_value(spec: ConfigSpec, value: Any) -> Any:
    """Normalize one configured value or raise a value-free validation error."""

    if value is None or value == "":
        raise ValueError("missing")
    if spec.value_type is ConfigType.STRING:
        normalized = str(value).strip()
        minimum = 16 if spec.sensitive else 1
        if len(normalized) < minimum:
            raise ValueError("too_short")
        return normalized
    if spec.value_type is ConfigType.STRING_LIST:
        raw_items = value if isinstance(value, (list, tuple)) else str(value).split(",")
        normalized_items = tuple(
            str(item).strip() for item in raw_items if str(item).strip()
        )
        if not normalized_items:
            raise ValueError("empty_list")
        return normalized_items
    if spec.value_type is ConfigType.BOOLEAN:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in _TRUE:
            return True
        if normalized in _FALSE:
            return False
        raise ValueError("invalid_boolean")
    if spec.value_type in {
        ConfigType.POSITIVE_FLOAT,
        ConfigType.NONNEGATIVE_FLOAT,
        ConfigType.POSITIVE_INTEGER,
        ConfigType.NONNEGATIVE_INTEGER,
    }:
        if isinstance(value, bool):
            raise ValueError("invalid_number")
        number = float(value)
        if not math.isfinite(number) or (
            number < 0
            if spec.value_type
            in {ConfigType.NONNEGATIVE_FLOAT, ConfigType.NONNEGATIVE_INTEGER}
            else number <= 0
        ):
            raise ValueError("not_positive")
        if spec.value_type in {
            ConfigType.POSITIVE_INTEGER,
            ConfigType.NONNEGATIVE_INTEGER,
        }:
            if not number.is_integer():
                raise ValueError("not_integer")
            return int(number)
        return number
    if spec.value_type is ConfigType.ABSOLUTE_PATH:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            raise ValueError("not_absolute")
        return str(path)
    if spec.value_type is ConfigType.HTTPS_URL:
        normalized = str(value).strip()
        if (
            not normalized.startswith("https://")
            or "@" in normalized.split("://", 1)[1].split("/", 1)[0]
        ):
            raise ValueError("invalid_https_url")
        return normalized
    if spec.value_type is ConfigType.UUID:
        normalized = str(value).strip()
        if not _UUID.fullmatch(normalized):
            raise ValueError("invalid_uuid")
        return normalized.lower()
    if spec.value_type is ConfigType.SHA256:
        normalized = str(value).strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", normalized):
            raise ValueError("invalid_sha256")
        return normalized
    raise ValueError("unsupported_type")


def validate_operation_configuration(
    operation: str,
    *,
    values: Mapping[str, Any],
    environment: str | None = None,
) -> dict[str, Any]:
    """Validate only configuration that can affect ``operation``."""

    if operation not in OPERATION_REQUIREMENTS:
        raise ValueError(f"unknown configuration operation: {operation}")
    selected_environment = (
        (environment or str(values.get("CREATOR_OS_ENVIRONMENT") or "development"))
        .strip()
        .lower()
    )
    if selected_environment not in {"development", "test", "production"}:
        raise ConfigurationValidationError(
            operation,
            ({"name": "CREATOR_OS_ENVIRONMENT", "reason": "invalid_environment"},),
        )
    issues: list[dict[str, str]] = []
    checked: list[str] = []
    groups = OPERATION_REQUIREMENTS[operation]
    for alternatives in groups:
        # The kill switch has no implicit inactive value in production, but a
        # missing value remains harmless for development-only read/write tests.
        if (
            alternatives == ("CREATOR_OS_KILL_SWITCH",)
            and selected_environment != "production"
            and not any(
                values.get(name) is not None and values.get(name) != ""
                for name in alternatives
            )
        ):
            continue
        selected = next(
            (
                name
                for name in alternatives
                if values.get(name) is not None and values.get(name) != ""
            ),
            None,
        )
        if selected is None:
            issues.append(
                {"name": "|".join(alternatives), "reason": "missing_required"}
            )
            continue
        checked.append(selected)
        spec = CONFIG_REGISTRY[selected]
        try:
            parsed = parse_config_value(spec, values[selected])
        except (TypeError, ValueError, OverflowError):
            issues.append({"name": selected, "reason": "invalid"})
            continue
        if selected == "CREATOR_OS_KILL_SWITCH" and parsed is True:
            issues.append({"name": selected, "reason": "active"})
    if (
        operation not in {"read_only", "backup", "restore_drill"}
        and selected_environment == "production"
        and str(values.get("ALLOW_INSECURE_LOCAL") or "").strip().lower() in _TRUE
    ):
        issues.append({"name": "ALLOW_INSECURE_LOCAL", "reason": "forbidden"})
    if issues:
        raise ConfigurationValidationError(operation, issues)
    return {
        "schema": "creator_os.configuration_validation.v1",
        "operation": operation,
        "environment": selected_environment,
        "eligible": True,
        "checked": sorted(checked),
    }


def configuration_manifest(
    *,
    values: Mapping[str, Any],
    include_sources: Sequence[str] = ("environment",),
) -> dict[str, Any]:
    """Return typed presence metadata without exposing secret material."""

    included = set(include_sources)
    items: list[dict[str, Any]] = []
    for name, spec in sorted(CONFIG_REGISTRY.items()):
        if spec.source not in included:
            continue
        present = values.get(name) is not None and values.get(name) != ""
        valid = False
        normalized: Any = None
        if present:
            try:
                normalized = parse_config_value(spec, values[name])
                valid = True
            except (TypeError, ValueError, OverflowError):
                pass
        items.append(
            {
                "name": name,
                "owner": spec.owner,
                "purpose": spec.purpose,
                "type": spec.value_type.value,
                "sensitive": spec.sensitive,
                "requiredEnvironments": list(spec.required_environments),
                "default": spec.default,
                "validation": spec.validation,
                "failBehavior": spec.fail_behavior.value,
                "rotation": spec.rotation,
                "redaction": spec.redaction,
                "changeImpact": spec.change_impact,
                "source": spec.source,
                "present": present,
                "valid": valid,
                "value": (
                    "[REDACTED]"
                    if present and spec.sensitive
                    else normalized
                    if present and valid
                    else None
                ),
            }
        )
    return {
        "schema": "creator_os.configuration_registry.v1",
        "items": items,
    }


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """Redact registered and conventionally sensitive keys recursively."""

    redacted: dict[str, Any] = {}
    for key, value in values.items():
        spec = CONFIG_REGISTRY.get(key)
        conventionally_sensitive = any(
            token in key.upper()
            for token in ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "PRIVATE_KEY")
        )
        if (spec and spec.sensitive) or conventionally_sensitive:
            redacted[key] = "[REDACTED]" if value is not None and value != "" else None
        elif isinstance(value, Mapping):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact_mapping(item) if isinstance(item, Mapping) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted
