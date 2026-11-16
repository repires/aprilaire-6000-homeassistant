"""A failed token-renewal ping must wake the blocked receive loop."""

from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.aprilaire_cloud.vendor.websocket import AprilaireLocationWebSocket


@pytest.mark.asyncio
async def test_ping_failure_closes_transport():
    manager = AprilaireLocationWebSocket(
        client=Mock(),
        session=Mock(),
        location_id="synthetic",
        message_callback=AsyncMock(),
        state_callback=AsyncMock(),
    )
    manager._async_ping_messages = AsyncMock(side_effect=RuntimeError("synthetic failure"))
    ws = Mock(close=AsyncMock())
    with pytest.raises(RuntimeError):
        await manager._async_ping_loop(ws)
    ws.close.assert_awaited_once()
