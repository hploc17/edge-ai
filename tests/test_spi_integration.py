"""Offline SPI transport/config/store contracts; no broker, devices or real data writes."""
import ast
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_definitions(relative, names, namespace=None):
    """Load exact production definitions without application startup side effects."""
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    tree.body = [n for n in tree.body if getattr(n, 'name', None) in names]
    ns = namespace or {}
    exec(compile(tree, str(ROOT / relative), 'exec'), ns)
    return ns


class SPIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = ROOT / 'webgis/backend/services/data_store.py'
        source = path.read_text(encoding='utf-8').split('\nimport sys\n\n# Singleton instance')[0]
        source = source.replace('Path(__file__).resolve().parent.parent / "data"',
                                'Path(%r)' % self.temp.name)
        self.ns = {'__file__': str(path)}
        exec(compile(source, str(path), 'exec'), self.ns)
        self.store = self.ns['DataStore'](Path(self.temp.name) / 'history.db')
        self.store.nodes = {'edge': {'edge_id': 'edge', 'segment_id': 'seg',
                                     'latitude': 10, 'longitude': 106}}
        self.store.segments = {'seg': {'coordinates': [[106, 10], [106.1, 10.1]]}}

    def metrics(self, status='SLOW', score=60):
        return dict(algorithm_version='v3', traffic_status=status, congestion_score=score,
                    score_thresholds={'free_max': 50, 'slow_max': 75},
                    spi_thresholds={'free_above_percent': 50, 'congested_at_or_below_percent': 25},
                    raw_traffic_state='CONGESTED', stable_traffic_state=status,
                    minimum_valid_tracks=3, hcm_los_proxy_is_official=False,
                    hcm_los_proxy_thresholds={'A': 90}, density_pcu_per_km_lane=12,
                    pcu_weight_basis='PROJECT_ASSUMPTION_NOT_TCVN_VERIFIED',
                    speed_ratio_percent=40, speed_reduction_index=60,
                    valid_speed_tracks=3, status_pending='CONGESTED', status_confirm_seconds=10,
                    raw_traffic_status='CONGESTED', representative_speed_kmh=16,
                    representative_speed_method='median', hcm_los_proxy=None,
                    free_flow_speed_kmh=None, reference_speed_kmh=40)

    def test_mqtt_allowlist_to_store_geojson_and_cache(self):
        ns = load_definitions('communication/mqtt_client.py', {'MQTTPublisher'}, {
            'json': json, 'uuid': __import__('uuid'), '_iso_now': lambda: 'now',
            'CAMERA_ID': 'cam', 'SEGMENT_ID': 'seg', 'ENABLE_EDGE_FORECAST': True})
        publisher = ns['MQTTPublisher'].__new__(ns['MQTTPublisher'])
        publisher._lock = threading.Lock()
        publisher._sequence = 0
        publisher._edge_id = 'edge'
        publisher._topic_telemetry = 'traffic/edge/telemetry'
        publisher.sync_edge_id_from_env = Mock()
        publisher._get_cached_mac = lambda: None
        publisher._publish_raw = Mock()
        metrics = self.metrics()
        metrics['forecast'] = {'ready': False, 'method': 'V3_LINEAR_EXTRAPOLATION'}
        publisher.publish_telemetry(metrics, {})
        payload = json.loads(publisher._publish_raw.call_args[0][1])
        self.store.update_telemetry('edge', payload)
        for key, expected in metrics.items():
            self.assertEqual(payload[key], expected, key)
            self.assertEqual(self.store.nodes['edge'][key], expected, key)
            self.assertEqual(self.store.get_nodes_geojson()['features'][0]['properties'][key], expected, key)
            self.assertEqual(self.store.get_segments_geojson()['features'][0]['properties'][key], expected, key)
        self.store._save_state_cache(force=True)
        cache = json.loads(self.ns['NODE_STATE_CACHE_FILE'].read_text(encoding='utf-8'))
        for key in metrics.keys() - {'traffic_status', 'congestion_score'}:
            self.assertEqual(cache['edge'][key], metrics[key], key)
        self.ns['_save_json_file'](self.ns['APPROVED_NODES_FILE'], self.store.nodes)
        restored = self.ns['DataStore'](Path(self.temp.name) / 'history.db')
        self.assertEqual(restored.nodes['edge']['score_thresholds'], metrics['score_thresholds'])

    def test_unknown_does_not_color_free_or_pollute_valid_average(self):
        for status, score in [('UNKNOWN', 0), ('SLOW', 60), ('UNKNOWN', 0), ('CONGESTED', 80)]:
            self.store.update_telemetry('edge', self.metrics(status, score))
        self.assertEqual(self.store.get_forecast_series('seg')[0]['score'], 70)
        self.store.update_telemetry('edge', self.metrics('UNKNOWN', 0))
        self.assertEqual(self.store.get_forecast_series('seg')[0]['score'], 70)
        self.assertEqual(self.store.get_nodes_geojson()['features'][0]['properties']['marker_color'], '#6B7280')
        self.assertEqual(self.store.get_segments_geojson()['features'][0]['properties']['traffic_color'], '#6B7280')
        self.assertEqual(self.store.get_timeline_records('seg')[0]['traffic_color'], '#6B7280')

    def test_all_unknown_has_no_valid_score(self):
        self.store.update_telemetry('edge', self.metrics('UNKNOWN', 0))
        self.assertIsNone(self.store.get_forecast_series('seg')[0]['score'])

    def test_algorithm_switch_resets_minute_aggregate(self):
        self.store.update_telemetry('edge', dict(self.metrics(score=90), algorithm_version='v2'))
        self.store.update_telemetry('edge', self.metrics(score=60))
        series = self.store.get_forecast_series('seg')
        self.assertEqual(series[0]['score'], 60)
        self.assertEqual(series[0]['algorithm_version'], 'v3')
        self.assertEqual(series[0]['sample_count'], 1)
        self.assertEqual(self.store.get_timeline_records('seg')[0]['algorithm_version'], 'v3')

    def test_saved_null_reference_clears_environment_default(self):
        resolve = load_definitions('main.py', {'resolve_reference_speed'}, {'os': os})['resolve_reference_speed']
        with patch.dict(os.environ, {'SPI_REFERENCE_SPEED_KMH': '45'}):
            self.assertIsNone(resolve(None, {'reference_speed_kmh': None}))
            self.assertEqual(resolve(None, {}), 45)
            self.assertEqual(resolve(30, {'reference_speed_kmh': None}), 30)

    def test_remote_config_validates_then_persists(self):
        from communication import jetson_agent
        points = [[0.1, 0.9], [0.9, 0.9], [0.7, 0.1], [0.3, 0.1]]
        params = dict(detection_roi=points, analysis_roi=points, road_width_m=7,
                      road_length_m=20, algorithm_version='v3', reference_speed_kmh=40,
                      minimum_valid_tracks=3, status_confirm_seconds=0, free_flow_speed_kmh=None)
        remote = str(Path(self.temp.name) / 'remote.json')
        with patch.object(jetson_agent, 'CONFIGS_DIR', self.temp.name), \
             patch.object(jetson_agent, 'REMOTE_ROI_CONFIG', remote):
            handler = jetson_agent.make_set_roi_remote_handler()
            ack = handler({'params': params})
            self.assertIn('persisted', ack)
            self.assertIn('stop then start', ack)
            saved = json.loads(Path(remote).read_text())
            for key in ('algorithm_version', 'reference_speed_kmh', 'minimum_valid_tracks',
                        'status_confirm_seconds', 'free_flow_speed_kmh'):
                self.assertEqual(saved[key], params[key])
            self.assertEqual(saved['free_speed_ratio_min_percent'], 50)
            self.assertEqual(saved['congested_speed_ratio_max_percent'], 25)
            for key, value in [('algorithm_version', 'v4'), ('reference_speed_kmh', 0),
                               ('free_flow_speed_kmh', float('nan')), ('minimum_valid_tracks', 0),
                               ('minimum_valid_tracks', 1.5), ('status_confirm_seconds', -1),
                               ('status_confirm_seconds', float('inf'))]:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    handler({'params': dict(params, **{key: value})})
            self.assertEqual(json.loads(Path(remote).read_text()), saved)

    def test_http_request_validation(self):
        from pydantic import BaseModel, Field, ValidationError
        from typing import List, Optional, Literal
        ns = load_definitions('webgis/backend/routers/remote_control.py', {'SetRoiRequest'},
                              dict(BaseModel=BaseModel, Field=Field, List=List,
                                   Optional=Optional, Literal=Literal, __name__=__name__))
        request = ns['SetRoiRequest']
        roi = dict(detection_roi=[], analysis_roi=[])
        self.assertEqual(request(**roi).minimum_valid_tracks, 3)
        for key, value in [('algorithm_version', 'v4'), ('reference_speed_kmh', -1),
                           ('free_flow_speed_kmh', float('inf')), ('minimum_valid_tracks', 1.5),
                           ('status_confirm_seconds', float('nan'))]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                request(**roi, **{key: value})

    def test_main_algorithm_config_and_intentional_overrides(self):
        resolve = load_definitions('main.py', {'resolve_algorithm_version'}, {'os': os})['resolve_algorithm_version']
        with patch.dict(os.environ, {'TRAFFIC_ALGORITHM_VERSION': ''}):
            self.assertEqual(resolve(None, {'algorithm_version': 'v3'}), 'v3')
            self.assertEqual(resolve(None, {}), 'v2')
            self.assertEqual(resolve('v1', {'algorithm_version': 'v3'}), 'v1')
        with patch.dict(os.environ, {'TRAFFIC_ALGORITHM_VERSION': 'v2'}):
            self.assertEqual(resolve(None, {'algorithm_version': 'v3'}), 'v3')
            self.assertEqual(resolve(None, {}), 'v2')
            self.assertEqual(resolve('v1', {'algorithm_version': 'v3'}), 'v1')

    def test_existing_sqlite_schema_migrates_unknown_safely(self):
        legacy = Path(self.temp.name) / 'legacy.db'
        with sqlite3.connect(str(legacy)) as conn:
            conn.execute('''CREATE TABLE traffic_timeline (
                id INTEGER PRIMARY KEY, segment_id TEXT, minute_bucket TEXT, timestamp TEXT,
                time_str TEXT, road_name TEXT, congestion_score INTEGER, avg_speed_kmh REAL,
                traffic_status TEXT, traffic_color TEXT, vehicle_count INTEGER,
                sample_count INTEGER DEFAULT 1, UNIQUE(segment_id, minute_bucket))''')
            conn.execute("INSERT INTO traffic_timeline(segment_id, minute_bucket, traffic_status, congestion_score) VALUES ('seg','one','UNKNOWN',0)")
        conn.close()
        self.ns['_init_history_db'](legacy)
        with sqlite3.connect(str(legacy)) as conn:
            self.assertEqual(conn.execute('SELECT score_mean, score_sample_count FROM traffic_timeline').fetchone(), (None, 0))
        conn.close()

    def test_http_roi_action_forwards_flat_spi_configuration(self):
        from fastapi import APIRouter, Depends, HTTPException
        from pydantic import BaseModel, Field
        from typing import List, Optional, Literal
        mqtt = Mock()
        ns = load_definitions('webgis/backend/routers/remote_control.py',
                              {'SetRoiRequest', 'set_remote_roi'}, dict(
                                  BaseModel=BaseModel, Field=Field, List=List,
                                  Optional=Optional, Literal=Literal, __name__=__name__,
                                  router=APIRouter(), Depends=Depends, HTTPException=HTTPException,
                                  require_staff=lambda: None, _check_node_exists=lambda _: {},
                                  _new_command_id=lambda _: 'test', mqtt_service=mqtt))
        points = [[0.1, 0.9], [0.9, 0.9], [0.7, 0.1], [0.3, 0.1]]
        req = ns['SetRoiRequest'](detection_roi=points, analysis_roi=points,
                                  road_length_m=20, reference_speed_kmh=40,
                                  free_flow_speed_kmh=55)
        response = asyncio.run(ns['set_remote_roi']('edge', req))
        self.assertTrue(response['restart_required'])
        self.assertEqual(response['status'], 'sent')
        sent = mqtt.publish_command.call_args.kwargs
        self.assertEqual(sent['action'], 'set_roi_remote')
        self.assertEqual(sent['params']['algorithm_version'], 'v3')
        self.assertEqual(sent['params']['reference_speed_kmh'], 40)
        self.assertEqual(sent['params']['free_flow_speed_kmh'], 55)


if __name__ == '__main__':
    unittest.main()
