#!/usr/bin/env python3
"""Compatibility entrypoint for the packaged Reel Factory next-batch module."""

from __future__ import annotations

from reel_factory import next_batch as _next_batch

CAMPAIGN_FACTORY_REQUEST_ENV = _next_batch.CAMPAIGN_FACTORY_REQUEST_ENV
CAMPAIGN_FACTORY_TIMEOUT_ENV = _next_batch.CAMPAIGN_FACTORY_TIMEOUT_ENV
_campaign_factory_command = _next_batch._campaign_factory_command
campaign_factory_next_batch = _next_batch.campaign_factory_next_batch
main = _next_batch.main
select_next_batch = _next_batch.select_next_batch


if __name__ == "__main__":
    raise SystemExit(main())
