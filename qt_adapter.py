# gui/qt_adapter.py
from PyQt5.QtCore import QObject, pyqtSignal

from backend import Backend
from backend.model import Channel


class QtBackendAdapter(QObject):
    channelUpdated = pyqtSignal(str, object)

    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self._subscribed_channels: set[str] = set()

    def register_channel(self, name: str):
        """Backend-Channel abonnieren und ggf. aktuellen Wert sofort senden."""
        if name in self._subscribed_channels:
            return
        self._subscribed_channels.add(name)

        # zukünftige Änderungen aus Backend-Thread
        self.backend.model.subscribe(name, self._on_channel_update)

        # aktuellen Wert, falls schon vorhanden, sofort in den GUI-Thread schicken
        ch = self.backend.model.get(name)
        if ch is not None:
            self.channelUpdated.emit(ch.name, ch.value)

    def _on_channel_update(self, ch: Channel):
        # Wird in Backend-Threads aufgerufen; Signal geht thread-sicher in GUI-Thread
        self.channelUpdated.emit(ch.name, ch.value)
