#!/usr/bin/env python3
"""Test hợp đồng giữa các khối: Jetson -> Backend (token tải ảnh), API lịch sử, cấu hình nvinfer.

Không khởi động FastAPI/MQTT thật và không đụng dữ liệu trong webgis/backend/data:
các module có tác dụng phụ (data_store) được thay bằng module giả trong sys.modules.
"""

import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, 'webgis', 'backend')
for path in (ROOT, BACKEND):
    if path not in sys.path:
        sys.path.insert(0, path)


class FakeRequest(object):
    def __init__(self, headers):
        self.headers = dict((k.lower(), v) for k, v in headers.items())


class TestSnapshotUploadAuth(unittest.TestCase):
    """C1: header Jetson gửi phải được backend chấp nhận."""

    def setUp(self):
        os.environ.setdefault('JWT_SECRET', 'unit-test-secret')
        self.auth = importlib.import_module('services.auth_middleware')
        self._saved = self.auth.EDGE_TOKEN
        self.auth.EDGE_TOKEN = 'edge-secret-123'

    def tearDown(self):
        self.auth.EDGE_TOKEN = self._saved

    def edge_headers(self):
        from snap.snapshot_service import SnapshotCoordinator
        coordinator = SnapshotCoordinator.__new__(SnapshotCoordinator)
        coordinator.edge_token = 'edge-secret-123'
        return coordinator._auth_headers()

    def test_jetson_snapshot_headers_are_accepted(self):
        request = FakeRequest(self.edge_headers())
        self.assertTrue(self.auth.verify_edge_token(self.auth.edge_token_from_request(request)))

    def test_bearer_edge_token_is_accepted_for_backward_compatibility(self):
        request = FakeRequest({'Authorization': 'Bearer edge-secret-123'})
        self.assertTrue(self.auth.verify_edge_token(self.auth.edge_token_from_request(request)))

    def test_wrong_or_missing_token_rejected(self):
        self.assertFalse(self.auth.verify_edge_token(
            self.auth.edge_token_from_request(FakeRequest({'X-Edge-Token': 'wrong'}))))
        self.assertFalse(self.auth.verify_edge_token(self.auth.edge_token_from_request(FakeRequest({}))))

    def test_server_without_edge_token_rejects_everything(self):
        self.auth.EDGE_TOKEN = ''
        self.assertFalse(self.auth.verify_edge_token(''))
        self.assertFalse(self.auth.verify_edge_token('anything'))


class TestHistoryTimeline(unittest.TestCase):
    """H4: phút đường vắng (avg_speed_kmh = NULL) không được làm API lỗi 500."""

    def setUp(self):
        from unittest import mock
        fake_store_module = types.ModuleType('services.data_store')

        class FakeStore(object):
            def get_timeline_records(self, segment_id=None, date=None):
                return [
                    {'congestion_score': 20, 'avg_speed_kmh': 30.0},
                    {'congestion_score': 10, 'avg_speed_kmh': None},   # phút đường vắng
                    {'congestion_score': 70, 'avg_speed_kmh': 8.0},
                ]

        fake_store_module.store = FakeStore()
        fake_auth = types.ModuleType('services.auth_middleware')
        fake_auth.require_staff = lambda: None
        # patch.dict tự khôi phục sys.modules kể cả khi setUp lỗi giữa chừng
        patcher = mock.patch.dict(sys.modules, {'services.data_store': fake_store_module,
                                                'services.auth_middleware': fake_auth})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Nạp trực tiếp file router (không qua routers/__init__.py vốn import mọi router)
        spec = importlib.util.spec_from_file_location(
            'history_under_test', os.path.join(BACKEND, 'routers', 'history.py'))
        self.history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.history)

    def test_timeline_with_null_speed(self):
        result = self.history.get_timeline(segment_id='segment-001', date=None)
        self.assertEqual(result['peak_congestion_score'], 70)
        self.assertEqual(result['min_speed_kmh'], 8.0)
        self.assertEqual(result['avg_speed_kmh'], 19.0)


