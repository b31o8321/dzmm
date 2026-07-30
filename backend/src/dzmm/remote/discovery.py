"""Best-effort mDNS advertisement for a remote-enabled dzmm host."""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any

log = logging.getLogger(__name__)


def _is_supported_lan_ipv4(address: str) -> bool:
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
        import ifaddr

        for adapter in ifaddr.get_adapters():
            for item in adapter.ips:
                address = item.ip
                if not isinstance(address, str):
                    continue
                if _is_supported_lan_ipv4(address):
                    addresses.add(address)
    except (ImportError, OSError):
        pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if _is_supported_lan_ipv4(address):
                addresses.add(address)
    except OSError:
        return []
    return [socket.inet_aton(address) for address in sorted(addresses)]


class RemoteDiscovery:
    SERVICE_TYPE = "_dzmm._tcp.local."

    def __init__(self) -> None:
        self._zeroconf: Any = None
        self._service_info: Any = None

    async def start(
        self,
        *,
        server_id: str,
        version: str,
        api_version: int,
        port: int,
    ) -> bool:
        if self._zeroconf is not None:
            return True
        addresses = _lan_ipv4_addresses()
        if not addresses:
            log.warning("remote discovery disabled: no LAN IPv4 address found")
            return False
        try:
            from zeroconf import ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf

            hostname = socket.gethostname() or "dzmm"
            safe_name = hostname.replace(".", "-")
            info = ServiceInfo(
                self.SERVICE_TYPE,
                f"dzmm on {safe_name}.{self.SERVICE_TYPE}",
                addresses=addresses,
                port=port,
                properties={
                    "server_id": server_id,
                    "version": version,
                    "api_version": str(api_version),
                    "pairing": "available",
                },
                server=f"{safe_name}.local.",
            )
            zeroconf = AsyncZeroconf()
            self._zeroconf = zeroconf
            self._service_info = info
            await zeroconf.async_register_service(info)
            log.info("remote discovery started on _dzmm._tcp port %d", port)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("remote discovery unavailable: %s: %r", type(exc).__name__, exc)
            await self.stop()
            return False

    async def stop(self) -> None:
        zeroconf = self._zeroconf
        info = self._service_info
        self._zeroconf = None
        self._service_info = None
        if zeroconf is None:
            return
        try:
            if info is not None:
                await zeroconf.async_unregister_service(info)
        except Exception as exc:  # noqa: BLE001
            log.debug("remote discovery unregister failed: %s", exc)
        finally:
            try:
                await zeroconf.async_close()
            except Exception:  # noqa: BLE001
                pass
