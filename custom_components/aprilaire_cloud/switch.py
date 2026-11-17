"""Switch platform for on/off-only AprilAire capabilities."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import AprilaireCloudDataUpdateCoordinator
from .data import AprilaireCloudConfigEntry
from .entity import (
    AprilaireCloudEntity,
    DynamicEntityDescriptor,
    raise_ha_write_error,
    setup_dynamic_platform_entities,
)
from .profiles import (
    AprilaireCommandError,
    NormalizedDehumidifierState,
    SetDehumidifierPower,
    get_profile,
)
from .vendor import AprilaireCloudApiError, AprilaireCloudRateLimitError


async def async_setup_entry(hass, entry: AprilaireCloudConfigEntry, async_add_entities) -> None:
    """Set up honest on/off-only control entities and Zone 2 temperature range lock."""
    coordinator = entry.runtime_data.coordinator

    def _descriptors_for_device(device_id: str, device):
        profile = get_profile(device.profile_key)
        if profile is None:
            return
        desc = profile.entity_descriptions(device)
        if "dehumidifier_power" in desc.switch_keys:
            yield DynamicEntityDescriptor(
                unique_id=f"{device_id}_dehumidifier_power",
                factory=AprilaireDehumidifierPowerSwitch,
                args=(coordinator, device_id),
            )
        if (
            device.device_status.get("model") in {"6003", "6003_GS"}
            and device.hierarchy.access == "manage"
        ):
            for zone in ("SZ2", "SZ3"):
                if f"thermostat_{zone.lower()}" in desc.climate_keys:
                    yield DynamicEntityDescriptor(
                        unique_id=f"{device_id}_{zone.lower()}_temp_lock",
                        factory=AprilaireZone2TempLockSwitch,
                        args=(coordinator, device_id, zone),
                    )

    setup_dynamic_platform_entities(
        entry,
        async_add_entities,
        _descriptors_for_device,
    )


class AprilaireZone2TempLockSwitch(AprilaireCloudEntity, SwitchEntity, RestoreEntity):
    """Switch to enforce 18.0°C - 23.0°C temperature bounds on Zone 2 (SZ2 / Basement)."""

    _attr_icon = "mdi:thermometer-lock"

    def __init__(self, coordinator, device_id, zone="SZ2") -> None:
        self._zone_key = zone
        self._attr_name = f"{zone} temperature range lock"
        super().__init__(coordinator, device_id, f"{zone.lower()}_temp_lock")

    async def async_added_to_hass(self) -> None:
        """Restore this device's opt-in state before starting its policy."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        self.coordinator.range_locks.set_enabled(
            self._device_id,
            self._zone_key,
            last_state is not None and last_state.state == "on",
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.range_locks.enabled(self._device_id, self._zone_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        manager = self.coordinator.range_locks
        return {
            "min_temp_c": manager.minimum,
            "max_temp_c": manager.maximum,
            "enforced_zone": self._zone_key,
            "last_error": manager.errors.get((self._device_id, self._zone_key)),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.range_locks.set_enabled(self._device_id, self._zone_key, True)
        self.coordinator.async_update_listeners()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.range_locks.set_enabled(self._device_id, self._zone_key, False)
        self.coordinator.async_update_listeners()


class AprilaireDehumidifierPowerSwitch(AprilaireCloudEntity, SwitchEntity):
    """On/off control for a dehumidifier without a usable humidity target."""

    _attr_translation_key = "dehumidifier_power"

    def __init__(
        self,
        coordinator: AprilaireCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the on/off-only entity."""
        super().__init__(coordinator, device_id, "dehumidifier_power")

    @property
    def is_on(self) -> bool | None:
        """Return the normalized power state."""
        normalized = cast(NormalizedDehumidifierState | None, self.normalized_state)
        if normalized is None or normalized.mode not in {"on", "off"}:
            return None
        return normalized.mode == "on"

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the dehumidifier on."""
        await self._async_set_power(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the dehumidifier off."""
        await self._async_set_power(False)

    async def _async_set_power(self, enabled: bool) -> None:
        """Execute the profile-owned power command."""
        try:
            await self.coordinator.async_execute_command(
                self._device_id,
                SetDehumidifierPower(enabled=enabled),
            )
        except (
            AprilaireCommandError,
            AprilaireCloudRateLimitError,
            AprilaireCloudApiError,
        ) as err:
            raise_ha_write_error(err)
