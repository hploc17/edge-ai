#!/usr/bin/env python3
"""Context-Aware & Dwell-Time Traffic Classifier (Phương án 2).

Nâng cấp thuật toán phân loại ùn tắc dựa trên:
1. Phân biệt ngữ cảnh: Nút giao có đèn (Signalized) vs Đoạn đường không đèn (Mid-block).
2. Thời gian lưu (Dwell Time): T_dwell = t_current - t_entry của từng track trong ROI.
3. Ân hạn đèn đỏ hợp pháp: 0 - 30 giây giữ nhãn FREE (HCM 2010 Chương 18 & Webster).
4. Low Vehicle Count Guard: Ngăn ngừa bùng nổ mật độ ảo trên đoạn ROI ngắn khi đường vắng.
5. Lọc xe đỗ tĩnh: has_moved >= 1.5m để loại bỏ xe đỗ lề đường.

Tương thích hoàn toàn với Python 3.6 (JetPack 4.x) và Python 3.11+.
Giữ nguyên giao diện (Interface) với TrafficAnalyzer và WebGIS.
"""

from __future__ import print_function

import math
import os
import time
from collections import deque

import numpy as np

from analytics.traffic_classifier import (
    TrafficAnalyzer,
    TrafficStateModel,
)


class ContextAwareTrafficStateModel(TrafficStateModel):
    """Mô hình phân loại ùn tắc theo ngữ cảnh và thời gian lưu (Dwell-Time).

    Ngữ cảnh:
      - 'signalized': Nút giao có đèn tín hiệu (có thời gian chờ đèn ân hạn 0 - 30s)
      - 'midblock': Đoạn đường thông thường không đèn (ngưỡng dwell-time ngắn 0 - 5s)
    """

    CONTEXT_SIGNALIZED = 'signalized'
    CONTEXT_MIDBLOCK = 'midblock'

    def __init__(self,
                 context='signalized',
                 signalized_grace_period_s=30.0,
                 signalized_slow_threshold_s=55.0,
                 midblock_free_threshold_s=5.0,
                 midblock_slow_threshold_s=15.0,
                 stopped_speed_kmh=5.0,
                 congested_speed_kmh=10.0,
                 slow_speed_kmh=18.0,
                 slow_density_veh_per_km_lane=140.0,
                 congested_density_veh_per_km_lane=220.0,
                 free_speed_kmh=22.0,
                 free_max_score=30.0,
                 slow_min_score=35.0,
                 slow_max_score=64.0,
                 congested_min_score=65.0):
        super(ContextAwareTrafficStateModel, self).__init__(
            stopped_speed_kmh=stopped_speed_kmh,
            congested_speed_kmh=congested_speed_kmh,
            slow_speed_kmh=slow_speed_kmh,
            slow_density_veh_per_km_lane=slow_density_veh_per_km_lane,
            congested_density_veh_per_km_lane=congested_density_veh_per_km_lane,
            free_speed_kmh=free_speed_kmh,
            free_max_score=free_max_score,
            slow_min_score=slow_min_score,
            slow_max_score=slow_max_score,
            congested_min_score=congested_min_score,
        )
        self.context = str(context).lower().strip()
        if self.context not in (self.CONTEXT_SIGNALIZED, self.CONTEXT_MIDBLOCK):
            self.context = self.CONTEXT_SIGNALIZED

        self.signalized_grace_s = float(signalized_grace_period_s)
        self.signalized_slow_s = float(signalized_slow_threshold_s)
        self.midblock_free_s = float(midblock_free_threshold_s)
        self.midblock_slow_s = float(midblock_slow_threshold_s)

        # Lưu vết thời điểm vào ROI của từng track_id: {track_id: entry_time}
        self._track_entry_times = {}
        # Lưu vết dwell-time gần nhất để báo cáo telemetry
        self._last_dwell_stats = {
            'max_dwell_s': 0.0,
            'mean_dwell_s': 0.0,
            'stopped_dwell_max_s': 0.0,
            'tracked_in_roi_count': 0,
        }

    def update_dwell_times(self, active_track_ids, timestamp, stopped_track_ids=None):
        """Cập nhật dwell time cho các xe đang hiện diện trong Analysis ROI."""
        now = float(timestamp)
        active_set = set(int(t) for t in active_track_ids) if active_track_ids else set()
        stopped_set = set(int(t) for t in stopped_track_ids) if stopped_track_ids else set()

        # Đăng ký entry_time cho các xe mới vào ROI
        for tid in active_set:
            if tid not in self._track_entry_times:
                self._track_entry_times[tid] = now

        # Dọn dẹp các track đã rời khỏi ROI
        prune_ids = [tid for tid in self._track_entry_times if tid not in active_set]
        for tid in prune_ids:
            del self._track_entry_times[tid]

        # Tính toán thống kê Dwell Time
        if not active_set:
            self._last_dwell_stats = {
                'max_dwell_s': 0.0,
                'mean_dwell_s': 0.0,
                'stopped_dwell_max_s': 0.0,
                'tracked_in_roi_count': 0,
            }
            return self._last_dwell_stats

        dwell_list = [now - self._track_entry_times[tid] for tid in active_set if tid in self._track_entry_times]
        stopped_dwell_list = [
            now - self._track_entry_times[tid]
            for tid in stopped_set
            if tid in self._track_entry_times
        ]

        max_dwell = max(dwell_list) if dwell_list else 0.0
        mean_dwell = (sum(dwell_list) / float(len(dwell_list))) if dwell_list else 0.0
        stopped_max = max(stopped_dwell_list) if stopped_dwell_list else 0.0

        self._last_dwell_stats = {
            'max_dwell_s': round(max_dwell, 1),
            'mean_dwell_s': round(mean_dwell, 1),
            'stopped_dwell_max_s': round(stopped_max, 1),
            'tracked_in_roi_count': len(active_set),
        }
        return self._last_dwell_stats

    def classify(self, avg_speed_kmh, density, stopped_ratio, timestamp=None,
                 median_speed_kmh=None, vehicle_count=None, max_speed_kmh=None,
                 dwell_stats=None):
        """Phân loại trạng thái có xét đến Dwell Time & Ngữ cảnh đèn tín hiệu."""
        if timestamp is None:
            timestamp = time.time()

        if dwell_stats is not None:
            stats = dwell_stats
        else:
            stats = self._last_dwell_stats

        raw = self._raw_classify_v2(
            avg_speed_kmh, density, stopped_ratio,
            median_speed_kmh=median_speed_kmh,
            vehicle_count=vehicle_count,
            max_speed_kmh=max_speed_kmh,
            dwell_stats=stats,
        )
        self._state_history.append((float(timestamp), raw))

        # Cửa sổ làm mượt 10s
        cutoff = timestamp - self.SMOOTH_WINDOW_S
        while self._state_history and self._state_history[0][0] < cutoff:
            self._state_history.popleft()

        counts = {self.FREE: 0, self.SLOW: 0, self.CONGESTED: 0, self.UNKNOWN: 0}
        for _, s in self._state_history:
            counts[s] = counts.get(s, 0) + 1
        smooth = max(counts, key=counts.get)
        self._current_smooth = smooth

        score = self._congestion_score_v2(
            avg_speed_kmh, density, stopped_ratio,
            state=smooth,
            median_speed_kmh=median_speed_kmh,
            vehicle_count=vehicle_count,
            dwell_stats=stats,
        )
        return smooth, score

    def _raw_classify_v2(self, avg_speed_kmh, density, stopped_ratio,
                         median_speed_kmh=None, vehicle_count=None,
                         max_speed_kmh=None, dwell_stats=None):
        effective_speed = median_speed_kmh if median_speed_kmh is not None else avg_speed_kmh
        if effective_speed is None:
            return self.UNKNOWN

        stats = dwell_stats or self._last_dwell_stats
        max_dwell = stats.get('max_dwell_s', 0.0)
        stopped_max_dwell = stats.get('stopped_dwell_max_s', 0.0)

        # -------------------------------------------------------------
        # BẢO VỆ 1: Low Vehicle Count Guard & Stationary Incident (Fix A3)
        # -------------------------------------------------------------
        if vehicle_count is not None:
            if vehicle_count <= 2:
                # Nếu có xe đứng yên (tai nạn/chết máy) kéo dài vượt ngưỡng -> SLOW
                if vehicle_count > 0 and stopped_ratio >= 0.50:
                    if stopped_max_dwell >= self.stationary_incident_threshold_s:
                        self._incident_detected = True
                        return self.SLOW
                else:
                    self._incident_detected = False
                return self.FREE
            if vehicle_count <= 4 and density < self.slow_density:
                if max_speed_kmh is not None and max_speed_kmh >= 20.0:
                    return self.FREE
                if stopped_ratio >= 0.50 and max_dwell > self.midblock_slow_s:
                    return self.SLOW
                return self.FREE

        # -------------------------------------------------------------
        # BẢO VỆ 2: Gating Dwell Time theo ngữ cảnh (Nút giao vs Đoạn không đèn)
        # -------------------------------------------------------------
        if self.context == self.CONTEXT_SIGNALIZED:
            # A. Nút giao có đèn: Ân hạn thời gian chờ đèn đỏ (0 - 30 giây)
            if stopped_max_dwell <= self.signalized_grace_s:
                # Trong thời gian đèn đỏ hợp pháp, nếu xe trôi hoặc dừng bình thường -> FREE
                if effective_speed >= self.free_speed_kmh or stopped_ratio < 0.15:
                    return self.FREE
                # Nếu dừng chờ đèn đỏ tập trung nhưng chưa quá 30s -> FREE (không phạt kẹt xe)
                if stopped_max_dwell <= self.signalized_grace_s and max_dwell <= self.signalized_slow_s:
                    return self.FREE
            elif stopped_max_dwell <= self.signalized_slow_s:
                # 30s - 55s: Dòng xe chờ lâu hơn 1 chu kỳ ngắn, có dấu hiệu dồn dịch -> SLOW
                return self.SLOW
            else:
                # > 55s: Xe dừng đỗ vượt quá 1 chu kỳ đèn đỏ (> 1 phút)
                if stopped_ratio >= 0.30 or density >= self.slow_density:
                    return self.CONGESTED
                return self.SLOW
        else:
            # B. Đoạn đường không đèn (Mid-block)
            if max_dwell <= self.midblock_free_s:
                # 0 - 5 giây: Xe đi qua bình thường trên đoạn 15-20m -> FREE
                return self.FREE
            elif max_dwell <= self.midblock_slow_s:
                # 5 - 15 giây: Xe đi chậm bất thường -> SLOW
                return self.SLOW
            else:
                # > 15 giây: Dừng hẳn hoặc nghẽn trên đoạn không đèn -> CONGESTED
                if stopped_ratio >= 0.25 or effective_speed <= self.congested_speed_kmh:
                    return self.CONGESTED
                return self.SLOW

        # -------------------------------------------------------------
        # BẢO VỆ 3: Ưu tiên Dòng trôi thoát tự do (Free-Flow Override)
        # -------------------------------------------------------------
        if effective_speed >= self.free_speed_kmh and stopped_ratio < 0.15:
            return self.FREE

        # -------------------------------------------------------------
        # BẢO VỆ 4: Gating theo tỷ lệ dừng (Stop Ratio Gating)
        # Nếu tỷ lệ dừng < 15%, không bao giờ gán CONGESTED
        # -------------------------------------------------------------
        if stopped_ratio < 0.15 and effective_speed >= self.congested_speed_kmh:
            return self.SLOW

        # Tiêu chí kẹt xe nghiêm trọng
        speed_congested = effective_speed <= self.congested_speed_kmh
        density_congested = density >= self.congested_density
        stopped_heavy = stopped_ratio >= 0.30

        if (speed_congested or stopped_heavy) and (density_congested or stopped_ratio >= 0.40):
            return self.CONGESTED

        return self.SLOW

    def _congestion_score_v2(self, avg_speed_kmh, density, stopped_ratio,
                             state=None, median_speed_kmh=None,
                             vehicle_count=None, dwell_stats=None):
        """Tính điểm kẹt xe có khóa chặn ngữ cảnh và Dwell Time."""
        effective_speed = median_speed_kmh if median_speed_kmh is not None else avg_speed_kmh
        stats = dwell_stats or self._last_dwell_stats

        # Bảo vệ số lượng xe thấp (Fix A3: nếu phát hiện sự cố đứng yên, phản ánh điểm cảnh báo)
        if vehicle_count is not None and vehicle_count <= 2:
            if getattr(self, '_incident_detected', False):
                return 45  # Mức điểm cảnh báo SLOW (35-65) khi phát hiện sự cố đứng yên kéo dài
            return min(15, int(round(stopped_ratio * 15.0)))

        # Thành phần 1: Vận tốc (0 - 50 điểm) - Speed Reduction Index
        score = 0.0
        if effective_speed is not None:
            speed_ref = max(self.free_speed_kmh, 25.0)
            speed_score = max(0.0, 50.0 * (1.0 - effective_speed / speed_ref))
            score += min(50.0, speed_score)
        else:
            score += 15.0

        # Thành phần 2: Tỷ lệ dừng (0 - 30 điểm)
        # Nếu đang trong thời gian ân hạn đèn đỏ ở nút giao, giảm bớt điểm phạt dừng
        stopped_dwell = stats.get('stopped_dwell_max_s', 0.0)
        if self.context == self.CONTEXT_SIGNALIZED and stopped_dwell <= self.signalized_grace_s:
            # Trong 30s đèn đỏ đầu tiên, tỷ lệ dừng không bị phạt tối đa
            effective_stopped_ratio = stopped_ratio * 0.3
        else:
            effective_stopped_ratio = stopped_ratio

        stopped_score = min(30.0, 30.0 * (effective_stopped_ratio / 0.35))
        score += stopped_score

        # Thành phần 3: Mật độ quy đổi PCE (0 - 20 điểm) - Jam Density Ratio
        if self.congested_density > 0:
            density_score = min(20.0, 20.0 * (density / self.congested_density))
            score += density_score

        # Khóa chặn điểm số đồng bộ với nhãn trạng thái (Tránh mâu thuẫn điểm - nhãn)
        if state == self.FREE:
            # FREE: 0 - 30 điểm
            if self.context == self.CONTEXT_SIGNALIZED and stopped_dwell <= self.signalized_grace_s:
                score = min(25.0, score)
            else:
                score = min(float(self.free_max_score), score)
        elif state == self.SLOW:
            # SLOW: 35 - 64 điểm
            score = max(float(self.slow_min_score), min(float(self.slow_max_score), score))
        elif state == self.CONGESTED:
            # CONGESTED: 65 - 100 điểm
            score = max(float(self.congested_min_score), score)

        return int(round(min(100.0, max(0.0, score))))


