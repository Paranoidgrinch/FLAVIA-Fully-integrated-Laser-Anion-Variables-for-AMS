# backend/opc_worker.py
import threading
import queue
from typing import Dict, Any, Optional

from opcua import Client
from opcua.ua import VariantType

from .model import DataModel
from .config import CHANNELS


class OpcWorker(threading.Thread):
    def __init__(self, url: str, model: DataModel,
                 poll_interval: float = 1.0,
                 reconnect_delay: float = 5.0):
        super().__init__(daemon=True)
        self.url = url
        self.model = model
        self.poll_interval = poll_interval
        self.reconnect_delay = reconnect_delay

        self._client: Optional[Client] = None
        self._nodes: Dict[str, Any] = {}  # name -> opcua.Node
        self._stop_event = threading.Event()
        self._cmd_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._poll_now = threading.Event()
        self._reconnect_event = threading.Event()

        # nur Kanäle mit OPC-Konfiguration
        self._opc_channels = {
            name: cfg for name, cfg in CHANNELS.items() if cfg.opc_node_id
        }

    def run(self):
        import time

        while not self._stop_event.is_set():
            try:
                if self._client is None or self._reconnect_event.is_set():
                    self._disconnect()
                    self._reconnect_event.clear()
                    self._try_connect()

                if self._client is not None:
                    self._process_commands()
                    self._poll_nodes()

            except Exception:
                # Bei Fehler: Verbindung schließen und nach Delay neu versuchen
                self._disconnect()
                if self._stop_event.wait(self.reconnect_delay):
                    break
            finally:
                # auf nächsten Poll warten (oder sofort, wenn force_poll)
                if self._stop_event.is_set():
                    break
                self._poll_now.wait(self.poll_interval)
                self._poll_now.clear()

        self._disconnect()

    def _try_connect(self):
        self.model.update("opc_connected", False, source="opc", quality="bad")
        self._client = Client(self.url)
        self._client.connect()
        self._nodes.clear()
        for name, cfg in self._opc_channels.items():
            self._nodes[name] = self._client.get_node(cfg.opc_node_id)
        self.model.update("opc_connected", True, source="opc", quality="good")

    def _disconnect(self):
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._nodes.clear()
        self.model.update("opc_connected", False, source="opc", quality="bad")

    def _process_commands(self):
        while True:
            try:
                name, value = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            cfg = self._opc_channels.get(name)
            node = self._nodes.get(name)
            if not cfg or not node or not cfg.opc_write:
                continue
            try:
                if cfg.opc_variant_type == VariantType.Boolean:
                    v = bool(value)
                    node.set_value(v)
                    self.model.update(name, v, source="opc")
                else:
                    v = float(value)
                    node.set_value(v, cfg.opc_variant_type or VariantType.Float)
                    self.model.update(name, v, source="opc")
            except Exception:
                # Fehler beim Schreiben ignorieren / später logging
                pass

    def _poll_nodes(self):
        if self._client is None:
            return
        for name, cfg in self._opc_channels.items():
            if not cfg.opc_read:
                continue
            node = self._nodes.get(name)
            if not node:
                continue
            try:
                value = node.get_value()
                if cfg.opc_variant_type == VariantType.Boolean:
                    value = bool(value)
                else:
                    value = float(value)
                self.model.update(name, value, source="opc")
            except Exception:
                # Einzelner Node-Read darf nicht den kompletten Thread killen
                pass

    # öffentliche API
    def write(self, channel_name: str, value: Any):
        self._cmd_queue.put((channel_name, value))
        self.force_poll()

    def force_poll(self):
        self._poll_now.set()

    def request_reconnect(self):
        self._reconnect_event.set()
        self.force_poll()

    def stop(self):
        self._stop_event.set()
        self.force_poll()
        self.join(timeout=5.0)
        self._disconnect()