class TestInferConfigPaths(unittest.TestCase):
    """M6: đường dẫn tương đối trong config nvinfer được hiểu theo thư mục chứa config."""

    def test_relative_engine_resolved_against_config_dir(self):
        from core.gstreamer_builder import ensure_infer_config
        workdir = tempfile.mkdtemp(prefix='kltn-infer-')
        try:
            cfg_dir = os.path.join(workdir, 'configs')
            os.makedirs(cfg_dir)
            for name in ('exp.engine', 'exp.onnx', 'labels_custom.txt'):
                open(os.path.join(cfg_dir, name), 'w').close()
            cfg = os.path.join(cfg_dir, 'infer.txt')
            with open(cfg, 'w') as handle:
                handle.write('[property]\nmodel-engine-file=exp.engine\nonnx-file=exp.onnx\n'
                             'labelfile-path=labels_custom.txt\n')
            cwd = os.getcwd()
            os.chdir(workdir)   # CWD khác thư mục config, giống khi agent chạy main.py
            try:
                ensure_infer_config(cfg)
            finally:
                os.chdir(cwd)
            content = open(cfg).read()
            self.assertIn('model-engine-file=%s' % os.path.join(cfg_dir, 'exp.engine'), content)
            self.assertIn('onnx-file=%s' % os.path.join(cfg_dir, 'exp.onnx'), content)
            self.assertIn('labelfile-path=%s' % os.path.join(cfg_dir, 'labels_custom.txt'), content)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


class TestCommandTtl(unittest.TestCase):
    """M8: lệch đồng hồ lớn (Jetson chưa NTP) không được làm mọi lệnh bị 'expired'."""

    def test_expiry_rules(self):
        try:
            from communication.mqtt_client import command_expiry
        except ImportError as error:   # paho-mqtt chưa cài trên máy phát triển
            self.skipTest('paho-mqtt not installed: %s' % error)
        import time
        now = time.time()
        self.assertFalse(command_expiry(now - 5, 30)[0])          # lệnh mới
        self.assertTrue(command_expiry(now - 120, 30)[0])         # lệnh trễ thật
        self.assertFalse(command_expiry(now - 86400 * 400, 30)[0])  # đồng hồ lệch > 1 năm


class TestPipelineSourceTracking(unittest.TestCase):
    """The active source must follow pipeline state and be cleared after stop."""

    def setUp(self):
        from threading import RLock
        from unittest.mock import Mock
        from services.data_store import DataStore

        self.store = DataStore.__new__(DataStore)
        self.store._lock = RLock()
        self.store.nodes = {'edge-1': {'pipeline_running': False}}
        self.store._save_state_cache = Mock()
        self.store.mark_node_telemetry_stale = Mock()

    def test_pipeline_source_is_recorded_and_cleared_on_stop(self):
        self.store.update_pipeline_status(
            'edge-1',
            running=True,
            pid=123,
            source_type='file',
            source_name='traffic.mp4',
        )
        self.assertEqual(self.store.nodes['edge-1']['pipeline_source_type'], 'file')
        self.assertEqual(self.store.nodes['edge-1']['pipeline_source_name'], 'traffic.mp4')

        self.store.update_pipeline_status('edge-1', running=False)
        self.assertIsNone(self.store.nodes['edge-1']['pipeline_source_type'])
        self.assertIsNone(self.store.nodes['edge-1']['pipeline_source_name'])


class TestPreviewRequestIsolation(unittest.TestCase):
    """A missing preview ID must never fall back to another request's frame."""

    def setUp(self):
        from unittest import mock
        fake_store = types.ModuleType('services.data_store')
        fake_store.store = object()
        fake_mqtt = types.ModuleType('services.mqtt_service')
        fake_mqtt.mqtt_service = object()
        fake_ws = types.ModuleType('services.websocket_manager')
        fake_ws.ws_manager = object()
        fake_auth = types.ModuleType('services.auth_middleware')
        fake_auth.require_staff = lambda: None
        patcher = mock.patch.dict(sys.modules, {
            'services.data_store': fake_store,
            'services.mqtt_service': fake_mqtt,
            'services.websocket_manager': fake_ws,
            'services.auth_middleware': fake_auth,
        })
        patcher.start()
        self.addCleanup(patcher.stop)

        spec = importlib.util.spec_from_file_location(
            'remote_control_under_test',
            os.path.join(BACKEND, 'routers', 'remote_control.py'))
        self.remote_control = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.remote_control)
        self.remote_control._preview_cache['preview-old'] = {
            'data': b'old-frame',
            'content_type': 'image/jpeg',
            'expires_at': 9999999999,
            'edge_id': 'edge-1',
        }

    def test_unknown_preview_does_not_return_another_frame(self):
        import asyncio
        result = asyncio.run(
            self.remote_control.get_cached_preview_frame('edge-1', 'preview-new'))
        self.assertEqual(result['status'], 'pending')
        self.assertIsNone(result['preview_url'])

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                self.remote_control.get_preview_image_file('edge-1', 'preview-new'))
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
