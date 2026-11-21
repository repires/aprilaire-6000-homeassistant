"""Base functionality for Aprilaire entities."""

import logging
from collections.abc import Callable, Iterable
from typing import Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import BaseCoordinatorEntity
from pyaprilaire.const import Attribute

from .coordinator import AprilaireCoordinator

_LOGGER = logging.getLogger(__name__)

type EntityCandidate = tuple[Callable[[dict[str, Any]], bool], Callable[[], Iterable[Entity]]]


@callback
def async_add_entities_when_ready(
    config_entry: ConfigEntry,
    coordinator: AprilaireCoordinator,
    async_add_entities: Callable[[list[Entity]], None],
    candidates: Iterable[EntityCandidate],
) -> None:
    """Add each candidate's entities once its predicate holds for the data.

    Initialization can finish with reads timed out (the 6003 is slow right
    after an HA restart), so data that gates an entity may only arrive later
    through COS or polling. Checking once at setup would leave those entities
    uncreated until the next reload.
    """
    pending = list(candidates)
    remove_listener: Callable[[], None] | None = None

    @callback
    def _add_ready() -> None:
        nonlocal remove_listener
        ready = [candidate for candidate in pending if candidate[0](coordinator.data)]
        if not ready:
            return
        for candidate in ready:
            pending.remove(candidate)
        entities = [entity for _, factory in ready for entity in factory()]
        if entities:
            async_add_entities(entities)
        if not pending and remove_listener is not None:
            remove_listener()
            remove_listener = None

    _add_ready()
    if pending:
        remove_listener = coordinator.async_add_listener(_add_ready)
        config_entry.async_on_unload(lambda: remove_listener() if remove_listener else None)


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
