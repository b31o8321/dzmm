"""state_apply package - incrementally split from a single 1091-line file.

For now everything still lives in `_impl.py`; subsequent refactors will
carve handlers out into per-tag modules.
"""

from dzmm.service.state_apply._impl import *  # noqa: F401, F403
from dzmm.service.state_apply import _impl as _impl  # noqa: F401

# Re-export the public entry point. Only `apply_tags` is consumed externally
# (verified via grep across backend/tests and backend/src).
from dzmm.service.state_apply._impl import (  # noqa: E402
    apply_tags,
)
