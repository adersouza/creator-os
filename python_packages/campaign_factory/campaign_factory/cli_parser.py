from __future__ import annotations

import argparse

from .cli_parser_core import register_core_commands
from .cli_parser_operations import register_operations_commands


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="campaign-factory")
    sub = parser.add_subparsers(dest="cmd", required=True)
    register_core_commands(sub)
    register_operations_commands(sub)
    return parser
