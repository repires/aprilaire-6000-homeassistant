"""Switch platform for on/off-only AprilAire capabilities."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .climate import SZ2_LOCK_MAX_C, SZ2_LOCK_MIN_C
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
    NormalizedThermostatState,
    SetDehumidifierPower,
    SetThermostatSetpoints,
    get_profile,
)
from .vendor import AprilaireCloudApiError, AprilaireCloudRateLimitError


async def async_setup_entry(hass, entry: AprilaireCloudConfigEntry, async_add_entities) -> None:
    """Set up honest on/off-only control entities and Zone 2 temperature range lock."""
    coordinator = entry.runtime_data.coordinator
    if not hasattr(coordinator, "sz2_temp_lock_enabled"):
        coordinator.sz2_temp_lock_enabled = True

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
        if "thermostat_sz2" in desc.climate_keys:
            yield DynamicEntityDescriptor(
                unique_id=f"{device_id}_sz2_temp_lock",
                factory=AprilaireZone2TempLockSwitch,
                args=(coordinator, device_id),
            )

    setup_dynamic_platform_entities(
        entry,
        async_add_entities,
        _descriptors_for_device,
    )


class AprilaireZone2TempLockSwitch(AprilaireCloudEntity, SwitchEntity, RestoreEntity):
    """Switch to enforce 18.0°C - 23.0°C temperature bounds on Zone 2 (SZ2 / Basement)."""

    _attr_icon = "mdi:thermometer-lock"
    _attr_name = "Basement Temp Lock (18–23°C)"

    def __init__(
        self,
        coordinator: AprilaireCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the Zone 2 temperature lock switch."""
        super().__init__(coordinator, device_id, "sz2_temp_lock")

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup (default ON)."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self.coordinator.sz2_temp_lock_enabled = last_state.state == "on"
        else:
            self.coordinator.sz2_temp_lock_enabled = True

    @property
    def is_on(self) -> bool:
        """Return True if the 18-23°C lock is active."""
        return bool(getattr(self.coordinator, "sz2_temp_lock_enabled", True))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return lock range metadata."""
        attrs = dict(super().extra_state_attributes)
        attrs.update(
            {
                "min_temp_c": SZ2_LOCK_MIN_C,
                "max_temp_c": SZ2_LOCK_MAX_C,
                "enforced_zone": "SZ2 (Basement)",
            }
        )
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the 18-23°C lock and immediately clamp SZ2 if out of bounds."""
        self.coordinator.sz2_temp_lock_enabled = True
        self.coordinator.async_update_listeners()
        normalized = cast(NormalizedThermostatState | None, self.normalized_state)
        if normalized and (zone := normalized.zones.get("SZ2")):
            clamped_heat = None
            clamped_cool = None
            if zone.heat_setpoint is not None and not (
                SZ2_LOCK_MIN_C <= zone.heat_setpoint <= SZ2_LOCK_MAX_C
            ):
                clamped_heat = max(SZ2_LOCK_MIN_C, min(SZ2_LOCK_MAX_C, zone.heat_setpoint))
            if zone.cool_setpoint is not None and not (
                SZ2_LOCK_MIN_C <= zone.cool_setpoint <= SZ2_LOCK_MAX_C
            ):
                clamped_cool = max(SZ2_LOCK_MIN_C, min(SZ2_LOCK_MAX_C, zone.cool_setpoint))
            if clamped_heat is not None or clamped_cool is not None:
                await self.coordinator.async_execute_command(
                    self._device_id,
                    SetThermostatSetpoints(
                        zone="SZ2", heat=clamped_heat, cool=clamped_cool
                    ),
                )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the 18-23°C lock."""
        self.coordinator.sz2_temp_lock_enabled = False
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
