from __future__ import annotations

from threading import RLock


class OperationRegistry:
    """Coordinates cancellation with the final persistence boundary."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}
        self._lock = RLock()

    def begin(self, request_id: str) -> bool:
        with self._lock:
            if request_id in self._states:
                return False
            self._states[request_id] = "generating"
            return True

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            if self._states.get(request_id) != "generating":
                return False
            self._states[request_id] = "cancelled"
            return True

    def enter_applying(self, request_id: str) -> bool:
        with self._lock:
            state = self._states.get(request_id)
            if state is None:
                return True
            if state == "cancelled":
                return False
            if state != "generating":
                return False
            self._states[request_id] = "applying"
            return True

    def finish(self, request_id: str) -> None:
        with self._lock:
            self._states.pop(request_id, None)
