#!/usr/bin/env python3
"""Hardware metrics collector for NVIDIA Jetson Nano.

Reads CPU %, RAM %, GPU % and SoC thermal sensors.
Compatible with Python 3.6 (JetPack 4.x).
"""

import datetime
import glob
import os
import shutil
import socket
import time
import uuid


def _get_local_ip():
    """Retrieve active local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_mac_address():
    """Retrieve primary MAC address."""
    try:
        raw_mac = uuid.getnode()
        mac = ":".join(
            ["{:02x}".format((raw_mac >> ele) & 0xFF) for ele in range(0, 8 * 6, 8)][::-1]
        )
        return mac.upper()
    except Exception:
        return "00:00:00:00:00:00"


def collect_hardware_metrics(fps=0.0):
    """Collect hardware utilization metrics from Jetson Nano (fast loop)."""
    cpu_val = None
    ram_val = None
    gpu_val = None
    temp_val = None

    try:
        import psutil
        cpu_val = int(psutil.cpu_percent(interval=None))
        vm = psutil.virtual_memory()
        ram_val = int(vm.percent)
    except Exception:
        pass

    # Read Tegra GPU utilization on JetPack
    gpu_path = "/sys/devices/gpu.0/load"
    if os.path.exists(gpu_path):
        try:
            with open(gpu_path, "r") as f:
                val = int(f.read().strip())
                gpu_val = int(val / 10) if val > 100 else int(val)
        except Exception:
            pass

    # Read SoC Thermal zone
    for zone in ("/sys/devices/virtual/thermal/thermal_zone1/temp",
                 "/sys/devices/virtual/thermal/thermal_zone0/temp"):
        if os.path.exists(zone):
            try:
                with open(zone, "r") as f:
                    temp_val = round(float(f.read().strip()) / 1000.0, 1)
                    break
            except Exception:
                pass

    return {
        "fps": round(float(fps), 1),
        "cpu_usage_pct": cpu_val,
        "ram_usage_pct": ram_val,
        "gpu_usage_pct": gpu_val,
        "temperature_c": temp_val,
    }


def collect_comprehensive_health(fps=0.0, camera_status="streaming", outbox_dir=None):
    """Collect rich system and peripheral health diagnostics for on-demand WebGIS requests.

    Returns a comprehensive diagnostic dictionary suitable for Gói 2 (On-Demand Device Health).
    """
    now_iso = (
        datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    ).strftime("%Y-%m-%dT%H:%M:%S+07:00")

    uptime_s = 0
    boot_time_iso = None
    cpu_val = None
    cpu_count = 4
    ram_used_mb = 0
    ram_total_mb = 0
    ram_pct = 0
    swap_used_mb = 0
    swap_total_mb = 0
    gpu_val = None
    temp_val = None

    try:
        import psutil
        cpu_val = int(psutil.cpu_percent(interval=None))
        cpu_count = psutil.cpu_count(logical=True) or 4
        vm = psutil.virtual_memory()
        ram_pct = int(vm.percent)
        ram_used_mb = int(vm.used / (1024 * 1024))
        ram_total_mb = int(vm.total / (1024 * 1024))

        sm = psutil.swap_memory()
        swap_used_mb = int(sm.used / (1024 * 1024))
        swap_total_mb = int(sm.total / (1024 * 1024))

        boot_timestamp = psutil.boot_time()
        uptime_s = int(time.time() - boot_timestamp)
        boot_time_iso = datetime.datetime.fromtimestamp(boot_timestamp).strftime(
            "%Y-%m-%dT%H:%M:%S+07:00"
        )
    except Exception:
        # Fallback uptime from /proc/uptime if on Linux
        if os.path.exists("/proc/uptime"):
            try:
                with open("/proc/uptime", "r") as f:
                    uptime_s = int(float(f.readline().split()[0]))
            except Exception:
                pass

    # Read Tegra GPU load
    gpu_path = "/sys/devices/gpu.0/load"
    if os.path.exists(gpu_path):
        try:
            with open(gpu_path, "r") as f:
                val = int(f.read().strip())
                gpu_val = int(val / 10) if val > 100 else int(val)
        except Exception:
            pass

    # Read SoC Thermal zone
    for zone in ("/sys/devices/virtual/thermal/thermal_zone1/temp",
                 "/sys/devices/virtual/thermal/thermal_zone0/temp"):
        if os.path.exists(zone):
            try:
                with open(zone, "r") as f:
                    temp_val = round(float(f.read().strip()) / 1000.0, 1)
                    break
            except Exception:
                pass

    # Disk usage
    disk_path = outbox_dir if (outbox_dir and os.path.exists(outbox_dir)) else "."
    disk_usage_pct = 0
    disk_free_gb = 0.0
    disk_total_gb = 0.0
    try:
        usage = shutil.disk_usage(disk_path)
        disk_total_gb = round(usage.total / (1024 ** 3), 2)
        disk_free_gb = round(usage.free / (1024 ** 3), 2)
        disk_usage_pct = int((usage.used / usage.total) * 100)
    except Exception:
        pass

    # Outbox queue count
    outbox_count = 0
    if outbox_dir and os.path.isdir(outbox_dir):
        try:
            outbox_count = len(glob.glob(os.path.join(outbox_dir, "*.jpg"))) + len(
                glob.glob(os.path.join(outbox_dir, "*.jpeg"))
            )
        except Exception:
            pass

    latency_ms = round(1000.0 / max(float(fps), 1.0), 1) if float(fps) > 0 else None

    return {
        "timestamp": now_iso,
        "general": {
            "uptime_seconds": uptime_s,
            "boot_time": boot_time_iso,
            "service_status": "running",
        },
        "network": {
            "local_ip": _get_local_ip(),
            "mac_address": _get_mac_address(),
            "status": "connected",
        },
        "hardware": {
            "cpu_usage_pct": cpu_val,
            "cpu_cores": cpu_count,
            "ram_used_mb": ram_used_mb,
            "ram_total_mb": ram_total_mb,
            "ram_usage_pct": ram_pct,
            "swap_used_mb": swap_used_mb,
            "swap_total_mb": swap_total_mb,
            "gpu_usage_pct": gpu_val,
            "temperature_c": temp_val,
            "power_mode": "10W_MAXN",
        },
        "storage": {
            "disk_total_gb": disk_total_gb,
            "disk_free_gb": disk_free_gb,
            "disk_usage_pct": disk_usage_pct,
            "outbox_unsent_images": outbox_count,
        },
        "pipeline": {
            "camera_status": camera_status,
            "pipeline_fps": round(float(fps), 1),
            "inference_latency_ms": latency_ms,
        },
    }
