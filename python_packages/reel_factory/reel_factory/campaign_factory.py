#!/usr/bin/env python3
"""CLI entrypoint for Campaign Factory."""

from .campaign_store import cli_main

if __name__ == "__main__":
    raise SystemExit(cli_main())
