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


def main() -> int:
    parser = build_cli_parser()
    args = parser.parse_args()
    settings = get_settings()

    if args.cmd == "serve":
        uvicorn.run(
            "campaign_factory.app:app", host=args.host, port=args.port, reload=False
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

    governance_commands = {
        "creator-governance-status",
        "creator-governance-transition",
        "creator-governance-rename",
        "creator-identity-enroll",
        "creator-authorization-grant",
        "creator-authorization-revoke",
        "campaign-governance-status",
        "campaign-governance-transition",
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
        factory = SimpleNamespace(
            settings=settings,
            conn=conn,
            domains=SimpleNamespace(creator_governance=repository),
        )
        try:
            result = dispatch_operations_commands(args, factory, settings)
            return int(result or 0)
        finally:
            conn.close()

    cf = CampaignFactory(settings)
    try:
        for dispatch in (
            dispatch_scale_commands,
            dispatch_pipeline_commands,
            dispatch_operations_commands,
        ):
            result = dispatch(args, cf, settings)
            if result is not None:
                return result
    finally:
        cf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
