"""Entities whose data arrives after setup must still be created.

At an HA restart the 6003 can be slow to answer, so initialization finishes
with reads timed out. Platforms that only checked ``coordinator.data`` once
at setup never created those entities, and HA kept showing their registry
entries as restored placeholders ("unavailable").
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pyaprilaire.const import Attribute

from custom_components.aprilaire import humidifier, select, sensor, switch
from custom_components.aprilaire.entity import async_add_entities_when_ready
from custom_components.aprilaire.protocol import ATTR_HEAT_BLAST, ATTR_ZONE_COUNT


class FakeCoordinator:
    """Just enough of AprilaireCoordinator for platform setup."""

    def __init__(self, data=None):
        self.data = dict(data or {Attribute.CONNECTED: True})
        self.device_info = None
        self.client = SimpleNamespace(
            set_air_cleaning=Mock(),
            set_fresh_air=Mock(),
            set_humidification_setpoint=Mock(),
            set_dehumidification_setpoint=Mock(),
        )
        self.listeners = []

    def async_add_listener(self, update_callback, context=None):
        self.listeners.append(update_callback)

        def remove():
            if update_callback in self.listeners:
                self.listeners.remove(update_callback)

        return remove

    def push(self, **data):
        self.data.update(data)
        for listener in list(self.listeners):
            listener()


class FakeEntry:
    unique_id = "b4:82:55:00:00:01"

    def __init__(self, coordinator):
        self.runtime_data = coordinator
        self.unloads = []

    def async_on_unload(self, func):
        self.unloads.append(func)

    def unload(self):
        for func in self.unloads:
            func()


def collect():
    added = []
    return added, lambda entities: added.extend(entities)


def keys(entities):
    return sorted(entity.entity_description.key for entity in entities)


def test_present_data_adds_immediately_and_leaves_no_listener():
    coordinator = FakeCoordinator({"x": 1})
    entry = FakeEntry(coordinator)
    added, add = collect()
    async_add_entities_when_ready(entry, coordinator, add, [(lambda d: "x" in d, lambda: ["e"])])
    assert added == ["e"]
    assert coordinator.listeners == []


def test_late_data_adds_once_then_stops_listening():
    coordinator = FakeCoordinator({})
    entry = FakeEntry(coordinator)
    added, add = collect()
    async_add_entities_when_ready(entry, coordinator, add, [(lambda d: "x" in d, lambda: ["e"])])
    assert added == []
    coordinator.push(other=1)
    assert added == []
    coordinator.push(x=1)
    coordinator.push(x=2)
    assert added == ["e"]
    assert coordinator.listeners == []


def test_unload_removes_pending_listener():
    coordinator = FakeCoordinator({})
    entry = FakeEntry(coordinator)
    added, add = collect()
    async_add_entities_when_ready(entry, coordinator, add, [(lambda d: "x" in d, lambda: ["e"])])
    entry.unload()
    coordinator.push(x=1)
    assert added == []
    assert coordinator.listeners == []


@pytest.mark.asyncio
async def test_heat_blast_switch_appears_when_state_arrives_late():
    coordinator = FakeCoordinator()
    entry = FakeEntry(coordinator)
    added, add = collect()
    await switch.async_setup_entry(None, entry, add)
    assert added == []
    coordinator.push(**{ATTR_HEAT_BLAST: 0})
    assert keys(added) == ["heat_blast"]


@pytest.mark.asyncio
async def test_sensors_appear_when_their_status_arrives_late():
    coordinator = FakeCoordinator()
    entry = FakeEntry(coordinator)
    added, add = collect()
    await sensor.async_setup_entry(None, entry, add)
    initial = keys(added)
    assert "indoor_temperature_controlling_sensor" not in initial
    assert "zone_count" not in initial
    coordinator.push(
        **{
            Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 0,
            Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 22.0,
            ATTR_ZONE_COUNT: 2,
        }
    )
    later = keys(added)
    assert "indoor_temperature_controlling_sensor" in later
    assert "zone_count" in later
    assert len(later) == len(set(later))


@pytest.mark.asyncio
async def test_humidifier_and_fresh_air_appear_when_availability_arrives_late():
    coordinator = FakeCoordinator()
    entry = FakeEntry(coordinator)
    humidifiers, add_humidifiers = collect()
    selects, add_selects = collect()
    await humidifier.async_setup_entry(None, entry, add_humidifiers)
    await select.async_setup_entry(None, entry, add_selects)
    assert humidifiers == []
    assert keys(selects) == ["fan_mode"]
    coordinator.push(**{Attribute.HUMIDIFICATION_AVAILABLE: 2, Attribute.VENTILATION_AVAILABLE: 1})
    assert keys(humidifiers) == ["humidifier"]
    assert keys(selects) == ["fan_mode", "fresh_air_event", "fresh_air_mode"]


def _poll_coordinator(data):
    from unittest.mock import AsyncMock

    from custom_components.aprilaire.coordinator import AprilaireCoordinator

    coordinator = object.__new__(AprilaireCoordinator)
    coordinator.data = data
    reads = []

    async def read(domain, attribute, timeout=5):
        reads.append((int(domain), attribute))

    coordinator.client = SimpleNamespace(
        connected=True,
        protocol=SimpleNamespace(read=read),
        read_thermostat_status=AsyncMock(),
        read_iaq_status=AsyncMock(),
    )
    return coordinator, reads


@pytest.mark.asyncio
async def test_poll_rereads_initialization_data_that_never_arrived(monkeypatch):
    from unittest.mock import AsyncMock

    from custom_components.aprilaire import coordinator as module

    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    coordinator, reads = _poll_coordinator({Attribute.MODEL_NUMBER: 28})
    await coordinator._poll_once()
    # SENSORS 1 always; then catch-up: SCHEDULING 5, SETUP 10, CONTROL 7, SENSORS 2.
    assert set(reads) == {(5, 1), (3, 5), (1, 10), (2, 7), (5, 2)}


@pytest.mark.asyncio
async def test_poll_skips_catch_up_once_data_is_present(monkeypatch):
    from unittest.mock import AsyncMock

    from custom_components.aprilaire import coordinator as module

    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    coordinator, reads = _poll_coordinator(
        {
            Attribute.MODEL_NUMBER: 28,
            ATTR_HEAT_BLAST: 0,
            ATTR_ZONE_COUNT: 2,
            Attribute.HUMIDIFICATION_AVAILABLE: 2,
            Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 0,
        }
    )
    await coordinator._poll_once()
    # Heat Blast keeps being refreshed; nothing else is re-read.
    assert set(reads) == {(5, 1), (3, 5)}


@pytest.mark.asyncio
async def test_poll_does_not_probe_6003_attributes_on_other_models(monkeypatch):
    from unittest.mock import AsyncMock

    from custom_components.aprilaire import coordinator as module

    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    coordinator, reads = _poll_coordinator(
        {
            Attribute.MODEL_NUMBER: 7,
            Attribute.HUMIDIFICATION_AVAILABLE: 0,
            Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 0,
        }
    )
    await coordinator._poll_once()
    assert set(reads) == {(5, 1)}
