#!/usr/bin/env python3
"""Standalone mode: analytics reads VIDEO, this agent owns CSI when capturing.

CSI analytics MUST embed SnapshotCoordinator in the DeepStream process instead.
"""
import argparse
import json
import logging
import os
import signal
import ssl
import threading
try:
    from .config import load_env_file, mqtt_settings
    from .runtime import create_from_env
except ImportError:
    from config import load_env_file, mqtt_settings
    from runtime import create_from_env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=os.path.join(os.path.dirname(__file__), ".env"))
    args = parser.parse_args()
    load_env_file(args.env)
    if os.getenv("ANALYTICS_SOURCE", "csi").lower() not in ("video", "video_demo", "file"):
        parser.error("Standalone agent requires ANALYTICS_SOURCE=video. For CSI embed service in DeepStream; no second camera opener.")
    import paho.mqtt.client as mqtt  # paho-mqtt==1.6.1 on Python 3.6
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    config = mqtt_settings()
    # Clean session + non-retained commands: do not execute old broker commands after reconnect.
    client = mqtt.Client(client_id=config["client_id"], clean_session=True)
    if config["username"]:
        client.username_pw_set(config["username"], config["password"])
    if config["tls"]:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.max_queued_messages_set(100)

    def publish_result(result):
        client.publish(config["result_topic"], json.dumps(result), qos=1, retain=False)

    service = create_from_env(publish_result, analysis_source="video")

    def on_connect(current, _userdata, _flags, rc):
        if rc == 0:
            current.subscribe([(config["command_topic"], 1), (config["telemetry_topic"], 0)])
            logging.info("MQTT connected; mode VIDEO_DEMO -> CSI_DIRECT")
        else:
            logging.error("MQTT connection refused (rc=%s)", rc)

    def on_message(_client, _userdata, message):
        if message.retain or len(message.payload) > 65536:
            return
        if message.topic == config["command_topic"]:
            service.handle_mqtt_command(message.payload, retained=message.retain)
        elif message.topic == config["telemetry_topic"]:
            try:
                service.update_telemetry(json.loads(message.payload.decode("utf-8")), network=True)
            except (ValueError, UnicodeError):
                pass

    client.on_connect, client.on_message = on_connect, on_message
    stopping = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopping.set())
    service.start()
    try:
        client.connect_async(config["host"], config["port"], keepalive=30)
        client.loop_start()
        while not stopping.wait(0.5):
            if not service.is_running():
                raise RuntimeError("Snapshot worker stopped; check outbox storage")
    finally:
        service.stop()  # Drain copied frames/save uploads before stopping MQTT.
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
