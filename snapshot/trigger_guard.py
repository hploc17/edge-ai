#!/usr/bin/env python3
"""Snapshot Trigger Guard: verifies double-condition (confirm duration + cooldown)
before signaling a snapshot event.

Compatible with Python 3.6 (JetPack 4.x).
"""

import time
from config.settings import CONGESTION_CONFIRM_SECONDS, SNAPSHOT_COOLDOWN_SECONDS


class SnapshotTrigger(object):
    """Decides when to trigger a snapshot based on persistent congestion and cooldown."""

    def __init__(self,
                 congestion_confirm_seconds=CONGESTION_CONFIRM_SECONDS,
                 cooldown_seconds=SNAPSHOT_COOLDOWN_SECONDS):
        self._confirm_s = float(congestion_confirm_seconds)
        self._cooldown_s = float(cooldown_seconds)
        self._congested_since = None
        self._last_snapshot_time = -self._cooldown_s
        self._was_congested = False

    def check(self, traffic_status, now=None):
        """Return True if snapshot condition is met."""
        if now is None:
            now = time.monotonic()

        is_congested = (traffic_status == 'CONGESTED')

        if not is_congested:
            self._congested_since = None
            self._was_congested = False
            return False

        if self._congested_since is None:
            self._congested_since = now

        confirmed_duration = now - self._congested_since
        if confirmed_duration < self._confirm_s:
            return False

        cooldown_elapsed = now - self._last_snapshot_time
        if cooldown_elapsed < self._cooldown_s:
            return False

        self._last_snapshot_time = now
        return True

    def reset_cooldown(self):
        """Allow immediate snapshot on demand."""
        self._last_snapshot_time = -self._cooldown_s
