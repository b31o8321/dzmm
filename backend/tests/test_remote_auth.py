import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from dzmm.db.models import PairedDevice
from dzmm.remote.auth import (
    RemoteRouteClass,
    classify_remote_route,
    hash_device_token,
    is_loopback_peer,
)
from tests.remote_helpers import app_client


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/health", RemoteRouteClass.HEALTH),
        ("POST", "/remote/pair/requests", RemoteRouteClass.PUBLIC_PAIRING),
        ("GET", "/remote/pair/requests/abc", RemoteRouteClass.PUBLIC_PAIRING),
        ("POST", "/remote/pair/pin", RemoteRouteClass.PUBLIC_PAIRING),
        ("POST", "/remote/pair/qr-claim", RemoteRouteClass.PUBLIC_PAIRING),
        ("GET", "/sessions", RemoteRouteClass.PAIRED_GAMEPLAY),
        ("GET", "/sessions/42/messages", RemoteRouteClass.PAIRED_GAMEPLAY),
        ("POST", "/sessions/42/suggest_actions", RemoteRouteClass.PAIRED_GAMEPLAY),
        ("POST", "/sessions/42/turn-runs", RemoteRouteClass.PAIRED_GAMEPLAY),
        ("GET", "/sessions/42/turn-runs/run-1/events", RemoteRouteClass.PAIRED_GAMEPLAY),
        ("GET", "/model_configs", RemoteRouteClass.LOCAL_ONLY),
        ("POST", "/wizard/fw/finalize", RemoteRouteClass.LOCAL_ONLY),
        ("GET", "/sessions/1/messages/2/debug", RemoteRouteClass.LOCAL_ONLY),
        ("GET", "/remote/admin/status", RemoteRouteClass.LOCAL_ONLY),
    ],
)
def test_remote_route_policy(method, path, expected):
    assert classify_remote_route(method, path) == expected


def test_loopback_peer_ignores_forwarded_header_concepts():
    assert is_loopback_peer("127.0.0.1")
    assert is_loopback_peer("::1")
    assert is_loopback_peer("::ffff:127.0.0.1")
    assert not is_loopback_peer("192.168.1.25")


def test_every_registered_route_has_a_safe_classification(remote_app):
    app, _, _ = remote_app
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        concrete_path = (
            route.path.replace("{session_id}", "1")
            .replace("{request_id}", "request")
            .replace("{device_id}", "device")
            .replace("{msg_id}", "1")
            .replace("{goal_id}", "1")
            .replace("{npc_id}", "1")
            .replace("{feedback_id}", "1")
            .replace("{asset_id}", "1")
            .replace("{screenplay_id}", "1")
            .replace("{world_id}", "1")
            .replace("{character_id}", "1")
            .replace("{id}", "1")
        )
        for method in route.methods or {"GET"}:
            classification = classify_remote_route(method, concrete_path)
            assert classification in RemoteRouteClass


async def _pair_with_pin(app, remote_host="192.168.1.25") -> tuple[str, str]:
    async with app_client(app) as local:
        opened = await local.post("/remote/admin/pairing/pin")
        assert opened.status_code == 200
        pin = opened.json()["pin"]
    async with app_client(app, remote_host) as remote:
        paired = await remote.post(
            "/remote/pair/pin",
            json={
                "device_id": "android-device-0001",
                "device_name": "Norman Pixel",
                "pin": pin,
            },
        )
        assert paired.status_code == 200
        return paired.json()["device_token"], paired.json()["server_id"]


@pytest.mark.asyncio
async def test_remote_health_is_public_and_has_stable_identity(remote_app):
    app, _, _ = remote_app
    async with app_client(app, "192.168.1.25") as remote:
        first = await remote.get("/health")
        second = await remote.get("/health")
    assert first.status_code == 200
    assert first.json()["server_id"] == second.json()["server_id"]
    assert first.json()["api_version"] == 1
    assert first.json()["remote_access"] is True
    assert "pair_pin" in first.json()["capabilities"]


@pytest.mark.asyncio
async def test_concurrent_health_requests_share_one_server_identity(remote_app):
    import asyncio

    app, _, _ = remote_app
    async with app_client(app, "192.168.1.25") as remote:
        responses = await asyncio.gather(*(remote.get("/health") for _ in range(8)))
    assert len({response.json()["server_id"] for response in responses}) == 1


@pytest.mark.asyncio
async def test_remote_access_requires_token_and_ignores_x_forwarded_for(remote_app):
    app, _, _ = remote_app
    async with app_client(app, "192.168.1.25") as remote:
        response = await remote.get(
            "/sessions",
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_loopback_keeps_existing_api_access(remote_app):
    app, _, _ = remote_app
    async with app_client(app) as local:
        response = await local.get("/sessions")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_paired_token_is_hashed_scoped_and_revocable(remote_app):
    app, session_maker, _ = remote_app
    token, _ = await _pair_with_pin(app)

    async with session_maker() as session:
        device = (await session.execute(select(PairedDevice))).scalar_one()
        assert device.token_hash == hash_device_token(token)
        assert token not in device.token_hash

    headers = {"Authorization": f"Bearer {token}"}
    async with app_client(app, "192.168.1.25") as remote:
        sessions = await remote.get("/sessions", headers=headers)
        models = await remote.get("/model_configs", headers=headers)
    assert sessions.status_code == 200
    assert models.status_code == 403
    assert models.json()["code"] == "local_only"

    async with app_client(app) as local:
        revoked = await local.delete("/remote/admin/devices/android-device-0001")
    assert revoked.status_code == 204

    async with app_client(app, "192.168.1.25") as remote:
        after_revoke = await remote.get("/sessions", headers=headers)
    assert after_revoke.status_code == 401
    assert after_revoke.json()["code"] == "revoked"


@pytest.mark.asyncio
async def test_remote_disabled_blocks_pairing_but_not_health(tmp_path):
    from dzmm.db.base import async_session, get_engine, init_db
    from dzmm.main import create_app

    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/disabled.db")
    await init_db(engine)
    app = create_app(
        async_session(engine),
        remote_access_enabled=False,
        start_remote_discovery=False,
    )
    async with app_client(app, "192.168.1.25") as remote:
        health = await remote.get("/health")
        pairing = await remote.post(
            "/remote/pair/requests",
            json={"device_id": "android-device-0001", "device_name": "Pixel"},
        )
    assert health.status_code == 200
    assert health.json()["remote_access"] is False
    assert pairing.status_code == 403
    assert pairing.json()["code"] == "remote_disabled"
    await engine.dispose()


@pytest.mark.asyncio
async def test_cors_allows_tauri_and_rejects_unknown_web_origins(remote_app):
    app, _, _ = remote_app
    preflight_headers = {
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    }
    async with app_client(app) as local:
        allowed = await local.options(
            "/sessions",
            headers={"Origin": "tauri://localhost", **preflight_headers},
        )
        denied = await local.options(
            "/sessions",
            headers={"Origin": "https://evil.example", **preflight_headers},
        )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "tauri://localhost"
    assert denied.status_code == 400
