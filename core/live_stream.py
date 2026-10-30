#!/usr/bin/env python3
"""
Live Stream Controller for Jetson Nano & MediaMTX On-Demand Streaming.

Architecture:
- Manages GStreamer 'valve' element (drop=true by default).
- Controlled on-demand via MQTT commands (start_live, stop_live, live_keepalive).
- Automatically shuts off after LIVE_IDLE_TIMEOUT_S (default 60s) of inactivity.
- On error (e.g. MediaMTX down or network drop), closes valve gracefully without
  interrupting the primary DeepStream AI pipeline.

Compatible with Python 3.6 (JetPack 4.x).
"""

from __future__ import print_function

import os
import sys
import threading
import time


class LiveStreamController(object):
    """Quản lý trạng thái và vòng đời của nhánh Live Stream On-Demand."""

    def __init__(self, valve=None, encoder=None, idle_timeout_s=60, rtsp_url="", continuous_mode=False, sink=None):
        self.valve = valve
        self.encoder = encoder
        self.sink = sink
        self.rtsp_url = str(rtsp_url)
        self.error_message = None
        self.last_keepalive_time = time.time()

        # Fix V1: Chế độ Continuous 24/7 PHẢI được bật tường minh (continuous_mode=True hoặc LIVE_CONTINUOUS_MODE=true).
        # Mặc định hệ thống luôn là On-Demand: van đóng ban đầu (drop=True), trạng thái 'off', không tốn 16GB/ngày.
        env_continuous = os.getenv("LIVE_CONTINUOUS_MODE", "0").lower() in ("1", "true", "yes")
        self.continuous_mode = bool(continuous_mode) or env_continuous

        parsed_timeout = float(idle_timeout_s) if idle_timeout_s is not None else 60.0
        if not self.continuous_mode and parsed_timeout <= 0:
            parsed_timeout = 60.0  # An toàn: ép về 60s On-Demand nếu không bật continuous_mode tường minh
        self.idle_timeout_s = parsed_timeout

        self._lock = threading.Lock()
        self._timer_thread = None
        self._stop_timer = False

        if self.continuous_mode and self.idle_timeout_s <= 0:
            self.state = "on"
            initial_drop = False
        else:
            self.state = "off"
            initial_drop = True

        if self.valve is not None:
            try:
                self.valve.set_property("drop", initial_drop)
            except Exception as e:
                print("[LIVE CONTROLLER] Warning setting initial valve drop: %s" % e)

        # Bật thread giám sát timeout nếu ở chế độ on-demand
        if self.idle_timeout_s > 0:
            self._start_timer_thread()

    def _start_timer_thread(self):
        self._stop_timer = False
        self._timer_thread = threading.Thread(
            target=self._idle_monitor_loop,
            name="LiveStreamIdleMonitor"
        )
        self._timer_thread.daemon = True
        self._timer_thread.start()

    def _idle_monitor_loop(self):
        """Tự động ngắt phát nếu có bật chế độ idle timeout (> 0)."""
        while not self._stop_timer:
            time.sleep(2.0)
            if self.idle_timeout_s <= 0:
                continue
            with self._lock:
                if self.state == "on":
                    elapsed = time.time() - self.last_keepalive_time
                    if elapsed > self.idle_timeout_s:
                        print(
                            "[LIVE CONTROLLER] Idle timeout reached (%.1fs > %.1fs). Auto-stopping..."
                            % (elapsed, self.idle_timeout_s)
                        )
                        self._apply_stop(reason="idle_timeout")

    def _apply_stop(self, reason="requested"):
        """Nội bộ: đóng valve và cập nhật trạng thái."""
        if self.valve is not None:
            try:
                self.valve.set_property("drop", True)
            except Exception as e:
                print("[LIVE CONTROLLER] Error closing valve: %s" % e)

        self.state = "off"
        print("[LIVE CONTROLLER] Stream stopped (reason=%s). Valve closed (drop=True)." % reason)

    def _force_idr_frame(self):
        """Phát tín hiệu ép encoder sinh ra khung hình I-frame (IDR) lập tức."""
        if self.encoder is None:
            return

        try:
            # Phương án 1: Thử dùng GstVideo event nếu môi trường có gi
            import gi
            gi.require_version("Gst", "1.0")
            gi.require_version("GstVideo", "1.0")
            from gi.repository import Gst, GstVideo

            # Gửi downstream force-key-unit event
            event = GstVideo.video_event_new_downstream_force_key_unit(
                Gst.CLOCK_TIME_NONE, 0, 0, True, 0
            )
            pad = self.encoder.get_static_pad("sink")
            if pad and pad.is_linked():
                pad.send_event(event)
                print("[LIVE CONTROLLER] Successfully dispatched downstream force-key-unit event.")
        except Exception as e:
            # Fallback nếu không có GstVideo binding
            try:
                # Một số encoder hỗ trợ set property trực tiếp
                if hasattr(self.encoder, "set_property"):
                    # nvv4l2h264enc force-idr property nếu khả dụng
                    pass
            except Exception:
                pass
            print("[LIVE CONTROLLER] Force keyframe event notice: %s" % e)

    def start(self):
        """Kích hoạt mở luồng phát Live Stream (On-Demand)."""
        with self._lock:
            if self.state == "on":
                self.last_keepalive_time = time.time()
                return {
                    "status": "already_running",
                    "state": self.state,
                    "rtsp_url": self.rtsp_url
                }

            self.state = "starting"
            self.error_message = None

            # Phục hồi trạng thái sink nếu trước đó bị lỗi ngắt về NULL (Fix V2)
            if self.sink is not None and hasattr(self.sink, "set_state"):
                try:
                    import gi
                    gi.require_version("Gst", "1.0")
                    from gi.repository import Gst
                    playing_state = Gst.State.PLAYING
                except Exception:
                    playing_state = "PLAYING"
                try:
                    self.sink.set_state(playing_state)
                except Exception as _sink_err:
                    print("[LIVE CONTROLLER] Notice re-arming sink to PLAYING: %s" % _sink_err)

            if self.valve is not None:
                try:
                    self.valve.set_property("drop", False)
                    print("[LIVE CONTROLLER] Valve opened (drop=False). Starting H.264 push...")
                except Exception as e:
                    self.state = "error"
                    self.error_message = "Failed to open valve: %s" % e
                    print("[LIVE CONTROLLER] [ERROR] %s" % self.error_message)
                    return {
                        "status": "error",
                        "state": self.state,
                        "error": self.error_message
                    }

            self._force_idr_frame()
            self.state = "on"
            self.last_keepalive_time = time.time()

            return {
                "status": "started",
                "state": self.state,
                "rtsp_url": self.rtsp_url
            }

    def stop(self, reason="requested"):
        """Dừng luồng phát Live Stream (Fix V1: Cho phép dừng chủ động, đóng valve drop=True)."""
        with self._lock:
            # Nếu đang ở chế độ continuous_mode VÀ lý do dừng chỉ là idle timeout (không phải lệnh dừng chủ động)
            if self.continuous_mode and self.idle_timeout_s <= 0 and reason not in ("force", "pipeline_stop", "stop_live", "user_stop", "requested"):
                print("[LIVE CONTROLLER] Continuous streaming enabled. Ignoring idle timeout stop.")
                return {"status": "continuous_running", "state": self.state, "reason": "continuous_mode"}

            if self.state == "off":
                return {"status": "already_stopped", "state": self.state}

            self._apply_stop(reason=reason)
            return {"status": "stopped", "state": self.state, "reason": reason}

    def keep_alive(self):
        """Nhận nhịp tim duy trì luồng từ người xem WebGIS."""
        with self._lock:
            if self.state == "on":
                self.last_keepalive_time = time.time()
                return {"status": "ok", "state": self.state}
            else:
                # Nếu đang tắt mà có keep-alive, tự động bật
                return self.start()

    def status(self):
        """Lấy thông tin trạng thái hoạt động hiện tại."""
        with self._lock:
            now = time.time()
            since_keepalive = round(now - self.last_keepalive_time, 1) if self.last_keepalive_time else None
            return {
                "state": self.state,
                "rtsp_url": self.rtsp_url,
                "idle_timeout_s": self.idle_timeout_s,
                "seconds_since_keepalive": since_keepalive,
                "error": self.error_message
            }

    def update_rtsp_url(self, new_url):
        """Cập nhật địa chỉ RTSP ingest động nhận từ Backend qua MQTT (Fix V6)."""
        if not new_url:
            return
        with self._lock:
            if self.rtsp_url != new_url:
                print("[LIVE CONTROLLER] Updating RTSP Ingest URL dynamically to: %s" % new_url)
                self.rtsp_url = new_url
                if self.sink is not None and hasattr(self.sink, "set_property"):
                    try:
                        self.sink.set_property("location", new_url)
                    except Exception as e:
                        print("[LIVE CONTROLLER] Notice setting sink location: %s" % e)

    def on_bus_error(self, message):
        """Xử lý sự kiện lỗi bus từ nhánh RTSP sink (không làm crash pipeline AI - Fix V2)."""
        with self._lock:
            self.error_message = str(message)
            self.state = "error"
            if self.valve is not None:
                try:
                    self.valve.set_property("drop", True)
                except Exception:
                    pass
            if self.sink is not None and hasattr(self.sink, "set_state"):
                try:
                    import gi
                    gi.require_version("Gst", "1.0")
                    from gi.repository import Gst
                    null_state = Gst.State.NULL
                except Exception:
                    null_state = "NULL"
                try:
                    self.sink.set_state(null_state)
                except Exception:
                    pass
            print(
                "[LIVE CONTROLLER] [STREAM BRANCH ERROR] %s. Valve closed; main DeepStream AI pipeline is intact."
                % self.error_message
            )


