# Leybold GRAPHIX Dual-TCP + OPC UA + MQTT Pressure Control (mbar)
# Abgespeckte Version:
# - Feste IP/Ports, festes Polling-Intervall (1000 ms)
# - Device A: "Ion Cooler Graphix"
#       A1 -> INJ
#       A2 -> RFQ
#       A3 -> INJ Ref
# - Device B: "ESA Graphix"
#       B1 -> ESA
# - PLC Vac Gruppe:
#       Vac 1 -> OP1 (Thyracont über OPC UA)
#       Vac 2 -> OP2 (Thyracont über OPC UA)
# - Plot mit 2 Y-Achsen, 6 Signale:
#       linke Achse:  INJ (A1), RFQ (A2)
#       rechte Achse: INJ Ref (A3), ESA (B1), Vac 1 (OP1), Vac 2 (OP2)
# - GUI minimalisiert:
#       - Oben: Start, Stop, Enable logging + Pfad in einer Zeile
#       - Links oben: PLC Vac (Vac 1, Vac 2), darunter ESA Graphix (ESA)
#       - Rechts oben: Ion Cooler Graphix
#       - MQTT-Status + Controls nebeneinander
#
# Requirements:
#   pip install pyqt5 matplotlib opcua paho-mqtt

import socket
import re
import math
import datetime
import time
from functools import partial
from collections import deque

from PyQt5 import QtCore, QtGui, QtWidgets
from opcua import Client
import paho.mqtt.client as mqtt

# --- Matplotlib (embedded) ---
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates

# === GRAPHIX Connection defaults ===
DEVICE_A_IP = "192.168.0.15"   # Ion Cooler Graphix
DEVICE_A_PORT = 100

DEVICE_B_IP = "192.168.0.16"   # ESA Graphix
DEVICE_B_PORT = 100

POLL_MS = 1000            # polling interval in ms

SO = bytes([0x0E])       # Write (unused here)
SI = bytes([0x0F])       # Read
EOT = bytes([0x04])      # End of Transmission

# === OPC UA settings (Thyracont über S7) ===
OPC_UA_URL = (
    "opc.tcp://DESKTOP-UH9J072:4980/"
    "Softing_dataFEED_OPC_Suite_Configuration2"
)
NODE_VAK1 = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Vak1"
NODE_VAK2 = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Vak2"
OPC_UPDATE_MS = 1000

# PLC-Scaling zurückrechnen
PLC_TO_VOLT = 100.01446968500767

def plc_to_voltage(cal_val: float) -> float:
    """Wandelt In_Cal_VakX zurück in Sensorspannung U [V]."""
    if cal_val is None:
        return float("nan")
    try:
        return (float(cal_val) - 1e-8) / PLC_TO_VOLT
    except (TypeError, ValueError):
        return float("nan")

# Thyracont-Kennlinie
V_MIN, V_MAX = 1.8, 8.6  # spezifizierter Bereich

def voltage_to_mbar(u: float) -> float:
    """Thyracont VSM72MV: V = 0.6*log10(p) + 6.8 -> p [mbar]."""
    if u is None or math.isnan(u):
        return float("nan")
    if u < V_MIN:
        u = V_MIN
    elif u > V_MAX:
        u = V_MAX
    return 10 ** ((u - 6.8) / 0.6)

# Offset nur für OPC-Kanal 2
CH2_OFFSET = 0.245

# === Kanal-Namen ===
# A1,A2,A3 = Ion Cooler (INJ, RFQ, INJ Ref)
# B1       = ESA
# OP1,OP2  = Vac 1, Vac 2 (Thyracont über OPC UA)
GRAPHIX_KEYS = ["A1", "A2", "A3", "B1"]
OPCUA_KEYS = ["OP1", "OP2"]
ALL_KEYS = GRAPHIX_KEYS + OPCUA_KEYS

# Achsen-Zuordnung
LEFT_Y_KEYS = ["A1", "A2"]              # INJ, RFQ
RIGHT_Y_KEYS = ["A3", "B1", "OP1", "OP2"]

# Anzeigenamen für GUI & Legende
DISPLAY_NAMES = {
    "A1": "INJ",
    "A2": "RFQ",
    "A3": "INJ Ref",
    "B1": "ESA",
    "OP1": "Vac 1",
    "OP2": "Vac 2",
}

