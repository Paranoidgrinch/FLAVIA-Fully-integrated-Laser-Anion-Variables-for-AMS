# backend/logger_thread.py
import threading
from datetime import datetime
from typing import List

from .model import DataModel


class LoggerThread(threading.Thread):
    def __init__(self, model: DataModel, channels_to_log: List[str],
                 filepath: str, interval: float = 1.0):
        super().__init__(daemon=True)
        self.model = model
        self.channels = channels_to_log
        self.filepath = filepath
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self):
        try:
            with open(self.filepath, "w") as f:
                header = "timestamp\t" + "\t".join(self.channels) + "\n"
                f.write(header)
                while not self._stop_event.is_set():
                    from time import sleep

                    line_parts = [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
                    for name in self.channels:
                        ch = self.model.get(name)
                        val = ch.value if ch else None
                        if isinstance(val, float):
                            line_parts.append(f"{val:.6f}")
                        else:
                            line_parts.append(str(val) if val is not None else "nan")
                    f.write("\t".join(line_parts) + "\n")
                    f.flush()
                    if self._stop_event.wait(self.interval):
                        break
        except Exception:
            # Logging-Fehler werden hier nicht weitergegeben
            pass

    def stop(self):
        self._stop_event.set()
        self.join(timeout=3.0)
