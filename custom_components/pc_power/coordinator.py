"""State coordinator: probe the PC, send magic packets, run the shutdown command."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    AUTH_KEY,
    AUTH_PASSWORD,
    CONF_BOOT_GRACE,
    CONF_BROADCAST,
    CONF_CUSTOM_CMD,
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_OS_TYPE,
    CONF_SCAN_INTERVAL,
    CONF_SHUTDOWN_METHOD,
    CONF_SSH_AUTH,
    CONF_SSH_KEY,
    CONF_SSH_PASSWORD,
    CONF_SSH_PORT,
    CONF_SSH_USER,
    CONF_TCP_PORTS,
    CONF_WOL_PORT,
    DEFAULT_BOOT_GRACE,
    DEFAULT_BROADCAST,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SHUTDOWN_COMMANDS,
    DEFAULT_SSH_PORT,
    DEFAULT_TCP_PORTS,
    DEFAULT_WOL_PORT,
    DOMAIN,
    METHOD_SSH,
    OS_WINDOWS,
)

try:
    import asyncssh
except ImportError:  # pragma: no cover - handled at runtime
    asyncssh = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)

PROBE_TIMEOUT = 1.5
TCP_TIMEOUT = 0.6


@dataclass
class PCStatus:
    """Result of one probe."""

    is_on: bool
    rtt: float | None = None
    last_seen: datetime | None = None


def parse_ports(raw: str | None) -> list[int]:
    """Parse a comma separated port list."""
    if not raw:
        return []
    ports: list[int] = []
    for chunk in str(raw).replace(" ", "").split(","):
        if not chunk:
            continue
        try:
            port = int(chunk)
        except ValueError:
            continue
        if 0 < port < 65536:
            ports.append(port)
    return ports


def _magic_packet(mac: str) -> bytes:
    """Build a Wake-on-LAN magic packet."""
    clean = mac.replace(":", "").replace("-", "").replace(".", "")
    return b"\xff" * 6 + bytes.fromhex(clean) * 16


def _derived_broadcast(host: str) -> str | None:
    """Guess the /24 broadcast address of a private IPv4 host."""
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        return None
    if not address.is_private:
        return None
    parts = str(address).split(".")
    return ".".join([*parts[:3], "255"])


async def _probe_icmp(host: str, timeout: float) -> tuple[bool, float | None] | None:
    """ICMP echo via icmplib. Returns None when ICMP is not usable."""
    try:
        import icmplib
    except ImportError:
        return None

    for privileged in (True, False):
        try:
            result = await icmplib.async_ping(
                host, count=1, timeout=timeout, privileged=privileged
            )
        except PermissionError:
            continue
        except Exception:  # noqa: BLE001 - never break the poll loop
            return None
        return bool(result.is_alive), result.avg_rtt or None
    return None


async def _probe_ping_binary(host: str, timeout: float) -> bool:
    """Fallback using the ping binary (present on HA OS / Supervised)."""
    try:
        process = await asyncio.create_subprocess_exec(
            "ping",
            "-n",
            "-c",
            "1",
            "-W",
            str(max(1, int(timeout))),
            host,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (FileNotFoundError, NotImplementedError, OSError):
        return False

    try:
        return await asyncio.wait_for(process.wait(), timeout=timeout + 1) == 0
    except asyncio.TimeoutError:
        process.kill()
        return False


async def _probe_tcp(host: str, port: int) -> bool:
    """Fallback: is a TCP port accepting connections?"""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=TCP_TIMEOUT
        )
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001
        pass
    return True


async def async_probe(
    host: str, tcp_ports: list[int], timeout: float = PROBE_TIMEOUT
) -> tuple[bool, float | None]:
    """Return (is_on, rtt) using ICMP first, then TCP ports."""
    icmp = await _probe_icmp(host, timeout)
    if icmp is not None and icmp[0]:
        return True, icmp[1]

    tasks = [_probe_ping_binary(host, timeout)]
    tasks.extend(_probe_tcp(host, port) for port in tcp_ports)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if result is True:
            return True, None
    return False, None


class PCPowerCoordinator(DataUpdateCoordinator[PCStatus]):
    """Polls one PC and exposes wake / shutdown actions."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set up the coordinator from the config entry."""
        self.entry = entry
        self.conf: dict[str, Any] = {**entry.data, **entry.options}
        self.host: str = self.conf[CONF_HOST]
        self.mac: str = self.conf[CONF_MAC]
        self.tcp_ports = parse_ports(self.conf.get(CONF_TCP_PORTS, DEFAULT_TCP_PORTS))
        self.boot_grace: int = int(
            self.conf.get(CONF_BOOT_GRACE, DEFAULT_BOOT_GRACE)
        )
        interval = int(self.conf.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.conf.get(CONF_NAME)}",
            update_interval=timedelta(seconds=interval),
        )
        self._last_seen: datetime | None = None

    async def _async_update_data(self) -> PCStatus:
        """Probe the PC. A powered-off PC is a valid state, never an error."""
        try:
            is_on, rtt = await async_probe(self.host, self.tcp_ports)
        except Exception:  # noqa: BLE001 - keep the entity available
            _LOGGER.exception("Probe of %s failed", self.host)
            is_on, rtt = False, None

        if is_on:
            self._last_seen = dt_util.utcnow()
        return PCStatus(is_on=is_on, rtt=rtt, last_seen=self._last_seen)

    async def async_wake(self) -> None:
        """Send magic packets."""
        await self.hass.async_add_executor_job(self._send_magic_packets)

    def _broadcast_targets(self) -> list[str]:
        """Return every broadcast address worth trying."""
        targets: list[str] = []
        configured = self.conf.get(CONF_BROADCAST) or DEFAULT_BROADCAST
        for candidate in (configured, _derived_broadcast(self.host), "255.255.255.255"):
            if candidate and candidate not in targets:
                targets.append(candidate)
        return targets

    def _send_magic_packets(self) -> None:
        """Broadcast the magic packet a few times (sync, runs in executor)."""
        packet = _magic_packet(self.mac)
        port = int(self.conf.get(CONF_WOL_PORT, DEFAULT_WOL_PORT))
        for target in self._broadcast_targets():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    sock.settimeout(2)
                    for _ in range(3):
                        sock.sendto(packet, (target, port))
                        time.sleep(0.05)
            except OSError as err:
                _LOGGER.warning("Cannot send magic packet to %s: %s", target, err)
                continue
            _LOGGER.debug("Magic packet sent to %s:%s for %s", target, port, self.mac)
            return
        _LOGGER.error("Could not send magic packet for %s", self.conf.get(CONF_NAME))

    async def async_shutdown(self) -> None:
        """Run the shutdown command over SSH."""
        method = self.conf.get(CONF_SHUTDOWN_METHOD, METHOD_SSH)
        if method != METHOD_SSH:
            raise HomeAssistantError(
                "这台电脑没有配置关机方式，只能唤醒"
            )

        if asyncssh is None:
            raise HomeAssistantError("缺少 asyncssh 依赖，请重新安装集成")

        os_type = self.conf.get(CONF_OS_TYPE, OS_WINDOWS)
        command = (self.conf.get(CONF_CUSTOM_CMD) or "").strip() or (
            DEFAULT_SHUTDOWN_COMMANDS.get(os_type) or ""
        )
        if not command:
            raise HomeAssistantError("关机命令为空")

        kwargs: dict[str, Any] = {
            "host": self.host,
            "port": int(self.conf.get(CONF_SSH_PORT, DEFAULT_SSH_PORT)),
            "known_hosts": None,
            "connect_timeout": 10,
            "login_timeout": 10,
        }
        if username := self.conf.get(CONF_SSH_USER):
            kwargs["username"] = username

        auth = self.conf.get(CONF_SSH_AUTH, AUTH_PASSWORD)
        if auth == AUTH_KEY:
            key = (self.conf.get(CONF_SSH_KEY) or "").strip()
            if not key:
                raise HomeAssistantError("未配置 SSH 私钥路径")
            kwargs["client_keys"] = [key]
        else:
            kwargs["password"] = self.conf.get(CONF_SSH_PASSWORD) or ""

        try:
            connection = await asyncssh.connect(**kwargs)
        except (asyncssh.Error, OSError) as err:
            raise HomeAssistantError(f"SSH 连接失败：{err}") from err

        try:
            await connection.run(command, check=False, timeout=15)
        except Exception as err:  # noqa: BLE001 - the host dies mid-command
            _LOGGER.debug("Shutdown command ended early (expected): %s", err)
        finally:
            connection.close()

        _LOGGER.debug("Shutdown command sent to %s: %s", self.host, command)