# Global singleton instance (nếu cần truy cập nhanh)
_GLOBAL_CONTROLLER = None
_GLOBAL_LOCK = threading.Lock()


def set_global_controller(controller):
    global _GLOBAL_CONTROLLER
    with _GLOBAL_LOCK:
        _GLOBAL_CONTROLLER = controller


def get_global_controller():
    global _GLOBAL_CONTROLLER
    with _GLOBAL_LOCK:
        return _GLOBAL_CONTROLLER


def register_live_handlers(cmd_handler):
    """Đăng ký các lệnh điều khiển Live Stream vào CommandHandler."""
    def _handle_start(payload):
        ctrl = get_global_controller()
        if not ctrl:
            return {'status': 'error', 'message': 'LiveStreamController not ready'}
        if isinstance(payload, dict):
            params = payload.get('params', {})
            rtsp_url = params.get('rtsp_url') if isinstance(params, dict) else None
            if rtsp_url:
                ctrl.update_rtsp_url(rtsp_url)
        return ctrl.start()

    def _handle_stop(payload):
        ctrl = get_global_controller()
        if not ctrl:
            return {'status': 'error', 'message': 'LiveStreamController not ready'}
        return ctrl.stop(reason='mqtt_command')

    def _handle_keepalive(payload):
        ctrl = get_global_controller()
        if not ctrl:
            return {'status': 'error', 'message': 'LiveStreamController not ready'}
        return ctrl.keep_alive()

    def _handle_status(payload):
        ctrl = get_global_controller()
        if not ctrl:
            return {'state': 'off', 'message': 'LiveStreamController not ready'}
        return ctrl.status()

    cmd_handler.register('start_live', _handle_start)
    cmd_handler.register('stop_live', _handle_stop)
    cmd_handler.register('live_keepalive', _handle_keepalive)
    cmd_handler.register('live_status', _handle_status)
    print('[LIVE STREAM] Registered start_live, stop_live, live_keepalive, live_status into CommandHandler')