# Feste, gut unterscheidbare Farben
COLOR_MAP = {
    "A1": "#1f77b4",   # blau
    "A2": "#ff7f0e",   # orange
    "A3": "#2ca02c",   # grün
    "B1": "#d62728",   # rot
    "OP1": "#9467bd",  # lila
    "OP2": "#000000",  # schwarz
}

# ---- GRAPHIX Protocol helpers ----
def leybold_crc(payload: bytes) -> bytes:
    s = sum(payload) % 256
    c = 255 - s
    if c < 32:
        c += 32
    return bytes([c])

def build_read(group: int, param: int) -> bytes:
    body = f"{group};{param}".encode("ascii")
    payload = SI + body
    return payload + leybold_crc(payload) + EOT

def parse_ack_value(resp: bytes) -> str:
    if not resp:
        return ""
    if resp.endswith(EOT):
        resp = resp[:-1]
    if len(resp) >= 1:
        resp = resp[:-1]
    try:
        idx = resp.index(b"\x06") + 1
        val = resp[idx:]
    except ValueError:
        val = resp
    return val.decode("ascii", errors="ignore").strip()

# --- Unit conversion -> mbar ---
def to_mbar(value_with_unit: str):
    m = re.search(r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?:\s*([A-Za-z]+))?", value_with_unit)
    if not m:
        return None, None
    val = float(m.group(1))
    unit = (m.group(2) or "").lower()

    if unit in ("mbar", "mbar."):
        return val, "mbar"
    if unit in ("pa", "pa."):
        return val / 100.0, "mbar"     # 1 Pa = 0.01 mbar
    if unit in ("torr", "tor", "mmhg"):
        return val * 1.33322, "mbar"   # 1 Torr ≈ 1.33322 mbar
    return val, "mbar"

def format_sci(val: float):
    if val is None or (isinstance(val, float) and (math.isnan(val) or val == 0)):
        return "0 mbar"
    exp = int(math.floor(math.log10(abs(val))))
    if -2 <= exp <= 2:
        return f"{val:.6g} mbar"
    a = val / (10 ** exp)
    return f"{a:.3g} × 10^{exp} mbar"

def html_sci(text: str) -> str:
    s = text.replace("10^", "10<sup>")
    s = s.replace(" mbar", "</sup> mbar") if "<sup>" in s else s
    return s

