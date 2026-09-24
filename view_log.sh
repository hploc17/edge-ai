#!/bin/bash
CONTAINER_NAME="traffic_edge_container"
echo "[INFO] Dang theo doi log cua $CONTAINER_NAME (Ctrl+C de thoat)..."
docker logs -f --tail 100 "$CONTAINER_NAME"
