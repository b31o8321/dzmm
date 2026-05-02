import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def _make_world(client: AsyncClient) -> int:
    r = await client.post("/worlds", json={"name": "测试世界", "content_md": "内容", "style": "realistic", "rules_mode": "light"})
    assert r.status_code == 200
    return r.json()["id"]


async def test_create_standalone_screenplay(client: AsyncClient):
    wid = await _make_world(client)
    r = await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "迷雾剧本",
        "genre": "悬疑探案",
        "pc_name": "林探",
        "pc_profile_md": "老警探",
        "pc_base_stats_json": "{}",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["world_id"] == wid
    assert data["title"] == "迷雾剧本"
    assert data["session_id"] is None


async def test_list_world_screenplays(client: AsyncClient):
    wid = await _make_world(client)
    await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "剧本A", "genre": "悬疑探案", "pc_name": "A", "pc_profile_md": "", "pc_base_stats_json": "{}"
    })
    await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "剧本B", "genre": "英雄成长", "pc_name": "B", "pc_profile_md": "", "pc_base_stats_json": "{}"
    })
    r = await client.get(f"/worlds/{wid}/screenplays")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    titles = {it["title"] for it in items}
    assert titles == {"剧本A", "剧本B"}


async def test_get_screenplay(client: AsyncClient):
    wid = await _make_world(client)
    create_r = await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "剧本X", "genre": "政治阴谋", "pc_name": "侠客", "pc_profile_md": "背景", "pc_base_stats_json": "{}"
    })
    sp_id = create_r.json()["id"]
    r = await client.get(f"/screenplays/{sp_id}")
    assert r.status_code == 200
    assert r.json()["id"] == sp_id


async def test_delete_screenplay(client: AsyncClient):
    wid = await _make_world(client)
    create_r = await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "剧本Y", "genre": "灾难求生", "pc_name": "幸存者", "pc_profile_md": "", "pc_base_stats_json": "{}"
    })
    sp_id = create_r.json()["id"]
    r = await client.delete(f"/screenplays/{sp_id}")
    assert r.status_code == 204
    r2 = await client.get(f"/screenplays/{sp_id}")
    assert r2.status_code == 404
