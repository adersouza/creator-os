"""Compatibility shim for the packaged Reel Factory posting_ledger module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import posting_ledger as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.posting_ledger", run_name="__main__")
else:
    sys.modules[__name__] = _module
