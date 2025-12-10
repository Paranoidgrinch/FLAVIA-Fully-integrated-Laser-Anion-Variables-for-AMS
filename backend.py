# backend/backend.py
import threading
import time
from typing import Optional, List

from .config import (
    OPC_DEFAULT_URL,
    MQTT_DEFAULT_HOST,
    MQTT_DEFAULT_PORT,
    BACKEND_LOG_CHANNELS,
)
from .model import DataModel
from .opc_worker import OpcWorker
from .mqtt_worker import MqttWorker
from .devices import IonSourceDevice
from .logger_thread import LoggerThread
from .stepper_worker import StepperWorker
from .magnet_worker import MagnetWorker
from .gaussmeter_worker import GaussmeterWorker
from .keithley_worker import KeithleyWorker


class Backend:
    """Orchestriert OPC-Worker, MQTT-Worker, Devices und Logging."""

    def __init__(self,
                 opc_url: str = OPC_DEFAULT_URL,
                 mqtt_host: str = MQTT_DEFAULT_HOST,
                 mqtt_port: int = MQTT_DEFAULT_PORT):
        # zentrales Datenmodell
        self.model = DataModel()

        # Worker
        self.opc = OpcWorker(opc_url, self.model, poll_interval=1.0)
        self.mqtt = MqttWorker(mqtt_host, mqtt_port, self.model)

        # Domänenlogik (z.B. Delta-Spannung)
        self.ion_source = IonSourceDevice(self.model, self.opc)

        # Logger (optional)
        self.logger: Optional[LoggerThread] = None

        # Stepper
        self.stepper = StepperWorker(self.model)  # NEU

        #threading lock fü rad bewegung
        self._sample_move_lock = threading.Lock()

        #Magnet
        self.magnet = MagnetWorker(self.model)          # NEU
        self.gaussmeter = GaussmeterWorker(self.model)  # NEU


        #keithley
        self.keithley = KeithleyWorker(self.model)



    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    def start(self):
        """OPC- und MQTT-Threads starten."""
        self.opc.start()
        self.mqtt.start()
        self.stepper.start()
        self.magnet.start()       # NEU
        self.gaussmeter.start()   # NEU
        self.keithley.start()

    def stop(self):
        """Worker und Logger sauber stoppen."""
        if self.logger:
            self.logger.stop()
            self.logger = None
        #stepper
        try:
            self.stepper.shutdown()
        except Exception:
            pass
        # Magnet & Gaussmeter
        try:
            self.magnet.shutdown()
        except Exception:
            pass
        try:
            self.gaussmeter.shutdown()
        except Exception:
            pass

        # Keithley
        try:
            self.keithley.shutdown()
        except Exception:
            pass

        #opc
        try:
            self.opc.stop()
        except Exception:
            pass

        #mqtt
        try:
            self.mqtt.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # High-Level API für GUI / andere Frontends
    # ------------------------------------------------------------------
    def set_digital_output(self, name: str, value: bool):
        """Digitalen Ausgang über OPC setzen."""
        self.opc.write(name, bool(value))

    def set_opc_analog(self, name: str, value: float):
        """Analogen OPC-Sollwert setzen."""
        self.opc.write(name, float(value))

    def set_extraction_voltage(self, value: float):
        """Extraction-Spannung setzen (inkl. Delta-Logik für Einzellinse)."""
        self.ion_source.set_extraction_voltage(float(value))

    def set_einzellinse_voltage(self, value: float):
        """Einzellinse-Spannung setzen (Delta wird neu berechnet)."""
        self.ion_source.set_einzellinse_voltage(float(value))

    def set_mqtt_setpoint(self, name: str, value: float):
        """MQTT-Sollwert (PSU/HV) setzen."""
        self.mqtt.publish_value(name, float(value))

    def set_magnet_current(self, value: float):
        """Magnet-Sollstrom (A) setzen."""
        self.magnet.set_current(float(value))

    
    # ----------------------------------------------------------
    # Stepper-API für GUI (mit HV-Ramping)
    # ----------------------------------------------------------
    def move_sample_to_position(self, steps: int):
        """
        Sample-Rad bewegen:
        - HV (Sputter, Extraction, Einzellinse) mit max. 250 V/s auf 0 fahren
        - Stepper zur Zielposition fahren
        - HV wieder auf ursprüngliche Werte hochfahren
        Läuft in einem eigenen Thread, blockiert GUI nicht.
        """
        t = threading.Thread(
            target=self._perform_sample_move,
            args=(int(steps), False),
            daemon=True,
        )
        t.start()

    def stop_stepper(self):
        """Stepper-Bewegung sofort stoppen (HV-Ramping wird NICHT abgebrochen)."""
        self.stepper.stop_motion()

    def home_stepper(self):
        """
        Home-Fahrt mit HV-Ramping:
        - HV runter
        - Home-Fahrt
        - HV wieder hoch
        """
        t = threading.Thread(
            target=self._perform_sample_move,
            args=(None, True),
            daemon=True,
        )
        t.start()

    # ----------------------------------------------------------
    # Hilfsfunktionen für HV-Ramping / Stepper
    # ----------------------------------------------------------
    def _get_channel_value(self, name: str, default: float = 0.0) -> float:
        ch = self.model.get(name)
        if ch is None or ch.value is None:
            return default
        try:
            return float(ch.value)
        except Exception:
            return default
        


    def _ramp_values(self,
                     start: dict[str, float],
                     end: dict[str, float],
                     max_rate: float = 250.0,
                     dt: float = 0.1):
        """
        Rampen von start[name] zu end[name] mit max. max_rate V/s.
        dt: Zeit pro Schritt (s). Schrittweite = max_rate * dt.
        Wird über OPC-Worker geschrieben.
        """
        # Kopie, damit wir lokal arbeiten
        current = dict(start)
        max_step = max_rate * dt

        if max_step <= 0:
            # Fallback: direkt setzen
            for name, target in end.items():
                self.opc.write(name, target)
            return

        while True:
            all_done = True
            for name, cur in current.items():
                target = end.get(name, cur)
                if abs(cur - target) <= 0.1:
                    # bereits am Ziel
                    continue

                all_done = False

                if cur < target:
                    new_val = min(cur + max_step, target)
                else:
                    new_val = max(cur - max_step, target)

                current[name] = new_val
                self.opc.write(name, new_val)

            if all_done:
                break

            time.sleep(dt)

        # am Ende einmal sicherstellen, dass die Zielwerte gesetzt sind
        for name, target in end.items():
            self.opc.write(name, target)



    def _wait_for_stepper_idle(self, max_wait_sec: float = 120.0):
        """
        Wartet, bis stepper_moving False ist (oder max_wait_sec abgelaufen sind).
        """
        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            ch = self.model.get("stepper_moving")
            moving = bool(ch.value) if ch and ch.value is not None else False
            if not moving:
                return True
            time.sleep(0.2)
        return False
    


    def _perform_sample_move(self, target_steps: Optional[int], home: bool):
        """
        Führt eine komplette Sample-Bewegung mit HV-Ramping aus:
        1) HV (Sputter, Extraction, Einzellinse) auf 0V rampen (max. 250 V/s)
        2) Stepper bewegen (Go oder Home)
        3) Auf Bewegungsende warten
        4) HV wieder auf ursprüngliche Werte rampen (max. 250 V/s)
        """
        hv_channels = [
            "sputter_voltage_set",
            "extraction_voltage_set",
            "einzellinse_voltage_set",
        ]

        with self._sample_move_lock:
            # 1) aktuelle HV-Sollwerte auslesen
            initial_values = {
                name: self._get_channel_value(name, 0.0) for name in hv_channels
            }

            # 2) HV auf 0V rampen
            down_start = dict(initial_values)
            down_end = {name: 0.0 for name in hv_channels}
            self._ramp_values(down_start, down_end, max_rate=2500.0, dt=0.1)

            # 3) Stepper bewegen
            if home:
                self.stepper.go_home()
            else:
                if target_steps is not None:
                    self.stepper.move_to(int(target_steps))

            # 4) auf Ende der Bewegung warten (oder Timeout)
            self._wait_for_stepper_idle(max_wait_sec=120.0)


            #4a) buffer wartezeit weil das rad langsam ist
            time.sleep(5.0)

            # 5) HV wieder hoch auf ursprüngliche Werte
            up_start = {name: 0.0 for name in hv_channels}
            up_end = dict(initial_values)
            self._ramp_values(up_start, up_end, max_rate=2500.0, dt=0.1)

    

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def start_logging(self, filepath: str,
                      interval: float = 1.0,
                      channels: Optional[List[str]] = None):
        """Logging-Thread starten."""
        if channels is None:
            channels = BACKEND_LOG_CHANNELS
        if self.logger:
            self.logger.stop()
        self.logger = LoggerThread(self.model, channels, filepath, interval)
        self.logger.start()

    def stop_logging(self):
        """Logging-Thread stoppen."""
        if self.logger:
            self.logger.stop()
            self.logger = None

    # ------------------------------------------------------------------
    # OPC-Hilfsfunktionen
    # ------------------------------------------------------------------
    def request_opc_reconnect(self):
        """OPC-Reconnect anfordern."""
        self.opc.request_reconnect()

    def force_opc_poll(self):
        """OPC-Poll sofort erzwingen."""
        self.opc.force_poll()
