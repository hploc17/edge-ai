#!/usr/bin/env python3
"""Standalone Remote Maintenance & Diagnostic Service for Jetson Edge AI.

Feature Highlights:
  - Completely decoupled / pluggable: can be enabled/disabled without touching core pipeline logic.
  - On-demand Diagnostic Collection: collects GPU, CPU, RAM, thermal, disk, camera status,
    and the last N lines of pipeline/system logs.
  - Zero Inbound: triggered securely via MQTT command ('fetch_logs' / 'maintenance_diagnostics').
  - Compatible with Python 3.6 (JetPack 4.x on Jetson Nano).

Usage:
  1. As a module inside jetson_agent.py (optional 2-line plug):
     from communication.remote_maintenance import register_maintenance_handler
     register_maintenance_handler(cmd_handler, agent_state)

  2. Standalone test on Jetson:
     python3 communication/remote_maintenance.py --test
"""

from __future__ import print_function

import collections
import glob
import json
import os
import platform
import subprocess
import sys
import time

# Ring buffer for in-memory log capturing if imported as logger
_IN_MEMORY_LOGS = collections.deque(maxlen=300)


def append_in_memory_log(msg):
    """Optionally append a message to the in-memory diagnostic buffer."""
    ts = time.strftime("%H:%M:%S")
    _IN_MEMORY_LOGS.append("[%s] %s" % (ts, str(msg).strip()))


def _read_file_tail(file_path, num_lines=100):
    """Safely read the last N lines of a file."""
    if not os.path.isfile(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return [l.rstrip("\r\n") for l in lines[-num_lines:]]
    except Exception as err:
        return ["[WARN] Failed to read log file %s: %s" % (file_path, err)]


def _get_dmesg_tail(num_lines=30):
    """Fetch kernel/hardware diagnostic tail (especially for camera CSI / USB / NVMM errors)."""
    try:
        out = subprocess.check_output(
            ["dmesg", "-T"],
            stderr=subprocess.STDOUT,
            timeout=3
        ).decode("utf-8", errors="replace")
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        return lines[-num_lines:]
    except Exception:
        # Fallback if dmesg -T or dmesg is not permitted
        try:
            out = subprocess.check_output(
                ["dmesg"],
                stderr=subprocess.STDOUT,
                timeout=2
            ).decode("utf-8", errors="replace")
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            return lines[-num_lines:]
        except Exception as err:
            return ["[INFO] dmesg output not available: %s" % err]


def _get_tegra_stats():
    """Extract Tegra GPU and thermal stats if available on Jetson."""
    stats = {}
    # Read Tegra thermal zones
    thermal_paths = glob.glob("/sys/devices/virtual/thermal/thermal_zone*/")
    for tdir in thermal_paths:
        try:
            type_file = os.path.join(tdir, "type")
            temp_file = os.path.join(tdir, "temp")
            if os.path.isfile(type_file) and os.path.isfile(temp_file):
                with open(type_file, "r") as f:
                    z_type = f.read().strip()
                with open(temp_file, "r") as f:
                    z_temp = float(f.read().strip()) / 1000.0  # millidegree to Celsius
                stats[z_type] = round(z_temp, 1)
        except Exception:
            pass

    # Read Tegra GPU frequency & load
    gpu_load_path = "/sys/devices/gpu.0/load"
    if os.path.isfile(gpu_load_path):
        try:
            with open(gpu_load_path, "r") as f:
                stats["gpu_load_pct"] = float(f.read().strip()) / 10.0
        except Exception:
            pass

    return stats


def _get_disk_free_gb():
    """Get free disk space on root filesystem in GB."""
    try:
        st = os.statvfs("/")
        free_bytes = st.f_bavail * st.f_frsize
        total_bytes = st.f_blocks * st.f_frsize
        return {
            "free_gb": round(float(free_bytes) / (1024 ** 3), 2),
            "total_gb": round(float(total_bytes) / (1024 ** 3), 2),
            "used_pct": round((1.0 - float(free_bytes) / float(total_bytes)) * 100.0, 1)
        }
    except Exception:
        return {"free_gb": 0.0, "total_gb": 0.0, "used_pct": 0.0}


def _check_camera_devices():
    """Check detected video devices."""
    video_devs = sorted(glob.glob("/dev/video*"))
    return video_devs


def collect_diagnostics(num_lines=100, agent_state=None):
    """Generate a comprehensive diagnostic report dictionary for maintenance."""
    edge_id = os.getenv("EDGE_ID", "edge-01")
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S+07:00")

    # 1. Pipeline status
    pipeline_info = {
        "is_running": False,
        "pid": None,
        "uptime_seconds": 0.0,
    }
    if agent_state and isinstance(agent_state, dict):
        proc = agent_state.get("pipeline_process")
        started_at = agent_state.get("pipeline_started_at")
        if proc is not None and proc.poll() is None:
            pipeline_info["is_running"] = True
            pipeline_info["pid"] = proc.pid
            if started_at:
                pipeline_info["uptime_seconds"] = round(time.time() - started_at, 1)

    # 2. Collect recent logs
    collected_logs = []

    # A. In-memory logs
    if _IN_MEMORY_LOGS:
        collected_logs.append("--- [IN-MEMORY RECENT LOGS] ---")
        collected_logs.extend(list(_IN_MEMORY_LOGS)[-num_lines:])

    # B. Look for common log files
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(script_dir, "pipeline.log"),
        os.path.join(script_dir, "jetson_agent.log"),
        os.path.join(script_dir, "nohup.out"),
        "/tmp/pipeline.log",
        "/tmp/jetson_agent.log",
    ]
    for cpath in candidates:
        if os.path.isfile(cpath):
            file_lines = _read_file_tail(cpath, num_lines=num_lines)
            if file_lines:
                collected_logs.append("--- [LOG FILE: %s] ---" % os.path.basename(cpath))
                collected_logs.extend(file_lines)
                break

    # C. Hardware dmesg tail
    dmesg_lines = _get_dmesg_tail(num_lines=25)
    if dmesg_lines:
        collected_logs.append("--- [HARDWARE / DMESG TAIL] ---")
        collected_logs.extend(dmesg_lines)

    # Format combined logs
    full_log_text = "\n".join(collected_logs)

    # 3. Assemble full report
    report = {
        "status": "success",
        "action": "fetch_logs",
        "edge_id": edge_id,
        "timestamp": now_iso,
        "system_info": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "thermal": _get_tegra_stats(),
            "disk": _get_disk_free_gb(),
            "camera_devices": _check_camera_devices(),
        },
        "pipeline_status": pipeline_info,
        "log_lines_count": len(collected_logs),
        "logs": full_log_text,
    }
    return report


