# jetson_snapshot v2 — chi module Jetson, khong co Backend/Frontend

## Bon tinh huong da trien khai

| Nguon nhan dien | Kich hoat | Nguon anh |
|---|---|---|
| Video demo | Admin gui `capture_test_snapshot` | Mo CSI de chup mot JPEG |
| Video demo | `CONGESTED` lien tuc >= 15 giay | Mo CSI de chup mot JPEG |
| Camera CSI | Admin gui `capture_test_snapshot` | Copy frame moi tu pipeline DeepStream dang chay |
| Camera CSI | `CONGESTED` lien tuc >= 15 giay | Copy frame tu cung pipeline DeepStream |

Tat ca upload toi `POST /api/v1/snapshots`, field `image`, Bearer `EDGE_TOKEN`.
Khong gui anh qua MQTT, khong dung WebRTC, khong sua model/van toc/Backend/Frontend.
Khong phat heartbeat gia thay cho DeepStream. Callback ket qua co `command_id`,
action, status (`queued`, `completed`, `failed`), timestamp, va URL khi hoan thanh.

**Khong phai cu copy thu muc la main cu tu co ket noi frame.** Neu main cua ban
chua goi module snapshot, can them cac diem noi trong muc 3. Che do CSI khong
co chuong trinh thu hai tu doc duoc frame trong bo nho cua main.

## 1. Cai module

Giai nen de co duong dan (thu muc `jetson_snapshot` nam canh main):

`/workspace/1908/02_deepstream_edge/jetson_snapshot/`

Giu ban cu de doi chieu; khong chep de Backend/Frontend hoac `mqtt_publisher.py`.
Chi bat mot bo xu ly snapshot. Khong chay dong thoi module snapshot cu va v2.

Trong Docker dang dung de chay DeepStream:

```bash
cd /workspace/1908/02_deepstream_edge/jetson_snapshot
cp .env.example .env
nano .env
python3 -m pip install -r requirements.txt
python3 -c 'import cv2,numpy,requests,paho.mqtt.client; print("dependencies OK")'
```

OpenCV/numpy dung ban san co trong JetPack/DeepStream. Khong cai de
`opencv-python` bang pip. `cv2.getBuildInformation()` bao GStreamer NO van khong
ngan module nay chup: phan mo CSI goi truc tiep `gst-launch-1.0`; OpenCV chi ma
hoa JPEG, chuyen mau, ghi nhan anh demo. Lenh GStreamer tren Jetson phai chay duoc.

Hai bien bat buoc:

```env
BACKEND_URL=http://IP-MAY-BACKEND:3000
EDGE_TOKEN=token-giong-backend
```

Khong dung `localhost` neu Backend o PC/VPS khac. Dung HTTPS hoac duong truyen
VPN/LAN tin cay; token di qua HTTP thuan khong duoc ma hoa. Cac pin dependency
de tuong thich Python 3.6 la phien ban cu, khong phai khang dinh an toan production.

## 2. Nhan dien video demo — chay agent doc lap duoc

Trong `jetson_snapshot/.env`:

```env
ANALYTICS_SOURCE=video
MQTT_URL=mqtts://YOUR_CLUSTER.s1.eu.hivemq.cloud:8883
MQTT_USERNAME=YOUR_USERNAME
MQTT_PASSWORD=YOUR_PASSWORD
MQTT_SNAPSHOT_CLIENT_ID=edge-01-snapshot-v2
MQTT_COMMAND_TOPIC=traffic/edge-01/command
MQTT_COMMAND_RESULT_TOPIC=traffic/edge-01/command-result
MQTT_TELEMETRY_TOPIC=traffic/edge-01/telemetry
CSI_SENSOR_ID=0
```

Agent nhan manual command va theo doi telemetry tren HiveMQ. Telemetry phai co
`timestamp` ISO-8601 kem mui gio, `traffic_status`, `edge_id` dung. Module dung
dong ho monotonic de xac nhan 15 giay thuc, khong tinh theo PTS cua video.
Khong dung `#` cho ba topic nay. Client ID agent phai KHAC client ID main de
hai ket noi khong da nhau khoi broker. Agent khong sua cau hinh MQTT cua main.

Chay trong terminal moi tu host, thay `worker` bang dung ten container:

```bash
docker exec -it worker bash
cd /workspace/1908/02_deepstream_edge/jetson_snapshot
python3 csi_capture_agent.py --env .env
```

**Main doc video chi gui telemetry; khong xu ly action chup lan thu hai.** Neu
main cu cung subscribe command, bo qua rieng `capture_test_snapshot` trong
dispatcher cu, khong phat `failed`/`completed` cho action nay. Khong chi truyen
`--no-snapshot` neu handler cu van bao "Snapshot disabled"; no co the tranh
trang thai command voi agent. Cac lenh dieu khien khac giu nguyen.

