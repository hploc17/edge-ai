#!/usr/bin/env python3
"""Command handler: process commands received via MQTT from Backend/WebGIS.

SECURITY:
  Only the following actions are permitted (strict whitelist):
    - list_videos           : list available video files in fixed directory
    - capture_preview       : grab one frame and upload for ROI drawing
    - set_roi_remote        : write remote ROI config file (normalized coords)
    - start_pipeline        : start analytics pipeline subprocess
    - stop_pipeline         : gracefully stop analytics pipeline subprocess
    - capture_snapshot      : trigger manual snapshot upload
    - get_health            : collect and publish hardware diagnostics
    - restart_analytics     : legacy alias for stop + start
    - reload_config         : reload ROI config without full restart
    - request_status        : report pipeline running status

  Shell commands are NEVER executed.
  Arbitrary code execution via MQTT is NOT allowed.

Compatible with Python 3.6 (JetPack 4.x).
"""

from __future__ import print_function

import json
import os
import threading
import time

try:
    from communication.mqtt_client import parse_timestamp_seconds
except ImportError:
    try:
        from mqtt_client import parse_timestamp_seconds
    except ImportError:
        def parse_timestamp_seconds(value):
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            val_str = str(value).strip()
            try:
                return float(val_str)
            except ValueError:
                pass
            import re
            import datetime
            if val_str.endswith('Z') or val_str.endswith('z'):
                val_str = val_str[:-1] + '+0000'
            val_str = re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', val_str)
            for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
                try:
                    dt = datetime.datetime.strptime(val_str, fmt)
                    return dt.timestamp()
                except ValueError:
                    pass
            return None

ALLOWED_ACTIONS = frozenset([
    # Remote control (new)
    'list_videos',
    'capture_preview',
    'set_roi_remote',
    'start_pipeline',
    'start_csi',
    'stop_pipeline',
    'capture_snapshot',
    # Diagnostics & Spatial
    'get_health',
    'get_spatial_info',
    'request_status',
    'fetch_logs',
    'maintenance_diagnostics',
    # Live Streaming (MediaMTX On-Demand)
    'start_live',
    'stop_live',
    'live_keepalive',
    'live_status',
    # Legacy compatibility
    'capture_test_snapshot',
    'restart_analytics',
    'restart_pipeline',
    'reload_config',
    'start_video_test',
])

# Payload key aliases: support both (action/cmd) and (command_id/request_id)
_ACTION_ALIASES = ('action', 'cmd')
_CMD_ID_ALIASES = ('command_id', 'request_id')


def _extract_action(data):
    """Extract action name from payload, supporting 'action' and 'cmd' aliases."""
    for key in _ACTION_ALIASES:
        if key in data and data[key]:
            return str(data[key])
    return ''


def _extract_command_id(data):
    """Extract command_id from payload, supporting 'command_id' and 'request_id' aliases."""
    for key in _CMD_ID_ALIASES:
        if key in data and data[key]:
            return str(data[key])
    return 'unknown'


