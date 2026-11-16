"""Base functionality for Aprilaire entities."""

import logging
from typing import override

from homeassistant.helpers.update_coordinator import BaseCoordinatorEntity
from pyaprilaire.const import Attribute

from .coordinator import AprilaireCoordinator

_LOGGER = logging.getLogger(__name__)


class BaseAprilaireEntity(BaseCoordinatorEntity[AprilaireCoordinator]):
    """Base for Aprilaire entities."""

    _attr_available = False
    _attr_has_entity_name = True

    def __init__(self, coordinator: AprilaireCoordinator, unique_id: str | None) -> None:
        """Initialize the entity."""

        super().__init__(coordinator)

        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{unique_id}_{self.translation_key}"

    @property
    def available(self) -> bool:
        """Only a connected transport can provide available controls."""
        return bool(
            self.coordinator.data.get(Attribute.CONNECTED)
        ) and not self.coordinator.data.get(Attribute.STOPPED, False)

    @override
    async def async_update(self) -> None:
        """Implement abstract base method."""