Agent mo `nvarguscamerasrc sensor-id=0 num-buffers=1` trong worker chi khi can;
file video va camera CSI la hai nguon khac nhau. Khong tu restart Docker,
DeepStream hay `nvargus-daemon`. Neu CSI ban, yeu cau chup loi, khong dung main.

### Y nghia anh demo

Khi video demo bao ket nhung anh lay tu CSI, hai nguon KHONG trung nhau.
Tren JPEG luon co nhan `CSI LIVE PHOTO / ANALYSIS: DEMO VIDEO` va
`NOT congestion evidence for the demo video`. Metadata gui kem gom:

```json
{
  "analysis_source": "VIDEO_DEMO",
  "snapshot_source": "CSI_DIRECT",
  "source_mismatch": "true"
}
```

Cac so xe/toc do/trang thai trong form la so lieu cua VIDEO de giu API hien co.
Khong coi chung la ket qua phan tich camera trong anh. Backend cu co the bo
qua metadata moi, va modal co the van hien so lieu video; nhan in tren JPEG
giup phan biet. Chua sua Frontend de doi cach trinh bay theo yeu cau chi viet module.

## 3. Nhan dien CSI — tich hop vao main, khong chay agent doc lap

`ANALYTICS_SOURCE=csi` khong mo CSI lan thu hai. Neu chay CLI o che do nay,
agent se tu choi va huong dan tich hop, khong tranh camera voi DeepStream.

### A. Neu main da dung SnapshotCoordinator cua goi truoc

Day la truong hop `main_roi_traffic_snapshot_fixed.py` da co
`route_command`, `snapshot_context_by_source` va `snapshot_osd_src_probe`.
Chi can thay import:

```python
from jetson_snapshot.snapshot_service import SnapshotCoordinator
```

Them nguon phan tich khi khoi tao (bien `kind` cua main hien co la `video`/`csi`):

```python
snapshot_service = SnapshotCoordinator(
    api_url=backend_url,
    edge_token=edge_token,
    analysis_source=kind,
    # GIU cac tham so edge_id, camera_id, queue_size, callback... hien co
)
```

Doi loi goi status-only thanh full metrics de VIDEO co so lieu khi chup CSI:

```python
snapshot_service.update_telemetry(metrics)
```

Giu `handle_mqtt_command(payload)`, `should_map_frame(status)`,
`submit_frame(frame_bgr, metrics)`, `start()` va `stop()` trong main hien co.
O mode video, `should_map_frame` tra False, worker tu chup CSI; o mode CSI,
frame hien tai duoc copy nhu truoc. **Khong cai them probe o muc B** neu da
co `snapshot_osd_src_probe` nay, va khong chay them agent.

### B. Neu main_roi_traffic_fixed.py chua dung SnapshotCoordinator

Them cac diem noi sau vao main, thay phan snapshot cu. Day la snippet tich hop,
khong phai mot main DeepStream doc lap; ten bien can khop voi main cua ban.

1. Import o dau file:

```python
from jetson_snapshot.config import load_env_file
from jetson_snapshot.runtime import create_from_env
from jetson_snapshot.deepstream_integration import attach_snapshot_probe
```

2. Sau khi co `mqtt_publisher`, truoc khi bat pipeline:

```python
# Co the dung duong dan tuyet doi de tranh phu thuoc thu muc chay lenh.
load_env_file('/workspace/1908/02_deepstream_edge/jetson_snapshot/.env')

def publish_snapshot_result(result):
    mqtt_publisher.publish_command_result(
        result['command_id'], result['action'],
        result['status'], result['message']
    )

# Dung source_type/kind tu nguon da resolve, khong dat video khi dang dung CSI.
snapshot_service = create_from_env(
    result_callback=publish_snapshot_result,
    analysis_source=kind  # 'csi' hoac 'video'
)
snapshot_service.start()
```

Callback tren tuong thich ham 4 tham so cua `mqtt_publisher.py` cu. URL anh
duoc Backend phat qua `snapshot:ready` sau HTTP upload, nen callback MQTT nay
khong bat buoc mang URL. Khong thay ket noi MQTT hien co.

3. Trong callback/dispatcher nhan command, xu ly rieng snapshot va RETURN:

```python
def route_command(payload):
    if isinstance(payload, dict) and payload.get('action') == 'capture_test_snapshot':
        snapshot_service.handle_mqtt_command(payload)
        return  # Khong de handler cu bao completed truoc khi co anh!
    cmd_handler.handle(payload)  # Giu cac action khac cua ban

mqtt_publisher._command_callback = route_command
```

Neu main nhan raw Paho message, kiem tra `message.retain` hoac truyen
`retained=message.retain` khi goi `handle_mqtt_command`. Backend phai publish
command voi `retain=False`. Role Admin do Backend kiem tra, Jetson khong nhan
`role` tu frontend de phan quyen.

4. Khi tracker da tinh duoc `metrics`, luu context theo source:

