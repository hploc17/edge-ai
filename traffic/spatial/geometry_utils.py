#!/usr/bin/env python3
"""Geometry utility functions for ROI and vehicle bounding box processing.

Compatible with Python 3.6 (JetPack 4.x).
Deliberately has no DeepStream or GUI dependencies so it can run anywhere.
"""

from __future__ import print_function


def point_in_polygon(point, polygon):
    """Return True when point is inside or on the edge of polygon (Ray Casting)."""
    if not polygon or len(polygon) < 3:
        return True

    x, y = float(point[0]), float(point[1])
    inside = False
    count = len(polygon)
    j = count - 1

    for i in range(count):
        xi, yi = float(polygon[i][0]), float(polygon[i][1])
        xj, yj = float(polygon[j][0]), float(polygon[j][1])

        cross = (x - xi) * (yj - yi) - (y - yi) * (xj - xi)
        if abs(cross) <= 1e-6:
            if min(xi, xj) - 1e-6 <= x <= max(xi, xj) + 1e-6:
                if min(yi, yj) - 1e-6 <= y <= max(yi, yj) + 1e-6:
                    return True

        intersects = ((yi > y) != (yj > y))
        if intersects:
            x_intersection = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x <= x_intersection:
                inside = not inside
        j = i

    return inside


def bbox_bottom_center(bbox):
    """Return (x, y) bottom-center contact point of a bounding box [x1, y1, x2, y2]."""
    x1, _y1, x2, y2 = bbox
    return ((float(x1) + float(x2)) / 2.0, float(y2))
