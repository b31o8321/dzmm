import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character,
    CharState,
    Message,
    ModelConfig,
    Session as GameSession,
    TurnRun,
    World,
)
from dzmm.main import create_app
from dzmm.remote.turn_runs import (
    EventGapError,
    RunEventHub,
    TurnRunManager,
    create_or_get_turn_run,
    finish_turn_run,
    mark_stale_turn_runs_interrupted,
    turn_run_payload,
)
from dzmm.service.session_turn_coordinator import (
    SessionBusyError,
    SessionTurnCoordinator,
)
from tests.test_api import StubGM


@pytest.fixture
async def turn_run_db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/turn-runs.db")
    await init_db(engine)
    session_maker = async_session(engine)
    async with session_maker() as session:
        world = World(name="W", content_md="world", style="dark")
        character = Character(
            world=world,
            name="P",
            profile_md="player",
            base_stats_json="{}",
        )
        model = ModelConfig(
            name="M",
            type="ollama",
            base_url="http://localhost:11434",
            model_name="test",
        )
        session.add_all([world, character, model])
        await session.flush()
        game = GameSession(
            name="S",
            world_id=world.id,
            character_id=character.id,
            gm_model_config_id=model.id,
            summarizer_model_config_id=model.id,
        )
        session.add(game)
        await session.flush()
        session.add(CharState(session_id=game.id))
        await session.commit()
        session_id = game.id
    yield session_maker, session_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_request_returns_same_turn_run(turn_run_db):
    session_maker, session_id = turn_run_db
    async with session_maker() as session:
        first, created = await create_or_get_turn_run(
            session,
            session_id=session_id,
            request_id="request-1",
            action="打开门",
            run_id="run-1",
        )
    async with session_maker() as session:
        repeated, repeated_created = await create_or_get_turn_run(
            session,
            session_id=session_id,
            request_id="request-1",
            action="这次文本不会覆盖第一次",
            run_id="run-2",
        )

    assert created is True
    assert repeated_created is False
    assert repeated.id == first.id == "run-1"
    assert repeated.action == "打开门"


@pytest.mark.asyncio
async def test_turn_run_completion_records_assistant_message(turn_run_db):
    session_maker, session_id = turn_run_db
    async with session_maker() as session:
        run, _ = await create_or_get_turn_run(
            session,
            session_id=session_id,
            request_id="request-2",
            action="倾听",
        )
        run_id = run.id
    async with session_maker() as session:
        completed = await finish_turn_run(
            session,
            run_id,
            status="completed",
            assistant_message_id=123,
        )

    payload = turn_run_payload(completed)
    assert payload["status"] == "completed"
    assert payload["assistant_message_id"] == 123
    assert payload["completed_at"] is not None


@pytest.mark.asyncio
async def test_backend_startup_interrupts_stale_running_records(turn_run_db):
    session_maker, session_id = turn_run_db
    async with session_maker() as session:
        session.add(
            TurnRun(
                id="stale-run",
                session_id=session_id,
                request_id="request-stale",
                action="未完成动作",
                status="running",
            )
        )
        session.add(
            TurnRun(
                id="completed-run",
                session_id=session_id,
                request_id="request-completed",
                action="已完成动作",
                status="completed",
            )
        )
        await session.commit()

    assert await mark_stale_turn_runs_interrupted(session_maker) == 1

    async with session_maker() as session:
        stale = await session.get(TurnRun, "stale-run")
        completed = await session.get(TurnRun, "completed-run")
    assert stale.status == "interrupted"
    assert stale.error_code == "run_interrupted"
    assert completed.status == "completed"


@pytest.mark.asyncio
async def test_event_hub_replays_multiple_reconnects_with_monotonic_ids():
    hub = RunEventHub(buffer_size=8)
    await hub.publish("narrative", '{"text":"A"}')
    await hub.publish("tag", '{"name":"dice"}')
    await hub.publish("done", '{"assistant_msg_id":3}')
    await hub.close()

    first = await hub.subscribe(0)
    all_events = [event async for event in first]
    second = await hub.subscribe(1)
    after_first = [event async for event in second]
    third = await hub.subscribe(2)
    after_second = [event async for event in third]

    assert [event["id"] for event in all_events] == ["1", "2", "3"]
    assert [event["id"] for event in after_first] == ["2", "3"]
    assert [event["id"] for event in after_second] == ["3"]


@pytest.mark.asyncio
async def test_event_hub_reports_gap_after_bounded_buffer_rollover():
    hub = RunEventHub(buffer_size=2)
    for index in range(4):
        await hub.publish("narrative", f'{{"text":"{index}"}}')

    with pytest.raises(EventGapError) as raised:
        await hub.subscribe(0)

    assert raised.value.earliest_id == 3
    assert raised.value.latest_id == 4


