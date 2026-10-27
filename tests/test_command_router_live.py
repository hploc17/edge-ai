import time
import pytest
from communication.command_router import ALLOWED_ACTIONS, CommandHandler
from core.live_stream import LiveStreamController, set_global_controller, register_live_handlers


class MockPublisher(object):
    def __init__(self):
        self.results = []

    def publish_command_result(self, command_id, action, status, message=""):
        self.results.append({
            "command_id": command_id,
            "action": action,
            "status": status,
            "message": message
        })


def test_command_router_whitelist_contains_live():
    for act in ["start_live", "stop_live", "live_keepalive", "live_status"]:
        assert act in ALLOWED_ACTIONS, "Action %s must be in ALLOWED_ACTIONS" % act


def test_command_router_live_lifecycle():
    pub = MockPublisher()
    handler = CommandHandler(pub)

    # Initialize a mock LiveStreamController
    class MockValve(object):
        def __init__(self):
            self.drop = True
        def set_property(self, k, v):
            if k == "drop":
                self.drop = v

    valve = MockValve()
    ctrl = LiveStreamController(valve=valve, idle_timeout_s=10.0, rtsp_url="rtsp://localhost:8554/live/edge-01")
    set_global_controller(ctrl)
    register_live_handlers(handler)

    # 1. Test start_live
    handler.handle({
        "command_id": "test-start-1",
        "action": "start_live",
        "params": {"injected_malicious_url": "http://evil.com/stream"} # Must be ignored!
    })
    time.sleep(0.1)
    assert ctrl.state == "on"
    assert valve.drop is False

    # 2. Test live_keepalive
    handler.handle({
        "command_id": "test-keep-1",
        "action": "live_keepalive"
    })
    time.sleep(0.1)
    assert ctrl.state == "on"

    # 3. Test live_status
    handler.handle({
        "command_id": "test-stat-1",
        "action": "live_status"
    })
    time.sleep(0.1)
    assert ctrl.state == "on"

    # 4. Test stop_live
    handler.handle({
        "command_id": "test-stop-1",
        "action": "stop_live"
    })
    time.sleep(0.1)
    assert ctrl.state == "off"
    assert valve.drop is True


def test_command_router_rejects_disallowed_actions():
    pub = MockPublisher()
    handler = CommandHandler(pub)

    handler.handle({
        "command_id": "bad-1",
        "action": "system_exec_rm_rf",
        "params": {}
    })
    assert len(pub.results) == 1
    assert pub.results[0]["status"] == "rejected"
    assert "disallowed action" in pub.results[0]["message"]
