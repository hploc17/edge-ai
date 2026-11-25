#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_jetson.py - Đo hiệu năng Jetson Nano (FPS, GPU %, CPU %, RAM, Nhiệt độ, Công suất, Network, MQTT, Process).

Hỗ trợ 3 chế độ sử dụng:
1. Chế độ Watcher Daemon (--watch / -w) [KHUYÊN DÙNG CHO WEBGIS & DOCKER]:
     python3 measure_jetson.py --watch
     -> Chạy thường trực trên Jetson (Host hoặc Docker), tự động nhận biết khi có pipeline
        khởi động từ WebGIS, tự trích xuất tên video/camera để đặt nhãn phase, tự thu thập
        hiệu suất và tự xuất file thống kê khi video kết thúc hoặc WebGIS bấm Stop.

2. Tích hợp trực tiếp vào Jetson Agent & main.py:
     Khi Jetson Agent nhận lệnh từ WebGIS, nó tự động kích hoạt profiler với tên video tương ứng.
     (main.py sẽ tự truyền FPS trực tiếp từ probe và PID của tiến trình con).

3. Chạy thủ công 1 lần từ terminal:
     python3 measure_jetson.py --phase baseline --duration 600 --warmup 60 --pid $(pgrep -f main.py | head -n1)

Tương thích Python 3.6 (JetPack 4.6.1) và Python 3.11+.
"""
from __future__ import print_function

import argparse
import csv
import glob
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time

# ----------------------------------------------------------------------------- tegrastats
RE_RAM = re.compile(r"RAM (\d+)/(\d+)MB")
RE_CPU = re.compile(r"CPU \[([^\]]*)\]")
RE_GPU = re.compile(r"GR3D_FREQ (\d+)%")
RE_TEMP = re.compile(r"(\w+)@(-?[\d.]+)C")
RE_POWER_IN = re.compile(r"(?:POM_5V_IN|VDD_IN) (\d+)/(\d+)")

METRICS_COLUMNS = [
    "t", "elapsed_s", "fps", "gpu_pct", "cpu_avg_pct", "cpu_max_core_pct",
    "ram_used_mb", "ram_total_mb", "temp_cpu_c", "temp_gpu_c", "temp_thermal_c",
    "power_in_mw", "net_tx_kbps", "net_rx_kbps", "mqtt_msgs", "mqtt_kbps",
    "proc_cpu_pct", "proc_rss_mb"
]


def parse_tegrastats(line):
    """Tra ve dict cac chi so tu mot dong tegrastats; truong nao khong co thi bo qua."""
    out = {}
    m = RE_RAM.search(line)
    if m:
        out["ram_used_mb"] = int(m.group(1))
        out["ram_total_mb"] = int(m.group(2))
    m = RE_CPU.search(line)
    if m:
        loads = []
        for item in m.group(1).split(","):
            item = item.strip()
            if item.lower() == "off" or "%" not in item:
                continue
            try:
                loads.append(float(item.split("%")[0]))
            except ValueError:
                pass
        if loads:
            out["cpu_avg_pct"] = sum(loads) / len(loads)
            out["cpu_max_core_pct"] = max(loads)
    m = RE_GPU.search(line)
    if m:
        out["gpu_pct"] = float(m.group(1))
    for name, val in RE_TEMP.findall(line):
        key = name.lower()
        if key in ("cpu", "gpu", "thermal", "ao", "pll"):
            out["temp_%s_c" % key] = float(val)
    m = RE_POWER_IN.search(line)
    if m:
        out["power_in_mw"] = int(m.group(1))
    return out


class TegrastatsReader(threading.Thread):
    def __init__(self, interval_ms, out_dir=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self.interval_ms = interval_ms
        self.latest = {}
        self.lock = threading.Lock()
        self.proc = None
        self.error = None
        self.out_dir = out_dir
        self.stop_event = threading.Event()
        self.last_sample = None
        self.parsed_lines = 0
        self.returncode = None
        self.command = None

    def run(self):
        raw = None
        try:
            executable = os.environ.get('TEGRASTATS_PATH') or shutil.which('tegrastats')
            if not executable:
                executable = next((p for p in (
                    '/usr/bin/tegrastats', '/usr/local/bin/tegrastats',
                    '/home/nvidia/tegrastats') if os.access(p, os.X_OK)), 'tegrastats')
            self.command = [executable, '--interval', str(self.interval_ms)]
            if self.out_dir:
                raw = open(os.path.join(self.out_dir, 'tegrastats.log'), 'w', encoding='utf-8')
            if self.stop_event.is_set():
                return
            self.proc = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, bufsize=1)
            if self.stop_event.is_set():
                self.proc.terminate()
            for line in self.proc.stdout:
                if raw:
                    raw.write(line)
                    raw.flush()
                data = parse_tegrastats(line)
                if data:
                    with self.lock:
                        self.latest = data
                        self.last_sample = time.monotonic()
                        self.parsed_lines += 1
            self.returncode = self.proc.wait()
            if not self.stop_event.is_set() and self.parsed_lines == 0:
                self.error = 'tegrastats exited unexpectedly (code %s); see tegrastats.log' % self.returncode
                if raw:
                    raw.write('[ERROR] tegrastats thoat voi ma loi code %s (parsed_lines=0).\n' % self.returncode)
                    raw.flush()
        except Exception as e:
            self.error = 'tegrastats: %s' % e
            if raw:
                raw.write('[ERROR] Khong the khoi chay tegrastats: %s\n' % e)
                raw.write('[NGUYEN NHAN VA HUONG DAN KHAC PHUC]:\n')
                raw.write('1. Neu dang chay trong Docker container tren Jetson Nano:\n')
                raw.write('   - Docker image mac dinh thuong KHONG chua san file /usr/bin/tegrastats tu Host OS.\n')
                raw.write('   - Khac phuc: khi chay Docker container, them tham so mount:\n')
                raw.write('     -v /usr/bin/tegrastats:/usr/bin/tegrastats:ro --privileged -v /sys:/sys\n')
                raw.write('2. Neu muon do tu ben ngoai Docker (khong can sua container):\n')
                raw.write('   - Chay ngoai Host OS cua Jetson: python3 measure_jetson.py --watch\n')
                raw.write('3. He thong da tu dong kich hoat Sysfs Fallback doc truc tiep GPU %% tu /sys/devices/gpu.0/load\n')
                raw.flush()
        finally:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
            if self.proc and self.proc.stdout:
                self.proc.stdout.close()
            if raw:
                raw.close()
            if self.error:
                print('[MEASURE WARNING] ' + self.error, file=sys.stderr)

    def snapshot(self):
        with self.lock:
            if (self.error or self.last_sample is None or
                    time.monotonic() - self.last_sample > max(3.0, self.interval_ms / 1000.0 * 3)):
                return {}
            return dict(self.latest)

    def diagnostics(self):
        return {'command': self.command, 'parsed_lines': self.parsed_lines,
                'returncode': self.returncode, 'error': self.error,
                'status': 'error' if self.error else ('collected' if self.parsed_lines else 'no_data'),
                'raw_log': 'tegrastats.log'}

    def stop(self):
        self.stop_event.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        if self.is_alive():
            self.join(timeout=2.0)
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            if self.is_alive():
                self.join(timeout=2.0)


# ----------------------------------------------------------------------------- mang
def default_iface():
    """Card mang co default route (thuong la eth0 hoac wlan0)."""
    try:
        with open("/proc/net/route") as f:
            next(f)
            for line in f:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000":
                    return parts[0]
    except (IOError, OSError, StopIteration):
        pass
    return None


def read_iface_bytes(iface):
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                if name.strip() == iface:
                    cols = rest.split()
                    return int(cols[0]), int(cols[8])  # rx_bytes, tx_bytes
    except (IOError, OSError):
        pass
    return None, None


# ----------------------------------------------------------------------------- tien trinh pipeline
CLK_TCK = os.sysconf(os.sysconf_names["SC_CLK_TCK"]) if hasattr(os, "sysconf") else 100
NCPU = os.cpu_count() or 1


def read_proc(pid):
    """Tra ve (tong tick CPU, RSS MB) cua tien trinh; None neu tien trinh da tat."""
    try:
        with open("/proc/%d/stat" % pid) as f:
            stat = f.read()
        # ten tien trinh nam trong ngoac, co the chua dau cach -> cat sau dau ')'
        fields = stat[stat.rindex(")") + 2:].split()
        ticks = int(fields[11]) + int(fields[12])  # utime + stime
        rss_mb = None
        with open("/proc/%d/status" % pid) as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_mb = int(line.split()[1]) / 1024.0
                    break
        return ticks, rss_mb
    except (IOError, OSError, ValueError, IndexError):
        return None, None


def is_process_alive(pid):
    """Kiem tra xem PID con ton tai khong."""
    if not pid:
        return False
    if sys.platform.startswith("linux"):
        return os.path.isdir("/proc/%d" % pid)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False


# ----------------------------------------------------------------------------- FPS tu file log
class LogTailer(threading.Thread):
    """Doc noi tiep file log cua pipeline va lay so FPS moi nhat theo regex."""

    def __init__(self, path, pattern):
        threading.Thread.__init__(self)
        self.daemon = True
        self.path = path
        self.regex = re.compile(pattern, re.IGNORECASE)
        self.latest_fps = None
        self.latest_t = 0.0
        self.running = True

    def run(self):
        while self.running and not os.path.exists(self.path):
            time.sleep(0.5)
        try:
            with open(self.path, "r", errors="ignore") as f:
                f.seek(0, os.SEEK_END)
                while self.running:
                    line = f.readline()
                    if not line:
                        time.sleep(0.2)
                        continue
                    m = self.regex.search(line)
                    if m:
                        try:
                            self.latest_fps = float(m.group(1))
                            self.latest_t = time.time()
                        except (ValueError, IndexError):
                            pass
        except Exception:
            pass


# ----------------------------------------------------------------------------- MQTT
class MqttCounter(object):
    """Nghe lai ban tin MQTT de do kich thuoc va tan suat. Khong gui gi len broker."""

    def __init__(self, args, writer):
        import paho.mqtt.client as mqtt  # chi can khi dung --mqtt-host
        self.writer = writer
        self.fps_key = getattr(args, "fps_json_key", None)
        self.lock = threading.Lock()
        self.window = {"msgs": 0, "bytes": 0}
        self.latest_fps = None
        self.latest_t = 0.0
        self.recording = False
        self.client = mqtt.Client(client_id="measure-%d" % os.getpid())
        if getattr(args, "mqtt_user", None):
            self.client.username_pw_set(args.mqtt_user, getattr(args, "mqtt_pass", None) or None)
        if getattr(args, "mqtt_tls", False):
            self.client.tls_set()
        self.topic = getattr(args, "mqtt_topic", "traffic/#")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(args.mqtt_host, getattr(args, "mqtt_port", 1883), keepalive=30)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, rc):
        client.subscribe(self.topic, qos=0)

    @staticmethod
    def wire_size(topic, payload_len):
        # PUBLISH QoS0: 1 byte header + Remaining Length (1-4 byte) + 2 byte do dai topic + topic + payload
        remaining = 2 + len(topic.encode("utf-8")) + payload_len
        rl = 1 if remaining < 128 else 2 if remaining < 16384 else 3 if remaining < 2097152 else 4
        return 1 + rl + remaining

    def _on_message(self, client, userdata, msg):
        now = time.time()
        size = self.wire_size(msg.topic, len(msg.payload))
        if self.fps_key and msg.topic.endswith("telemetry"):
            try:
                data = json.loads(msg.payload.decode("utf-8"))
                val = data
                for part in self.fps_key.split("."):
                    val = val[part]
                self.latest_fps = float(val)
                self.latest_t = now
            except Exception:
                pass
        with self.lock:
            if self.recording:
                self.window["msgs"] += 1
                self.window["bytes"] += size
                self.writer.writerow([round(now, 3), msg.topic, len(msg.payload), size])

    def take_window(self):
        with self.lock:
            w = dict(self.window)
            self.window = {"msgs": 0, "bytes": 0}
        return w

    def stop(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass


# ----------------------------------------------------------------------------- thong ke
def describe(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return {"n": len(vals), "mean": mean, "std": sd, "min": min(vals), "max": max(vals)}


def fmt(d, nd=1):
    if not d:
        return "khong co du lieu"
    f = "%." + str(nd) + "f"
    return (f + " ± " + f + "  (min " + f + ", max " + f + ", n=%d)") % (
        d["mean"], d["std"], d["min"], d["max"], d["n"])


def mb_to_gb(d):
    if not d:
        return None
    return {k: (v / 1024.0 if k != "n" else v) for k, v in d.items()}


# ----------------------------------------------------------------------------- Trích xuất nhãn Phase từ command line
def extract_phase_from_cmdline(cmdline_parts):
    """Trích xuất tên kịch bản đo từ danh sách đối số command line của main.py."""
    source = None
    algo = None
    for i, p in enumerate(cmdline_parts):
        if p in ("-s", "--source") and i + 1 < len(cmdline_parts):
            source = cmdline_parts[i + 1]
        elif p.startswith("--source="):
            source = p.split("=", 1)[1]
        elif p == "--algo-version" and i + 1 < len(cmdline_parts):
            algo = cmdline_parts[i + 1]
        elif p.startswith("--algo-version="):
            algo = p.split("=", 1)[1]

    phase = "pipeline_run"
    if source:
        base = os.path.basename(source.replace("\\", "/"))
        stem = os.path.splitext(base)[0]
        phase = stem if stem else source
    if algo:
        phase = "%s_%s" % (phase, algo)
    return phase


def find_running_pipeline(root_dir=None):
    """
    Tự động dò tìm tiến trình main.py đang chạy trên hệ thống.
    Trả về (pid, phase_name, cmdline_str) hoặc (None, None, None).
    """
    if root_dir is None:
        root_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Kiểm tra file khóa .pipeline.lock (chuẩn hóa của dự án)
    lock_file = os.path.join(root_dir, ".pipeline.lock")
    if os.path.isfile(lock_file):
        try:
            with open(lock_file, "r") as f:
                content = f.read().strip()
                if content.isdigit():
                    pid = int(content)
                    if is_process_alive(pid):
                        # Đọc cmdline
                        cmd_parts = []
                        cmdline_path = "/proc/%d/cmdline" % pid
                        if os.path.isfile(cmdline_path):
                            with open(cmdline_path, "rb") as cf:
                                raw = cf.read()
                                cmd_parts = [p.decode("utf-8", "ignore") for p in raw.split(b"\x00") if p]
                        phase = extract_phase_from_cmdline(cmd_parts)
                        return pid, phase, " ".join(cmd_parts)
        except Exception:
            pass

    # 2. Quét /proc trên Linux
    if sys.platform.startswith("linux") and os.path.isdir("/proc"):
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                pid = int(entry)
                cmdline_path = "/proc/%d/cmdline" % pid
                if not os.path.isfile(cmdline_path):
                    continue
                try:
                    with open(cmdline_path, "rb") as f:
                        raw = f.read()
                        if b"main.py" in raw and b"jetson_agent.py" not in raw and b"measure_jetson.py" not in raw:
                            parts = [p.decode("utf-8", "ignore") for p in raw.split(b"\x00") if p]
                            phase = extract_phase_from_cmdline(parts)
                            return pid, phase, " ".join(parts)
                except (IOError, OSError):
                    continue
        except Exception:
            pass

    # 3. Quét qua pgrep fallback
    if sys.platform.startswith("linux"):
        try:
            out = subprocess.check_output(["pgrep", "-f", "python3.*main.py"], stderr=subprocess.DEVNULL)
            pids = [int(p.strip()) for p in out.decode("utf-8").split() if p.strip().isdigit()]
            for pid in pids:
                if pid != os.getpid() and is_process_alive(pid):
                    cmd_parts = []
                    cmdline_path = "/proc/%d/cmdline" % pid
                    if os.path.isfile(cmdline_path):
                        with open(cmdline_path, "rb") as cf:
                            raw = cf.read()
                            cmd_parts = [p.decode("utf-8", "ignore") for p in raw.split(b"\x00") if p]
                    phase = extract_phase_from_cmdline(cmd_parts)
                    return pid, phase, " ".join(cmd_parts)
        except Exception:
            pass

    return None, None, None


# ----------------------------------------------------------------------------- Sysfs Fallback
def read_sysfs_metrics():
    """
    Fallback tự động đọc phần cứng từ sysfs và /proc khi tegrastats không khả dụng
    (ví dụ: chạy trong Docker container thiếu quyền hoặc chưa mount binary tegrastats).
    """
    out = {}
    # 1. GPU load từ sysfs (/sys/devices/gpu.0/load)
    for p in ("/sys/devices/gpu.0/load",
              "/sys/devices/platform/host1x/57000000.gpu/load",
              "/sys/devices/57000000.gpu/load"):
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    val = float(f.read().strip())
                    out["gpu_pct"] = val / 10.0 if val > 100 else val
                    break
            except Exception:
                pass

    # 2. RAM & CPU từ psutil hoặc /proc/meminfo
    try:
        import psutil
        vm = psutil.virtual_memory()
        out["ram_used_mb"] = int(vm.used / (1024 * 1024))
        out["ram_total_mb"] = int(vm.total / (1024 * 1024))
        out["cpu_avg_pct"] = float(psutil.cpu_percent(interval=None))
    except Exception:
        if os.path.exists("/proc/meminfo"):
            try:
                mem = {}
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            mem[parts[0].strip()] = int(parts[1].strip().split()[0])
                if "MemTotal" in mem and "MemAvailable" in mem:
                    total_mb = int(mem["MemTotal"] / 1024)
                    avail_mb = int(mem["MemAvailable"] / 1024)
                    out["ram_total_mb"] = total_mb
                    out["ram_used_mb"] = total_mb - avail_mb
            except Exception:
                pass

    # 3. Nhiệt độ SoC từ /sys/devices/virtual/thermal/thermal_zone*
    try:
        for zone_dir in glob.glob("/sys/devices/virtual/thermal/thermal_zone*"):
            type_file = os.path.join(zone_dir, "type")
            temp_file = os.path.join(zone_dir, "temp")
            if os.path.exists(type_file) and os.path.exists(temp_file):
                try:
                    with open(type_file, "r") as tf:
                        z_type = tf.read().strip().lower()
                    with open(temp_file, "r") as tmf:
                        t_val = round(float(tmf.read().strip()) / 1000.0, 1)
                    if "cpu" in z_type and "temp_cpu_c" not in out:
                        out["temp_cpu_c"] = t_val
                    elif "gpu" in z_type and "temp_gpu_c" not in out:
                        out["temp_gpu_c"] = t_val
                    elif ("pll" in z_type or "thermal" in z_type or "ao" in z_type) and "temp_thermal_c" not in out:
                        out["temp_thermal_c"] = t_val
                except Exception:
                    pass
    except Exception:
        pass

    # 4. Công suất mW từ INA3221 (nếu có sysfs)
    for p in glob.glob("/sys/bus/i2c/drivers/ina3221x/*/hwmon/hwmon*/in1_input"):
        try:
            with open(p, "r") as f:
                out["power_in_mw"] = int(float(f.read().strip()))
                break
        except Exception:
            pass

    return out


# ----------------------------------------------------------------------------- JetsonPerformanceProfiler
class JetsonPerformanceProfiler(object):
    """
    Bộ đo hiệu năng Jetson Nano hỗ trợ:
    1. Chạy ngầm trong main.py (lấy FPS trực tiếp từ probe và PID tiến trình).
    2. Chạy độc lập qua CLI measure_jetson.py hoặc chế độ Watcher daemon.
    """

    def __init__(self, phase="baseline", duration=None, warmup=0, interval=1.0,
                 out_dir="bench_results", iface=None, pid=None, no_tegrastats=False,
                 get_fps_fn=None, on_duration_reached=None,
                 log_file=None, fps_regex=None,
                 mqtt_host=None, mqtt_port=1883, mqtt_topic="traffic/#",
                 mqtt_user=None, mqtt_pass=None, mqtt_tls=False, fps_json_key=None):
        self.phase = phase
        self.duration = duration
        self.warmup = max(0, int(warmup or 0))
        self.interval = max(0.1, float(interval or 1.0))
        self.out_dir = out_dir
        self.iface = iface or default_iface()
        self.pid = pid or os.getpid()
        self.no_tegrastats = bool(no_tegrastats)
        self.get_fps_fn = get_fps_fn
        self.on_duration_reached = on_duration_reached
        self.log_file = log_file
        self.fps_regex = fps_regex or r"(?:\*\*PERF:\s*(?:\{[^}]*?:\s*)?|fps\s*[:=]?\s*)([0-9]+(?:\.[0-9]+)?)"
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_topic = mqtt_topic
        self.mqtt_user = mqtt_user
        self.mqtt_pass = mqtt_pass
        self.mqtt_tls = mqtt_tls
        self.fps_json_key = fps_json_key

        self.cols = METRICS_COLUMNS
        self.run_dir = None
        self._thread = None
        self._stop_event = threading.Event()
        self._is_running = False
        self._stopped = False
        self.rows = []
        self.summary = None

        self.tegra = None
        self.log_tail = None
        self.mqtt = None
        self.metrics_file = None
        self.metrics_writer = None
        self.mqtt_file = None
        self.t_start = 0.0

    def is_running(self):
        if self._stopped:
            return False
        return self._is_running and (self._thread is not None and self._thread.is_alive())

    def start(self):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(self.out_dir, "%s_%s" % (stamp, self.phase))
        if not os.path.exists(self.run_dir):
            os.makedirs(self.run_dir)

        if not self.no_tegrastats:
            self.tegra = TegrastatsReader(int(self.interval * 1000), self.run_dir)
            self.tegra.start()

        if self.log_file:
            self.log_tail = LogTailer(self.log_file, self.fps_regex)
            self.log_tail.start()

        self.mqtt_file = open(os.path.join(self.run_dir, "mqtt_messages.csv"), "w", newline="")
        mqtt_writer = csv.writer(self.mqtt_file)
        mqtt_writer.writerow(["t", "topic", "payload_bytes", "mqtt_bytes_est"])

        if self.mqtt_host:
            try:
                class _ArgsMock(object):
                    pass
                m_args = _ArgsMock()
                m_args.fps_json_key = self.fps_json_key
                m_args.mqtt_user = self.mqtt_user
                m_args.mqtt_pass = self.mqtt_pass
                m_args.mqtt_tls = self.mqtt_tls
                m_args.mqtt_topic = self.mqtt_topic
                m_args.mqtt_host = self.mqtt_host
                m_args.mqtt_port = self.mqtt_port
                self.mqtt = MqttCounter(m_args, mqtt_writer)
            except Exception as e:
                print("[MEASURE WARNING] Khong the khoi tao MQTT counter: %s" % e, file=sys.stderr)

        self.metrics_file = open(os.path.join(self.run_dir, "metrics.csv"), "w", newline="")
        self.metrics_writer = csv.writer(self.metrics_file)
        self.metrics_writer.writerow(self.cols)

        dur_str = ("%d giay" % self.duration) if self.duration else "khong gioi han"
        print("[*] [MEASURE] Khoi dong bo do hieu nang: phase='%s' | PID=%d | card=%s | warmup=%ds | duration=%s -> %s"
              % (self.phase, self.pid, self.iface, self.warmup, dur_str, self.run_dir))

        self._stop_event.clear()
        self._stopped = False
        self._is_running = True
        self._thread = threading.Thread(target=self._worker_loop, name="JetsonPerformanceProfiler")
        self._thread.daemon = True
        self._thread.start()
        return self.run_dir

    def _worker_loop(self):
        # Giai doan warm-up
        if self.warmup > 0:
            print("[*] [MEASURE] Dang cho warm-up %d giay..." % self.warmup)
            t_wstart = time.time()
            while time.time() - t_wstart < self.warmup:
                if self._stop_event.is_set():
                    return
                time.sleep(min(0.5, self.warmup - (time.time() - t_wstart)))
            print("[*] [MEASURE] Ket thuc warm-up. Bat dau ghi metrics!")

        if self.tegra is not None and self.tegra.error:
            print("[!] [MEASURE] " + self.tegra.error, file=sys.stderr)

        if self.mqtt:
            self.mqtt.take_window()
            self.mqtt.recording = True

        rx0, tx0 = read_iface_bytes(self.iface) if self.iface else (None, None)
        p_ticks0, _ = read_proc(self.pid) if self.pid else (None, None)
        self.t_start = time.time()
        t_prev = self.t_start

        while not self._stop_event.is_set():
            time.sleep(self.interval)
            if self._stop_event.is_set():
                break

            now = time.time()
            dt = max(0.001, now - t_prev)
            t_prev = now
            elapsed = now - self.t_start

            if self.duration and elapsed >= self.duration:
                print("\n[*] [MEASURE] Da dat thoi gian do yeu cau (%d giay)." % self.duration)
                if callable(self.on_duration_reached):
                    try:
                        self.on_duration_reached()
                    except Exception as e:
                        print("[MEASURE WARNING] on_duration_reached error: %s" % e, file=sys.stderr)
                break

            row = {"t": round(now, 3), "elapsed_s": round(elapsed, 1)}
            if self.tegra is not None:
                row.update(self.tegra.snapshot())

            # Sysfs Fallback: neu tegrastats khong co san hoac thieu truong nao (vd chay trong Docker)
            sysfs_data = read_sysfs_metrics()
            for k, v in sysfs_data.items():
                if row.get(k) is None:
                    row[k] = v

            # Mang
            rx1, tx1 = read_iface_bytes(self.iface) if self.iface else (None, None)
            if rx0 is not None and rx1 is not None:
                row["net_tx_kbps"] = max(0.0, (tx1 - tx0) * 8 / 1000.0 / dt)
                row["net_rx_kbps"] = max(0.0, (rx1 - rx0) * 8 / 1000.0 / dt)
                rx0, tx0 = rx1, tx1

            # Tien trinh pipeline
            if self.pid:
                ticks, rss = read_proc(self.pid)
                if ticks is not None and p_ticks0 is not None:
                    row["proc_cpu_pct"] = max(0.0, (ticks - p_ticks0) / float(CLK_TCK) / dt / NCPU * 100.0)
                    row["proc_rss_mb"] = rss
                    p_ticks0 = ticks

            # MQTT
            if self.mqtt:
                win = self.mqtt.take_window()
                row["mqtt_msgs"] = win["msgs"]
                row["mqtt_kbps"] = win["bytes"] * 8 / 1000.0 / dt

            # FPS
            fps = None
            if callable(self.get_fps_fn):
                try:
                    fval = self.get_fps_fn()
                    if fval is not None and fval > 0:
                        fps = round(float(fval), 2)
                except Exception:
                    pass
            if fps is None and self.log_tail and self.log_tail.latest_fps is not None and now - self.log_tail.latest_t < 5:
                fps = self.log_tail.latest_fps
            elif fps is None and self.mqtt and self.mqtt.latest_fps is not None and now - self.mqtt.latest_t < 5:
                fps = self.mqtt.latest_fps
            row["fps"] = fps

            try:
                self.metrics_writer.writerow([row.get(c, "") if row.get(c) is not None else "" for c in self.cols])
                self.metrics_file.flush()
            except Exception:
                pass
            self.rows.append(row)

            if int(elapsed) > 0 and int(elapsed) % 30 == 0:
                print("  [MEASURE] t=%4ds | fps=%s | gpu=%s%% | cpu_proc=%.1f%% | rss=%.1fMB | tx=%.1f kbit/s" % (
                    elapsed, "%.1f" % fps if fps else "-",
                    row.get("gpu_pct", "-"), row.get("proc_cpu_pct") or 0.0,
                    row.get("proc_rss_mb") or 0.0, row.get("net_tx_kbps") or 0.0))
        self._is_running = False

    def stop(self):
        if self._stopped:
            return self.run_dir
        self._stopped = True
        self._is_running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        if self.metrics_file and not self.metrics_file.closed:
            try:
                self.metrics_file.close()
            except Exception:
                pass

        if self.mqtt:
            self.mqtt.recording = False
            self.mqtt.stop()
        if self.mqtt_file and not self.mqtt_file.closed:
            try:
                self.mqtt_file.close()
            except Exception:
                pass

        if self.tegra is not None:
            self.tegra.stop()
        if self.log_tail:
            self.log_tail.running = False

        self._generate_summary()
        return self.run_dir

    def _generate_summary(self):
        if not self.run_dir:
            return

        def col(name):
            return [r.get(name) for r in self.rows]

        summary = {k: describe(col(k)) for k in self.cols if k not in ("t", "elapsed_s")}
        summary["meta"] = {
            "phase": self.phase,
            "iface": self.iface,
            "duration_s": self.duration,
            "warmup_s": self.warmup,
            "samples": len(self.rows),
            "pid": self.pid,
            "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.t_start if self.t_start else time.time()))
        }
        summary['meta']['tegrastats'] = (
            self.tegra.diagnostics() if self.tegra else {'status': 'disabled'})
        try:
            summary["meta"]["nvpmodel"] = subprocess.check_output(
                ["nvpmodel", "-q"], stderr=subprocess.STDOUT, universal_newlines=True).strip()
        except Exception:
            summary["meta"]["nvpmodel"] = "khong doc duoc (chay 'sudo nvpmodel -q' va ghi tay)"

        self.summary = summary

        # 1. Luu JSON
        try:
            with open(os.path.join(self.run_dir, "summary.json"), "w") as fj:
                json.dump(summary, fj, indent=2, ensure_ascii=False)
        except Exception as e:
            print("[MEASURE WARNING] Khong ghi duoc summary.json: %s" % e, file=sys.stderr)

        # 2. Luu Markdown & in ra console
        lines = [
            "# Ket qua do hieu nang - Phase: %s" % self.phase,
            "",
            "Bat dau: %s | So mau: %d | Warm-up bo qua: %d s | Card mang: %s | PID: %s"
            % (summary["meta"]["started"], len(self.rows), self.warmup, self.iface, str(self.pid)),
            "Che do nguon: %s" % summary["meta"]["nvpmodel"].replace("\n", " "),
            'Tegrastats: %s' % json.dumps(summary['meta']['tegrastats'], ensure_ascii=False),
            "",
            "| Chi so | TB ± do lech chuan (min, max, n) |",
            "| --- | --- |",
            "| FPS chuoi phan tich | %s |" % fmt(summary.get("fps")),
            "| GPU (%%) | %s |" % fmt(summary.get("gpu_pct")),
            "| CPU trung binh cac nhan (%%) | %s |" % fmt(summary.get("cpu_avg_pct")),
            "| RAM he thong (GB) | %s |" % fmt(mb_to_gb(summary.get("ram_used_mb")), 2),
            "| Nhiet do GPU (°C) | %s |" % fmt(summary.get("temp_gpu_c")),
            "| Nhiet do CPU (°C) | %s |" % fmt(summary.get("temp_cpu_c")),
            "| Cong suat dau vao (mW) | %s |" % fmt(summary.get("power_in_mw"), 0),
            "| Mang gui di - toan bo card (kbit/s) | %s |" % fmt(summary.get("net_tx_kbps"), 2),
            "| MQTT nghe duoc (kbit/s, uoc tinh tang MQTT) | %s |" % fmt(summary.get("mqtt_kbps"), 2),
            "| So ban tin MQTT / lan lay mau | %s |" % fmt(summary.get("mqtt_msgs"), 2),
            "| CPU rieng tien trinh pipeline (%% cua ca may) | %s |" % fmt(summary.get("proc_cpu_pct")),
            "| RAM rieng tien trinh pipeline (MB) | %s |" % fmt(summary.get("proc_rss_mb"), 0),
            "",
            "Ghi chu: 'Mang gui di' do o card mang nen da gom header TCP/IP va moi luong khac.",
        ]
        md_text = "\n".join(lines)
        try:
            with open(os.path.join(self.run_dir, "summary.md"), "w") as fm:
                fm.write(md_text + "\n")
        except Exception as e:
            print("[MEASURE WARNING] Khong ghi duoc summary.md: %s" % e, file=sys.stderr)

        print("\n" + "=" * 60)
        print(md_text)
        print("=" * 60)
        print("[*] [MEASURE] Ket qua do da luu tai: %s\n" % self.run_dir)


# ----------------------------------------------------------------------------- Chế độ Watcher Daemon
def run_watcher(args):
    """
    Chế độ Watcher Daemon:
    Tự động chạy thường trực trên Jetson, phát hiện khi pipeline bắt đầu chạy từ WebGIS hoặc Docker,
    tự trích xuất tên video/nguồn và thuật toán, thu thập thông số hiệu năng và tự lưu khi pipeline dừng.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(script_dir, "pipeline.log")

    print("=" * 68)
    print("[*] [WATCHER] CHẾ ĐỘ GIÁM SÁT HIỆU NĂNG TỰ ĐỘNG JETSON NANO")
    print("[*] [WATCHER] Đang quét hệ thống... Chờ lệnh khởi động pipeline từ WebGIS/Docker.")
    print("[*] [WATCHER] Nhấn Ctrl+C để thoát khỏi chế độ giám sát.")
    print("=" * 68)

    last_idle_time = 0.0

    while True:
        try:
            pid, auto_phase, cmd_str = find_running_pipeline(script_dir)
            if pid is None:
                now = time.time()
                if now - last_idle_time >= 15.0:
                    print("[*] [WATCHER] Trạng thái: Chờ pipeline... (Hệ thống rảnh, chưa có lệnh từ Web)")
                    last_idle_time = now
                time.sleep(1.0)
                continue

            # Phát hiện pipeline đang chạy!
            phase_name = args.phase if (args.phase and args.phase != "baseline") else (auto_phase or "webgis_run")
            print("\n" + "=" * 68)
            print("[*] [WATCHER] 🔥 PHÁT HIỆN PIPELINE ĐANG CHẠY TỪ WEBGIS!")
            print("[*] [WATCHER] PID tiến trình: %d" % pid)
            print("[*] [WATCHER] Nhãn kịch bản / Video: %s" % phase_name)
            if cmd_str:
                print("[*] [WATCHER] Lệnh: %s" % (cmd_str[:100] + "..." if len(cmd_str) > 100 else cmd_str))
            print("[*] [WATCHER] Bắt đầu thu thập số liệu hiệu năng...")
            print("=" * 68 + "\n")

            log_file_to_tail = args.log or (log_path if os.path.exists(log_path) else None)
            profiler = JetsonPerformanceProfiler(
                phase=phase_name,
                duration=args.duration,
                warmup=args.warmup,
                interval=args.interval,
                out_dir=args.out,
                iface=args.iface,
                pid=pid,
                no_tegrastats=args.no_tegrastats,
                log_file=log_file_to_tail,
                fps_regex=args.fps_regex,
                mqtt_host=args.mqtt_host,
                mqtt_port=args.mqtt_port,
                mqtt_topic=args.mqtt_topic,
                mqtt_user=args.mqtt_user,
                mqtt_pass=args.mqtt_pass,
                mqtt_tls=args.mqtt_tls,
                fps_json_key=args.fps_json_key
            )
            profiler.start()

            # Chờ đến khi pipeline dừng
            while is_process_alive(pid):
                time.sleep(1.0)
                if args.duration and (time.time() - profiler.t_start) >= args.duration:
                    break

            print("\n[*] [WATCHER] 🛑 Pipeline PID=%d đã dừng (WebGIS bấm dừng hoặc video kết thúc)!" % pid)
            out_dir = profiler.stop()
            print("[*] [WATCHER] ✅ Hoàn tất phiên đo cho video/nguồn '%s'." % phase_name)
            print("[*] [WATCHER] Kết quả đã lưu tại: %s" % out_dir)
            print("[*] [WATCHER] Trở lại trạng thái chờ lượt chạy tiếp theo từ WebGIS...\n")
            time.sleep(2.0)  # Cooldown tránh nhận diện lại tiến trình cũ đang thoát
            last_idle_time = time.time()

        except KeyboardInterrupt:
            print("\n[*] [WATCHER] Đã nhận tín hiệu dừng từ người dùng. Thoát.")
            break
        except Exception as e:
            print("[!] [WATCHER ERROR] %s" % e, file=sys.stderr)
            time.sleep(2.0)


