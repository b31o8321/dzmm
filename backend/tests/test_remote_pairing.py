import asyncio

import pytest
from datetime import timedelta
from sqlalchemy import func, select

from dzmm.db.base import init_db
from dzmm.db.models import PairedDevice, RemoteServerState
from dzmm.remote.auth import hash_device_token
from dzmm.remote.pairing import PairRequest, PairingWindow, _now
from tests.remote_helpers import app_client


@pytest.mark.asyncio
async def test_phone_request_approve_and_poll(remote_app):
    app, _, _ = remote_app
    async with app_client(app, "192.168.1.30") as remote:
        created = await remote.post(
            "/remote/pair/requests",
            json={"device_id": "android-request-1", "device_name": "Pixel 9"},
        )
    assert created.status_code == 202
    request_id = created.json()["request_id"]
    secret = created.json()["poll_secret"]

    async with app_client(app) as local:
        pending = await local.get("/remote/admin/pair-requests")
        assert pending.json()[0]["device_name"] == "Pixel 9"
        approved = await local.post(f"/remote/admin/pair-requests/{request_id}/approve")
    assert approved.status_code == 200

    async with app_client(app, "192.168.1.30") as remote:
        polled = await remote.get(
            f"/remote/pair/requests/{request_id}",
            params={"wait_seconds": 0},
            headers={"X-DZMM-Pair-Secret": secret},
        )
        wrong_secret = await remote.get(
            f"/remote/pair/requests/{request_id}",
            params={"wait_seconds": 0},
            headers={"X-DZMM-Pair-Secret": "x" * 32},
        )
    assert polled.status_code == 200
    assert polled.json()["status"] == "approved"
    assert polled.json()["device_token"].startswith("dt-")
    assert wrong_secret.status_code == 404


def test_pairing_secret_values_are_redacted_from_repr():
    now = _now()
    request = PairRequest(
        request_id="request-id",
        poll_secret="poll-secret-value",
        device_id="android-redact-1",
        device_name="Phone",
        client_ip="192.168.1.40",
        created_at=now,
        expires_at=now + timedelta(minutes=1),
        device_token="device-token-value",
    )
    window = PairingWindow(value="pairing-window-secret", expires_at=now)

    assert "poll-secret-value" not in repr(request)
    assert "device-token-value" not in repr(request)
    assert "pairing-window-secret" not in repr(window)


@pytest.mark.asyncio
async def test_phone_request_can_be_denied(remote_app):
    app, _, _ = remote_app
    async with app_client(app, "192.168.1.31") as remote:
        created = await remote.post(
            "/remote/pair/requests",
            json={"device_id": "android-request-2", "device_name": "Tablet"},
        )
    request_id = created.json()["request_id"]
    secret = created.json()["poll_secret"]
    async with app_client(app) as local:
        denied = await local.post(f"/remote/admin/pair-requests/{request_id}/deny")
    assert denied.status_code == 200
    async with app_client(app, "192.168.1.31") as remote:
        polled = await remote.get(
            f"/remote/pair/requests/{request_id}",
            params={"wait_seconds": 0},
            headers={"X-DZMM-Pair-Secret": secret},
        )
    assert polled.json()["status"] == "denied"
    assert "device_token" not in polled.json()


@pytest.mark.asyncio
async def test_qr_claim_is_single_use(remote_app):
    app, _, _ = remote_app
    async with app_client(app) as local:
        created = await local.post("/remote/admin/pairing/qr")
    claim = created.json()["claim"]
    body = {"device_id": "android-qr-0001", "device_name": "QR Phone", "claim": claim}
    async with app_client(app, "192.168.1.32") as remote:
        first = await remote.post("/remote/pair/qr-claim", json=body)
    async with app_client(app, "192.168.1.33") as remote:
        replay = await remote.post("/remote/pair/qr-claim", json=body)
    assert first.status_code == 200
    assert first.json()["device_token"].startswith("dt-")
    assert replay.status_code == 410
    assert replay.json()["detail"]["code"] == "claim_invalid"


@pytest.mark.asyncio
async def test_concurrent_qr_claim_has_exactly_one_winner(remote_app):
    app, _, _ = remote_app
    async with app_client(app) as local:
        created = await local.post("/remote/admin/pairing/qr")
    claim = created.json()["claim"]

    async def submit(host: str, device_id: str):
        async with app_client(app, host) as remote:
            return await remote.post(
                "/remote/pair/qr-claim",
                json={
                    "device_id": device_id,
                    "device_name": "QR Phone",
                    "claim": claim,
                },
            )

    results = await asyncio.gather(
        submit("192.168.1.41", "android-qr-race-1"),
        submit("192.168.1.42", "android-qr-race-2"),
    )

    assert sorted(response.status_code for response in results) == [200, 410]
    assert sum("device_token" in response.json() for response in results) == 1
    loser = next(response for response in results if response.status_code == 410)
    assert loser.json()["detail"]["code"] == "claim_invalid"


