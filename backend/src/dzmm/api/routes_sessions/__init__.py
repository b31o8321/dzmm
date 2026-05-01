"""routes_sessions package — endpoints split per domain.

Each sub-module owns its own `router = APIRouter()` (no prefix); we mount
them all under the package-level `/sessions` prefix here so main.py only
includes one router.

Tests monkeypatch `dzmm.api.routes_sessions.build_client`; the actual
captured reference lives in the `turn` sub-module (the only consumer).
We install a __setattr__ proxy so `monkeypatch.setattr` writes at the
package level get mirrored down to every sub-module that captured the
name. Any future sub-module that imports `build_client` from `_common`
will be picked up automatically by the proxy."""
import sys as _sys

from fastapi import APIRouter

from dzmm.api.routes_sessions._common import (  # noqa: F401 — public re-exports
    build_client,
    get_session_dep,
    get_session_maker_dep,
)
from dzmm.api.routes_sessions._common import (  # noqa: F401 — backward compat
    _npc_to_dict,
    _parse_events_json,
    _to_out,
)
from dzmm.api.routes_sessions.base import router as _base_router
from dzmm.api.routes_sessions.locations import router as _locations_router
from dzmm.api.routes_sessions.export import router as _export_router
from dzmm.api.routes_sessions.feedback import router as _feedback_router
from dzmm.api.routes_sessions.goals import router as _goals_router
from dzmm.api.routes_sessions.hidden_events import router as _hidden_events_router
from dzmm.api.routes_sessions.messages import router as _messages_router
from dzmm.api.routes_sessions.npcs import router as _npcs_router
from dzmm.api.routes_sessions.spinoff import router as _spinoff_router
from dzmm.api.routes_sessions.threads import router as _threads_router
from dzmm.api.routes_sessions.turn import router as _turn_router

router = APIRouter()
for _sub in (
    _base_router,
    _messages_router,
    _turn_router,
    _threads_router,
    _npcs_router,
    _goals_router,
    _hidden_events_router,
    _feedback_router,
    _export_router,
    _locations_router,
    _spinoff_router,
):
    router.include_router(_sub)


# Tests monkeypatch attributes here at the package level (e.g.
# `dzmm.api.routes_sessions.build_client`). The actual route handlers
# capture their own module-local bindings, so we mirror every public
# attribute write down to every sub-module that already binds the same
# name. This keeps the long-standing test contract working through the
# multi-file split.
_pkg_module = _sys.modules[__name__]
_pkg_module_setattr = _pkg_module.__class__.__setattr__

# All sub-modules that may capture monkeypatched names. Add new ones here
# if a future endpoint module imports a patchable symbol from `_common`.
_SUBMODULES = (
    "dzmm.api.routes_sessions._common",
    "dzmm.api.routes_sessions.base",
    "dzmm.api.routes_sessions.export",
    "dzmm.api.routes_sessions.feedback",
    "dzmm.api.routes_sessions.goals",
    "dzmm.api.routes_sessions.hidden_events",
    "dzmm.api.routes_sessions.messages",
    "dzmm.api.routes_sessions.npcs",
    "dzmm.api.routes_sessions.spinoff",
    "dzmm.api.routes_sessions.threads",
    "dzmm.api.routes_sessions.turn",
    "dzmm.api.routes_sessions.locations",
)


def _proxy_setattr(self, name, value):  # type: ignore[no-redef]
    _pkg_module_setattr(self, name, value)
    if name.startswith("_"):
        return
    for _mod_name in _SUBMODULES:
        _mod = _sys.modules.get(_mod_name)
        if _mod is not None and hasattr(_mod, name):
            setattr(_mod, name, value)


_pkg_module.__class__ = type(
    "_RoutesSessionsModule",
    (_pkg_module.__class__,),
    {"__setattr__": _proxy_setattr},
)
