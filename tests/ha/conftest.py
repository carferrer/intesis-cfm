"""Use real Home Assistant with a simulated WMP client."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.intesisbox.intesisbox import IntesisBox


@pytest.fixture(autouse=True)
def enable_custom(enable_custom_integrations):
    yield


@pytest.fixture
def controller():
    box = IntesisBox("192.0.2.1")
    box.data_received(
        b"ID:IS-IR-WMP-1,001DC9A2C911,192.0.2.1,ASCII,v1,-44\r"
        b"LIMITS:SETPTEMP,[160,300]\rLIMITS:FANSP,[AUTO,1,2,3]\r"
        b"LIMITS:MODE,[AUTO,HEAT,COOL,FAN,DRY]\r"
        b"LIMITS:VANEUD,[AUTO,SWING]\rLIMITS:VANELR,[]\r"
        b"CHN,1:ONOFF,ON\rCHN,1:MODE,COOL\rCHN,1:FANSP,AUTO\r"
        b"CHN,1:AMBTEMP,215\rCHN,1:SETPTEMP,230\r"
    )
    box._connected = True
    box._disconnected.clear()
    with (
        patch.object(box, "async_connect", new=AsyncMock()),
        patch.object(box, "async_close", new=AsyncMock()),
        patch.object(box, "async_run", new=AsyncMock()),
    ):
        yield box


@pytest.fixture
def mock_client(controller):
    with (
        patch("custom_components.intesisbox.IntesisBox", return_value=controller),
        patch(
            "custom_components.intesisbox.config_flow.IntesisBox",
            return_value=controller,
        ),
    ):
        yield controller
