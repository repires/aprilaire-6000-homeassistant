"""Offline frames and fake transports; no thermostat connections."""

import asyncio
from copy import deepcopy
from importlib import import_module
from unittest.mock import Mock

import pytest
from pyaprilaire.const import Attribute, FunctionalDomain
from pyaprilaire.packet import MAPPING, Packet

# Capture before importing component code: loading it must not mutate the library.
ORIGINAL_MAPPING = deepcopy(MAPPING)
ORIGINAL_PARSE = Packet.parse.__func__

import_module("custom_components.aprilaire.coordinator")


def test_component_does_not_patch_global_library_parser():
    assert Packet.parse.__func__ is ORIGINAL_PARSE
    assert MAPPING == ORIGINAL_MAPPING


def frame(body, sequence=1):
    head = bytes([1, sequence, len(body) >> 8, len(body) & 255]) + bytes(body)
    return head + bytes([Packet._generate_crc(list(head))])


def test_nack_status_is_not_interpreted_as_a_domain():
    from custom_components.aprilaire.protocol import StreamDecoder

    packets = StreamDecoder().feed(frame([6, 0x22]))
    assert len(packets) == 1
    assert packets[0].nack_attribute == 0x22


def test_every_frame_split_and_multiple_frames():
    from custom_components.aprilaire.protocol import StreamDecoder

    wire = frame([3, 2, 1, 2, 2, 85, 22])
    for split in range(1, len(wire)):
        decoder = StreamDecoder()
        assert decoder.feed(wire[:split]) == []
        result = decoder.feed(wire[split:] + wire)
        assert len(result) == 2
        assert result[0].data[Attribute.HEAT_SETPOINT] == 21.5


def test_bad_crc_and_short_mac_do_not_poison_following_frame():
    from custom_components.aprilaire.protocol import StreamDecoder

    good = frame([3, 2, 1, 2, 2, 85, 22])
    bad = good[:-1] + bytes([good[-1] ^ 255])
    result = StreamDecoder().feed(bad + frame([3, 8, 2, 1]) + good)
    assert len(result) == 1
    assert result[0].data[Attribute.HEAT_SETPOINT] == 21.5


@pytest.mark.asyncio
async def test_reconnect_reinitializes_and_closes_all_owned_tasks():
    from custom_components.aprilaire.protocol import AprilaireProtocol

    seen = []

    async def callback(domain, attribute, data):
        pass

    for _ in range(2):
        protocol = AprilaireProtocol(callback)

        async def reply(domain, attribute, timeout=5, protocol=protocol):
            seen.append((domain, attribute))
            if (domain, attribute) == (8, 2):
                protocol.data[Attribute.MODEL_NUMBER] = 28
                return {Attribute.MAC_ADDRESS: "02:00:00:00:00:01"}
            return {}

        protocol.read = reply
        protocol.connection_made(Mock())
        await asyncio.wait_for(protocol.ready.wait(), 3)
        await protocol.async_close()
        assert not protocol._tasks
    assert seen.count((8, 2)) == 2
    assert seen.count((2, 1)) == 2
    assert seen.count((1, 10)) == 2


@pytest.mark.asyncio
async def test_correlated_nack_finishes_read_without_timeout():
    from custom_components.aprilaire.protocol import AprilaireProtocol

    protocol = AprilaireProtocol(Mock())
    read = asyncio.create_task(protocol.read(FunctionalDomain.SCHEDULING, 5, timeout=0.5))
    await asyncio.sleep(0)
    packet = protocol.packet_queue.get_nowait()
    protocol.data_received(frame([6, 0x22], packet.sequence))
    assert await read is None
    assert not protocol._responses
    await protocol.async_close()


def test_read_timeout_recovers_complete_frame_after_corrupt_length():
    from custom_components.aprilaire.protocol import StreamDecoder

    decoder = StreamDecoder()
    good = frame([3, 2, 1, 2, 2, 85, 22])
    assert decoder.feed(bytes([1, 1, 3, 0]) + good) == []
    packets = decoder.feed(b"", discard_partial=True)
    assert len(packets) == 1
    assert packets[0].data[Attribute.HEAT_SETPOINT] == 21.5


def test_short_control_response_is_discarded():
    from custom_components.aprilaire.protocol import StreamDecoder

    assert StreamDecoder().feed(frame([3, 2, 1, 2])) == []


@pytest.mark.asyncio
async def test_full_client_reconnect_and_unload_leaves_no_protocol_tasks(monkeypatch):
    import logging

    from custom_components.aprilaire.protocol import AprilaireLocalClient

    loop = asyncio.get_running_loop()
    connections = []
    updates = []
    replies = {
        (8, 2): [2, 0, 0, 0, 0, 1, 1, 66, 2, 2, 2, 28, 4, 14],
        (2, 7): [5, 0, 1, 0, 2],
        (2, 1): [2, 2, 85, 22],
        (5, 2): [4, 85, 3, 0, 0, 47, 3, 0],
        (8, 4): list(b"TEST000\x00Synthetic Zone\x00\x00"),
        (7, 6): [0, 0, 0, 1],
        (7, 7): [0, 2, 2, 0],
        (3, 4): [0] * 10,
        (5, 1): [0, 85, 3, 0, 4, 146, 0, 47, 3, 146, 0, 43, 3, 0, 3, 0],
        (2, 4): [50],
        (1, 10): [1, 0, 2, 1, 1, 1, 1, 10, 10, 1, 47],
        (3, 5): [0],
    }

    class Transport:
        def __init__(self, protocol):
            self.protocol = protocol
            self.closed = False

        def write(self, data):
            if data[4] != 2:
                return
            key = tuple(data[5:7])
            body = [3, *key, *replies[key]] if key in replies else [6, 0x21]
            loop.call_soon(self.protocol.data_received, frame(body, data[1]))

        def close(self):
            if not self.closed:
                self.closed = True
                self.protocol.connection_lost(None)

    async def connect(factory, host, port):
        protocol = factory()
        transport = Transport(protocol)
        connections.append((transport, protocol))
        protocol.connection_made(transport)
        return transport, protocol

    monkeypatch.setattr(loop, "create_connection", connect)
    client = AprilaireLocalClient(
        "synthetic.invalid", 7000, updates.append, logging.getLogger(__name__), 3600, 0.01
    )
    try:
        await client.start_listen()
        await client.wait_ready(10)
        assert client.connected
        first = connections[0]
        first[0].close()

        async def reconnected():
            while len(connections) < 2 or not connections[1][1].ready.is_set():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(reconnected(), 10)
        assert client.connected
        assert sum(Attribute.HEAT_SETPOINT in data for data in updates) == 2
        assert not first[1]._tasks
    finally:
        await client.async_stop()
    assert not client.connected
    assert client.protocol is None
    assert client._runner_task is None
    assert all(not protocol._tasks for _, protocol in connections)
