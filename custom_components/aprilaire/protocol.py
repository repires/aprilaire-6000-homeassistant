"""Owned 0.9.1 compatibility adapter for the 6003 automation endpoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from copy import deepcopy

from pyaprilaire.client import AprilaireClient, _AprilaireClientProtocol
from pyaprilaire.const import Action, Attribute, FunctionalDomain
from pyaprilaire.packet import MAPPING, NackPacket, Packet, ValueType

_LOGGER = logging.getLogger(__name__)
ATTR_HEAT_BLAST = "heat_blast"
ATTR_ZONE_COUNT = "zone_count"
ATTR_DAT_LOW_LIMIT = "dat_low_limit"
ATTR_DAT_HIGH_LIMIT = "dat_high_limit"

# This table belongs to this component; importing it never changes pyaprilaire.
_PACKET_MAPPING = deepcopy(MAPPING)
for action in (Action.READ_RESPONSE, Action.COS):
    mapping = _PACKET_MAPPING[action]
    mapping.setdefault(FunctionalDomain.SCHEDULING, {})[5] = [(ATTR_HEAT_BLAST, ValueType.INTEGER)]
    mapping[FunctionalDomain.IDENTIFICATION][2] = [
        (Attribute.MAC_ADDRESS, ValueType.MAC_ADDRESS),
        (None, None),
        (Attribute.HARDWARE_REVISION, ValueType.INTEGER),
        (Attribute.FIRMWARE_MAJOR_REVISION, ValueType.INTEGER),
        (Attribute.FIRMWARE_MINOR_REVISION, ValueType.INTEGER),
        (Attribute.PROTOCOL_MAJOR_REVISION, ValueType.INTEGER),
        (Attribute.MODEL_NUMBER, ValueType.INTEGER),
        (Attribute.GAINSPAN_FIRMWARE_MAJOR_REVISION, ValueType.INTEGER),
        (Attribute.GAINSPAN_FIRMWARE_MINOR_REVISION, ValueType.INTEGER),
    ]
    mapping.setdefault(FunctionalDomain.SETUP, {})[10] = [
        (None, None),
        (None, None),
        (ATTR_ZONE_COUNT, ValueType.INTEGER),
        *[(None, None)] * 5,
        (ATTR_DAT_LOW_LIMIT, ValueType.TEMPERATURE),
        (None, None),
        (ATTR_DAT_HIGH_LIMIT, ValueType.TEMPERATURE),
    ]


class StreamDecoder:
    """Reassemble bounded TCP frames and validate before decoding their fields."""

    def __init__(self):
        self.buffer = bytearray()
        self._resync = False

    def feed(self, data: bytes, *, discard_partial: bool = False) -> list[Packet]:
        self.buffer.extend(data)
        if discard_partial:
            self._resync = True
        packets = []
        while len(self.buffer) >= 4:
            count = int.from_bytes(self.buffer[2:4], "big")
            if self.buffer[0] not in (1, 2) or not 2 <= count <= 1024:
                del self.buffer[0]
                self._resync = True
                continue
            size = count + 5
            if len(self.buffer) < size:
                if self._resync:
                    found = False
                    for start in range(1, len(self.buffer) - 6):
                        length = int.from_bytes(self.buffer[start + 2 : start + 4], "big") + 5
                        candidate = self.buffer[start : start + length]
                        if (
                            self.buffer[start] in (1, 2)
                            and 7 <= length <= 1029
                            and len(candidate) == length
                            and Packet._verify_crc(candidate[:-1], candidate[-1])
                        ):
                            del self.buffer[:start]
                            found = True
                            break
                    if found:
                        continue
                if discard_partial:
                    self.buffer.clear()
                break
            frame = bytes(self.buffer[:size])
            if not Packet._verify_crc(frame[:-1], frame[-1]):
                del self.buffer[0]
                self._resync = True
                continue
            del self.buffer[:size]
            self._resync = False
            packet = self._decode(frame)
            if packet is not None:
                packets.append(packet)
        return packets

    @staticmethod
    def _decode(frame: bytes) -> Packet | None:
        body = frame[4:-1]
        if body[0] == Action.NACK:
            if len(body) != 2:
                return None
            packet = NackPacket(body[1])
            packet.sequence = frame[1]
            return packet
        if len(body) < 3:
            return None
        try:
            action, domain = Action(body[0]), FunctionalDomain(body[1])
            fields = _PACKET_MAPPING[action][domain][body[2]]
        except (ValueError, KeyError):
            return None
        packet = Packet(action, domain, body[2], frame[0], frame[1], len(body))
        payload = body[3:]
        offset = 0
        for key, kind, *extra in fields:
            if offset == len(payload):
                if (domain, body[2]) == (FunctionalDomain.IDENTIFICATION, 2) and offset in (6, 7):
                    break
                return None
            width = (
                6
                if kind == ValueType.MAC_ADDRESS
                else extra[0] + 1
                if kind == ValueType.TEXT
                else 1
            )
            if offset + width > len(payload):
                return None
            value = payload[offset : offset + width]
            offset += width
            if key is None or kind is None:
                continue
            if kind == ValueType.MAC_ADDRESS:
                packet.data[key] = ":".join(f"{b:02x}" for b in value)
            elif kind == ValueType.TEXT:
                packet.data[key] = value.rstrip(b"\x00 ").decode("latin-1")
            elif kind in (ValueType.TEMPERATURE, ValueType.TEMPERATURE_REQUIRED):
                if kind != ValueType.TEMPERATURE_REQUIRED or value[0]:
                    packet.data[key] = Packet._decode_temperature(value[0])
            elif kind == ValueType.HUMIDITY:
                packet.data[key] = Packet._decode_humidity(value[0])
            elif kind != ValueType.INTEGER_REQUIRED or value[0]:
                packet.data[key] = value[0]
        return packet


class AprilaireProtocol(_AprilaireClientProtocol):
    """Own every sender, initialization task, and outstanding read."""

    def __init__(self, callback, logger=_LOGGER):
        super().__init__(callback, None, logger)
        self.decoder = StreamDecoder()
        self.closed = asyncio.Event()
        self.ready = asyncio.Event()
        self.data = {}
        self._tasks = set()
        self._responses = {}
        self._sequence = 0
        self.pacing = 0.30

    def connection_made(self, transport):
        self.transport = transport
        for coroutine in (self._send_loop(), self._initialize()):
            task = asyncio.create_task(coroutine)
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _send_packet(self, packet):
        self._sequence = self._sequence % 127 + 1
        packet.sequence = self._sequence
        await self.packet_queue.put(packet)
        return packet.sequence

    async def read(self, domain, attribute, timeout=5):
        packet = Packet(Action.READ_REQUEST, domain, attribute)
        sequence = await self._send_packet(packet)
        future = asyncio.get_running_loop().create_future()
        self._responses[sequence] = (future, domain, attribute)
        try:
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            self._handle_packets(self.decoder.feed(b"", discard_partial=True))
            _LOGGER.debug("No reply for automation attribute %d/%d", domain, attribute)
            return None
        finally:
            self._responses.pop(sequence, None)

    async def _send_loop(self):
        try:
            while True:
                packet = await self.packet_queue.get()
                try:
                    self.transport.write(packet.serialize())
                finally:
                    self.packet_queue.task_done()
                await asyncio.sleep(self.pacing)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Automation sender failed")
            if self.transport:
                self.transport.close()
            self.closed.set()

    def data_received(self, data):
        self._handle_packets(self.decoder.feed(data))

    def _handle_packets(self, packets):
        for packet in packets:
            pending = self._responses.get(packet.sequence)
            if isinstance(packet, NackPacket):
                _LOGGER.debug("Automation NACK status 0x%02x", packet.nack_attribute)
                if pending and not pending[0].done():
                    pending[0].set_result(None)
                continue
            self.data.update(packet.data)
            if pending and (packet.functional_domain, packet.attribute) == pending[1:]:
                if not pending[0].done():
                    pending[0].set_result(packet.data)
            task = asyncio.create_task(
                self.data_received_callback(packet.functional_domain, packet.attribute, packet.data)
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _initialize(self):
        try:
            if not await self.read(FunctionalDomain.IDENTIFICATION, 2):
                self.transport.close()
                self.closed.set()
                return
            if Attribute.MODEL_NUMBER not in self.data:
                await self.read(FunctionalDomain.IDENTIFICATION, 1)
            is_6003 = self.data.get(Attribute.MODEL_NUMBER) == 28
            self.pacing = 0.30 if is_6003 else 0.05
            for domain, attribute in [
                (FunctionalDomain.CONTROL, 7),
                (FunctionalDomain.CONTROL, 1),
                (FunctionalDomain.SENSORS, 2),
                (FunctionalDomain.IDENTIFICATION, 4 if is_6003 else 5),
                (FunctionalDomain.STATUS, 6),
                (FunctionalDomain.STATUS, 7),
                (FunctionalDomain.SCHEDULING, 4),
                (FunctionalDomain.SENSORS, 1),
                (FunctionalDomain.CONTROL, 4),
                (FunctionalDomain.CONTROL, 3),
            ]:
                await self.read(domain, attribute)
            if is_6003:
                await self.read(FunctionalDomain.SETUP, 10)
                await self.read(FunctionalDomain.SCHEDULING, 5)
            await self.configure_cos()
            await self.sync()
            await self.packet_queue.join()
            self.ready.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Automation initialization failed")
            self.transport.close()
            self.closed.set()

    def connection_lost(self, exc):
        self.closed.set()
        self.transport = None
        for future, _, _ in self._responses.values():
            if not future.done():
                future.cancel()
        for task in self._tasks:
            task.cancel()

    async def async_close(self):
        if self.transport:
            self.transport.close()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self.closed.set()


class AprilaireLocalClient(AprilaireClient):
    """Reuse command encoding while owning the connection and reconnect lifecycle."""

    def __init__(self, *args):
        super().__init__(*args)
        self._runner_task = None
        self._ready = asyncio.Event()

    async def start_listen(self):
        self.stopped = False
        self._runner_task = asyncio.create_task(self._run())

    async def _run(self):
        try:
            while not self.stopped:
                self._ready.clear()
                self.protocol = AprilaireProtocol(self.data_received, self.logger)
                try:
                    await asyncio.wait_for(
                        asyncio.get_running_loop().create_connection(
                            lambda: self.protocol, self.host, self.port
                        ),
                        10,
                    )
                    ready = asyncio.create_task(self.protocol.ready.wait())
                    closed = asyncio.create_task(self.protocol.closed.wait())
                    try:
                        await asyncio.wait((ready, closed), return_when=asyncio.FIRST_COMPLETED)
                        if self.protocol.ready.is_set():
                            self.connected = True
                            self.reconnecting = False
                            self.state_changed()
                            self._ready.set()
                        await asyncio.wait_for(closed, self.reconnect_interval)
                    finally:
                        ready.cancel()
                        closed.cancel()
                        await asyncio.gather(ready, closed, return_exceptions=True)
                except (OSError, TimeoutError):
                    _LOGGER.debug("Automation connection unavailable; retrying")
                finally:
                    await self.protocol.async_close()
                    self.protocol = None
                    self.connected = False
                    self.state_changed()
                self.reconnecting = True
                await asyncio.sleep(self.retry_connection_interval)
        finally:
            self.connected = False
            self.state_changed()

    async def wait_ready(self, timeout=90):
        await asyncio.wait_for(self._ready.wait(), timeout)

    def stop_listen(self):
        self.stopped = True
        if self._runner_task:
            self._runner_task.cancel()
        self.connected = False
        self.state_changed()

    async def async_stop(self):
        self.stop_listen()
        if self._runner_task:
            with suppress(asyncio.CancelledError):
                await self._runner_task
            self._runner_task = None