```python
# Tao dict mot lan ben ngoai tracker_probe:
snapshot_context_by_source = {}

# TRONG tracker_probe, sau khi tinh metrics:
snapshot_context_by_source[int(frame_meta.source_id)] = dict(metrics)
snapshot_service.update_telemetry(metrics)
```

5. Sau khi xay `pipeline, ..., osd` va truoc `PLAYING`:

```python
snapshot_pad = None
snapshot_probe_id = None
if snapshot_service.mode == 'csi':
    snapshot_pad, snapshot_probe_id = attach_snapshot_probe(
        osd, snapshot_service,
        get_metrics=lambda frame_meta: snapshot_context_by_source.get(int(frame_meta.source_id)),
        source_id=0
    )
```

Helper gan vao `nvdsosd src`, lay dung `frame_meta.batch_id` va chi copy RGBA
khi can. Worker moi chuyen BGR, ma hoa JPEG va upload. Khong luu con tro
GstBuffer/NvBufSurface vao queue sau khi probe tra ve.

Pipeline can nhanh **RGBA/OSD** ngay ca khi tat display, vi du doan sau tracker:
`nvvideoconvert → caps RGBA/NVMM → nvdsosd → fakesink`.
Neu `--no-display` trong builder cu loai han OSD, phai giu nhanh off-screen nay
hoac dung builder da sua trong goi truoc. Helper khong tu thay pipeline/model.

6. Trong `finally`, sau khi pipeline ve NULL:

```python
if snapshot_pad is not None:
    snapshot_pad.remove_probe(snapshot_probe_id)
snapshot_service.stop()  # Drain jobs; worker uses timeouts for capture/network.
```

Tom lai o che do tich hop: chay main nhu binh thuong; khong can terminal thu
hai chay `csi_capture_agent.py`. Co worker rieng, nhung cung process de lay frame.

## 4. Queue, cooldown va mat mang

- Auto: CONGESTED lien tuc 15 giay; 60 giay giua anh khi cung dot ket.
- FREE/SLOW/UNKNOWN reset xac nhan; dot ket moi can xac nhan lai 15 giay.
- Thieu telemetry >5 giay: khong phat sinh auto snapshot; khi co lai tinh lai.
- Manual khong bi cooldown ket xe chan; queue co gioi han, thieu frame se loi.
- Mot worker ma hoa/upload. Khong tao thread moi cho tung frame/anh.
- Luu JPEG atomic + metadata trong `ledger.sqlite3` truoc upload.
- Upload loi: giu JPEG, retry cung snapshot/event ID, khong chup lai de retry.
- Chi HTTP 2xx + JSON success + snapshot URL dung contract moi duoc xoa JPEG.
- Day 500 anh hoac budget 2GB: tu choi anh moi; KHONG xoa anh chua gui.
- Chi mot service duoc giu cung outbox (file lock). Dung chay hai service voi
  hai outbox khac nhau cho cung camera; module khong the khoa camera cua moi app khac.
- Dedupe ca trong RAM va qua restart, giu toi da 2000 receipt da hoan thanh.
  Commands co timestamp qua 60 giay bi tu choi; lenh khong timestamp chi giu
  tuong thich, dedupe cua chung khong duoc bao dam vo han sau khi receipt bi don.
- Anh da gui tu duoc xoa khoi outbox; Backend giu ban chinh. Khong xoa outbox
  thu cong khi con anh chua gui. `.part` chua hoan tat co the duoc don khi recovery.
- Bind-mount outbox ra host de viec recreate container khong lam mat du lieu.
- CSI mo that bai/encoder loi duoc bao qua command-result; khong restart main.

Frontend cu timeout sau 20 giay co the khong tu hien thi anh upload tre sau
khi mang phuc hoi. Anh van o Backend (`GET /api/v1/snapshots`); can UI ho tro
refresh/lich su neu muon xem anh tre tu dong. Khong thay UI trong ban nay.

## 5. Kiem thu

```bash
cd /workspace/1908/02_deepstream_edge/jetson_snapshot
python3 -m unittest discover -s tests -v
python3 -m compileall -q .
```

Smoke test HTTP voi source Backend da co (chay tren PC co Node va dependencies):

```bash
python3 tests/check_backend_contract.py /path/to/backend/src/app.js
```

Script dung Backend tam chi bind 127.0.0.1, dung token test va thu muc tam; khong
ket noi HiveMQ that. Kiem tra JPEG, auth, luu anh va viec Backend goi emit event.
Khong kiem tra browser hay truyen WebSocket thuc qua mang trong script nay.

Xem `TEST_RESULTS.md` de phan biet test logic/HTTP va nhung phan can Jetson that.

## Tham chieu ky thuat

- DeepStream 6.0.1 `get_nvds_buf_surface` can RGBA va batch_id cua frame:
  https://archive.docs.nvidia.com/metropolis/deepstream/6.0.1/python-api/PYTHON_API/Methods/methodsdoc.html#get-nvds-buf-surface
- Paho API (goi dung pin 1.6.1/callback v1 cho JetPack 4.x):
  https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html