# --- TCP Client ---
class TcpClient:
    def __init__(self, host, port, timeout=2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None

    def xfer(self, frame: bytes) -> bytes:
        if not self.sock:
            self.connect()
        self.sock.sendall(frame)
        chunks = []
        while True:
            chunk = self.sock.recv(1024)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\x04" in chunk:  # EOT
                break
        return b"".join(chunks)



class GraphixWorker(QtCore.QObject):
    """
    Pollt die beiden GRAPHIX-Controller (Ion Cooler, ESA) in einem eigenen Thread
    und schickt die Werte per Signal an die GUI.
    """
    resultsReady = QtCore.pyqtSignal(dict, dict)  # (values_mbar, raw_map)
    error = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.clients = {}
        self._poll_items = []
        self._poll_index = 0
        # Nur die echten GRAPHIX-Kanäle
        self._latest_values = {key: None for key in GRAPHIX_KEYS}
        self._latest_raw = {key: "" for key in GRAPHIX_KEYS}
        self._timer = None

    @QtCore.pyqtSlot()
    def start(self):
        """Im Worker-Thread aufgerufen (thread.started -> start)."""
        self._running = True
        self.clients = {}
        self._poll_items = []
        self._poll_index = 0
        self._latest_values = {key: None for key in GRAPHIX_KEYS}
        self._latest_raw = {key: "" for key in GRAPHIX_KEYS}

        # Feste Konfiguration aus den Konstanten
        config = {
            "A": (DEVICE_A_IP, DEVICE_A_PORT),  # Ion Cooler Graphix
            "B": (DEVICE_B_IP, DEVICE_B_PORT),  # ESA Graphix
        }

        for dev in ("A", "B"):
            host, port = config[dev]
            try:
                client = TcpClient(host, port, timeout=2.0)
                client.connect()
                self.clients[dev] = client

                # Device A: Kanäle 1,2,3  (INJ, RFQ, INJ Ref)
                # Device B: nur Kanal 1   (ESA)
                if dev == "A":
                    channels = (1, 2, 3)
                else:
                    channels = (1,)

                for ch in channels:
                    frame = build_read(ch, 29)  # Param 29 = Druck inkl. Einheit
                    key = f"{dev}{ch}"
                    if key in GRAPHIX_KEYS:
                        self._poll_items.append((dev, ch, frame))
            except Exception as e:
                name = "Ion Cooler Graphix" if dev == "A" else "ESA Graphix"
                self.error.emit(f"Connection failed ({name}): {e}")

        if not self._poll_items:
            self.error.emit("No GRAPHIX device configured/connected.")
            return

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll_step)
        self._timer.start()

    @QtCore.pyqtSlot()
    def stop(self):
        """Aus dem GUI-Thread per invokeMethod aufgerufen."""
        self._running = False
        if self._timer is not None:
            self._timer.stop()
        for c in self.clients.values():
            try:
                c.close()
            except Exception:
                pass
        self.clients = {}
        self._poll_items = []

    @QtCore.pyqtSlot()
    def _poll_step(self):
        if not self._running or not self._poll_items:
            return

        dev, ch, frame = self._poll_items[self._poll_index]
        client = self.clients.get(dev)
        if not client:
            self._poll_index = (self._poll_index + 1) % len(self._poll_items)
            return

        key = f"{dev}{ch}"  # "A1", "A2", "A3", "B1"

        try:
            resp = client.xfer(frame)
            raw = parse_ack_value(resp)
            val_mbar, _ = to_mbar(raw)
            self._latest_values[key] = val_mbar
            self._latest_raw[key] = raw
        except Exception as e:
            self._latest_values[key] = None
            self._latest_raw[key] = f"ERROR {e}"
            try:
                client.connect()
            except Exception:
                pass

        # Am Ende einer Poll-Runde kompletten Satz senden
        if self._poll_index == len(self._poll_items) - 1:
            self.resultsReady.emit(dict(self._latest_values), dict(self._latest_raw))

        self._poll_index = (self._poll_index + 1) % len(self._poll_items)




# --- Plotting canvas mit zwei Y-Achsen ---
class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None, max_points=600):
        self.fig = Figure(figsize=(5, 4), tight_layout=True)
        super().__init__(self.fig)
        self.setParent(parent)

        self.ax_left = self.fig.add_subplot(111)
        self.ax_right = self.ax_left.twinx()

        self.max_points = max_points
        self.t = deque(maxlen=max_points)
        self.y = {key: deque(maxlen=max_points) for key in ALL_KEYS}

        self.lines = {}
        self.axis_of = {}

        # Linien auf linker & rechter Achse mit festen Farben
        for key in LEFT_Y_KEYS:
            color = COLOR_MAP.get(key, None)
            label = DISPLAY_NAMES.get(key, key)
            if color:
                (ln,) = self.ax_left.plot([], [], label=label, color=color)
            else:
                (ln,) = self.ax_left.plot([], [], label=label)
            self.lines[key] = ln
            self.axis_of[key] = "L"

        for key in RIGHT_Y_KEYS:
            color = COLOR_MAP.get(key, None)
            label = DISPLAY_NAMES.get(key, key)
            if color:
                (ln,) = self.ax_right.plot([], [], label=label, color=color)
            else:
                (ln,) = self.ax_right.plot([], [], label=label)
            self.lines[key] = ln
            self.axis_of[key] = "R"

        self.plot_enabled = {key: False for key in ALL_KEYS}

        self.ax_left.set_xlabel("Time")
        self.ax_left.set_ylabel("INJ / RFQ (mbar)")
        self.ax_right.set_ylabel("INJ Ref / ESA / Vac 1 / Vac 2 (mbar)")
        self.ax_left.grid(True, which="both", linestyle="--", alpha=0.3)

        self.ax_left.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.ax_left.xaxis.set_major_locator(mdates.AutoDateLocator())

        # gemeinsame Legende
        all_lines = list(self.lines.values())
        labels = [ln.get_label() for ln in all_lines]
        self.ax_left.legend(all_lines, labels, loc="upper right")

    def set_plot_enabled(self, key: str, enabled: bool):
        self.plot_enabled[key] = enabled
        self.redraw()

    def append_point(self, when: datetime.datetime, values: dict):
        self.t.append(when)
        for key in ALL_KEYS:
            self.y[key].append(values.get(key, float("nan")))

    def redraw(self):
        if not self.t:
            return
        x = mdates.date2num(list(self.t))

        for key, ln in self.lines.items():
            if not self.plot_enabled.get(key, False):
                ln.set_data([], [])
            else:
                ln.set_data(x, list(self.y[key]))

        # Autoscale für beide Y-Achsen
        self.ax_left.relim()
        self.ax_left.autoscale_view()

        self.ax_right.relim()
        self.ax_right.autoscale_view()

        # X-Achse begrenzen
        self.ax_left.set_xlim(x[0], x[-1] if len(x) > 1 else x[0] + 1/86400.0)

        self.draw_idle()

