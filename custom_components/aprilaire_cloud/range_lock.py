"""Optional, coordinator-owned temperature policies for confirmed Celsius zones."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from math import ceil, isfinite
from time import monotonic

from .profiles import SetThermostatSetpoints
from .profiles.thermostat import ThermostatProfile

_LOGGER = logging.getLogger(__name__)
DEFAULT_MIN_C = 18.0
DEFAULT_MAX_C = 23.0


def clamp_command(record, zone_key, minimum, maximum):
    """Clamp active endpoints, preserving a conservative 3°F auto deadband."""
    state = ThermostatProfile().normalize(replace(record, pending_device_settings={}))
    zone = state.zones.get(zone_key)
    if zone is None or zone.temperature_unit != "C":
        return None
    heat, cool = zone.heat_setpoint, zone.cool_setpoint
    new_heat = min(maximum, max(minimum, heat)) if heat is not None else None
    new_cool = min(maximum, max(minimum, cool)) if cool is not None else None
    if zone.raw_mode == "auto" and heat is not None and cool is not None:
        gap = ceil((3 / 1.8) * 2) / 2
        if maximum - minimum < gap:
            return None
        if new_cool - new_heat < gap:
            new_heat = min(new_heat, maximum - gap)
            new_cool = max(new_cool, new_heat + gap)
        if (new_heat, new_cool) != (heat, cool):
            return SetThermostatSetpoints(zone_key, heat=new_heat, cool=new_cool)
    elif zone.raw_mode == "heat" and new_heat != heat:
        return SetThermostatSetpoints(zone_key, heat=new_heat)
    elif zone.raw_mode == "cool" and new_cool != cool:
        return SetThermostatSetpoints(zone_key, cool=new_cool)
    return None


class RangeLockManager:
    """Coalesce one bounded attempt per zone, independent of entity listeners."""

    def __init__(self, coordinator, minimum=DEFAULT_MIN_C, maximum=DEFAULT_MAX_C):
        if (
            not all(isfinite(value) for value in (minimum, maximum))
            or not 10 <= minimum <= 30
            or not 12 <= maximum <= 32
            or maximum - minimum < 2
            or minimum * 2 != round(minimum * 2)
            or maximum * 2 != round(maximum * 2)
        ):
            raise ValueError("Temperature range requires half-degree bounds and a 2°C span")
        self.coordinator = coordinator
        self.minimum = minimum
        self.maximum = maximum
        self._enabled = set()
        self.tasks = {}
        self._next_attempt = {}
        self.errors = {}
        self._stopped = False

    def enabled(self, device_id, zone):
        return (device_id, zone) in self._enabled

    def set_enabled(self, device_id, zone, enabled):
        key = (device_id, zone)
        if enabled:
            self._enabled.add(key)
            self.schedule()
        else:
            self._enabled.discard(key)
            if task := self.tasks.get(key):
                task.cancel()
            self.errors.pop(key, None)

    def schedule(self):
        if self._stopped:
            return
        for device_id, zone in self._enabled:
            key = (device_id, zone)
            record = self.coordinator._devices.get(device_id)
            if key in self.tasks or monotonic() < self._next_attempt.get(key, 0):
                continue
            if (
                record is None
                or record.hierarchy.access != "manage"
                or not self.coordinator.device_is_available(device_id)
            ):
                continue
            if record.device_status.get("model") not in {"6003", "6003_GS"}:
                continue
            command = clamp_command(record, zone, self.minimum, self.maximum)
            if command is None:
                continue
            self._next_attempt[key] = monotonic() + 60
            task = self.coordinator.hass.async_create_task(self._attempt(key, command))
            self.tasks[key] = task
            task.add_done_callback(lambda _, key=key: self.tasks.pop(key, None))

    async def _attempt(self, key, command):
        try:
            await self.coordinator.async_execute_command(key[0], command)
            self.errors.pop(key, None)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            self.errors[key] = type(err).__name__
            _LOGGER.warning(
                "Temperature range correction failed (%s); waiting before retry",
                type(err).__name__,
            )

    async def async_stop(self):
        self._stopped = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
