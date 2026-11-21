"""The Aprilaire switch component (Heat Blast control via domain 3, attribute 5)."""

from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ATTR_HEAT_BLAST, AprilaireConfigEntry, AprilaireCoordinator
from .entity import BaseAprilaireEntity, async_add_entities_when_ready


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AprilaireConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Aprilaire switch entities."""
    coordinator = config_entry.runtime_data
    assert config_entry.unique_id is not None

    unique_id = config_entry.unique_id
    async_add_entities_when_ready(
        config_entry,
        coordinator,
        async_add_entities,
        [
            (
                lambda data: ATTR_HEAT_BLAST in data,
                lambda: [AprilaireHeatBlastSwitch(coordinator, unique_id)],
            )
        ],
    )


class AprilaireHeatBlastSwitch(BaseAprilaireEntity, SwitchEntity):
    """Switch entity for AprilAire Heat Blast (spec 2.8)."""

    _attr_icon = "mdi:fire-alert"

    def __init__(self, coordinator: AprilaireCoordinator, unique_id: str) -> None:
        """Initialize the Heat Blast switch."""
        self.entity_description = SwitchEntityDescription(
            key="heat_blast",
            translation_key="heat_blast",
        )
        super().__init__(coordinator, unique_id)

    @property
    @override
    def is_on(self) -> bool | None:
        """Return True if Heat Blast is currently active."""
        val = self.coordinator.data.get(ATTR_HEAT_BLAST)
        if val is None:
            return None
        return int(val) == 1

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Activate Heat Blast."""
        await self.coordinator.async_set_heat_blast(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Deactivate Heat Blast."""
        await self.coordinator.async_set_heat_blast(False)
