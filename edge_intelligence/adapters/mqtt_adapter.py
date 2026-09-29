"""
OpsLens - MQTT Adapter

Subscribes to MQTT broker topics and maps payloads to TagReading.
Configuration:
  MQTT_BROKER_URL    e.g. mqtt://localhost:1883
  MQTT_TOPICS        comma-separated list of topics
  MQTT_TAG_MAPPING   path to JSON mapping topic->tag_name

SAFETY: READ-ONLY subscriber. Never publishes control commands.
Gracefully disabled if paho-mqtt is not installed.
"""
import os
import json
import logging
import asyncio
from typing import AsyncGenerator, Dict, Any, Optional
from .base import BaseAdapter

logger = logging.getLogger("opslens.adapter.mqtt")

MQTT_BROKER = os.environ.get("MQTT_BROKER_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
MQTT_TOPICS = os.environ.get("MQTT_TOPICS", "opslens/telemetry/#").split(",")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", None)
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", None)


class MQTTAdapter(BaseAdapter):
    """
    MQTT subscriber adapter. Maps MQTT payloads to OpsLens TagReading model.
    READ-ONLY: Never publishes to control topics.
    """

    def __init__(self):
        self._client = None
        self._connected = False
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    async def connect(self) -> bool:
        try:
            import paho.mqtt.client as mqtt
            self._client = mqtt.Client()
            if MQTT_USERNAME:
                self._client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

            def on_message(client, userdata, msg):
                try:
                    payload = json.loads(msg.payload.decode("utf-8"))
                    self._queue.put_nowait({"topic": msg.topic, "payload": payload})
                except Exception as e:
                    logger.debug(f"[MQTTAdapter] Failed to parse message: {e}")

            self._client.on_message = on_message
            self._client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            for topic in MQTT_TOPICS:
                self._client.subscribe(topic.strip())
            self._client.loop_start()
            self._connected = True
            logger.info(f"[MQTTAdapter] Connected to {MQTT_BROKER}:{MQTT_PORT}")
            return True
        except ImportError:
            logger.warning("[MQTTAdapter] paho-mqtt not installed. Run: pip install paho-mqtt")
            return False
        except Exception as e:
            logger.error(f"[MQTTAdapter] Connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
        self._connected = False

    async def stream_readings(self) -> AsyncGenerator:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from models import TagReading, current_iso_utc
        from tag_registry import TAG_REGISTRY

        while self._connected:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                payload = msg["payload"]
                # Expected MQTT payload: {"tag": "VLV-04-POS", "value": 43.0, ...}
                tag = payload.get("tag") or payload.get("tag_id")
                value = payload.get("value")
                if tag and value is not None:
                    reg = TAG_REGISTRY.get(tag)
                    yield TagReading(
                        tag=tag,
                        value=value,
                        timestamp=payload.get("timestamp", current_iso_utc()),
                        unit=reg.unit if reg else payload.get("unit", ""),
                        equipment_id=reg.equipment_id if reg else payload.get("equipment_id", "UNKNOWN"),
                    )
            except asyncio.TimeoutError:
                continue

    def status(self) -> Dict[str, Any]:
        return {
            "adapter": "mqtt",
            "connected": self._connected,
            "broker": f"{MQTT_BROKER}:{MQTT_PORT}",
            "subscribed_topics": MQTT_TOPICS,
            "read_only": True,
        }

    @property
    def adapter_type(self) -> str:
        return "mqtt"
