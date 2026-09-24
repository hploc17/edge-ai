# Ket qua kiem thu jetson_snapshot v2

## Da chay

- `python -m unittest discover -s tests -v`: **26/26 PASS**.
- `tests/check_backend_contract.py` voi Backend snapshot hien co:
  **4/4 luong PASS** (VIDEO/CSI x MANUAL/CONGESTION).
- Backend nhan multipart JPEG that, bao ve anh bang token, Viewer khong duoc
  gui command, luu anh, goi `snapshot:ready` hai lan va `congestion:event` hai lan.
- `ast.parse(..., feature_version=(3,6))`: **10/10 file Python PASS**.

## Nhung gi unit tests kiem tra

- Video: manual/auto chup CSI; khong copy frame demo.
- CSI: manual/auto copy frame cua pipeline; khong goi mo CSI moi.
- Xac nhan 15 giay, cooldown 60 giay, FREE/SLOW/UNKNOWN khong tu chup.
- Telemetry mat quang/stale/duplicate/khac edge/NaN bi xu ly dung.
- Whitelist action, chong retained command, command het han, path injection.
- Hang doi bounded; khong co frame thi timeout; khong copy GPU khi idle.
- Upload/encode chay trong worker, khong trong luong goi submit_frame.
- Giu anh mat mang, retry cung anh va ID qua restart.
- Dedupe manual request ca truoc va sau restart; receipt terminal duoc gioi han.
- Outbox day khong xoa anh chua gui; khong chup them gay tran.
- Recovery neu ngat sau rename JPEG hoac sau reserve nhung chua co JPEG.
- GStreamer fixed argv, shell=False, capture timeout, gioi han JPEG.
- Ma hoa JPEG OpenCV that, RGBA -> BGR va nhan nguon video demo.
- HTTP multipart, Bearer, chan redirect, phan hoi chua xac nhan khong xoa anh.
- Exception encoder/callback khong lam chet worker.
- File lock ngan hai service dung cung outbox.

## Moi truong kiem thu

- Linux x86_64, Python 3.12; Python 3.6 moi kiem tra grammar, chua chay runtime.
- Paho MQTT 1.6.1, requests 2.27.1, OpenCV 5.0.0 trong moi truong test rieng.
- Node.js v24.19.0 va source Backend hien co, khong sua Backend.
- CSI gia lap tra JPEG test; clock gia lap de test 15/60 giay khong can cho thuc.

## Chua kiem chung o day

- CSI/Argus, sensor-id, sensor mode va thoi gian auto-exposure tren Jetson that.
- Map RGBA NvBufSurface/pyds, builder OSD va muc FPS/RAM thuc te tren Jetson Nano.
- Python 3.6 + phien ban OpenCV/JetPack thuc te cua thiet bi.
- Dang nhap TLS/ACL vao cum HiveMQ that cua nguoi dung.
- Browser nhan WebSocket va anh qua mang thuc; smoke test xac minh server goi emit,
  khong mo browser hay client WebSocket that.
- Mat nguon vat ly trong luc SD card dang ghi, nguon dien/camera phan cung.

Khong co so lieu FPS, do tre hay do chinh xac thuc nghiem duoc tao gia.
Backend/Frontend/main nhan dien cua nguoi dung khong duoc chinh sua trong goi nay.
