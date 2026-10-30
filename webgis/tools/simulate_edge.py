#!/usr/bin/env python3
"""Wrapper redirecting to the single source of truth simulator in tools/simulate_edge.py.

This wrapper ensures that any scripts or developers calling this legacy path
will automatically execute the master simulator with the updated MQTT schema.
"""

import os
import runpy
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# Locate master simulator at repository root: tools/simulate_edge.py
REPO_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
TARGET_SCRIPT = os.path.join(REPO_ROOT, "tools", "simulate_edge.py")

if not os.path.isfile(TARGET_SCRIPT):
    # Fallback if invoked inside a standalone webgis directory
    PARENT_DIR = os.path.dirname(CURRENT_DIR)
    TARGET_SCRIPT = os.path.join(PARENT_DIR, "tools", "simulate_edge.py")

if __name__ == "__main__":
    if not os.path.isfile(TARGET_SCRIPT):
        print("[ERROR] Master simulator not found at: %s" % TARGET_SCRIPT)
        sys.exit(1)

    root_dir = os.path.dirname(os.path.dirname(TARGET_SCRIPT))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    runpy.run_path(TARGET_SCRIPT, run_name="__main__")
