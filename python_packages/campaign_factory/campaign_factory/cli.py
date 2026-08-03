from __future__ import annotations

from types import SimpleNamespace

import uvicorn
from creator_os_core.sqlite import connect_sqlite

from .cli_dispatch_operations import dispatch_operations_commands
from .cli_dispatch_pipeline import dispatch_pipeline_commands
from .cli_dispatch_scale import dispatch_scale_commands
from .cli_parser import build_cli_parser
from .config import get_settings
from .core import CampaignFactory, new_id, slugify, utc_now
from .creator_governance import CreatorGovernanceRepository
from .db import init_db
from .incident_privacy import CreatorPrivacyRepository, IncidentRepository
from .operational_observability import OperationalObservabilityRepository
from .operator_authority import (
    authorize_cli_operation,
    claim_cli_authority_event,
    complete_cli_authority_event,
)


def main() -> int:
    parser = build_cli_parser()
    args = parser.parse_args()
    authority = authorize_cli_operation(args)
    settings = get_settings()

    if args.cmd == "serve":
        cf = CampaignFactory(settings)
        try:
            authority_claim = claim_cli_authority_event(cf.conn, authority)
        finally:
            cf.close()
        if authority_claim["status"] == "replay":
            return _replayed_exit_code(authority_claim)
        if authority_claim["status"] == "in_progress":
            raise RuntimeError("operator_operation_already_in_progress")
        if authority_claim["status"] == "reconciliation_required":
            raise RuntimeError("operator_operation_reconciliation_required")
        try:
            uvicorn.run(
                "campaign_factory.app:app",
                host=args.host,
                port=args.port,
                reload=False,
            )
        except Exception as exc:
            _complete_cli(
                settings,
                authority,
                succeeded=False,
                retryable=True,
                error=f"{type(exc).__name__}:{exc}",
            )
            raise
        _complete_cli(
            settings,
            authority,
            succeeded=True,
            exit_code=0,
        )
        return 0

    if (
        getattr(args, "cmd", None) == "create"
        and args.mode == "recreate_reel"
        and not args.apply
        and (
            getattr(args, "reference_url", None)
            or getattr(args, "reference_video", None)
        )
    ):
        # Analysis dry-runs are strictly write-free: do not construct the normal
        # CampaignFactory, whose startup intentionally applies schema migrations
        # and creates runtime directories.
        if settings.db_path.exists():
            conn = connect_sqlite(settings.db_path, readonly=True, wal=False)
            conn.execute("PRAGMA query_only = ON")
        else:
            conn = connect_sqlite(":memory:", wal=False)
            init_db(conn)
            conn.execute("PRAGMA query_only = ON")
        factory = SimpleNamespace(settings=settings, conn=conn)
        try:
            result = dispatch_pipeline_commands(args, factory, settings)
            return int(result or 0)
        finally:
            conn.close()

    if getattr(args, "cmd", None) == "reconcile" and (
        args.reconcile_cmd == "report" or not args.apply
    ):
        if not settings.db_path.exists():
            raise FileNotFoundError(
                f"reconciliation database not found: {settings.db_path}"
            )
        conn = connect_sqlite(settings.db_path, readonly=True, wal=False)
        conn.execute("PRAGMA query_only = ON")
        factory = SimpleNamespace(settings=settings, conn=conn)
        try:
            result = dispatch_pipeline_commands(args, factory, settings)
            return int(result or 0)
        finally:
            conn.close()

    if getattr(args, "cmd", None) == "production-readiness-proof":
        if not settings.db_path.exists():
            raise FileNotFoundError(
                f"production readiness database not found: {settings.db_path}"
            )
        conn = connect_sqlite(settings.db_path, readonly=True, wal=False)
        conn.execute("PRAGMA query_only = ON")
        factory = SimpleNamespace(settings=settings, conn=conn)
        try:
            result = dispatch_pipeline_commands(args, factory, settings)
            return int(result or 0)
        finally:
            conn.close()

    governance_commands = {
        "creator-governance-status",
        "creator-governance-transition",
        "creator-governance-rename",
        "creator-identity-enroll",
        "creator-authorization-grant",
        "creator-authorization-revoke",
        "campaign-governance-status",
        "campaign-governance-transition",
        "incident-report",
        "incident-create",
        "incident-transition",
        "operational-observability",
        "creator-privacy-report",
        "creator-privacy-request",
        "creator-privacy-transition",
        "creator-privacy-verify",
    }
    if getattr(args, "cmd", None) in governance_commands and not getattr(
        args, "apply", False
    ):
        if not settings.db_path.exists():
            raise FileNotFoundError(
                f"governance preview database not found: {settings.db_path}"
            )
        conn = connect_sqlite(settings.db_path, readonly=True, wal=False)
        conn.execute("PRAGMA query_only = ON")
        repository = CreatorGovernanceRepository(
            conn,
            new_id=new_id,
            slugify=slugify,
            utc_now=utc_now,
            managed_root=settings.root,
        )
        incidents = IncidentRepository(conn, new_id=new_id, utc_now=utc_now)
        creator_privacy = CreatorPrivacyRepository(conn, new_id=new_id, utc_now=utc_now)
        operational_observability = OperationalObservabilityRepository(
            conn, utc_now=utc_now
        )
        factory = SimpleNamespace(
            settings=settings,
            conn=conn,
            domains=SimpleNamespace(
                creator_governance=repository,
                incidents=incidents,
                creator_privacy=creator_privacy,
                operational_observability=operational_observability,
            ),
        )
        try:
            result = dispatch_operations_commands(args, factory, settings)
            return int(result or 0)
        finally:
            conn.close()

    cf = CampaignFactory(settings)
    try:
        authority_claim = claim_cli_authority_event(cf.conn, authority)
        if authority_claim["status"] == "replay":
            return _replayed_exit_code(authority_claim)
        if authority_claim["status"] == "in_progress":
            raise RuntimeError("operator_operation_already_in_progress")
        if authority_claim["status"] == "reconciliation_required":
            raise RuntimeError("operator_operation_reconciliation_required")
        try:
            exit_code = 0
            for dispatch in (
                dispatch_scale_commands,
                dispatch_pipeline_commands,
                dispatch_operations_commands,
            ):
                result = dispatch(args, cf, settings)
                if result is not None:
                    exit_code = int(result)
                    break
        except Exception as exc:
            complete_cli_authority_event(
                cf.conn,
                authority,
                succeeded=False,
                retryable=True,
                error=f"{type(exc).__name__}:{exc}",
            )
            raise
        complete_cli_authority_event(
            cf.conn,
            authority,
            succeeded=True,
            exit_code=exit_code,
        )
        return exit_code
    finally:
        cf.close()


def _complete_cli(
    settings,
    authority,
    *,
    succeeded: bool,
    exit_code: int | None = None,
    retryable: bool = False,
    error: str | None = None,
) -> None:
    cf = CampaignFactory(settings)
    try:
        complete_cli_authority_event(
            cf.conn,
            authority,
            succeeded=succeeded,
            exit_code=exit_code,
            retryable=retryable,
            error=error,
        )
    finally:
        cf.close()


def _replayed_exit_code(claim: dict) -> int:
    outcome = claim.get("outcome")
    if not isinstance(outcome, dict) or not isinstance(outcome.get("exitCode"), int):
        raise RuntimeError("operator_cli_replay_outcome_missing")
    return int(outcome["exitCode"])


if __name__ == "__main__":
    raise SystemExit(main())
