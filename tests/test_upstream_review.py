"""Behaviour carried over from the pyaprilaire #126 and HA core #186563 reviews."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from pyaprilaire.const import Attribute, FunctionalDomain

from custom_components.aprilaire import mac_matches_entry, normalize_mac
from custom_components.aprilaire.coordinator import AprilaireCoordinator
from custom_components.aprilaire.protocol import (
    ATTR_HEAT_BLAST,
    COS_HEAT_BLAST_INDEX,
    PACED_FRAME_INTERVAL,
    UNPACED_FRAME_INTERVAL,
    AprilaireProtocol,
)


@pytest.mark.asyncio
async def test_cos_subscription_enables_heat_blast_and_keeps_other_channels():
    protocol = AprilaireProtocol(Mock())
    await protocol.configure_cos()
    packet = protocol.packet_queue.get_nowait()

    assert (packet.functional_domain, packet.attribute) == (FunctionalDomain.STATUS, 1)
    assert len(packet.raw_data) == 29
    assert packet.raw_data[COS_HEAT_BLAST_INDEX] == 1
    # Every other channel matches what pyaprilaire 0.9.1 subscribes to.
    expected = [
        1,
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        1,
        1,
        1,
        0,
        1,
        0,
        1,
        1,
        0,
        0,
        0,
        0,
        1,
        0,
        1,
        0,
        1,
        1,
        1,
        0,
        0,
    ]
    assert packet.raw_data == expected
    await protocol.async_close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "interval"),
    [(28, PACED_FRAME_INTERVAL), (7, UNPACED_FRAME_INTERVAL), (None, PACED_FRAME_INTERVAL)],
)
async def test_pacing_follows_identified_model(model, interval):
    protocol = AprilaireProtocol(AsyncMock())

    async def reply(domain, attribute, timeout=5):
        if (domain, attribute) == (FunctionalDomain.IDENTIFICATION, 2):
            if model is not None:
                protocol.data[Attribute.MODEL_NUMBER] = model
            return {Attribute.MAC_ADDRESS: "02:00:00:00:00:01"}
        return {}

    protocol.read = reply
    protocol.connection_made(Mock())
    await asyncio.wait_for(protocol.ready.wait(), 3)
    assert protocol.pacing == interval
    await protocol.async_close()


def _coordinator(read_back, connected=True):
    coordinator = object.__new__(AprilaireCoordinator)
    protocol = SimpleNamespace(_send_packet=AsyncMock(), read=AsyncMock(return_value=read_back))
    coordinator.client = SimpleNamespace(
        connected=connected,
        protocol=protocol,
        read_control=AsyncMock(),
        read_thermostat_status=AsyncMock(),
    )
    return coordinator, protocol


@pytest.mark.asyncio
async def test_heat_blast_write_is_confirmed_by_read_back():
    coordinator, protocol = _coordinator({ATTR_HEAT_BLAST: 1})
    await coordinator.async_set_heat_blast(True)
    assert protocol._send_packet.await_args.args[0].raw_data == [1]
    protocol.read.assert_awaited_once_with(FunctionalDomain.SCHEDULING, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("read_back", [{ATTR_HEAT_BLAST: 0}, None])
async def test_heat_blast_write_not_applied_raises(read_back):
    coordinator, _ = _coordinator(read_back)
    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_heat_blast(True)


@pytest.mark.asyncio
async def test_heat_blast_write_while_disconnected_raises():
    coordinator, protocol = _coordinator({ATTR_HEAT_BLAST: 1}, connected=False)
    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_heat_blast(True)
    protocol._send_packet.assert_not_awaited()


@pytest.mark.parametrize(
    ("stored", "padded"),
    [
        ("b4:82:55:0:1a:5", "b4:82:55:00:1a:05"),  # 0.9.1 dropped leading zeros
        ("0::3::4a::1::2::3", "00:03:4a:01:02:03"),  # 12 chars, regrouped by format_mac
        ("b4:82:55:00:1a:05", "b4:82:55:00:1a:05"),  # already padded (pyaprilaire 0.10)
    ],
)
def test_normalize_mac_matches_pyaprilaire_0_10_format(stored, padded):
    assert normalize_mac(stored) == padded


@pytest.mark.parametrize(
    "unique_id",
    ["b4:82:55:0:1a:5", "b4:82:55:00:1a:05"],
)
def test_entry_matches_before_and_after_core_migration(unique_id):
    # The 0.9.1 parser reports the unpadded form; the entry may hold either form.
    assert mac_matches_entry("b4:82:55:0:1a:5", unique_id)


def test_entry_rejects_a_different_thermostat():
    assert not mac_matches_entry("b4:82:55:0:1a:5", "b4:82:55:00:1a:06")
