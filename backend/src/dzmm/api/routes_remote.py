"""LAN pairing and loopback-only remote administration endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from dzmm.remote.pairing import PairingError, PairingManager

router = APIRouter(prefix="/remote", tags=["remote"])


def get_pairing_manager_dep() -> PairingManager:
    raise RuntimeError("pairing manager dependency not configured")


class DeviceIdentity(BaseModel):
    device_id: str = Field(min_length=8, max_length=120)
    device_name: str = Field(min_length=1, max_length=120)


class PinPairRequest(DeviceIdentity):
    pin: str = Field(pattern=r"^\d{6}$")


class QrClaimRequest(DeviceIdentity):
    claim: str = Field(min_length=20, max_length=200)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds") + "Z"


def _raise_pairing_error(exc: PairingError) -> None:
    statuses = {
        "bad_pin": 401,
        "pairing_closed": 409,
        "rate_limited": 429,
        "too_many_pending": 429,
        "request_not_found": 404,
        "request_expired": 409,
        "request_denied": 409,
        "request_approved": 409,
        "claim_invalid": 410,
    }
    raise HTTPException(
        status_code=statuses.get(exc.code, 400),
        detail={"code": exc.code, "message": exc.code.replace("_", " ")},
    ) from exc


@router.post("/pair/requests", status_code=202)
async def create_pair_request(
    body: DeviceIdentity,
    request: Request,
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    try:
        pair_request = await manager.submit_request(
            device_id=body.device_id,
            device_name=body.device_name,
            client_ip=request.client.host if request.client else "unknown",
        )
    except PairingError as exc:
        _raise_pairing_error(exc)
    return {
        "request_id": pair_request.request_id,
        "poll_secret": pair_request.poll_secret,
        "expires_at": _iso(pair_request.expires_at),
        "status": pair_request.status,
    }


@router.get("/pair/requests/{request_id}")
async def poll_pair_request(
    request_id: str,
    pair_secret: str = Header(alias="X-DZMM-Pair-Secret", min_length=20, max_length=200),
    wait_seconds: float = Query(default=25.0, ge=0, le=25),
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    try:
        pair_request = await manager.poll_request(request_id, pair_secret, wait_seconds)
    except PairingError as exc:
        _raise_pairing_error(exc)
    response: dict[str, object] = {
        "status": pair_request.status,
        "expires_at": _iso(pair_request.expires_at),
    }
    if pair_request.status == "approved":
        response.update(
            device_token=pair_request.device_token,
            server_id=pair_request.server_id,
        )
    return response


@router.post("/pair/pin")
async def pair_with_pin(
    body: PinPairRequest,
    request: Request,
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    try:
        device_token, server_id = await manager.redeem_pin(
            pin=body.pin,
            device_id=body.device_id,
            device_name=body.device_name,
            client_ip=request.client.host if request.client else "unknown",
        )
    except PairingError as exc:
        _raise_pairing_error(exc)
    return {"device_token": device_token, "server_id": server_id}


@router.post("/pair/qr-claim")
async def pair_with_qr_claim(
    body: QrClaimRequest,
    request: Request,
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    try:
        device_token, server_id = await manager.claim_qr(
            claim=body.claim,
            device_id=body.device_id,
            device_name=body.device_name,
            client_ip=request.client.host if request.client else "unknown",
        )
    except PairingError as exc:
        _raise_pairing_error(exc)
    return {"device_token": device_token, "server_id": server_id}


@router.get("/admin/status")
async def remote_admin_status(
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    pending = await manager.list_pending_requests()
    devices = await manager.list_devices()
    return {
        "server_id": await manager.server_id(),
        "pairing": await manager.pairing_status(),
        "pending_count": len(pending),
        "device_count": len(devices),
    }


@router.post("/admin/pairing/pin")
async def open_pin_pairing(
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    window = await manager.open_pin_window()
    return {"pin": window.value, "expires_at": _iso(window.expires_at)}


@router.post("/admin/pairing/qr")
async def create_qr_pairing(
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    window = await manager.create_qr_claim()
    return {"claim": window.value, "expires_at": _iso(window.expires_at)}


@router.get("/admin/pair-requests")
async def list_pair_requests(
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    requests = await manager.list_pending_requests()
    return [
        {
            "request_id": item.request_id,
            "device_id": item.device_id,
            "device_name": item.device_name,
            "client_ip": item.client_ip,
            "created_at": _iso(item.created_at),
            "expires_at": _iso(item.expires_at),
        }
        for item in requests
    ]


@router.post("/admin/pair-requests/{request_id}/approve")
async def approve_pair_request(
    request_id: str,
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    try:
        item = await manager.approve_request(request_id)
    except PairingError as exc:
        _raise_pairing_error(exc)
    return {"request_id": item.request_id, "status": item.status}


@router.post("/admin/pair-requests/{request_id}/deny")
async def deny_pair_request(
    request_id: str,
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    try:
        item = await manager.deny_request(request_id)
    except PairingError as exc:
        _raise_pairing_error(exc)
    return {"request_id": item.request_id, "status": item.status}


@router.get("/admin/devices")
async def list_paired_devices(
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    devices = await manager.list_devices()
    return [
        {
            "device_id": device.device_id,
            "name": device.name,
            "paired_at": _iso(device.paired_at),
            "last_seen": _iso(device.last_seen) if device.last_seen else None,
        }
        for device in devices
    ]


@router.delete("/admin/devices/{device_id}", status_code=204)
async def revoke_paired_device(
    device_id: str,
    manager: PairingManager = Depends(get_pairing_manager_dep),
):
    if not await manager.revoke_device(device_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "device_not_found", "message": "device not found"},
        )
