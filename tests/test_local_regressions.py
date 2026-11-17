"""Source data must stay valid and independent of connection lifetime."""

from types import SimpleNamespace

from pyaprilaire.const import Attribute

from custom_components.aprilaire.coordinator import AprilaireCoordinator
from custom_components.aprilaire.entity import BaseAprilaireEntity


def test_disconnected_entity_does_not_keep_constructor_availability():
    coordinator = SimpleNamespace(data={Attribute.CONNECTED: True}, device_info=None)
    entity = BaseAprilaireEntity(coordinator, "synthetic")
    assert entity.available
    coordinator.data = {Attribute.CONNECTED: False, Attribute.RECONNECTING: True}
    assert not entity.available


def test_faulty_builtin_sensor_is_not_a_valid_fallback():
    coordinator = object.__new__(AprilaireCoordinator)
    data = {
        Attribute.MODEL_NUMBER: 28,
        Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 4,
        Attribute.BUILT_IN_TEMPERATURE_SENSOR_STATUS: 3,
        Attribute.BUILT_IN_TEMPERATURE_SENSOR_VALUE: 0,
    }
    result = coordinator._normalize_sensors(data)
    assert result[Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS] == 4


def test_repeated_builtin_updates_remain_fresh_without_overwriting_raw_status():
    coordinator = object.__new__(AprilaireCoordinator)
    coordinator._raw_data = {}
    coordinator.data = {}
    coordinator.config_entry = None
    coordinator.unique_id = None
    coordinator._listeners = {}
    coordinator.async_set_updated_data(
        {
            Attribute.MODEL_NUMBER: 28,
            Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 4,
            Attribute.BUILT_IN_TEMPERATURE_SENSOR_STATUS: 0,
            Attribute.BUILT_IN_TEMPERATURE_SENSOR_VALUE: 21,
        }
    )
    coordinator.async_set_updated_data({Attribute.BUILT_IN_TEMPERATURE_SENSOR_VALUE: 22})
    assert coordinator.data[Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE] == 22
    assert coordinator._raw_data[Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS] == 4