# --- MQTT-Client nur für Pressure-Control ---
DEFAULT_MQTT_HOST = "192.168.0.20"
DEFAULT_MQTT_PORT = 1883
DEFAULT_KEEPALIVE = 30
SUB_TOPICS = [
    ("pressure/#", 0),
]

class MqttClient(QtCore.QObject):
    """MQTT-Client in separatem Thread; Events per Qt-Signal."""
    messageReceived = QtCore.pyqtSignal(str, str)
    connectionChanged = QtCore.pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = mqtt.Client(protocol=mqtt.MQTTv311)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._host = DEFAULT_MQTT_HOST
        self._port = DEFAULT_MQTT_PORT
        self._running = False
        self._thread = None

    def configure(self, host: str, port: int):
        self._host = host
        self._port = int(port)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = QtCore.QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run_loop)
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            self._client.disconnect()
        except Exception:
            pass
        if self._thread:
            self._thread.quit()
            self._thread.wait(2000)

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False):
        try:
            self._client.publish(topic, payload=payload, qos=qos, retain=retain)
        except Exception as e:
            self.connectionChanged.emit(False, f"Publish-Fehler: {e}")

    # ---------- intern ----------
    def _run_loop(self):
        try:
            self._client.connect(self._host, self._port, keepalive=DEFAULT_KEEPALIVE)
            for t, qos in SUB_TOPICS:
                self._client.subscribe(t, qos=qos)
            while self._running:
                self._client.loop(timeout=0.1)
                time.sleep(0.05)
        except Exception as e:
            self.connectionChanged.emit(False, f"MQTT-Startfehler: {e}")
            self._running = False

    def _on_connect(self, client, userdata, flags, rc):
        ok = (rc == mqtt.CONNACK_ACCEPTED)
        msg = "verbunden" if ok else f"Connect RC={rc}"
        self.connectionChanged.emit(ok, msg)
        if ok:
            for t, qos in SUB_TOPICS:
                client.subscribe(t, qos=qos)

    def _on_disconnect(self, client, userdata, rc):
        self.connectionChanged.emit(False, "getrennt")

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8", errors="ignore")
        except Exception:
            payload = ""
        self.messageReceived.emit(msg.topic, payload)

