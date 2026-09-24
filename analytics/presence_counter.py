#!/usr/bin/env python3
"""ROI Presence Counter — tracks vehicles confirmed inside Analysis ROI.

Uses confirmation hysteresis to avoid false counts from jitter.
Compatible with Python 3.6 (JetPack 4.x).
"""

from __future__ import print_function
from collections import defaultdict, deque
from spatial.geometry_utils import point_in_polygon, bbox_bottom_center


class RoiPresenceCounter(object):
    """Track vehicles currently confirmed inside the Analysis ROI polygon.

    A vehicle is 'confirmed present' after its bottom-center has been inside
    the ROI for enter_confirm_seconds.

    A vehicle is 'confirmed absent' after its bottom-center has been outside
    (or the track is lost) for exit_confirm_seconds.

    A track that disappears from the tracker entirely is removed after
    lost_timeout_seconds regardless of its confirmed state.
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
        self._confirmed_by_class = defaultdict(int)
        self._raw_tracks = 0

    def set_raw_tracks(self, count):
        self._raw_tracks = int(count)

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
                    'confirmed': False,
                    'in_roi_since': None,
                    'out_roi_since': None,
                    'last_seen': timestamp,
                }
                self._tracks[track_id] = state

            state['last_seen'] = timestamp
            state['class_name'] = class_name

            if in_analysis:
                state['out_roi_since'] = None
                if not state['confirmed']:
                    if state['in_roi_since'] is None:
                        state['in_roi_since'] = timestamp
                    elif timestamp - state['in_roi_since'] >= self._enter_confirm_s:
                        state['confirmed'] = True
                        self._confirmed_by_class[class_name] += 1
                        events.append({
                            'event': 'confirmed',
                            'track_id': track_id,
                            'class_name': class_name,
                            'timestamp': timestamp,
                        })
            else:
                state['in_roi_since'] = None
                if state['confirmed']:
                    if state['out_roi_since'] is None:
                        state['out_roi_since'] = timestamp
                    elif timestamp - state['out_roi_since'] >= self._exit_confirm_s:
                        state['confirmed'] = False
                        self._confirmed_by_class[class_name] = max(
                            0, self._confirmed_by_class[class_name] - 1
                        )
                        state['out_roi_since'] = None
                        events.append({
                            'event': 'released',
                            'track_id': track_id,
                            'class_name': class_name,
                            'timestamp': timestamp,
                        })

        remove_ids = []
        for track_id, state in self._tracks.items():
            if track_id in active_ids:
                continue
            age = timestamp - state['last_seen']
            if age > self._lost_timeout_s:
                if state['confirmed']:
                    class_name = state['class_name']
                    self._confirmed_by_class[class_name] = max(
                        0, self._confirmed_by_class[class_name] - 1
                    )
                    events.append({
                        'event': 'released',
                        'track_id': track_id,
                        'class_name': class_name,
                        'timestamp': timestamp,
                    })
                remove_ids.append(track_id)

        for track_id in remove_ids:
            del self._tracks[track_id]

        return events

    def snapshot(self):
        classes = sorted(self._vehicle_classes)
        by_class = dict(
            (name, int(self._confirmed_by_class[name]))
            for name in classes
        )
        return {
            'current_total': sum(by_class.values()),
            'current_by_class': by_class,
            'raw_tracks': self._raw_tracks,
        }
