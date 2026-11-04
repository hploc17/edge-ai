#!/usr/bin/env python3
"""ROI Presence Counter — tracks vehicles confirmed inside Analysis ROI.

Uses confirmation hysteresis to avoid false counts from jitter.
Compatible with Python 3.6 (JetPack 4.x).
"""

from __future__ import print_function
from collections import Counter
from spatial.geometry_utils import point_in_polygon, bbox_bottom_center


class RoiPresenceCounter(object):
    """Track vehicles currently confirmed inside the Analysis ROI polygon.

    A vehicle is 'confirmed present' after its bottom-center has been inside
    the ROI for enter_confirm_seconds.

    A vehicle is 'confirmed absent' after its bottom-center has been outside
    (or the track is lost) for exit_confirm_seconds.

    A track that disappears from the tracker entirely is removed after
    lost_timeout_seconds regardless of its confirmed state.

    Số đếm theo lớp được TÍNH LẠI từ tập track đang confirmed ở mỗi lần snapshot(),
    lớp của mỗi track là lớp được bỏ phiếu nhiều nhất trong lịch sử của track đó.
    Cách này không bị "trôi" khi detector đổi nhãn của cùng một xe (vd motorbike <-> bicycle).
    """

    def __init__(self, analysis_roi, vehicle_classes,
                 enter_confirm_seconds=0.10,
                 exit_confirm_seconds=0.25,
                 lost_timeout_seconds=1.00):
        self._roi = list(analysis_roi)
        self._vehicle_classes = set(vehicle_classes)
        self._enter_confirm_s = float(enter_confirm_seconds)
        self._exit_confirm_s = float(exit_confirm_seconds)
        self._lost_timeout_s = float(lost_timeout_seconds)

        self._tracks = {}
        self._raw_tracks = 0

    def set_raw_tracks(self, count):
        self._raw_tracks = int(count)

    def update_geometry(self, analysis_roi):
        """Hot-reload new Analysis ROI polygon dynamically."""
        self._roi = list(analysis_roi)
        print("[ROI] RoiPresenceCounter geometry updated to %d points" % len(self._roi))

    def reset(self):
        """Xóa toàn bộ trạng thái track (dùng khi đổi ROI/hiệu chuẩn)."""
        self._tracks.clear()
        self._raw_tracks = 0

    @staticmethod
    def _track_class(state):
        votes = state['class_votes']
        return votes.most_common(1)[0][0] if votes else state['class_name']

    def update(self, detection_objects, timestamp):
        timestamp = float(timestamp)
        events = []
        active_ids = set()

        for obj in detection_objects:
            track_id = int(obj['track_id'])
            class_name = str(obj['class_name'])
            if class_name not in self._vehicle_classes:
                continue

            bbox = obj['bbox']
            point = bbox_bottom_center(bbox)
            in_analysis = point_in_polygon(point, self._roi)
            active_ids.add(track_id)

            state = self._tracks.get(track_id)
            if state is None:
                state = {
                    'class_name': class_name,
                    'class_votes': Counter(),
                    'confirmed': False,
                    'in_roi_since': None,
                    'out_roi_since': None,
                    'last_seen': timestamp,
                    'position': point,
                }
                self._tracks[track_id] = state

            state['last_seen'] = timestamp
            state['class_name'] = class_name
            state['class_votes'][class_name] += 1
            state['position'] = point

            if in_analysis:
                state['out_roi_since'] = None
                if not state['confirmed']:
                    if state['in_roi_since'] is None:
                        state['in_roi_since'] = timestamp
                    elif timestamp - state['in_roi_since'] >= self._enter_confirm_s:
                        state['confirmed'] = True
                        events.append({
                            'event': 'confirmed',
                            'track_id': track_id,
                            'class_name': self._track_class(state),
                            'timestamp': timestamp,
                        })
            else:
                state['in_roi_since'] = None
                if state['confirmed']:
                    if state['out_roi_since'] is None:
                        state['out_roi_since'] = timestamp
                    elif timestamp - state['out_roi_since'] >= self._exit_confirm_s:
                        state['confirmed'] = False
                        state['out_roi_since'] = None
                        events.append({
                            'event': 'released',
                            'track_id': track_id,
                            'class_name': self._track_class(state),
                            'timestamp': timestamp,
                        })

        remove_ids = []
        for track_id, state in self._tracks.items():
            if track_id in active_ids:
                continue
            age = timestamp - state['last_seen']
            if age > self._lost_timeout_s:
                if state['confirmed']:
                    events.append({
                        'event': 'released',
                        'track_id': track_id,
                        'class_name': self._track_class(state),
                        'timestamp': timestamp,
                    })
                remove_ids.append(track_id)

        for track_id in remove_ids:
            del self._tracks[track_id]

        return events

    def snapshot(self):
        by_class = dict((name, 0) for name in sorted(self._vehicle_classes))
        confirmed_ids = []
        track_positions = {}
        track_classes = {}
        for tid, state in self._tracks.items():
            if not state.get('confirmed'):
                continue
            cls = self._track_class(state)
            confirmed_ids.append(tid)
            track_positions[tid] = state['position']
            track_classes[tid] = cls
            if cls in by_class:
                by_class[cls] += 1
        return {
            'current_total': sum(by_class.values()),
            'current_by_class': by_class,
            'current_track_ids': confirmed_ids,
            # Vị trí đáy-giữa bbox (pixel) và lớp của từng track đang confirmed,
            # dùng cho vùng loại trừ (exclusion_polygons) trong TrafficAnalyzer
            'track_positions': track_positions,
            'track_classes': track_classes,
            'raw_tracks': self._raw_tracks,
        }
