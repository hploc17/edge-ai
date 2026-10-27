import time
import pytest
from core.live_stream import LiveStreamController


class MockGstElement(object):
    def __init__(self):
        self.properties = {}

    def set_property(self, key, val):
        self.properties[key] = val

    def get_property(self, key):
        return self.properties.get(key)


def test_controller_initial_state():
    mock_valve = MockGstElement()
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=1.0, rtsp_url="rtsp://localhost:8554/live/cam1")
    assert ctrl.state == "off"
    assert mock_valve.get_property("drop") is True


def test_controller_start_and_stop():
    mock_valve = MockGstElement()
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=5.0, rtsp_url="rtsp://localhost:8554/live/cam1")

    # Start
    res = ctrl.start()
    assert res["status"] == "started"
    assert ctrl.state == "on"
    assert mock_valve.get_property("drop") is False

    # Calling start again while running returns already_running
    res2 = ctrl.start()
    assert res2["status"] == "already_running"

    # Stop
    res_stop = ctrl.stop()
    assert res_stop["status"] == "stopped"
    assert ctrl.state == "off"
    assert mock_valve.get_property("drop") is True


def test_controller_idle_timeout():
    mock_valve = MockGstElement()
    # 0.5s timeout for fast testing
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=0.5, rtsp_url="rtsp://localhost:8554/live/cam1")

    ctrl.start()
    assert ctrl.state == "on"
    assert mock_valve.get_property("drop") is False

    # Wait for idle timeout to fire (> 0.5s + monitor cycle)
    time.sleep(2.5)

    assert ctrl.state == "off"
    assert mock_valve.get_property("drop") is True


def test_controller_keepalive_resets_idle():
    mock_valve = MockGstElement()
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=1.5, rtsp_url="rtsp://localhost:8554/live/cam1")

    ctrl.start()
    time.sleep(0.8)
    res = ctrl.keep_alive()
    assert res["status"] == "ok"
    assert ctrl.state == "on"


def test_controller_bus_error_handling():
    mock_valve = MockGstElement()
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=5.0)

    ctrl.start()
    assert ctrl.state == "on"

    ctrl.on_bus_error("Connection refused by RTSP server")
    assert ctrl.state == "error"
    assert "Connection refused" in ctrl.error_message
    assert mock_valve.get_property("drop") is True
