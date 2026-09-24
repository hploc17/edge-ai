#!/bin/bash

# ==============================================================================
# Script khoi chay Container DeepStream tren Jetson Nano (Khoi dong tuc thi)
# ==============================================================================

# 1. Cho phep cac tien trinh tu Docker truy cap vao X-server de hien thi GUI (neu co)
export DISPLAY="${DISPLAY:-}"
if [ -n "${DISPLAY}" ]; then
    echo "[*] Dang cap quyen truy cap X-server cho Docker (DISPLAY=${DISPLAY})..."
    xhost +local:root >/dev/null 2>&1 || xhost + >/dev/null 2>&1 || true
else
    echo "[*] Che do Headless (khong co bien DISPLAY)..."
fi

# 2. Xac dinh duong dan thu muc du an
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "[*] Duong dan thu muc du an: ${PROJECT_DIR}"

# 3. Kiem tra: Uu tien image san co tren may
if [ -z "${IMAGE_NAME}" ]; then
    if docker image inspect "jetson-traffic-ai-deepstream:latest" >/dev/null 2>&1; then
        IMAGE_NAME="jetson-traffic-ai-deepstream:latest"
    elif docker image inspect "jetson-deepstream-edge:latest" >/dev/null 2>&1; then
        IMAGE_NAME="jetson-deepstream-edge:latest"
    elif docker image inspect "traffic-edge-nano:latest" >/dev/null 2>&1; then
        IMAGE_NAME="traffic-edge-nano:latest"
    else
        IMAGE_NAME="traffic-edge-nano:latest"
    fi
fi

if ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
    echo "[*] Image '${IMAGE_NAME}' chua ton tai. Dang build lan dau tu Dockerfile..."
    docker build -t ${IMAGE_NAME} -f "$PROJECT_DIR/Dockerfile" "$PROJECT_DIR"
else
    echo "[✓] Image '${IMAGE_NAME}' da ton tai. Khoi dong container ngay lap tuc..."
fi

# 4. Xoa container cu neu dang chay
if [ "$(docker ps -aq -f name=${CONTAINER_NAME})" ]; then
    echo "[*] Dang don dep container cu: ${CONTAINER_NAME}..."
    docker stop ${CONTAINER_NAME} >/dev/null 2>&1 || true
    docker rm ${CONTAINER_NAME} >/dev/null 2>&1 || true
fi

XAUTH_MOUNT=""
if [ -f "${HOME}/.Xauthority" ]; then
    XAUTH_MOUNT="-v ${HOME}/.Xauthority:/root/.Xauthority:ro"
fi

VIDEO_MOUNT=""
if [ -d "$PROJECT_DIR/Video" ]; then
    VIDEO_MOUNT="-v $PROJECT_DIR/Video:/workspace/Video -v $PROJECT_DIR/Video:/app/Video"
elif [ -d "$PROJECT_DIR/../traffic_pipeline_demo/edge/Video" ]; then
    VIDEO_MOUNT="-v $(cd "$PROJECT_DIR/../traffic_pipeline_demo/edge/Video" && pwd):/workspace/Video"
fi

ENV_FILE_ARG=""
if [ -f "$PROJECT_DIR/.env" ]; then
    ENV_FILE_ARG="--env-file $PROJECT_DIR/.env"
fi

echo "[*] Dang khoi chay DeepStream Container..."
echo "--------------------------------------------------------"

# 5. Khoi chay Docker DeepStream Container
docker run -it \
    --runtime nvidia \
    --name ${CONTAINER_NAME} \
    --network host \
    --ipc=host \
    -e DISPLAY=${DISPLAY} \
    -e QT_X11_NO_MITSHM=1 \
    -e PYTHONIOENCODING=utf-8 \
    -e LANG=C.UTF-8 \
    -e LC_ALL=C.UTF-8 \
    -e PYTHONUNBUFFERED=1 \
    ${XAUTH_MOUNT} \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v /tmp/argus_socket:/tmp/argus_socket \
    -v /dev:/dev \
    -v ${PROJECT_DIR}:/workspace \
    -v ${PROJECT_DIR}:/app \
    ${VIDEO_MOUNT} \
    -w /workspace \
    ${ENV_FILE_ARG} \
    --privileged \
    ${IMAGE_NAME} \
    bash
