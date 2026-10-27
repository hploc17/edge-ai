#!/usr/bin/env python3
"""
LiveStreamSender: WebSocket Ingest Client for Jetson Nano.

Transmits real-time JPEG frames from GStreamer appsink to Backend (/ws/ingest/{edge_id}).
On-Demand behavior:
- Handshakes with backend on connection.
- Listens for {"type": "start"} and {"type": "stop"} commands from backend.
- Strictly transmits frames ONLY when backend confirms active viewers.
- Zero-Queue principle: Drops frames locally when channel is busy or rate limit reached.

Compatible with Python 3.6 (JetPack 4.x).
"""

import json
import logging
import os
import sys
import threading
import time

try:
    import websocket
except ImportError:
    websocket = None


class LiveStreamSender(object):
    """Quản lý kết nối WebSocket Ingest từ Jetson lên Backend."""

    def __init__(self, backend_url, edge_id, edge_token, width=640, height=360, fps=10):
        self.backend_url = backend_url.rstrip('/')
        self.edge_id = edge_id
        self.edge_token = edge_token
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.min_interval = 1.0 / max(1, self.fps)

        self.ws = None
        self.is_connected = False
        self.is_streaming = False
        self.running = False
        self.thread = None

        self.last_sent_time = 0.0
        self.lock = threading.Lock()

        # Suy ra WS URL từ Backend HTTP URL
        if self.backend_url.startswith('https://'):
            ws_base = 'wss://' + self.backend_url[8:]
        elif self.backend_url.startswith('http://'):
            ws_base = 'ws://' + self.backend_url[7:]
        else:
            ws_base = 'ws://' + self.backend_url

        self.ws_url = '{}/ws/ingest/{}?token={}'.format(ws_base, self.edge_id, self.edge_token)

    def start(self):
        if websocket is None:
            print('[LIVE SENDER] WARNING: "websocket-client" not installed. Live streaming disabled.')
            print('[LIVE SENDER] Install via: pip3 install websocket-client')
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, name='LiveStreamSenderThread')
        self.thread.daemon = True
        self.thread.start()
        print('[LIVE SENDER] Started background ingest thread targeting: {}'.format(self.ws_url))

    def stop(self):
        self.running = False
        self.is_streaming = False
        self.is_connected = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    def _run_loop(self):
        retry_delay = 2.0
        while self.running:
            try:
                headers = [
                    'X-Edge-Token: {}'.format(self.edge_token)
                ]

                ws_app = websocket.WebSocketApp(
                    self.ws_url,
                    header=headers,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )
                self.ws = ws_app
                ws_app.run_forever(ping_interval=15, ping_timeout=10)

            except Exception as e:
                print('[LIVE SENDER] Connection error: {}'.format(e))

            self.is_connected = False
            self.is_streaming = False

            if not self.running:
                break

            time.sleep(retry_delay)
            retry_delay = min(15.0, retry_delay * 1.5)

    def _on_open(self, ws):
        self.is_connected = True
        print('[LIVE SENDER] Connected to Backend Ingest. Sending handshake hello...')
        hello_payload = {
            'type': 'hello',
            'edge_id': self.edge_id,
            'width': self.width,
            'height': self.height,
            'fps': self.fps
        }
        try:
            ws.send(json.dumps(hello_payload))
        except Exception as e:
            print('[LIVE SENDER] Handshake failed: {}'.format(e))

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            if msg_type == 'start':
                self.is_streaming = True
                print('[LIVE SENDER] >>> START STREAMING <<< (Viewers active on WebGIS)')
            elif msg_type == 'stop':
                self.is_streaming = False
                print('[LIVE SENDER] >>> STOP STREAMING <<< (0 viewers - entering On-Demand Idle)')
        except Exception as e:
            print('[LIVE SENDER] Error parsing message: {}'.format(e))

    def _on_error(self, ws, error):
        print('[LIVE SENDER] WebSocket error: {}'.format(error))

    def _on_close(self, ws, *args):
        self.is_connected = False
        self.is_streaming = False
        print('[LIVE SENDER] WebSocket ingest connection closed')

    def send_frame(self, jpeg_bytes):
        """Được gọi từ GStreamer appsink để gửi binary JPEG frame."""
        if not self.is_connected or not self.is_streaming or not self.ws:
            return False

        now = time.time()
        # Rate-limiting theo FPS cấu hình (mặc định 10 FPS)
        if (now - self.last_sent_time) < self.min_interval:
            return False

        try:
            with self.lock:
                if self.ws and self.is_connected:
                    self.ws.send(jpeg_bytes, opcode=websocket.ABNF.OPCODE_BINARY)
                    self.last_sent_time = now
                    return True
        except Exception as e:
            # Drop frame nếu socket nghẽn
            return False

        return False
