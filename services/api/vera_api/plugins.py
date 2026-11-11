"""Feature plug-in seams: the module list, routers and reset tables.

A feature ticket appends ONE line to FEATURES (its module name). Everything else it registers
from its own module at import time.
"""

from importlib import import_module

from fastapi import APIRouter

# One line per feature module, imported in order by load_features().
FEATURES: list[str] = [
    "vera_api.adapters",
    "vera_api.comms",
    "vera_api.identity",
    "vera_api.callbacks",
    "vera_api.automations",
]

ROUTERS: list[tuple[APIRouter, bool]] = []  # (router, synthetic_only)
RESET_TABLES: list[str] = []
_loaded = False


def register_router(router: APIRouter, synthetic_only: bool = False) -> None:
    """create_app mounts the router; synthetic_only routers only in the synthetic environment."""
    if all(router is not r for r, _ in ROUTERS):
        ROUTERS.append((router, synthetic_only))


def register_reset_tables(tables: list[str]) -> None:
    """Tables truncated by the demo reset (POST /api/demo/reset)."""
    for table in tables:
        if not table.replace("_", "").isalnum():
            raise ValueError(f"bad table name '{table}'")
        if table not in RESET_TABLES:
            RESET_TABLES.append(table)


def load_features() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for name in FEATURES:
        import_module(name)
