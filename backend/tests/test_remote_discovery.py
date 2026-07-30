import socket
import sys
from types import ModuleType

import pytest

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.main import create_app
from dzmm.remote.discovery import RemoteDiscovery


class FakeServiceInfo:
    def __init__(self, service_type, name, **kwargs):
        self.service_type = service_type
        self.name = name
        self.kwargs = kwargs


class FakeZeroconf:
    instances = []

    def __init__(self):
        self.registered = []
        self.unregistered = []
        self.closed = False
        self.instances.append(self)

    def register_service(self, info):
        self.registered.append(info)

    def unregister_service(self, info):
        self.unregistered.append(info)

    def close(self):
        self.closed = True


def test_discovery_registers_identity_and_stops(monkeypatch):
    fake_module = ModuleType("zeroconf")
    fake_module.ServiceInfo = FakeServiceInfo
    fake_module.Zeroconf = FakeZeroconf
    monkeypatch.setitem(sys.modules, "zeroconf", fake_module)
    monkeypatch.setattr(
        "dzmm.remote.discovery._lan_ipv4_addresses",
        lambda: [socket.inet_aton("192.168.1.20")],
    )
    FakeZeroconf.instances.clear()

    discovery = RemoteDiscovery()
    assert discovery.start(
        server_id="server-uuid",
        version="0.16.0",
        api_version=1,
        port=8765,
    )
    zeroconf = FakeZeroconf.instances[0]
    info = zeroconf.registered[0]
    assert info.service_type == "_dzmm._tcp.local."
    assert info.kwargs["port"] == 8765
    assert info.kwargs["properties"]["server_id"] == "server-uuid"
    assert info.kwargs["properties"]["api_version"] == "1"

    discovery.stop()
    assert zeroconf.unregistered == [info]
    assert zeroconf.closed


def test_discovery_is_best_effort_without_lan_address(monkeypatch):
    monkeypatch.setattr("dzmm.remote.discovery._lan_ipv4_addresses", lambda: [])
    assert not RemoteDiscovery().start(
        server_id="server-uuid",
        version="0.16.0",
        api_version=1,
        port=8765,
    )


@pytest.mark.asyncio
async def test_remote_enabled_app_runs_discovery_lifecycle(tmp_path, monkeypatch):
    calls = []

    def fake_start(self, **kwargs):
        calls.append(("start", kwargs))
        return True

    def fake_stop(self):
        calls.append(("stop", {}))

    monkeypatch.setattr(RemoteDiscovery, "start", fake_start)
    monkeypatch.setattr(RemoteDiscovery, "stop", fake_stop)
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/discovery.db")
    await init_db(engine)
    app = create_app(
        async_session(engine),
        remote_access_enabled=True,
        start_remote_discovery=True,
    )

    async with app.router.lifespan_context(app):
        assert calls[0][0] == "start"
    await engine.dispose()

    assert calls[0][0] == "start"
    assert calls[0][1]["port"] == 8765
    assert calls[-1][0] == "stop"
