# backend/model.py
from dataclasses import dataclass, field
from typing import Any, Dict, List, Callable, Optional
import threading
import time

from .config import CHANNELS


@dataclass
class Channel:
    name: str
    unit: str = ""
    value: Any = None
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    quality: str = "unknown"


class DataModel:
    """Thread-sicheres Datenmodell für alle Kanäle."""
    def __init__(self):
        self._lock = threading.RLock()
        self._channels: Dict[str, Channel] = {}
        self._subscribers: Dict[str, List[Callable[[Channel], None]]] = {}

    def update(self, name: str, value: Any, source: str = "", quality: str = "good"):
        with self._lock:
            cfg = CHANNELS.get(name)
            unit = cfg.unit if cfg else ""
            ch = self._channels.get(name)
            if ch is None:
                ch = Channel(name=name, unit=unit, value=value, source=source, quality=quality)
                self._channels[name] = ch
            else:
                ch.value = value
                ch.timestamp = time.time()
                ch.source = source
                ch.quality = quality

            subs = list(self._subscribers.get(name, []))

        # callbacks außerhalb des Locks
        for cb in subs:
            try:
                cb(ch)
            except Exception:
                pass

    def get(self, name: str) -> Optional[Channel]:
        with self._lock:
            return self._channels.get(name)

    def subscribe(self, name: str, callback: Callable[[Channel], None]):
        with self._lock:
            self._subscribers.setdefault(name, []).append(callback)
