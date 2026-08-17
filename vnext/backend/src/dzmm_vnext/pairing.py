from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .persistence import mobile_devices, pairing_requests

GAMEPLAY_CAPABILITY = "gameplay"
PAIRING_TTL = timedelta(minutes=10)


class PairingRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_name: str = Field(min_length=1, max_length=120)


class PairingRequestCreated(BaseModel):
    request_id: str
    device_id: str
    approval_code: str
    expires_at: datetime


class PendingPairing(BaseModel):
    request_id: str
    device_id: str
    device_name: str
    expires_at: datetime


class PairingCompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_code: str = Field(min_length=12, max_length=128)


class MobileCredential(BaseModel):
    device_id: str
    access_token: str
    capabilities: list[str]


class MobileDevice(BaseModel):
    id: str
    name: str
    status: str
    capabilities: list[str]


class PairingError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class PairingService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def request(self, payload: PairingRequestInput) -> PairingRequestCreated:
        now = _now()
        request_id, device_id = str(uuid4()), str(uuid4())
        approval_code = token_urlsafe(18)
        expires_at = now + PAIRING_TTL
        async with self._session_factory() as session, session.begin():
            await session.execute(
                insert(mobile_devices).values(
                    id=device_id,
                    name=payload.device_name,
                    status="pending",
                    token_hash=None,
                    capabilities=[GAMEPLAY_CAPABILITY],
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.execute(
                insert(pairing_requests).values(
                    id=request_id,
                    device_id=device_id,
                    code_hash=_digest(approval_code),
                    status="pending",
                    expires_at=expires_at,
                    created_at=now,
                )
            )
        return PairingRequestCreated(
            request_id=request_id,
            device_id=device_id,
            approval_code=approval_code,
            expires_at=expires_at,
        )

    async def pending(self) -> list[PendingPairing]:
        now = _now()
        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(pairing_requests).where(
                    pairing_requests.c.status == "pending", pairing_requests.c.expires_at <= now
                )
            )
            result = await session.execute(
                select(pairing_requests, mobile_devices.c.name.label("device_name"))
                .join(mobile_devices, mobile_devices.c.id == pairing_requests.c.device_id)
                .where(pairing_requests.c.status == "pending")
                .order_by(pairing_requests.c.created_at)
            )
            rows = result.mappings().all()
        return [
            PendingPairing(
                request_id=row["id"],
                device_id=row["device_id"],
                device_name=row["device_name"],
                expires_at=row["expires_at"],
            )
            for row in rows
        ]

    async def active(self) -> list[MobileDevice]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(mobile_devices)
                .where(mobile_devices.c.status == "active")
                .order_by(mobile_devices.c.created_at)
            )
            rows = result.mappings().all()
        return [
            MobileDevice(
                id=row["id"],
                name=row["name"],
                status=row["status"],
                capabilities=row["capabilities"],
            )
            for row in rows
        ]

    async def approve(self, request_id: str) -> None:
        now = _now()
        async with self._session_factory() as session, session.begin():
            changed = await session.execute(
                update(pairing_requests)
                .where(
                    pairing_requests.c.id == request_id,
                    pairing_requests.c.status == "pending",
                    pairing_requests.c.expires_at > now,
                )
                .values(status="approved")
            )
            if changed.rowcount != 1:
                raise PairingError("pairing request is unavailable or expired")

    async def complete(self, request_id: str, payload: PairingCompletionInput) -> MobileCredential:
        now = _now()
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                select(pairing_requests, mobile_devices.c.capabilities)
                .join(mobile_devices, mobile_devices.c.id == pairing_requests.c.device_id)
                .where(pairing_requests.c.id == request_id)
            )
            row = result.mappings().one_or_none()
            if (
                row is None
                or row["status"] != "approved"
                or row["expires_at"] <= now
                or not hmac.compare_digest(row["code_hash"], _digest(payload.approval_code))
            ):
                raise PairingError("pairing approval is unavailable, expired, or invalid")
            token = token_urlsafe(32)
            await session.execute(
                update(mobile_devices)
                .where(mobile_devices.c.id == row["device_id"])
                .values(status="active", token_hash=_digest(token), updated_at=now)
            )
            await session.execute(delete(pairing_requests).where(pairing_requests.c.id == request_id))
        return MobileCredential(
            device_id=row["device_id"], access_token=token, capabilities=row["capabilities"]
        )

    async def authenticate(self, token: str) -> MobileDevice:
        async with self._session_factory() as session:
            result = await session.execute(
                select(mobile_devices).where(
                    mobile_devices.c.token_hash == _digest(token),
                    mobile_devices.c.status == "active",
                )
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise PairingError("mobile credential is invalid or revoked")
        return MobileDevice(
            id=row["id"], name=row["name"], status=row["status"], capabilities=row["capabilities"]
        )

    async def revoke(self, device_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            changed = await session.execute(
                update(mobile_devices)
                .where(mobile_devices.c.id == device_id, mobile_devices.c.status == "active")
                .values(status="revoked", token_hash=None, updated_at=_now())
            )
            if changed.rowcount != 1:
                raise PairingError("active mobile device not found")
