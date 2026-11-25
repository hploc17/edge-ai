"""Focused SPI v3 contract and legacy-isolation regressions."""
import unittest

from analytics.traffic_classifier import TrafficAnalyzer
from analytics.traffic_classifier_v3 import classify_traffic_v3, SPITrafficAnalyzer


def snapshot(classes=None):
    classes = classes or {1: 'car', 2: 'car', 3: 'car'}
    counts = {}
    for name in classes.values():
        counts[name] = counts.get(name, 0) + 1
    return dict(current_total=len(classes), current_track_ids=list(classes),
                current_by_class=counts, track_classes=classes,
                track_positions={t: (10, 10) for t in classes})


def speeds(value):
    return {t: {'speed_kmh': value, 'has_moved': False} for t in (1, 2, 3)}


class TestSPIV3(unittest.TestCase):
    def classify(self, values, **kwargs):
        config = dict(vehicle_count=len(values), vehicle_speeds=values,
                      reference_speed_kmh=40)
        config.update(kwargs)
        return classify_traffic_v3(**config)

    def test_boundaries_and_complement(self):
        for speed, state in [(0, 'CONGESTED'), (10, 'CONGESTED'),
                             (10.01, 'SLOW'), (20, 'SLOW'), (20.01, 'FREE')]:
            result = self.classify([speed] * 3)
            self.assertEqual(result['traffic_state'], state)
            self.assertAlmostEqual(result['spi'] + result['speed_reduction_index'], 100)

    def test_median_overrides_aggregate_and_count(self):
        result = self.classify([0, 10, 100, None, -1, float('nan'), float('inf')],
                               average_speed_kmh=90, valid_speed_tracks=99)
        self.assertEqual(result['median_speed_kmh'], 10)
        self.assertEqual(result['valid_speed_tracks'], 3)
        self.assertEqual(result['spi'], 25)
        self.assertEqual(self.classify([0, 10, 20, 100])['median_speed_kmh'], 15)

    def test_raw_ratio_is_not_clamped(self):
        result = self.classify([60] * 3)
        self.assertEqual((result['spi'], result['speed_ratio_percent'],
                          result['congestion_score']), (100, 150, 0))

    def test_unknown_indices_and_minimum(self):
        for ref in (None, 0, -10, float('nan'), float('inf')):
            result = self.classify([20] * 3, reference_speed_kmh=ref)
            self.assertEqual(result['data_quality'], 'CONFIG_REQUIRED')
            self.assertIsNone(result['spi'])
        for values in ([], [10], [10, 10], [None] * 3):
            result = self.classify(values, valid_speed_tracks=99)
            self.assertEqual(result['traffic_state'], 'UNKNOWN')
            self.assertIsNone(result['speed_reduction_index'])
            self.assertEqual(result['congestion_score'], 0)
        self.assertEqual(self.classify([10], minimum_valid_tracks=1)['data_quality'], 'VALID')
        self.assertEqual(self.classify([])['data_quality'], 'EMPTY')

    def test_ffs_is_independent_and_optional(self):
        result = self.classify([20] * 3)
        self.assertIsNone(result['hcm_los_proxy'])
        proxy = self.classify([20] * 3, free_flow_speed_kmh=20)
        self.assertEqual(proxy['hcm_los_proxy'], 'A')
        self.assertEqual(proxy['spi'], result['spi'])
        self.assertFalse(proxy['hcm_los_proxy_is_official'])
        self.assertEqual(proxy['spi_thresholds']['free_above_percent'], 50)

    def test_stationary_queue_and_temporal_states(self):
        analyzer = SPITrafficAnalyzer(100, 1, 40, status_confirm_seconds=10,
                                      ignore_never_moved=True)
        first = analyzer.analyze(0, snapshot(), speeds(0))
        self.assertEqual(first['raw_traffic_state'], 'CONGESTED')
        self.assertEqual(first['stable_traffic_state'], 'UNKNOWN')
        self.assertEqual(first['congestion_score'], 0)
        self.assertTrue(first['status_pending'])
        self.assertEqual(first['stopped_vehicle_count'], 3)
        for t in range(1, 11):
            settled = analyzer.analyze(t, snapshot(), speeds(0))
        self.assertEqual(settled['traffic_status'], 'CONGESTED')
        changed = analyzer.analyze(11, snapshot(), speeds(40))
        self.assertEqual(changed['raw_traffic_state'], 'FREE')
        self.assertEqual(changed['stable_traffic_state'], 'CONGESTED')
        unknown = analyzer.analyze(12, snapshot(), {})
        self.assertEqual(unknown['traffic_status'], 'UNKNOWN')
        self.assertEqual(unknown['congestion_score'], 0)

    def test_roi_exclusions_fire_and_invalid_samples(self):
        analyzer = SPITrafficAnalyzer(100, 1, 40, status_confirm_seconds=0,
            exclusion_polygons=[[(90, 90), (110, 90), (110, 110), (90, 110)]])
        pres = snapshot({1: 'car', 2: 'car', 3: 'car', 4: 'truck', 5: 'vehicle_fire'})
        pres['track_positions'][4] = (100, 100)
        obs = speeds(0)
        obs.update({t: {'speed_kmh': 100} for t in (4, 5, 99)})
        result = analyzer.analyze(0, pres, obs)
        self.assertEqual(result['current_vehicle_count'], 3)
        self.assertEqual(result['valid_speed_tracks'], 3)
        self.assertEqual(result['spi'], 0)
        self.assertNotIn('vehicle_fire', result['counts_by_class'])
        obs[1]['speed_kmh'] = float('nan')
        self.assertEqual(analyzer.analyze(1, pres, obs)['data_quality'], 'INSUFFICIENT_DATA')
        self.assertIn('vehicle_fire', pres['current_by_class'])  # Input unmodified.

    def test_pcu_weights_do_not_change_legacy(self):
        pres = snapshot({1: 'bicycle', 2: 'motorbike', 3: 'car', 4: 'truck', 5: 'bus'})
        v3 = SPITrafficAnalyzer(1000, 1, 40).analyze(0, pres, speeds(20))
        legacy = TrafficAnalyzer(1000, 1).analyze(0, pres, speeds(20))
        self.assertEqual(v3['density_pcu_per_km_lane'], 6)
        self.assertEqual(legacy['density_pcu_per_km_lane'], 5.3)
        self.assertEqual(v3['pce'], 6)

    def test_forecast_extrapolates_only_valid_v3_scores(self):
        analyzer = SPITrafficAnalyzer(100, 1, 40, forecast_minimum_history_seconds=10)
        for t in range(11):
            result = analyzer.analyze(t, snapshot(), speeds(40 * (1 - t / 1000)))
        forecast = result['forecast']
        self.assertTrue(forecast['ready'])
        self.assertAlmostEqual(forecast['horizons']['5m']['congestion_score'], 31)
        self.assertAlmostEqual(forecast['horizons']['10m']['congestion_score'], 61)
        self.assertEqual(forecast['horizons']['10m']['status'], 'SLOW')
        self.assertAlmostEqual(forecast['r_squared'], 1)
        self.assertEqual(forecast['confidence'], 'HIGH')
        self.assertIs(analyzer.analyze(10.5, snapshot(), speeds(39))['forecast'], forecast)
        self.assertEqual(len(analyzer._score_history), 0)
        analyzer.analyze(11, snapshot(), {})
        self.assertEqual(len(analyzer._v3_history), 0)
        analyzer.analyze(11.1, snapshot(), speeds(30))
        analyzer.analyze(11.2, snapshot(), speeds(30))
        self.assertEqual(len(analyzer._v3_history), 1)
        self.assertFalse(analyzer.analyze(1000, snapshot(), {})['forecast']['ready'])
        self.assertEqual(len(analyzer._v3_history), 0)

    def test_disabled_forecast_and_threshold_telemetry(self):
        analyzer = SPITrafficAnalyzer(100, 1, 40, forecast_enabled=False,
            status_confirm_seconds=0, free_speed_ratio_min_percent=50,
            congested_speed_ratio_max_percent=25)
        result = analyzer.analyze(0, snapshot(), speeds(22))
        self.assertEqual(result['traffic_status'], 'FREE')
        self.assertEqual(result['spi_thresholds']['free_above_percent'], 50)
        self.assertEqual(result['score_thresholds'], {'free_max': 50, 'slow_max': 75})
        self.assertEqual(result['representative_speed_kmh'], 22)
        self.assertEqual(result['representative_speed_method'], 'median')
        self.assertEqual(result['raw_traffic_status'], result['raw_traffic_state'])
        self.assertEqual(result['forecast']['reason'], 'Disabled')

    def test_noncanonical_thresholds_require_config_without_constructor_crash(self):
        for key in ('free_speed_ratio_min_percent', 'congested_speed_ratio_max_percent'):
            for value in (60, 30, -1, None, 'bad', float('nan'), float('inf')):
                with self.subTest(key=key, value=value):
                    config = {key: value}
                    direct = self.classify([20] * 3, **config)
                    analyzer = SPITrafficAnalyzer(100, 1, 40, **config)
                    adapted = analyzer.analyze(0, snapshot(), speeds(20))
                    for result in (direct, adapted):
                        self.assertEqual(result['data_quality'], 'CONFIG_REQUIRED')
                        self.assertIn('50/25', result['reason'])
                        self.assertIsNone(result['spi'])
                        self.assertEqual(result['congestion_score'], 0)
                        self.assertEqual(result['score_thresholds'], {'free_max': 50, 'slow_max': 75})

    def test_gap_and_timestamp_reset_restart_persistence_and_forecast(self):
        analyzer = SPITrafficAnalyzer(100, 1, 40, status_confirm_seconds=2,
                                      forecast_minimum_history_seconds=10)
        for t in range(11):
            result = analyzer.analyze(t, snapshot(), speeds(10))
        self.assertTrue(result['forecast']['ready'])
        self.assertIsNone(result['forecast']['r_squared'])
        self.assertEqual(result['forecast']['confidence'], 'UNDEFINED')
        for t in (20, 0):
            result = analyzer.analyze(t, snapshot(), speeds(10))
            self.assertEqual(result['traffic_status'], 'UNKNOWN')
            self.assertEqual(result['status_pending_seconds'], 0)
            self.assertFalse(result['forecast']['ready'])
            self.assertEqual(len(analyzer._v3_history), 1)

    def test_missing_roi_ids_cannot_use_camera_wide_speeds(self):
        pres = snapshot()
        del pres['current_track_ids']
        result = SPITrafficAnalyzer(100, 1, 40).analyze(0, pres, speeds(40))
        self.assertIsNone(result['spi'])
        self.assertEqual(result['valid_speed_tracks'], 0)


if __name__ == '__main__':
    unittest.main()
