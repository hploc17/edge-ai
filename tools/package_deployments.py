#!/usr/bin/env python3
"""Packaging utility to build clean deployment archives for Jetson Edge and WebGIS.

Removes heavy/unnecessary files:
- node_modules (460+ MB)
- test videos in Video/ (164+ MB)
- snapshot image dumps in webgis/backend/data/snapshots/ (168+ MB)
- __pycache__, .pytest_cache, logs, test files, thesis docx
"""

import os
import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

# Output directory for zip packages
OUTPUT_DIR = ROOT_DIR

def create_gitkeep(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    gitkeep = path / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("# Placeholder\n", encoding="utf-8")
    return gitkeep

def should_skip_file(file_path: Path) -> bool:
    name = file_path.name
    # Skip python cache / compiled
    if name.endswith(('.pyc', '.pyo', '.pyd')):
        return True
    if '__pycache__' in file_path.parts:
        return True
    if '.pytest_cache' in file_path.parts:
        return True
    # Skip heavy video files
    if name.endswith(('.mp4', '.avi', '.mkv', '.h264', '.filepart')):
        return True
    # Skip temporary files
    if name in ('cookies.txt', 'Thumbs.db', '.DS_Store'):
        return True
    return False

def add_file_to_zip(zf: zipfile.ZipFile, src_path: Path, arc_name: str):
    if not src_path.exists():
        return
    if should_skip_file(src_path):
        return
    zf.write(str(src_path), arc_name)

def add_dir_to_zip(zf: zipfile.ZipFile, src_dir: Path, arc_prefix: str, exclude_filter=None):
    if not src_dir.exists():
        return
    for root, dirs, files in os.walk(src_dir):
        # Exclude unwanted directories
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.pytest_cache', 'node_modules', '.vite', '.git')]
        rel_root = Path(root).relative_to(src_dir)
        for f in sorted(files):
            full_path = Path(root) / f
            if should_skip_file(full_path):
                continue
            if exclude_filter and exclude_filter(full_path):
                continue
            arc_name = (Path(arc_prefix) / rel_root / f).as_posix()
            zf.write(str(full_path), arc_name)

def build_jetson_package(zip_path: Path):
    print(f"\n[1/3] Đang nén gói triển khai Jetson Edge: {zip_path.name}...")
    
    # Ensure jetson requirements.txt exists
    jetson_req = ROOT_DIR / "requirements.txt"
    if not jetson_req.exists():
        jetson_req_content = (
            "# Thu vien Python can thiet tren NVIDIA Jetson Nano / DeepStream 6.0.1\n"
            "# Luu y: pyds va gi (PyGObject) da co san trong JetPack / DeepStream Container\n"
            "paho-mqtt==1.6.1\n"
            "requests>=2.25.0\n"
            "psutil>=5.8.0\n"
            "python-dotenv>=0.19.0\n"
            "websocket-client>=1.3.0\n"
            "numpy>=1.19.0\n"
            "opencv-python>=4.5.0\n"
        )
        jetson_req.write_text(jetson_req_content, encoding="utf-8")

    # Create README_JETSON.md
    readme_jetson = ROOT_DIR / "README_JETSON.md"
    readme_content = (
        "# 🚀 HƯỚNG DẪN TRIỂN KHAI JETSON EDGE AI TRAFFIC MONITORING\n\n"
        "Gói triển khai gọn nhẹ tối ưu dành riêng cho thiết bị biên NVIDIA Jetson Nano (JetPack 4.x / DeepStream 6.x).\n\n"
        "## 1. Cài đặt thư viện phụ thuộc\n"
        "```bash\n"
        "sudo apt-get update && sudo apt-get install -y python3-pip libgstreamer1.0-dev\n"
        "pip3 install -r requirements.txt\n"
        "```\n\n"
        "## 2. Cấu hình hệ thống\n"
        "Chỉnh sửa file `.env` phù hợp với mạng thực địa:\n"
        "- `BACKEND_URL`: Địa chỉ máy chủ WebGIS (ví dụ: `http://192.168.1.100:8000`)\n"
        "- `MQTT_HOST`, `MQTT_USER`, `MQTT_PASS`: Thông tin kết nối MQTT Broker\n"
        "- `ANALYTICS_SOURCE`: `csi` (Camera CSI thực tế) hoặc `file` (video thử nghiệm trong Video/)\n"
        "- `LIVE_STREAM_ENABLED`: 1 (bật truyền luồng RTSP về WebGIS)\n\n"
        "## 3. Khởi chạy\n"
        "```bash\n"
        "chmod +x restart_edge.sh\n"
        "python3 main.py\n"
        "# Hoặc khởi động qua script:\n"
        "./restart_edge.sh\n"
        "```\n"
    )
    readme_jetson.write_text(readme_content, encoding="utf-8")

    # Ensure empty placeholders
    create_gitkeep(ROOT_DIR / "Video")
    create_gitkeep(ROOT_DIR / "outbox")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # Jetson Root Files
        for f in ['main.py', 'restart_edge.sh', '.env', '.env.example', 'requirements.txt', 'README_JETSON.md']:
            add_file_to_zip(zf, ROOT_DIR / f, f)
        
        # Video & Outbox empty placeholders
        add_file_to_zip(zf, ROOT_DIR / "Video" / ".gitkeep", "Video/.gitkeep")
        add_file_to_zip(zf, ROOT_DIR / "outbox" / ".gitkeep", "outbox/.gitkeep")

        # Modules
        for mod in ['core', 'spatial', 'analytics', 'communication', 'config', 'configs', 'snap', 'snapshot', 'tools']:
            add_dir_to_zip(zf, ROOT_DIR / mod, mod)

    size_kb = zip_path.stat().st_size / 1024
    print(f"  -> Hoàn thành gói Jetson: {zip_path.name} ({size_kb:.1f} KB)")


def build_webgis_package(zip_path: Path):
    print(f"\n[2/3] Đang nén gói triển khai WebGIS: {zip_path.name}...")

    # Ensure empty placeholders in backend
    create_gitkeep(ROOT_DIR / "webgis" / "backend" / "data" / "snapshots")
    create_gitkeep(ROOT_DIR / "webgis" / "backend" / "data" / "logs")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # WebGIS Scripts & Docs at root level
        for f in [
            'start_webgis.bat',
            'start_webgis.sh',
            'start_webgis_prod.bat',
            'start_webgis_dev.bat',
            'open_firewall_mediamtx.bat',
            'simulate_traffic.bat',
            'README_WEBGIS.md'
        ]:
            add_file_to_zip(zf, ROOT_DIR / f, f)

        # MediaMTX Streaming Server
        add_dir_to_zip(zf, ROOT_DIR / "deploy" / "mediamtx", "deploy/mediamtx")

        # WebGIS Tools (Simulators)
        add_dir_to_zip(zf, ROOT_DIR / "webgis" / "tools", "webgis/tools")

        # WebGIS Backend (Exclude snapshot jpg/png/jpeg files, only keep placeholder and json data)
        def exclude_snapshot_images(p: Path):
            if "data" in p.parts and "snapshots" in p.parts:
                return p.suffix.lower() in ('.jpg', '.jpeg', '.png')
            return False

        add_dir_to_zip(zf, ROOT_DIR / "webgis" / "backend", "webgis/backend", exclude_filter=exclude_snapshot_images)

        # WebGIS Frontend (Include source code AND built dist, EXCLUDE node_modules, .vite, .git)
        add_dir_to_zip(zf, ROOT_DIR / "webgis" / "frontend", "webgis/frontend")

        # WebGIS Auth-Service (Include source, prisma, dev.db, EXCLUDE node_modules)
        add_dir_to_zip(zf, ROOT_DIR / "webgis" / "auth-service", "webgis/auth-service")

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  -> Hoàn thành gói WebGIS: {zip_path.name} ({size_mb:.2f} MB)")


def build_full_clean_package(zip_path: Path):
    print(f"\n[3/3] Đang nén gói toàn diện làm sạch (Full Clean System): {zip_path.name}...")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # All root scripts & configs
        for f in [
            'main.py',
            'restart_edge.sh',
            '.env',
            '.env.example',
            '.gitignore',
            'requirements.txt',
            'README.md',
            'README_JETSON.md',
            'README_WEBGIS.md',
            'start_webgis.bat',
            'start_webgis.sh',
            'start_webgis_prod.bat',
            'start_webgis_dev.bat',
            'open_firewall_mediamtx.bat',
            'simulate_traffic.bat'
        ]:
            add_file_to_zip(zf, ROOT_DIR / f, f)

        # Video & Outbox empty placeholders
        add_file_to_zip(zf, ROOT_DIR / "Video" / ".gitkeep", "Video/.gitkeep")
        add_file_to_zip(zf, ROOT_DIR / "outbox" / ".gitkeep", "outbox/.gitkeep")

        # Edge modules
        for mod in ['core', 'spatial', 'analytics', 'communication', 'config', 'configs', 'snap', 'snapshot', 'tools']:
            add_dir_to_zip(zf, ROOT_DIR / mod, mod)

        # MediaMTX
        add_dir_to_zip(zf, ROOT_DIR / "deploy" / "mediamtx", "deploy/mediamtx")

        # WebGIS Tools
        add_dir_to_zip(zf, ROOT_DIR / "webgis" / "tools", "webgis/tools")

        # WebGIS Backend
        def exclude_snapshot_images(p: Path):
            if "data" in p.parts and "snapshots" in p.parts:
                return p.suffix.lower() in ('.jpg', '.jpeg', '.png')
            return False

        add_dir_to_zip(zf, ROOT_DIR / "webgis" / "backend", "webgis/backend", exclude_filter=exclude_snapshot_images)

        # WebGIS Frontend & Auth
        add_dir_to_zip(zf, ROOT_DIR / "webgis" / "frontend", "webgis/frontend")
        add_dir_to_zip(zf, ROOT_DIR / "webgis" / "auth-service", "webgis/auth-service")

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  -> Hoàn thành gói Full Clean: {zip_path.name} ({size_mb:.2f} MB)")


if __name__ == '__main__':
    jetson_zip = OUTPUT_DIR / "deploy_jetson.zip"
    webgis_zip = OUTPUT_DIR / "deploy_webgis.zip"
    full_zip = OUTPUT_DIR / "deploy_full_clean.zip"

    build_jetson_package(jetson_zip)
    build_webgis_package(webgis_zip)
    build_full_clean_package(full_zip)

    print("\n==============================================================================")
    print("HOÀN THÀNH TẠO 3 GÓI TRIỂN KHAI SẠCH:")
    print(f"  1. Gói Jetson Edge:  {jetson_zip.name}  ({jetson_zip.stat().st_size / 1024:.1f} KB)")
    print(f"  2. Gói WebGIS:       {webgis_zip.name}  ({webgis_zip.stat().st_size / (1024*1024):.2f} MB)")
    print(f"  3. Gói Full Hệ thống:{full_zip.name}    ({full_zip.stat().st_size / (1024*1024):.2f} MB)")
    print("==============================================================================")
