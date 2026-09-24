#!/usr/bin/env python3
"""Robust homography speed estimation for Jetson Nano / Python 3.6.

This module deliberately has no DeepStream dependency so its geometry, clock
and speed calculations can be tested on a development PC.
"""

from __future__ import print_function

import math
from collections import Counter, deque

import numpy as np


def _mean(values):
    if not values:
        return None
    return float(sum(values)) / float(len(values))


def _median(values):
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _bbox_bottom_center(bbox):
    return ((float(bbox[0]) + float(bbox[2])) / 2.0, float(bbox[3]))


def _cross(a, b, c):
    return ((b[0] - a[0]) * (c[1] - b[1]) -
            (b[1] - a[1]) * (c[0] - b[0]))


class PerspectiveCalibration(object):
    """Map an ordered four-corner image quadrilateral to road metres.

    Required order is P1=near-left, P2=near-right, P3=far-right,
    P4=far-left.  The physical road length must be the measured distance
    between the P1-P2 and P4-P3 cross-sections, not the complete visible road.
    """

    def __init__(self, image_points, road_width_m, road_length_m):
        if len(image_points) != 4:
            raise ValueError('Perspective calibration requires 4 points')
        if float(road_width_m) <= 0.0 or float(road_length_m) <= 0.0:
            raise ValueError('Road width and length must be positive')

        self.image_points = [
            [float(point[0]), float(point[1])] for point in image_points
        ]
        self.road_width_m = float(road_width_m)
        self.road_length_m = float(road_length_m)
        self._validate_ordered_quadrilateral(self.image_points)

        world_points = [
            [0.0, 0.0],
            [self.road_width_m, 0.0],
            [self.road_width_m, self.road_length_m],
            [0.0, self.road_length_m]
        ]
        self.matrix = self._solve_homography(
            self.image_points, world_points
        )

    @staticmethod
    def _validate_ordered_quadrilateral(points):
        for point in points:
            if not np.all(np.isfinite(np.asarray(point, dtype=np.float64))):
                raise ValueError('Calibration point is not finite')

        for first in range(4):
            for second in range(first + 1, 4):
                distance = math.hypot(
                    points[first][0] - points[second][0],
                    points[first][1] - points[second][1]
                )
                if distance < 2.0:
                    raise ValueError('Calibration points are duplicated')

        crosses = [
            _cross(points[index], points[(index + 1) % 4],
                   points[(index + 2) % 4])
            for index in range(4)
        ]
        if any(abs(value) < 1e-6 for value in crosses):
            raise ValueError('Calibration contains collinear points')
        positive = all(value > 0.0 for value in crosses)
        negative = all(value < 0.0 for value in crosses)
        if not (positive or negative):
            raise ValueError(
                'Calibration points are crossed or incorrectly ordered; '
                'use near-left, near-right, far-right, far-left'
            )

    @staticmethod
    def _solve_homography(source_points, destination_points):
        rows = []
        values = []
        for source, destination in zip(source_points, destination_points):
            x, y = source
            u, v = destination
            rows.append([
                x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y
            ])
            values.append(u)
            rows.append([
                0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y
            ])
            values.append(v)
        try:
            coefficients = np.linalg.solve(
                np.asarray(rows, dtype=np.float64),
                np.asarray(values, dtype=np.float64)
            )
        except np.linalg.LinAlgError:
            raise ValueError('Calibration points are degenerate')
        matrix = np.append(coefficients, 1.0).reshape((3, 3))
        if not np.all(np.isfinite(matrix)):
            raise ValueError('Calibration produced an invalid homography')
        return matrix

    def transform(self, point):
        x = float(point[0])
        y = float(point[1])
        denominator = (
            self.matrix[2, 0] * x +
            self.matrix[2, 1] * y +
            self.matrix[2, 2]
        )
        if abs(denominator) < 1e-9:
            raise ValueError('Point cannot be projected to the road plane')
        world_x = (
            self.matrix[0, 0] * x +
            self.matrix[0, 1] * y +
            self.matrix[0, 2]
        ) / denominator
        world_y = (
            self.matrix[1, 0] * x +
            self.matrix[1, 1] * y +
            self.matrix[1, 2]
        ) / denominator
        return float(world_x), float(world_y)

    def image_to_world(self, px, py):
        return self.transform((px, py))

    def world_distance_m(self, px1, py1, px2, py2):
        wx1, wy1 = self.image_to_world(px1, py1)
        wx2, wy2 = self.image_to_world(px2, py2)
        return math.hypot(wx2 - wx1, wy2 - wy1)


