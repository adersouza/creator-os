"""Compatibility shim for the experimental Grok A/B prompt workflow."""

from __future__ import annotations

import sys

from experiments import grok_ab_experiment as _impl


if __name__ == "__main__":
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
