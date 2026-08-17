"""Best-effort mDNS advertisement for a LAN gameplay Host."""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any

log = logging.getLogger(__name__)

SERVICE_TYPE = "_dzmm._tcp.local."


def _is_private_lan_ipv4(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return (
        isinstance(parsed, ipaddress.IPv4Address)
        and parsed.is_private
        and not parsed.is_loopback
        and not parsed.is_link_local
        and not parsed.is_unspecified
    )


def _lan_ipv4_addresses() -> list[bytes]:
    addresses: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if _is_private_lan_ipv4(address):
                addresses.add(address)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
            if _is_private_lan_ipv4(address):
                addresses.add(address)
    except OSError:
        pass
    return [socket.inet_aton(address) for address in sorted(addresses)]


def lan_host_urls(port: int) -> list[str]:
    return [f"http://{socket.inet_ntoa(address)}:{port}" for address in _lan_ipv4_addresses()]


class HostAdvertisement:
    """Advertise only pairing-safe metadata; failure never stops gameplay."""

    def __init__(self) -> None:
        self._zeroconf: Any = None
        self._service_info: Any = None

    async def start(self, *, host_id: str, port: int) -> bool:
        if self._zeroconf is not None:
            return True
        addresses = _lan_ipv4_addresses()
        if not addresses:
            log.warning("mDNS Host advertisement skipped: no private IPv4 address")
            return False
        try:
            from zeroconf import ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf

            hostname = (socket.gethostname() or "dzmm").replace(".", "-")
            service_info = ServiceInfo(
                SERVICE_TYPE,
                f"DZMM Host on {hostname}.{SERVICE_TYPE}",
                addresses=addresses,
                port=port,
                properties={
                    "host_id": host_id,
                    "api": "v2",
                    "pairing": "approval",
                    "capability": "gameplay",
                },
                server=f"{hostname}.local.",
            )
            zeroconf = AsyncZeroconf()
            self._zeroconf = zeroconf
            self._service_info = service_info
            await zeroconf.async_register_service(service_info)
            log.info("mDNS Host advertisement started on %s:%d", SERVICE_TYPE, port)
            return True
        except Exception as error:  # noqa: BLE001  # pragma: no cover - platform varies
            log.warning("mDNS Host advertisement unavailable: %s: %s", type(error).__name__, error)
            await self.stop()
            return False

    async def stop(self) -> None:
        zeroconf, service_info = self._zeroconf, self._service_info
        self._zeroconf = None
        self._service_info = None
        if zeroconf is None:
            return
        try:
            if service_info is not None:
                await zeroconf.async_unregister_service(service_info)
        except Exception as error:  # noqa: BLE001  # pragma: no cover - best-effort cleanup
            log.debug("mDNS Host advertisement cleanup failed: %s", error)
        finally:
            await zeroconf.async_close()
