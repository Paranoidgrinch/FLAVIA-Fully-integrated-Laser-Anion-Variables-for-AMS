import sys
import socket
import re

from PyQt5 import QtWidgets, QtCore


# Feste Laser-Adresse (bei Bedarf einfach hier ändern)
LASER_HOST = "192.168.0.7"
LASER_PORT = 103


# Fault-Code -> Beschreibung (paraphrasiert aus dem Manual)
FAULT_DESCRIPTIONS = {
    1: "Laser head interlock fault",
    2: "External interlock fault",
    3: "Power supply cover interlock fault",
    4: "LBO temperature fault",
    5: "LBO not locked at set temperature",
    6: "Vanadate temperature fault",
    7: "Etalon temperature fault",
    8: "Diode 1 temperature fault",
    10: "Baseplate temperature fault",
    11: "Diode heatsink 1 temperature fault",
    16: "Diode 1 over-current fault",
    18: "Over-current fault",
    19: "Diode 1 undervoltage fault",
    21: "Diode 1 overvoltage fault",
    25: "Diode 1 EEPROM fault",
    27: "Laser head EEPROM fault",
    28: "Power supply EEPROM fault",
    29: "Power supply/head mismatch fault",
    31: "Shutter state mismatch",
    40: "Head/diode mismatch fault",
    47: "Vanadate 2 temperature fault",
}