class StreamTimestamp(object):
    """Turn possibly broken DeepStream PTS values into monotonic seconds."""

    def __init__(self, source_kind, nominal_fps=30.0,
                 maximum_pts_gap_seconds=2.0):
        self.source_kind = str(source_kind)
        self.nominal_fps = max(1.0, float(nominal_fps))
        self.maximum_pts_gap_seconds = float(maximum_pts_gap_seconds)
        self.last_pts = None
        self.last_frame_number = None
        self.last_wall = None
        self.output_seconds = 0.0

    def _fallback_delta(self, frame_number, wall_now):
        if (self.source_kind == 'video' and
                self.last_frame_number is not None and
                frame_number is not None):
            frame_delta = int(frame_number) - int(self.last_frame_number)
            if frame_delta > 0:
                return float(frame_delta) / self.nominal_fps
        if self.last_wall is not None and wall_now is not None:
            wall_delta = float(wall_now) - float(self.last_wall)
            if 0.0 < wall_delta <= self.maximum_pts_gap_seconds:
                return wall_delta
        return 1.0 / self.nominal_fps

    def resolve(self, pts_seconds, frame_number=None, wall_now=None):
        delta = self._fallback_delta(frame_number, wall_now)
        valid_pts = (
            pts_seconds is not None and
            np.isfinite(float(pts_seconds)) and
            float(pts_seconds) >= 0.0
        )
        if valid_pts:
            current_pts = float(pts_seconds)
            if self.last_pts is not None:
                pts_delta = current_pts - self.last_pts
                if 0.0 < pts_delta <= self.maximum_pts_gap_seconds:
                    delta = pts_delta
            self.last_pts = current_pts

        if self.last_frame_number is not None:
            self.output_seconds += max(1e-6, float(delta))
        self.last_frame_number = (
            int(frame_number) if frame_number is not None else
            (0 if self.last_frame_number is None else
             self.last_frame_number + 1)
        )
        self.last_wall = float(wall_now) if wall_now is not None else None
        return self.output_seconds