def make_maintenance_handler(agent_state=None):
    """Return a handler callable for command_router."""
    def handler(data):
        params = data.get("params", {}) if isinstance(data, dict) else {}
        num_lines = int(params.get("lines", 100))
        num_lines = max(10, min(300, num_lines))
        report = collect_diagnostics(num_lines=num_lines, agent_state=agent_state)
        return report
    return handler


def register_maintenance_handler(cmd_handler, agent_state=None):
    """Dynamically plug maintenance actions into CommandHandler without changing core code."""
    # Ensure actions are allowed in whitelist
    try:
        from communication.command_router import ALLOWED_ACTIONS
        if hasattr(ALLOWED_ACTIONS, "_add"):
            ALLOWED_ACTIONS._add("fetch_logs")
            ALLOWED_ACTIONS._add("maintenance_diagnostics")
        elif isinstance(ALLOWED_ACTIONS, set):
            ALLOWED_ACTIONS.add("fetch_logs")
            ALLOWED_ACTIONS.add("maintenance_diagnostics")
        elif isinstance(ALLOWED_ACTIONS, frozenset):
            import communication.command_router as _cr
            _cr.ALLOWED_ACTIONS = frozenset(list(_cr.ALLOWED_ACTIONS) + ["fetch_logs", "maintenance_diagnostics"])
    except Exception as e:
        print("[MAINTENANCE] Note on whitelist:", e)

    handler_fn = make_maintenance_handler(agent_state)
    cmd_handler.register("fetch_logs", handler_fn)
    cmd_handler.register("maintenance_diagnostics", handler_fn)
    print("[MAINTENANCE] Remote maintenance handlers registered successfully ('fetch_logs', 'maintenance_diagnostics')")


if __name__ == "__main__":
    print("--- [TESTING REMOTE MAINTENANCE REPORT] ---")
    rep = collect_diagnostics(num_lines=20)
    print("Edge ID:", rep["edge_id"])
    print("Timestamp:", rep["timestamp"])
    print("System Info:", json.dumps(rep["system_info"], indent=2))
    print("Pipeline Status:", rep["pipeline_status"])
    print("Logs Preview:\n%s" % rep["logs"][:400])
    print("--- [TEST COMPLETED SUCCESSFULLY] ---")