# ----------------------------------------------------------------------------- main CLI
def main():
    ap = argparse.ArgumentParser(description="Đo hiệu năng Jetson Nano tự động hoặc thủ công")
    ap.add_argument("--watch", "-w", action="store_true",
                    help="Bật chế độ Watcher Daemon: Tự động chạy nền, tự nhận biết khi WebGIS kích hoạt pipeline, tự thu thập thông số và tự xuất báo cáo khi xong")
    ap.add_argument("--phase", default="baseline", help="Tên kịch bản đo, vd: baseline, live_on, osd_off (ở chế độ watch sẽ tự lấy theo tên video)")
    ap.add_argument("--duration", type=int, default=None, help="Số giây ghi số liệu (mặc định: đo liên tục tới khi pipeline dừng)")
    ap.add_argument("--warmup", type=int, default=0, help="Số giây bỏ qua ở đầu (mặc định: 0s)")
    ap.add_argument("--interval", type=float, default=1.0, help="Chu kỳ lấy mẫu (giây)")
    ap.add_argument("--out", default="bench_results", help="Thư mục lưu kết quả (mặc định: bench_results)")
    ap.add_argument("--iface", default=None, help="Card mạng (mặc định: card có default route)")
    ap.add_argument("--pid", type=int, default=None, help="PID tiến trình pipeline (ở chế độ watch sẽ tự dò)")
    ap.add_argument("--no-tegrastats", action="store_true", help="Không gọi tegrastats (chạy trên máy không phải Jetson)")
    ap.add_argument("--log", default=None, help="File log của pipeline để đọc FPS")
    ap.add_argument("--fps-regex",
                    default=r"(?:\*\*PERF:\s*(?:\{[^}]*?:\s*)?|fps\s*[:=]?\s*)([0-9]+(?:\.[0-9]+)?)",
                    help="Regex lấy FPS từ log; nhóm (1) là số FPS")
    ap.add_argument("--mqtt-host", default=None)
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--mqtt-topic", default="traffic/#")
    ap.add_argument("--mqtt-user", default=None)
    ap.add_argument("--mqtt-pass", default=None)
    ap.add_argument("--mqtt-tls", action="store_true")
    ap.add_argument("--fps-json-key", default=None,
                    help="Tên trường FPS trong JSON telemetry nếu có (vd fps hoặc metrics.fps)")
    args = ap.parse_args()

    if args.watch:
        run_watcher(args)
        return

    # Chế độ chạy thủ công 1 lần
    profiler = JetsonPerformanceProfiler(
        phase=args.phase,
        duration=args.duration,
        warmup=args.warmup,
        interval=args.interval,
        out_dir=args.out,
        iface=args.iface,
        pid=args.pid,
        no_tegrastats=args.no_tegrastats,
        log_file=args.log,
        fps_regex=args.fps_regex,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        mqtt_topic=args.mqtt_topic,
        mqtt_user=args.mqtt_user,
        mqtt_pass=args.mqtt_pass,
        mqtt_tls=args.mqtt_tls,
        fps_json_key=args.fps_json_key
    )

    profiler.start()
    try:
        while profiler.is_running():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[*] Dừng sớm theo yêu cầu.")
    finally:
        profiler.stop()


if __name__ == "__main__":
    main()
