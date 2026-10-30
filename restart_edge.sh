#!/usr/bin/env bash
# ==============================================================================
# Script: restart_edge.sh - Khởi động lại dịch vụ hệ thống Edge AI trên Jetson
# Hỗ trợ cả 3 chế độ: Systemd Service, Docker Container, hoặc Python Native
# ==============================================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}==============================================================================${NC}"
echo -e "${BLUE}       JETSON EDGE AI - KHỞI ĐỘNG LẠI DỊCH VỤ HỆ THỐNG (SERVICE RESTART)      ${NC}"
echo -e "${BLUE}==============================================================================${NC}"

# 0. Tự động giải phóng và khởi động lại driver camera CSI (nvargus-daemon)
echo -e "${YELLOW}[0/3] Khởi động lại camera daemon nvargus-daemon (chống kẹt camera)...${NC}"
sudo systemctl restart nvargus-daemon 2>/dev/null
sleep 1

# Tên dịch vụ systemd mặc định (hoặc truyền qua đối số: ./restart_edge.sh ten_service)
SERVICE_NAME="${1:-}"

# 1. Tự động tìm dịch vụ systemd nếu chưa truyền tham số
if [ -z "$SERVICE_NAME" ]; then
    DETECTED_SERVICE=$(systemctl list-unit-files --type=service 2>/dev/null | grep -E "edge|jetson|traffic" | awk '{print $1}' | head -n 1)
    if [ -n "$DETECTED_SERVICE" ]; then
        SERVICE_NAME="$DETECTED_SERVICE"
    fi
fi

# 2. Xử lý khởi động lại theo Systemd Service (nếu có service trên máy)
if [ -n "$SERVICE_NAME" ] && systemctl list-unit-files "$SERVICE_NAME" >/dev/null 2>&1; then
    echo -e "${YELLOW}[1/2] Đang khởi động lại dịch vụ Systemd: ${SERVICE_NAME} ...${NC}"
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}✓ DỊCH VỤ SYSTEMD ĐÃ RESTART THÀNH CÔNG! Trạng thái: ACTIVE (RUNNING)${NC}"
        sudo systemctl status "$SERVICE_NAME" --no-pager -n 5
        exit 0
    else
        echo -e "${RED}[LỖI] Dịch vụ ${SERVICE_NAME} không thể khởi động!${NC}"
        sudo journalctl -u "$SERVICE_NAME" -n 20 --no-pager
        exit 1
    fi
fi

# 3. Kiểm tra Docker Container
CONTAINER_NAME=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E "edge|traffic|deepstream|jetson" | head -n 1)
if [ -n "$CONTAINER_NAME" ]; then
    echo -e "${YELLOW}[1/2] Đang khởi động lại Docker container: ${CONTAINER_NAME} ...${NC}"
    docker restart "$CONTAINER_NAME" >/dev/null
    sleep 2
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "${GREEN}✓ DỊCH VỤ DOCKER ĐÃ RESTART THÀNH CÔNG! Container: ${CONTAINER_NAME}${NC}"
        exit 0
    fi
fi

# 4. Phương án mặc định: Chạy Native Python trực tiếp
echo -e "${YELLOW}[INFO] Đang khởi động lại tiến trình Python Agent nhận lệnh từ WebGIS...${NC}"

# Dọn dẹp tiến trình Python cũ nếu đang kẹt
pkill -f "communication/jetson_agent.py" 2>/dev/null
pkill -f "main.py" 2>/dev/null
sleep 1

# Khởi động Jetson Agent (tiến trình nhận lệnh MQTT, chụp preview, điều khiển từ xa)
echo -e "${YELLOW}Đang khởi chạy: python3 communication/jetson_agent.py ...${NC}"
nohup python3 communication/jetson_agent.py > jetson_agent.log 2>&1 &
AGENT_PID=$!
sleep 2

if ps -p $AGENT_PID > /dev/null; then
    echo -e "${GREEN}==============================================================================${NC}"
    echo -e "${GREEN}  ✓ JETSON AGENT ĐÃ HOẠT ĐỘNG! PID: ${AGENT_PID}${NC}"
    echo -e "${GREEN}  ✓ Đang lắng nghe lệnh điều khiển và phát Heartbeat lên WebGIS.${NC}"
    echo -e "${GREEN}  ✓ Log tiến trình: tail -f jetson_agent.log${NC}"
    echo -e "${GREEN}==============================================================================${NC}"
    exit 0
else
    echo -e "${RED}[LỖI] Jetson Agent không thể khởi chạy. Kiểm tra file jetson_agent.log bên dưới:${NC}"
    cat jetson_agent.log 2>/dev/null | tail -n 20
    exit 1
fi
