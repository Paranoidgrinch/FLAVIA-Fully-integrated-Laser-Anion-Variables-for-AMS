# backend/keithley_worker.py

import threading
import time
import socket
from typing import Optional

from .model import DataModel


KEITHLEY_DEFAULT_HOST = "192.168.0.2"
KEITHLEY_DEFAULT_PORT = 100


class KeithleyWorker(threading.Thread):
    """
    Hintergrundthread für das Keithley 6485.
    - Liest mit ~10 Hz Stromwerte (READ?)
    - Schreibt Momentanwert in nA und 1s-Intervallmittel + Sigma ins DataModel.

    Channels:
      keithley_connected            (bool)
      keithley_current_nA           (float)  # Momentanwert
      keithley_current_nA_avg_1s    (float)  # Mittelwert der letzten Sekunde
      keithley_current_nA_sigma_1s  (float)  # Sigma der letzten Sekunde
    """

    def __init__(self,
                 model: DataModel,
                 host: str = KEITHLEY_DEFAULT_HOST,
                 port: int = KEITHLEY_DEFAULT_PORT,
                 sample_period: float = 0.1,
                 avg_interval: float = 1.0):
        super().__init__(daemon=True)
        self.model = model
        self.host = host
        self.port = port
        self.sample_period = sample_period
        self.avg_interval = avg_interval

        self._stop_event = threading.Event()
        self._sock: Optional[socket.socket] = None

        # Aggregation für 1-s-Intervall
        self._bucket_start: Optional[float] = None
        self._bucket_values: list[float] = []

    # ------------------------------------------------------------------
    def run(self):
        buf = b""
        try:
            while not self._stop_event.is_set():
                # Verbindung sicherstellen
                if self._sock is None:
                    self._connect()
                    # nicht zu aggressiv reconnecten
                    if self._sock is None:
                        time.sleep(1.0)
                        continue

                cycle_start = time.perf_counter()

                try:
                    self._sock.sendall(b"READ?\n")
                except OSError:
                    # Verbindung verloren -> neu verbinden
                    self._disconnect()
                    continue

                line = None
                # Antwortzeile einlesen
                while not self._stop_event.is_set() and line is None:
                    try:
                        chunk = self._sock.recv(4096)
                    except socket.timeout:
                        continue
                    except OSError:
                        self._disconnect()
                        break

                    if not chunk:
                        # Verbindung vom Gerät geschlossen
                        self._disconnect()
                        break

                    buf += chunk
                    if b"\n" in buf:
                        line_bytes, buf = buf.split(b"\n", 1)
                        line = line_bytes.decode("ascii", errors="ignore").strip()

                if self._sock is None or self._stop_event.is_set():
                    continue

                if not line:
                    continue

                try:
                    current_A = float(line.replace(",", "."))
                except ValueError:
                    continue

                # in nA, Betrag
                current_nA = abs(current_A) * 1e9

                # Momentanwert ins Modell schreiben
                self.model.update(
                    "keithley_current_nA",
                    current_nA,
                    source="keithley",
                    quality="good",
                )

                # 1-s-Aggregation aktualisieren
                now = time.perf_counter()
                self._update_avg_bucket(now, current_nA)

                # 10-Hz-Takt einhalten
                cycle_time = time.perf_counter() - cycle_start
                remaining = self.sample_period - cycle_time
                if remaining > 0:
                    time.sleep(remaining)

        finally:
            self._disconnect()

    # ------------------------------------------------------------------
    def _connect(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect((self.host, self.port))
            self._sock = s
            self._set_connected(True)
            self._initialize_keithley()
        except Exception:
            self._sock = None
            self._set_connected(False)

    def _disconnect(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._set_connected(False)

    def _set_connected(self, connected: bool):
        self.model.update(
            "keithley_connected",
            bool(connected),
            source="keithley",
            quality="good" if connected else "bad",
        )

    def _send_scpi(self, cmd: str):
        if self._sock is None:
            return
        try:
            self._sock.sendall((cmd + "\n").encode("ascii"))
        except OSError:
            self._disconnect()

    def _initialize_keithley(self):
        # vereinfachte Grundkonfiguration
        commands = [
            "*RST",
            ":SYST:ZCH OFF",
            ":SYST:ZCOR ON",
            ":FORM:ELEM READ",
            ":SENS:CURR:RANG:AUTO ON",
            f":SENS:CURR:NPLC 0.1",
        ]
        for cmd in commands:
            self._send_scpi(cmd)
            time.sleep(0.05)

    # ------------------------------------------------------------------
    def _update_avg_bucket(self, now: float, current_nA: float):
        """Berechnet 1-s-Mittelwert + Sigma und schreibt ins DataModel."""
        if self._bucket_start is None:
            self._bucket_start = now
            self._bucket_values = [current_nA]
            return

        self._bucket_values.append(current_nA)
        if now - self._bucket_start >= self.avg_interval:
            values = self._bucket_values
            n = len(values)
            if n == 0:
                self._bucket_start = now
                self._bucket_values = []
                return

            mean = sum(values) / n
            if n > 1:
                var = sum((v - mean) ** 2 for v in values) / n
            else:
                var = 0.0
            sigma = max(var, 0.0) ** 0.5

            self.model.update(
                "keithley_current_nA_avg_1s",
                mean,
                source="keithley",
                quality="good",
            )
            self.model.update(
                "keithley_current_nA_sigma_1s",
                sigma,
                source="keithley",
                quality="good",
            )

            # neuen Bucket starten
            self._bucket_start = now
            self._bucket_values = [current_nA]

    # ------------------------------------------------------------------
    def shutdown(self):
        self._stop_event.set()
