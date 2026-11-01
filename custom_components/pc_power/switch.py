"""Switch platform: one switch entity per PC."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_MAC,
    CONF_NAME,
    CONF_SHUTDOWN_METHOD,
    DOMAIN,
    METHOD_SSH,
    OFF_GRACE,
)
from .coordinator import PCPowerCoordinator


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    """Add the switch for this PC."""
    coordinator: PCPowerCoordinator = entry.runtime_data
    async_add_entities([PCPowerSwitch(coordinator, entry)])


class PCPowerSwitch(CoordinatorEntity[PCPowerCoordinator], SwitchEntity):
    """A single on/off tile that also reports the real power state."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:desktop-tower-monitor"

    def __init__(self, coordinator: PCPowerCoordinator, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        conf = coordinator.conf
        self._attr_unique_id = f"{DOMAIN}_{conf[CONF_MAC]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, conf[CONF_MAC])},
            name=conf[CONF_NAME],
            manufacturer="PC Power",
            model="Wake-on-LAN + SSH",
            sw_version="1.0.0",
        )
        self._optimistic_state: bool | None = None
        self._optimistic_until: float = 0.0

    @property
    def available(self) -> bool:
        """Always available: a powered-off PC is 'off', not 'unavailable'."""
        return True

    @property
    def is_on(self) -> bool:
        """Return the power state, honouring the optimistic grace window."""
        if (
            self._optimistic_state is not None
            and time.monotonic() < self._optimistic_until
        ):
            return self._optimistic_state
        return bool(self.coordinator.data and self.coordinator.data.is_on)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose a few diagnostics."""
        data = self.coordinator.data
        return {
            "ip_address": self.coordinator.host,
            "mac_address": self.coordinator.mac,
            "rtt_ms": round(data.rtt, 1) if data and data.rtt else None,
            "last_seen": data.last_seen.isoformat() if data and data.last_seen else None,
            "shutdown_configured": self.coordinator.conf.get("shutdown_method")
            == METHOD_SSH,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Wake the PC."""
        await self.coordinator.async_wake()
        self._optimistic_state = True
        self._optimistic_until = time.monotonic() + self.coordinator.boot_grace
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Shut the PC down over SSH."""
        await self.coordinator.async_shutdown()
        self._optimistic_state = False
        self._optimistic_until = time.monotonic() + OFF_GRACE
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        """Drop the optimistic guess as soon as reality matches it."""
        actual = bool(self.coordinator.data and self.coordinator.data.is_on)
        if self._optimistic_state is not None:
            if actual == self._optimistic_state:
                self._optimistic_state = None
            elif time.monotonic() >= self._optimistic_until:
                self._optimistic_state = None
        super()._handle_coordinator_update()
