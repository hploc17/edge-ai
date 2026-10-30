#!/usr/bin/env python3
"""Unit tests for communication layer: WebGIS registration & health diagnostics."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.system_metrics import (
    collect_hardware_metrics,
    collect_comprehensive_health,
    _get_local_ip,
    _get_mac_address,
)
from communication.command_router import CommandHandler, ALLOWED_ACTIONS
from communication.mqtt_client import (
    MQTTPublisher,
    TOPIC_REGISTRATION,
    TOPIC_DEVICE_HEALTH,
    TOPIC_COMMAND_RESULT,
)

# Đảm bảo các lệnh remote control đã được thêm vào whitelist
REQUIRED_REMOTE_ACTIONS = {
    'list_videos', 'capture_preview', 'set_roi_remote',
    'start_pipeline', 'stop_pipeline', 'capture_snapshot',
}
assert REQUIRED_REMOTE_ACTIONS.issubset(ALLOWED_ACTIONS), \
    "Missing remote control actions in ALLOWED_ACTIONS: %s" % (REQUIRED_REMOTE_ACTIONS - ALLOWED_ACTIONS)


class MockMQTTPublisher(object):
    """Mock publisher to capture published messages for testing."""

    def __init__(self):
        self.published = []
        self.health_reports = []
        self.command_results = []
        self._is_connected = True
        self._lock = None
        self._registration_profile = None

    def _publish_raw(self, topic, payload, qos=0):
        self.published.append({'topic': topic, 'payload': payload, 'qos': qos})

    def publish(self, topic, payload, qos=0, retain=False, **kwargs):
        self.published.append({'topic': topic, 'payload': payload, 'qos': qos, 'retain': retain})

    def publish_device_health(self, command_id, health_data):
        self.health_reports.append({'command_id': command_id, 'data': health_data})

    def publish_command_result(self, command_id, action, status, message):
        self.command_results.append({
            'command_id': command_id,
            'action': action,
            'status': status,
            'message': message,
        })


def test_collect_hardware_metrics():
    metrics = collect_hardware_metrics(fps=25.0)
    assert 'fps' in metrics
    assert metrics['fps'] == 25.0
    assert 'cpu_usage_pct' in metrics
    assert 'ram_usage_pct' in metrics
    assert 'gpu_usage_pct' in metrics
    assert 'temperature_c' in metrics


def test_collect_comprehensive_health():
    health = collect_comprehensive_health(fps=22.5, camera_status='streaming')
    assert 'timestamp' in health

    # 1. General
    assert 'general' in health
    assert 'uptime_seconds' in health['general']
    assert 'service_status' in health['general']
    assert health['general']['service_status'] == 'running'

    # 2. Network
    assert 'network' in health
    assert 'local_ip' in health['network']
    assert 'mac_address' in health['network']

    # 3. Hardware
    assert 'hardware' in health
    hw = health['hardware']
    assert 'cpu_usage_pct' in hw
    assert 'ram_used_mb' in hw
    assert 'ram_total_mb' in hw
    assert 'ram_usage_pct' in hw
    assert 'swap_used_mb' in hw
    assert 'swap_total_mb' in hw

    # 4. Storage
    assert 'storage' in health
    st = health['storage']
    assert 'disk_total_gb' in st
    assert 'disk_free_gb' in st
    assert 'disk_usage_pct' in st
    assert 'outbox_unsent_images' in st

    # 5. Pipeline
    assert 'pipeline' in health
    pl = health['pipeline']
    assert pl['camera_status'] == 'streaming'
    assert pl['pipeline_fps'] == 22.5
    assert pl['inference_latency_ms'] is not None


def test_command_handler_get_health():
    mock_pub = MockMQTTPublisher()
    handler = CommandHandler(mock_pub)

    assert 'get_health' in ALLOWED_ACTIONS
    assert 'request_status' in ALLOWED_ACTIONS

    # Register health handler
    def health_fn(payload):
        return {
            'cpu': 50,
            'ram': 70,
            'status': 'healthy'
        }

    handler.register('get_health', health_fn)

    # Simulate incoming get_health command
    cmd_payload = {
        'action': 'get_health',
        'command_id': 'cmd-test-123'
    }
    handler.handle(cmd_payload)

    # Allow background thread in CommandHandler to execute
    import time
    time.sleep(0.1)

    assert len(mock_pub.health_reports) == 1
    assert mock_pub.health_reports[0]['command_id'] == 'cmd-test-123'
    assert mock_pub.health_reports[0]['data']['cpu'] == 50

    assert len(mock_pub.command_results) == 1
    assert mock_pub.command_results[0]['status'] == 'completed'


def test_command_handler_disallowed_action():
    mock_pub = MockMQTTPublisher()
    handler = CommandHandler(mock_pub)

    # Disallowed action
    cmd_payload = {
        'action': 'rm -rf /',
        'command_id': 'cmd-bad'
    }
    handler.handle(cmd_payload)

    assert len(mock_pub.command_results) == 1
    assert mock_pub.command_results[0]['status'] == 'rejected'


def test_mqtt_publisher_registration_and_health():
    pub = MQTTPublisher()
    mock_client = MockMQTTPublisher()
    pub._client = mock_client
    pub._is_connected = True

    # Test Gói 1: Registration
    sample_profile = {
        'event': 'device_registered',
        'edge_id': 'edge-01',
        'device_name': 'Nút giao Nguyễn Trãi',
        'geo': {'lat': 20.998412, 'lng': 105.795123},
    }
    pub.set_registration_profile(sample_profile)
    assert len(mock_client.published) >= 1
    reg_msg = [p for p in mock_client.published if 'registration' in p['topic']][0]
    assert 'Nút giao Nguyễn Trãi' in reg_msg['payload']

    # Test Gói 2: Device Health
    pub.publish_device_health('cmd-999', {'cpu_usage_pct': 45, 'status': 'ok'})
    health_msg = [p for p in mock_client.published if 'device-health' in p['topic']][0]
    assert 'cmd-999' in health_msg['payload']
    assert '45' in health_msg['payload']


def test_collect_spatial_info():
    from communication.system_metrics import collect_spatial_info
    info = collect_spatial_info()
    assert 'mac_address' in info
    assert 'edge_id' in info
    assert 'latitude' in info
    assert 'longitude' in info
    assert 'camera_heading' in info
    assert 'camera_fov' in info


def test_command_handler_get_spatial_info():
    import time
    from communication.system_metrics import collect_spatial_info
    mock_pub = MockMQTTPublisher()
    handler = CommandHandler(mock_pub)
    handler.register('get_spatial_info', lambda data: collect_spatial_info())

    cmd_payload = {
        'action': 'get_spatial_info',
        'command_id': 'spat-123'
    }
    handler.handle(cmd_payload)
    time.sleep(0.1)

    assert len(mock_pub.command_results) == 1
    assert mock_pub.command_results[0]['status'] == 'completed'
    assert isinstance(mock_pub.command_results[0]['message'], dict)
    assert 'mac_address' in mock_pub.command_results[0]['message']


def test_data_store_mac_lookup():
    from webgis.backend.services.data_store import DataStore
    ds = DataStore()
    dummy_mac = '02:00:00:AA:BB:CC'
    ds.nodes['test-edge'] = {'edge_id': 'test-edge', 'mac_address': dummy_mac}
    node = ds.get_node_by_mac(dummy_mac)
    assert node is not None
    assert node['edge_id'] == 'test-edge'


def test_data_store_mac_lookup_normalized():
    from webgis.backend.services.data_store import DataStore
    ds = DataStore()
    ds.nodes['test-norm-edge'] = {'edge_id': 'test-norm-edge', 'mac_address': 'AA:BB:CC:DD:EE:01'}
    
    # Check with clean hex without colons
    node_clean = ds.get_node_by_mac('aabbccddee01')
    assert node_clean is not None
    assert node_clean['edge_id'] == 'test-norm-edge'

    # Check with hyphens
    node_hyphen = ds.get_node_by_mac('AA-BB-CC-DD-EE-01')
    assert node_hyphen is not None
    assert node_hyphen['edge_id'] == 'test-norm-edge'


def test_system_metrics_board_serial():
    from communication.system_metrics import _get_board_serial
    serial = _get_board_serial()
    # On non-Jetson development machines, it returns None safely
    assert serial is None or isinstance(serial, str)


def test_mqtt_service_command_routing_single_topic():
    from webgis.backend.services.mqtt_service import mqtt_service
    from webgis.backend.services.data_store import store
    import json

    store.nodes['test-hw-edge'] = {
        'edge_id': 'test-hw-edge',
        'mac_address': 'AA:BB:CC:DD:EE:02',
        'status': 'online'
    }

    published_topics = []

    class MockClient:
        def publish(self, topic, payload, qos=1):
            published_topics.append(topic)

    orig_client = mqtt_service._client
    orig_conn = mqtt_service._connected
    try:
        mqtt_service._client = MockClient()
        mqtt_service._connected = True

        mqtt_service.publish_command('test-hw-edge', 'start_pipeline', 'cmd-test-123')

        # Verifies L1: ONLY the single logic topic is targeted (no duplicate hardware MAC topic)
        assert 'traffic/test-hw-edge/command' in published_topics
        assert len(published_topics) == 1
        assert 'traffic/hw/aabbccddee02/command' not in published_topics
    finally:
        mqtt_service._client = orig_client
        mqtt_service._connected = orig_conn
        store.nodes.pop('test-hw-edge', None)


def test_command_handler_deduplication():
    from communication.command_router import CommandHandler

    call_counts = {'start_pipeline': 0}

    def dummy_start(payload):
        call_counts['start_pipeline'] += 1
        return 'OK'

    class MockPublisher:
        def publish_command_result(self, **kwargs):
            pass

    handler = CommandHandler(MockPublisher(), dedupe_ttl=60.0)
    handler.register('start_pipeline', dummy_start)

    cmd_payload = {
        'action': 'start_pipeline',
        'command_id': 'cmd-dedupe-999',
        'params': {}
    }

    # First delivery -> Should execute
    handler.handle(cmd_payload)
    assert call_counts['start_pipeline'] == 1

    # Second delivery with same command_id -> Should be ignored (deduped)
    handler.handle(cmd_payload)
    assert call_counts['start_pipeline'] == 1

    # Third delivery with same command_id -> Still ignored
    handler.handle(cmd_payload)
    assert call_counts['start_pipeline'] == 1

    # New command_id -> Should execute
    cmd_payload_new = {
        'action': 'start_pipeline',
        'command_id': 'cmd-dedupe-1000',
        'params': {}
    }
    handler.handle(cmd_payload_new)
    assert call_counts['start_pipeline'] == 2


def test_mqtt_service_provisioning_approval():
    from webgis.backend.services.mqtt_service import mqtt_service

    published = []

    class MockClient:
        def publish(self, topic, payload, qos=1):
            published.append((topic, payload))

    orig_client = mqtt_service._client
    orig_conn = mqtt_service._connected
    try:
        mqtt_service._client = MockClient()
        mqtt_service._connected = True

        success = mqtt_service.publish_provisioning_approval(
            mac_address="AA:BB:CC:DD:EE:FF",
            assigned_edge_id="edge-99",
            approved_data={"name": "Test Camera"}
        )
        assert success is True
        assert len(published) == 1
        topic, payload_str = published[0]
        assert topic == "traffic/provisioning/aabbccddeeff"
        assert "edge-99" in payload_str
    finally:
        mqtt_service._client = orig_client
        mqtt_service._connected = orig_conn


def test_l4_single_agent_heartbeat_and_lwt_isolation():
    """L4: Đảm bảo chỉ có Jetson Agent mới thiết lập LWT và phát Heartbeat cấp Node; Pipeline không làm sập Node."""
    # 1. Agent MQTTPublisher: Có LWT và được phát heartbeat
    agent_pub = MQTTPublisher(client_id="test-agent", is_agent=True)
    assert agent_pub._is_agent is True
    assert b"/heartbeat" in agent_pub._client._will_topic

    # 2. Pipeline MQTTPublisher: KHÔNG có LWT lên heartbeat và KHÔNG phát heartbeat
    pipeline_pub = MQTTPublisher(client_id="test-pipeline", is_agent=False)
    assert pipeline_pub._is_agent is False
    assert not pipeline_pub._client._will_topic

    published = []
    pipeline_pub._publish_raw = lambda t, p, **k: published.append((t, p))
    pipeline_pub.publish_heartbeat()
    assert len(published) == 0, "Pipeline worker must NOT publish node heartbeat"

    # 3. Khi pipeline dừng/thoát, không được phát tin offline đè lên node
    pipeline_pub.stop(publish_offline=True)
    assert len(published) == 0, "Pipeline stop must NOT publish offline status to node heartbeat"


def test_l9_heartbeat_no_coordinates_and_no_fake_spatial_drift():
    """L9: Định danh thiết bị chuẩn hóa, Heartbeat không chứa lat/lng, không báo spatial drift giả."""
    import json
    from webgis.backend.services.mqtt_service import mqtt_service
    from webgis.backend.services.data_store import store

    # 1. Heartbeat của Agent không chứa tọa độ tĩnh
    agent_pub = MQTTPublisher(client_id="test-agent-l9", is_agent=True)
    heartbeat_calls = []
    agent_pub._publish_raw = lambda topic, payload, **kwargs: heartbeat_calls.append((topic, json.loads(payload)))

    agent_pub.publish_heartbeat()
    assert len(heartbeat_calls) == 1
    topic, hb_data = heartbeat_calls[0]
    assert "heartbeat" in topic
    assert "latitude" not in hb_data, "Heartbeat không được chứa latitude (L9)"
    assert "longitude" not in hb_data, "Heartbeat không được chứa longitude (L9)"
    assert hb_data["status"] == "online"

    # 2. Không sinh cảnh báo spatial drift giả khi chỉ có tọa độ nhập tay tĩnh
    test_edge = "edge-l9-test"
    store.nodes[test_edge] = {
        "edge_id": test_edge,
        "name": "Test Node L9",
        "latitude": 10.852708,
        "longitude": 106.660508,
        "status": "online",
        "last_seen": "2026-10-28T00:00:00+07:00",
    }

    class DummyMsg:
        def __init__(self, t, p):
            self.topic = t
            self.payload = p.encode("utf-8")

    # Bản tin heartbeat có chứa số nhập tay cũ (Hà Nội vs TP.HCM)
    msg_static = DummyMsg(
        f"traffic/{test_edge}/heartbeat",
        json.dumps({
            "edge_id": test_edge,
            "status": "online",
            "latitude": 20.998412,
            "longitude": 105.795123,
        })
    )
    mqtt_service._on_message(None, None, msg_static)
    assert "spatial_drift" not in store.nodes[test_edge], "Không được sinh cảnh báo spatial drift khi không có GPS thật"

    # 3. Khi có module GPS thật (hardware_gps: has_gps=True), spatial drift được kích hoạt chính xác
    msg_real_gps = DummyMsg(
        f"traffic/{test_edge}/heartbeat",
        json.dumps({
            "edge_id": test_edge,
            "status": "online",
            "hardware_gps": {
                "has_gps": True,
                "latitude": 10.860000,
                "longitude": 106.670000,
            }
        })
    )
    mqtt_service._on_message(None, None, msg_real_gps)
    assert "spatial_drift" in store.nodes[test_edge], "Có GPS thật và bị lệch > 50m thì kích hoạt spatial drift"
    assert store.nodes[test_edge]["spatial_drift"]["is_hardware_gps"] is True

    # Dọn dẹp
    store.nodes.pop(test_edge, None)




