"""Constants for the PC Power integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "pc_power"
NAME = "PC Power"
PLATFORMS: list[Platform] = [Platform.SWITCH]

CONF_NAME = "name"
CONF_HOST = "host"
CONF_MAC = "mac"
CONF_BROADCAST = "broadcast_address"
CONF_WOL_PORT = "wol_port"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_BOOT_GRACE = "boot_grace"
CONF_TCP_PORTS = "tcp_ports"

CONF_SHUTDOWN_METHOD = "shutdown_method"
CONF_OS_TYPE = "os_type"
CONF_SSH_PORT = "ssh_port"
CONF_SSH_USER = "ssh_user"
CONF_SSH_AUTH = "ssh_auth"
CONF_SSH_PASSWORD = "ssh_password"
CONF_SSH_KEY = "ssh_key"
CONF_CUSTOM_CMD = "custom_command"

DEFAULT_BROADCAST = "255.255.255.255"
DEFAULT_WOL_PORT = 9
DEFAULT_SCAN_INTERVAL = 15
DEFAULT_BOOT_GRACE = 120
DEFAULT_TCP_PORTS = "445,3389,22"
DEFAULT_SSH_PORT = 22

OFF_GRACE = 60

METHOD_SSH = "ssh"
METHOD_NONE = "none"
METHODS = [METHOD_SSH, METHOD_NONE]

OS_WINDOWS = "windows"
OS_LINUX = "linux"
OS_MACOS = "macos"
OS_CUSTOM = "custom"
OS_TYPES = [OS_WINDOWS, OS_LINUX, OS_MACOS, OS_CUSTOM]

AUTH_PASSWORD = "password"
AUTH_KEY = "key"
AUTH_TYPES = [AUTH_PASSWORD, AUTH_KEY]

DEFAULT_SHUTDOWN_COMMANDS = {
    OS_WINDOWS: "shutdown /s /f /t 0",
    OS_LINUX: "sudo -n systemctl poweroff",
    OS_MACOS: "pmset sleepnow",
    OS_CUSTOM: "",
}
