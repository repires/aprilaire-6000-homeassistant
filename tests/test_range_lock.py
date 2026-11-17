"""Range policy is opt-in, independent, coalesced, and mode-aware."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.test_cloud_contracts import thermostat


def test_auto_clamping_preserves_deadband_inside_interval():
    from custom_components.aprilaire_cloud.range_lock import clamp_command

    result = clamp_command(thermostat(mode="auto", heat=24, cool=26), "PZ1", 18, 23)
    assert result.heat == 21
    assert result.cool == 23


@pytest.mark.asyncio
async def test_independent_default_off_and_coalesced_retry(monkeypatch):
    from custom_components.aprilaire_cloud.range_lock import RangeLockManager

    clock = [0.0]
    monkeypatch.setattr("custom_components.aprilaire_cloud.range_lock.monotonic", lambda: clock[0])
    record = thermostat(heat=25)
    coordinator = SimpleNamespace(
        _devices={"one": record, "two": record},
        device_is_available=lambda _: True,
        async_execute_command=AsyncMock(side_effect=RuntimeError("offline")),
        hass=SimpleNamespace(async_create_task=asyncio.create_task),
    )
    manager = RangeLockManager(coordinator)
    assert not manager.enabled("one", "PZ1")
    manager.set_enabled("one", "PZ1", True)
    for _ in range(10):
        manager.schedule()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert coordinator.async_execute_command.await_count == 1
    assert not manager.enabled("two", "PZ1")
    manager.schedule()
    await asyncio.sleep(0)
    assert coordinator.async_execute_command.await_count == 1
    clock[0] = 61
    manager.schedule()
    await asyncio.sleep(0)
    assert coordinator.async_execute_command.await_count == 2
    await manager.async_stop()
    assert not manager.tasks


def test_single_mode_does_not_clamp_inactive_endpoint():
    from custom_components.aprilaire_cloud.range_lock import clamp_command

    result = clamp_command(thermostat(heat=24, cool=16), "PZ1", 18, 23)
    assert result.heat == 23
    assert result.cool is None


@pytest.mark.asyncio
async def test_disabled_or_unavailable_policy_never_writes():
    from custom_components.aprilaire_cloud.range_lock import RangeLockManager

    coordinator = SimpleNamespace(
        _devices={"one": thermostat(heat=25)},
        device_is_available=lambda _: False,
        async_execute_command=AsyncMock(),
        hass=SimpleNamespace(async_create_task=asyncio.create_task),
    )
    manager = RangeLockManager(coordinator)
    manager.set_enabled("one", "PZ1", True)
    manager.schedule()
    await asyncio.sleep(0)
    assert not manager.tasks
    coordinator.device_is_available = lambda _: True
    manager.set_enabled("one", "PZ1", False)
    manager.schedule()
    await asyncio.sleep(0)
    coordinator.async_execute_command.assert_not_awaited()
    await manager.async_stop()


@pytest.mark.parametrize(
    "minimum,maximum", [(18.2, 23), (18, 23.2), (23, 18), (22, 23), (float("nan"), 23)]
)
def test_unrepresentable_or_invalid_range_is_rejected(minimum, maximum):
    from custom_components.aprilaire_cloud.range_lock import RangeLockManager

    with pytest.raises(ValueError):
        RangeLockManager(None, minimum, maximum)
