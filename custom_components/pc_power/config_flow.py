"""Config and options flow for PC Power."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    AUTH_KEY,
    AUTH_PASSWORD,
    AUTH_TYPES,
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
    DEFAULT_BOOT_GRACE,
    DEFAULT_BROADCAST,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SSH_PORT,
    DEFAULT_TCP_PORTS,
    DOMAIN,
    METHOD_SSH,
    METHODS,
    OS_CUSTOM,
    OS_TYPES,
    OS_WINDOWS,
)

_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def normalize_mac(value: str) -> str | None:
    """Normalise AA-BB-CC-DD-EE-FF / aabbccddeeff to aa:bb:cc:dd:ee:ff."""
    raw = (value or "").strip().lower().replace("-", ":").replace(".", ":")
    if re.fullmatch(r"[0-9a-f]{12}", raw):
        raw = ":".join(raw[i : i + 2] for i in range(0, 12, 2))
    return raw if _MAC_RE.match(raw) else None


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Basic connection settings."""
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME, default=defaults.get(CONF_NAME, "")
            ): selector.TextSelector(),
            vol.Required(
                CONF_HOST, default=defaults.get(CONF_HOST, "")
            ): selector.TextSelector(),
            vol.Required(
                CONF_MAC, default=defaults.get(CONF_MAC, "")
            ): selector.TextSelector(),
            vol.Optional(
                CONF_BROADCAST,
                default=defaults.get(CONF_BROADCAST, DEFAULT_BROADCAST),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5,
                    max=300,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="秒",
                )
            ),
            vol.Optional(
                CONF_BOOT_GRACE,
                default=defaults.get(CONF_BOOT_GRACE, DEFAULT_BOOT_GRACE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10,
                    max=600,
                    step=5,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="秒",
                )
            ),
            vol.Optional(
                CONF_TCP_PORTS,
                default=defaults.get(CONF_TCP_PORTS, DEFAULT_TCP_PORTS),
            ): selector.TextSelector(),
        }
    )


def _shutdown_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Shutdown over SSH."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SHUTDOWN_METHOD,
                default=defaults.get(CONF_SHUTDOWN_METHOD, METHOD_SSH),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=METHODS,
                    translation_key="shutdown_method",
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Optional(
                CONF_OS_TYPE, default=defaults.get(CONF_OS_TYPE, OS_WINDOWS)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=OS_TYPES,
                    translation_key="os_type",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_SSH_PORT, default=defaults.get(CONF_SSH_PORT, DEFAULT_SSH_PORT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=65535,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_SSH_USER, default=defaults.get(CONF_SSH_USER, "")
            ): selector.TextSelector(),
            vol.Optional(
                CONF_SSH_AUTH, default=defaults.get(CONF_SSH_AUTH, AUTH_PASSWORD)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=AUTH_TYPES,
                    translation_key="ssh_auth",
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Optional(
                CONF_SSH_PASSWORD, default=defaults.get(CONF_SSH_PASSWORD, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.PASSWORD
                )
            ),
            vol.Optional(
                CONF_SSH_KEY, default=defaults.get(CONF_SSH_KEY, "")
            ): selector.TextSelector(),
            vol.Optional(
                CONF_CUSTOM_CMD, default=defaults.get(CONF_CUSTOM_CMD, "")
            ): selector.TextSelector(),
        }
    )


def _validate_shutdown(data: dict[str, Any]) -> dict[str, str]:
    """Validate the shutdown step."""
    errors: dict[str, str] = {}
    if data.get(CONF_SHUTDOWN_METHOD) != METHOD_SSH:
        return errors

    if not (data.get(CONF_SSH_USER) or "").strip():
        errors[CONF_SSH_USER] = "missing_user"

    if data.get(CONF_SSH_AUTH, AUTH_PASSWORD) == AUTH_KEY:
        if not (data.get(CONF_SSH_KEY) or "").strip():
            errors[CONF_SSH_KEY] = "missing_key"
    elif not data.get(CONF_SSH_PASSWORD):
        errors[CONF_SSH_PASSWORD] = "missing_password"

    if data.get(CONF_OS_TYPE) == OS_CUSTOM and not (
        data.get(CONF_CUSTOM_CMD) or ""
    ).strip():
        errors[CONF_CUSTOM_CMD] = "missing_command"

    return errors


class PCPowerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a PC."""

    VERSION = 1

    _data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: address, MAC and polling."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = normalize_mac(user_input.get(CONF_MAC, ""))
            if mac is None:
                errors[CONF_MAC] = "invalid_mac"
            else:
                user_input[CONF_MAC] = mac
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                self._data = user_input
                return await self.async_step_shutdown()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_shutdown(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: how to shut the PC down."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_shutdown(user_input)
            if not errors:
                return self.async_create_entry(
                    title=self._data[CONF_NAME],
                    data={**self._data, **user_input},
                )

        return self.async_show_form(
            step_id="shutdown",
            data_schema=_shutdown_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return PCPowerOptionsFlow()


class PCPowerOptionsFlow(OptionsFlow):
    """Edit an existing PC."""

    _data: dict[str, Any] = {}

    @property
    def _conf(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: connection settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = normalize_mac(user_input.get(CONF_MAC, ""))
            if mac is None:
                errors[CONF_MAC] = "invalid_mac"
            else:
                user_input[CONF_MAC] = mac
                self._data = user_input
                return await self.async_step_shutdown()

        return self.async_show_form(
            step_id="init",
            data_schema=_user_schema(user_input or self._conf),
            errors=errors,
        )

    async def async_step_shutdown(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: shutdown settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_shutdown(user_input)
            if not errors:
                data = {**self._data, **user_input}
                self.hass.config_entries.async_update_entry(
                    self.config_entry, title=data[CONF_NAME]
                )
                return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="shutdown",
            data_schema=_shutdown_schema(user_input or self._conf),
            errors=errors,
        )
