"""routes_sessions package — incrementally split from 1134 lines.
Step 1: wrap _impl.py without splitting; subsequent refactors carve out
modules per route domain."""
import sys as _sys

from dzmm.api.routes_sessions._impl import *  # noqa
from dzmm.api.routes_sessions import _impl as _impl  # noqa

# main.py uses these.
from dzmm.api.routes_sessions._impl import (  # noqa
    router,
    get_session_dep,
    get_session_maker_dep,
)

# Tests use monkeypatch.setattr("dzmm.api.routes_sessions.build_client", ...)
# so this name must be importable on the package level.
from dzmm.api.routes_sessions._impl import build_client  # noqa


# Tests monkeypatch attributes here at the package level (e.g.
# `dzmm.api.routes_sessions.build_client`). Because the actual route handlers
# live in `_impl` and reference their own module-local bindings, we mirror
# every package-level attribute write down to `_impl` so monkeypatching at
# the package boundary still affects the running code. This preserves the
# existing test contract while we incrementally split `_impl.py` apart.
_pkg_module = _sys.modules[__name__]
_pkg_module_setattr = _pkg_module.__class__.__setattr__


def _proxy_setattr(self, name, value):  # type: ignore[no-redef]
    _pkg_module_setattr(self, name, value)
    if not name.startswith("_") and hasattr(_impl, name):
        setattr(_impl, name, value)


_pkg_module.__class__ = type(
    "_RoutesSessionsModule",
    (_pkg_module.__class__,),
    {"__setattr__": _proxy_setattr},
)
