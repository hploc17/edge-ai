#!/usr/bin/env python3
"""Standalone Tool to Fetch Diagnostics & Logs from Jetson over MQTT.

Usage:
    # 1. Fetch last 100 lines of logs from edge-01:
    python tools/fetch_jetson_logs.py --edge-id edge-01

    # 2. Fetch last 200 lines and save to custom file:
    python tools/fetch_jetson_logs.py --edge-id edge-01 --lines 200 --output my_log.txt

The log file is automatically saved to:
    webgis/backend/data/logs/jetson_{edge_id}_latest.log
where AI or engineers on PC can immediately read and analyze it.
"""

from __future__ import print_function

import argparse
import json
import os
import ssl
import sys
import time
import uuid
import paho.mqtt.client as mqtt_lib

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Automatically read master .env
env_path = os.path.join(ROOT_DIR, ".env")
if os.path.isfile(env_path):
    try:
        with open(env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))
    except Exception:
        pass

DEFAULT_HOST = os.getenv("MQTT_HOST", "829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud")
DEFAULT_PORT = int(os.getenv("MQTT_PORT", "8883"))
DEFAULT_USER = os.getenv("MQTT_USER", "admin")
DEFAULT_PASS = os.getenv("MQTT_PASS", "12345678")


def fetch_logs_from_jetson(edge_id="edge-01", num_lines=100, timeout_s=10.0, output_file=None):
    command_id = "maint-%s" % uuid.uuid4().hex[:8]
    topic_command = "traffic/%s/command" % edge_id
    topic_result = "traffic/%s/command-result" % edge_id

    result_container = {"data": None, "received": False}

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("[PC-MAINT] Connected to MQTT broker. Subscribing to %s ..." % topic_result)
            client.subscribe(topic_result, qos=1)
            # Send command
            cmd_payload = {
                "action": "fetch_logs",
                "command_id": command_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
                "params": {"lines": num_lines}
            }
            client.publish(topic_command, json.dumps(cmd_payload), qos=1)
            print("[PC-MAINT] Sent 'fetch_logs' request (id=%s) to %s" % (command_id, topic_command))
        else:
            print("[PC-MAINT] Connection failed with rc=%d" % rc)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            if payload.get("command_id") == command_id or payload.get("action") in ("fetch_logs", "maintenance_diagnostics"):
                result_container["data"] = payload
                result_container["received"] = True
                print("[PC-MAINT] Received diagnostic response from %s!" % edge_id)
        except Exception as e:
            pass

    maint_client_id = os.getenv("MQTT_MAINT_CLIENT_ID", "%s-maint" % edge_id)
    client = mqtt_lib.Client(client_id=maint_client_id, clean_session=True)
    if DEFAULT_USER:
        client.username_pw_set(DEFAULT_USER, DEFAULT_PASS)
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS)
    client.on_connect = on_connect
    client.on_message = on_message

    print("[PC-MAINT] Connecting to %s:%d ..." % (DEFAULT_HOST, DEFAULT_PORT))
    client.connect(DEFAULT_HOST, DEFAULT_PORT, keepalive=30)
    client.loop_start()

    # Wait for response
    start_t = time.time()
    try:
        while time.time() - start_t < timeout_s:
            if result_container["received"]:
                break
            time.sleep(0.2)
    finally:
        client.loop_stop()
        client.disconnect()

    data = result_container["data"]
    if not data:
        print("[PC-MAINT] [ERROR] Timeout waiting for Jetson response after %.1f seconds." % timeout_s)
        print("          Please check if communication/jetson_agent.py is running on Jetson.")
        return None

    # Determine output file path
    if not output_file:
        logs_dir = os.path.join(ROOT_DIR, "webgis", "backend", "data", "logs")
        os.makedirs(logs_dir, exist_ok=True)
        output_file = os.path.join(logs_dir, "jetson_%s_latest.log" % edge_id)

    # Save to file
    msg_obj = data.get("message") if isinstance(data.get("message"), dict) else data
    log_text = msg_obj.get("logs", "") if isinstance(msg_obj, dict) else str(msg_obj)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("=== JETSON DIAGNOSTIC LOG [%s] ===\n" % edge_id)
        f.write("Timestamp: %s\n" % data.get("timestamp"))
        if isinstance(msg_obj, dict):
            f.write("System: %s\n" % json.dumps(msg_obj.get("system_info", {}), indent=2))
            f.write("Pipeline Status: %s\n" % json.dumps(msg_obj.get("pipeline_status", {}), indent=2))
        f.write("\n=== RAW LOGS ===\n")
        f.write(log_text)

    print("[PC-MAINT] Successfully saved Jetson logs to: %s" % output_file)
    print("\n----------------- [LOG PREVIEW] -----------------")
    print(log_text[-1200:] if len(log_text) > 1200 else log_text)
    print("-------------------------------------------------")
    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Jetson diagnostic logs via MQTT.")
    parser.add_argument("--edge-id", default="edge-01", help="Edge Device ID (default: edge-01)")
    parser.add_argument("--lines", type=int, default=100, help="Number of log lines (default: 100)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout in seconds (default: 10)")
    parser.add_argument("--output", default=None, help="Output file path (default: webgis/backend/data/logs/...)")
    args = parser.parse_args()

    fetch_logs_from_jetson(edge_id=args.edge_id, num_lines=args.lines, timeout_s=args.timeout, output_file=args.output)
