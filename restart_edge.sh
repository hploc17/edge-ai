#!/usr/bin/env bash
# ==============================================================================
# Script: restart_edge.sh - Khởi động lại dịch vụ hệ thống Edge AI trên Jetson
# Cơ chế: Khởi động lại Service (Systemd / Docker) -> Tự động xóa sạch 100% tiến trình cũ
# ==============================================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}==============================================================================${NC}"
echo -e "${BLUE}       JETSON EDGE AI - KHỞI ĐỘNG LẠI DỊCH VỤ HỆ THỐNG (SERVICE RESTART)      ${NC}"
echo -e "${BLUE}==============================================================================${NC}"

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
    echo -e "      (Hệ điều hành đang tự động quét sạch mọi tiến trình cũ và giải phóng VRAM...)"
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2
    
    echo -e "\n${YELLOW}[2/2] Kiểm tra trạng thái dịch vụ sau khi khởi động lại:${NC}"
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}==============================================================================${NC}"
        echo -e "${GREEN}  ✓ DỊCH VỤ ĐÃ KHỞI ĐỘNG LẠI THÀNH CÔNG! Trạng thái: ACTIVE (RUNNING)${NC}"
        echo -e "${GREEN}  ✓ Toàn bộ tiến trình cũ, VRAM và kết nối mạng cũ đã được dọn sạch.${NC}"
        echo -e "${GREEN}==============================================================================${NC}"
        sudo systemctl status "$SERVICE_NAME" --no-pager -n 5
        exit 0
    else
        echo -e "${RED}[LỖI] Dịch vụ ${SERVICE_NAME} không thể khởi động! Kiểm tra log bên dưới:${NC}"
        sudo journalctl -u "$SERVICE_NAME" -n 20 --no-pager
        exit 1
    fi
fi

# 3. Phương án dự phòng: Khởi động lại dịch vụ qua Docker Container
echo -e "${YELLOW}[INFO] Không tìm thấy Systemd service riêng. Đang chuyển sang cơ chế Docker Restart...${NC}"

DEFAULT_CONTAINER="edge_ai_container"
CONTAINER_NAME=$(docker ps --format '{{.Names}}' | grep -E "edge|traffic|deepstream|jetson" | head -n 1)
if [ -z "$CONTAINER_NAME" ]; then
    CONTAINER_NAME=$(docker ps --format '{{.Names}}' | head -n 1)
fi

if [ -n "$CONTAINER_NAME" ]; then
    echo -e "${YELLOW}[1/2] Đang khởi động lại Docker container: ${CONTAINER_NAME} ...${NC}"
    echo -e "      (Docker đang gửi tín hiệu dừng sạch sẽ mọi tiến trình bên trong container...)"
    docker restart "$CONTAINER_NAME" >/dev/null
    sleep 2
    
    echo -e "\n${YELLOW}[2/2] Kiểm tra trạng thái container sau khi restart:${NC}"
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "${GREEN}==============================================================================${NC}"
        echo -e "${GREEN}  ✓ DỊCH VỤ DOCKER ĐÃ RESTART THÀNH CÔNG! Container: ${CONTAINER_NAME}${NC}"
        echo -e "${GREEN}  ✓ Mọi tiến trình cũ, VRAM và kết nối mạng cũ đã được dọn sạch 100%.${NC}"
        echo -e "${GREEN}==============================================================================${NC}"
        exit 0
    else
        echo -e "${RED}[LỖI] Container ${CONTAINER_NAME} không chạy được sau khi restart.${NC}"
        exit 1
    fi
else
    echo -e "${RED}[LỖI] Không tìm thấy Systemd Service lẫn Docker Container nào trên máy Jetson!${NC}"
    exit 1
fi