# --- GUI ---
class Main(QtWidgets.QWidget):
    staleThresholdMs = 3000  # nach 3 s ohne MQTT-Update -> grau

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ion Cooler / ESA Graphix Monitor")
        self.resize(1100, 750)

        # === Start/Stop + Logging in einer Zeile ===
        self.start = QtWidgets.QPushButton("Start")
        self.stop = QtWidgets.QPushButton("Stop")
        self.stop.setEnabled(False)

        self.logEnable = QtWidgets.QCheckBox("Enable logging (TXT)")
        self.logPathBtn = QtWidgets.QPushButton("Choose file…")
        self.logPathBtn.setEnabled(False)
        self.logPathLbl = QtWidgets.QLabel("—")

        topRow = QtWidgets.QHBoxLayout()
        topRow.addWidget(self.start)
        topRow.addWidget(self.stop)
        topRow.addSpacing(20)
        topRow.addWidget(self.logEnable)
        topRow.addWidget(self.logPathBtn)
        topRow.addWidget(self.logPathLbl, 1)

        # --- Channel labels + Plot-Checkboxen ---
        self.channel_labels = {}
        self.channel_plot_checks = {}

        # Plot
        self.canvas = PlotCanvas(self, max_points=600)

        # === PLC Vac (OPC UA) links oben ===
        plcGB = QtWidgets.QGroupBox("PLC Vac")
        plcLayout = QtWidgets.QGridLayout(plcGB)

        # Vac 1 (OP1)
        lbl_v1 = QtWidgets.QLabel("Vac 1: —")
        f = lbl_v1.font()
        f.setPointSize(18)
        lbl_v1.setFont(f)
        chk_v1 = QtWidgets.QCheckBox("Plot")
        self.channel_labels["OP1"] = lbl_v1
        self.channel_plot_checks["OP1"] = chk_v1
        chk_v1.toggled.connect(lambda state, k="OP1": self.canvas.set_plot_enabled(k, state))
        plcLayout.addWidget(lbl_v1, 0, 0)
        plcLayout.addWidget(chk_v1, 0, 1)

        # Vac 2 (OP2)
        lbl_v2 = QtWidgets.QLabel("Vac 2: —")
        f = lbl_v2.font()
        f.setPointSize(18)
        lbl_v2.setFont(f)
        chk_v2 = QtWidgets.QCheckBox("Plot")
        self.channel_labels["OP2"] = lbl_v2
        self.channel_plot_checks["OP2"] = chk_v2
        chk_v2.toggled.connect(lambda state, k="OP2": self.canvas.set_plot_enabled(k, state))
        plcLayout.addWidget(lbl_v2, 1, 0)
        plcLayout.addWidget(chk_v2, 1, 1)

        # === ESA Graphix (Device B) darunter ===
        esaGB = QtWidgets.QGroupBox("ESA Graphix")
        esaLayout = QtWidgets.QGridLayout(esaGB)

        lbl_esa = QtWidgets.QLabel("ESA: —")
        f = lbl_esa.font()
        f.setPointSize(18)
        lbl_esa.setFont(f)
        chk_esa = QtWidgets.QCheckBox("Plot")
        self.channel_labels["B1"] = lbl_esa
        self.channel_plot_checks["B1"] = chk_esa
        chk_esa.toggled.connect(lambda state, k="B1": self.canvas.set_plot_enabled(k, state))
        esaLayout.addWidget(lbl_esa, 0, 0)
        esaLayout.addWidget(chk_esa, 0, 1)

        # === Ion Cooler Graphix (Device A) rechts ===
        ionGB = QtWidgets.QGroupBox("Ion Cooler Graphix")
        ionLayout = QtWidgets.QGridLayout(ionGB)

        ion_channels = [("A1", "INJ"), ("A2", "RFQ"), ("A3", "INJ Ref")]
        for row, (key, label_text) in enumerate(ion_channels):
            lbl = QtWidgets.QLabel(f"{label_text}: —")
            f = lbl.font()
            f.setPointSize(18)
            lbl.setFont(f)
            chk = QtWidgets.QCheckBox("Plot")
            self.channel_labels[key] = lbl
            self.channel_plot_checks[key] = chk
            chk.toggled.connect(lambda state, k=key: self.canvas.set_plot_enabled(k, state))
            ionLayout.addWidget(lbl, row, 0)
            ionLayout.addWidget(chk, row, 1)

        # === Device-Anordnung: links PLC Vac + ESA, rechts Ion Cooler ===
        leftColWidget = QtWidgets.QWidget()
        leftColLayout = QtWidgets.QVBoxLayout(leftColWidget)
        leftColLayout.setContentsMargins(0, 0, 0, 0)
        leftColLayout.addWidget(plcGB)
        leftColLayout.addWidget(esaGB)

        deviceRow = QtWidgets.QHBoxLayout()
        deviceRow.addWidget(leftColWidget, 1)
        deviceRow.addWidget(ionGB, 1)

        # === MQTT Pressure-Control (Status + Controls nebeneinander) ===
        mqttGB = QtWidgets.QGroupBox("Pressure Control (MQTT, 0–10 V)")
        mqttLayout = QtWidgets.QHBoxLayout(mqttGB)

        self.mqttConnLabel = QtWidgets.QLabel("MQTT: (noch nicht verbunden)")
        self.mqttConnLabel.setStyleSheet("color:#888")

        self.pSet = QtWidgets.QDoubleSpinBox()
        self.pSet.setDecimals(2)
        self.pSet.setRange(0, 10)
        self.pSet.setSingleStep(0.01)
        self.pSet.setKeyboardTracking(False)
        self.pSet.setAccelerated(True)

        self.pSetBtn = QtWidgets.QPushButton("Set Pressure (V)")
        self.pMeasV = QtWidgets.QLabel("-")

        mqttLayout.addWidget(self.mqttConnLabel)
        mqttLayout.addStretch(1)
        mqttLayout.addWidget(QtWidgets.QLabel("Pressure (0–10 V)"))
        mqttLayout.addWidget(self.pSet)
        mqttLayout.addWidget(self.pSetBtn)
        mqttLayout.addWidget(QtWidgets.QLabel("meas_v"))
        mqttLayout.addWidget(self.pMeasV)
        mqttLayout.addStretch(1)

        # --- Main Layout ---
        v = QtWidgets.QVBoxLayout(self)
        v.addLayout(topRow)
        v.addLayout(deviceRow)
        v.addWidget(mqttGB)
        v.addWidget(self.canvas, 1)

        # Timers (Plot + Logging; GRAPHIX läuft im Worker-Thread)
        self.timer_plot = QtCore.QTimer(self)
        self.timer_plot.setInterval(1000)  # redraw every second
        self.timer_plot.timeout.connect(self.canvas.redraw)

        self.timer_log = QtCore.QTimer(self)
        self.timer_log.setInterval(1000)   # write to file once per second
        self.timer_log.timeout.connect(self.write_log_line)

        # Worker-Thread für GRAPHIX
        self.graphix_thread = None
        self.graphix_worker = None

        # latest values (mbar) per ALL_KEYS
        self.latest = {key: None for key in ALL_KEYS}
        self.latest_raw = {key: "" for key in ALL_KEYS}

        # logging state
        self._log_file = None
        self._log_path = None
        self._log_active = False

        # OPC-UA Client
        self.opc_client = None
        self.opc_node1 = None
        self.opc_node2 = None
        self.timer_opc = QtCore.QTimer(self)
        self.timer_opc.timeout.connect(self.opc_update)

        # MQTT Client
        self.mqtt = MqttClient()
        self._mqtt_lastUpdate = {}
        self._staleTimer = QtCore.QTimer(self)
        self._staleTimer.timeout.connect(self._refresh_mqtt_stale)
        self._staleTimer.start(500)

        # Signals
        self.start.clicked.connect(self.on_start)
        self.stop.clicked.connect(self.on_stop)
        self.logEnable.toggled.connect(self.on_toggle_logging)
        self.logPathBtn.clicked.connect(self.choose_log_path)

        # MQTT Signals
        self.pSetBtn.clicked.connect(
            partial(self._mqtt_publish_set, "pressure/cmd/set_v", lambda: self.pSet.value())
        )
        self.pSet.editingFinished.connect(self.pSetBtn.click)

        self.mqtt.messageReceived.connect(self._on_mqtt_msg)
        self.mqtt.connectionChanged.connect(self._on_mqtt_conn_changed)

        # gleich verbinden
        self._mqtt_connect_and_start()

    # ---------- Logging ----------
    def choose_log_path(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Choose log file (TXT)", filter="Text file (*.txt)")
        if path:
            if not path.lower().endswith(".txt"):
                path += ".txt"
            self._log_path = path
            self.logPathLbl.setText(path)

    def on_toggle_logging(self, checked: bool):
        if checked:
            self.logPathBtn.setEnabled(True)
            if not self._log_path:
                self.choose_log_path()
                if not self._log_path:
                    self.logEnable.setChecked(False)
                    return
            ok = QtWidgets.QMessageBox.question(
                self, "Enable logging",
                f"Write measurements to\n\n{self._log_path}\n\nevery second?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            if ok == QtWidgets.QMessageBox.Yes:
                try:
                    self._log_file = open(self._log_path, "a", encoding="utf-8")
                    self._log_file.write("# time (ISO8601Z); channel; value_mbar; pretty; raw\n")
                    self._log_file.flush()
                    self._log_active = True
                    self.timer_log.start()
                except Exception as e:
                    QtWidgets.QMessageBox.critical(self, "Logging failed", str(e))
                    self.logEnable.setChecked(False)
            else:
                self.logEnable.setChecked(False)
        else:
            self.logPathBtn.setEnabled(False)
            self.stop_logging()

    def stop_logging(self):
        self.timer_log.stop()
        self._log_active = False
        try:
            if self._log_file:
                self._log_file.flush()
                self._log_file.close()
        finally:
            self._log_file = None

    def write_log_line(self):
        if not self._log_active or not self._log_file:
            return
        now = datetime.datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        for key in ALL_KEYS:
            val = self.latest.get(key, None)
            raw = self.latest_raw.get(key, "")
            if val is None:
                continue
            pretty = format_sci(val)
            line = f"{now}; {key}; {val:.9g}; {pretty}; raw: {raw}\n"
            self._log_file.write(line)
        self._log_file.flush()


    # ---------- GRAPHIX Worker-Anbindung ----------

    def _stop_graphix_thread(self):
        """Hilfsfunktion, um den Worker-Thread sauber zu beenden."""
        if self.graphix_worker is not None:
            QtCore.QMetaObject.invokeMethod(
                self.graphix_worker,
                "stop",
                QtCore.Qt.QueuedConnection,
            )
        if self.graphix_thread is not None:
            self.graphix_thread.quit()
            self.graphix_thread.wait(2000)
        self.graphix_worker = None
        self.graphix_thread = None

    def on_graphix_results(self, values: dict, raw_map: dict):
        """
        Wird im GUI-Thread aufgerufen, wenn der Worker neue Werte hat.
        values: z.B. {"A1": 1e-3, "A2": ...}
        raw_map: {"A1": "1.0E-3 mbar", ...}
        """
        # interne latest-Maps aktualisieren
        for key, val in values.items():
            if key in GRAPHIX_KEYS:
                self.latest[key] = val
        for key, raw in raw_map.items():
            if key in GRAPHIX_KEYS:
                self.latest_raw[key] = raw

        # Labels für GRAPHIX-Kanäle aktualisieren
        for key in GRAPHIX_KEYS:
            lbl = self.channel_labels.get(key)
            if lbl is None:
                continue
            name = DISPLAY_NAMES.get(key, key)
            val = self.latest.get(key, None)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                lbl.setText(f"{name}: —")
            else:
                lbl.setText(f"{name}: " + html_sci(format_sci(val)))

        # neuen Punkt für den Plot hinzufügen (inkl. OPC-UA Werte)
        now = datetime.datetime.utcnow()
        values_for_plot = {k: self.latest.get(k, float("nan")) for k in ALL_KEYS}
        self.canvas.append_point(now, values_for_plot)

    def on_graphix_error(self, msg: str):
        QtWidgets.QMessageBox.warning(self, "GRAPHIX error", msg)

    # ---------- Start/Stop GRAPHIX/OPC ----------
    def on_start(self):
        # ggf. alten Worker beenden
        self._stop_graphix_thread()

        # neuen Worker-Thread aufsetzen
        self.graphix_thread = QtCore.QThread(self)
        self.graphix_worker = GraphixWorker()
        self.graphix_worker.moveToThread(self.graphix_thread)

        self.graphix_thread.started.connect(self.graphix_worker.start)
        self.graphix_worker.resultsReady.connect(self.on_graphix_results)
        self.graphix_worker.error.connect(self.on_graphix_error)
        self.graphix_thread.finished.connect(self._stop_graphix_thread)

        self.graphix_thread.start()

        # Plot-Timer starten
        self.timer_plot.start()
        self.start.setEnabled(False)
        self.stop.setEnabled(True)

        # OPC UA verbinden & Timer starten
        self.opc_connect()

    def on_stop(self):
        self.timer_plot.stop()
        self.stop_logging()

        # GRAPHIX-Worker stoppen
        self._stop_graphix_thread()

        self.start.setEnabled(True)
        self.stop.setEnabled(False)

        # OPC stoppen
        self.timer_opc.stop()
        if self.opc_client:
            try:
                self.opc_client.disconnect()
            except Exception:
                pass
        self.opc_client = None
        self.opc_node1 = None
        self.opc_node2 = None

    
    # ---------- OPC UA ----------
    def opc_connect(self):
        try:
            self.opc_client = Client(OPC_UA_URL)
            self.opc_client.session_timeout = 10000
            self.opc_client.connect()
            self.opc_node1 = self.opc_client.get_node(NODE_VAK1)
            self.opc_node2 = self.opc_client.get_node(NODE_VAK2)
            self.timer_opc.start(OPC_UPDATE_MS)
        except Exception:
            self.opc_client = None
            self.opc_node1 = None
            self.opc_node2 = None

    def opc_safe_read(self, node):
        if self.opc_client is None or node is None:
            return None
        try:
            return node.get_value()
        except Exception:
            return None

    def opc_update(self):
        if self.opc_client is None:
            self.opc_connect()
            if self.opc_client is None:
                return

        cal1 = self.opc_safe_read(self.opc_node1)
        cal2 = self.opc_safe_read(self.opc_node2)

        u1 = plc_to_voltage(cal1)
        u2 = plc_to_voltage(cal2)

        if not math.isnan(u2):
            u2_corr = u2 + CH2_OFFSET
        else:
            u2_corr = float("nan")

        p1 = voltage_to_mbar(u1)
        p2 = voltage_to_mbar(u2_corr)

        # in mbar speichern (werden beim nächsten GRAPHIX-Zyklus mit geplottet)
        self.latest["OP1"] = p1
        self.latest_raw["OP1"] = f"PLC1={cal1},U1={u1}"
        self.latest["OP2"] = p2
        self.latest_raw["OP2"] = f"PLC2={cal2},U2corr={u2_corr}"

        # Anzeigen
        for key, p in (("OP1", p1), ("OP2", p2)):
            lbl = self.channel_labels.get(key)
            if lbl is None:
                continue
            name = DISPLAY_NAMES.get(key, key)
            if p is None or (isinstance(p, float) and math.isnan(p)):
                lbl.setText(f"{name}: —")
            else:
                lbl.setText(f"{name}: " + html_sci(format_sci(p)))

    # ---------- MQTT-Helper ----------
    def _fmt2(self, text: str) -> str:
        try:
            v = float(text.replace(",", "."))
            return f"{v:.2f}"
        except Exception:
            return text

    def _mqtt_connect_and_start(self):
        self.mqtt.configure(DEFAULT_MQTT_HOST, DEFAULT_MQTT_PORT)
        self.mqtt.start()

    def _on_mqtt_conn_changed(self, ok: bool, text: str):
        self.mqttConnLabel.setText(f"MQTT: {text}")
        self.mqttConnLabel.setStyleSheet("color:#0a0" if ok else "color:#a00")

    def _on_mqtt_msg(self, topic: str, payload: str):
        now_ms = int(time.time() * 1000)
        self._mqtt_lastUpdate[topic] = now_ms

        if topic == "pressure/meas_v":
            self.pMeasV.setText(self._fmt2(payload))
        elif topic == "pressure/set_v":
            self._try_set_spin(self.pSet, payload, 10.0, decimals=2)

    def _try_set_spin(self,
                      spin: QtWidgets.QDoubleSpinBox,
                      text: str,
                      maxv: float,
                      decimals: int = 2):
        try:
            val = float(text.replace(",", "."))
        except Exception:
            return
        val = max(0.0, min(round(val, decimals), maxv))
        if not spin.hasFocus():
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)

    def _mqtt_publish_set(self, topic: str, getter):
        val = getter()
        payload = f"{val:.2f}".replace(",", ".")
        self.mqtt.publish(topic, payload)

    def _refresh_mqtt_stale(self):
        now_ms = int(time.time() * 1000)

        def mark(label: QtWidgets.QLabel, topics):
            latest = max([self._mqtt_lastUpdate.get(t, 0) for t in topics], default=0)
            if latest and (now_ms - latest) < self.staleThresholdMs:
                label.setStyleSheet("color:#000")
            else:
                label.setStyleSheet("color:#888")

        mark(self.pMeasV, ["pressure/meas_v"])

    # ---------- Close event ----------
    def closeEvent(self, event):
        try:
            self.on_stop()
            self.mqtt.stop()
        finally:
            event.accept()

if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec_())
