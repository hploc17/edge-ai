# HUONG DAN CHAY VA DANH SACH ARGUMENTS - EDGE TRAFFIC OPTIMAL
*(Jetson Nano - DeepStream 6.0.1 - YOLO11 - CSI Camera / Video / RTSP)*

---

## 1. TONG QUAN CAC SCRIPTS KHOI CHAY

Thu muc chua cac script tien ich da duoc cau hinh toi uu cho Docker va phan cung NVIDIA Jetson Nano:

| Script | Cong dung | Cach su dung |
|---|---|---|
| `run.sh` | Khoi chay he thong o che do chay ngam (Daemon) hoac tuong tac | `./run.sh` hoac `./run.sh -it` |
| `run_ds.sh` | Vao truc tiep moi truong Bash ben trong Container (giong `traffic_pipeline_demo`) | `./run_ds.sh` |
| `view_log.sh` | Theo doi log thoi gian thuc cua container dang chay | `./view_log.sh` |
| `stop.sh` | Dung va giai phong container an toan | `./stop.sh` |

Truoc khi chay lan dau, cap quyen thuc thi cho tat ca cac file script:
```bash
chmod +x *.sh
```

---

## 2. CAC CHE DO CHAY THUC TE

### Che do 1: Chay ngam he thong (Daemon Mode - Khuyen dung cho van hanh thuc te)
Container se tu dong chay ngam duoi background voi chinh sach `--restart unless-stopped`:
```bash
./run.sh
```
- Theo doi tien trinh hoat dong:
  ```bash
  ./view_log.sh
  ```
- Dung he thong:
  ```bash
  ./stop.sh
  ```

### Che do 2: Vao moi truong Interactive (Debug va chay thu cong)
Ban co the vao truc tiep terminal ben trong container de test tung lenh:
```bash
./run_ds.sh
# Hoac:
./run.sh -it
```
Khi da o ben trong container (`/workspace` hoac `/app`):
```bash
# Chay voi camera CSI (mac dinh):
python3 main.py --source csi --sensor-id 0

# Chay voi video file (co san trong Video/):
python3 main.py --source Video/1.h264
# Hoac:
python3 main.py --source /workspace/Video/1.h264

# Chay khong can hien thi man hinh GUI (Headless):
python3 main.py --source csi --no-display
```

### Che do 3: Cai dat tu dong chay khi bat nguon (Systemd Service)
He thong da co san file service `edge-traffic-docker.service`.
```bash
sudo cp edge-traffic-docker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable edge-traffic-docker.service
sudo systemctl start edge-traffic-docker.service
```

---

## 3. DANH SACH CHI TIET CAC ARGUMENTS (main.py)

Cu phap tong quat:
```bash
python3 main.py [source] [options]
```

### A. Nguon video (Video Source Arguments)
| Argument | Kieu du lieu | Mac dinh | Y nghia va Cach dung |
|---|---|---|---|
| `source` / `-s` / `--source` | String | `csi` | Nguon video dau vao. Co the truyen:<br>- `csi` hoac `csi://0`: Camera CSI Jetson Nano<br>- `/duong/dan/video.mp4`: File video cuc bo<br>- `rtsp://admin:pass@ip:554/stream`: Luong IP Camera RTSP<br>- `/dev/video0`: USB Webcam |
| `--sensor-id` | Int | `0` | Sensor ID cua camera CSI (0 hoac 1 tren board Jetson Nano B01). |
| `--source-fps` | Float | `30.0` | Toc do khung hinh danh dinh cua camera/video dau vao (dung dong bo clock PTS). |

