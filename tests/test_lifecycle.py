"""Home Assistant coordinator teardown with the actual framework."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.aprilaire_cloud.coordinator import AprilaireCloudDataUpdateCoordinator


@pytest.mark.asyncio
async def test_cloud_shutdown_disables_framework_refresh_and_owned_policies(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(options={}, entry_id="synthetic", async_on_unload=Mock())
    coordinator = AprilaireCloudDataUpdateCoordinator(
        hass, config_entry=entry, client=SimpleNamespace(username="user@example.com")
    )
    coordinator.range_locks.tasks[("one", "SZ2")] = asyncio.create_task(asyncio.sleep(100))
    await coordinator.async_shutdown()
    assert coordinator._shutdown_requested
    assert not coordinator.range_locks.tasks
