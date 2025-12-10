# backend/magnet_worker.py

import threading
import time
import socket
import queue
from typing import Optional

from .model import DataModel


MAGNET_DEFAULT_HOST = "192.168.0.5"
MAGNET_DEFAULT_PORT = 8462


class MagnetWorker(threading.Thread):
    """
    Thread für die TCP-Verbindung zum Delta SM 60-100 Magnet-Netzteil.
    - verarbeitet Sollwerte (Strom)
    - liest periodisch Messwerte (Strom/Spannung)
    - aktualisiert DataModel-Kanäle:
        magnet_connected (bool)
        magnet_current_set (A)
        magnet_current_meas (A)
        magnet_voltage_meas (V)
    """

    def __init__(self,
                 model: DataModel,
                 host: str = MAGNET_DEFAULT_HOST,
                 port: int = MAGNET_DEFAULT_PORT,
                 poll_interval: float = 1.0,
                 voltage_limit: float = 60.0):
        super().__init__(daemon=True)
        self.model = model
        self.host = host
        self.port = port
        self.poll_interval = poll_interval
        self.voltage_limit = voltage_limit

        self._sock: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._cmd_queue: "queue.Queue[tuple[str, Optional[float]]]" = queue.Queue()

    # ------------------------------------------------------------------
    # Thread-Loop
    # ------------------------------------------------------------------
    def run(self):
        while not self._stop_event.is_set():
            # Verbindung sicherstellen
            if self._sock is None:
                self._connect()

            # Kommandos bearbeiten
            try:
                cmd, arg = self._cmd_queue.get(timeout=self.poll_interval)
                if cmd == "set_current" and arg is not None:
                    self._handle_set_current(arg)
                elif cmd == "shutdown":
                    break
            except queue.Empty:
                pass
            except Exception:
                self._disconnect()

            # Messwerte pollen
            try:
                self._poll_measurements()
            except Exception:
                self._disconnect()

        self._disconnect()

    # ------------------------------------------------------------------
    # Verbindungslogik
    # ------------------------------------------------------------------
    def _connect(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((self.host, self.port))
            self._sock = s
            self._update_connected(True)
        except Exception:
            self._sock = None
            self._update_connected(False)

    def _disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._update_connected(False)

    def _update_connected(self, connected: bool):
        self.model.update(
            "magnet_connected",
            bool(connected),
            source="magnet",
            quality="good" if connected else "bad",
        )

    # ------------------------------------------------------------------
    # Low-Level-Kommunikation
    # ------------------------------------------------------------------
    def _send_command(self, cmd: str, expect_response: bool = False) -> Optional[str]:
        if self._sock is None:
            self._connect()
            if self._sock is None:
                return None
        try:
            self._sock.sendall((cmd + "\n").encode("ascii"))
            if expect_response:
                resp = self._sock.recv(1024).decode("ascii").strip()
                return resp
            return None
        except Exception:
            self._disconnect()
            return None

    def _handle_set_current(self, current: float):
        # Begrenzen
        current = max(0.0, min(120.0, float(current)))

        # Strom und feste Spannung setzen
        self._send_command(f"sour:curr {current:.4f}", expect_response=False)
        self._send_command(f"sour:volt {self.voltage_limit:.3f}", expect_response=False)

        # Sollwert im Modell aktualisieren
        self.model.update(
            "magnet_current_set",
            current,
            source="magnet",
        )

    def _poll_measurements(self):
        if self._sock is None:
            return

        # Strom
        cur_str = self._send_command("meas:curr?", expect_response=True)
        if cur_str:
            try:
                cur = float(cur_str)
                self.model.update(
                    "magnet_current_meas",
                    cur,
                    source="magnet",
                )
            except ValueError:
                pass

        # Spannung
        volt_str = self._send_command("meas:volt?", expect_response=True)
        if volt_str:
            try:
                volt = float(volt_str)
                self.model.update(
                    "magnet_voltage_meas",
                    volt,
                    source="magnet",
                )
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------
    def set_current(self, current: float):
        """Sollstrom setzen (A)."""
        try:
            self._cmd_queue.put_nowait(("set_current", float(current)))
        except queue.Full:
            pass

    def shutdown(self):
        """Thread beenden."""
        self._stop_event.set()
        try:
            self._cmd_queue.put_nowait(("shutdown", None))
        except queue.Full:
            pass
