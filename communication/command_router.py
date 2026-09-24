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

ALLOWED_ACTIONS = frozenset([
    # Remote control (new)
    'list_videos',
    'capture_preview',
    'set_roi_remote',
    'start_pipeline',
    'stop_pipeline',
    'capture_snapshot',
    # Diagnostics
    'get_health',
    'request_status',
    # Legacy compatibility
    'restart_analytics',
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

    def __init__(self, publisher):
        """
        publisher: MQTTPublisher instance (to send command-result)
        """
        self._publisher = publisher
        self._handlers = {}
        self._lock = threading.Lock()

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

                msg_val = result if isinstance(result, (dict, list)) else (str(result) if result else 'OK')
                self._publisher.publish_command_result(
                    command_id=command_id,
                    action=action,
                    status='completed',
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