### B. Cau hinh mo hinh & Khong gian (Model & Spatial Configs)
| Argument | Kieu du lieu | Mac dinh | Y nghia va Cach dung |
|---|---|---|---|
| `--roi-config` | String (Path) | `configs/roi_traffic_nano.json` | Duong dan file JSON dinh nghia toa do vung Detection ROI, Analysis ROI, 4 diem can bang Perspective Calibration, chieu rong duong (`road_width_m`) va chieu dai doan duong (`road_length_m`). |
| `--infer-config` | String (Path) | `configs/config_infer_yolo11_nano.txt` | File cau hinh DeepStream nvinfer cho mo hinh YOLO11 (chua engine TensorRT, threshold, custom parser lib). |
| `--tracker-config` | String (Path) | `configs/config_tracker_optimized.yml` | File cau hinh DeepStream NvTracker (NvDCF/NvSORT) toi uu hoa bo nho cho Jetson Nano 4GB. |
| `--labels` | String (Path) | `configs/labels_custom.txt` | File danh sach nhan phuong tien (ID: Name). |
| `--vehicle-classes` | String | `car,motorcycle,bus,truck` | Danh sach cac class phuong tien can loc va phan tich (ngan cach boi dau phay). |
| `--detection-margin` | Int | `100` | So pixel mo rong quanh Analysis ROI de phat hien phuong tien truoc khi vao vung tinh toan van toc. |

### C. Bo dem & Theo doi phuong tien (Presence Tracking)
| Argument | Kieu du lieu | Mac dinh | Y nghia va Cach dung |
|---|---|---|---|
| `--enter-confirm` | Float | `0.10` | Thoi gian (giay) mot track ID phai nam lien tuc trong ROI de xac nhan da vao vung. Giup loai bo nhap nhay ID. |
| `--exit-confirm` | Float | `0.25` | Thoi gian (giay) track ID o ngoai ROI truoc khi xac nhan da roi khoi vung. |
| `--lost-timeout` | Float | `1.00` | Thoi gian (giay) toi da neu mat dau track ID thi xoa khoi bo nho dem. |

### D. Uoc luong van toc & Homography (Speed Estimator)
| Argument | Kieu du lieu | Mac dinh | Y nghia va Cach dung |
|---|---|---|---|
| `--speed-window` | Float | `2.00` | Cua so thoi gian (giay) dung de hoi quy vi tri va tinh toc do tuc thoi. |
| `--speed-min-time` | Float | `0.80` | Thoi gian theo doi toi thieu (giay) de bat dau xuat van toc tin cay. |
| `--speed-min-displacement` | Float | `0.35` | Khoang cach di chuyen toi thieu tren mat duong (met) truoc khi tinh van toc (tranh xe dung yen bi nhay toc do do rung pixel). |
| `--speed-smoothing-alpha` | Float | `0.25` | He so lam min EMA (Exponential Moving Average) cho van toc (0.0 -> 1.0). |
| `--speed-max-gap` | Float | `0.75` | Khoang cach thoi gian toi da giua 2 frame phat hien. Neu lau hon thi reset track speed. |
| `--speed-max-kmh` | Float | `130.0` | Nguong toc do vat ly toi da (km/h) de loai bo cac gia tri outlier bat thuong. |

### E. Phan loai trang thai ket xe (Traffic Classification)
| Argument | Kieu du lieu | Mac dinh | Y nghia va Cach dung |
|---|---|---|---|
| `--stopped-speed-kmh` | Float | `3.0` | Nguong van toc (km/h) de danh dau xe dang dung yen. |
| `--congested-speed-kmh` | Float | `5.0` | Nguong van toc trung binh (km/h) de canh bao trang thai UN TAC (CONGESTED). |
| `--slow-speed-kmh` | Float | `15.0` | Nguong van toc trung binh (km/h) de xep loai trang thai XE DONG / DI CHAM (SLOW). |
| `--slow-density` | Float | `25.0` | Mat do phuong tien (xe/km/lan) bat dau chuyen sang trang thai SLOW. |
| `--congested-density` | Float | `40.0` | Mat do phuong tien (xe/km/lan) bat dau chuyen sang trang thai CONGESTED. |

### F. Du bao ket xe 5 - 10 phut (Forecast)
| Argument | Kieu du lieu | Mac dinh | Y nghia va Cach dung |
|---|---|---|---|
| `--forecast-min-history` | Float | `300.0` | Thoi gian thu thap du lieu toi thieu (5 phut = 300s) truoc khi mo model du bao trang thai 5m/10m. |
| `--forecast-history` | Float | `900.0` | Cua so bo nho lich su toi da dung cho model du bao (15 phut = 900s). |

