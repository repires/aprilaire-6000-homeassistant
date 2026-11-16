"""The Aprilaire coordinator (Enhanced for 6000-Series / Model 6003)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import ipaddress
import logging
from typing import Any, override

import pyaprilaire.client
from pyaprilaire.const import MODELS as UPSTREAM_MODELS, Action, Attribute, FunctionalDomain
from pyaprilaire.packet import MAPPING, NackPacket, Packet, ValueType

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import BaseDataUpdateCoordinatorProtocol

from .const import DOMAIN

RECONNECT_INTERVAL = 60 * 60
RETRY_CONNECTION_INTERVAL = 10
WAIT_TIMEOUT = 30
SENSOR_POLL_INTERVAL = 60

_LOGGER = logging.getLogger(__name__)

# Extend upstream model table with 8840M (14) and 6003 (28)
EXTENDED_MODELS: dict[int, str] = {
    **UPSTREAM_MODELS,
    14: "8840M",
    28: "6003 (6000-Series Zone Control)",
}

ATTR_HEAT_BLAST = "heat_blast"
ATTR_ZONE_COUNT = "zone_count"
ATTR_DAT_LOW_LIMIT = "dat_low_limit"
ATTR_DAT_HIGH_LIMIT = "dat_high_limit"

# Register (3, 5) Heat Blast, (1, 10) Zone System Settings, and extended (8, 2) ID in pyaprilaire's packet MAPPING
MAPPING[Action.READ_RESPONSE][FunctionalDomain.SCHEDULING][5] = [
    (ATTR_HEAT_BLAST, ValueType.INTEGER),
]
MAPPING[Action.READ_RESPONSE][FunctionalDomain.IDENTIFICATION][2] = [
    (Attribute.MAC_ADDRESS, ValueType.MAC_ADDRESS),
    (None, None),  # force_connection
    (Attribute.HARDWARE_REVISION, ValueType.INTEGER),
    (Attribute.FIRMWARE_MAJOR_REVISION, ValueType.INTEGER),
    (Attribute.FIRMWARE_MINOR_REVISION, ValueType.INTEGER),
    (Attribute.PROTOCOL_MAJOR_REVISION, ValueType.INTEGER),
    (Attribute.MODEL_NUMBER, ValueType.INTEGER),
    (Attribute.GAINSPAN_FIRMWARE_MAJOR_REVISION, ValueType.INTEGER),
    (Attribute.GAINSPAN_FIRMWARE_MINOR_REVISION, ValueType.INTEGER),
]
MAPPING[Action.READ_RESPONSE][FunctionalDomain.SETUP][10] = [
    (None, None),  # 0
    (None, None),  # 1 Staging Based On
    (ATTR_ZONE_COUNT, ValueType.INTEGER),  # 2 Number of Zones
    (None, None),  # 3 Zones to Stage
    (None, None),  # 4 Zone 1 Weighting
    (None, None),  # 5 Zone 2 Weighting
    (None, None),  # 6 Zone 3 Weighting
    (None, None),  # 7 DAT Sensor Enabled
    (ATTR_DAT_LOW_LIMIT, ValueType.TEMPERATURE),  # 8 DAT Low Limit
    (None, None),  # 9 Downstage on DAT
    (ATTR_DAT_HIGH_LIMIT, ValueType.TEMPERATURE),  # 10 DAT High Limit
]


async def _paced_queue_loop(self: Any, loop_count: int | None = None) -> None:
    """Send at most one packet per 0.30s so the 19200-baud RS-485 bus never drops burst frames."""
    while loop_count is None or loop_count > 0:
        if loop_count is not None:
            loop_count -= 1
        try:
            packet: Packet = self.packet_queue.get_nowait()
            if self.transport:
                serialized_packet = packet.serialize()
                if hasattr(self, "logger") and self.logger:
                    self.logger.debug("Sent data: %s", serialized_packet.hex(" "))
                self.transport.write(serialized_packet)
                await asyncio.sleep(0.30)
                continue
        except asyncio.QueueEmpty:
            pass
        await asyncio.sleep(0.10)


async def _read_thermostat_name_v2(self: Any) -> None:
    """Read (8, 4) Location & Name (supported on 6000-series where (8, 5) NACKs)."""
    await self._send_packet(
        Packet(Action.READ_REQUEST, FunctionalDomain.IDENTIFICATION, 4)
    )


def _patched_packet_parse(cls: Any, data: bytes) -> Any:
    """Patch upstream Packet.parse to fix 16-bit length bitwise shift and MAC hex formatting."""
    data_index = 0

    while data_index < len(data):
        if data_index + 4 > len(data):
            break
        revision = data[data_index]
        sequence = data[data_index + 1]
        count = (data[data_index + 2] << 8) | data[data_index + 3]

        if data_index + count + 5 > len(data):
            break

        action = int(data[data_index + 4])
        functional_domain = int(data[data_index + 5])
        attribute = int(data[data_index + 6])

        try:
            action = Action(action)
            functional_domain = FunctionalDomain(functional_domain)
        except Exception:
            data_index += count + 5
            continue

        if action == Action.NACK:
            nack_attribute = int(data[data_index + 5])
            yield NackPacket(nack_attribute)
            data_index += count + 5
            continue

        if (
            action not in MAPPING
            or functional_domain not in MAPPING[action]
            or attribute not in MAPPING[action][functional_domain]
        ):
            data_index += count + 5
            continue

        packet = Packet(
            action, functional_domain, attribute, revision, sequence, count
        )

        final_index = data_index + count + 3
        payload_start_index = data_index
        data_index += 7
        attribute_index = 0

        while data_index <= final_index:
            if attribute_index >= len(
                MAPPING[action][functional_domain][attribute]
            ):
                data_index += 1
            else:
                attribute_info = MAPPING[action][functional_domain][attribute][
                    attribute_index
                ]

                attribute_name, value_type = attribute_info[0], attribute_info[1]
                extra_attribute_info = attribute_info[2:]

                if attribute_name is None or value_type is None:
                    data_index += 1
                    attribute_index += 1
                    continue

                data_value = data[data_index]

                if value_type == ValueType.INTEGER:
                    packet.data[attribute_name] = data_value
                    data_index += 1
                elif value_type == ValueType.INTEGER_REQUIRED:
                    if data_value is not None and data_value != 0:
                        packet.data[attribute_name] = data_value
                    data_index += 1
                elif value_type == ValueType.HUMIDITY:
                    packet.data[attribute_name] = cls._decode_humidity(data_value)
                    data_index += 1
                elif value_type == ValueType.TEMPERATURE:
                    packet.data[attribute_name] = cls._decode_temperature(data_value)
                    data_index += 1
                elif value_type == ValueType.TEMPERATURE_REQUIRED:
                    if data_value is not None and data_value != 0:
                        packet.data[attribute_name] = cls._decode_temperature(data_value)
                    data_index += 1
                elif value_type == ValueType.MAC_ADDRESS:
                    mac_address_components = []
                    for _ in range(0, 6):
                        mac_address_components.append(f"{data[data_index]:02x}")
                        data_index += 1
                    packet.data[attribute_name] = ":".join(mac_address_components)
                elif value_type == ValueType.TEXT:
                    text_length = extra_attribute_info[0]
                    text = ""
                    for _ in range(0, text_length):
                        current_value = " " if data[data_index] == 0 else chr(data[data_index])
                        text += current_value
                        data_index += 1
                    data_index += 1
                    packet.data[attribute_name] = text.strip(" ")

                attribute_index += 1

        crc = data[data_index]
        if Packet._verify_crc(data[payload_start_index:data_index], crc):
            yield packet

        data_index += 1


Packet.parse = classmethod(_patched_packet_parse)


async def _noop_update_status(self: Any) -> None:
    """Disable upstream pyaprilaire _update_status to prevent burst flood & socket disconnect on 6003."""
    pass


# Patch upstream _AprilaireClientProtocol so bursts are paced on the RS-485 UART
pyaprilaire.client._AprilaireClientProtocol._queue_loop = _paced_queue_loop
pyaprilaire.client._AprilaireClientProtocol.read_thermostat_name = _read_thermostat_name_v2
pyaprilaire.client._AprilaireClientProtocol._update_status = _noop_update_status

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
        self._ip_watchdog_task: asyncio.Task[None] | None = None
        self._host = host
        self._port = port

        self._listeners: dict[CALLBACK_TYPE, tuple[CALLBACK_TYPE, object | None]] = {}

        self.client = pyaprilaire.client.AprilaireClient(
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
        # Indoor humidity fallback
        hum_status = normalized.get(Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS)
        builtin_hum = normalized.get(Attribute.BUILT_IN_HUMIDITY_SENSOR_VALUE)
        if (hum_status is None or hum_status != 0) and builtin_hum is not None:
            normalized[Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS] = 0
            normalized[Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE] = builtin_hum

        # Indoor temperature fallback
        temp_status = normalized.get(Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS)
        builtin_temp = normalized.get(Attribute.BUILT_IN_TEMPERATURE_SENSOR_VALUE)
        if (temp_status is None or temp_status != 0) and builtin_temp is not None:
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

        self.data = self._normalize_sensors(self.data | data)

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
        if getattr(self.client, "protocol", None) is not None:
            await self.client.protocol._send_packet(
                Packet(Action.READ_REQUEST, domain, attribute)
            )

    async def async_set_fan_mode(self, fan_mode_value: int) -> None:
        """Update furnace/AC blower fan mode and immediately refresh control + equipment status."""
        await self.client.update_fan_mode(fan_mode_value)
        await self.client.read_control()
        await self.client.read_thermostat_status()

    async def async_set_heat_blast(self, enabled: bool) -> None:
        """Enable or disable Heat Blast (3, 5) and read back state."""
        if getattr(self.client, "protocol", None) is not None:
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
                await self._send_raw_read(FunctionalDomain.SCHEDULING, 5)
                await asyncio.sleep(0.35)
                await self.client.read_thermostat_status()
                await asyncio.sleep(0.35)
                await self.client.read_iaq_status()
            except Exception:
                _LOGGER.debug("Periodic sensor poll skipped", exc_info=True)

    async def _rediscover_host_by_mac(self, target_mac: str) -> str | None:
        """Scan the local /24 subnet for the thermostat's port and verify its MAC."""
        try:
            network = ipaddress.ip_network(f"{self._host}/24", strict=False)
        except ValueError:
            return None

        sem = asyncio.Semaphore(64)

        async def _probe(ip: str) -> str | None:
            async with sem:
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(ip, self._port), timeout=0.4
                    )
                except (OSError, TimeoutError):
                    return None
                try:
                    # Query (8, 2) MAC & Extended ID: [0x01, 0x00, 0x00, 0x00, 0x02, 0x08, 0x02]
                    frame = bytes([0x01, 0x00, 0x00, 0x00, 0x02, 0x08, 0x02])
                    writer.write(frame)
                    await writer.drain()
                    resp = await asyncio.wait_for(reader.read(64), timeout=0.8)
                    if len(resp) >= 13 and resp[5] == 0x08 and resp[6] == 0x02:
                        mac = ":".join(f"{b:02x}" for b in resp[7:13])
                        if mac.lower() == target_mac.lower():
                            return ip
                except (OSError, TimeoutError):
                    pass
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
                return None

        results = await asyncio.gather(
            *(_probe(str(ip)) for ip in network.hosts() if str(ip) != self._host)
        )
        return next((ip for ip in results if ip is not None), None)

    async def _ip_watchdog(self) -> None:
        """If the thermostat is disconnected for >90s, rediscover its IP by MAC."""
        consecutive_down = 0
        while True:
            await asyncio.sleep(30)
            if getattr(self.client, "protocol", None) is not None:
                consecutive_down = 0
                continue
            consecutive_down += 1
            if consecutive_down < 3:
                continue
            target_mac = self.data.get(Attribute.MAC_ADDRESS)
            if not target_mac:
                continue
            new_ip = await self._rediscover_host_by_mac(str(target_mac))
            if new_ip and new_ip != self._host:
                _LOGGER.warning(
                    "AprilAire thermostat IP changed from %s to %s (matched MAC %s); updating config",
                    self._host,
                    new_ip,
                    target_mac,
                )
                self._host = new_ip
                self.client.host = new_ip
                if self.config_entry is not None:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={**self.config_entry.data, "host": new_ip},
                    )
                consecutive_down = 0

    async def start_listen(self) -> None:
        """Start listening for data."""
        await self.client.start_listen()
        if self._sensor_poll_task is None or self._sensor_poll_task.done():
            self._sensor_poll_task = asyncio.create_task(self._periodic_sensor_poll())
        if self._ip_watchdog_task is None or self._ip_watchdog_task.done():
            self._ip_watchdog_task = asyncio.create_task(self._ip_watchdog())

    def stop_listen(self) -> None:
        """Stop listening for data."""
        if self._sensor_poll_task and not self._sensor_poll_task.done():
            self._sensor_poll_task.cancel()
        if self._ip_watchdog_task and not self._ip_watchdog_task.done():
            self._ip_watchdog_task.cancel()
        self.client.stop_listen()

    async def wait_for_ready(
        self, ready_callback: Callable[[bool], Awaitable[None]]
    ) -> bool:
        """Wait for the client to be ready and query extended 6003 attributes."""

        if not self.data or Attribute.MAC_ADDRESS not in self.data:
            await self.client.read_mac_address()

            data = await self.client.wait_for_response(
                FunctionalDomain.IDENTIFICATION, 2, WAIT_TIMEOUT
            )

            if not data or Attribute.MAC_ADDRESS not in data:
                _LOGGER.error("Missing MAC address")
                await ready_callback(False)

                return False

        if not self.data or Attribute.THERMOSTAT_MODES not in self.data:
            await self.client.read_thermostat_iaq_available()

            await self.client.wait_for_response(
                FunctionalDomain.CONTROL, 7, WAIT_TIMEOUT
            )

        if (
            not self.data
            or Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS not in self.data
        ):
            await self.client.read_sensors()

            await self.client.wait_for_response(
                FunctionalDomain.SENSORS, 2, WAIT_TIMEOUT
            )

        # Queue and wait for extended 6003 attributes via paced RS-485 queue
        for domain, attr in (
            (FunctionalDomain.IDENTIFICATION, 4),  # Location & Thermostat Name ("Whole Home")
            (FunctionalDomain.SETUP, 10),          # Zone System Settings (Zone count, DAT limits)
            (FunctionalDomain.SCHEDULING, 5),      # Heat Blast state (spec 3.5)
            (FunctionalDomain.SENSORS, 1),         # Full Sensor Values array (LAT, ODT, Built-in)
        ):
            await self._send_raw_read(domain, attr)
            await self.client.wait_for_response(domain, attr, 10)

        await self.client.read_thermostat_status()
        await self.client.wait_for_response(FunctionalDomain.STATUS, 6, 10)

        await self.client.read_iaq_status()
        await self.client.wait_for_response(FunctionalDomain.STATUS, 7, 10)

        await self.client.read_control()
        await self.client.wait_for_response(FunctionalDomain.CONTROL, 1, 10)

        # Ensure critical IAQ and LAT attributes are populated; retry once if missing
        if Attribute.HUMIDIFICATION_AVAILABLE not in self.data:
            await asyncio.sleep(0.35)
            await self.client.read_thermostat_iaq_available()
            await self.client.wait_for_response(FunctionalDomain.CONTROL, 7, 5)

        if Attribute.LAT_SENSOR_STATUS not in self.data:
            await asyncio.sleep(0.35)
            await self._send_raw_read(FunctionalDomain.SENSORS, 1)
            await self.client.wait_for_response(FunctionalDomain.SENSORS, 1, 5)

        if getattr(self.client, "protocol", None) is not None:
            try:
                await self.client.protocol.configure_cos()
            except Exception:
                _LOGGER.debug("Failed to configure COS", exc_info=True)

        if self.config_entry is not None and (info := self.create_device_info(self.data)):
            dr.async_get(self.hass).async_get_or_create(
                config_entry_id=self.config_entry.entry_id, **info
            )

        await ready_callback(True)

        return True

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
            device_info["model"] = EXTENDED_MODELS.get(
                model_number, f"Unknown ({model_number})"
            )

        firmware_major_revision = data.get(Attribute.FIRMWARE_MAJOR_REVISION)
        firmware_minor_revision = data.get(Attribute.FIRMWARE_MINOR_REVISION)
        if firmware_major_revision is not None:
            device_info["sw_version"] = (
                str(firmware_major_revision)
                if firmware_minor_revision is None
                else f"{firmware_major_revision}.{firmware_minor_revision:02}"
            )

        return device_info
