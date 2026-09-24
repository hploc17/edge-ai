#!/usr/bin/env python3
"""Command handler: process commands received via MQTT from Backend/WebGIS.

SECURITY:
  Only the following actions are permitted (strict whitelist):
    - restart_analytics
    - reload_config
    - capture_test_snapshot
    - request_status

  Shell commands are NEVER executed.
  Arbitrary code execution via MQTT is NOT allowed.
  Code updates must be performed via SSH + Git over VPN only.

Compatible with Python 3.6 (JetPack 4.x).
"""

from __future__ import print_function

import json
import os
import threading

ALLOWED_ACTIONS = frozenset([
    'restart_analytics',
    'reload_config',
    'capture_test_snapshot',
    'request_status',
    'get_health',
    'start_video_test',
])


class CommandHandler(object):
    """Process commands received from MQTT and route to registered handlers.

    Usage:
        handler = CommandHandler(publisher)
        handler.register('reload_config', reload_config_fn)
        handler.register('restart_analytics', restart_fn)

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

        handler_fn(payload: dict) -> str (result message)
        """
        if action not in ALLOWED_ACTIONS:
            raise ValueError('Action "%s" is not in the allowed whitelist' % action)
        with self._lock:
            self._handlers[action] = handler_fn

    def handle(self, data):
        """Process a command payload received from MQTT.

        data: dict parsed from JSON
        """
        if not isinstance(data, dict):
            print('[CMD] Rejected: payload is not a JSON object')
            return

        action = data.get('action', '')
        command_id = data.get('command_id', 'unknown')

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
                # If handler returns a dict for get_health, publish directly to device-health topic
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
