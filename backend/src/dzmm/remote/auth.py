"""Remote request classification and device-token authentication.

The middleware is implemented as plain ASGI middleware so existing streaming
SSE responses are not buffered or cancelled by BaseHTTPMiddleware.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from re import Pattern, compile as compile_pattern

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from dzmm.db.models import PairedDevice


class RemoteRouteClass(StrEnum):
    HEALTH = "health"
    PUBLIC_PAIRING = "public_pairing"
    PAIRED_GAMEPLAY = "paired_gameplay"
    LOCAL_ONLY = "local_only"


_PUBLIC_PAIRING: tuple[tuple[str, Pattern[str]], ...] = (
    ("POST", compile_pattern(r"^/remote/pair/requests$")),
    ("GET", compile_pattern(r"^/remote/pair/requests/[^/]+$")),
    ("POST", compile_pattern(r"^/remote/pair/pin$")),
    ("POST", compile_pattern(r"^/remote/pair/qr-claim$")),
)

_PAIRED_GAMEPLAY: tuple[tuple[str, Pattern[str]], ...] = (
    ("GET", compile_pattern(r"^/sessions$")),
    ("GET", compile_pattern(r"^/sessions/\d+$")),
    ("GET", compile_pattern(r"^/sessions/\d+/(messages|state|locations|npcs|goals)$")),
    ("POST", compile_pattern(r"^/sessions/\d+/suggest_actions$")),
    ("POST", compile_pattern(r"^/sessions/\d+/turn-runs$")),
    ("GET", compile_pattern(r"^/sessions/\d+/turn-runs/[^/]+$")),
    ("GET", compile_pattern(r"^/sessions/\d+/turn-runs/[^/]+/events$")),
)


def classify_remote_route(method: str, path: str) -> RemoteRouteClass:
    """Return the remote capability class for one concrete HTTP request.

    The safe default is LOCAL_ONLY. New FastAPI routes therefore cannot become
    remotely reachable merely because somebody forgot to update this module.
    """

    normalized_method = method.upper()
    if normalized_method == "GET" and path == "/health":
        return RemoteRouteClass.HEALTH
    for expected_method, pattern in _PUBLIC_PAIRING:
        if normalized_method == expected_method and pattern.fullmatch(path):
            return RemoteRouteClass.PUBLIC_PAIRING
    for expected_method, pattern in _PAIRED_GAMEPLAY:
        if normalized_method == expected_method and pattern.fullmatch(path):
            return RemoteRouteClass.PAIRED_GAMEPLAY
    return RemoteRouteClass.LOCAL_ONLY


def is_loopback_peer(host: str | None) -> bool:
    if host is None:
        return False
    normalized = host.split("%", 1)[0].lower()
    if normalized == "localhost":
        return True
    try:
        address = ipaddress.ip_address(normalized)
        return address.is_loopback or (
            isinstance(address, ipaddress.IPv6Address)
            and address.ipv4_mapped is not None
            and address.ipv4_mapped.is_loopback
        )
    except ValueError:
        return False


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bearer_token(headers: Headers) -> str | None:
    value = headers.get("authorization", "")
    scheme, separator, token = value.partition(" ")
    if separator and scheme.lower() == "bearer" and token:
        return token.strip()
    return None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message},
    )


class RemoteAccessMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        session_maker: async_sessionmaker[AsyncSession],
        remote_access_enabled: bool,
    ) -> None:
        self.app = app
        self.session_maker = session_maker
        self.remote_access_enabled = remote_access_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        peer = scope.get("client")
        peer_host = peer[0] if peer else None
        if is_loopback_peer(peer_host):
            await self.app(scope, receive, send)
            return

        route_class = classify_remote_route(scope["method"], scope["path"])
        if route_class == RemoteRouteClass.HEALTH:
            await self.app(scope, receive, send)
            return
        if not self.remote_access_enabled:
            await _error(403, "remote_disabled", "Remote access is disabled")(
                scope, receive, send
            )
            return
        if route_class == RemoteRouteClass.PUBLIC_PAIRING:
            await self.app(scope, receive, send)
            return
        if route_class == RemoteRouteClass.LOCAL_ONLY:
            await _error(403, "local_only", "This endpoint is available only on the host")(
                scope, receive, send
            )
            return

        token = _bearer_token(Headers(scope=scope))
        if token is None:
            await _error(401, "unauthorized", "A paired-device token is required")(
                scope, receive, send
            )
            return

        token_hash = hash_device_token(token)
        async with self.session_maker() as session:
            device = (
                await session.execute(
                    select(PairedDevice).where(
                        PairedDevice.token_hash == token_hash,
                        PairedDevice.revoked_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if device is None or not hmac.compare_digest(device.token_hash, token_hash):
                await _error(401, "revoked", "The device token is invalid or revoked")(
                    scope, receive, send
                )
                return
            now = datetime.now(UTC).replace(tzinfo=None)
            if device.last_seen is None or now - device.last_seen >= timedelta(minutes=1):
                device.last_seen = now
                await session.commit()
            scope.setdefault("state", {})["remote_device_id"] = device.device_id

        await self.app(scope, receive, send)