@pytest.mark.asyncio
async def test_qr_claim_attempts_are_rate_limited_per_ip(remote_app):
    app, _, _ = remote_app
    body = {
        "device_id": "android-qr-rate-1",
        "device_name": "QR Phone",
        "claim": "x" * 32,
    }
    async with app_client(app, "192.168.1.38") as remote:
        first = await remote.post("/remote/pair/qr-claim", json=body)
        second = await remote.post("/remote/pair/qr-claim", json=body)
    assert first.status_code == 410
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_pin_rate_limit_and_success_closes_window(remote_app):
    app, _, _ = remote_app
    async with app_client(app) as local:
        opened = await local.post("/remote/admin/pairing/pin")
    pin = opened.json()["pin"]
    async with app_client(app, "192.168.1.33") as remote:
        for _ in range(5):
            failed = await remote.post(
                "/remote/pair/pin",
                json={
                    "device_id": "android-pin-0001",
                    "device_name": "PIN Phone",
                    "pin": "000000" if pin != "000000" else "999999",
                },
            )
            assert failed.status_code == 401
        limited = await remote.post(
            "/remote/pair/pin",
            json={
                "device_id": "android-pin-0001",
                "device_name": "PIN Phone",
                "pin": pin,
            },
        )
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_concurrent_pin_exchange_has_exactly_one_winner(remote_app):
    app, _, _ = remote_app
    async with app_client(app) as local:
        opened = await local.post("/remote/admin/pairing/pin")
    pin = opened.json()["pin"]

    async def submit(host: str, device_id: str):
        async with app_client(app, host) as remote:
            return await remote.post(
                "/remote/pair/pin",
                json={
                    "device_id": device_id,
                    "device_name": "PIN Phone",
                    "pin": pin,
                },
            )

    results = await asyncio.gather(
        submit("192.168.1.43", "android-pin-race-1"),
        submit("192.168.1.44", "android-pin-race-2"),
    )

    assert sorted(response.status_code for response in results) == [200, 409]
    assert sum("device_token" in response.json() for response in results) == 1
    loser = next(response for response in results if response.status_code == 409)
    assert loser.json()["detail"]["code"] == "pairing_closed"


@pytest.mark.asyncio
async def test_repair_rotates_token_without_plaintext_persistence(remote_app):
    app, session_maker, engine = remote_app

    async def pair_once(host: str) -> str:
        async with app_client(app) as local:
            opened = await local.post("/remote/admin/pairing/pin")
        async with app_client(app, host) as remote:
            paired = await remote.post(
                "/remote/pair/pin",
                json={
                    "device_id": "android-rotate-1",
                    "device_name": "Rotating Phone",
                    "pin": opened.json()["pin"],
                },
            )
        return paired.json()["device_token"]

    first = await pair_once("192.168.1.34")
    second = await pair_once("192.168.1.35")
    assert first != second

    async with session_maker() as session:
        device = (await session.execute(select(PairedDevice))).scalar_one()
        assert device.token_hash == hash_device_token(second)
        assert first not in device.token_hash
        assert second not in device.token_hash
        assert await session.scalar(select(func.count(PairedDevice.id))) == 1
        first_server_id = (await session.get(RemoteServerState, 1)).server_id

    await init_db(engine)
    async with session_maker() as session:
        assert (await session.get(RemoteServerState, 1)).server_id == first_server_id
        assert await session.scalar(select(func.count(PairedDevice.id))) == 1


@pytest.mark.asyncio
async def test_pair_request_is_rate_limited_per_ip(remote_app):
    app, _, _ = remote_app
    body = {"device_id": "android-rate-1", "device_name": "Phone"}
    async with app_client(app, "192.168.1.36") as remote:
        first = await remote.post("/remote/pair/requests", json=body)
        second = await remote.post("/remote/pair/requests", json=body)
    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_expired_pair_requests_release_memory(remote_app):
    app, _, _ = remote_app
    manager = app.state.pairing_manager
    request = await manager.submit_request(
        device_id="android-expiry-1",
        device_name="Old Phone",
        client_ip="192.168.1.37",
    )
    request.expires_at = _now() - manager.REQUEST_RETENTION - timedelta(seconds=1)
    assert await manager.list_pending_requests() == []
    assert request.request_id not in manager._requests
    assert request.request_id not in manager._request_events


@pytest.mark.asyncio
async def test_shutdown_discards_ephemeral_pairing_state(remote_app):
    app, _, _ = remote_app
    manager = app.state.pairing_manager
    request = await manager.submit_request(
        device_id="android-shutdown-1",
        device_name="Phone",
        client_ip="192.168.1.39",
    )
    await manager.open_pin_window()
    await manager.create_qr_claim()

    await manager.shutdown()

    assert request.request_id not in manager._requests
    assert manager._request_events == {}
    assert manager._pin_window is None
    assert manager._qr_claims == {}
