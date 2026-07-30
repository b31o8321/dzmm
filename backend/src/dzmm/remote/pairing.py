"""In-memory pairing windows backed by persistent hashed device credentials."""

from __future__ import annotations

import asyncio
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dzmm.db.models import PairedDevice, RemoteServerState
from dzmm.remote.auth import hash_device_token


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def ensure_server_state(session: AsyncSession) -> RemoteServerState:
    state = await session.get(RemoteServerState, 1)
    if state is None:
        state = RemoteServerState(id=1, server_id=str(uuid4()))
        session.add(state)
        await session.commit()
    return state


@dataclass
class PairRequest:
    request_id: str
    poll_secret: str = field(repr=False)
    device_id: str
    device_name: str
    client_ip: str
    created_at: datetime
    expires_at: datetime
    status: str = "pending"
    device_token: str | None = field(default=None, repr=False)
    server_id: str | None = None


@dataclass
class PairingWindow:
    value: str = field(repr=False)
    expires_at: datetime


class PairingError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PairingManager:
    REQUEST_TTL = timedelta(seconds=60)
    REQUEST_RETENTION = timedelta(minutes=5)
    REQUEST_IP_COOLDOWN = timedelta(seconds=30)
    PIN_TTL = timedelta(minutes=5)
    QR_TTL = timedelta(minutes=5)
    QR_IP_COOLDOWN = timedelta(seconds=1)
    PIN_COOLDOWN = timedelta(seconds=60)
    MAX_PENDING = 5
    MAX_PIN_FAILURES = 5

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self.session_maker = session_maker
        self._lock = asyncio.Lock()
        self._requests: dict[str, PairRequest] = {}
        self._request_events: dict[str, asyncio.Event] = {}
        self._last_request_by_ip: dict[str, datetime] = {}
        self._pin_window: PairingWindow | None = None
        self._qr_claims: dict[str, datetime] = {}
        self._last_qr_attempt_by_ip: dict[str, datetime] = {}
        self._pin_failures: dict[str, tuple[int, datetime | None]] = {}
        self._server_id_cache: str | None = None

    def _cleanup(self, now: datetime) -> None:
        remove_request_ids: list[str] = []
        for request in self._requests.values():
            if request.status == "pending" and request.expires_at <= now:
                request.status = "expired"
                event = self._request_events.get(request.request_id)
                if event is not None:
                    event.set()
            if request.status != "pending" and request.expires_at + self.REQUEST_RETENTION <= now:
                remove_request_ids.append(request.request_id)
        for request_id in remove_request_ids:
            self._requests.pop(request_id, None)
            self._request_events.pop(request_id, None)
        self._last_request_by_ip = {
            client_ip: timestamp
            for client_ip, timestamp in self._last_request_by_ip.items()
            if now - timestamp < self.REQUEST_IP_COOLDOWN
        }
        self._qr_claims = {
            claim: expiry for claim, expiry in self._qr_claims.items() if expiry > now
        }
        self._last_qr_attempt_by_ip = {
            client_ip: timestamp
            for client_ip, timestamp in self._last_qr_attempt_by_ip.items()
            if now - timestamp < self.QR_IP_COOLDOWN
        }
        if self._pin_window is not None and self._pin_window.expires_at <= now:
            self._pin_window = None

    async def server_id(self) -> str:
        if self._server_id_cache is not None:
            return self._server_id_cache
        async with self._lock:
            if self._server_id_cache is None:
                async with self.session_maker() as session:
                    self._server_id_cache = (await ensure_server_state(session)).server_id
            return self._server_id_cache

    async def submit_request(
        self,
        *,
        device_id: str,
        device_name: str,
        client_ip: str,
    ) -> PairRequest:
        now = _now()
        async with self._lock:
            self._cleanup(now)
            last_request = self._last_request_by_ip.get(client_ip)
            if last_request is not None and now - last_request < self.REQUEST_IP_COOLDOWN:
                raise PairingError("rate_limited")
            pending = sum(request.status == "pending" for request in self._requests.values())
            if pending >= self.MAX_PENDING:
                raise PairingError("too_many_pending")
            request = PairRequest(
                request_id=secrets.token_urlsafe(18),
                poll_secret=secrets.token_urlsafe(32),
                device_id=device_id,
                device_name=device_name,
                client_ip=client_ip,
                created_at=now,
                expires_at=now + self.REQUEST_TTL,
            )
            self._requests[request.request_id] = request
            self._request_events[request.request_id] = asyncio.Event()
            self._last_request_by_ip[client_ip] = now
            return request

    async def poll_request(
        self,
        request_id: str,
        poll_secret: str,
        wait_seconds: float,
    ) -> PairRequest:
        async with self._lock:
            self._cleanup(_now())
            request = self._requests.get(request_id)
            if request is None or not hmac.compare_digest(request.poll_secret, poll_secret):
                raise PairingError("request_not_found")
            event = self._request_events[request_id]
            should_wait = request.status == "pending" and wait_seconds > 0
        if should_wait:
            try:
                await asyncio.wait_for(event.wait(), timeout=min(wait_seconds, 25.0))
            except TimeoutError:
                pass
        async with self._lock:
            self._cleanup(_now())
            return self._requests[request_id]

    async def list_pending_requests(self) -> list[PairRequest]:
        async with self._lock:
            self._cleanup(_now())
            return [request for request in self._requests.values() if request.status == "pending"]

    async def approve_request(self, request_id: str) -> PairRequest:
        async with self._lock:
            self._cleanup(_now())
            request = self._requests.get(request_id)
            if request is None:
                raise PairingError("request_not_found")
            if request.status != "pending":
                raise PairingError(f"request_{request.status}")
            token, server_id = await self._issue_device_token(
                request.device_id, request.device_name
            )
            request.device_token = token
            request.server_id = server_id
            request.status = "approved"
            self._request_events[request_id].set()
            return request

    async def deny_request(self, request_id: str) -> PairRequest:
        async with self._lock:
            self._cleanup(_now())
            request = self._requests.get(request_id)
            if request is None:
                raise PairingError("request_not_found")
            if request.status != "pending":
                raise PairingError(f"request_{request.status}")
            request.status = "denied"
            self._request_events[request_id].set()
            return request

    async def open_pin_window(self) -> PairingWindow:
        async with self._lock:
            value = f"{secrets.randbelow(1_000_000):06d}"
            self._pin_window = PairingWindow(value=value, expires_at=_now() + self.PIN_TTL)
            return self._pin_window

    async def redeem_pin(
        self,
        *,
        pin: str,
        device_id: str,
        device_name: str,
        client_ip: str,
    ) -> tuple[str, str]:
        now = _now()
        async with self._lock:
            self._cleanup(now)
            failures, cooldown_until = self._pin_failures.get(client_ip, (0, None))
            if cooldown_until is not None and cooldown_until > now:
                raise PairingError("rate_limited")
            if self._pin_window is None:
                raise PairingError("pairing_closed")
            if not hmac.compare_digest(self._pin_window.value, pin):
                failures += 1
                if failures >= self.MAX_PIN_FAILURES:
                    self._pin_failures[client_ip] = (0, now + self.PIN_COOLDOWN)
                else:
                    self._pin_failures[client_ip] = (failures, None)
                raise PairingError("bad_pin")
            self._pin_window = None
            self._pin_failures.pop(client_ip, None)
            return await self._issue_device_token(device_id, device_name)

    async def create_qr_claim(self) -> PairingWindow:
        async with self._lock:
            claim = secrets.token_urlsafe(32)
            expiry = _now() + self.QR_TTL
            self._qr_claims[claim] = expiry
            return PairingWindow(value=claim, expires_at=expiry)

    async def claim_qr(
        self,
        *,
        claim: str,
        device_id: str,
        device_name: str,
        client_ip: str,
    ) -> tuple[str, str]:
        async with self._lock:
            now = _now()
            self._cleanup(now)
            last_attempt = self._last_qr_attempt_by_ip.get(client_ip)
            if last_attempt is not None and now - last_attempt < self.QR_IP_COOLDOWN:
                raise PairingError("rate_limited")
            self._last_qr_attempt_by_ip[client_ip] = now
            expiry = self._qr_claims.pop(claim, None)
            if expiry is None:
                raise PairingError("claim_invalid")
            return await self._issue_device_token(device_id, device_name)

    async def shutdown(self) -> None:
        """Wake outstanding polls and discard all ephemeral pairing secrets."""

        async with self._lock:
            for event in self._request_events.values():
                event.set()
            self._requests.clear()
            self._request_events.clear()
            self._last_request_by_ip.clear()
            self._pin_window = None
            self._qr_claims.clear()
            self._last_qr_attempt_by_ip.clear()
            self._pin_failures.clear()

    async def pairing_status(self) -> dict[str, bool]:
        async with self._lock:
            self._cleanup(_now())
            return {
                "pin_open": self._pin_window is not None,
                "qr_open": bool(self._qr_claims),
                "request_open": True,
            }

    async def list_devices(self) -> list[PairedDevice]:
        async with self.session_maker() as session:
            return list(
                (
                    await session.execute(
                        select(PairedDevice)
                        .where(PairedDevice.revoked_at.is_(None))
                        .order_by(PairedDevice.paired_at.desc())
                    )
                ).scalars()
            )

    async def revoke_device(self, device_id: str) -> bool:
        async with self.session_maker() as session:
            device = (
                await session.execute(
                    select(PairedDevice).where(
                        PairedDevice.device_id == device_id,
                        PairedDevice.revoked_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if device is None:
                return False
            device.revoked_at = _now()
            await session.commit()
            return True

    async def _issue_device_token(self, device_id: str, device_name: str) -> tuple[str, str]:
        token = "dt-" + secrets.token_hex(32)
        token_hash = hash_device_token(token)
        now = _now()
        async with self.session_maker() as session:
            state = await ensure_server_state(session)
            device = (
                await session.execute(
                    select(PairedDevice).where(PairedDevice.device_id == device_id)
                )
            ).scalar_one_or_none()
            if device is None:
                device = PairedDevice(
                    device_id=device_id,
                    name=device_name,
                    token_hash=token_hash,
                    paired_at=now,
                )
                session.add(device)
            else:
                device.name = device_name
                device.token_hash = token_hash
                device.paired_at = now
                device.last_seen = None
                device.revoked_at = None
            await session.commit()
            self._server_id_cache = state.server_id
            return token, state.server_id
