"""The Aprilaire select component (with standalone Furnace Fan Mode control)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast, override

from pyaprilaire.const import Attribute

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AprilaireConfigEntry, AprilaireCoordinator
from .entity import BaseAprilaireEntity

AIR_CLEANING_EVENT_MAP = {0: "off", 3: "event_clean", 4: "allergies"}
AIR_CLEANING_MODE_MAP = {0: "off", 1: "constant_clean", 2: "automatic"}
FRESH_AIR_EVENT_MAP = {0: "off", 2: "3hour", 3: "24hour"}
FRESH_AIR_MODE_MAP = {0: "off", 1: "automatic"}
FURNACE_FAN_MODE_MAP = {2: "auto", 1: "on", 3: "circulate"}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AprilaireConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Aprilaire select devices."""

    coordinator = config_entry.runtime_data

    assert config_entry.unique_id is not None

    descriptions: list[AprilaireSelectDescription] = []

    if coordinator.data.get(Attribute.AIR_CLEANING_AVAILABLE) == 1:
        descriptions.extend(
            [
                AprilaireSelectDescription(
                    key="air_cleaning_event",
                    translation_key="air_cleaning_event",
                    options_map=AIR_CLEANING_EVENT_MAP,
                    event_value_key=Attribute.AIR_CLEANING_EVENT,
                    mode_value_key=Attribute.AIR_CLEANING_MODE,
                    is_event=True,
                    select_option_fn=coordinator.client.set_air_cleaning,
                ),
                AprilaireSelectDescription(
                    key="air_cleaning_mode",
                    translation_key="air_cleaning_mode",
                    options_map=AIR_CLEANING_MODE_MAP,
                    event_value_key=Attribute.AIR_CLEANING_EVENT,
                    mode_value_key=Attribute.AIR_CLEANING_MODE,
                    is_event=False,
                    select_option_fn=coordinator.client.set_air_cleaning,
                ),
            ]
        )

    if coordinator.data.get(Attribute.VENTILATION_AVAILABLE) == 1:
        descriptions.extend(
            [
                AprilaireSelectDescription(
                    key="fresh_air_event",
                    translation_key="fresh_air_event",
                    options_map=FRESH_AIR_EVENT_MAP,
                    event_value_key=Attribute.FRESH_AIR_EVENT,
                    mode_value_key=Attribute.FRESH_AIR_MODE,
                    is_event=True,
                    select_option_fn=coordinator.client.set_fresh_air,
                ),
                AprilaireSelectDescription(
                    key="fresh_air_mode",
                    translation_key="fresh_air_mode",
                    options_map=FRESH_AIR_MODE_MAP,
                    event_value_key=Attribute.FRESH_AIR_EVENT,
                    mode_value_key=Attribute.FRESH_AIR_MODE,
                    is_event=False,
                    select_option_fn=coordinator.client.set_fresh_air,
                ),
            ]
        )

    entities: list[SelectEntity] = [
        AprilaireSelectEntity(coordinator, description, config_entry.unique_id)
        for description in descriptions
    ]
    # Always expose standalone Furnace / AC Blower Fan Mode select on Device Controls
    entities.append(AprilaireFanModeSelectEntity(coordinator, config_entry.unique_id))

    async_add_entities(entities)


@dataclass(frozen=True, kw_only=True)
class AprilaireSelectDescription(SelectEntityDescription):
    """Class describing Aprilaire select entities."""

    options_map: dict[int, str]
    event_value_key: str
    mode_value_key: str
    is_event: bool
    select_option_fn: Callable[[int, int], Awaitable]


class AprilaireSelectEntity(BaseAprilaireEntity, SelectEntity):
    """Base select entity for Aprilaire."""

    entity_description: AprilaireSelectDescription

    def __init__(
        self,
        coordinator: AprilaireCoordinator,
        description: AprilaireSelectDescription,
        unique_id: str,
    ) -> None:
        """Initialize a select for an Aprilaire device."""

        self.entity_description = description
        self.values_map = {v: k for k, v in description.options_map.items()}

        super().__init__(coordinator, unique_id)

        self._attr_options = list(description.options_map.values())

    @property
    @override
    def current_option(self) -> str:
        """Get the current option."""

        if self.entity_description.is_event:
            value_key = self.entity_description.event_value_key
        else:
            value_key = self.entity_description.mode_value_key

        current_value = int(self.coordinator.data.get(value_key, 0))

        return self.entity_description.options_map.get(current_value, "off")

    @override
    async def async_select_option(self, option: str) -> None:
        """Set the current option."""

        if self.entity_description.is_event:
            event_value = self.values_map[option]

            mode_value = cast(
                int, self.coordinator.data.get(self.entity_description.mode_value_key)
            )
        else:
            mode_value = self.values_map[option]

            event_value = cast(
                int, self.coordinator.data.get(self.entity_description.event_value_key)
            )

        await self.entity_description.select_option_fn(mode_value, event_value)


class AprilaireFanModeSelectEntity(BaseAprilaireEntity, SelectEntity):
    """Standalone Furnace / AC Blower Fan Mode control (Auto / On / Circulate)."""

    _attr_icon = "mdi:fan"

    def __init__(self, coordinator: AprilaireCoordinator, unique_id: str) -> None:
        """Initialize the furnace fan mode select entity."""
        self.entity_description = SelectEntityDescription(
            key="fan_mode",
            translation_key="fan_mode",
        )
        self._values_map = {v: k for k, v in FURNACE_FAN_MODE_MAP.items()}
        super().__init__(coordinator, unique_id)
        self._attr_options = list(FURNACE_FAN_MODE_MAP.values())

    @property
    @override
    def current_option(self) -> str | None:
        """Return the current furnace fan mode."""
        raw_mode = self.coordinator.data.get(Attribute.FAN_MODE)
        if raw_mode is None:
            return None
        return FURNACE_FAN_MODE_MAP.get(int(raw_mode))

    @override
    async def async_select_option(self, option: str) -> None:
        """Set the furnace/AC blower fan mode (1=On, 2=Auto, 3=Circulate)."""
        if option not in self._values_map:
            raise ValueError(f"Unsupported fan mode option: {option}")
        await self.coordinator.async_set_fan_mode(self._values_map[option])
