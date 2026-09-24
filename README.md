# Edge AI Traffic Monitoring & Analytics (Modular & Docker Edition)

He thong giam sat va phan tich giao thong bien tren nen tang **NVIDIA Jetson Nano** (JetPack 4.x / DeepStream 6.x / Python 3.6+) duoc thiet ke theo **Kien truc Module Hoa chuan muc**, san sang trien khai thuc dia bang Docker voi cac script dieu khien `.sh` va co che **tu khoi dong khi cap dien**.

---

## 🏛️ Cau Truc Module Chuan Muc

```text
edge_traffic_optimal/
├── RUN_GUIDE.md                    # [0] Huong dan chay he thong & toan bo arguments chi tiet
├── run.sh                          # [1] Script khoi chay Docker container nen (hoac -it)
├── run_ds.sh                       # [2] Script vao truc tiep interactive bash container
├── stop.sh                         # [3] Script dung va giai phong container
├── view_log.sh                     # [4] Script xem log thoi gian thuc cua container
├── edge-traffic-docker.service     # [5] File cau hinh Systemd de Jetson tu chay khi bat nguon
├── .env                            # [5] File bien moi truong cau hinh thuc te
├── .env.example                    # [6] Mau cau hinh moi truong
├── Dockerfile                      # [7] Container image dua tren DeepStream 6.0.1
├── requirements.txt                # [8] Thu vien Python tuong thich
│
├── core/                           # MODULE 1: PIPELINE & GStreamer
│   ├── gstreamer_builder.py        # Xay dung hardware pipeline GStreamer tren NVMM
│   └── deepstream_probe.py         # Trich xuat metadata AI va frame zero-copy
│
├── spatial/                        # MODULE 2: HINH HOC & KHONG GIAN
│   ├── geometry_utils.py           # Thuat toan diem tiep dat (bottom-center) & Ray Casting da giac
│   └── roi_manager.py              # Quan ly, nap va luu tru cau hinh ROI JSON
│
├── analytics/                      # MODULE 3: PHAN TICH GIAO THONG LOI
│   ├── presence_counter.py         # Dem luu luong theo vung hien dien (Hysteresis loc rung lac)
│   ├── speed_estimator.py          # Do toc do thuc te qua ma tran Homography 3x3 va Hoi quy tuyen tinh
│   └── traffic_classifier.py       # Phan loai trang thai (FREE/SLOW/CONGESTED) va Congestion Score
│
├── snapshot/                       # MODULE 4: CHUP ANH BANG CHUNG & NGOAI TUYEN
│   ├── trigger_guard.py            # Bo kich hoat kep (15s ket xe lien tuc + 60s cooldown)
│   ├── uploader.py                 # Ma hoa JPEG va gui HTTP multipart POST len Backend
│   └── offline_outbox.py           # Hang doi luu dia (Disk Queue) tu retry khi mat mang (Quota 2GB)
│
├── communication/                  # MODULE 5: TRUYEN THONG & DIEU KHIEN TU XA
│   ├── mqtt_client.py              # HiveMQ TLS: Telemetry dinh ky (1s) & Heartbeat (5s)
│   ├── command_router.py           # Nhan lenh WebGIS theo Strict Whitelist an toan
│   └── system_metrics.py           # Thu thap % CPU, % GPU, % RAM va Nhiet do SoC Jetson
│
├── config/                         # MODULE 6: CAU HINH TAP TRUNG
│   └── settings.py                 # Quan ly doc bien moi truong (.env) va tham so he thong
│
├── tools/                          # MODULE 7: CONG CU NGOAI VI & TEST
│   ├── roi_picker.py               # Cong cu truc quan ve da giac ROI bang chuot
│   └── simulate_edge.py            # Bo mo phong chay thu nghiem tren may tinh
│
├── configs/                        # Thu muc cau hinh mount ngoai host
│   ├── config_infer_yolo11_nano.txt # Cau hinh nvinfer YOLOv11 TensorRT
│   ├── config_tracker_optimized.yml # Cau hinh DeepStream NvTracker toi uu
│   ├── labels_custom.txt           # Nhan phan loai phuong tien
│   └── roi_traffic_nano.json       # Toa do ROI va kich thuoc duong thuc te
│
├── outbox/                         # Thu muc chua anh chup ngoai tuyen mount ngoai host
├── main.py                         # Diem dieu phoi trung tam (Orchestrator)
└── tests/                          # Bo Unit Tests doc lap (45/45 tests passed)
```

---

## 🚀 HUONG DAN VAN HANH BANG DOCKER & SCRIPT `.sh`

### 1. Cau hinh bien moi truong
Chinh sua file `.env` theo dia chi IP Backend va thong tin MQTT cua ban:
```bash
nano .env
```

### 2. Khoi chay he thong bang file `run.sh`
Chi can chay script:
```bash
chmod +x *.sh
./run.sh
```
*Script se tu dong:*
- Kiem tra va khoi dong driver camera `nvargus-daemon`.
- Tao thu muc luu anh ngoai tuyen `outbox/`.
- Chay container ngam voi day du co `--runtime nvidia`, truy cap camera CSI va mount thu muc `configs/` ngoai host.

### 3. Xem log thoi gian thuc
```bash
./view_log.sh
```

### 4. Dung he thong
```bash
./stop.sh
```

---

## 🔌 CAU HINH TU DONG CHAY KHI JETSON BAT NGUON

De khi cam nguon dien ngoai hien truong, Jetson Nano se **tu dong chay Docker container**:

```bash
# 1. Sao chep file service vao thu muc he thong
sudo cp edge-traffic-docker.service /etc/systemd/system/

# 2. Tai lai daemon va kich hoat tu khoi dong
sudo systemctl daemon-reload
sudo systemctl enable edge-traffic-docker.service

# 3. Khoi chay thu nghiem ngay lap tuc
sudo systemctl start edge-traffic-docker.service
```

*Co che:* Service nay dam bao mang Internet va driver camera CSI (`nvargus-daemon`) da san sang 100% truoc khi kich hoat Docker container, tranh hoan toan loi khong nhan dien duoc camera khi may vua khoi dong.

---

## 🧪 CHAY KIEM THU UNIT TEST
```bash
python -m pytest tests
```
*Ket qua:* **45 / 45 test cases PASSED** (Kiem tra toan bo cac module `spatial`, `analytics`, `snapshot`, `config`).
