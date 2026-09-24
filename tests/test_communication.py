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

    def publish(self, topic, payload, qos=0):
        self.published.append({'topic': topic, 'payload': payload, 'qos': qos})

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
