# backend/gaussmeter_worker.py

import threading
import time
import socket
from typing import Optional

from .model import DataModel


GAUSSMETER_DEFAULT_HOST = "192.168.0.13"   # EX-6030
GAUSSMETER_DEFAULT_PORT = 100


class GaussmeterWorker(threading.Thread):
    """
    Thread für TCP-Verbindung zum EX-6030 / LakeShore 421.
    - Initialisiert das 421 auf Gauss/DC/Autorange
    - Liest periodisch das Magnetfeld und aktualisiert:
        gaussmeter_connected (bool)
        magnet_field_meas (kG)
    """

    def __init__(self,
                 model: DataModel,
                 host: str = GAUSSMETER_DEFAULT_HOST,
                 port: int = GAUSSMETER_DEFAULT_PORT,
                 poll_interval: float = 1.0):
        super().__init__(daemon=True)
        self.model = model
        self.host = host
        self.port = port
        self.poll_interval = poll_interval

        self._sock: Optional[socket.socket] = None
        self._stop_event = threading.Event()

        self._write_delay = 0.06
        self._read_idle = 0.25
        self._read_overall = 0.8

    # ------------------------------------------------------------------
    def run(self):
        while not self._stop_event.is_set():
            if self._sock is None:
                self._connect()

            if self._sock is not None:
                try:
                    field_kG = self._read_field_kG()
                    if field_kG != field_kG:  # NaN
                        # Fehler -> Verbindung schließen
                        self._disconnect()
                        self.model.update(
                            "magnet_field_meas",
                            float("nan"),
                            source="gauss",
                            quality="bad",
                        )
                    else:
                        self.model.update(
                            "magnet_field_meas",
                            field_kG,
                            source="gauss",
                            quality="good",
                        )
                except Exception:
                    self._disconnect()
            time.sleep(self.poll_interval)

        self._disconnect()

    # ------------------------------------------------------------------
    def _connect(self):
        try:
            s = socket.create_connection((self.host, self.port), timeout=2.0)
            s.settimeout(1.0)

            # Grundkonfiguration
            for cmd in (b"UNIT G", b"ACDC 0", b"AUTO 1"):
                s.sendall(cmd + b"\r\n")
                time.sleep(self._write_delay)
                self._read_line(s)

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
            "gaussmeter_connected",
            bool(connected),
            source="gauss",
            quality="good" if connected else "bad",
        )

    # ------------------------------------------------------------------
    def _read_line(self, sock: socket.socket) -> str:
        end = time.time() + self._read_overall
        buf = bytearray()
        while time.time() < end:
            sock.settimeout(self._read_idle)
            try:
                chunk = sock.recv(256)
            except socket.timeout:
                if buf:
                    break
                continue
            except OSError:
                return ""
            if not chunk:
                break
            buf += chunk
            if b"\r" in chunk or b"\n" in chunk:
                break
        try:
            return bytes(buf).strip().decode("ascii", "replace")
        except Exception:
            return ""

    def _txrx(self, cmd: str) -> str:
        if not self._sock:
            return ""
        try:
            self._sock.sendall(cmd.encode("ascii") + b"\r\n")
            time.sleep(self._write_delay)
            return self._read_line(self._sock)
        except OSError:
            return ""

    def _read_field_kG(self) -> float:
        if not self._sock:
            return float("nan")

        mult_map = {"µ": 1e-6, "u": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3}
        val = self._txrx("FIELD?")
        mul = self._txrx("FIELDM?")
        unit = self._txrx("UNIT?")

        try:
            base = float((val or "").strip())
        except Exception:
            return float("nan")

        value = base * mult_map.get((mul or "").strip(), 1.0)

        # in Gauss
        if (unit or "").strip().upper().startswith("T"):
            value *= 1e4  # 1 T = 10.000 G

        # Gauss -> kG
        return value / 1000.0

    # ------------------------------------------------------------------
    def shutdown(self):
        self._stop_event.set()