### G. Tich hop he thong Cloud & Snapshot (Integration Flags)
| Argument | Kieu du lieu | Mac dinh | Y nghia va Cach dung |
|---|---|---|---|
| `--no-mqtt` | Flag (Action) | `False` | Tat toan bo ket noi MQTT (khong gui Telemetry len Broker HiveMQ, khong lang nghe Remote Command). |
| `--no-snapshot` | Flag (Action) | `False` | Tat dich vu chup anh Snapshot (khong chup khi ket xe, khong phan hoi lenh chup tu Cloud). |
| `--no-display` | Flag (Action) | `False` | Che do Headless khong hien thi cua so GUI tren man hinh X11 (tiet kiem RAM va GPU cua Jetson Nano). |
| `--setup` | Flag (Action) | `False` | Mo cua so OpenCV de click chuot ve ROI, nhap chieu dai/rong duong va tu dong ghi file JSON cau hinh. |

---

## 4. VI DU CAC CA SU DUNG THUC TE

### Vi du 0: Ve ROI va nhap kich thuoc mat duong truc tiep bang chuot (--setup)
```bash
# Ve ROI tren video file:
python3 main.py --source Video/1.h264 --setup

# Hoac ve ROI truc tiep tu Camera CSI thuc dia:
python3 main.py --source csi --sensor-id 0 --setup
```
**Cac thao tac trong cua so hien thi:**
- **Chuot trai**: Click them diem. Voi **ANALYSIS ROI**, click 4 diem theo thu tu: `Near-Left (P1) -> Near-Right (P2) -> Far-Right (P3) -> Far-Left (P4)`.
- **[n]**: Chuyen sang ve vung **DETECTION ROI** (neu bo qua khong ve, he thong se tu dong mo rong Analysis ROI them 100px).
- **Chuot phai**: Xoa diem vua click (Undo).
- **[r]**: Xoa toan bo diem dang ve de ve lai tu dau.
- **[s]**: Chot va luu. Cua so dong lai, terminal se hien prompt:
  ```text
  Nhap chieu rong mat duong (road_width_m) [Mac dinh: 7.5]: 7.0
  Nhap chieu dai doan duong (road_length_m) [Mac dinh: 25.0]: 20.0
  Nhap so lan duong (lane_count) [Mac dinh: 2]: 2
  ```
  File `configs/roi_traffic_nano.json` se duoc tu dong cap nhat va he thong hoi ban co muon tiep tuc chay pipeline phan tich luon khong.

### Vi du 1: Chay thuc te tren duong voi CSI Camera + Gui MQTT Cloud + Chup Snapshot
```bash
python3 main.py \
  --source csi \
  --sensor-id 0 \
  --roi-config configs/roi_traffic_nano.json \
  --congested-speed-kmh 5.0 \
  --congested-density 40.0
```

### Vi du 2: Chay test voi file video MP4 (offline, khong can MQTT va khong chup anh)
```bash
python3 main.py \
  --source /workspace/data/highway_test.mp4 \
  --no-mqtt \
  --no-snapshot
```

### Vi du 3: Chay voi camera IP RTSP o che do Headless (tiet kiem tai toi da tren Jetson)
```bash
python3 main.py \
  --source "rtsp://admin:password123@192.168.1.100:554/stream1" \
  --no-display
```

### Vi du 4: Tinh chinh van toc cho doan duong do thi dong duc xe may
```bash
python3 main.py \
  --source csi \
  --vehicle-classes "motorcycle,car,bus" \
  --slow-speed-kmh 20.0 \
  --congested-speed-kmh 8.0 \
  --speed-smoothing-alpha 0.35
```

---

## 5. CAU HINH BIEN MOI TRUONG (.env)

Tep `.env` o thu muc goc duoc tu dong nap khi container khoi chay:

```ini
# Backend API luu tru snapshot
BACKEND_URL=http://192.168.1.26:3000
EDGE_TOKEN=dev-edge-token

# Dinh danh thiet bi
EDGE_ID=edge-01
CAMERA_ID=camera-01
SEGMENT_ID=segment-001
SENSOR_ID=0

# HiveMQ Cloud MQTT Broker
MQTT_HOST=829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud
MQTT_PORT=8883
MQTT_USER=admin
MQTT_PASS=12345678

# Nguong Snapshot
CONGESTION_CONFIRM_SECONDS=15.0
SNAPSHOT_COOLDOWN_SECONDS=60.0
JPEG_QUALITY=75
OUTBOX_DIR=/app/outbox
```