class TrackSpeedEstimator(object):
    """Estimate planar vehicle speed using regression over track history.

    Linear regression over several world-coordinate samples is substantially
    less sensitive to bounding-box jitter than a single first/last pair.
    """

    def __init__(self, calibration, history_seconds=2.0,
                 minimum_time_seconds=0.8,
                 minimum_displacement_m=0.35,
                 smoothing_alpha=0.25,
                 maximum_speed_kmh=130.0,
                 stale_track_seconds=3.0,
                 maximum_sample_gap_seconds=2.0):
        self.calibration = calibration
        self.history_seconds = float(history_seconds)
        self.minimum_time_seconds = float(minimum_time_seconds)
        self.minimum_displacement_m = float(minimum_displacement_m)
        self.smoothing_alpha = float(smoothing_alpha)
        self.maximum_speed_kmh = float(maximum_speed_kmh)
        self.stale_track_seconds = float(stale_track_seconds)
        self.maximum_sample_gap_seconds = float(maximum_sample_gap_seconds)
        if self.history_seconds < self.minimum_time_seconds:
            raise ValueError('history_seconds must be >= minimum_time_seconds')
        if not 0.0 < self.smoothing_alpha <= 1.0:
            raise ValueError('smoothing_alpha must be in (0, 1]')
        self.tracks = {}

    @staticmethod
    def _majority_class(votes, fallback):
        return votes.most_common(1)[0][0] if votes else fallback

    @staticmethod
    def _fit_velocity(history):
        times = np.asarray([item[0] for item in history], dtype=np.float64)
        xs = np.asarray([item[1] for item in history], dtype=np.float64)
        ys = np.asarray([item[2] for item in history], dtype=np.float64)
        times = times - times[0]
        centered = times - float(np.mean(times))
        denominator = float(np.sum(centered * centered))
        if denominator <= 1e-12:
            return None
        velocity_x = float(np.sum(centered * (xs - np.mean(xs))) /
                           denominator)
        velocity_y = float(np.sum(centered * (ys - np.mean(ys))) /
                           denominator)
        return velocity_x, velocity_y

    def reset(self):
        self.tracks.clear()

    def update(self, objects, timestamp):
        timestamp = float(timestamp)
        seen_ids = set()
        results = {}

        for obj in objects:
            track_id = int(obj['track_id'])
            class_name = str(obj.get('class_name', 'vehicle'))
            world_x, world_y = self.calibration.transform(
                _bbox_bottom_center(obj['bbox'])
            )
            seen_ids.add(track_id)
            state = self.tracks.get(track_id)
            if state is None:
                state = {
                    'history': deque(),
                    'smoothed_speed': None,
                    'class_votes': Counter(),
                    'last_seen': timestamp,
                    'rejected_samples': 0
                }
                self.tracks[track_id] = state

            history = state['history']
            if history:
                sample_delta = timestamp - history[-1][0]
                if (sample_delta <= 0.0 or
                        sample_delta > self.maximum_sample_gap_seconds):
                    history.clear()
                    state['smoothed_speed'] = None
                    state['rejected_samples'] = 0

            if history:
                sample_delta = timestamp - history[-1][0]
                sample_distance = math.hypot(
                    world_x - history[-1][1], world_y - history[-1][2]
                )
                instantaneous = sample_distance / sample_delta * 3.6
                if instantaneous > self.maximum_speed_kmh * 2.0:
                    state['rejected_samples'] += 1
                    state['last_seen'] = timestamp
                    if state['rejected_samples'] >= 3:
                        history.clear()
                        state['smoothed_speed'] = None
                        state['rejected_samples'] = 0
                    continue

            state['rejected_samples'] = 0
            state['class_votes'][class_name] += 1
            state['last_seen'] = timestamp
            history.append((timestamp, world_x, world_y))
            while (len(history) > 2 and
                   timestamp - history[0][0] > self.history_seconds):
                history.popleft()

            elapsed = history[-1][0] - history[0][0]
            if len(history) >= 2 and elapsed >= self.minimum_time_seconds:
                displacement = math.hypot(
                    history[-1][1] - history[0][1],
                    history[-1][2] - history[0][2]
                )
                if displacement < self.minimum_displacement_m:
                    raw_speed = 0.0
                    fitted = (0.0, 0.0)
                else:
                    fitted = self._fit_velocity(history)
                    raw_speed = (
                        math.hypot(fitted[0], fitted[1]) * 3.6
                        if fitted is not None else None
                    )

                if (raw_speed is not None and
                        0.0 <= raw_speed <= self.maximum_speed_kmh):
                    previous = state['smoothed_speed']
                    if previous is None:
                        smoothed = raw_speed
                    else:
                        alpha = self.smoothing_alpha
                        smoothed = alpha * raw_speed + (1.0 - alpha) * previous
                    state['smoothed_speed'] = smoothed

            if state['smoothed_speed'] is not None:
                fitted = self._fit_velocity(history)
                direction = 'UNKNOWN'
                if fitted is not None and abs(fitted[1]) >= 0.05:
                    direction = 'P1_TO_P4' if fitted[1] > 0.0 else 'P4_TO_P1'
                results[track_id] = {
                    'track_id': track_id,
                    'class_name': self._majority_class(
                        state['class_votes'], class_name
                    ),
                    'speed_kmh': round(float(state['smoothed_speed']), 2),
                    'direction': direction,
                    'method': 'homography_track_regression',
                    'sample_seconds': round(elapsed, 3)
                }

        stale_ids = [
            track_id for track_id, state in self.tracks.items()
            if track_id not in seen_ids and
            timestamp - state['last_seen'] >= self.stale_track_seconds
        ]
        for track_id in stale_ids:
            del self.tracks[track_id]
        return results

    @staticmethod
    def class_speed_stats(speeds, _objects=None):
        grouped = {}
        obj_class_map = {}
        if _objects:
            for o in _objects:
                obj_class_map[int(o['track_id'])] = str(o.get('class_name', 'vehicle'))

        for tid, speed in speeds.items():
            cname = speed.get('class_name') or obj_class_map.get(int(tid), 'vehicle')
            grouped.setdefault(cname, []).append(
                float(speed['speed_kmh'])
            )
        output = {}
        for class_name, values in sorted(grouped.items()):
            output[class_name] = {
                'count': len(values),
                'sample_count': len(values),
                'avg_speed_kmh': round(_mean(values), 2),
                'median_speed_kmh': round(_median(values), 2)
            }
        return output
