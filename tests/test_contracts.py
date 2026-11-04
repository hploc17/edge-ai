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


if __name__ == '__main__':
    unittest.main()
