#!/usr/bin/env python3
"""Reference-speed reduction indicator classifier (V3).

V3 compares observed ROI speed with a configured reference speed.  The
normalized reduction index and its display status bands are project settings;
they are not presented as official HCM LOS criteria.
"""

from __future__ import print_function

import math

from analytics.traffic_classifier import TrafficAnalyzer, TrafficStateModel


def _finite_number(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def spi_level_from_value(spi):
    spi = _finite_number(spi)
    if spi is None:
        return None
    if spi <= 25.0:
        return 'HEAVY_CONGESTION'
    if spi <= 50.0:
        return 'MILD_CONGESTION'
    if spi <= 75.0:
        return 'SMOOTH'
    return 'VERY_SMOOTH'


def spi_state_from_level(level):
    return {
        'HEAVY_CONGESTION': 'CONGESTED',
        'MILD_CONGESTION': 'SLOW',
        'SMOOTH': 'FREE',
        'VERY_SMOOTH': 'FREE',
    }.get(level, 'UNKNOWN')


def classify_traffic_v3(v_avg=None, v_ref=None, vehicle_count=None,
                        stopped_ratio=None, pce=None, vehicle_speeds=None,
                        average_speed_kmh=None, reference_speed_kmh=None,
                        valid_speed_tracks=None, minimum_valid_tracks=1,
                        signalized=None, dwell_stats=None,
                        free_speed_ratio_min_percent=65.0,
                        congested_speed_ratio_max_percent=40.0):
    """Evaluate one window using the configured reference-speed indicator.

    vehicle_speeds may be a dict {track_id: {'speed_kmh': ...}} or an iterable
    of numeric speeds. Dict entries with has_moved=False are parked/still
    observations and are not used as moving-track evidence.
    """
    if average_speed_kmh is not None:
        v_avg = average_speed_kmh
    if reference_speed_kmh is not None:
        v_ref = reference_speed_kmh

    base = {
        'method': 'REFERENCE_SPEED_REDUCTION_V3',
        'spi': None,
        'spi_level': None,
        'speed_ratio_percent': None,
        'speed_reduction_index': None,
        'traffic_state': 'UNKNOWN',
        'average_speed_kmh': None,
        'reference_speed_kmh': None,
        'vehicle_count': int(vehicle_count or 0),
        'valid_speed_tracks': 0,
        'stopped_ratio': round(max(0.0, min(1.0,
                                             float(stopped_ratio or 0.0))), 3),
        'pce': None if pce is None else float(pce),
        'data_quality': 'CONFIG_REQUIRED',
        'reason': 'Reference speed is not configured',
        'signalized': bool(signalized) if signalized is not None else None,
        'dwell_stats': dwell_stats,
    }

    ref = _finite_number(v_ref)
    if ref is None or ref <= 0.0:
        base['data_quality'] = 'CONFIG_REQUIRED'
        base['reason'] = 'reference_speed_kmh is missing or invalid'
        return base
    base['reference_speed_kmh'] = round(ref, 2)

    count = int(vehicle_count or 0)
    base['vehicle_count'] = count
    if count <= 0:
        base['data_quality'] = 'EMPTY'
        base['reason'] = 'No confirmed vehicles in the Analysis ROI'
        return base

    if vehicle_speeds is not None:
        valid_speeds = []
        if isinstance(vehicle_speeds, dict):
            for tid, info in vehicle_speeds.items():
                if isinstance(info, dict):
                    if info.get('has_moved', True) is False:
                        continue
                    raw = info.get('speed_kmh')
                else:
                    raw = info
                value = _finite_number(raw)
                if value is not None and value >= 0.0:
                    valid_speeds.append(value)
        else:
            for raw in vehicle_speeds:
                value = _finite_number(raw)
                if value is not None and value >= 0.0:
                    valid_speeds.append(value)
        if valid_speed_tracks is None:
            valid_speed_tracks = len(valid_speeds)
        if v_avg is None and valid_speeds:
            v_avg = sum(valid_speeds) / float(len(valid_speeds))

    avg = _finite_number(v_avg)
    try:
        valid_count = int(valid_speed_tracks or 0)
    except (TypeError, ValueError, OverflowError):
        valid_count = 0
    base['valid_speed_tracks'] = valid_count

    if avg is None:
        base['data_quality'] = 'INSUFFICIENT_DATA'
        base['reason'] = 'No finite vehicle speed values'
        return base
    if avg < 0.0:
        base['data_quality'] = 'INVALID_SPEED'
        base['reason'] = 'Average speed is negative'
        return base

    minimum = max(1, int(minimum_valid_tracks or 1))
    if valid_count < minimum:
        base['data_quality'] = 'INSUFFICIENT_DATA'
        base['reason'] = (
            'Only %d valid speed track(s); %d required'
            % (valid_count, minimum)
        )
        return base

    free_threshold = _finite_number(free_speed_ratio_min_percent)
    congested_threshold = _finite_number(congested_speed_ratio_max_percent)
    if (free_threshold is None or congested_threshold is None or
            congested_threshold < 0.0 or congested_threshold > 100.0 or
            free_threshold < 0.0 or free_threshold > 100.0 or
            congested_threshold >= free_threshold):
        base['data_quality'] = 'CONFIG_REQUIRED'
        base['reason'] = 'Speed-ratio display thresholds are invalid'
        return base

    # SPI is bounded to 0..100.
    raw_ratio = 100.0 * avg / ref
    speed_ratio = max(0.0, min(100.0, raw_ratio))
    reduction_index = max(0.0, min(100.0, 100.0 - speed_ratio))
    level = spi_level_from_value(speed_ratio)
    state = spi_state_from_level(level)
    base.update({
        'spi': round(speed_ratio, 2),
        'spi_level': level,
        'speed_ratio_percent': round(raw_ratio, 2),
        'speed_reduction_index': round(reduction_index, 2),
        'traffic_state': state,
        'average_speed_kmh': round(avg, 2),
        'valid_speed_tracks': valid_count,
        'data_quality': 'VALID',
        'reason': None,
    })
    return base


class SPITrafficStateModel(TrafficStateModel):
    """Minimal state model adapter for the existing TrafficAnalyzer."""

    UNKNOWN = 'UNKNOWN'
    FREE = 'FREE'
    SLOW = 'SLOW'
    CONGESTED = 'CONGESTED'

    def __init__(self, reference_speed_kmh=None, minimum_valid_tracks=1,
                 ignore_never_moved=True, free_speed_ratio_min_percent=65.0,
                 congested_speed_ratio_max_percent=40.0,
                 status_confirm_seconds=10.0):
        super(SPITrafficStateModel, self).__init__()
        self.reference_speed_kmh = reference_speed_kmh
        self.minimum_valid_tracks = int(minimum_valid_tracks)
        self.ignore_never_moved = bool(ignore_never_moved)
        self.free_speed_ratio_min_percent = float(free_speed_ratio_min_percent)
        self.congested_speed_ratio_max_percent = float(congested_speed_ratio_max_percent)
        self.status_confirm_seconds = max(0.0, float(status_confirm_seconds))
        self.last_result = None
        self._stable_state = self.UNKNOWN
        self._candidate_state = None
        self._candidate_since = None

    def apply_temporal_persistence(self, result, timestamp):
        """Confirm a changed state only after it persists for configured time."""
        proposed = result.get('traffic_state')
        now = float(timestamp)
        if result.get('data_quality') != 'VALID' or proposed not in (
                self.FREE, self.SLOW, self.CONGESTED):
            self._candidate_state = None
            self._candidate_since = None
            result['traffic_state'] = self.UNKNOWN
            result['status_pending'] = False
            return result

        if proposed == self._stable_state:
            self._candidate_state = None
            self._candidate_since = None
            result['status_pending'] = False
            return result

        if proposed != self._candidate_state:
            self._candidate_state = proposed
            self._candidate_since = now

        candidate_since = self._candidate_since if self._candidate_since is not None else now
        elapsed = max(0.0, now - candidate_since)
        if elapsed >= self.status_confirm_seconds:
            self._stable_state = proposed
            self._candidate_state = None
            self._candidate_since = None
            result['status_pending'] = False
        else:
            result['status_pending'] = True
            proposed = self._stable_state if self._stable_state != self.UNKNOWN else self.UNKNOWN
        result['traffic_state'] = proposed
        result['status_pending_seconds'] = round(elapsed, 2)
        return result

    def classify(self, avg_speed_kmh, density, stopped_ratio, timestamp=None,
                 median_speed_kmh=None, vehicle_count=None, max_speed_kmh=None,
                 vehicle_speeds=None, valid_speed_tracks=None, pce=None,
                 signalized=None, dwell_stats=None):
        self.last_result = classify_traffic_v3(
            average_speed_kmh=median_speed_kmh if median_speed_kmh is not None else avg_speed_kmh,
            reference_speed_kmh=self.reference_speed_kmh,
            vehicle_count=vehicle_count,
            stopped_ratio=stopped_ratio,
            pce=pce,
            vehicle_speeds=vehicle_speeds,
            valid_speed_tracks=(valid_speed_tracks if valid_speed_tracks is not None
                                else (1 if median_speed_kmh is not None or avg_speed_kmh is not None else 0)),
            minimum_valid_tracks=self.minimum_valid_tracks,
            signalized=signalized,
            dwell_stats=dwell_stats,
            free_speed_ratio_min_percent=self.free_speed_ratio_min_percent,
            congested_speed_ratio_max_percent=self.congested_speed_ratio_max_percent,
        )
        state = self.last_result['traffic_state']
        if state not in (self.FREE, self.SLOW, self.CONGESTED):
            state = self.UNKNOWN
        # The concrete analyzer replaces this preliminary classification with
        # one that includes the exact number of valid speed tracks.
        return state, 0


class SPITrafficAnalyzer(TrafficAnalyzer):
    """TrafficAnalyzer adapter that preserves existing geometry and telemetry."""

    def __init__(self, road_length_m, lane_count, reference_speed_kmh=None,
                 minimum_valid_tracks=1, state_model=None,
                 free_speed_ratio_min_percent=65.0,
                 congested_speed_ratio_max_percent=40.0,
                 status_confirm_seconds=10.0,
                 forecast_history_seconds=900.0,
                 forecast_minimum_history_seconds=300.0,
                 exclusion_polygons=None, ignore_never_moved=True,
                 traffic_context=None):
        if state_model is None:
            state_model = SPITrafficStateModel(
                reference_speed_kmh=reference_speed_kmh,
                minimum_valid_tracks=minimum_valid_tracks,
                ignore_never_moved=ignore_never_moved,
                free_speed_ratio_min_percent=free_speed_ratio_min_percent,
                congested_speed_ratio_max_percent=congested_speed_ratio_max_percent,
                status_confirm_seconds=status_confirm_seconds,
            )
        super(SPITrafficAnalyzer, self).__init__(
            road_length_m=road_length_m,
            lane_count=lane_count,
            state_model=state_model,
            forecast_history_seconds=forecast_history_seconds,
            forecast_minimum_history_seconds=forecast_minimum_history_seconds,
            exclusion_polygons=exclusion_polygons,
            ignore_never_moved=ignore_never_moved,
        )
        self.traffic_context = traffic_context

    def analyze(self, timestamp, presence_snapshot, speeds):
        metrics = super(SPITrafficAnalyzer, self).analyze(
            timestamp, presence_snapshot, speeds
        )
        # Super.analyze has already filtered to ROI and excluded IDs.
        roi_ids = presence_snapshot.get('current_track_ids')
        if roi_ids is not None:
            excluded = self.excluded_track_ids(presence_snapshot)
            roi_speeds = {
                tid: info for tid, info in speeds.items()
                if int(tid) in (set(int(t) for t in roi_ids) - excluded)
            }
        else:
            roi_speeds = speeds

        valid_speeds = []
        for tid, info in roi_speeds.items():
            if not isinstance(info, dict):
                continue
            if self._ignore_never_moved and not info.get('has_moved', True):
                continue
            value = _finite_number(info.get('speed_kmh'))
            if value is not None and value >= 0.0:
                valid_speeds.append(value)

        result = classify_traffic_v3(
            average_speed_kmh=metrics.get('avg_speed_kmh'),
            reference_speed_kmh=getattr(
                self._state_model, 'reference_speed_kmh', None
            ),
            vehicle_count=metrics.get('current_vehicle_count'),
            stopped_ratio=metrics.get('stopped_vehicle_ratio'),
            # Keep PCE outside this speed-only classifier. The existing shared
            # analyzer's PCE weights are legacy values and cannot be claimed
            # as TCVN 13592:2022 for generic bus/truck labels.
            pce=None,
            vehicle_speeds=roi_speeds,
            valid_speed_tracks=len(valid_speeds),
            minimum_valid_tracks=getattr(
                self._state_model, 'minimum_valid_tracks', 1
            ),
            signalized=(
                self.traffic_context == 'signalized'
                if self.traffic_context is not None else None
            ),
            free_speed_ratio_min_percent=self._state_model.free_speed_ratio_min_percent,
            congested_speed_ratio_max_percent=self._state_model.congested_speed_ratio_max_percent,
        )

        result = self._state_model.apply_temporal_persistence(result, timestamp)
        self._state_model.last_result = result

        mapped_state = result['traffic_state']
        metrics['traffic_status'] = (
            mapped_state if mapped_state in ('FREE', 'SLOW', 'CONGESTED')
            else 'UNKNOWN'
        )
        # Additive V3 fields; no SPI value is written into congestion_score.
        metrics['method'] = 'REFERENCE_SPEED_REDUCTION_V3'
        metrics['spi'] = result['spi']
        metrics['spi_level'] = result['spi_level']
        metrics['speed_ratio_percent'] = result['speed_ratio_percent']
        metrics['speed_reduction_index'] = result['speed_reduction_index']
        metrics['traffic_state'] = result['traffic_state']
        metrics['reference_speed_kmh'] = result['reference_speed_kmh']
        metrics['valid_speed_tracks'] = result['valid_speed_tracks']
        metrics['stopped_vehicle_ratio'] = result['stopped_ratio']
        metrics['stopped_ratio'] = result['stopped_ratio']
        metrics['pce'] = result['pce']
        metrics['data_quality'] = result['data_quality']
        metrics['reason'] = result['reason']
        metrics['status_pending'] = result.get('status_pending', False)
        metrics['status_pending_seconds'] = result.get('status_pending_seconds', 0.0)
        metrics['status_confirm_seconds'] = self._state_model.status_confirm_seconds
        metrics['spi_signalized'] = result['signalized']
        metrics['algorithm_version'] = 'v3'
        metrics['traffic_context'] = self.traffic_context
        # Backward-compatible heatmap field; for V3 this stores a display-only
        # speed-reduction index, not the legacy weighted congestion score.
        metrics['congestion_score'] = result['speed_reduction_index'] or 0
        metrics['forecast'] = {
            'ready': False,
            'reason': 'V3 SPI forecast not implemented',
        }
        return metrics
