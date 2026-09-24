#!/usr/bin/env python3
"""
roi_picker.py
-------------
Cong cu truc quan (dung OpenCV thuan, khong phu thuoc DeepStream/pyds)
de VE ROI BANG CHUOT truc tiep tren 1 khung hinh thuc te tu camera/video.

Tuong thich: Step 6, Python 3.6+, OpenCV (python3-opencv tren Jetson Nano).

Dieu khien trong cua so hien anh:
  - Chuot trai : them 1 diem vao ROI dang ve
  - Chuot phai : xoa diem vua them (undo)
  - Phim [n]   : chot xong ROI hien tai (>=3 diem), chuyen sang ROI tiep theo
                 (thu tu: DETECTION ROI truoc, ANALYSIS ROI sau)
  - Phim [r]   : xoa het diem cua ROI dang ve, ve lai tu dau
  - Phim [s]   : luu ca 2 ROI ra file JSON (roi_config.json) va thoat
  - Phim [q]   : thoat KHONG luu
"""

from __future__ import print_function

import argparse
import json
import os
import sys

import cv2
import numpy as np

STREAMMUX_WIDTH = 1280
STREAMMUX_HEIGHT = 720
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roi_config.json")

_points_by_target = {"detection": [], "analysis": []}
_current_target = "detection"


def grab_one_frame(source_type: str, source: str = None,
                   width: int = STREAMMUX_WIDTH, height: int = STREAMMUX_HEIGHT):
    """Lay 1 frame dai dien tu camera hoac video de nguoi dung ve ROI.

    Tu dong resize ve dung kich thuoc width x height (1280x720) de toa do ve
    khop 100% voi he toa do ma nvstreammux su dung trong pipeline DeepStream.
    """
    cap = None
    s_type = str(source_type).strip().lower()

    if s_type == "file":
        if not source:
            sys.stderr.write("[FATAL] --source la bat buoc voi source-type 'file'\n")
            return _create_fallback_frame(width, height)

        cap = cv2.VideoCapture(source)
        if not cap.isOpened() and (source.endswith(".h264") or source.endswith(".264")):
            # Fallback GStreamer pipeline cho video file raw h264
            gst_str = (
                "filesrc location=\"{}\" ! h264parse ! avdec_h264 ! "
                "videoconvert ! video/x-raw,format=BGR ! appsink"
            ).format(source)
            cap = cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)

        if cap.isOpened():
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total > 3:
                cap.set(cv2.CAP_PROP_POS_FRAMES, total // 3)

    elif s_type in ("usb", "video"):
        dev = source if source is not None else "/dev/video0"
        dev_str = str(dev)
        if dev_str.isdigit():
            cap = cv2.VideoCapture(int(dev_str))
        elif dev_str.startswith("/dev/video"):
            try:
                cap = cv2.VideoCapture(int(dev_str.replace("/dev/video", "")))
            except ValueError:
                cap = cv2.VideoCapture(dev_str)
        else:
            cap = cv2.VideoCapture(dev_str)

    elif s_type == "csi":
        gst_str = (
            "nvarguscamerasrc sensor-id=0 ! "
            "video/x-raw(memory:NVMM),width={w},height={h},framerate=30/1,format=NV12 ! "
            "nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! "
            "video/x-raw,format=BGR ! appsink"
        ).format(w=width, h=height)
        cap = cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)

    elif s_type == "rtsp":
        if source:
            cap = cv2.VideoCapture(source)

    else:
        # Thu mo truc tiep source neu khong xac dinh ro loai
        if source:
            cap = cv2.VideoCapture(source)

    frame = None
    if cap and cap.isOpened():
        # Doc thu toi da 5 frame de bo qua frame den dau tien
        for _ in range(5):
            ret, tmp = cap.read()
            if ret and tmp is not None:
                frame = tmp
                break
        cap.release()

    if frame is None:
        print("[CANH BAO] Khong doc duoc frame truc tiep tu nguon '{}', dung khung hinh mau {}x{}.".format(
            source, width, height
        ), file=sys.stderr)
        return _create_fallback_frame(width, height)

    if frame.shape[1] != width or frame.shape[0] != height:
        frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

    return frame


