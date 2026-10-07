#!/bin/bash
CONTAINER_NAME="traffic_edge_container"
echo "[INFO] Dang dung container: $CONTAINER_NAME..."
docker stop "$CONTAINER_NAME" >/dev/null 2>&1 && docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
echo "[SUCCESS] Da dung va giai phong container thanh cong!"
