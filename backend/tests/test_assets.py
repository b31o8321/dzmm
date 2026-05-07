"""Tests for /assets API."""
import pytest
from httpx import ASGITransport, AsyncClient

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.main import create_app
import dzmm.service.assets as _assets_svc


@pytest.fixture
async def http(tmp_path):
    """Like the shared `http` fixture but also calls init_paths for upload support."""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    session_maker = async_session(engine)
    app = create_app(session_maker)

    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    _assets_svc.init_paths(tmp_path, builtin_dir)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_assets_list_empty(http):
    r = await http.get("/assets")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_assets_upload_then_list(http):
    files = {"file": ("test.jpg", b"\xff\xd8\xff\xe0fake jpeg bytes", "image/jpeg")}
    r = await http.post(
        "/assets/upload",
        files=files,
        data={"kind": "image", "category": "npc_avatar", "title": "Test Avatar"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["kind"] == "image"
    assert data["mime"] == "image/jpeg"
    assert data["tag"] == {"category": "npc_avatar"}
    asset_id = data["id"]

    r2 = await http.get("/assets", params={"kind": "image", "category": "npc_avatar"})
    assert r2.status_code == 200
    assert any(a["id"] == asset_id for a in r2.json())


async def test_assets_upload_rejects_bad_mime(http):
    files = {"file": ("evil.exe", b"MZ\x00\x00", "application/x-msdownload")}
    r = await http.post("/assets/upload", files=files, data={"kind": "image"})
    assert r.status_code == 415


async def test_assets_attach_and_query_by_owner(http):
    files = {"file": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")}
    r = await http.post("/assets/upload", files=files, data={"kind": "image", "category": "scene"})
    assert r.status_code == 200
    asset_id = r.json()["id"]

    r2 = await http.post(
        f"/assets/{asset_id}/attach",
        json={"owner_type": "world", "owner_id": 999, "slot": "cover"},
    )
    assert r2.status_code == 200

    r3 = await http.get("/assets/by_owner/world/999")
    assert r3.status_code == 200
    items = r3.json()
    assert any(it["asset"]["id"] == asset_id and it["slot"] == "cover" for it in items)


async def test_assets_delete_cascades_links(http):
    files = {"file": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")}
    r = await http.post("/assets/upload", files=files, data={"kind": "image"})
    asset_id = r.json()["id"]
    await http.post(
        f"/assets/{asset_id}/attach",
        json={"owner_type": "world", "owner_id": 999, "slot": "cover"},
    )

    r2 = await http.delete(f"/assets/{asset_id}")
    assert r2.status_code == 204

    r3 = await http.get("/assets/by_owner/world/999")
    assert all(it["asset"]["id"] != asset_id for it in r3.json())
