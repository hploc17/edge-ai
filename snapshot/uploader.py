#!/usr/bin/env python3
"""Snapshot Uploader: encodes annotated JPEG and uploads via HTTP multipart.
Falls back to OfflineOutbox if network request fails.

Compatible with Python 3.6 (JetPack 4.x).
"""

from __future__ import print_function
import json
import os
import queue
import threading
import time
import uuid

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

try:
    import urllib.request as _urllib_request
    import urllib.error as _urllib_error
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

from config.settings import (
    UPLOAD_ENDPOINT,
    EDGE_TOKEN,
    EDGE_ID,
    CAMERA_ID,
    SEGMENT_ID,
    JPEG_QUALITY,
)


def _encode_jpeg(frame, quality=JPEG_QUALITY):
    if not _HAS_CV2 or frame is None:
        return None
    success, buffer = cv2.imencode(
        '.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
    )
    if not success:
        return None
    return buffer.tobytes()


def _upload_http(jpeg_bytes, meta):
    if not _HAS_URLLIB:
        return False, 'urllib not available'

    boundary = '----TrafficSnapshotBoundary' + uuid.uuid4().hex
    parts = []

    def _add_field(name, value):
        parts.append(('--' + boundary + '\r\n').encode('utf-8'))
        parts.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode('utf-8'))
        parts.append(str(value).encode('utf-8'))
        parts.append(b'\r\n')

    _add_field('edge_id', meta.get('edge_id', EDGE_ID))
    _add_field('camera_id', meta.get('camera_id', CAMERA_ID))
    _add_field('segment_id', meta.get('segment_id', SEGMENT_ID))
    _add_field('event_id', meta.get('event_id', ''))
    _add_field('timestamp', meta.get('timestamp', ''))
    _add_field('traffic_status', meta.get('traffic_status', 'CONGESTED'))
    _add_field('metrics', json.dumps(meta.get('metrics', {})))

    # File part
    parts.append(('--' + boundary + '\r\n').encode('utf-8'))
    parts.append((
        'Content-Disposition: form-data; name="snapshot"; filename="%s.jpg"\r\n'
        'Content-Type: image/jpeg\r\n\r\n' % meta.get('event_id', 'snapshot')
    ).encode('utf-8'))
    parts.append(jpeg_bytes)
    parts.append(b'\r\n')
    parts.append(('--' + boundary + '--\r\n').encode('utf-8'))

    body = b''.join(parts)
    headers = {
        'Content-Type': 'multipart/form-data; boundary=' + boundary,
        'Content-Length': str(len(body)),
        'Authorization': 'Bearer ' + EDGE_TOKEN,
    }

    req = _urllib_request.Request(UPLOAD_ENDPOINT, data=body, headers=headers, method='POST')
    try:
        with _urllib_request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201), 'HTTP %d' % resp.status
    except Exception as err:
        return False, str(err)


class SnapshotWorker(object):
    """Background worker that processes frame encoding and HTTP upload."""

    def __init__(self, outbox=None, jpeg_quality=JPEG_QUALITY):
        self._queue = queue.Queue(maxsize=10)
        self._outbox = outbox
        self._jpeg_quality = int(jpeg_quality)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._stop_event = threading.Event()

    def start(self):
        self._thread.start()
        print('[SNAPSHOT] Uploader worker thread started')

    def stop(self):
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def submit(self, frame, metrics, event_id=None):
        if event_id is None:
            event_id = str(uuid.uuid4())
        task = {
            'frame': frame,
            'metrics': metrics,
            'event_id': event_id,
            'submitted_at': time.time(),
        }
        try:
            self._queue.put_nowait(task)
            return True
        except queue.Full:
            print('[SNAPSHOT] Queue full, dropped event %s' % event_id)
            return False

    def _run(self):
        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if task is None:
                break

            self._process_task(task)
            self._queue.task_done()

    def _process_task(self, task):
        event_id = task['event_id']
        metrics = task['metrics']
        frame = task['frame']

        jpeg_bytes = _encode_jpeg(frame, quality=self._jpeg_quality)
        if jpeg_bytes is None:
            print('[SNAPSHOT] Failed to encode JPEG for %s' % event_id)
            return

        meta = {
            'event_id': event_id,
            'edge_id': EDGE_ID,
            'camera_id': CAMERA_ID,
            'segment_id': SEGMENT_ID,
            'timestamp': metrics.get('timestamp', ''),
            'traffic_status': metrics.get('traffic_status', 'CONGESTED'),
            'metrics': metrics,
        }

        ok, msg = _upload_http(jpeg_bytes, meta)
        if ok:
            print('[SNAPSHOT] Uploaded %s (%d bytes)' % (event_id, len(jpeg_bytes)))
        else:
            print('[SNAPSHOT] Upload failed (%s), saving to outbox...' % msg)
            if self._outbox:
                self._outbox.save(jpeg_bytes, meta, event_id)