@pytest.mark.asyncio
async def test_consumer_disconnect_does_not_cancel_producer(turn_run_db):
    session_maker, session_id = turn_run_db
    coordinator = SessionTurnCoordinator()
    manager = TurnRunManager(session_maker, coordinator)
    continue_producing = asyncio.Event()

    async def producer():
        yield {"event": "narrative", "data": '{"text":"first"}'}
        await continue_producing.wait()
        yield {"event": "done", "data": '{"assistant_msg_id":17}'}

    payload, created = await manager.create_or_get(
        session_id=session_id,
        request_id="detached-request",
        action="继续",
        producer_factory=producer,
    )
    events = await manager.subscribe(payload["run_id"], 0)
    first = await anext(events)
    await events.aclose()
    continue_producing.set()
    await manager.wait(payload["run_id"])

    async with session_maker() as session:
        run = await session.get(TurnRun, payload["run_id"])
    assert created is True
    assert first["event"] == "narrative"
    assert run.status == "completed"
    assert run.assistant_message_id == 17


@pytest.mark.asyncio
async def test_model_failure_is_persisted_and_replayable(turn_run_db):
    session_maker, session_id = turn_run_db
    manager = TurnRunManager(session_maker, SessionTurnCoordinator())

    async def failing_producer():
        yield {"event": "narrative", "data": '{"text":"partial"}'}
        raise RuntimeError("provider disconnected")

    payload, _ = await manager.create_or_get(
        session_id=session_id,
        request_id="failed-request",
        action="失败动作",
        producer_factory=failing_producer,
    )
    await manager.wait(payload["run_id"])
    events = await manager.subscribe(payload["run_id"], 0)
    replay = [event async for event in events]

    async with session_maker() as session:
        run = await session.get(TurnRun, payload["run_id"])
    assert run.status == "failed"
    assert run.error_code == "model_error"
    assert any("provider disconnected" in event["data"] for event in replay)


@pytest.mark.asyncio
async def test_shutdown_interrupts_run_and_releases_session(turn_run_db):
    session_maker, session_id = turn_run_db
    coordinator = SessionTurnCoordinator()
    manager = TurnRunManager(session_maker, coordinator)

    async def producer():
        await asyncio.Event().wait()
        yield {"event": "done", "data": "{}"}

    payload, _ = await manager.create_or_get(
        session_id=session_id,
        request_id="shutdown-request",
        action="等待关闭",
        producer_factory=producer,
    )
    await manager.shutdown()

    async with session_maker() as session:
        run = await session.get(TurnRun, payload["run_id"])
    assert run.status == "interrupted"
    assert run.error_code == "run_interrupted"
    assert await coordinator.get_active(session_id) is None


@pytest.mark.asyncio
async def test_repeated_active_create_is_idempotent_and_other_request_is_busy(turn_run_db):
    session_maker, session_id = turn_run_db
    manager = TurnRunManager(session_maker, SessionTurnCoordinator())
    release = asyncio.Event()

    async def producer():
        await release.wait()
        yield {"event": "done", "data": '{"assistant_msg_id":1}'}

    first, _ = await manager.create_or_get(
        session_id=session_id,
        request_id="same-request",
        action="唯一动作",
        producer_factory=producer,
    )
    repeated, created = await manager.create_or_get(
        session_id=session_id,
        request_id="same-request",
        action="不会替换",
        producer_factory=producer,
    )
    with pytest.raises(SessionBusyError) as raised:
        await manager.create_or_get(
            session_id=session_id,
            request_id="other-request",
            action="并发动作",
            producer_factory=producer,
        )

    assert created is False
    assert repeated["run_id"] == first["run_id"]
    assert raised.value.active.run_id == first["run_id"]
    release.set()
    await manager.wait(first["run_id"])


@pytest.mark.asyncio
async def test_turn_run_api_commits_only_one_message_pair_for_repeated_submit(
    turn_run_db,
    monkeypatch,
):
    session_maker, session_id = turn_run_db
    app = create_app(session_maker, start_remote_discovery=False)
    monkeypatch.setattr(
        "dzmm.api.routes_sessions.build_client",
        lambda _config: StubGM("<narrative>门后很安静。</narrative>"),
    )
    request = {"request_id": "android-request-1", "action": "检查门后"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            f"/sessions/{session_id}/turn-runs", json=request
        )
        repeated = await client.post(
            f"/sessions/{session_id}/turn-runs", json=request
        )
        run_id = created.json()["run_id"]
        await app.state.turn_run_manager.wait(run_id)
        status = await client.get(f"/sessions/{session_id}/turn-runs/{run_id}")
        events = await client.get(
            f"/sessions/{session_id}/turn-runs/{run_id}/events"
        )
        replay = await client.get(
            f"/sessions/{session_id}/turn-runs/{run_id}/events",
            headers={"Last-Event-ID": "1"},
        )
        gap = await client.get(
            f"/sessions/{session_id}/turn-runs/{run_id}/events",
            headers={"Last-Event-ID": "999"},
        )

    async with session_maker() as session:
        run_count = await session.scalar(
            select(func.count(TurnRun.id)).where(TurnRun.session_id == session_id)
        )
        messages = (
            await session.execute(
                select(Message).where(Message.session_id == session_id)
            )
        ).scalars().all()

    assert created.status_code == repeated.status_code == 202
    assert repeated.json()["run_id"] == run_id
    assert status.json()["status"] == "completed"
    assert status.json()["assistant_message_id"] is not None
    assert "id: 1" in events.text and "event: done" in events.text
    assert "id: 1" not in replay.text and "event: done" in replay.text
    assert gap.status_code == 409
    assert gap.json()["code"] == "event_gap"
    assert run_count == 1
    assert [message.role for message in messages] == ["user", "assistant"]
