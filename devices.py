# backend/devices.py
from typing import Optional

from .model import DataModel, Channel
from .opc_worker import OpcWorker


class IonSourceDevice:
    """Kapselt die Delta-Spannungslogik für Extraction / Einzellinse."""

    def __init__(self, model: DataModel, opc: OpcWorker):
        self.model = model
        self.opc = opc
        self._last_extraction: Optional[float] = None
        self._last_einzellinse: Optional[float] = None
        self._delta: float = 0.0

        self.model.subscribe("extraction_voltage_set", self._on_extraction_update)
        self.model.subscribe("einzellinse_voltage_set", self._on_einzellinse_update)

    def _on_extraction_update(self, ch: Channel):
        if isinstance(ch.value, (int, float)):
            self._last_extraction = float(ch.value)
            self._update_delta()

    def _on_einzellinse_update(self, ch: Channel):
        if isinstance(ch.value, (int, float)):
            self._last_einzellinse = float(ch.value)
            self._update_delta()

    def _update_delta(self):
        if self._last_extraction is not None and self._last_einzellinse is not None:
            self._delta = self._last_einzellinse - self._last_extraction
            self.model.update("delta_voltage", self._delta, source="logic")

    # API für GUI/Backend
    def set_extraction_voltage(self, value: float):
        """Setzt Extraction und führt Einzellinse nach."""
        self.opc.write("extraction_voltage_set", value)
        new_einzellinse = value + self._delta
        self.opc.write("einzellinse_voltage_set", new_einzellinse)

    def set_einzellinse_voltage(self, value: float):
        """Setzt Einzellinse und aktualisiert Delta."""
        self.opc.write("einzellinse_voltage_set", value)
        # Delta wird über Subscriptions neu berechnet
