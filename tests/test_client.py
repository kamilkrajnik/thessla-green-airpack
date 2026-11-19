"""AirPackClient transport tests against a fake gateway on the loopback interface."""

import asyncio

import pytest
from pymodbus import FramerType

from custom_components.thessla_green_airpack.client import AirPackClient
from custom_components.thessla_green_airpack.const import (
    CONNECTION_MODBUS_TCP,
    CONNECTION_RTU_OVER_TCP,
)
from custom_components.thessla_green_airpack.registers import Table

# Exchange captured on a Waveshare RS485 TO ETH (firmware V4019) in transparent mode:
# read holding register 4452 (0x1164) of unit 10 -> value 10.
RTU_REQUEST = bytes.fromhex("0a 03 11 64 00 01 c1 92")
RTU_RESPONSE = bytes.fromhex("0a 03 02 00 0a 9d 82")
# The same request / response as a converting gateway sees them (MBAP header, no CRC).
MBAP_REQUEST = bytes.fromhex("00 01 00 00 00 06 0a 03 11 64 00 01")
MBAP_RESPONSE = bytes.fromhex("00 01 00 00 00 05 0a 03 02 00 0a")
REPLIES = {RTU_REQUEST: RTU_RESPONSE, MBAP_REQUEST: MBAP_RESPONSE}


@pytest.fixture
async def gateway(socket_enabled):
    """TCP server on the loopback interface (the only host the test harness allows).

    Answers the one request above and records what it received.
    """
    received: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.read(256)
        received.append(request)
        writer.write(REPLIES.get(request, b""))
        await writer.drain()
        await reader.read()  # until the client disconnects
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1], received
    server.close()
    await server.wait_closed()


@pytest.mark.parametrize(
    ("connection_type", "framer", "wire_request"),
    [
        (CONNECTION_MODBUS_TCP, FramerType.SOCKET, MBAP_REQUEST),
        (CONNECTION_RTU_OVER_TCP, FramerType.RTU, RTU_REQUEST),
    ],
)
async def test_transport_framing(gateway, connection_type: str, framer: FramerType, wire_request: bytes) -> None:
    port, received = gateway
    client = AirPackClient("127.0.0.1", port, 10, connection_type=connection_type, timeout=2)
    assert client.framer is framer
    try:
        assert await client.read(Table.HOLDING, 0x1164, 1) == [10]
    finally:
        await client.close()
    assert received == [wire_request]


def test_default_is_modbus_tcp() -> None:
    assert AirPackClient("127.0.0.1", 502, 10).framer is FramerType.SOCKET


def test_unknown_connection_type() -> None:
    with pytest.raises(KeyError):
        AirPackClient("127.0.0.1", 502, 10, connection_type="serial")
