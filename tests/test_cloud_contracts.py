"""Behavioral regression tests with synthetic thermostat payloads."""

from dataclasses import replace

import pytest

from custom_components.aprilaire_cloud.models import DeviceRecord, HierarchyDevice
from custom_components.aprilaire_cloud.profiles import (
    CommandNotSupportedError,
    CommandValidationError,
    SetThermostatSetpoints,
)
from custom_components.aprilaire_cloud.profiles.thermostat import ThermostatProfile


def thermostat(model="6003", mode="heat", heat=21.0, cool=22.0):
    return DeviceRecord(
        hierarchy=HierarchyDevice("device-one", "location-one", "Synthetic", access="manage"),
        device_status={"model": model},
        device_settings={
            "thermostatPZ1": {"mode": mode, "fan": "auto", "heat": heat, "cool": cool}
        },
        device_setup={"type": "thermostat", "thermostat": {"temperatureUnit": "C"}},
        profile_key="thermostat",
        supported=True,
    )


def test_unknown_model_cannot_gain_writes_from_numeric_json():
    with pytest.raises(CommandNotSupportedError):
        ThermostatProfile().encode_command(
            thermostat("unverified"), SetThermostatSetpoints("PZ1", heat=22)
        )


def test_partial_auto_update_moves_companion_to_keep_deadband():
    # Heat 21 -> 22 with cool at 22: cool moves up to the nearest grid value
    # that keeps the 3F deadband (2.0C on the 0.5C grid; 1.5C is only 2.7F).
    result = ThermostatProfile().encode_command(
        thermostat(mode="auto"), SetThermostatSetpoints("PZ1", heat=22)
    )
    assert result.payload == {"thermostatPZ1": {"heat": 22.0, "cool": 24.0}}


def test_auto_cool_change_moves_heat_down():
    result = ThermostatProfile().encode_command(
        thermostat(mode="auto", heat=21, cool=24), SetThermostatSetpoints("PZ1", heat=21, cool=22)
    )
    assert result.payload == {"thermostatPZ1": {"heat": 20.0, "cool": 22.0}}


def test_auto_both_sides_changed_into_deadband_is_rejected():
    with pytest.raises(CommandValidationError):
        ThermostatProfile().encode_command(
            thermostat(mode="auto", heat=20, cool=25),
            SetThermostatSetpoints("PZ1", heat=22, cool=22.5),
        )


def test_companion_cannot_be_pushed_past_its_limit():
    # Cool is already at the top of its range, so heat cannot rise into the deadband.
    with pytest.raises(CommandValidationError):
        ThermostatProfile().encode_command(
            thermostat(mode="auto", heat=30, cool=33.5), SetThermostatSetpoints("PZ1", heat=33)
        )


def test_8920w_heat_side_boundary_from_issue_8_capture():
    # Live 8920W capture (billda/ha-aprilaire-cloud#8): heat 70F -> 73F with
    # cool at 75F. The thermostat stores 75F as 23.88. Heat must stay at
    # the requested 73F and cool move to 76F.
    record = replace(
        thermostat("8920W", mode="auto", heat=21.11, cool=23.88),
        device_setup={"type": "thermostat", "thermostat": {"temperatureUnit": "F"}},
    )
    result = ThermostatProfile().encode_command(
        record, SetThermostatSetpoints("PZ1", heat=22.78, cool=23.89)
    )
    assert result.payload == {"thermostatPZ1": {"heat": 22.78, "cool": 24.44}}


def test_8920w_cool_side_boundary_from_issue_8_capture():
    # Same capture: cool 75F -> 72F with heat at 70F; heat moves to 69F.
    record = replace(
        thermostat("8920W", mode="auto", heat=21.11, cool=23.88),
        device_setup={"type": "thermostat", "thermostat": {"temperatureUnit": "F"}},
    )
    result = ThermostatProfile().encode_command(
        record, SetThermostatSetpoints("PZ1", heat=21.11, cool=22.22)
    )
    assert result.payload == {"thermostatPZ1": {"heat": 20.56, "cool": 22.22}}


def test_single_heat_mode_preserves_crossed_inactive_setpoint():
    result = ThermostatProfile().encode_command(
        thermostat(cool=20), SetThermostatSetpoints("PZ1", heat=22.5)
    )
    assert result.payload == {"thermostatPZ1": {"heat": 22.5, "cool": 20}}


