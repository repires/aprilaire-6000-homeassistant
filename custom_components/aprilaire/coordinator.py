"""The Aprilaire coordinator (Enhanced for 6000-Series / Model 6003)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import BaseDataUpdateCoordinatorProtocol
from pyaprilaire.const import MODELS as UPSTREAM_MODELS
from pyaprilaire.const import Action, Attribute, FunctionalDomain
from pyaprilaire.packet import Packet

from .const import DOMAIN
from .protocol import (
    ATTR_HEAT_BLAST,
    AprilaireLocalClient,
)

RECONNECT_INTERVAL = 60 * 60
RETRY_CONNECTION_INTERVAL = 10
WAIT_TIMEOUT = 30
SENSOR_POLL_INTERVAL = 60

_LOGGER = logging.getLogger(__name__)


EXTENDED_MODELS = UPSTREAM_MODELS

AprilaireConfigEntry = ConfigEntry["AprilaireCoordinator"]


class AprilaireCoordinator(BaseDataUpdateCoordinatorProtocol):
    """Coordinator for interacting with the thermostat."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: AprilaireConfigEntry | None,
        host: str,
        port: int,
    ) -> None:
        """Initialize the coordinator."""

        self.hass = hass
        self.config_entry = config_entry
        self.unique_id = config_entry.unique_id if config_entry else None
        self.data: dict[str, Any] = {}
        self._sensor_poll_task: asyncio.Task[None] | None = None
        self._raw_data: dict[str, Any] = {}
        self._host = host
        self._port = port

        self._listeners: dict[CALLBACK_TYPE, tuple[CALLBACK_TYPE, object | None]] = {}

        self.client = AprilaireLocalClient(
            host,
            port,
            self.async_set_updated_data,
            _LOGGER,
            RECONNECT_INTERVAL,
            RETRY_CONNECTION_INTERVAL,
        )

        if hasattr(self.client, "data") and self.client.data:
            self.data = self._normalize_sensors(self.client.data)

    def _normalize_sensors(self, data: dict[str, Any]) -> dict[str, Any]:
        """On 6003 zoned systems, controlling sensor is status 4; fall back to built-in sensor."""
        normalized = dict(data)
        if data.get(Attribute.MODEL_NUMBER) != 28:
            return normalized
        # Indoor humidity fallback
        hum_status = normalized.get(Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS)
        builtin_hum = normalized.get(Attribute.BUILT_IN_HUMIDITY_SENSOR_VALUE)
        if (
            hum_status != 0
            and normalized.get(Attribute.BUILT_IN_HUMIDITY_SENSOR_STATUS) == 0
            and builtin_hum is not None
        ):
            normalized[Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS] = 0
            normalized[Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE] = builtin_hum

        # Indoor temperature fallback
        temp_status = normalized.get(Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS)
        builtin_temp = normalized.get(Attribute.BUILT_IN_TEMPERATURE_SENSOR_VALUE)
        if (
            temp_status != 0
            and normalized.get(Attribute.BUILT_IN_TEMPERATURE_SENSOR_STATUS) == 0
            and builtin_temp is not None
        ):
            normalized[Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS] = 0
            normalized[Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE] = builtin_temp

        return normalized

    @callback
    @override
    def async_add_listener(
        self, update_callback: CALLBACK_TYPE, context: Any = None
    ) -> Callable[[], None]:
        """Listen for data updates."""

        @callback
        def remove_listener() -> None:
            """Remove update listener."""
            self._listeners.pop(remove_listener, None)

        self._listeners[remove_listener] = (update_callback, context)

        return remove_listener

    @callback
    def async_update_listeners(self) -> None:
        """Update all registered listeners."""
        for update_callback, _ in list(self._listeners.values()):
            update_callback()

    def async_set_updated_data(self, data: Any) -> None:
        """Manually update data, notify listeners and update device registry."""

        old_device_info = self.create_device_info(self.data)

        self._raw_data.update(data)
        self.data = self._normalize_sensors(self._raw_data)

        self.async_update_listeners()

        # Pass merged self.data so MAC_ADDRESS is always present when checking changes
        new_device_info = self.create_device_info(self.data)

        if (
            self.config_entry is not None
            and new_device_info is not None
            and old_device_info != new_device_info
        ):
            dr.async_get(self.hass).async_get_or_create(
                config_entry_id=self.config_entry.entry_id, **new_device_info
            )

    async def _send_raw_read(self, domain: FunctionalDomain, attribute: int) -> None:
        """Send a raw READ_REQUEST frame via the underlying protocol."""
        if self.client.connected and self.client.protocol is not None:
            await self.client.protocol.read(domain, attribute)

    async def async_set_fan_mode(self, fan_mode_value: int) -> None:
        """Update furnace/AC blower fan mode and immediately refresh control + equipment status."""
        await self.client.update_fan_mode(fan_mode_value)
        await self.client.read_control()
        await self.client.read_thermostat_status()

    async def async_set_heat_blast(self, enabled: bool) -> None:
        """Enable or disable Heat Blast (3, 5) and read back state."""
        if self.client.connected and self.client.protocol is not None:
            await self.client.protocol._send_packet(
                Packet(
                    Action.WRITE,
                    FunctionalDomain.SCHEDULING,
                    5,
                    raw_data=[1 if enabled else 0],
                )
            )
            await self._send_raw_read(FunctionalDomain.SCHEDULING, 5)
            await self.client.read_control()
            await self.client.read_thermostat_status()

    async def _periodic_sensor_poll(self) -> None:
        """Periodically poll (5, 1) full sensor array (LAT/ODT), (3, 5) Heat Blast, and equipment status."""
        while True:
            await asyncio.sleep(SENSOR_POLL_INTERVAL)
            try:
                await self._send_raw_read(FunctionalDomain.SENSORS, 1)
                await asyncio.sleep(0.35)
                if ATTR_HEAT_BLAST in self.data:
                    await self._send_raw_read(FunctionalDomain.SCHEDULING, 5)
                await asyncio.sleep(0.35)
                await self.client.read_thermostat_status()
                await asyncio.sleep(0.35)
                await self.client.read_iaq_status()
            except Exception:
                _LOGGER.debug("Periodic sensor poll skipped", exc_info=True)

    async def start_listen(self) -> None:
        """Start listening for data."""
        await self.client.start_listen()
        if self._sensor_poll_task is None or self._sensor_poll_task.done():
            self._sensor_poll_task = asyncio.create_task(self._periodic_sensor_poll())

    def stop_listen(self) -> None:
        """Stop listening for data."""
        if self._sensor_poll_task and not self._sensor_poll_task.done():
            self._sensor_poll_task.cancel()
        self.client.stop_listen()

    async def wait_for_ready(self, ready_callback: Callable[[bool], Awaitable[None]]) -> bool:
        """Wait for the client to be ready and query extended 6003 attributes."""

        try:
            await self.client.wait_ready()
        except TimeoutError:
            await ready_callback(False)
            return False
        await ready_callback(True)
        return True

    async def async_stop(self) -> None:
        """Cancel and await all tasks owned by this entry."""
        self.stop_listen()
        if self._sensor_poll_task:
            await asyncio.gather(self._sensor_poll_task, return_exceptions=True)
            self._sensor_poll_task = None
        await self.client.async_stop()

    @property
    def device_name(self) -> str:
        """Get the name of the thermostat."""
        return self.create_device_name(self.data)

    def create_device_name(self, data: dict[str, Any] | None) -> str:
        """Create the name of the thermostat."""
        name = data.get(Attribute.NAME) if data else None
        return name or "Aprilaire"

    def get_hw_version(self, data: dict[str, Any]) -> str:
        """Get the hardware version."""
        if hardware_revision := data.get(Attribute.HARDWARE_REVISION):
            return (
                f"Rev. {chr(hardware_revision)}"
                if hardware_revision > ord("A")
                else str(hardware_revision)
            )
        return "Unknown"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Get the device info for the thermostat."""
        return self.create_device_info(self.data)

    def create_device_info(self, data: dict[str, Any]) -> DeviceInfo | None:
        """Create the device info for the thermostat."""

        if data is None or Attribute.MAC_ADDRESS not in data or self.unique_id is None:
            return None

        device_info = DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            connections={(dr.CONNECTION_NETWORK_MAC, data[Attribute.MAC_ADDRESS])},
            name=self.create_device_name(data),
            manufacturer="AprilAire",
            hw_version=self.get_hw_version(data),
        )

        model_number = data.get(Attribute.MODEL_NUMBER)
        if model_number is not None:
            device_info["model"] = EXTENDED_MODELS.get(model_number, f"Unknown ({model_number})")

        firmware_major_revision = data.get(Attribute.FIRMWARE_MAJOR_REVISION)
        firmware_minor_revision = data.get(Attribute.FIRMWARE_MINOR_REVISION)
        if firmware_major_revision is not None:
            device_info["sw_version"] = (
                str(firmware_major_revision)
                if firmware_minor_revision is None
                else f"{firmware_major_revision}.{firmware_minor_revision:02}"
            )

        return device_info