class CommandHandler(object):
    """Process commands received from MQTT and route to registered handlers.

    Usage:
        handler = CommandHandler(publisher)
        handler.register('list_videos', list_videos_fn)
        handler.register('start_pipeline', start_pipeline_fn)

        # In MQTTPublisher, set command_callback=handler.handle
    """

    def __init__(self, publisher, dedupe_ttl=60.0, command_ttl=30.0):
        """
        publisher: MQTTPublisher instance (to send command-result)
        dedupe_ttl: Thời gian ghi nhớ command_id đã xử lý để chống lặp (mặc định: 60s)
        command_ttl: Thời hạn sống của lệnh (mặc định: 30s - Fix L8)
        """
        self._publisher = publisher
        self._handlers = {}
        self._lock = threading.Lock()
        self._seen_commands = {}  # {command_id: timestamp}
        self._dedupe_ttl = float(dedupe_ttl)
        self._command_ttl = float(command_ttl)

    def register(self, action, handler_fn):
        """Register a handler function for an action.

        handler_fn(payload: dict) -> any (result message or dict)
        """
        if action not in ALLOWED_ACTIONS:
            raise ValueError('Action "%s" is not in the allowed whitelist' % action)
        with self._lock:
            self._handlers[action] = handler_fn

    def handle(self, data):
        """Process a command payload received from MQTT.

        data: dict parsed from JSON. Supports both:
          {"action": "...", "command_id": "...", "params": {...}}
          {"cmd":    "...", "request_id": "...", "params": {...}}
        """
        if not isinstance(data, dict):
            print('[CMD] Rejected: payload is not a JSON object')
            return

        action = _extract_action(data)
        command_id = _extract_command_id(data)

        # ── TTL Check: Kiểm tra hạn sống của lệnh (Fix L8) ──
        cmd_ts = data.get('timestamp')
        ttl = float(data.get('ttl', self._command_ttl))
        if cmd_ts is not None and parse_timestamp_seconds is not None:
            ts_sec = parse_timestamp_seconds(cmd_ts)
            if ts_sec is not None:
                age = time.time() - ts_sec
                if age > ttl:
                    print('[CMD] Command expired (age=%.1fs > ttl=%.1fs): action=%s command_id=%s' %
                          (age, ttl, action, command_id))
                    self._publisher.publish_command_result(
                        command_id=command_id,
                        action=action or 'unknown',
                        status='expired',
                        message='Command expired (age=%.1fs > ttl=%.1fs)' % (age, ttl),
                    )
                    return

        # ── Deduplication: Chống lặp lệnh trùng lặp trong 60 giây (L1) ──
        if command_id:
            now = time.time()
            with self._lock:
                # Dọn dẹp các lệnh quá hạn 60s
                expired = [cid for cid, ts in self._seen_commands.items() if now - ts > self._dedupe_ttl]
                for cid in expired:
                    del self._seen_commands[cid]

                if command_id in self._seen_commands:
                    print('[CMD] Duplicate command ignored (seen %.1fs ago): action=%s command_id=%s' %
                          (now - self._seen_commands[command_id], action, command_id))
                    return
                self._seen_commands[command_id] = now

        if not action:
            print('[CMD] Rejected: missing action/cmd field in payload')
            self._publisher.publish_command_result(
                command_id=command_id,
                action='unknown',
                status='rejected',
                message='Missing action or cmd field in payload',
            )
            return

        if action not in ALLOWED_ACTIONS:
            print('[CMD] Rejected unknown action: %s' % action)
            self._publisher.publish_command_result(
                command_id=command_id,
                action=action,
                status='rejected',
                message='Unknown or disallowed action: %s' % action,
            )
            return

        print('[CMD] Received action=%s command_id=%s' % (action, command_id))

        with self._lock:
            handler_fn = self._handlers.get(action)

        if handler_fn is None:
            self._publisher.publish_command_result(
                command_id=command_id,
                action=action,
                status='not_implemented',
                message='Handler for action "%s" not registered' % action,
            )
            return

        # Execute handler in a separate thread to not block MQTT callback
        def _run():
            try:
                result = handler_fn(data)

                # Special case: get_health publishes to device-health topic directly
                if action == 'get_health' and isinstance(result, dict) and hasattr(self._publisher, 'publish_device_health'):
                    self._publisher.publish_device_health(command_id=command_id, health_data=result)

                # Chuẩn hóa status từ kết quả handler (Fix L5)
                status = 'completed'
                msg_val = result

                if isinstance(result, dict):
                    raw_status = str(result.get('status', '')).lower().strip()
                    if raw_status in ('error', 'failed', 'rejected'):
                        status = raw_status
                    elif 'error' in result and not raw_status:
                        status = 'error'
                    elif raw_status in ('completed', 'success', 'ok'):
                        status = 'completed'

                    # Trích xuất message nếu là dict gọn {status, message}
                    if 'message' in result and len(result) <= 2:
                        msg_val = result['message']
                elif isinstance(result, tuple) and len(result) == 2:
                    ok, detail = result
                    status = 'completed' if ok else 'error'
                    msg_val = detail
                elif isinstance(result, str):
                    msg_val = result
                elif result is None:
                    msg_val = 'OK'

                self._publisher.publish_command_result(
                    command_id=command_id,
                    action=action,
                    status=status,
                    message=msg_val,
                )
            except Exception as err:
                print('[CMD] Handler error for %s: %s' % (action, err))
                self._publisher.publish_command_result(
                    command_id=command_id,
                    action=action,
                    status='error',
                    message=str(err),
                )

        t = threading.Thread(target=_run, daemon=True)
        t.start()