def test_8920w_preserves_whole_fahrenheit_grid():
    record = replace(
        thermostat("8920W", cool=24),
        device_setup={"type": "thermostat", "thermostat": {"temperatureUnit": "F"}},
    )
    result = ThermostatProfile().encode_command(record, SetThermostatSetpoints("PZ1", heat=21.11))
    assert result.payload["thermostatPZ1"]["heat"] == 21.11


def test_stage_two_cooling_is_not_reported_as_fan():
    record = replace(
        thermostat(),
        status_payloads={"thermostatPZ1": {"coolingStatus": "stage2", "isFanOn": True}},
    )
    assert ThermostatProfile().normalize(record).zones["PZ1"].operating_state == "cooling"


def test_switch_to_auto_rejects_crossed_existing_pair():
    from custom_components.aprilaire_cloud.profiles import SetThermostatMode

    with pytest.raises(CommandValidationError):
        ThermostatProfile().encode_command(
            thermostat(heat=23, cool=21), SetThermostatMode("PZ1", mode="auto")
        )


def test_incomplete_setpoint_contract_stays_read_only():
    record = replace(thermostat(), device_settings={"thermostatPZ1": {"mode": "heat", "heat": 21}})
    with pytest.raises(CommandNotSupportedError):
        ThermostatProfile().encode_command(record, SetThermostatSetpoints("PZ1", heat=22))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 50])
def test_nonfinite_and_out_of_range_setpoints_are_rejected(value):
    with pytest.raises(CommandValidationError):
        ThermostatProfile().encode_command(thermostat(), SetThermostatSetpoints("PZ1", heat=value))


def test_read_only_account_cannot_write():
    from custom_components.aprilaire_cloud.profiles import CommandAccessError

    record = thermostat()
    record = replace(record, hierarchy=replace(record.hierarchy, access="view"))
    with pytest.raises(CommandAccessError):
        ThermostatProfile().encode_command(record, SetThermostatSetpoints("PZ1", heat=22))


@pytest.mark.parametrize("scale", [{}, [], None, 12])
def test_malformed_unit_evidence_is_read_only(scale):
    record = thermostat("8920W")
    record = replace(
        record,
        device_setup={},
        device_settings={"thermostatPZ1": {"mode": "heat", "heat": 21, "cool": 24, "scale": scale}},
    )
    with pytest.raises(CommandNotSupportedError):
        ThermostatProfile().encode_command(record, SetThermostatSetpoints("PZ1", heat=22))


def test_only_6003_setpoint_mismatches_remain_inconclusive():
    command = SetThermostatSetpoints("PZ1", heat=22)
    profile = ThermostatProfile()
    assert profile.mismatch_is_rejection(command, record=thermostat("8920W"))
    assert not profile.mismatch_is_rejection(command, record=thermostat("6003"))


def test_8920w_deadband_is_kept_in_single_mode_by_moving_cool():
    # The 8920W enforces its deadband in every mode, so the inactive cool
    # setpoint moves rather than the write being refused.
    record = replace(
        thermostat("8920W", mode="heat", heat=21, cool=22), device_setup={"temperatureUnit": "F"}
    )
    result = ThermostatProfile().encode_command(record, SetThermostatSetpoints("PZ1", heat=23))
    assert result.payload == {"thermostatPZ1": {"heat": 22.78, "cool": 24.44}}


def test_settings_scale_is_explicit_unit_evidence_for_8920w():
    record = thermostat("8920W", cool=24)
    settings = {"thermostatPZ1": {"mode": "heat", "heat": 20, "cool": 24, "scale": "F"}}
    record = replace(record, device_setup={}, device_settings=settings)
    result = ThermostatProfile().encode_command(record, SetThermostatSetpoints("PZ1", heat=21.11))
    assert result.payload["thermostatPZ1"]["heat"] == 21.11


def test_auto_requires_numeric_companion_before_changing_mode():
    from custom_components.aprilaire_cloud.profiles import SetThermostatMode

    record = replace(thermostat(), device_settings={"thermostatPZ1": {"mode": "heat", "heat": 21}})
    with pytest.raises(CommandNotSupportedError):
        ThermostatProfile().encode_command(record, SetThermostatMode("PZ1", mode="auto"))