class ContextAwareTrafficAnalyzer(TrafficAnalyzer):
    """TrafficAnalyzer nâng cấp: Tự động trích xuất track_id và cập nhật Dwell Time."""

    def __init__(self, road_length_m, lane_count,
                 state_model=None,
                 forecast_history_seconds=900.0,
                 forecast_minimum_history_seconds=300.0,
                 exclusion_polygons=None,
                 ignore_never_moved=True):
        if state_model is None:
            state_model = ContextAwareTrafficStateModel()
        super(ContextAwareTrafficAnalyzer, self).__init__(
            road_length_m=road_length_m,
            lane_count=lane_count,
            state_model=state_model,
            forecast_history_seconds=forecast_history_seconds,
            forecast_minimum_history_seconds=forecast_minimum_history_seconds,
            exclusion_polygons=exclusion_polygons,
            ignore_never_moved=ignore_never_moved,
        )

    def analyze(self, timestamp, presence_snapshot, speeds):
        """Phân tích giao thông có tích hợp Dwell-Time và lọc xe di chuyển >= 1.5m."""
        roi_track_ids = presence_snapshot.get('current_track_ids')
        active_ids = set(roi_track_ids) if roi_track_ids else set(speeds.keys())

        # Lọc các xe dừng: vận tốc < 5.0 km/h
        stopped_ids = set()
        for tid in active_ids:
            sp_info = speeds.get(tid)
            if sp_info is not None:
                sp_val = sp_info.get('speed_kmh') if isinstance(sp_info, dict) else sp_info
                if sp_val is not None and float(sp_val) < self._state_model.stopped_speed_kmh:
                    stopped_ids.add(tid)

        # Cập nhật Dwell-Time vào StateModel V2 nếu là ContextAwareTrafficStateModel
        dwell_stats = None
        if hasattr(self._state_model, 'update_dwell_times'):
            dwell_stats = self._state_model.update_dwell_times(
                active_ids, timestamp, stopped_track_ids=stopped_ids
            )

        # Chạy logic analyze cơ bản của lớp cha
        metrics = super(ContextAwareTrafficAnalyzer, self).analyze(
            timestamp, presence_snapshot, speeds
        )

        # Bổ sung các thông số Dwell-Time và thuật toán vào telemetry
        if dwell_stats:
            metrics['dwell_time_avg_s'] = dwell_stats.get('mean_dwell_s', 0.0)
            metrics['max_dwell_s'] = dwell_stats.get('max_dwell_s', 0.0)
            metrics['stopped_dwell_max_s'] = dwell_stats.get('stopped_dwell_max_s', 0.0)
            metrics['traffic_context'] = getattr(self._state_model, 'context', 'signalized')
            metrics['algorithm_version'] = 'v2_dwell_time'

        return metrics