class LaserConnection:
    """
    Sehr dünner Wrapper um die TCP/IP-Verbindung zum Verdi.

    Nutzt die RS-232-Befehle aus dem Verdi-Manual über TCP.
    """

    def __init__(self, host, port, timeout=1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        """TCP-Verbindung aufbauen oder Exception werfen."""
        self.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        self.sock = s

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def send_command(self, command: str):
        """
        Kommando schicken und Antwort als bereinigten String zurückgeben.

        Gibt None zurück bei Timeout/Fehler.
        """
        if self.sock is None:
            return None

        try:
            data = (command + "\r\n").encode("ascii")
            self.sock.sendall(data)

            chunks = b""
            while True:
                try:
                    part = self.sock.recv(1024)
                except socket.timeout:
                    break
                if not part:
                    break
                chunks += part
                if b"\r\n" in chunks:
                    break

            if not chunks:
                return None

            text = chunks.decode("ascii", errors="ignore")
            text = text.replace("\r", "").replace("\n", "").strip()
            return text
        except OSError:
            return None

    # --------- Komfort-Methoden für konkrete Abfragen ------------ #

    def get_keyswitch_enabled(self):
        """True/False/None je nach ?K Antwort."""
        resp = self.send_command("?K")
        if resp is None:
            return None
        text = resp
        if text.upper().startswith("?K"):
            text = text[2:].strip()
        if text == "1":
            return True
        if text == "0":
            return False
        return None

    def get_fault_codes(self):
        """
        Liefert (codes, roher_text).

        codes:
          - None: keine Antwort vom Laser
          - []  : System OK
          - [..]: Liste von Fault-Codes (int)
        """
        resp = self.send_command("?F")
        if resp is None:
            return None, "No response from laser"

        text = resp
        if text.upper().startswith("?F"):
            text = text[2:].strip()

        if "SYSTEM OK" in text.upper():
            return [], "System OK"

        codes = []
        for part in re.split(r"[,&\s]+", text):
            if part.isdigit():
                try:
                    codes.append(int(part))
                except ValueError:
                    pass

        return codes, text

    def describe_fault_codes(self, codes):
        """Gibt eine Liste von beschreibenden Strings zu Fault-Codes zurück."""
        if not codes:
            return ["System OK"]
        lines = []
        for code in codes:
            desc = FAULT_DESCRIPTIONS.get(code, "Unknown fault")
            lines.append(f"{code}: {desc}")
        return lines

    def get_lbo_temperatures(self):
        """
        LBO set temperature (?LBOST) und measured temperature (?LBOT) als Floats.

        Rückgabe: (set_temp, measured_temp), jeweils Float oder None.
        """
        set_resp = self.send_command("?LBOST")
        meas_resp = self.send_command("?LBOT")

        def parse(resp_text, prefix):
            if resp_text is None:
                return None
            text = resp_text
            if text.upper().startswith(prefix.upper()):
                text = text[len(prefix):].strip()
            try:
                return float(text)
            except ValueError:
                return None

        set_temp = parse(set_resp, "?LBOST")
        meas_temp = parse(meas_resp, "?LBOT")
        return set_temp, meas_temp

    def get_laser_state(self):
        """
        ?L:
          0 = OFF (Standby)
          1 = ON
          2 = OFF wegen Fault
        """
        resp = self.send_command("?L")
        if resp is None:
            return None
        text = resp
        if text.upper().startswith("?L"):
            text = text[2:].strip()
        try:
            return int(text)
        except ValueError:
            return None

    def set_laser_on(self, on: bool):
        """L=1 / L=0 senden und Zustand grob prüfen."""
        cmd = f"L={1 if on else 0}"
        _ = self.send_command(cmd)
        state = self.get_laser_state()
        if state is None:
            return False
        if on:
            return state == 1
        else:
            return state == 0

    def set_shutter_open(self, open_: bool):
        """S=1 / S=0 – Shutter öffnen/schließen."""
        cmd = f"S={1 if open_ else 0}"
        _ = self.send_command(cmd)

    def set_power(self, watts: float):
        """P=nn.nnnn – Setze Light-Regulation-Sollwert."""
        value = max(0.0, float(watts))
        cmd = f"P={value:.4f}"
        _ = self.send_command(cmd)

    def get_set_power(self):
        """?SP – Set Power (Sollwert) als Float oder None."""
        resp = self.send_command("?SP")
        if resp is None:
            return None
        text = resp
        if text.upper().startswith("?SP"):
            text = text[3:].strip()
        try:
            return float(text)
        except ValueError:
            return None

    def get_output_power(self):
        """?P – Gemessene Output Power in W als Float oder None."""
        resp = self.send_command("?P")
        if resp is None:
            return None
        text = resp
        if text.upper().startswith("?P"):
            text = text[2:].strip()
        try:
            return float(text)
        except ValueError:
            return None


class FaultDialog(QtWidgets.QDialog):
    """
    Dialog, der nach dem Keystatus die Faults zeigt und bei Fault 5
    automatisch in die LBO-Wartephase geht.

    Ablauf:
      - Anzeige der aktuellen Fault-Liste
      - Button "Refresh" aktualisiert die Liste
      - Sobald nur noch Fault 5 vorhanden ist:
          * LBO set & measured Temp werden jede Sekunde gelesen
          * Wenn |set - measured| <= 5°C:
                - Faults werden erneut geprüft
                - Wenn keine Faults mehr: Laser einschalten und Dialog schließen
    """

    def __init__(self, laser: LaserConnection, parent=None):
        super().__init__(parent)
        self.laser = laser

        self.setWindowTitle("Laser Faults / LBO Warm-up")
        self.setModal(True)

        self.lbo_tolerance = 5.0  # ±5°C
        self.lbo_timer = QtCore.QTimer(self)
        self.lbo_timer.setInterval(1000)  # 1 s
        self.lbo_timer.timeout.connect(self.update_lbo_temperatures)

        self._build_ui()
        self.refresh_faults()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        self.info_label = QtWidgets.QLabel(
            "Fault list from the laser controller.\n"
            "Fix faults on the hardware and press 'Refresh'."
        )
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.list_widget = QtWidgets.QListWidget()
        layout.addWidget(self.list_widget)

        # LBO-Temperatur-Block (anfangs versteckt)
        self.lbo_group = QtWidgets.QGroupBox("LBO temperature lock")
        lbo_layout = QtWidgets.QFormLayout()
        self.lbo_set_label = QtWidgets.QLabel("--- °C")
        self.lbo_meas_label = QtWidgets.QLabel("--- °C")
        self.lbo_diff_label = QtWidgets.QLabel("--- °C")
        lbo_layout.addRow("Set temperature:", self.lbo_set_label)
        lbo_layout.addRow("Measured temperature:", self.lbo_meas_label)
        lbo_layout.addRow("Difference:", self.lbo_diff_label)
        self.lbo_group.setLayout(lbo_layout)
        self.lbo_group.setVisible(False)
        layout.addWidget(self.lbo_group)

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_faults)

        self.exit_button = QtWidgets.QPushButton("Cancel Startup")
        self.exit_button.clicked.connect(self.reject)

        button_layout.addStretch()
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.exit_button)
        layout.addLayout(button_layout)

    # ------------ Fault-Handling ---------------- #

    def refresh_faults(self):
        """?F lesen, Liste aktualisieren und ggf. LBO-Monitor starten."""
        codes, raw_text = self.laser.get_fault_codes()
        self.list_widget.clear()

        if codes is None:
            self.list_widget.addItem("No response from laser while reading faults.")
            self.info_label.setText("No response from laser while reading faults.")
            self.stop_lbo_monitor()
            self.lbo_group.setVisible(False)
            return

        if not codes:
            # Keine Faults: wir können mit dem Start fortfahren.
            self.list_widget.addItem("No active faults (System OK).")
            self.info_label.setText("No active faults. Continuing startup.")
            self.stop_lbo_monitor()
            self.lbo_group.setVisible(False)
            self.accept()
            return

        # Faults anzeigen
        for line in self.laser.describe_fault_codes(codes):
            self.list_widget.addItem(line)

        # Nur Fault Code 5 -> LBO-Wartephase
        if set(codes) == {5}:
            self.info_label.setText(
                "Only fault 5 (LBO not locked at set temperature) is present.\n"
                "Waiting for LBO temperature to reach the setpoint..."
            )
            self.refresh_button.setEnabled(False)
            self.lbo_group.setVisible(True)
            self.start_lbo_monitor()
        else:
            self.info_label.setText(
                "Faults are present. Fix them on the laser and press 'Refresh'."
            )
            self.refresh_button.setEnabled(True)
            self.lbo_group.setVisible(False)
            self.stop_lbo_monitor()

    def start_lbo_monitor(self):
        if not self.lbo_timer.isActive():
            self.update_lbo_temperatures()  # Sofort einmal auslesen
            self.lbo_timer.start()

    def stop_lbo_monitor(self):
        if self.lbo_timer.isActive():
            self.lbo_timer.stop()

    def update_lbo_temperatures(self):
        """Jede Sekunde: LBO set/measured auslesen und vergleichen."""
        set_temp, meas_temp = self.laser.get_lbo_temperatures()

        if set_temp is None:
            self.lbo_set_label.setText("--- °C")
        else:
            self.lbo_set_label.setText(f"{set_temp:.2f} °C")

        if meas_temp is None:
            self.lbo_meas_label.setText("--- °C")
        else:
            self.lbo_meas_label.setText(f"{meas_temp:.2f} °C")

        if set_temp is None or meas_temp is None:
            self.lbo_diff_label.setText("--- °C")
            return

        diff = meas_temp - set_temp
        self.lbo_diff_label.setText(f"{diff:+.2f} °C")

        # Toleranz-Kriterium
        if abs(diff) <= self.lbo_tolerance:
            # Innerhalb Toleranz -> Faults erneut prüfen
            self.stop_lbo_monitor()
            self.info_label.setText(
                "LBO temperature is within tolerance. Checking fault status..."
            )

            codes, raw_text = self.laser.get_fault_codes()
            self.list_widget.clear()

            if codes is None:
                self.list_widget.addItem(
                    "No response from laser while checking faults."
                )
                self.refresh_button.setEnabled(True)
                self.lbo_group.setVisible(False)
                return

            if not codes:
                self.list_widget.addItem("No active faults (System OK).")
                # Laser einschalten und Dialog schließen
                self.laser.set_laser_on(True)
                self.accept()
            else:
                for line in self.laser.describe_fault_codes(codes):
                    self.list_widget.addItem(line)
                self.info_label.setText(
                    "LBO temperature is OK, but faults are still present.\n"
                    "Fix them on the laser and press 'Refresh'."
                )
                self.refresh_button.setEnabled(True)
                self.lbo_group.setVisible(False)


