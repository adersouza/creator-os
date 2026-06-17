"""Runtime guard for deprecated local generation paths."""
from __future__ import annotations

import os


DEPRECATED_GENERATOR_ALLOW_FLAG = "REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS"
DEPRECATED_GENERATOR_FLAG = "REEL_FACTORY_RAISE_ON_DEPRECATED_GENERATORS"
PROD_ENV_VARS = ("REEL_FACTORY_ENV", "APP_ENV", "ENV", "NODE_ENV", "VERCEL_ENV")
LOCAL_ENV_VALUES = {"local", "development", "dev", "test"}
PROD_ENV_VALUES = {"prod", "production"}
TRUTHY = {"1", "true", "yes", "on"}


class DeprecatedGeneratorError(RuntimeError):
    """Raised when a deprecated generation path is closed for this runtime."""


def _env_value(name: str) -> str:
    return os.environ.get(name, "").strip().lower()


def _truthy(name: str) -> bool:
    return _env_value(name) in TRUTHY


def _prod_env_active() -> bool:
    return any(_env_value(name) in PROD_ENV_VALUES for name in PROD_ENV_VARS)


def _local_or_test_context() -> bool:
    return _env_value("REEL_FACTORY_ENV") in LOCAL_ENV_VALUES or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def deprecated_generator_allowed() -> bool:
    if _prod_env_active():
        return False
    return _truthy(DEPRECATED_GENERATOR_ALLOW_FLAG) and _local_or_test_context()


def guard_deprecated_generator(feature: str) -> None:
    """Fail closed unless a local/test operator explicitly enables legacy review."""
    if _truthy(DEPRECATED_GENERATOR_FLAG) or not deprecated_generator_allowed():
        raise DeprecatedGeneratorError(
            f"{feature} is deprecated; set {DEPRECATED_GENERATOR_ALLOW_FLAG}=1 with "
            "REEL_FACTORY_ENV=local|development|test only for local migration review"
        )
