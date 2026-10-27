#!/usr/bin/env python3
"""Offline outbox: persist unsent snapshots to disk for later retry.

When the network is unavailable, JPEG + metadata are stored locally.
A retry thread periodically attempts to re-upload pending items.

Limits:
  - Max 500 files OR 2 GB total
  - When over limit, oldest ALREADY-SENT items are deleted first,
    then oldest pending items if still over limit

Compatible with Python 3.6 (JetPack 4.x).
"""

from __future__ import print_function

import glob
import json
import os
import threading
import time

try:
    import urllib.request as _urllib_request
    import urllib.error as _urllib_error
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

OUTBOX_DIR = os.getenv('OUTBOX_DIR', '/workspace/1908/outbox')
MAX_FILES = 500
MAX_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
RETRY_INTERVAL_S = 30.0
UPLOAD_TIMEOUT_S = 15


class OfflineOutbox(object):
    """File-based offline queue for JPEG snapshots."""

    def __init__(self, upload_url, edge_token,
                 outbox_dir=OUTBOX_DIR,
                 max_files=MAX_FILES,
                 max_size_bytes=MAX_SIZE_BYTES):
        self._upload_url = upload_url
        self._edge_token = edge_token
        self._dir = outbox_dir
        self._max_files = max_files
        self._max_size = max_size_bytes
        self._lock = threading.Lock()
        os.makedirs(self._dir, exist_ok=True)
        self._retry_thread = threading.Thread(target=self._retry_loop, daemon=True)
        self._stop_event = threading.Event()

    def start(self):
        self._retry_thread.start()
        print('[OUTBOX] Started (dir=%s)' % self._dir)

    def stop(self):
        self._stop_event.set()

    def save(self, jpeg_bytes, meta, event_id):
        """Save JPEG and metadata to outbox directory."""
        with self._lock:
            self._enforce_limits()
            base = os.path.join(self._dir, event_id)
            try:
                with open(base + '.jpg', 'wb') as f:
                    f.write(jpeg_bytes)
                with open(base + '.json', 'w', encoding='utf-8') as f:
                    json.dump(meta, f)
                print('[OUTBOX] Saved event %s (%d bytes)' % (event_id, len(jpeg_bytes)))
            except IOError as err:
                print('[OUTBOX] Save error: %s' % err)

    def _pending_items(self):
        """Return list of (json_path, jpg_path) for pending items."""
        json_files = sorted(glob.glob(os.path.join(self._dir, '*.json')))
        items = []
        for jf in json_files:
            jpg = jf.replace('.json', '.jpg')
            if os.path.exists(jpg):
                items.append((jf, jpg))
        return items

    def _enforce_limits(self):
        """Trim outbox to stay within file count and size limits."""
        items = self._pending_items()
        total_size = sum(
            os.path.getsize(j) + os.path.getsize(p)
            for j, p in items
        )
        # Remove oldest items when over limit
        while (len(items) > self._max_files or total_size > self._max_size) and items:
            jf, jpg = items.pop(0)  # oldest first
            size = 0
            for path in (jf, jpg):
                try:
                    size += os.path.getsize(path)
                    os.remove(path)
                except OSError:
                    pass
            total_size = max(0, total_size - size)
            print('[OUTBOX] Removed oldest item to stay within limits')

    def _retry_loop(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(RETRY_INTERVAL_S)
            if self._stop_event.is_set():
                break
            with self._lock:
                items = self._pending_items()
            for jf, jpg in items:
                if self._stop_event.is_set():
                    break
                self._try_send(jf, jpg)

    def _try_send(self, json_path, jpg_path):
        """Attempt to upload a pending item."""
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            with open(jpg_path, 'rb') as f:
                jpeg_bytes = f.read()
        except IOError:
            return

        event_id = meta.get('event_id', 'unknown')
        success = self._upload(jpeg_bytes, meta, event_id)
        if success:
            with self._lock:
                for path in (json_path, jpg_path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            print('[OUTBOX] Sent and removed event %s' % event_id)

    def _upload(self, jpeg_bytes, meta, event_id):
        if not _HAS_URLLIB:
            return False
        try:
            boundary = 'OutboxBoundary-%s' % event_id.replace('-', '')
            body_parts = []
            for key, value in meta.items():
                if value is None:
                    value = ''
                body_parts.append(
                    '--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                    % (boundary, key, str(value))
                )
            filename = 'camera-01_%s.jpg' % event_id.replace('-', '')
            body_parts.append(
                '--%s\r\nContent-Disposition: form-data; name="image"; filename="%s"\r\n'
                'Content-Type: image/jpeg\r\n\r\n' % (boundary, filename)
            )
            body = (
                ''.join(body_parts).encode('utf-8') +
                jpeg_bytes +
                ('\r\n--%s--\r\n' % boundary).encode('utf-8')
            )
            req = _urllib_request.Request(
                self._upload_url,
                data=body,
                headers={
                    'Content-Type': 'multipart/form-data; boundary=%s' % boundary,
                    'Authorization': 'Bearer %s' % self._edge_token,
                    'X-Event-Id': event_id,
                },
                method='POST',
            )
            with _urllib_request.urlopen(req, timeout=UPLOAD_TIMEOUT_S) as resp:
                return 200 <= resp.getcode() < 300
        except Exception:
            return False
