"""Compatibility shim for the packaged Reel Factory model-fetch module."""

from __future__ import annotations

from reel_factory import fetch_models as _module

__all__ = []
for _name in dir(_module):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_module, _name)
        __all__.append(_name)


if __name__ == "__main__":
    raise SystemExit(_module.main())
