from __future__ import annotations

import uvicorn

from .cli_dispatch_operations import dispatch_operations_commands
from .cli_dispatch_pipeline import dispatch_pipeline_commands
from .cli_dispatch_scale import dispatch_scale_commands
from .cli_parser import build_cli_parser
from .config import get_settings
from .core import CampaignFactory


def main() -> int:
    parser = build_cli_parser()
    args = parser.parse_args()
    settings = get_settings()

    if args.cmd == "serve":
        uvicorn.run(
            "campaign_factory.app:app", host=args.host, port=args.port, reload=False
        )
        return 0

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