def _create_fallback_frame(width, height):
    """Tao frame mau neu khong mo duoc camera/video."""
    f = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.rectangle(f, (50, 50), (width - 50, height - 50), (50, 50, 50), 2)
    cv2.putText(f, "KHUNG HINH MAU VE ROI (1280x720)", (width // 4, height // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (180, 180, 180), 2)
    return f


def _on_mouse(event, x, y, _flags, _userdata):
    global _points_by_target, _current_target
    if event == cv2.EVENT_LBUTTONDOWN:
        _points_by_target[_current_target].append((int(x), int(y)))
    elif event == cv2.EVENT_RBUTTONDOWN:
        if _points_by_target[_current_target]:
            _points_by_target[_current_target].pop()


def _render(base_frame):
    frame = base_frame.copy()

    colors = {
        "detection": (0, 165, 255),  # Cam (BGR)
        "analysis": (255, 200, 0),   # Cyan / Xanh lo (BGR)
    }

    for name, pts in _points_by_target.items():
        color = colors[name]
        for p in pts:
            cv2.circle(frame, p, 5, color, -1)
        if len(pts) >= 2:
            for i in range(len(pts) - 1):
                cv2.line(frame, pts[i], pts[i + 1], color, 2)
            if name == _current_target and len(pts) >= 3:
                cv2.line(frame, pts[-1], pts[0], color, 1)  # preview net kin
            elif name != _current_target and len(pts) >= 3:
                cv2.line(frame, pts[-1], pts[0], color, 2)  # polygon hoan thanh

    cur_pts = len(_points_by_target[_current_target])
    hud_lines = [
        "Dang ve: {} ROI ({} diem)".format(_current_target.upper(), cur_pts),
        "Chuot trai: them diem | Chuot phai: xoa diem cuoi (undo)",
        "[n] chot ROI nay, chuyen tiep | [r] xoa lam lai | [s] luu & thoat | [q] thoat",
    ]
    for i, line in enumerate(hud_lines):
        y = 26 + i * 24
        cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1, cv2.LINE_AA)

    return frame


def interactive_pick(source_type: str, source: str = None, output_file: str = OUTPUT_FILE):
    """
    Mo cua so OpenCV cho phep nguoi dung ve DETECTION ROI va ANALYSIS ROI bang chuot.
    Luu ket qua vao output_file JSON va tra ve dict config neu nguoi dung nhan 's'.
    Tra ve None neu thoat bang 'q'.
    """
    global _current_target, _points_by_target
    _points_by_target = {"detection": [], "analysis": []}
    _current_target = "detection"

    frame = grab_one_frame(source_type, source)

    window = "ROI Picker (Step 6) - xem huong dan tren man hinh"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 1280, 720)
    cv2.setMouseCallback(window, _on_mouse)

    print("\n" + "=" * 60)
    print("[ROI PICKER] Bat dau che do ve ROI bang chuot truc tiep.")
    print("  1. Chuot trai: them diem (it nhat 3 diem)")
    print("  2. Chuot phai: undo xoa diem vua them")
    print("  3. Phim 'n': chot DETECTION ROI -> chuyen ve ANALYSIS ROI")
    print("  4. Phim 's': luu ca 2 ROI va nhap kich thuoc duong")
    print("  5. Phim 'q': thoat khong luu")
    print("=" * 60 + "\n")

    result = None
    while True:
        cv2.imshow(window, _render(frame))
        key = cv2.waitKey(25) & 0xFF

        if key == ord("q") or key == 27:
            print("[INFO] Thoat che do ve ROI ma khong luu.")
            break

        elif key in (ord("r"), ord("R")):
            _points_by_target[_current_target] = []
            print("[INFO] Da xoa diem cua {} ROI, ve lai tu dau.".format(_current_target.upper()))

        elif key in (ord("n"), ord("N")):
            if len(_points_by_target[_current_target]) < 3:
                print("[CANH BAO] Can it nhat 3 diem truoc khi chuyen tiep.")
                continue
            if _current_target == "detection":
                _current_target = "analysis"
                print("[INFO] Da chot DETECTION ROI. Gio hay ve ANALYSIS ROI (4 diem cho Homography).")
            else:
                print("[INFO] Da chot ca 2 ROI. Nhan 's' de luu.")

        elif key in (ord("s"), ord("S")):
            det_len = len(_points_by_target["detection"])
            ana_len = len(_points_by_target["analysis"])

            # Neu nguoi dung chi moi ve 1 ROI ma nhan 's', tu dong gan
            if _current_target == "detection" and det_len >= 3 and ana_len == 0:
                print("[INFO] Ban chua chuyen sang Analysis ROI. Su dung Detection ROI nay lam Analysis ROI.")
                _points_by_target["analysis"] = list(_points_by_target["detection"])
                ana_len = len(_points_by_target["analysis"])

            if det_len < 3 or ana_len < 3:
                print("[CANH BAO] Ca DETECTION ROI va ANALYSIS ROI deu can it nhat 3 diem truoc khi luu.")
                continue

            config = {
                "detection_roi": [list(p) for p in _points_by_target["detection"]],
                "analysis_roi": [list(p) for p in _points_by_target["analysis"]],
                "calibration_image_points": [list(p) for p in _points_by_target["analysis"]],
                "frame_width": frame.shape[1],
                "frame_height": frame.shape[0],
                "road_width_m": 10.0,
                "road_length_m": 25.0,
                "lane_count": 2,
            }

            # Neu Analysis ROI co dung 4 diem: hoan hao cho Homography
            if ana_len == 4:
                cv2.destroyAllWindows()
                for _ in range(3):
                    cv2.waitKey(1)
                print("\n[HIEU CHINH TOC DO HOMOGRAPHY - nhan Enter de dung mac dinh 10m x 25m]")
                print("Analysis ROI 4 diem theo thu tu: tren-trai -> tren-phai -> duoi-phai -> duoi-trai.")
                try:
                    # Ho tro ca Python 2 va Python 3 input
                    prompt_fn = input if sys.version_info[0] >= 3 else raw_input
                    w_in = prompt_fn("Chieu rong THAT cua doan duong (m) [Enter = 10.0]: ").strip()
                    if w_in:
                        config["road_width_m"] = float(w_in)

                    l_in = prompt_fn("Chieu dai THAT cua doan duong (m) [Enter = 25.0]: ").strip()
                    if l_in:
                        config["road_length_m"] = float(l_in)

                    lane_in = prompt_fn("So lan duong [Enter = 2]: ").strip()
                    if lane_in:
                        config["lane_count"] = max(1, int(lane_in))
                except (ValueError, EOFError):
                    print("[INFO] Dung gia tri mac dinh: 10.0m x 25.0m, 2 lan xe.")

            out_dir = os.path.dirname(os.path.abspath(output_file))
            if out_dir and not os.path.exists(out_dir):
                os.makedirs(out_dir)

            with open(output_file, "w") as f:
                json.dump(config, f, indent=2)
            print("[INFO] Da luu cau hinh ROI thanh cong vao: {}".format(output_file))
            result = config
            break

    cv2.destroyAllWindows()
    for _ in range(3):
        cv2.waitKey(1)
    return result


def main():
    parser = argparse.ArgumentParser(description="Tool ve ROI truc quan tren 1 frame video/camera (Step 6)")
    parser.add_argument("--source-type", choices=["csi", "usb", "file", "video", "rtsp"], default="file")
    parser.add_argument("--source", "-s", default=None, help="Duong dan video file hoac thiet bi /dev/video*")
    parser.add_argument("--output", "-o", default=OUTPUT_FILE, help="Duong dan file json xuat ra")
    args = parser.parse_args()

    config = interactive_pick(args.source_type, args.source, output_file=args.output)
    if config:
        print("\n[KET QUA CAU HINH ROI]:")
        print(json.dumps(config, indent=2))


if __name__ == "__main__":
    main()
