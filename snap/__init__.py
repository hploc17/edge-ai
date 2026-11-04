"""Jetson snapshot v2: VIDEO_DEMO -> CSI; CSI -> current pipeline frame."""
from .snapshot_service import SnapshotCoordinator

__all__ = ["SnapshotCoordinator"]
