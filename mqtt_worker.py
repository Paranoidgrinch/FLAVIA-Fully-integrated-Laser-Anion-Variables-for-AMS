# backend/mqtt_worker.py
import threading
import time
from typing import Dict, List

import paho.mqtt.client as mqtt

from .model import DataModel
from .config import CHANNELS, MQTT_DEFAULT_HOST, MQTT_DEFAULT_PORT, MQTT_DEFAULT_KEEPALIVE


class MqttWorker(threading.Thread):
    def __init__(self, host: str = MQTT_DEFAULT_HOST,
                 port: int = MQTT_DEFAULT_PORT,
                 model: DataModel = None):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.model = model

        self._client = mqtt.Client(protocol=mqtt.MQTTv311)
        self._stop_event = threading.Event()

        # nur Kanäle mit MQTT-Konfiguration
        self._mqtt_channels = {
            name: cfg for name, cfg in CHANNELS.items() if cfg.mqtt_topic
        }
        self._topic_to_names: Dict[str, List[str]] = {}
        for name, cfg in self._mqtt_channels.items():
            self._topic_to_names.setdefault(cfg.mqtt_topic, []).append(name)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def run(self):
        try:
            self._client.connect(self.host, self.port, keepalive=MQTT_DEFAULT_KEEPALIVE)
            self._client.loop_start()
            # warten, bis Stop angefordert
            while not self._stop_event.is_set():
                time.sleep(0.1)
        except Exception:
            if self.model:
                self.model.update("mqtt_connected", False, source="mqtt", quality="bad")
        finally:
            try:
                self._client.loop_stop()
            except Exception:
                pass
            try:
                self._client.disconnect()
            except Exception:
                pass
            if self.model:
                self.model.update("mqtt_connected", False, source="mqtt", quality="bad")

    def _on_connect(self, client, userdata, flags, rc):
        ok = (rc == mqtt.CONNACK_ACCEPTED)
        if self.model:
            self.model.update("mqtt_connected", ok, source="mqtt")
        if ok:
            # alle Mess-Topics abonnieren
            for cfg in self._mqtt_channels.values():
                if cfg.mqtt_topic and not cfg.mqtt_is_setpoint:
                    client.subscribe(cfg.mqtt_topic)

    def _on_disconnect(self, client, userdata, rc):
        if self.model:
            self.model.update("mqtt_connected", False, source="mqtt", quality="bad")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8", errors="ignore")
        except Exception:
            payload = ""
        names = self._topic_to_names.get(topic, [])
        for name in names:
            cfg = self._mqtt_channels.get(name)
            if not cfg or not self.model:
                continue
            # versuchen, Zahl zu parsen
            try:
                v = float(payload.replace(",", "."))
            except Exception:
                v = payload
            self.model.update(name, v, source="mqtt")

    def publish_value(self, channel_name: str, value: float):
        cfg = self._mqtt_channels.get(channel_name)
        if not cfg or not cfg.mqtt_topic:
            return
        try:
            dec = cfg.decimals
            payload = f"{float(value):.{dec}f}".replace(",", ".")
            self._client.publish(cfg.mqtt_topic, payload=payload, qos=0, retain=False)
            # Local Model-Update (Setpoint)
            if self.model:
                self.model.update(channel_name, float(value), source="mqtt")
        except Exception:
            pass

    def stop(self):
        self._stop_event.set()
        self.join(timeout=5.0)
