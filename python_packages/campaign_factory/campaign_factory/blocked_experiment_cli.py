from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .blocked_experiment_reporting import (
    blocked_experiment_report,
    record_blocked_experiment_decision,
    rollback_blocked_experiment_policy,
)

BLOCKED_EXPERIMENT_COMMANDS = frozenset(
    {
        "blocked-experiment-report",
        "blocked-experiment-decision",
        "blocked-experiment-rollback",
    }
)


def dispatch_blocked_experiment_command(
    args: Any,
    conn: Any,
    *,
    print_json: Callable[[Any], None],
) -> int | None:
    if args.cmd not in BLOCKED_EXPERIMENT_COMMANDS:
        return None
    if args.cmd == "blocked-experiment-report":
        result = blocked_experiment_report(
            conn,
            experiment_id=args.experiment_id,
            record_interpretation=args.record_interpretation,
        )
    elif args.cmd == "blocked-experiment-decision":
        result = record_blocked_experiment_decision(
            conn,
            experiment_id=args.experiment_id,
            operator=args.operator,
            decision=args.decision,
            reason=args.reason,
        )
    else:
        result = rollback_blocked_experiment_policy(
            conn,
            experiment_id=args.experiment_id,
            operator=args.operator,
            reason=args.reason,
        )
    print_json(result)
    return 0
