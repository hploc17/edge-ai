#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER_NAME="traffic_edge_container"

echo "========================================================"
echo "  KHOI DONG HE THONG EDGE TRAFFIC AI (NVIDIA JETSON NANO)"
echo "========================================================"

# 1. Cho phep cac tien trinh tu Docker truy cap vao X-server (neu co)
export DISPLAY="${DISPLAY:-}"
if [ -n "${DISPLAY}" ]; then
    echo "[*] Dang cap quyen truy cap X-server cho Docker (DISPLAY=${DISPLAY})..."
    xhost +local:root >/dev/null 2>&1 || xhost + >/dev/null 2>&1 || true
else
    echo "[*] Che do Headless (khong co bien DISPLAY)..."
fi

# 2. Dam bao dich vu camera daemon dang chay
if systemctl is-active --quiet nvargus-daemon 2>/dev/null; then
    echo "[*] nvargus-daemon dang chay."
else
    echo "[*] Khoi dong lai nvargus-daemon..."
    sudo systemctl restart nvargus-daemon >/dev/null 2>&1 || true
fi

# 3. Tao thu muc outbox ngoai host neu chua co
mkdir -p "$DIR/outbox"

# 4. Kiem tra Docker Image: Uu tien image san co tren may
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
    echo "[*] Image '${IMAGE_NAME}' chua ton tai. Dang build tu Dockerfile..."
    docker build -t "${IMAGE_NAME}" -f "$DIR/Dockerfile" "$DIR"
else
    echo "[*] Su dung Docker image: ${IMAGE_NAME}"
fi

# 5. Don dep container cu neu dang chay
if [ "$(docker ps -aq -f name=^/${CONTAINER_NAME}$)" ]; then
    echo "[*] Dang don dep container cu: ${CONTAINER_NAME}..."
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

XAUTH_MOUNT=""
if [ -f "${HOME}/.Xauthority" ]; then
    XAUTH_MOUNT="-v ${HOME}/.Xauthority:/root/.Xauthority:ro"
fi

VIDEO_MOUNT=""
if [ -d "$DIR/Video" ]; then
    VIDEO_MOUNT="-v $DIR/Video:/workspace/Video -v $DIR/Video:/app/Video"
elif [ -d "$DIR/../traffic_pipeline_demo/edge/Video" ]; then
    VIDEO_MOUNT="-v $(cd "$DIR/../traffic_pipeline_demo/edge/Video" && pwd):/workspace/Video"
fi

ENV_FILE_ARG=""
if [ -f "$DIR/.env" ]; then
    ENV_FILE_ARG="--env-file $DIR/.env"
fi

# 6. Chay container
if [ "$1" == "-it" ] || [ "$1" == "bash" ] || [ "$1" == "--interactive" ]; then
    shift || true
    CMD="${*:-bash}"
    echo "[*] Khoi chay container o che do tuong tac (Interactive)..."
    echo "--------------------------------------------------------"
    docker run -it --rm \
      --name "$CONTAINER_NAME" \
      --runtime nvidia \
      --network host \
      --ipc=host \
      --privileged \
      -e DISPLAY="${DISPLAY}" \
      -e QT_X11_NO_MITSHM=1 \
      -e PYTHONIOENCODING=utf-8 \
      -e LANG=C.UTF-8 \
      -e LC_ALL=C.UTF-8 \
      -e PYTHONUNBUFFERED=1 \
      ${XAUTH_MOUNT} \
      -v /tmp/.X11-unix:/tmp/.X11-unix \
      -v /tmp/argus_socket:/tmp/argus_socket \
      -v /dev:/dev \
      -v "$DIR":/app \
      -v "$DIR":/workspace \
      ${VIDEO_MOUNT} \
      -w /app \
      ${ENV_FILE_ARG} \
      "$IMAGE_NAME" \
      $CMD
else
    echo "[*] Dang chay Docker Container ngam: $CONTAINER_NAME..."
    docker run -d \
      --name "$CONTAINER_NAME" \
      --runtime nvidia \
      --restart unless-stopped \
      --network host \
      --ipc=host \
      --privileged \
      -e DISPLAY="${DISPLAY}" \
      -e QT_X11_NO_MITSHM=1 \
      -e PYTHONIOENCODING=utf-8 \
      -e LANG=C.UTF-8 \
      -e LC_ALL=C.UTF-8 \
      -e PYTHONUNBUFFERED=1 \
      ${XAUTH_MOUNT} \
      -v /tmp/.X11-unix:/tmp/.X11-unix \
      -v /tmp/argus_socket:/tmp/argus_socket \
      -v /dev:/dev \
      -v "$DIR":/app \
      -v "$DIR":/workspace \
      ${VIDEO_MOUNT} \
      -w /app \
      ${ENV_FILE_ARG} \
      "$IMAGE_NAME" \
      python3 /app/main.py --source csi --sensor-id 0

    echo "[OK] Container da khoi chay ngam thanh cong!"
    echo "-> Xem log truc tiep: ./view_log.sh"
    echo "-> Dung container:    ./stop.sh"
    echo "-> Chay tuong tac:    ./run.sh -it"
fi
