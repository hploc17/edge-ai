"""Capture/encoding functions; invoked ONLY by the snapshot worker."""
import os
import subprocess
import tempfile

import cv2
import numpy as np

def validate_jpeg(data, maximum=2 * 1024 * 1024):
    if not isinstance(data, bytes) or not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
        raise ValueError("Invalid or truncated JPEG")
    if len(data) > maximum:
        raise ValueError("JPEG exceeds SNAPSHOT_MAX_JPEG_BYTES")
    return data


class CsiCapture(object):
    def __init__(self, sensor_id=0, width=1920, height=1080, fps=30, timeout=12,
                 max_bytes=2 * 1024 * 1024, runner=None):
        self.sensor_id, self.width, self.height, self.fps = map(int, (sensor_id, width, height, fps))
        if self.sensor_id < 0 or min(self.width, self.height, self.fps) <= 0:
            raise ValueError("Invalid CSI sensor/dimensions/FPS")
        self.timeout, self.max_bytes = float(timeout), int(max_bytes)
        self.runner = runner or subprocess.run

    def __call__(self, quality):
        # Own directory, generated name; no MQTT values ever become a shell command/path.
        with tempfile.TemporaryDirectory(prefix="traffic-csi-") as directory:
            filename = os.path.join(directory, "frame.jpg")
            argv = ["gst-launch-1.0", "-e", "-q", "nvarguscamerasrc",
                    "sensor-id=%d" % self.sensor_id, "num-buffers=1", "!",
                    "video/x-raw(memory:NVMM),width=%d,height=%d,framerate=%d/1,format=NV12"
                    % (self.width, self.height, self.fps), "!", "nvvidconv", "!",
                    "video/x-raw,format=I420", "!", "jpegenc", "quality=%d" % quality,
                    "!", "filesink", "location=" + filename]
            # Do not collect unbounded GStreamer logs in RAM or leak them via MQTT.
            with open(os.devnull, "wb") as quiet:
                try:
                    result = self.runner(argv, shell=False, stdout=quiet, stderr=quiet,
                                         timeout=self.timeout, check=False)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("CSI_CAPTURE_TIMEOUT")
                except OSError:
                    raise RuntimeError("GST_LAUNCH_UNAVAILABLE")
            if result.returncode != 0 or not os.path.isfile(filename):
                raise RuntimeError("CSI_CAPTURE_FAILED_OR_CAMERA_BUSY")
            with open(filename, "rb") as image:
                return validate_jpeg(image.read(self.max_bytes + 1), self.max_bytes)


def encode_frame(frame, quality, color_format="BGR"):
    if frame is None:
        raise ValueError("SNAPSHOT_FRAME_IS_NONE")

    frame = np.asarray(frame)

    if frame.dtype != np.uint8:
        frame = np.clip(frame, 0, 255).astype(np.uint8)

    frame = np.ascontiguousarray(frame)

    if color_format == "RGBA":
        if frame.ndim != 3 or frame.shape[2] != 4:
            raise ValueError(
                "EXPECTED_RGBA_FRAME_GOT_%s" % (str(frame.shape),)
            )
        frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)

    elif color_format == "BGR":
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(
                "EXPECTED_BGR_FRAME_GOT_%s" % (str(frame.shape),)
            )
    else:
        raise ValueError("UNSUPPORTED_COLOR_FORMAT_%s" % color_format)

    success, encoded = cv2.imencode(
        ".jpg",
        frame,
        [
            int(cv2.IMWRITE_JPEG_QUALITY),
            int(quality)
        ]
    )

    if not success:
        raise RuntimeError("JPEG_ENCODE_FAILED")

    return encoded.tobytes()

def label_demo_image(jpeg, quality, timestamp, trigger):
    """Always burn in provenance: existing Backend may drop extra metadata fields."""
    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("JPEG_DECODE_FAILED")
    width = frame.shape[1]
    lines = ["CSI LIVE PHOTO / ANALYSIS: DEMO VIDEO", "NOT congestion evidence for the demo video",
             "%s | %s" % (trigger, timestamp)]
    scale = max(0.3, min(0.7, width / 1400.0))
    step = max(18, int(34 * scale / 0.7))
    cv2.rectangle(frame, (0, 0), (width, step * 3 + 12), (20, 20, 20), -1)
    for index, line in enumerate(lines):
        cv2.putText(frame, line, (8, (index + 1) * step), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (0, 220, 255), 1, cv2.LINE_AA)
    return encode_frame(frame, quality)