class LaserWindow(QtWidgets.QMainWindow):
    """
    Laser-GUI:

      - Fault-Status (alle 10 s abgefragt)
      - Eingabefeld für gewünschte Leistung
      - 'Set'-Button sendet P=..., danach wird ?P gelesen und angezeigt

    Die komplette Start-Sequenz (Connect, Keyswitch, Faults, LBO-Warmup)
    wird durch run_startup_sequence() erledigt.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Verdi V18 Minimal Controller")
        self.setFixedSize(800, 400)

        self.laser = LaserConnection(LASER_HOST, LASER_PORT, timeout=1.0)

        # >>> NEU: Cache für Logging <<<
        self.last_set_power = None      # in W
        self.last_output_power = None   # in W

        self._build_ui()

        self.fault_timer = QtCore.QTimer(self)
        self.fault_timer.setInterval(10000)  # 10 s
        self.fault_timer.timeout.connect(self.update_fault_status)

    def _build_ui(self):
        central = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(central)

        # Status-Gruppe
        status_group = QtWidgets.QGroupBox("Status")
        status_layout = QtWidgets.QFormLayout()
        self.fault_status_label = QtWidgets.QLabel("Not yet read")
        status_layout.addRow("Fault status:", self.fault_status_label)
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)

        # Power + Shutter Control
        power_group = QtWidgets.QGroupBox("Output power & shutter control")
        power_layout = QtWidgets.QGridLayout()

        # gewünschte Leistung
        self.power_spinbox = QtWidgets.QDoubleSpinBox()
        self.power_spinbox.setRange(0.0, 18.0)  # Verdi V18 typischer Bereich
        self.power_spinbox.setDecimals(4)
        self.power_spinbox.setSingleStep(0.1)
        self.power_spinbox.setSuffix(" W")

        self.set_power_button = QtWidgets.QPushButton("Set")
        self.set_power_button.clicked.connect(self.on_set_power_clicked)

        # gemessene Leistung
        self.output_power_label = QtWidgets.QLabel("--- W")

        # Shutter-Steuerung
        self.shutter_checkbox = QtWidgets.QCheckBox("Open")
        self.shutter_checkbox.stateChanged.connect(self.on_shutter_toggled)

        # Layout
        power_layout.addWidget(QtWidgets.QLabel("Requested power:"), 0, 0)
        power_layout.addWidget(self.power_spinbox, 0, 1)
        power_layout.addWidget(self.set_power_button, 0, 2)

        power_layout.addWidget(QtWidgets.QLabel("Output power (measured):"), 1, 0)
        power_layout.addWidget(self.output_power_label, 1, 1)

        power_layout.addWidget(QtWidgets.QLabel("Shutter:"), 2, 0)
        power_layout.addWidget(self.shutter_checkbox, 2, 1)

        power_group.setLayout(power_layout)
        main_layout.addWidget(power_group)

        main_layout.addStretch()
        self.setCentralWidget(central)

    # ------------ Startup-Sequenz ---------------- #

    def run_startup_sequence(self) -> bool:
        """
        Wird vor dem Anzeigen der GUI aufgerufen.

        Schritte:
          1. TCP verbinden, sonst Popup "Laser is not connected" und False.
          2. Keyswitch Status prüfen; falls aus:
                 Popup "Enable Keyswitch" mit OK/Cancel Schleife.
          3. FaultDialog -> Fault-Handling, LBO-Warmup, Laser einschalten.
        """
        # 1. Verbindung aufbauen
        try:
            self.laser.connect()
        except Exception:
            QtWidgets.QMessageBox.critical(
                self,
                "Connection error",
                "Laser is not connected",
            )
            return False

        # 2. Keyswitch-Schleife
        while True:
            ks = self.laser.get_keyswitch_enabled()
            if ks is True:
                break

            msg_box = QtWidgets.QMessageBox(self)
            msg_box.setIcon(QtWidgets.QMessageBox.Warning)
            msg_box.setWindowTitle("Enable Keyswitch")
            msg_box.setText("Enable Keyswitch")
            msg_box.setStandardButtons(
                QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel
            )
            result = msg_box.exec_()
            if result == QtWidgets.QMessageBox.Cancel:
                return False
            # bei OK: erneut prüfen

        # 3. Faults-Dialog inkl. LBO-Warmup und Laser-Einschalten
        fault_dialog = FaultDialog(self.laser, self)
        result = fault_dialog.exec_()
        if result != QtWidgets.QDialog.Accepted:
            return False

        # Hier angekommen: Faults ok und Laser ist eingeschaltet.
        return True

    # ------------ Laufender Betrieb ---------------- #

    def start_status_timer(self):
        self.fault_timer.start()
        self.update_fault_status()

    def update_fault_status(self):
        codes, raw_text = self.laser.get_fault_codes()
        if codes is None:
            self.fault_status_label.setText("No response from laser")
        elif not codes:
            self.fault_status_label.setText("System OK")
        else:
            desc_lines = self.laser.describe_fault_codes(codes)
            self.fault_status_label.setText("; ".join(desc_lines))

    def on_set_power_clicked(self):
        value = self.power_spinbox.value()
        # Sollwert setzen
        self.laser.set_power(value)
        # Gemessene Leistung zurücklesen
        measured = self.laser.get_output_power()
        if measured is None:
            self.output_power_label.setText("No response")
            # >>> NEU: Cache konsistent halten <<<
            self.last_output_power = None
        else:
            self.output_power_label.setText(f"{measured:.3f} W")
            # >>> NEU: Cache aktualisieren <<<
            self.last_output_power = float(measured)

        # >>> NEU: Set-Power immer cachen <<<
        self.last_set_power = float(value)




    def get_logging_powers(self):
        """
        Für das zentrale Logging:
        Gibt (set_power_W, output_power_W) zurück.

        - Wenn wir bereits gecachte Werte haben, werden sie verwendet.
        - Sonst wird einmal beim Laser nachgefragt.
        - Kann (None, None) zurückgeben, wenn keine Verbindung/Antwort.
        """
        set_p = self.last_set_power
        out_p = self.last_output_power

        # Falls noch nicht gesetzt, einmal vom Laser holen (falls verbunden)
        if set_p is None:
            try:
                set_p = self.laser.get_set_power()
            except Exception:
                set_p = None

        if out_p is None:
            try:
                out_p = self.laser.get_output_power()
            except Exception:
                out_p = None

        return set_p, out_p



    

    def on_shutter_toggled(self, state):
        open_ = (state == QtCore.Qt.Checked)
        self.laser.set_shutter_open(open_)

    # ------------ Cleanup ---------------- #

    def closeEvent(self, event):
        self.fault_timer.stop()
        self.laser.close()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    window = LaserWindow()
    # komplette Startprozedur durchlaufen
    if not window.run_startup_sequence():
        window.laser.close()
        sys.exit(0)

    # wenn alles OK ist: Haupt-GUI anzeigen und Fault-Monitor starten
    window.show()
    window.start_status_timer()
    sys.exit(app.exec_())
