import sys
import os
import time
import socket
from datetime import datetime

import numpy as np

import math

from opcua import Client
from opcua.ua import VariantType

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QGroupBox, QFormLayout, QFileDialog, QComboBox,
    QSlider, QFrame, QDoubleSpinBox, QSpinBox,
    QDialog, QDialogButtonBox, QMessageBox, QTabWidget,
    QLineEdit, QProgressBar
)

from PyQt5.QtGui import QTextCursor


import paho.mqtt.client as mqtt

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Optional SSH (wie in COMBI7)
try:
    import paramiko
except ImportError:
    paramiko = None


# ============================================================
# CONFIGURATION
# ============================================================

# Function generator (SRS DS345)
FG_IP_DEFAULT = "192.168.0.11"
FG_PORT_DEFAULT = 100

# Oscilloscope (GDS-1074B)
SCOPE_IP_DEFAULT = "192.168.0.14"
SCOPE_PORT_DEFAULT = 1024
RECORD_LENGTH = 1000  # slower but robust

# RFQ geometry
R0_MM = 5.232  # r0 = 5.232 mm

# Constants
u_to_kg = 1.66053906660e-27
e_charge = 1.602176634e-19

# ============================================================
# EMBEDDED RESONANCE DATA (from meas.txt)
# Frequency in MHz, C in pF, L in µH
# ============================================================

RESONANCE_PRESETS = [
    {"f_MHz": 0.5, "C_pF": 1100.0, "L_uH": 447.0},
    {"f_MHz": 0.6, "C_pF": 1100.0, "L_uH": 308.75},
    {"f_MHz": 0.7, "C_pF": 1100.0, "L_uH": 214.75},
    {"f_MHz": 0.8, "C_pF": 1300.0, "L_uH": 162.75},
    {"f_MHz": 0.9, "C_pF": 1300.0, "L_uH": 126.25},
    {"f_MHz": 1.0, "C_pF": 1300.0, "L_uH": 101.5},
    {"f_MHz": 1.1, "C_pF": 1300.0, "L_uH": 84.0},
    {"f_MHz": 1.2, "C_pF": 1300.0, "L_uH": 70.5},
    {"f_MHz": 1.3, "C_pF": 1300.0, "L_uH": 60.0},
    {"f_MHz": 1.4, "C_pF": 1300.0, "L_uH": 51.25},
    {"f_MHz": 1.5, "C_pF": 1300.0, "L_uH": 45.5},
    {"f_MHz": 1.6, "C_pF": 1300.0, "L_uH": 39.5},
    {"f_MHz": 1.7, "C_pF": 1300.0, "L_uH": 34.5},
    {"f_MHz": 1.8, "C_pF": 1300.0, "L_uH": 31.25},
    {"f_MHz": 1.9, "C_pF": 1300.0, "L_uH": 28.0},
    {"f_MHz": 2.0, "C_pF": 1300.0, "L_uH": 25.25},
    {"f_MHz": 2.1, "C_pF": 1300.0, "L_uH": 22.25},
    {"f_MHz": 2.2, "C_pF": 1300.0, "L_uH": 20.25},
    {"f_MHz": 2.3, "C_pF": 1300.0, "L_uH": 18.25},
    {"f_MHz": 2.4, "C_pF": 1300.0, "L_uH": 16.75},
    {"f_MHz": 2.5, "C_pF": 1500.0, "L_uH": 15.75},
    {"f_MHz": 2.6, "C_pF": 1700.0, "L_uH": 14.5},
    {"f_MHz": 2.7, "C_pF": 1700.0, "L_uH": 13.5},
    {"f_MHz": 2.8, "C_pF": 1700.0, "L_uH": 12.5},
    {"f_MHz": 2.9, "C_pF": 1700.0, "L_uH": 11.5},
    {"f_MHz": 3.0, "C_pF": 1500.0, "L_uH": 10.75},
]

# ============================================================
# DS345 CLIENT
# ============================================================

class DS345Client:
    """
    TCP client for DS345, persistent connection.
    Closely follows your original working code.
    """
    def __init__(self, ip=FG_IP_DEFAULT, port=FG_PORT_DEFAULT):
        self.ip = ip
        self.port = port
        self.sock = None

    def set_target(self, ip, port):
        self.close()
        self.ip = ip
        self.port = port

    def ensure_connection(self):
        if self.sock is None:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect((self.ip, self.port))
                self.sock = s
                return True
            except Exception as e:
                print("DS345 connection error:", e)
                self.sock = None
                return False
        return True

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except:
                pass
        self.sock = None

    def send_command(self, cmd):
        """
        cmd: SCPI string, without '\n'.
        If "?" is in cmd: return response.
        Else: return True on success, None on error.
        """
        if not self.ensure_connection():
            return None

        try:
            self.sock.sendall((cmd + "\n").encode("ascii"))

            if "?" in cmd:
                response = self.sock.recv(1024)

                # Try 4-byte binary float
                if len(response) == 4:
                    import struct
                    try:
                        return struct.unpack(">f", response)[0]
                    except struct.error:
                        pass

                # Fallback ASCII
                try:
                    return response.decode("ascii", errors="ignore").strip()
                except UnicodeDecodeError:
                    return None

            return True
        except Exception as e:
            print("DS345 command error:", e)
            self.close()
            return None

    def get_frequency(self):
        resp = self.send_command("FREQ?")
        try:
            return float(resp)
        except (TypeError, ValueError):
            return float("nan")

    def set_frequency(self, f_hz):
        return self.send_command(f"FREQ {f_hz}")

    def get_amplitude(self):
        resp = self.send_command("AMPL?")
        if resp is None:
            return float("nan")
        try:
            if isinstance(resp, (int, float)):
                return float(resp)
            return float(str(resp).replace("VP", "").strip())
        except ValueError:
            return float("nan")

    def set_amplitude(self, vpp):
        vpp = max(0.0, min(10.0, vpp))
        return self.send_command(f"AMPL {vpp}VP")


# ============================================================
# SCOPE CLIENT (GDS-1074B)
# ============================================================

class ScopeClient:
    """GDS-1074B waveform reader for CH2 & CH3 (slow but stable)."""

    def __init__(self, ip=SCOPE_IP_DEFAULT, port=SCOPE_PORT_DEFAULT, record_len=RECORD_LENGTH):
        self.ip = ip
        self.port = port
        self.record_len = record_len

    def set_target(self, ip, port):
        self.ip = ip
        self.port = port

    def _send_cmd(self, sock, cmd: str):
        sock.sendall((cmd.strip() + "\n").encode("ascii"))

    def _recv_all(self, sock, timeout=2.0) -> bytes:
        sock.settimeout(timeout)
        chunks = []
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
        except socket.timeout:
            pass
        return b"".join(chunks)

    def _get_volts_for_channel_single_connection(self, ch: int):
        """
        Separate TCP connection per channel, robust.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.ip, self.port))
            self._send_cmd(s, f":ACQuire:RECOrdlength {self.record_len}")
            self._send_cmd(s, f":ACQuire{ch}:MEMory?")
            raw = self._recv_all(s, timeout=2.0)

        marker = b"Waveform Data;"
        idx = raw.find(marker)
        if idx == -1:
            raise RuntimeError(f"'Waveform Data;' not found (CH{ch})")

        header_str = raw[:idx].decode("ascii", errors="ignore")
        block = raw[idx + len(marker):].lstrip()

        header = {}
        for part in header_str.split(";"):
            part = part.strip()
            if not part:
                continue
            if "," in part:
                key, val = part.split(",", 1)
                header[key.strip()] = val.strip()

        vscale = float(header.get("Vertical Scale", "1.0"))  # V/div

        if not block.startswith(b"#"):
            raise RuntimeError(f"No SCPI block (CH{ch})")

        ndigits = int(chr(block[1]))
        nbytes = int(block[2:2 + ndigits].decode())
        data_bytes = block[2 + ndigits:2 + ndigits + nbytes]

        raw_vals = np.frombuffer(data_bytes, dtype=">i2")
        volts = (raw_vals / 25.0) * vscale
        return volts

    def measure_ch2_ch3(self):
        """
        Reads CH2 and CH3 sequentially (separate connections).
        Returns (vpp2, vpp3, wave2, wave3).
        """
        wave2 = self._get_volts_for_channel_single_connection(2)
        wave3 = self._get_volts_for_channel_single_connection(3)

        vpp2 = float(wave2.max() - wave2.min())
        vpp3 = float(wave3.max() - wave3.min())
        return vpp2, vpp3, wave2, wave3


# ============================================================
# LC VIA SSH
# ============================================================

class LCSSHClient:
    """
    Controls rc_cmd_derin.py on the Pi via SSH.
    """

    def __init__(self):
        self.client = None
        self.host = ""
        self.username = ""
        self.password = ""
        self.workdir = "/home/pi/Desktop/Python"
        self.script = "python3 rc_cmd_derin.py"

    def connect(self, host, username, password, port=22, timeout=5.0):
        if paramiko is None:
            raise RuntimeError("paramiko is not installed (pip install paramiko)")

        host = host.strip()
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]

        if self.client:
            try:
                self.client.close()
            except:
                pass
            self.client = None

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            host,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
        )
        self.host = host
        self.username = username
        self.password = password

    def is_connected(self):
        return self.client is not None

    def close(self):
        if self.client:
            try:
                self.client.close()
            except:
                pass
        self.client = None

    def _run_rc_cmd(self, args, timeout=5.0):
        if not self.client:
            raise RuntimeError("Not connected to Pi")

        cmd = f"cd {self.workdir} && {self.script} " + " ".join(args)
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="ignore").strip()
        err = stderr.read().decode("utf-8", errors="ignore").strip()
        return out, err

    def set_value(self, name, value):
        """
        name: "C" or "L"
        value: float (C in pF, L in µH)
        """
        return self._run_rc_cmd(["set", name, str(value)])

    def get_value(self, name):
        out, err = self._run_rc_cmd(["get", name])
        if err:
            return float("nan"), err
        try:
            val = float(out)
            return val, ""
        except ValueError:
            return float("nan"), f"Parsing error: {out!r}"


# ============================================================
# PHYSICS: MATHIEU & LC
# ============================================================

def compute_q(m_u, z, r0_mm, f_hz, Vpp_FG, gain):
    """
    q_u = 4 q V0 / (m r0^2 omega^2)
    V0 = (G * Vpp_FG) / 2
    """
    if f_hz <= 0 or m_u <= 0 or gain <= 0:
        return float("nan")

    m = m_u * u_to_kg
    Q = abs(z) * e_charge
    r0 = r0_mm / 1000.0
    Vpp_RFQ = gain * Vpp_FG
    V0 = Vpp_RFQ / 2.0
    omega = 2.0 * math.pi * f_hz

    q_u = 4.0 * Q * V0 / (m * (r0 ** 2) * (omega ** 2))
    return q_u


def compute_freq_for_q(m_u, z, r0_mm, q_target, Vpp_FG, gain):
    """
    Frequency from target q:
    q_u = 2 Q G Vpp_FG / (m r0^2 omega^2)
    -> omega^2 = 2 Q G Vpp_FG / (m r0^2 q_u)
    -> f = omega / (2 pi)
    """
    if q_target <= 0 or m_u <= 0 or Vpp_FG <= 0 or gain <= 0:
        return float("nan")

    m = m_u * u_to_kg
    Q = abs(z) * e_charge
    r0 = r0_mm / 1000.0
    Vpp_RFQ = gain * Vpp_FG

    omega2 = 2.0 * Q * Vpp_RFQ / (m * r0**2 * q_target)
    if omega2 <= 0:
        return float("nan")
    omega = math.sqrt(omega2)
    f = omega / (2.0 * math.pi)
    return f


def L_from_f_C(f_hz, C_F):
    if f_hz <= 0 or C_F <= 0:
        return float("nan")
    return 1.0 / ((2.0 * math.pi * f_hz) ** 2 * C_F)


def C_from_f_L(f_hz, L_H):
    if f_hz <= 0 or L_H <= 0:
        return float("nan")
    return 1.0 / ((2.0 * math.pi * f_hz) ** 2 * L_H)



# ============================================================
# GUI
# ============================================================

class RFQUnifiedGUI(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RFQ – Mathieu, FG, LC (SSH), Scope + L-sweep")
        self.resize(1250, 800)

        self.fg = DS345Client()
        self.scope = ScopeClient()
        self.lc = LCSSHClient()

        # Use embedded resonance presets
        self.resonance_presets = RESONANCE_PRESETS

        self._build_ui()

        # FG update timer (only reads labels, does NOT overwrite inputs)
        self.timer_fg = QtCore.QTimer(self)
        self.timer_fg.timeout.connect(self.update_fg_display)
        self.timer_fg.start(2000)

    # ---------- UI building ----------

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)

        # Middle area: split left/right
        middle_layout = QtWidgets.QHBoxLayout()
        main_layout.addLayout(middle_layout)

        # LEFT COLUMN
        left_col = QtWidgets.QVBoxLayout()
        middle_layout.addLayout(left_col, stretch=3)

        # Top of left column: Mathieu + FG in a row
        left_top_row = QtWidgets.QHBoxLayout()
        left_col.addLayout(left_top_row)

        left_top_row.addWidget(self._build_mathieu_group(), stretch=1)
        left_top_row.addWidget(self._build_fg_group(), stretch=1)

        # Below: waveform plot
        left_col.addWidget(self._build_plot_group(), stretch=2)

        # RIGHT COLUMN
        right_col = QtWidgets.QVBoxLayout()
        middle_layout.addLayout(right_col, stretch=2)

        # Top of right column: LC circuit
        right_col.addWidget(self._build_lc_group())

        # Below: oscilloscope control
        right_col.addWidget(self._build_scope_group())

        # Bottom: log across full width
        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        main_layout.addWidget(self.log)

    # ---------- Mathieu group ----------

    def _build_mathieu_group(self):
        group = QtWidgets.QGroupBox("Mathieu calculator & frequency")
        layout = QtWidgets.QFormLayout(group)

        self.edit_mass = QtWidgets.QLineEdit("40.0")
        self.edit_charge = QtWidgets.QLineEdit("1")
        self.label_r0 = QtWidgets.QLabel(f"{R0_MM:.3f} mm (fixed)")

        self.edit_q_target = QtWidgets.QLineEdit("0.3")

        self.spin_amp = QtWidgets.QDoubleSpinBox()
        self.spin_amp.setRange(0.0, 10.0)
        self.spin_amp.setSingleStep(0.1)
        self.spin_amp.setDecimals(2)
        self.spin_amp.setValue(5.0)
        self.spin_amp.setSuffix(" Vpp")

        self.combo_gain = QtWidgets.QComboBox()
        self.combo_gain.addItems(["1 (HF amp off)", "10 (HF amp on)"])
        self.combo_gain.setCurrentIndex(1)

        self.edit_freq = QtWidgets.QLineEdit("200000.0")  # Hz

        btn_q_from_f = QtWidgets.QPushButton("Compute q from f")
        btn_q_from_f.clicked.connect(self.on_q_from_f)

        btn_f_from_q = QtWidgets.QPushButton("Compute f from q")
        btn_f_from_q.clicked.connect(self.on_f_from_q)

        self.lbl_q_result = QtWidgets.QLabel("q = ---")

        layout.addRow("Mass m (u):", self.edit_mass)
        layout.addRow("Charge z:", self.edit_charge)
        layout.addRow("r0:", self.label_r0)
        layout.addRow("Target q:", self.edit_q_target)
        layout.addRow("FG amplitude:", self.spin_amp)
        layout.addRow("HF amp gain:", self.combo_gain)
        layout.addRow("Frequency f (Hz):", self.edit_freq)

        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(btn_q_from_f)
        hl.addWidget(btn_f_from_q)
        layout.addRow(hl)
        layout.addRow("Result:", self.lbl_q_result)

        return group

    def _read_mathieu_params(self):
        try:
            m_u = float(self.edit_mass.text())
            z = int(self.edit_charge.text())
            q_target = float(self.edit_q_target.text())
            Vpp_FG = float(self.spin_amp.value())
            gain = 1 if self.combo_gain.currentIndex() == 0 else 10
        except ValueError:
            return None
        return m_u, z, q_target, Vpp_FG, gain

    def on_q_from_f(self):
        params = self._read_mathieu_params()
        if params is None:
            self.append_log("Error: invalid Mathieu parameters.")
            return
        m_u, z, q_target, Vpp_FG, gain = params

        try:
            f_hz = float(self.edit_freq.text())
        except ValueError:
            self.append_log("Error: frequency f is invalid.")
            return

        q_val = compute_q(m_u, z, R0_MM, f_hz, Vpp_FG, gain)
        if math.isnan(q_val):
            self.lbl_q_result.setText("q = NaN")
            self.append_log("Failed to compute q.")
        else:
            self.lbl_q_result.setText(f"q = {q_val:.3f}")
            self.append_log(
                f"q from f: m={m_u}u, z={z}, f={f_hz:.1f} Hz, "
                f"Vpp={Vpp_FG:.2f} V, gain={gain} -> q={q_val:.3f}"
            )

    def on_f_from_q(self):
        params = self._read_mathieu_params()
        if params is None:
            self.append_log("Error: invalid Mathieu parameters.")
            return
        m_u, z, q_target, Vpp_FG, gain = params

        f_hz = compute_freq_for_q(m_u, z, R0_MM, q_target, Vpp_FG, gain)
        if math.isnan(f_hz):
            self.append_log("Failed to compute frequency from q.")
            return

        self.edit_freq.setText(f"{f_hz:.3f}")
        self.lbl_q_result.setText("q = ---")
        self.append_log(
            f"f from q: m={m_u}u, z={z}, q={q_target}, "
            f"Vpp={Vpp_FG:.2f} V, gain={gain} -> f={f_hz:.1f} Hz"
        )

    # ---------- FG group ----------

    def _build_fg_group(self):
        group = QtWidgets.QGroupBox("Function generator (DS345)")
        layout = QtWidgets.QFormLayout(group)

        self.edit_fg_ip = QtWidgets.QLineEdit(FG_IP_DEFAULT)
        self.edit_fg_port = QtWidgets.QLineEdit(str(FG_PORT_DEFAULT))

        btn_fg_set_target = QtWidgets.QPushButton("Set FG target")
        btn_fg_set_target.clicked.connect(self.on_fg_set_target)

        self.lbl_fg_status = QtWidgets.QLabel("Status: unknown")
        self.lbl_fg_freq = QtWidgets.QLabel("f = --- Hz")
        self.lbl_fg_ampl = QtWidgets.QLabel("Vpp = --- V")

        btn_fg_read = QtWidgets.QPushButton("Read FG values")
        btn_fg_read.clicked.connect(self.update_fg_display)

        btn_fg_send = QtWidgets.QPushButton("Send f & Vpp to FG")
        btn_fg_send.clicked.connect(self.on_fg_send)

        layout.addRow("FG IP:", self.edit_fg_ip)
        layout.addRow("FG port:", self.edit_fg_port)
        layout.addRow(btn_fg_set_target)
        layout.addRow(self.lbl_fg_status)
        layout.addRow("FG frequency:", self.lbl_fg_freq)
        layout.addRow("FG amplitude:", self.lbl_fg_ampl)
        layout.addRow(btn_fg_read)
        layout.addRow(btn_fg_send)

        return group

    def on_fg_set_target(self):
        ip = self.edit_fg_ip.text().strip()
        try:
            port = int(self.edit_fg_port.text())
        except ValueError:
            self.append_log("FG: port is invalid.")
            return
        self.fg.set_target(ip, port)
        self.append_log(f"FG target set: {ip}:{port}")

    def update_fg_display(self):
        f = self.fg.get_frequency()
        a = self.fg.get_amplitude()

        if math.isnan(f) or math.isnan(a):
            self.lbl_fg_status.setText("Status: no connection / error")
        else:
            self.lbl_fg_status.setText("Status: connected")
            self.lbl_fg_freq.setText(f"f = {f:.1f} Hz")
            self.lbl_fg_ampl.setText(f"Vpp = {a:.3f} V")

    def on_fg_send(self):
        try:
            f = float(self.edit_freq.text())
        except ValueError:
            self.append_log("FG send: frequency f is invalid.")
            return

        Vpp_FG = float(self.spin_amp.value())
        self.fg.set_frequency(f)
        self.fg.set_amplitude(Vpp_FG)
        self.append_log(f"Sent to FG: f={f:.1f} Hz, Vpp={Vpp_FG:.2f} V")
        self.update_fg_display()

    # ---------- LC group (SSH + resonance presets + L sweep) ----------

    def _build_lc_group(self):
        group = QtWidgets.QGroupBox("LC circuit (Pi via SSH / rc_cmd_derin.py)")
        vlayout = QtWidgets.QVBoxLayout(group)

        form = QtWidgets.QFormLayout()
        vlayout.addLayout(form)

        # SSH login
        self.edit_pi_host = QtWidgets.QLineEdit("raspberrypi.local")
        self.edit_pi_user = QtWidgets.QLineEdit("pi")
        self.edit_pi_pass = QtWidgets.QLineEdit("raspberry")
        self.edit_pi_pass.setEchoMode(QtWidgets.QLineEdit.Password)

        btn_pi_connect = QtWidgets.QPushButton("Connect to Pi")
        btn_pi_connect.clicked.connect(self.on_pi_connect)

        self.lbl_pi_status = QtWidgets.QLabel("Status: not connected")

        # LC values
        self.edit_C_pF = QtWidgets.QLineEdit("1300.0")  # C in pF
        self.edit_L_uH = QtWidgets.QLineEdit("31.0")    # L in µH

        btn_L_from_C = QtWidgets.QPushButton("Compute L from f & C")
        btn_L_from_C.clicked.connect(self.on_L_from_C)

        btn_C_from_L = QtWidgets.QPushButton("Compute C from f & L")
        btn_C_from_L.clicked.connect(self.on_C_from_L)

        self.lbl_lc_info = QtWidgets.QLabel("")

        btn_lc_send = QtWidgets.QPushButton("Send LC values to Pi")
        btn_lc_send.clicked.connect(self.on_lc_send)

        btn_lc_read = QtWidgets.QPushButton("Read LC values from Pi")
        btn_lc_read.clicked.connect(self.on_lc_read)

        # Resonance preset combo (embedded data)
        self.combo_resonance = QtWidgets.QComboBox()
        if not self.resonance_presets:
            self.combo_resonance.addItem("No resonance data")
            self.combo_resonance.setEnabled(False)
        else:
            for row in self.resonance_presets:
                f_mhz = row["f_MHz"]
                c_pf = row["C_pF"]
                l_uh = row["L_uH"]
                text = f"{f_mhz:.3f} MHz  (C={c_pf:.0f} pF, L={l_uh:.3f} µH)"
                self.combo_resonance.addItem(text, row)
            self.combo_resonance.currentIndexChanged.connect(self.on_resonance_selected)

        # Add to form
        form.addRow("Pi host/IP:", self.edit_pi_host)
        form.addRow("User:", self.edit_pi_user)
        form.addRow("Password:", self.edit_pi_pass)
        form.addRow(btn_pi_connect)
        form.addRow(self.lbl_pi_status)

        form.addRow("Resonance preset:", self.combo_resonance)

        form.addRow("C (pF):", self.edit_C_pF)
        form.addRow("L (µH):", self.edit_L_uH)

        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(btn_L_from_C)
        hl.addWidget(btn_C_from_L)
        form.addRow(hl)

        form.addRow("Info:", self.lbl_lc_info)
        form.addRow(btn_lc_send)
        form.addRow(btn_lc_read)

        # Sweep controls
        sweep_group = QtWidgets.QGroupBox("L sweep (around current L)")
        sweep_layout = QtWidgets.QFormLayout(sweep_group)

        self.edit_sweep_span_uH = QtWidgets.QLineEdit("5.0")
        self.edit_sweep_step_uH = QtWidgets.QLineEdit("0.25")
        self.edit_sweep_dwell_ms = QtWidgets.QLineEdit("1000")

        self.check_sweep_scope = QtWidgets.QCheckBox("Measure Vpp from scope at each step")
        self.check_sweep_scope.setChecked(True)

        btn_sweep = QtWidgets.QPushButton("Start L sweep")
        btn_sweep.clicked.connect(self.on_sweep_L)

        sweep_layout.addRow("± span around L (µH):", self.edit_sweep_span_uH)
        sweep_layout.addRow("Step size (µH):", self.edit_sweep_step_uH)
        sweep_layout.addRow("Dwell time per step (ms):", self.edit_sweep_dwell_ms)
        sweep_layout.addRow(self.check_sweep_scope)
        sweep_layout.addRow(btn_sweep)

        vlayout.addWidget(sweep_group)

        return group

    def on_pi_connect(self):
        host = self.edit_pi_host.text().strip()
        user = self.edit_pi_user.text().strip()
        passwd = self.edit_pi_pass.text()

        try:
            self.lc.connect(host, user, passwd)
            self.lbl_pi_status.setText(f"Status: connected to {host}")
            self.append_log(f"SSH to Pi established: {host} as {user}")
        except Exception as e:
            self.lbl_pi_status.setText("Status: connection error")
            self.append_log(f"SSH error: {e}")

    def _read_freq(self):
        try:
            return float(self.edit_freq.text())
        except ValueError:
            return float("nan")

    def on_resonance_selected(self, idx):
        data = self.combo_resonance.itemData(idx)
        if not isinstance(data, dict):
            return
        f_mhz = data["f_MHz"]
        c_pf = data["C_pF"]
        l_uh = data["L_uH"]

        f_hz = f_mhz * 1e6
        self.edit_freq.setText(f"{f_hz:.3f}")
        self.edit_C_pF.setText(f"{c_pf:.3f}")
        self.edit_L_uH.setText(f"{l_uh:.3f}")

        self.append_log(
            f"Resonance preset selected: f={f_mhz:.3f} MHz, "
            f"C={c_pf:.0f} pF, L={l_uh:.3f} µH"
        )

    def on_L_from_C(self):
        f = self._read_freq()
        if math.isnan(f):
            self.append_log("LC: frequency f is invalid.")
            return

        try:
            C_pF = float(self.edit_C_pF.text())
        except ValueError:
            self.append_log("LC: C is invalid.")
            return

        C_dek_F = C_pF * 1e-12
        L_H = L_from_f_C(f, C_dek_F)
        if math.isnan(L_H):
            self.append_log("LC: failed to compute L.")
            return

        L_uH = L_H * 1e6
        self.edit_L_uH.setText(f"{L_uH:.3f}")

        info = f"Resonance at f={f:.1f} Hz: L={L_uH:.3f} µH for C={C_pF:.3f} pF"
        self.lbl_lc_info.setText(info)
        self.append_log(info)

    def on_C_from_L(self):
        f = self._read_freq()
        if math.isnan(f):
            self.append_log("LC: frequency f is invalid.")
            return

        try:
            L_uH = float(self.edit_L_uH.text())
        except ValueError:
            self.append_log("LC: L is invalid.")
            return

        L_H = L_uH * 1e-6
        C_F = C_from_f_L(f, L_H)
        if math.isnan(C_F):
            self.append_log("LC: failed to compute C.")
            return

        C_pF = C_F * 1e12
        self.edit_C_pF.setText(f"{C_pF:.3f}")

        info = f"Resonance at f={f:.1f} Hz: C={C_pF:.3f} pF for L={L_uH:.3f} µH"
        self.lbl_lc_info.setText(info)
        self.append_log(info)

    def on_lc_send(self):
        if not self.lc.is_connected():
            self.append_log("LC: not connected to Pi.")
            return

        try:
            C_pF_raw = float(self.edit_C_pF.text())
            L_uH_raw = float(self.edit_L_uH.text())
        except ValueError:
            self.append_log("LC: cannot send (invalid numbers).")
            return

        # C: 0..32768 pF in 0.5 pF steps
        C_max_pF = 32768.0
        C_step_pF = 0.5

        if not (0.0 <= C_pF_raw < C_max_pF):
            self.append_log(
                f"LC: C={C_pF_raw:.3f} pF out of range 0..{C_max_pF} pF. Not sent."
            )
            return

        C_index = round(C_pF_raw / C_step_pF)
        C_pF = C_index * C_step_pF
        if C_pF >= C_max_pF:
            C_pF = C_max_pF - C_step_pF

        # L: 0..512 µH in 0.25 µH steps
        L_max_uH = 512.0
        L_step_uH = 0.25

        if not (0.0 <= L_uH_raw < L_max_uH):
            self.append_log(
                f"LC: L={L_uH_raw:.3f} µH out of range 0..{L_max_uH} µH. Not sent."
            )
            return

        L_index = round(L_uH_raw / L_step_uH)
        L_uH = L_index * L_step_uH
        if L_uH >= L_max_uH:
            L_uH = L_max_uH - L_step_uH

        # put rounded values back to GUI
        self.edit_C_pF.setText(f"{C_pF:.3f}")
        self.edit_L_uH.setText(f"{L_uH:.3f}")

        try:
            outC, errC = self.lc.set_value("C", C_pF)  # pF to Pi
            outL, errL = self.lc.set_value("L", L_uH)  # µH to Pi
            self.append_log(
                f"LC sent to Pi: C={C_pF:.3f} pF, L={L_uH:.3f} µH "
                f"(rounded to 0.5 pF / 0.25 µH). "
                f"C-out={outC!r}, C-err={errC!r} | L-out={outL!r}, L-err={errL!r}"
            )
        except Exception as e:
            self.append_log(f"LC send error: {e}")

    def on_lc_read(self):
        if not self.lc.is_connected():
            self.append_log("LC: not connected to Pi.")
            return

        try:
            c_val, c_err = self.lc.get_value("C")
            l_val, l_err = self.lc.get_value("L")
        except Exception as e:
            self.append_log(f"LC read error: {e}")
            return

        if not math.isnan(c_val):
            self.edit_C_pF.setText(f"{c_val:.3f}")
        if not math.isnan(l_val):
            self.edit_L_uH.setText(f"{l_val:.3f}")

        self.append_log(f"LC from Pi: C={c_val} pF (err={c_err}), L={l_val} µH (err={l_err})")

    # ---------- L sweep ----------

    def on_sweep_L(self):
        if not self.lc.is_connected():
            QtWidgets.QMessageBox.warning(self, "Error", "Not connected to Pi (SSH).")
            return

        try:
            center_L = float(self.edit_L_uH.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Error", "Current L value is invalid.")
            return

        try:
            span = float(self.edit_sweep_span_uH.text())
            step = float(self.edit_sweep_step_uH.text())
            dwell_ms = float(self.edit_sweep_dwell_ms.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Error", "Sweep parameters are invalid.")
            return

        if span <= 0 or step <= 0 or dwell_ms <= 0:
            QtWidgets.QMessageBox.warning(self, "Error", "Span, step and dwell time must be > 0.")
            return

        dwell_s = dwell_ms / 1000.0
        measure_scope = self.check_sweep_scope.isChecked()

        # Build list of L values
        start = center_L - span
        stop = center_L + span

        values = []
        v = start
        if start < stop:
            while v <= stop + 1e-9:
                values.append(v)
                v += step
        else:
            while v >= stop - 1e-9:
                values.append(v)
                v -= step

        self.append_log(
            f"Starting L sweep around {center_L:.3f} µH: "
            f"from {start:.3f} to {stop:.3f} in steps of {step:.3f} µH."
        )

        # Results arrays
        L_meas = []
        Vpp2_list = []
        Vpp3_list = []
        max_vpp2 = -1.0
        best_L = None
        best_wave2 = None
        best_wave3 = None

        # Hardware limits and step grid
        L_max_uH = 512.0
        L_step_hw = 0.25

        for idx, val in enumerate(values):
            QtWidgets.QApplication.processEvents()

            if val < 0.0 or val >= L_max_uH:
                continue

            # Snap to hardware grid
            index = round(val / L_step_hw)
            L_uH = index * L_step_hw
            if L_uH >= L_max_uH:
                L_uH = L_max_uH - L_step_hw

            self.edit_L_uH.setText(f"{L_uH:.3f}")
            try:
                self.lc.set_value("L", L_uH)
            except Exception as e:
                self.append_log(f"Sweep: error setting L: {e}")
                continue

            self.append_log(f"Sweep step {idx+1}/{len(values)}: L={L_uH:.3f} µH")

            time.sleep(dwell_s)

            if measure_scope:
                try:
                    vpp2, vpp3, wave2, wave3 = self.scope.measure_ch2_ch3()
                    self.append_log(
                        f"  Scope: CH2 Vpp={vpp2:.3f} V, CH3 Vpp={vpp3:.3f} V"
                    )
                    L_meas.append(L_uH)
                    Vpp2_list.append(vpp2)
                    Vpp3_list.append(vpp3)

                    if vpp2 > max_vpp2:
                        max_vpp2 = vpp2
                        best_L = L_uH
                        best_wave2 = wave2
                        best_wave3 = wave3
                except Exception as e:
                    self.append_log(f"Sweep: scope error: {e}")

        if measure_scope and L_meas and best_L is not None:

            msg_txt = (f"Max CH2 Vpp during sweep: {max_vpp2:.3f} V\n"
                       f"at L = {best_L:.3f} µH")
            self.append_log("[Sweep finished] " + msg_txt)

            # Popup dialog with plot
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("L sweep result")
            dlg_layout = QtWidgets.QVBoxLayout(dialog)

            fig = Figure(figsize=(7, 6))
            canvas = FigureCanvas(fig)
            dlg_layout.addWidget(canvas)

            ax1 = fig.add_subplot(211)
            ax1.plot(L_meas, Vpp2_list, label="CH2 Vpp")
            ax1.plot(L_meas, Vpp3_list, label="CH3 Vpp")
            ax1.set_xlabel("L (µH)")
            ax1.set_ylabel("Vpp (V)")
            ax1.legend(loc="best")
            ax1.grid(True)

            if best_wave2 is not None and best_wave3 is not None:
                ax2 = fig.add_subplot(212)
                x2 = np.arange(len(best_wave2))
                x3 = np.arange(len(best_wave3))
                ax2.plot(x2, best_wave2, label="CH2 (best L)")
                ax2.plot(x3, best_wave3, label="CH3 (best L)")
                ax2.set_xlabel("Sample index")
                ax2.set_ylabel("Voltage (V)")
                ax2.legend(loc="best")
                ax2.grid(True)

            canvas.draw()

            info_label = QtWidgets.QLabel(msg_txt)
            dlg_layout.addWidget(info_label)

            btn_close = QtWidgets.QPushButton("Close")
            btn_close.clicked.connect(dialog.accept)
            dlg_layout.addWidget(btn_close)

            dialog.exec_()

        elif measure_scope:
            msg = "Sweep finished, but no valid scope data were collected."
            QtWidgets.QMessageBox.information(self, "Sweep result", msg)
            self.append_log("[Sweep finished] " + msg)
        else:
            msg = "Sweep finished (scope measurement disabled)."
            QtWidgets.QMessageBox.information(self, "Sweep result", msg)
            self.append_log("[Sweep finished] " + msg)

    # ---------- Scope / Plot group ----------

    def _build_scope_group(self):
        group = QtWidgets.QGroupBox("Oscilloscope (CH2 & CH3)")
        layout = QtWidgets.QFormLayout(group)

        self.edit_scope_ip = QtWidgets.QLineEdit(SCOPE_IP_DEFAULT)
        self.edit_scope_port = QtWidgets.QLineEdit(str(SCOPE_PORT_DEFAULT))

        btn_scope_set = QtWidgets.QPushButton("Set scope target")
        btn_scope_set.clicked.connect(self.on_scope_set_target)

        self.lbl_vpp2 = QtWidgets.QLabel("CH2 Vpp = --- V")
        self.lbl_vpp3 = QtWidgets.QLabel("CH3 Vpp = --- V")
        self.lbl_q_meas = QtWidgets.QLabel("q_meas (from CH2) = ---")

        btn_measure = QtWidgets.QPushButton("Measure CH2 & CH3 + plot")
        btn_measure.clicked.connect(self.on_measure_scope)

        layout.addRow("Scope IP:", self.edit_scope_ip)
        layout.addRow("Scope port:", self.edit_scope_port)
        layout.addRow(btn_scope_set)
        layout.addRow(btn_measure)
        layout.addRow(self.lbl_vpp2)
        layout.addRow(self.lbl_vpp3)
        layout.addRow(self.lbl_q_meas)

        return group

    def on_scope_set_target(self):
        ip = self.edit_scope_ip.text().strip()
        try:
            port = int(self.edit_scope_port.text())
        except ValueError:
            self.append_log("Scope: port is invalid.")
            return
        self.scope.set_target(ip, port)
        self.append_log(f"Scope target set: {ip}:{port}")

    def _build_plot_group(self):
        group = QtWidgets.QGroupBox("Waveform plot (CH2 & CH3)")
        layout = QtWidgets.QVBoxLayout(group)

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        return group

    def on_measure_scope(self):
        try:
            vpp2, vpp3, wave2, wave3 = self.scope.measure_ch2_ch3()
        except Exception as e:
            self.append_log(f"Scope error: {e}")
            self.lbl_vpp2.setText("CH2 Vpp = NaN")
            self.lbl_vpp3.setText("CH3 Vpp = NaN")
            self.lbl_q_meas.setText("q_meas (from CH2) = NaN")
            return

        self.lbl_vpp2.setText(f"CH2 Vpp = {vpp2:.3f} V")
        self.lbl_vpp3.setText(f"CH3 Vpp = {vpp3:.3f} V")
        self.append_log(f"Scope: CH2 Vpp={vpp2:.3f} V, CH3 Vpp={vpp3:.3f} V")

        # q_meas from CH2 (interpreting CH2 Vpp as RFQ Vpp)
        params = self._read_mathieu_params()
        if params is None:
            self.lbl_q_meas.setText("q_meas (from CH2) = NaN")
        else:
            m_u, z, q_target, Vpp_FG, gain = params
            try:
                f = float(self.edit_freq.text())
            except ValueError:
                f = float("nan")

            if math.isnan(f):
                self.lbl_q_meas.setText("q_meas (from CH2) = NaN")
            else:
                m = m_u * u_to_kg
                Q = abs(z) * e_charge
                r0 = R0_MM / 1000.0
                V0 = vpp2 / 2.0
                omega = 2.0 * math.pi * f
                q_meas = 4.0 * Q * V0 / (m * (r0 ** 2) * (omega ** 2))
                self.lbl_q_meas.setText(f"q_meas (from CH2) = {q_meas:.3f}")
                self.append_log(
                    f"q_meas from CH2: Vpp={vpp2:.3f} V, f={f:.1f} Hz -> q_meas={q_meas:.3f}"
                )

        # Update main plot
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        x2 = np.arange(len(wave2))
        x3 = np.arange(len(wave3))
        ax.plot(x2, wave2, label="CH2")
        ax.plot(x3, wave3, label="CH3")
        ax.set_xlabel("Sample index")
        ax.set_ylabel("Voltage (V)")
        ax.legend(loc="best")
        ax.grid(True)
        self.canvas.draw_idle()

    # ---------- Logging & close ----------

    def append_log(self, text):
        self.log.append(text)
        self.log.moveCursor(QTextCursor.End)

    def closeEvent(self, event):
        self.fg.close()
        self.lc.close()
        event.accept()



# ---------- COMBI7 L-sweep worker (background thread) ----------

class Combi7SweepWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(str)
    stepL = QtCore.pyqtSignal(float)
    dataPoint = QtCore.pyqtSignal(float, float, float)
    finished = QtCore.pyqtSignal(list, list, list, float, float, object, object, bool)
    error = QtCore.pyqtSignal(str)

    def __init__(self, lc_client, scope_client, parent=None):
        super().__init__(parent)
        self._lc = lc_client
        self._scope = scope_client
        self._running = False

    @QtCore.pyqtSlot(float, float, float, float, bool)
    def run_sweep(self, center_L, span, step, dwell_s, measure_scope):
        """
        Führt den L-Sweep in einem Hintergrundthread aus.

        Parameter sind analog zur ursprünglichen on_sweep_L-Implementierung:
          center_L   – aktueller L-Wert (µH)
          span       – ±Spanne um L (µH)
          step       – Schrittweite (µH)
          dwell_s    – Wartezeit pro Schritt (Sekunden)
          measure_scope – True, wenn Scope mitmessen soll
        """
        if span <= 0 or step <= 0 or dwell_s <= 0:
            self.error.emit("Sweep parameters must be > 0.")
            self.finished.emit([], [], [], float("nan"), float("nan"), None, None, measure_scope)
            return

        self._running = True

        # Liste der L-Werte wie im Original
        start = center_L - span
        stop = center_L + span

        values = []
        v = start
        if start < stop:
            while v <= stop + 1e-9:
                values.append(v)
                v += step
        else:
            while v >= stop - 1e-9:
                values.append(v)
                v -= step

        # Ergebnisse
        L_meas = []
        Vpp2_list = []
        Vpp3_list = []
        max_vpp2 = -1.0
        best_L = None
        best_wave2 = None
        best_wave3 = None

        # Hardware-Limits wie in COMBI7.py
        L_max_uH = 512.0
        L_step_hw = 0.25

        import time

        for idx, val in enumerate(values):
            if not self._running:
                break

            if val < 0.0 or val >= L_max_uH:
                continue

            # Snap auf Hardware-Grid
            index = round(val / L_step_hw)
            L_uH = index * L_step_hw
            if L_uH >= L_max_uH:
                L_uH = L_max_uH - L_step_hw

            # GUI über aktuellen Schritt informieren
            self.stepL.emit(L_uH)
            self.progress.emit(f"Sweep step {idx+1}/{len(values)}: L={L_uH:.3f} µH")

            # L zum LC-Client schicken
            try:
                self._lc.set_value("L", L_uH)
            except Exception as e:
                self.progress.emit(f"Sweep: error setting L: {e}")
                continue

            time.sleep(dwell_s)

            if measure_scope:
                try:
                    vpp2, vpp3, wave2, wave3 = self._scope.measure_ch2_ch3()
                    self.progress.emit(
                        f"  Scope: CH2 Vpp={vpp2:.3f} V, CH3 Vpp={vpp3:.3f} V"
                    )
                    L_meas.append(L_uH)
                    Vpp2_list.append(vpp2)
                    Vpp3_list.append(vpp3)
                    self.dataPoint.emit(L_uH, vpp2, vpp3)

                    if vpp2 > max_vpp2:
                        max_vpp2 = vpp2
                        best_L = L_uH
                        best_wave2 = wave2
                        best_wave3 = wave3
                except Exception as e:
                    self.progress.emit(f"Sweep: scope error: {e}")

        self._running = False
        self.finished.emit(L_meas, Vpp2_list, Vpp3_list, max_vpp2, best_L, best_wave2, best_wave3, measure_scope)

    @QtCore.pyqtSlot()
    def stop(self):
        self._running = False


# ---------- RFQ GUI-Subklasse für Tab-Einbettung + Thread-Sweep ----------

class Combi7InTab(RFQUnifiedGUI):
    """
    RFQUnifiedGUI-Subklasse für die Einbettung als Tab in test12.

    - UI und Funktionen 1:1 wie in RFQUnifiedGUI.
    - Der L-Sweep läuft in einem eigenen QThread.
    """
    def __init__(self, parent=None):
        super().__init__()
        self._sweep_thread = None
        self._sweep_worker = None

    def on_sweep_L(self):
        """Start L sweep in background worker thread (non-blocking)."""
        if not self.lc.is_connected():
            QtWidgets.QMessageBox.warning(self, "Error", "Not connected to Pi (SSH).")
            return

        # Parameter aus GUI lesen – identisch zum Original
        try:
            center_L = float(self.edit_L_uH.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Error", "Current L value is invalid.")
            return

        try:
            span = float(self.edit_sweep_span_uH.text())
            step = float(self.edit_sweep_step_uH.text())
            dwell_ms = float(self.edit_sweep_dwell_ms.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Error", "Sweep parameters are invalid.")
            return

        if span <= 0 or step <= 0 or dwell_ms <= 0:
            QtWidgets.QMessageBox.warning(self, "Error", "Span, step and dwell time must be > 0.")
            return

        if self._sweep_thread is not None and self._sweep_thread.isRunning():
            QtWidgets.QMessageBox.information(
                self,
                "L sweep",
                "An L sweep is already running.",
            )
            return

        dwell_s = dwell_ms / 1000.0
        measure_scope = self.check_sweep_scope.isChecked()

        self.append_log(
            f"Starting L sweep around {center_L:.3f} µH: "
            f"±{span:.3f} µH in steps of {step:.3f} µH; dwell {dwell_ms:.0f} ms."
        )

        # Worker + Thread anlegen
        self._sweep_thread = QtCore.QThread(self)
        self._sweep_worker = Combi7SweepWorker(self.lc, self.scope)
        self._sweep_worker.moveToThread(self._sweep_thread)

        # Verbindungen
        self._sweep_thread.started.connect(
            lambda: self._sweep_worker.run_sweep(center_L, span, step, dwell_s, measure_scope)
        )
        self._sweep_worker.progress.connect(self.append_log)
        self._sweep_worker.stepL.connect(self._on_sweep_step_L)
        self._sweep_worker.error.connect(self._on_sweep_error)
        self._sweep_worker.finished.connect(self._on_sweep_finished)
        self._sweep_worker.finished.connect(self._sweep_thread.quit)
        self._sweep_worker.finished.connect(self._sweep_worker.deleteLater)
        self._sweep_thread.finished.connect(self._on_sweep_thread_finished)

        self._sweep_thread.start()

    @QtCore.pyqtSlot(float)
    def _on_sweep_step_L(self, L_uH):
        """Während des Sweeps das L-Feld in der GUI aktualisieren."""
        self.edit_L_uH.setText(f"{L_uH:.3f}")

    @QtCore.pyqtSlot(str)
    def _on_sweep_error(self, message: str):
        QtWidgets.QMessageBox.warning(self, "L sweep error", message)

    @QtCore.pyqtSlot(list, list, list, float, float, object, object, bool)
    def _on_sweep_finished(
        self,
        L_meas,
        Vpp2_list,
        Vpp3_list,
        max_vpp2,
        best_L,
        best_wave2,
        best_wave3,
        measure_scope,
    ):
        """
        Sweep-Resultat behandeln; Logik entspricht dem unteren Teil
        der ursprünglichen on_sweep_L-Methode.
        """
        if measure_scope and L_meas and best_L is not None:
            msg_txt = (
                f"Max CH2 Vpp during sweep: {max_vpp2:.3f} V\n"
                f"at L = {best_L:.3f} µH"
            )
            self.append_log("[Sweep finished] " + msg_txt)

            # Popup-Dialog mit Plot
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("L sweep result")
            dlg_layout = QtWidgets.QVBoxLayout(dialog)

            fig = Figure(figsize=(7, 6))
            canvas = FigureCanvas(fig)
            dlg_layout.addWidget(canvas)

            ax1 = fig.add_subplot(211)
            ax1.plot(L_meas, Vpp2_list, label="CH2 Vpp")
            ax1.plot(L_meas, Vpp3_list, label="CH3 Vpp")
            ax1.set_xlabel("L (µH)")
            ax1.set_ylabel("Vpp (V)")
            ax1.legend(loc="best")
            ax1.grid(True)

            if best_wave2 is not None and best_wave3 is not None:
                ax2 = fig.add_subplot(212)
                x2 = np.arange(len(best_wave2))
                x3 = np.arange(len(best_wave3))
                ax2.plot(x2, best_wave2, label="CH2 (best L)")
                ax2.plot(x3, best_wave3, label="CH3 (best L)")
                ax2.set_xlabel("Sample index")
                ax2.set_ylabel("Voltage (V)")
                ax2.legend(loc="best")
                ax2.grid(True)

            canvas.draw()

            info_label = QtWidgets.QLabel(msg_txt)
            dlg_layout.addWidget(info_label)

            btn_close = QtWidgets.QPushButton("Close")
            btn_close.clicked.connect(dialog.accept)
            dlg_layout.addWidget(btn_close)

            dialog.exec_()

        elif measure_scope:
            msg = "Sweep finished, but no valid scope data were collected."
            QtWidgets.QMessageBox.information(self, "Sweep result", msg)
            self.append_log("[Sweep finished] " + msg)
        else:
            msg = "Sweep finished (scope measurement disabled)."
            QtWidgets.QMessageBox.information(self, "Sweep result", msg)
            self.append_log("[Sweep finished] " + msg)

    @QtCore.pyqtSlot()
    def _on_sweep_thread_finished(self):
        self._sweep_thread.deleteLater()
        self._sweep_thread = None
        self._sweep_worker = None

    def closeEvent(self, event):
        # Laufenden Sweep-Thread sauber stoppen, dann normales Cleanup der Basisklasse
        if self._sweep_worker is not None:
            self._sweep_worker.stop()
        if self._sweep_thread is not None:
            self._sweep_thread.quit()
            self._sweep_thread.wait(2000)
        super().closeEvent(event)




# ---------- Config folder ----------
CONFIG_BASE_DIR = r"C:\Users\ALIS\Desktop\Configs"

# ---------- MQTT defaults ----------
MQTT_DEFAULT_HOST = "192.168.0.20"
MQTT_DEFAULT_PORT = 1883
MQTT_DEFAULT_KEEPALIVE = 30
MQTT_SUB_TOPICS = [
    ("psu/1/#", 0),
    ("psu/2/#", 0),
    ("hv/1/#", 0),
    ("hv/4/#", 0),
]


class ScrollableSlider(QSlider):
    """
    Shared slider:
    - For OPC sliders: use self.control{'step_selector','multiplier'}.
    - For magnet slider: can also be used with control dict.
    """
    def __init__(self, parent=None, step_func=None):
        super().__init__(Qt.Horizontal, parent)
        self.control = None          # used by OPC sliders
        self.step_func = step_func   # optional

    def wheelEvent(self, event):
        delta = event.angleDelta().y()

        # Path 1: explicit step_func
        if self.step_func is not None:
            step = self.step_func() or 1
            new_val = self.value() + (step if delta > 0 else -step)
            self.setValue(min(self.maximum(), max(self.minimum(), new_val)))
            event.accept()
            return

        # Path 2: OPC-style with control dict
        if not self.control:
            return

        step_selector = self.control['step_selector']
        multiplier = self.control['multiplier']

        step_val = step_selector.currentData()
        if step_val is None:
            step_text = step_selector.currentText().replace(",", ".")
            step_val = float(step_text)

        ticks = max(1, round(step_val * multiplier))
        new_val = self.value() + (ticks if delta > 0 else -ticks)
        self.setValue(min(self.maximum(), max(self.minimum(), new_val)))
        event.accept()


class CollapsibleGroupBox(QGroupBox):
    """
    QGroupBox with a checkbox title to collapse/expand content.
    """
    def __init__(self, title="", parent=None):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(True)
        self._content_layout = None
        self.toggled.connect(self._on_toggled)

    def setLayout(self, layout):
        super().setLayout(layout)
        self._content_layout = layout

    def _on_toggled(self, checked):
        if self._content_layout is None:
            return
        for i in range(self._content_layout.count()):
            item = self._content_layout.itemAt(i)
            w = item.widget()
            if w is not None:
                w.setVisible(checked)


class MqttClient(QtCore.QObject):
    """MQTT client running in a separate Qt thread."""
    messageReceived = QtCore.pyqtSignal(str, str)
    connectionChanged = QtCore.pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = mqtt.Client(protocol=mqtt.MQTTv311)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._host = MQTT_DEFAULT_HOST
        self._port = MQTT_DEFAULT_PORT
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
            self.connectionChanged.emit(False, f"Publish error: {e}")

    def _run_loop(self):
        try:
            self._client.connect(self._host, self._port, keepalive=MQTT_DEFAULT_KEEPALIVE)
            for t, qos in MQTT_SUB_TOPICS:
                self._client.subscribe(t, qos=qos)
            while self._running:
                self._client.loop(timeout=0.1)
                time.sleep(0.05)
        except Exception as e:
            self.connectionChanged.emit(False, f"MQTT start error: {e}")
            self._running = False

    def _on_connect(self, client, userdata, flags, rc):
        ok = (rc == mqtt.CONNACK_ACCEPTED)
        msg = "Connected" if ok else f"Connect RC={rc}"
        self.connectionChanged.emit(ok, msg)
        if ok:
            for t, qos in MQTT_SUB_TOPICS:
                client.subscribe(t, qos=qos)

    def _on_disconnect(self, client, userdata, rc):
        self.connectionChanged.emit(False, "Disconnected")

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8", errors="ignore")
        except Exception:
            payload = ""
        self.messageReceived.emit(msg.topic, payload)




# ---------- Sample motor worker (background thread) ----------

class SampleMotorWorker(QtCore.QObject):
    """
    Simple worker talking to the stepper motor in a dedicated thread.

    It exposes slots for move / home / stop and does all socket I/O
    outside the GUI thread.
    """
    error = QtCore.pyqtSignal(str)

    def __init__(self, host: str = "192.168.0.6", port: int = 102, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = int(port)
        self._sock = None

    @QtCore.pyqtSlot()
    def connect_motor(self):
        """Open the TCP connection to the stepper controller (if not already open)."""
        if self._sock is not None:
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((self._host, self._port))
            self._sock = s
        except Exception as e:
            self._sock = None
            self.error.emit(f"Stepper connect error: {e}")

    def _send_command(self, command: str):
        """Low-level helper: send a single command and return the response string or None."""
        try:
            if self._sock is None:
                self.connect_motor()
                if self._sock is None:
                    return None

            self._sock.sendall((command + "\n").encode("ascii"))
            response = self._sock.recv(1024).decode("ascii", errors="ignore").strip()
            return response
        except Exception as e:
            self.error.emit(f"Stepper command error '{command}': {e}")
            try:
                if self._sock:
                    self._sock.close()
            except Exception:
                pass
            self._sock = None
            return None

    @QtCore.pyqtSlot(int)
    def move_to_position(self, target_position: int):
        """Set target position and start movement."""
        resp = self._send_command(f"s r0xca {target_position}")
        if resp != "ok":
            self.error.emit(f"Failed to set position ({target_position})")
            return
        resp = self._send_command("t 1")
        if resp != "ok":
            self.error.emit("Movement command failed")

    @QtCore.pyqtSlot()
    def stop_movement(self):
        """Stop any current movement."""
        self._send_command("t 0")

    @QtCore.pyqtSlot()
    def go_home(self):
        """Return to controller home position."""
        resp = self._send_command("t 2")
        if resp != "ok":
            self.error.emit("Home command failed")

    @QtCore.pyqtSlot()
    def shutdown(self):
        """Close the TCP socket (called during application shutdown)."""
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None




# ---------- Keithley measurement worker (background thread) ----------

class KeithleyWorker(QtCore.QObject):
    """
    Background worker for continuous Keithley measurements.

    - Runs in its own QThread.
    - Uses KeithleyWidget's SCPI methods, but only those that do NOT touch Qt GUI.
    """
    measurementReady = QtCore.pyqtSignal(str, float, float)  # timestamp, elapsed_s, current_nA
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, keithley_widget, parent=None):
        super().__init__(parent)
        self.kwidget = keithley_widget
        self._running = False

    @QtCore.pyqtSlot()
    def run(self):
        """
        Main loop executed in the worker thread.
        Uses the widget's read_current_once() which now only does socket & math,
        no GUI operations.
        """
        self._running = True
        if self.kwidget.start_time is None:
            self.kwidget.start_time = time.time()

        try:
            while self._running:
                try:
                    current_nA = self.kwidget.read_current_once()
                except Exception as e:
                    self.error.emit(f"Keithley read error: {e}")
                    break

                if current_nA is not None:
                    elapsed = time.time() - self.kwidget.start_time
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    self.measurementReady.emit(timestamp, elapsed, current_nA)

                # Sleep according to user-selected interval
                interval = max(0.1, float(self.kwidget.interval_seconds))
                end_time = time.time() + interval
                while self._running and time.time() < end_time:
                    time.sleep(0.02)
        finally:
            # Instrument disconnect is handled explicitly by the widget after stop,
            # but calling it twice is harmless.
            self.kwidget.disconnect_instrument()
            self._running = False
            self.finished.emit()

    @QtCore.pyqtSlot()
    def stop(self):
        self._running = False


# ---------- Keithley widget ----------

class KeithleyWidget(QtWidgets.QWidget):
    """
    Embedded Keithley 6485 monitor.

    - Measurement can start WITHOUT selecting a log file.
    - If a log file is selected beforehand, data is logged (inside the Keithley tab).
    - Plot shows current [nA] and sputter current [mA] (right y-axis).
    - Continuous measurement runs in a separate thread for smoother UI.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # Measurement state
        self.is_measuring = False
        self.start_time = None
        self.log_file_path = None  # optional

        # Threading
        self.measure_thread = None
        self.measure_worker = None

        # Data buffers
        self.timestamps = []
        self.measurements_nA = []
        self.sputter_values = []
        self.charge_nC = 0.0
        self.filter_threshold = 100000  # 100 µA in nA
        self.plot_start_time = 0
        self.window_size = 10
        # Limit the amount of data kept for plotting to avoid slowdowns.
        self.max_display_points = 2000

        # Simple settings mirrored from UI (safe to read from worker thread)
        self.filter_enabled = False
        self.interval_seconds = 1.0

        # TCP connection for Keithley 6485
        self.HOST = "192.168.0.2"
        self.PORT = 100
        self.sock = None
        self.connected = False

        # Optional OPC UA for sputter current display
        self.opc_url = "opc.tcp://DESKTOP-UH9J072:4980/Softing_dataFEED_OPC_Suite_Configuration2"
        self.opc_node_id = "ns=3;s=OPC_1.PLC_HV/Analog_In/In_Cal_Sputter_I"
        self.opc_client = None
        self.opc_node = None
        self.last_sputter_current = 0.0

        # Timer for sputter current (still in GUI thread)
        self.sputter_timer = QtCore.QTimer(self)
        self.sputter_timer.timeout.connect(self.update_sputter_current)
        self.sputter_timer.start(1000)

        self.build_ui()

    def build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        control_panel = QGroupBox("Keithley 6485 – Measurement Control")
        control_layout = QtWidgets.QGridLayout()

        # File selection (optional)
        self.file_label = QtWidgets.QLabel("No log file selected (optional)")
        browse_button = QtWidgets.QPushButton("Select Log File")
        browse_button.clicked.connect(self.select_log_file)

        # Measurement controls
        self.start_button = QtWidgets.QPushButton("Start Measurement")
        self.start_button.clicked.connect(self.toggle_measurement)
        self.start_button.setStyleSheet("background-color: #4CAF50; color: white;")

        self.stop_button = QtWidgets.QPushButton("Stop Measurement")
        self.stop_button.clicked.connect(self.toggle_measurement)
        self.stop_button.setStyleSheet("background-color: #f44336; color: white;")
        self.stop_button.setEnabled(False)

        self.clear_button = QtWidgets.QPushButton("Clear Graph")
        self.clear_button.clicked.connect(self.clear_graph)
        self.clear_button.setStyleSheet("background-color: #FFA500; color: white;")
        self.clear_button.setEnabled(False)

        # Interval control
        interval_label = QtWidgets.QLabel("Measurement interval (s):")
        self.interval_spin = QtWidgets.QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 60)
        self.interval_spin.setValue(1.0)
        self.interval_spin.setSingleStep(0.1)
        self.interval_spin.valueChanged.connect(self.on_interval_changed)

        # Moving average control
        avg_label = QtWidgets.QLabel("Moving average window:")
        self.avg_spin = QtWidgets.QSpinBox()
        self.avg_spin.setRange(1, 1000)
        self.avg_spin.setValue(10)
        self.avg_spin.valueChanged.connect(self.update_window_size)

        # Filter checkbox
        self.filter_checkbox = QtWidgets.QCheckBox("Filter values > 100 µA")
        self.filter_checkbox.setChecked(False)
        self.filter_checkbox.toggled.connect(self.on_filter_toggled)

        control_layout.addWidget(QtWidgets.QLabel("Log file (optional):"), 0, 0)
        control_layout.addWidget(self.file_label, 0, 1)
        control_layout.addWidget(browse_button, 0, 2)
        control_layout.addWidget(self.start_button, 1, 0, 1, 3)
        control_layout.addWidget(self.stop_button, 2, 0, 1, 3)
        control_layout.addWidget(self.clear_button, 3, 0, 1, 3)
        control_layout.addWidget(interval_label, 4, 0)
        control_layout.addWidget(self.interval_spin, 4, 1)
        control_layout.addWidget(avg_label, 5, 0)
        control_layout.addWidget(self.avg_spin, 5, 1)
        control_layout.addWidget(self.filter_checkbox, 6, 0, 1, 3)

        control_panel.setLayout(control_layout)
        layout.addWidget(control_panel)

        # Current / average / charge / sputter displays
        value_display_layout = QtWidgets.QVBoxLayout()

        current_display_layout = QtWidgets.QHBoxLayout()
        self.value_display = QtWidgets.QLabel("Current: ---")
        self.value_display.setStyleSheet("font-size: 24px; font-weight: bold; color: #2E86C1;")
        self.value_display.setAlignment(Qt.AlignCenter)
        current_display_layout.addWidget(self.value_display)

        self.avg_display = QtWidgets.QLabel("Avg: --- nA (σ: ---)")
        self.avg_display.setStyleSheet("font-size: 20px; color: #2E86C1;")
        self.avg_display.setAlignment(Qt.AlignCenter)
        current_display_layout.addWidget(self.avg_display)

        value_display_layout.addLayout(current_display_layout)

        charge_display_layout = QtWidgets.QHBoxLayout()
        self.charge_display = QtWidgets.QLabel("Charge: 0.00 nC")
        self.charge_display.setStyleSheet("font-size: 24px; font-weight: bold; color: #27AE60;")
        self.charge_display.setAlignment(Qt.AlignCenter)
        charge_display_layout.addWidget(self.charge_display)

        self.sputter_display = QtWidgets.QLabel("Sputter: --- mA")
        self.sputter_display.setStyleSheet("font-size: 24px; font-weight: bold; color: #8E44AD;")
        self.sputter_display.setAlignment(Qt.AlignCenter)
        charge_display_layout.addWidget(self.sputter_display)

        value_display_layout.addLayout(charge_display_layout)
        layout.addLayout(value_display_layout)

        # Plot (current + sputter)
        self.figure = Figure(figsize=(10, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax2 = self.ax.twinx()
        # Make sure sputter axis is on the right
        self.ax2.yaxis.set_label_position("right")
        self.ax2.yaxis.tick_right()
        layout.addWidget(self.canvas)

    # ---------- Simple UI-mirrored settings ----------

    def on_filter_toggled(self, checked: bool):
        self.filter_enabled = bool(checked)

    def on_interval_changed(self, val: float):
        self.interval_seconds = float(val)

    # ---------- Keithley low-level ----------

    def connect_instrument(self, show_errors_in_ui: bool = True):
        if self.connected:
            return True
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.HOST, self.PORT))
            self.initialize_keithley()
            self.connected = True
            return True
        except Exception as e:
            if show_errors_in_ui:
                QMessageBox.critical(self, "Keithley error", f"Connection failed: {e}")
            else:
                print(f"Keithley connection failed: {e}")
            self.connected = False
            self.sock = None
            return False

    def disconnect_instrument(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self.connected = False

    def initialize_keithley(self):
        init_commands = [
            "*RST", ":SYST:ZCH OFF", ":SYST:ZCOR ON",
            ":FORM:ELEM READ", ":SENS:CURR:RANG:AUTO ON",
            ":SENS:CURR:NPLC 1"
        ]
        for cmd in init_commands:
            self.send_command(cmd, 0.5)

    def send_command(self, command, wait_time=0.1):
        if not self.sock:
            return None
        try:
            self.sock.sendall((command + "\n").encode('ascii'))
            time.sleep(wait_time)
            if command.endswith("?"):
                response = self.sock.recv(1024).decode('ascii').strip()
                if '\n' in response:
                    response = response.split('\n')[0]
                return response
            return None
        except Exception as e:
            print(f"Command error: {e}")
            return None

    def read_current_once(self):
        """
        Return a single current value in nA, or None on error.
        This method does not touch any Qt GUI elements and is safe to use
        from a background worker thread.
        """
        if not self.connected and not self.connect_instrument(show_errors_in_ui=False):
            return None
        response = self.send_command("READ?", 0.5)
        if not response:
            return None
        try:
            if '\n' in response:
                response = response.split('\n')[0]
            current_A = float(response.replace(',', '.'))
            current_nA = abs(current_A) * 1e9
            if self.filter_enabled and current_nA > self.filter_threshold:
                return None
            return current_nA
        except ValueError as e:
            print(f"Value conversion error: {e}")
            return None

    def measure_average_current(self, duration_s: float):
        """
        Used by the Trace functionality.

        Measures for duration_s seconds and returns average current in nA.

        - If the requested dwell time for a trace step is shorter than or equal to the
          Keithley measurement interval (set via the interval spin box in the UI),
          a single reading is taken.
        - If the dwell time exceeds this interval, several readings are taken over the
          dwell период and the mean value is returned.
        """
        if duration_s <= 0:
            duration_s = 0.1

        if not self.connect_instrument(show_errors_in_ui=True):
            return None

        base_interval = max(0.1, float(self.interval_spin.value()))

        # Short dwell times: one representative measurement is enough.
        if duration_s <= base_interval:
            val = self.read_current_once()
            self.disconnect_instrument()
            return val

        end_time = time.time() + duration_s
        samples = []
        try:
            while time.time() < end_time:
                val = self.read_current_once()
                if val is not None:
                    samples.append(val)
                    # This runs in the GUI thread during trace, so we can update the display.
                    self.value_display.setText(f"Current: {val:.2f} nA")

                QtWidgets.QApplication.processEvents()

                remaining = end_time - time.time()
                if remaining <= 0:
                    break
                sleep_time = min(base_interval, remaining)
                time.sleep(sleep_time)
        finally:
            self.disconnect_instrument()

        if not samples:
            return None
        return float(np.mean(samples))

    # ---------- OPC for sputter current ----------

    def ensure_opc(self):
        if self.opc_client and self.opc_node:
            return True
        try:
            self.opc_client = Client(self.opc_url)
            self.opc_client.connect()
            self.opc_node = self.opc_client.get_node(self.opc_node_id)
            return True
        except Exception as e:
            print(f"OPC UA connection failed: {e}")
            self.opc_client = None
            self.opc_node = None
            return False

    def update_sputter_current(self):
        if not self.opc_client or not self.opc_node:
            return
        try:
            sputter_current = self.opc_node.get_value()
            self.last_sputter_current = float(sputter_current)
            self.sputter_display.setText(f"Sputter: {self.last_sputter_current:.2f} mA")
        except Exception as e:
            print(f"OPC UA error: {e}")
            self.sputter_display.setText("Sputter: --- mA")

    # ---------- Continuous measurement (now threaded) ----------

    def select_log_file(self):
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Select log file", "", "Text Files (*.txt);;All Files (*)",
            options=options
        )
        if file_path:
            self.log_file_path = file_path
            self.file_label.setText(os.path.basename(file_path))

    def update_window_size(self):
        self.window_size = self.avg_spin.value()

    def calculate_moving_stats(self):
        if len(self.measurements_nA) == 0:
            return None, None
        n = min(self.window_size, len(self.measurements_nA))
        last_n = self.measurements_nA[-n:]
        avg = np.mean(last_n)
        sigma = np.std(last_n)
        return avg, sigma

    def toggle_measurement(self):
        if not self.is_measuring:
            # Start measurement (no log file required)
            if not self.connect_instrument(show_errors_in_ui=True):
                return
            self.ensure_opc()

            self.timestamps = []
            self.measurements_nA = []
            self.sputter_values = []
            self.charge_nC = 0.0
            self.start_time = time.time()
            self.plot_start_time = 0

            # Optional: open/reset log file if path chosen
            if self.log_file_path:
                try:
                    with open(self.log_file_path, 'w') as f:
                        f.write("Timestamp,Elapsed Time (s),Current (nA),Charge (nC),Sputter Current (mA)\n")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Cannot open log file: {e}")
                    self.log_file_path = None  # disable logging for this run

            # Start worker thread
            self.measure_thread = QtCore.QThread(self)
            self.measure_worker = KeithleyWorker(self)
            self.measure_worker.moveToThread(self.measure_thread)
            self.measure_thread.started.connect(self.measure_worker.run)
            self.measure_worker.measurementReady.connect(self.update_measurement_from_worker)
            self.measure_worker.error.connect(self.on_worker_error)
            self.measure_worker.finished.connect(self.on_worker_finished)

            self.is_measuring = True
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.clear_button.setEnabled(True)

            self.measure_thread.start()
        else:
            # Stop measurement
            if self.measure_worker:
                self.measure_worker.stop()

    def clear_graph(self):
        if self.is_measuring and len(self.timestamps) > 0:
            self.plot_start_time = self.timestamps[-1]
            self.update_plot()
        else:
            self.timestamps = []
            self.measurements_nA = []
            self.sputter_values = []
            self.charge_nC = 0.0
            self.plot_start_time = 0
            self.update_plot()

    def update_measurement_from_worker(self, timestamp, elapsed, current_nA):
        """
        Slot called in GUI thread whenever the worker has a new measurement.
        """
        try:
            if len(self.timestamps) > 0:
                dt = elapsed - self.timestamps[-1]
                self.charge_nC += (self.measurements_nA[-1] + current_nA) / 2 * dt

            self.timestamps.append(elapsed)
            self.measurements_nA.append(current_nA)
            self.sputter_values.append(self.last_sputter_current)

            # Limit the in-memory data used for plotting to keep the UI responsive.
            # Only the oldest points are discarded; logging to file remains unaffected.
            if len(self.timestamps) > self.max_display_points:
                excess = len(self.timestamps) - self.max_display_points
                self.timestamps = self.timestamps[excess:]
                self.measurements_nA = self.measurements_nA[excess:]
                self.sputter_values = self.sputter_values[excess:]
                # Keep x-axis window consistent.
                if self.plot_start_time < self.timestamps[0]:
                    self.plot_start_time = self.timestamps[0]

            avg, sigma = self.calculate_moving_stats()

            self.value_display.setText(f"Current: {current_nA:.2f} nA")
            if avg is not None and sigma is not None:
                self.avg_display.setText(f"Avg: {avg:.2f} nA (σ: {sigma:.2f})")
            self.charge_display.setText(f"Charge: {self.charge_nC:.2f} nC")

            self.update_plot()

            # Optional logging within Keithley tab
            if self.log_file_path:
                try:
                    with open(self.log_file_path, 'a') as f:
                        f.write(f"{timestamp},{elapsed:.3f},{current_nA:.2f},"
                                f"{self.charge_nC:.2f},{self.last_sputter_current:.2f}\n")
                except Exception as e:
                    print(f"Log error: {e}")
        except Exception as e:
            print(f"Measurement error: {e}")
            QMessageBox.critical(self, "Error", f"Measurement failed: {str(e)}")
            # Stop gracefully
            self.toggle_measurement()

    def on_worker_error(self, message: str):
        print(f"Keithley worker error: {message}")
        QMessageBox.critical(self, "Keithley error", message)

    def on_worker_finished(self):
        """
        Called when the worker loop exits (either via stop or due to an error).
        """
        self.is_measuring = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.clear_button.setEnabled(bool(self.timestamps))

        if self.measure_thread is not None:
            self.measure_thread.quit()
            self.measure_thread.wait(2000)
            self.measure_thread = None
            self.measure_worker = None

        # Disconnect Keithley instrument
        self.disconnect_instrument()

        # Disconnect OPC if active
        if self.opc_client:
            try:
                self.opc_client.disconnect()
            except Exception:
                pass
            self.opc_client = None
        self.opc_node = None

    def update_plot(self):
        self.ax.clear()
        self.ax2.clear()
        if len(self.timestamps) > 0:
            plot_times = [t - self.plot_start_time for t in self.timestamps if t >= self.plot_start_time]
            plot_values = [v for t, v in zip(self.timestamps, self.measurements_nA) if t >= self.plot_start_time]
            plot_sputter = [s for t, s in zip(self.timestamps, self.sputter_values) if t >= self.plot_start_time]

            if plot_times:
                self.ax.plot(plot_times, plot_values, 'b-')
                self.ax.set_xlabel('Elapsed time (s)')
                self.ax.set_ylabel('Current (nA)')
                self.ax.tick_params(axis='y', labelcolor='b')
                self.ax.grid(True)

                if plot_sputter:
                    self.ax2.plot(plot_times, plot_sputter, 'g-')
                    self.ax2.set_ylabel('Sputter current (mA)')
                    self.ax2.tick_params(axis='y', labelcolor='g')
                    self.ax2.yaxis.set_label_position("right")
                    self.ax2.yaxis.tick_right()

                if len(plot_times) > 1:
                    self.ax.set_xlim(min(plot_times), max(plot_times))
                    self.ax.set_ylim(0, max(plot_values) * 1.1 if max(plot_values) > 0 else 1.0)
        self.canvas.draw()

    def cleanup(self):
        if self.is_measuring:
            self.toggle_measurement()
        self.disconnect_instrument()
        if self.opc_client:
            try:
                self.opc_client.disconnect()
            except Exception:
                pass
            self.opc_client = None
        self.opc_node = None


# ---------- Trace configuration dialog ----------

class TraceConfigDialog(QDialog):
    def __init__(self, parent, traceable_parameters, current_values):
        """
        traceable_parameters: dict key -> {'name', 'min', 'max'}
        current_values: dict key -> current physical value
        """
        super().__init__(parent)
        self.setWindowTitle("Trace configuration")
        self.traceable_parameters = traceable_parameters
        self.current_values = current_values

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.param_combo = QComboBox()
        for key, info in self.traceable_parameters.items():
            self.param_combo.addItem(info["name"], key)
        self.param_combo.currentIndexChanged.connect(self.on_param_changed)

        self.start_spin = QDoubleSpinBox()
        self.stop_spin = QDoubleSpinBox()
        self.step_spin = QDoubleSpinBox()
        for spin in (self.start_spin, self.stop_spin, self.step_spin):
            spin.setDecimals(3)
            spin.setSingleStep(0.1)
        # Allow fine step sizes for tracing down to 0.001
        self.step_spin.setSingleStep(0.001)

        self.dwell_spin = QDoubleSpinBox()
        self.dwell_spin.setDecimals(2)
        self.dwell_spin.setRange(0.1, 600.0)
        self.dwell_spin.setSingleStep(0.5)
        self.dwell_spin.setValue(1.0)

        form.addRow("Parameter:", self.param_combo)
        form.addRow("Start value:", self.start_spin)
        form.addRow("End value:", self.stop_spin)
        form.addRow("Step size:", self.step_spin)
        form.addRow("Measurement time per step [s]:", self.dwell_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.on_param_changed(0)

    def on_param_changed(self, index):
        key = self.param_combo.currentData()
        if not key:
            return
        info = self.traceable_parameters[key]
        cur = self.current_values.get(key, (info["min"] + info["max"]) / 2.0)
        self.start_spin.setRange(info["min"], info["max"])
        self.stop_spin.setRange(info["min"], info["max"])
        # Step size independent of overall parameter range, minimum 0.001
        span = info["max"] - info["min"]
        self.step_spin.setRange(0.001, max(span, 0.001))

        span = info["max"] - info["min"]
        default_start = max(info["min"], cur - span * 0.1)
        default_stop = min(info["max"], cur + span * 0.1)
        if default_stop <= default_start:
            default_start = info["min"]
            default_stop = info["max"]

        self.start_spin.setValue(default_start)
        self.stop_spin.setValue(default_stop)
        self.step_spin.setValue((default_stop - default_start) / 20.0)

    def get_config(self):
        key = self.param_combo.currentData()
        return {
            "param_key": key,
            "start": self.start_spin.value(),
            "stop": self.stop_spin.value(),
            "step": self.step_spin.value(),
            "dwell": self.dwell_spin.value(),
        }


# ---------- Trace result dialog (live plot + vertical setting line) ----------

class TraceResultDialog(QDialog):
    def __init__(self, parent, param_name, x_values=None, currents=None, original_value=0.0):
        super().__init__(parent)
        self.setWindowTitle(f"Trace result – {param_name}")
        self.param_name = param_name
        self.x_values = np.array(x_values, dtype=float) if x_values is not None else np.array([], dtype=float)
        self.currents = np.array(currents, dtype=float) if currents is not None else np.array([], dtype=float)
        self.original_value = original_value
        self.accepted_value = None

        self.data_line = None
        self.vline = None
        self.dragging = False
        self.interaction_enabled = False
        self.cid_press = None
        self.cid_release = None
        self.cid_motion = None

        layout = QVBoxLayout(self)

        self.figure = Figure(figsize=(7, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        layout.addWidget(self.canvas)

        info_label = QLabel(
            "During trace: curve is updated live.\n"
            "After trace: drag the vertical red line to choose a setting,\n"
            "then double-click inside the plot to confirm."
        )
        layout.addWidget(info_label)

        self.selected_label = QLabel("Selected value: ---")
        layout.addWidget(self.selected_label)

        # Export controls (enabled after the trace has finished)
        btn_layout = QHBoxLayout()
        self.export_plot_btn = QPushButton("Export plot (.jpx)")
        self.export_data_btn = QPushButton("Export data (.txt)")
        self.export_plot_btn.setEnabled(False)
        self.export_data_btn.setEnabled(False)
        self.export_plot_btn.clicked.connect(self.export_plot)
        self.export_data_btn.clicked.connect(self.export_data)
        btn_layout.addWidget(self.export_plot_btn)
        btn_layout.addWidget(self.export_data_btn)
        layout.addLayout(btn_layout)

        if self.x_values.size > 0:
            self.set_data(self.x_values, self.currents)

    def set_data(self, x_values, currents):
        """Update plot data (used during live trace)."""
        self.x_values = np.array(x_values, dtype=float)
        self.currents = np.array(currents, dtype=float)

        if self.data_line is None:
            self.data_line, = self.ax.plot(self.x_values, self.currents, 'b.-')
        else:
            self.data_line.set_data(self.x_values, self.currents)

        self.ax.relim()
        self.ax.autoscale_view()
        self.ax.set_xlabel(self.param_name)
        self.ax.set_ylabel("Current [nA]")
        self.ax.grid(True)
        self.canvas.draw_idle()

    def enable_interaction(self):
        """Enable vertical line and mouse interaction after trace is finished."""
        if self.interaction_enabled:
            return
        if self.x_values.size == 0:
            return

        max_idx = int(np.argmax(self.currents))
        x0 = float(self.x_values[max_idx])

        self.vline = self.ax.axvline(x=x0, color='r', linestyle='--')
        self.update_selected_label(x0)
        self.canvas.draw()

        self.cid_press = self.canvas.mpl_connect('button_press_event', self.on_press)
        self.cid_release = self.canvas.mpl_connect('button_release_event', self.on_release)
        self.cid_motion = self.canvas.mpl_connect('motion_notify_event', self.on_motion)

        # Enable exporting once the full trace has been acquired.
        self.set_export_enabled(True)

        self.interaction_enabled = True

    def update_selected_label(self, x_val):
        self.selected_label.setText(f"Selected {self.param_name}: {x_val:.3f}")

    def set_export_enabled(self, enabled: bool):
        """Enable or disable the export buttons."""
        self.export_plot_btn.setEnabled(enabled)
        self.export_data_btn.setEnabled(enabled)

    def export_plot(self):
        """Export the current trace plot as an image (.jpx by default)."""
        if self.x_values.size == 0:
            QMessageBox.warning(self, "Export plot", "No data available to export.")
            return

        default_name = f"trace_{self.param_name.replace(' ', '_')}.jpx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export plot",
            default_name,
            "JPEG image (*.jpx);;PNG image (*.png);;All files (*)"
        )
        if not file_path:
            return

        try:
            # If the user did not specify an extension, append .jpx
            if "." not in os.path.basename(file_path):
                file_path += ".jpx"
            self.figure.savefig(file_path, dpi=300)
            QMessageBox.information(self, "Export plot", f"Plot was saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export plot", f"Error while saving plot:\n{e}")

    def export_data(self):
        """Export the numerical trace data as a text file (.txt)."""
        if self.x_values.size == 0:
            QMessageBox.warning(self, "Export data", "No data available to export.")
            return

        default_name = f"trace_{self.param_name.replace(' ', '_')}.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export data",
            default_name,
            "Text file (*.txt);;All files (*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# Trace data for {self.param_name}\n")
                f.write("# Value\tCurrent_nA\n")
                for x, y in zip(self.x_values, self.currents):
                    if np.isnan(y):
                        continue
                    f.write(f"{x:.6f}\t{y:.6f}\n")
            QMessageBox.information(self, "Export data", f"Data were saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export data", f"Error while saving data:\n{e}")

    def on_press(self, event):
        if not self.interaction_enabled or event.inaxes != self.ax:
            return
        # Double click = confirm current line position
        if event.dblclick and event.button == 1:
            self.on_double_click(event)
            return

        x_line = self.vline.get_xdata()[0]
        if event.xdata is None:
            return

        # Check if click is close enough to the vertical line (5% of x-range)
        x_min, x_max = self.ax.get_xlim()
        tol = (x_max - x_min) * 0.05
        if abs(event.xdata - x_line) < tol:
            self.dragging = True

    def on_motion(self, event):
        if not self.interaction_enabled or not self.dragging:
            return
        if event.inaxes != self.ax or event.xdata is None:
            return
        x_new = event.xdata
        self.vline.set_xdata([x_new, x_new])
        self.update_selected_label(x_new)
        self.canvas.draw_idle()

    def on_release(self, event):
        self.dragging = False

    def on_double_click(self, event):
        if not self.interaction_enabled:
            return
        # Use current vertical line position
        x_line = self.vline.get_xdata()[0]
        diffs = np.abs(self.x_values - x_line)
        idx = int(np.argmin(diffs))
        selected_param = float(self.x_values[idx])
        self.update_selected_label(selected_param)
        msg = QMessageBox.question(
            self,
            "Apply new value?",
            f"Do you want to set a new value for {self.param_name}?\n\n"
            f"Suggested value: {selected_param:.3f}\n"
            f"Old value: {self.original_value:.3f}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if msg == QMessageBox.Yes:
            self.accepted_value = selected_param
            self.accept()


# ---------- Calculator dialog ----------

class CalculatorDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.main = parent  # OPCControlPanel
        self.setWindowTitle("Calculator")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.mass_input = QDoubleSpinBox()
        self.mass_input.setRange(1, 500)
        self.mass_input.setDecimals(2)
        self.mass_input.setValue(1.0)
        self.mass_input.setSuffix(" u")

        self.extraction_input = QDoubleSpinBox()
        self.extraction_input.setRange(0, 100000)
        self.extraction_input.setDecimals(1)
        self.extraction_input.setValue(1000.0)
        self.extraction_input.setSuffix(" V")

        self.sputter_input = QDoubleSpinBox()
        self.sputter_input.setRange(0, 100000)
        self.sputter_input.setDecimals(1)
        self.sputter_input.setValue(1000.0)
        self.sputter_input.setSuffix(" V")

        self.b_field_label = QLabel("0.00 kG")
        self.b_field_label.setStyleSheet("font-weight: bold; color: #2E86C1;")

        self.current_label = QLabel("0.0000 A")
        self.current_label.setStyleSheet("font-weight: bold; color: #27AE60;")

        for spin in (self.mass_input, self.extraction_input, self.sputter_input):
            spin.valueChanged.connect(self.update_calculations)

        form.addRow("Mass:", self.mass_input)
        form.addRow("Extraction Voltage:", self.extraction_input)
        form.addRow("Sputter Voltage:", self.sputter_input)
        form.addRow("Calculated B-field:", self.b_field_label)
        form.addRow("Required current:", self.current_label)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton("Apply to magnet")
        self.apply_btn.clicked.connect(self.apply_to_magnet)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.apply_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self.update_calculations()

    def update_calculations(self):
        try:
            mass_u = self.mass_input.value()
            extraction_v = self.extraction_input.value()
            sputter_v = self.sputter_input.value()

            mass_kg = mass_u * 1.66054e-27
            total_energy_ev = extraction_v + sputter_v

            b_field_tesla = np.sqrt(2 * total_energy_ev * 1.60218e-19 * mass_kg) / (1.60218e-19 * 0.5)
            b_field_kilogauss = b_field_tesla * 10  # 1 T = 10 kG

            current = (b_field_kilogauss - 0.0937) / 0.1055

            self.b_field_label.setText(f"{b_field_kilogauss:.2f} kG")
            self.current_label.setText(f"{current:.4f} A")
        except Exception as e:
            print(f"Calculation error: {e}")
            self.b_field_label.setText("ERR")
            self.current_label.setText("ERR")

    def apply_to_magnet(self):
        if not hasattr(self.main, "magnet_control"):
            QMessageBox.warning(self, "Calculator", "Magnet control not available.")
            return
        current_text = self.current_label.text()
        try:
            current_value = float(current_text.split()[0])
        except Exception:
            QMessageBox.warning(self, "Calculator", "Invalid current value.")
            return

        slider = self.main.magnet_control['slider']
        mult = self.main.magnet_control['multiplier']
        phys_min = slider.minimum() / mult
        phys_max = slider.maximum() / mult

        if current_value < phys_min or current_value > phys_max:
            QMessageBox.warning(
                self,
                "Calculator",
                f"Calculated current {current_value:.4f} A is out of slider range "
                f"[{phys_min:.3f}, {phys_max:.3f}] A."
            )
            return

        slider.setValue(int(round(current_value * mult)))
        QMessageBox.information(self, "Calculator", f"Magnet current set to {current_value:.4f} A.")


# ---------- Popout dialog for Keithley ----------

class KeithleyPopup(QtWidgets.QDialog):
    """
    Simple dialog that temporarily hosts the existing KeithleyWidget.
    """
    def __init__(self, main, widget):
        super().__init__(main)
        self.main = main
        self.widget = widget
        self.setWindowTitle("Keithley")
        self.setAttribute(Qt.WA_DeleteOnClose)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # IMPORTANT: reparent the widget to this dialog, then add to layout
        self.widget.setParent(self)
        layout.addWidget(self.widget)
        self.setLayout(layout)

        # Make sure the widget is visible
        self.widget.show()

    def closeEvent(self, event):
        # When user closes the popout, reattach Keithley into main tabs
        self.main.reattach_keithley_from_window()
        event.accept()


class CombiTabHost(QtWidgets.QWidget):
    """
    Host-Widget, das die COMBI7 RFQ GUI in einen Tab einbettet.

    Die eigentliche Logik (QTimer, SSH, Sockets) lebt in einer
    unsichtbaren Combi7InTab-Instanz; wir zeigen nur deren CentralWidget.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rfq_window = Combi7InTab(parent=self)

        # CentralWidget der RFQ-Window-Instanz herausnehmen und hier einbetten
        central = self.rfq_window.centralWidget()
        if central is not None:
            central.setParent(self)
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(central)
            self.setLayout(layout)

    def cleanup(self):
        """RFQ-Window schließen, damit es seine Verbindungen aufräumen kann."""
        try:
            self.rfq_window.close()
        except Exception:
            pass


class CombiPopup(QtWidgets.QDialog):
    """Popup-Dialog, der den COMBI7-Tab temporär hostet (analog KeithleyPopup)."""
    def __init__(self, main, widget):
        super().__init__(main)
        self.main = main
        self.widget = widget
        self.setWindowTitle("RFQ / COMBI7")
        self.setAttribute(Qt.WA_DeleteOnClose)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Widget in dieses Popup umparenten
        self.widget.setParent(self)
        layout.addWidget(self.widget)
        self.setLayout(layout)

        self.widget.show()

    def closeEvent(self, event):
        # Beim Schließen wieder zurück ins Hauptfenster
        self.main.reattach_combi_from_window()
        event.accept()



# ---------- Main window ----------

class OPCControlPanel(QMainWindow):
    # Signals used to send sample motor commands to the background worker
    sampleMoveRequested = QtCore.pyqtSignal(int)
    sampleHomeRequested = QtCore.pyqtSignal()
    sampleStopRequested = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OPC UA Control Panel + Keithley + Magnet")
        self.setGeometry(100, 100, 1200, 950)

        self.client = None
        self.url = "opc.tcp://DESKTOP-UH9J072:4980/Softing_dataFEED_OPC_Suite_Configuration2"

        # OPC UA node/value caches
        self._opc_node_cache = {}
        self._opc_last_values = {}

        self.delta_voltage = 0.0
        self.allowed_steps = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]


        self.logging_active = False
        self.log_file = None

        self.mqtt = MqttClient()
        self.mqtt_lastUpdate = {}
        self.mqtt_staleThresholdMs = 3000

        self.traceable_parameters = {}
        self.in_trace = False
        self.loading_config = False

        # Magnet + Gaussmeter basic state
        self.mag_host = "192.168.0.5"
        self.mag_port = 8462
        self.mag_sock = None
        self.mag_multiplier = 1000
        self.mag_last_current_A = float("nan")
        self.mag_last_voltage_V = float("nan")
        self.mag_last_field_kG = float("nan")

        self.gm_host = "192.168.0.13"
        self.gm_port = 100
        self.gm_sock = None
        self._gm_write_delay = 0.06
        self._gm_read_idle = 0.25
        self._gm_read_overall = 0.8


        # Sample motor (stepper) configuration
        self.sample_motor_host = "192.168.0.6"
        self.sample_motor_port = 102
        self.sample_position_file = r"C:\Users\ALIS\Desktop\ALIS_LABVIEW\ALIS_Positionen.txt"
        self.sample_position_map = {}

        # Threaded worker that talks to the stepper controller
        self.sample_motor_worker = SampleMotorWorker(self.sample_motor_host, self.sample_motor_port)
        self.sample_motor_thread = QtCore.QThread(self)
        self.sample_motor_worker.moveToThread(self.sample_motor_thread)
        self.sample_motor_thread.started.connect(self.sample_motor_worker.connect_motor)

        # Wire GUI -> worker signals
        self.sampleMoveRequested.connect(self.sample_motor_worker.move_to_position)
        self.sampleHomeRequested.connect(self.sample_motor_worker.go_home)
        self.sampleStopRequested.connect(self.sample_motor_worker.stop_movement)
        self.sample_motor_worker.error.connect(self.on_sample_motor_error)

        self.sample_motor_thread.start()

        # Throttling for OPC writes (to keep UI responsive when moving sliders)
        self.pending_opc_writes = {}
        self.opc_write_timer = QTimer(self)
        self.opc_write_timer.timeout.connect(self.process_pending_opc_writes)
        self.opc_write_timer.start(50)

        # Throttling for magnet setpoints (avoid blocking UI while dragging)
        self.pending_magnet_setpoint = None
        self.magnet_write_timer = QTimer(self)
        self.magnet_write_timer.timeout.connect(self.process_pending_magnet_setpoint)
        self.magnet_write_timer.start(50)

        # Keithley popout state
        self.keithley_detached = False
        self.keithley_popup = None

        # COMBI7 popout state
        self.combi_detached = False
        self.combi_popup = None

        self.init_ui()
        self.connect_opc()
        self.init_mqtt()

        # Magnet measurement timer
        self.mag_measure_timer = QTimer(self)
        self.mag_measure_timer.timeout.connect(self.update_magnet_measurements)
        self.mag_measure_timer.start(1000)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_all)
        self.refresh_timer.start(1000)

    # ---------- UI ----------

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # --- Tab 1: Control ---
        control_tab = QWidget()
        control_layout = QVBoxLayout()
        control_layout.setSpacing(5)
        control_tab.setLayout(control_layout)

                # ---------- Digital controls + sample selection ----------
        upper_row = QHBoxLayout()
        upper_row.setSpacing(15)

        # Left: existing digital controls (OPC)
        bool_group = CollapsibleGroupBox("Digital controls")
        bool_group.setStyleSheet("""
            QGroupBox {
                background-color: #f0f8ff;
                border: 1px solid gray;
                border-radius: 3px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
        """)
        bool_layout = QHBoxLayout()
        # etwas zusammengerückt
        bool_layout.setSpacing(10)

        left_column = QVBoxLayout()
        left_column.setSpacing(3)
        right_column = QVBoxLayout()
        right_column.setSpacing(3)

        self.controls = [
            ("ns=3;s=OPC_1.PLC_GND1/Digital_Out/Attenuator", "Attenuator"),
            ("ns=3;s=OPC_1.PLC_GND1/Digital_Out/Cup1", "Cup1"),
            ("ns=3;s=OPC_1.PLC_GND1/Digital_Out/Cup2", "Cup2"),
            ("ns=3;s=OPC_1.PLC_GND1/Digital_Out/Cup3", "Cup3"),
            ("ns=3;s=OPC_1.PLC_GND1/Digital_Out/Cup4", "Cup4"),
            ("ns=3;s=OPC_1.PLC_GND1/Digital_Out/Cup5", "Cup5"),
            ("ns=3;s=OPC_1.PLC_GND1/Digital_Out/Quick-Cool", "QuickCool"),
        ]
        self.checkboxes = {}

        for node_id, description in self.controls[:4]:
            hbox = QHBoxLayout()
            hbox.setSpacing(5)
            label = QLabel(description)
            checkbox = QCheckBox()
            checkbox.node_id = node_id
            checkbox.stateChanged.connect(self.on_checkbox_changed)
            hbox.addWidget(label)
            hbox.addWidget(checkbox)
            left_column.addLayout(hbox)
            self.checkboxes[node_id] = checkbox

        for node_id, description in self.controls[4:]:
            hbox = QHBoxLayout()
            hbox.setSpacing(5)
            label = QLabel(description)
            checkbox = QCheckBox()
            checkbox.node_id = node_id
            checkbox.stateChanged.connect(self.on_checkbox_changed)
            hbox.addWidget(label)
            hbox.addWidget(checkbox)
            right_column.addLayout(hbox)
            self.checkboxes[node_id] = checkbox

        bool_layout.addLayout(left_column)
        bool_layout.addLayout(right_column)
        bool_group.setLayout(bool_layout)

        upper_row.addWidget(bool_group, 1)

        # Right: sample selection / stepper motor control
        sample_group = QGroupBox("Sample selection")
        sample_group.setStyleSheet("""
            QGroupBox {
                background-color: #fff8dc;
                border: 1px solid gray;
                border-radius: 3px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
        """)
        sample_layout = QFormLayout()
        sample_layout.setVerticalSpacing(4)

        # Combobox for named sample positions
        self.sample_position_combo = QComboBox()
        self.sample_position_combo.setMinimumWidth(180)
        sample_layout.addRow("Choose position:", self.sample_position_combo)

        # Manual adjustment (in steps relative to chosen position)
        self.sample_adjust_spin = QSpinBox()
        self.sample_adjust_spin.setRange(-10000, 10000)
        self.sample_adjust_spin.setValue(0)
        self.sample_adjust_spin.setSuffix(" steps")
        sample_layout.addRow("Manual adjustment:", self.sample_adjust_spin)

        # Buttons: Move / Home / Stop
        btn_row = QHBoxLayout()
        self.sample_move_btn = QPushButton("Move")
        self.sample_home_btn = QPushButton("Home")
        self.sample_stop_btn = QPushButton("Stop")
        self.sample_stop_btn.setStyleSheet("background-color: red; color: white;")

        btn_row.addWidget(self.sample_move_btn)
        btn_row.addWidget(self.sample_home_btn)
        btn_row.addWidget(self.sample_stop_btn)
        sample_layout.addRow(btn_row)

        sample_group.setLayout(sample_layout)

        upper_row.addWidget(sample_group, 0)

        control_layout.addLayout(upper_row)

        # Wire sample selection buttons to local handlers
        self.sample_move_btn.clicked.connect(self.on_sample_move_clicked)
        self.sample_home_btn.clicked.connect(self.on_sample_home_clicked)
        self.sample_stop_btn.clicked.connect(self.on_sample_stop_clicked)

        # Fill combobox from position file
        self.load_sample_positions()


        # ---------- Oven temperature control ----------
        temp_group = CollapsibleGroupBox("Oven temperature control")
        temp_group.setStyleSheet("""
            QGroupBox {
                background-color: #fff0f5;
                border: 1px solid gray;
                border-radius: 3px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
        """)
        temp_layout = QFormLayout()
        temp_layout.setVerticalSpacing(2)
        temp_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.current_control = self.create_slider_control(
            0, 2, 100, "A", default_step=0.01, decimals=2, ramp_step=0.2
        )
        self.current_control['node_id'] = "ns=3;s=OPC_1.PLC_HV/Analog_Out/Out_Cal_Ofen"
        self.current_control['slider'].valueChanged.connect(self.on_current_changed)
        temp_layout.addRow("Oven current [A]:", self.current_control['container'])

        self.temp_display = QLabel("--")
        self.temp_display.setAlignment(Qt.AlignLeft)
        self.temp_display.node_id = "ns=3;s=OPC_1.PLC_HV/Analog_In/In_Cal_Ofen_Temp"
        temp_layout.addRow("Current temperature [°C]:", self.temp_display)

        temp_group.setLayout(temp_layout)
        control_layout.addWidget(temp_group)

        # ---------- Ion source controls ----------
        source_group = CollapsibleGroupBox("Ion source controls")
        source_group.setStyleSheet("""
            QGroupBox {
                background-color: #f0fff0;
                border: 1px solid gray;
                border-radius: 3px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
        """)
        source_layout = QFormLayout()
        source_layout.setVerticalSpacing(1)
        source_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Ionizer indicator FIRST
        self.ionizer_current_display = QLabel("--")
        self.ionizer_current_display.node_id = "ns=3;s=OPC_1.PLC_HV/Analog_In/In_Cal_Ionisierer"
        source_layout.addRow("Ionizer current indicator [A]:", self.ionizer_current_display)

        # Sputter voltage control + indicator
        self.sputter_voltage_control = self.create_slider_control(
            0, 10000, 10, "V", default_step=10.0, decimals=1, ramp_step=10.0
        )
        self.sputter_voltage_control['node_id'] = "ns=3;s=OPC_1.PLC_HV/Analog_Out/Out_Cal_Sputter_U"
        self.sputter_voltage_control['slider'].valueChanged.connect(self.on_voltage_changed)
        source_layout.addRow("Sputter voltage control [V]:", self.sputter_voltage_control['container'])

        self.sputter_voltage_display = QLabel("--")
        self.sputter_voltage_display.node_id = "ns=3;s=OPC_1.PLC_HV/Analog_In/In_Cal_Sputter_U"
        source_layout.addRow("Sputter voltage indicator [V]:", self.sputter_voltage_display)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        source_layout.addRow(separator)

        self.sputter_current_display = QLabel("--")
        self.sputter_current_display.node_id = "ns=3;s=OPC_1.PLC_HV/Analog_In/In_Cal_Sputter_I"
        source_layout.addRow("Sputter current indicator [mA]:", self.sputter_current_display)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        source_layout.addRow(separator)

        self.extraction_voltage_control = self.create_slider_control(
            0, 30000, 10, "V", default_step=10.0, decimals=1, ramp_step=200.0
        )
        self.extraction_voltage_control['node_id'] = "ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Extraktion"
        self.extraction_voltage_control['slider'].valueChanged.connect(self.on_extraction_voltage_changed)
        source_layout.addRow("Extraction voltage control [V]:", self.extraction_voltage_control['container'])

        self.extraction_voltage_display = QLabel("--")
        self.extraction_voltage_display.node_id = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Extraktion"
        source_layout.addRow("Extraction voltage indicator [V]:", self.extraction_voltage_display)

        self.delta_display = QLabel("--")
        source_layout.addRow("Delta voltage [V]:", self.delta_display)

        self.einzellinse_voltage_control = self.create_slider_control(
            0, 30000, 10, "V", default_step=10.0, decimals=1, ramp_step=200.0
        )
        self.einzellinse_voltage_control['node_id'] = "ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Einzellinse"
        self.einzellinse_voltage_control['slider'].valueChanged.connect(self.on_einzellinse_voltage_changed)
        source_layout.addRow("Einzellens 1 voltage control [V]:", self.einzellinse_voltage_control['container'])

        self.einzellinse_voltage_display = QLabel("--")
        self.einzellinse_voltage_display.node_id = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Einzellinse"
        source_layout.addRow("Einzellens 1 voltage indicator [V]:", self.einzellinse_voltage_display)

        source_group.setLayout(source_layout)
        control_layout.addWidget(source_group)

        # ---------- Magnet controls ----------
        magnet_group = CollapsibleGroupBox("Magnet controls")
        magnet_group.setStyleSheet("""
            QGroupBox {
                background-color: #fffbe6;
                border: 1px solid gray;
                border-radius: 3px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
        """)
        magnet_layout = QFormLayout()

        # Magnet set slider + manual input
        self.magnet_control = self.create_slider_control(
            0, 120, self.mag_multiplier, "A", default_step=0.1, decimals=3, ramp_step=0.5
        )
        self.magnet_control['slider'].valueChanged.connect(self.on_magnet_slider_changed)

        self.magnet_direct_input = QDoubleSpinBox()
        self.magnet_direct_input.setRange(0, 120.0)
        self.magnet_direct_input.setDecimals(4)
        self.magnet_direct_input.setSuffix(" A")
        self.magnet_direct_input.setValue(0.0)

        self.magnet_send_btn = QPushButton("Send")
        self.magnet_send_btn.clicked.connect(self.send_magnet_direct_current)

        mag_set_widget = QWidget()
        mag_set_layout = QHBoxLayout()
        mag_set_layout.setContentsMargins(0, 0, 0, 0)
        mag_set_layout.addWidget(self.magnet_control['container'])
        mag_set_layout.addWidget(self.magnet_direct_input)
        mag_set_layout.addWidget(self.magnet_send_btn)
        mag_set_widget.setLayout(mag_set_layout)

        self.magnet_meas_current_label = QLabel("--- A")
        self.magnet_meas_voltage_label = QLabel("--- V")
        self.magnet_field_label = QLabel("--- kG")

        magnet_layout.addRow("Magnet set current [A]:", mag_set_widget)
        magnet_layout.addRow("Measured current [A]:", self.magnet_meas_current_label)
        magnet_layout.addRow("Measured voltage [V]:", self.magnet_meas_voltage_label)
        magnet_layout.addRow("Magnetic field [kG]:", self.magnet_field_label)

        magnet_group.setLayout(magnet_layout)
        control_layout.addWidget(magnet_group)

        # ---------- Ion optics controls ----------
        optics_group = CollapsibleGroupBox("Ion optics controls")
        optics_group.setStyleSheet("""
            QGroupBox {
                background-color: #f5f0ff;
                border: 1px solid gray;
                border-radius: 3px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
        """)
        optics_layout = QFormLayout()
        optics_layout.setVerticalSpacing(1)
        optics_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Lens 2
        self.lens2_voltage_control = self.create_slider_control(
            0, 12500, 10, "V", default_step=10.0, decimals=1, ramp_step=100.0
        )
        self.lens2_voltage_control['node_id'] = "ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Linse2"
        self.lens2_voltage_control['slider'].valueChanged.connect(self.on_voltage_changed)
        optics_layout.addRow("Lens 2 voltage control [V]:", self.lens2_voltage_control['container'])

        self.lens2_voltage_display = QLabel("--")
        self.lens2_voltage_display.node_id = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Linse2"
        optics_layout.addRow("Lens 2 voltage indicator [V]:", self.lens2_voltage_display)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # Ion cooler
        self.ion_cooler_voltage_control = self.create_slider_control(
            0, 40000, 10, "V", default_step=10.0, decimals=1, ramp_step=200.0
        )
        self.ion_cooler_voltage_control['node_id'] = "ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Ionenkuehler"
        self.ion_cooler_voltage_control['slider'].valueChanged.connect(self.on_voltage_changed)
        optics_layout.addRow("Ion cooler voltage control [V]:", self.ion_cooler_voltage_control['container'])

        self.ion_cooler_voltage_display = QLabel("--")
        self.ion_cooler_voltage_display.node_id = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Ionenkuehler"
        optics_layout.addRow("Ion cooler voltage indicator [V]:", self.ion_cooler_voltage_display)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # MQTT status
        self.mqtt_status_label = QLabel("MQTT: not connected")
        optics_layout.addRow("MQTT status:", self.mqtt_status_label)

        # Guidefield 1
        self.psu1_mqtt_control = self.create_slider_control(
            0, 30, 10, "V", default_step=0.1, decimals=1, ramp_step=1.0
        )
        self.psu1_mqtt_meas_v = QLabel("-- V")
        optics_layout.addRow("Guidefield 1 set [V]:", self.psu1_mqtt_control['container'])
        optics_layout.addRow("Guidefield 1 meas. [V]:", self.psu1_mqtt_meas_v)

        # Guidefield 2
        self.psu2_mqtt_control = self.create_slider_control(
            0, 75, 10, "V", default_step=0.1, decimals=1, ramp_step=1.0
        )
        self.psu2_mqtt_meas_v = QLabel("-- V")
        optics_layout.addRow("Guidefield 2 set [V]:", self.psu2_mqtt_control['container'])
        optics_layout.addRow("Guidefield 2 meas. [V]:", self.psu2_mqtt_meas_v)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # HV1
        self.hv1_mqtt_control = self.create_slider_control(
            0, 6500, 10, "V", default_step=10.0, decimals=1, ramp_step=200.0
        )
        self.hv1_mqtt_meas_v = QLabel("-- V")
        self.hv1_mqtt_meas_i = QLabel("-- mA")
        optics_layout.addRow("HV1 set [V]:", self.hv1_mqtt_control['container'])
        optics_layout.addRow("HV1 meas. [V]:", self.hv1_mqtt_meas_v)
        optics_layout.addRow("HV1 meas. [mA]:", self.hv1_mqtt_meas_i)

        # HV4
        self.hv4_mqtt_control = self.create_slider_control(
            0, 6500, 10, "V", default_step=10.0, decimals=1, ramp_step=200.0
        )
        self.hv4_mqtt_meas_v = QLabel("-- V")
        self.hv4_mqtt_meas_i = QLabel("-- mA")
        optics_layout.addRow("HV4 set [V]:", self.hv4_mqtt_control['container'])
        optics_layout.addRow("HV4 meas. [V]:", self.hv4_mqtt_meas_v)
        optics_layout.addRow("HV4 meas. [mA]:", self.hv4_mqtt_meas_i)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # Quadrupoles
        self.quad1_voltage_control = self.create_slider_control(
            0, 6000, 10, "V", default_step=10.0, decimals=1, ramp_step=100.0
        )
        self.quad1_voltage_control['node_id'] = "ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Quad1"
        self.quad1_voltage_control['slider'].valueChanged.connect(self.on_voltage_changed)
        optics_layout.addRow("Quadrupole 1 voltage control [V]:", self.quad1_voltage_control['container'])

        self.quad1_voltage_display = QLabel("--")
        self.quad1_voltage_display.node_id = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Quad1"
        optics_layout.addRow("Quadrupole 1 voltage indicator [V]:", self.quad1_voltage_display)

        self.quad2_voltage_control = self.create_slider_control(
            0, 6000, 10, "V", default_step=10.0, decimals=1, ramp_step=100.0
        )
        self.quad2_voltage_control['node_id'] = "ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Quad2"
        self.quad2_voltage_control['slider'].valueChanged.connect(self.on_voltage_changed)
        optics_layout.addRow("Quadrupole 2 voltage control [V]:", self.quad2_voltage_control['container'])

        self.quad2_voltage_display = QLabel("--")
        self.quad2_voltage_display.node_id = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Quad2"
        optics_layout.addRow("Quadrupole 2 voltage indicator [V]:", self.quad2_voltage_display)

        self.quad3_voltage_control = self.create_slider_control(
            0, 6000, 10, "V", default_step=10.0, decimals=1, ramp_step=100.0
        )
        self.quad3_voltage_control['node_id'] = "ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Quad3"
        self.quad3_voltage_control['slider'].valueChanged.connect(self.on_voltage_changed)
        optics_layout.addRow("Quadrupole 3 voltage control [V]:", self.quad3_voltage_control['container'])

        self.quad3_voltage_display = QLabel("--")
        self.quad3_voltage_display.node_id = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Quad3"
        optics_layout.addRow("Quadrupole 3 voltage indicator [V]:", self.quad3_voltage_display)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # ESA
        self.esa_voltage_control = self.create_slider_control(
            0, 3000, 10, "V", default_step=10.0, decimals=1, ramp_step=50.0
        )
        self.esa_voltage_control['node_id'] = "ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_ESA"
        self.esa_voltage_control['slider'].valueChanged.connect(self.on_voltage_changed)
        optics_layout.addRow("ESA voltage control [V]:", self.esa_voltage_control['container'])

        self.esa_voltage_display = QLabel("--")
        self.esa_voltage_display.node_id = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_ESA"
        optics_layout.addRow("ESA voltage indicator [V]:", self.esa_voltage_display)

        self.esa_correction_control = self.create_slider_control(
            0, 1000, 10, "V", default_step=10.0, decimals=1, ramp_step=20.0
        )
        self.esa_correction_control['node_id'] = "ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_ESA_Z"
        self.esa_correction_control['slider'].valueChanged.connect(self.on_voltage_changed)
        optics_layout.addRow("ESA correction voltage control [V]:", self.esa_correction_control['container'])

        self.esa_correction_display = QLabel("--")
        self.esa_correction_display.node_id = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_ESA_Z"
        optics_layout.addRow("ESA correction voltage indicator [V]:", self.esa_correction_display)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # Lens 4
        self.lens4_voltage_control = self.create_slider_control(
            0, 10000, 10, "V", default_step=10.0, decimals=1, ramp_step=100.0
        )
        self.lens4_voltage_control['node_id'] = "ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Linse4"
        self.lens4_voltage_control['slider'].valueChanged.connect(self.on_voltage_changed)
        optics_layout.addRow("Lens 4 voltage control [V]:", self.lens4_voltage_control['container'])

        self.lens4_voltage_display = QLabel("--")
        self.lens4_voltage_display.node_id = "ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Linse4"
        optics_layout.addRow("Lens 4 voltage indicator [V]:", self.lens4_voltage_display)

        optics_group.setLayout(optics_layout)
        control_layout.addWidget(optics_group)

        # ---------- Status + buttons ----------
        self.status_label = QLabel("Status: Not connected")
        control_layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(5)
        self.refresh_btn = QPushButton("Refresh now")
        self.refresh_btn.clicked.connect(self.refresh_all)

        self.connect_btn = QPushButton("Reconnect OPC")
        self.connect_btn.clicked.connect(self.reconnect_opc)

        self.log_btn = QPushButton("Start logging")
        self.log_btn.setCheckable(True)
        self.log_btn.clicked.connect(self.toggle_logging)

        self.config_btn = QPushButton("Save config")
        self.config_btn.clicked.connect(self.save_config)

        self.load_config_btn = QPushButton("Load config")
        self.load_config_btn.clicked.connect(self.load_config)

        self.trace_btn = QPushButton("Trace…")
        self.trace_btn.clicked.connect(self.start_trace_dialog)

        self.keithley_pop_btn = QPushButton("Pop out Keithley")
        self.keithley_pop_btn.clicked.connect(self.toggle_keithley_popout)

        self.combi_pop_btn = QPushButton("Pop out RFQ/COMBI7")
        self.combi_pop_btn.clicked.connect(self.toggle_combi_popout)

        self.calc_btn = QPushButton("Calculator")
        self.calc_btn.clicked.connect(self.open_calculator)

        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.connect_btn)
        btn_layout.addWidget(self.log_btn)
        btn_layout.addWidget(self.config_btn)
        btn_layout.addWidget(self.load_config_btn)
        btn_layout.addWidget(self.trace_btn)
        btn_layout.addWidget(self.keithley_pop_btn)
        btn_layout.addWidget(self.combi_pop_btn)
        btn_layout.addWidget(self.calc_btn)

        control_layout.addLayout(btn_layout)

        self.tabs.addTab(control_tab, "Control")

        # --- Tab 2: Keithley ---
        self.keithley_widget = KeithleyWidget(self)
        self.tabs.addTab(self.keithley_widget, "Keithley")

        # --- Tab 3: RFQ / COMBI7 ---
        self.combi_tab = CombiTabHost(self)
        self.tabs.addTab(self.combi_tab, "RFQ / COMBI7")

        # Setup traceable parameters (includes magnet now)
        self.setup_traceable_parameters()

    # ---------- Traceable parameters ----------

    def setup_traceable_parameters(self):
        def phys_min_max(ctrl):
            return (
                ctrl['slider'].minimum() / ctrl['multiplier'],
                ctrl['slider'].maximum() / ctrl['multiplier'],
            )

        self.traceable_parameters = {}

        # OPC analog sliders
        for key, name, ctrl in [
            ("oven_current", "Oven current [A]", self.current_control),
            ("sputter_voltage", "Sputter voltage [V]", self.sputter_voltage_control),
            ("extraction_voltage", "Extraction voltage [V]", self.extraction_voltage_control),
            ("einzellinse_voltage", "Einzellens 1 voltage [V]", self.einzellinse_voltage_control),
            ("lens2_voltage", "Lens 2 voltage [V]", self.lens2_voltage_control),
            ("ion_cooler_voltage", "Ion cooler voltage [V]", self.ion_cooler_voltage_control),
            ("quad1_voltage", "Quadrupole 1 voltage [V]", self.quad1_voltage_control),
            ("quad2_voltage", "Quadrupole 2 voltage [V]", self.quad2_voltage_control),
            ("quad3_voltage", "Quadrupole 3 voltage [V]", self.quad3_voltage_control),
            ("esa_voltage", "ESA voltage [V]", self.esa_voltage_control),
            ("esa_corr_voltage", "ESA correction voltage [V]", self.esa_correction_control),
            ("lens4_voltage", "Lens 4 voltage [V]", self.lens4_voltage_control),
        ]:
            vmin, vmax = phys_min_max(ctrl)
            self.traceable_parameters[key] = {
                "name": name,
                "control": ctrl,
                "min": vmin,
                "max": vmax,
            }

        # MQTT analog sliders
        for key, name, ctrl in [
            ("guidefield1", "Guidefield 1 [V]", self.psu1_mqtt_control),
            ("guidefield2", "Guidefield 2 [V]", self.psu2_mqtt_control),
            ("hv1", "HV1 [V]", self.hv1_mqtt_control),
            ("hv4", "HV4 [V]", self.hv4_mqtt_control),
        ]:
            vmin, vmax = phys_min_max(ctrl)
            self.traceable_parameters[key] = {
                "name": name,
                "control": ctrl,
                "min": vmin,
                "max": vmax,
            }

        # Magnet PSU current (from main tab)
        slider = self.magnet_control['slider']
        mult = self.magnet_control['multiplier']
        vmin = slider.minimum() / mult
        vmax = slider.maximum() / mult
        self.traceable_parameters["magnet_current"] = {
            "name": "Magnet current [A]",
            "control": {
                "slider": slider,
                "multiplier": mult,
            },
            "min": vmin,
            "max": vmax,
        }

    # ---------- Slider factory ----------

    def create_slider_control(self, min_val, max_val, multiplier, unit,
                              default_step=1.0, decimals=1, ramp_step=None):
        container = QWidget()
        layout = QHBoxLayout()
        layout.setSpacing(3)
        layout.setContentsMargins(0, 0, 0, 0)
        container.setLayout(layout)

        decrease_btn = QPushButton("◀")
        decrease_btn.setFixedWidth(25)

        slider = ScrollableSlider()
        slider.setMinimum(round(min_val * multiplier))
        slider.setMaximum(round(max_val * multiplier))
        slider.setFixedWidth(180)
        slider.setSingleStep(1)

        increase_btn = QPushButton("▶")
        increase_btn.setFixedWidth(25)

        step_selector = QComboBox()
        step_selector.setFixedWidth(60)
        for step in self.allowed_steps:
            step_selector.addItem(format(step, "g"), step)
        default_index = self.allowed_steps.index(default_step) if default_step in self.allowed_steps else 1
        step_selector.setCurrentIndex(default_index)

        value_label = QLabel(f"{min_val:.{decimals}f} {unit}")
        value_label.setStyleSheet("font-weight: bold;")
        value_label.setFixedWidth(90)
        value_label.setAlignment(Qt.AlignRight)

        slider.control = {
            'step_selector': step_selector,
            'multiplier': multiplier
        }

        def update_value(value):
            real_value = value / multiplier
            value_label.setText(f"{real_value:.{decimals}f} {unit}")

        def step_ticks():
            val = step_selector.currentData()
            if val is None:
                val = float(step_selector.currentText().replace(",", "."))
            return max(1, round(val * multiplier))

        def decrease_value():
            slider.setValue(max(slider.minimum(), slider.value() - step_ticks()))

        def increase_value():
            slider.setValue(min(slider.maximum(), slider.value() + step_ticks()))

        slider.valueChanged.connect(update_value)
        decrease_btn.clicked.connect(decrease_value)
        increase_btn.clicked.connect(increase_value)

        layout.addWidget(decrease_btn)
        layout.addWidget(slider)
        layout.addWidget(increase_btn)
        layout.addWidget(step_selector)
        layout.addWidget(value_label)

        return {
            'container': container,
            'slider': slider,
            'decrease_btn': decrease_btn,
            'increase_btn': increase_btn,
            'step_selector': step_selector,
            'value_label': value_label,
            'multiplier': multiplier,
            'ramp_step': ramp_step
        }

    # ---------- OPC write throttling ----------

    def schedule_opc_write(self, node_id, value, variant_type=None):
        """
        Queue einen OPC-Write, aber nur wenn sich der Wert wirklich geändert hat.
        Das letzte Paar (node_id -> value) wird von process_pending_opc_writes()
        in sinnvollen Abständen rausgeschrieben.
        """
        if not self.client:
            return

        last = self._opc_last_values.get(node_id, None)

        # Float-Vergleich mit Toleranz
        if isinstance(value, float) and isinstance(last, float):
            if abs(value - last) < 1e-6:
                # Nichts zu tun – evtl. geplanten Write wieder entfernen
                self.pending_opc_writes.pop(node_id, None)
                return
        else:
            if value == last:
                self.pending_opc_writes.pop(node_id, None)
                return

        # Nur wenn sich der Wert geändert hat, wird geschrieben
        self.pending_opc_writes[node_id] = (value, variant_type)

    def process_pending_opc_writes(self):
        """Send queued OPC writes in a batch. Called regelmäßig von einem QTimer."""
        if not self.client or not self.pending_opc_writes:
            return
        items = list(self.pending_opc_writes.items())
        self.pending_opc_writes.clear()
        try:
            for node_id, (value, variant_type) in items:
                node = self.get_node_cached(node_id)
                if variant_type is None:
                    node.set_value(value)
                else:
                    node.set_value(value, variant_type)
                # Erfolgreich geschrieben -> als "last known" merken
                self._opc_last_values[node_id] = value
        except Exception as e:
            self.status_label.setText(f"OPC write error: {e}")

    # ---------- OPC connection ----------

    def get_node_cached(self, node_id):
        """
        Liefert einen gecachten OPC-Node für die angegebene node_id.
        Beim ersten Zugriff wird der Node vom Client geholt und gemerkt.
        """
        if not self.client:
            raise RuntimeError("OPC client is not connected")

        node = self._opc_node_cache.get(node_id)
        if node is None:
            node = self.client.get_node(node_id)
            self._opc_node_cache[node_id] = node
        return node

    def read_node_values(self, node_ids):
        """
        Lies mehrere OPC-Nodes in einem Roundtrip und gib ein dict node_id -> value zurück.
        Nutzt get_node_cached() und client.get_values().
        """
        if not self.client or not node_ids:
            return {}

        # Reihenfolge stabil halten
        nodes = [self.get_node_cached(nid) for nid in node_ids]
        values = self.client.get_values(nodes)

        result = {}
        for nid, val in zip(node_ids, values):
            self._opc_last_values[nid] = val
            result[nid] = val
        return result


    def connect_opc(self):
        try:
            if self.client:
                self.client.disconnect()

            # Reset OPC caches on (re)connect
            self._opc_node_cache.clear()
            self._opc_last_values.clear()

            self.client = Client(self.url)
            self.client.connect()
            self.status_label.setText("Status: Connected")
            self.refresh_all()
        except Exception as e:
            self.status_label.setText(f"Status: Connection failed – {str(e)}")

    def reconnect_opc(self):
        self.connect_opc()

    # ---------- Logging ----------

    def toggle_logging(self):
        if self.log_btn.isChecked():
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Select log file", "", "Text Files (*.txt);;All Files (*)"
            )
            if not file_path:
                self.log_btn.setChecked(False)
                return
            try:
                self.log_file = open(file_path, "w")
                header = "Timestamp\t"
                for _, description in self.controls:
                    header += f"{description}\t"
                indicators = [
                    ("OvenTemp", self.temp_display),
                    ("SputterV", self.sputter_voltage_display),
                    ("SputterI", self.sputter_current_display),
                    ("IonizerI", self.ionizer_current_display),
                    ("ExtractV", self.extraction_voltage_display),
                    ("Einzellens1V", self.einzellinse_voltage_display),
                    ("Lens2V", self.lens2_voltage_display),
                    ("IonCoolerV", self.ion_cooler_voltage_display),
                    ("Quad1V", self.quad1_voltage_display),
                    ("Quad2V", self.quad2_voltage_display),
                    ("Quad3V", self.quad3_voltage_display),
                    ("ESAV", self.esa_voltage_display),
                    ("ESACorrV", self.esa_correction_display),
                    ("Lens4V", self.lens4_voltage_display)
                ]
                for name, _ in indicators:
                    header += f"{name}\t"
                mqtt_headers = [
                    "GF1_Set", "GF1_Meas_V",
                    "GF2_Set", "GF2_Meas_V",
                    "HV1_Set", "HV1_Meas_V", "HV1_Meas_I",
                    "HV4_Set", "HV4_Meas_V", "HV4_Meas_I"
                ]
                for name in mqtt_headers:
                    header += f"{name}\t"

                # Magnet additions
                magnet_headers = ["MagnetCurrentSet_A", "MagnetField_kG"]
                for name in magnet_headers:
                    header += f"{name}\t"

                # Keithley additions
                keithley_headers = [
                    "KeithleyCurrent_nA",
                    "KeithleyAvg_nA",
                    "KeithleySigma_nA",
                    "KeithleyCharge_nC",
                    "KeithleySputter_mA"
                ]
                for name in keithley_headers:
                    header += f"{name}\t"

                self.log_file.write(header.rstrip() + "\n")
                self.logging_active = True
                self.log_btn.setText("Stop logging")
                self.status_label.setText(f"Status: Logging to {file_path}")
            except Exception as e:
                self.log_btn.setChecked(False)
                self.status_label.setText(f"Error opening log file: {str(e)}")
        else:
            if self.log_file:
                try:
                    self.log_file.close()
                except Exception:
                    pass
                self.log_file = None
            self.logging_active = False
            self.log_btn.setText("Start logging")
            self.status_label.setText("Status: Logging stopped")

    def write_log_entry(self):
        if not self.logging_active or not self.client or not self.log_file:
            return

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_line = f"{timestamp}\t"

            # Digitale Ausgänge gesammelt lesen
            dig_node_ids = [node_id for node_id, _ in self.controls]
            dig_values = self.read_node_values(dig_node_ids)
            for node_id in dig_node_ids:
                value = dig_values.get(node_id, None)
                log_line += f"{value}\t"

            indicators = [
                self.temp_display, self.sputter_voltage_display,
                self.sputter_current_display, self.ionizer_current_display,
                self.extraction_voltage_display, self.einzellinse_voltage_display,
                self.lens2_voltage_display, self.ion_cooler_voltage_display,
                self.quad1_voltage_display, self.quad2_voltage_display,
                self.quad3_voltage_display, self.esa_voltage_display,
                self.esa_correction_display, self.lens4_voltage_display
            ]

            # Alle Analog-Anzeigen in einem Rutsch lesen
            ind_node_ids = [ind.node_id for ind in indicators]
            ind_values = self.read_node_values(ind_node_ids)

            for indicator in indicators:
                value = ind_values.get(indicator.node_id, float("nan"))
                log_line += f"{value:.3f}\t"

            def parse_label_float(text):
                part = text.split()[0] if text else ""
                try:
                    return float(part.replace(",", "."))
                except Exception:
                    return float("nan")

            gf1_set = self.psu1_mqtt_control['slider'].value() / self.psu1_mqtt_control['multiplier']
            gf1_meas = parse_label_float(self.psu1_mqtt_meas_v.text())
            gf2_set = self.psu2_mqtt_control['slider'].value() / self.psu2_mqtt_control['multiplier']
            gf2_meas = parse_label_float(self.psu2_mqtt_meas_v.text())
            hv1_set = self.hv1_mqtt_control['slider'].value() / self.hv1_mqtt_control['multiplier']
            hv1_meas_v = parse_label_float(self.hv1_mqtt_meas_v.text())
            hv1_meas_i = parse_label_float(self.hv1_mqtt_meas_i.text())
            hv4_set = self.hv4_mqtt_control['slider'].value() / self.hv4_mqtt_control['multiplier']
            hv4_meas_v = parse_label_float(self.hv4_mqtt_meas_v.text())
            hv4_meas_i = parse_label_float(self.hv4_mqtt_meas_i.text())

            for v in [gf1_set, gf1_meas, gf2_set, gf2_meas,
                      hv1_set, hv1_meas_v, hv1_meas_i,
                      hv4_set, hv4_meas_v, hv4_meas_i]:
                log_line += f"{v:.3f}\t"

            # Magnet data (set current + B-field)
            mag_set = self.magnet_control['slider'].value() / self.magnet_control['multiplier']
            mag_field = getattr(self, "mag_last_field_kG", float("nan"))
            for v in [mag_set, mag_field]:
                log_line += f"{v:.6f}\t"

            # Keithley data (if measurement is active)
            kw = self.keithley_widget
            if kw.measurements_nA:
                current_nA = kw.measurements_nA[-1]
                avg_nA, sigma_nA = kw.calculate_moving_stats()
                if avg_nA is None:
                    avg_nA = float("nan")
                if sigma_nA is None:
                    sigma_nA = float("nan")
                charge_nC = kw.charge_nC
                sputter_mA = kw.last_sputter_current
            else:
                current_nA = avg_nA = sigma_nA = charge_nC = sputter_mA = float("nan")

            for v in [current_nA, avg_nA, sigma_nA, charge_nC, sputter_mA]:
                log_line += f"{v:.6f}\t"

            self.log_file.write(log_line.rstrip() + "\n")
            self.log_file.flush()
        except Exception as e:
            self.status_label.setText(f"Logging error: {str(e)}")

    # ---------- Save config ----------

    def save_config(self):
        os.makedirs(CONFIG_BASE_DIR, exist_ok=True)
        default_path = os.path.join(CONFIG_BASE_DIR, "config.txt")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save configuration",
            default_path,
            "Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# Config saved {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

                f.write("[DIGITAL]\n")
                for node_id, description in self.controls:
                    val = 1 if self.checkboxes[node_id].isChecked() else 0
                    f.write(f"{description}={val}\n")

                def control_value(ctrl):
                    return ctrl['slider'].value() / ctrl['multiplier']

                f.write("\n[ANALOG_OPC]\n")
                f.write(f"OvenCurrent={control_value(self.current_control):.6f}\n")
                f.write(f"SputterVoltage={control_value(self.sputter_voltage_control):.6f}\n")
                f.write(f"ExtractionVoltage={control_value(self.extraction_voltage_control):.6f}\n")
                f.write(f"EinzellinseVoltage={control_value(self.einzellinse_voltage_control):.6f}\n")
                f.write(f"Lens2Voltage={control_value(self.lens2_voltage_control):.6f}\n")
                f.write(f"IonCoolerVoltage={control_value(self.ion_cooler_voltage_control):.6f}\n")
                f.write(f"Quad1Voltage={control_value(self.quad1_voltage_control):.6f}\n")
                f.write(f"Quad2Voltage={control_value(self.quad2_voltage_control):.6f}\n")
                f.write(f"Quad3Voltage={control_value(self.quad3_voltage_control):.6f}\n")
                f.write(f"ESAVoltage={control_value(self.esa_voltage_control):.6f}\n")
                f.write(f"ESACorrVoltage={control_value(self.esa_correction_control):.6f}\n")
                f.write(f"Lens4Voltage={control_value(self.lens4_voltage_control):.6f}\n")
                f.write(f"DeltaVoltage={self.delta_voltage:.6f}\n")

                f.write("\n[MQTT_SETPOINTS]\n")
                f.write(f"Guidefield1={control_value(self.psu1_mqtt_control):.6f}\n")
                f.write(f"Guidefield2={control_value(self.psu2_mqtt_control):.6f}\n")
                f.write(f"HV1={control_value(self.hv1_mqtt_control):.6f}\n")
                f.write(f"HV4={control_value(self.hv4_mqtt_control):.6f}\n")

                # Magnet config
                f.write("\n[MAGNET]\n")
                mag_set = self.magnet_control['slider'].value() / self.magnet_control['multiplier']
                f.write(f"MagnetCurrent={mag_set:.6f}\n")

            self.status_label.setText(f"Config saved to {file_path}")
        except Exception as e:
            self.status_label.setText(f"Error saving config: {e}")

    # ---------- Load config (with ramping) ----------

    def load_config(self):
        os.makedirs(CONFIG_BASE_DIR, exist_ok=True)
        default_path = CONFIG_BASE_DIR
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load configuration",
            default_path,
            "Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return

        digital_cfg, analog_cfg, mqtt_cfg, magnet_cfg = self._read_config_file(file_path)
        if digital_cfg is None:
            QMessageBox.warning(self, "Config", "Could not read config file.")
            return

        reply = QMessageBox.question(
            self,
            "Load configuration",
            "Load configuration and ramp values stepwise to the targets?\n"
            "This will change the current setpoints.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        if not self.client:
            self.connect_opc()
            if not self.client:
                QMessageBox.warning(self, "Config", "OPC connection is not available.")
                return

        self.loading_config = True
        self.refresh_timer.stop()
        self.status_label.setText(f"Loading config {os.path.basename(file_path)} ...")

        try:
            # OPC analog
            analog_map = {
                "OvenCurrent": self.current_control,
                "SputterVoltage": self.sputter_voltage_control,
                "ExtractionVoltage": self.extraction_voltage_control,
                "EinzellinseVoltage": self.einzellinse_voltage_control,
                "Lens2Voltage": self.lens2_voltage_control,
                "IonCoolerVoltage": self.ion_cooler_voltage_control,
                "Quad1Voltage": self.quad1_voltage_control,
                "Quad2Voltage": self.quad2_voltage_control,
                "Quad3Voltage": self.quad3_voltage_control,
                "ESAVoltage": self.esa_voltage_control,
                "ESACorrVoltage": self.esa_correction_control,
                "Lens4Voltage": self.lens4_voltage_control,
            }

            for name, target in analog_cfg.items():
                ctrl = analog_map.get(name)
                if not ctrl:
                    continue
                self._ramp_control_to(ctrl, target)

            # Recompute delta (from extraction + Einzellinse)
            extr_val = self.extraction_voltage_control['slider'].value() / self.extraction_voltage_control['multiplier']
            einz_val = self.einzellinse_voltage_control['slider'].value() / self.einzellinse_voltage_control['multiplier']
            self.delta_voltage = einz_val - extr_val
            self.delta_display.setText(f"{self.delta_voltage:.1f} V")

            # MQTT analog
            mqtt_map = {
                "Guidefield1": self.psu1_mqtt_control,
                "Guidefield2": self.psu2_mqtt_control,
                "HV1": self.hv1_mqtt_control,
                "HV4": self.hv4_mqtt_control,
            }
            for name, target in mqtt_cfg.items():
                ctrl = mqtt_map.get(name)
                if not ctrl:
                    continue
                self._ramp_control_to(ctrl, target)

            # Magnet current
            if magnet_cfg:
                target = magnet_cfg.get("MagnetCurrent", None)
                if target is not None:
                    mag_ctrl = self.magnet_control
                    if mag_ctrl.get('ramp_step') is None:
                        mag_ctrl['ramp_step'] = 0.5
                    self._ramp_control_to(mag_ctrl, target)

            # Digital outputs
            for node_id, description in self.controls:
                if description in digital_cfg:
                    self.checkboxes[node_id].setChecked(bool(digital_cfg[description]))

            self.status_label.setText(f"Config {os.path.basename(file_path)} loaded.")
        except Exception as e:
            self.status_label.setText(f"Error while loading config: {e}")
        finally:
            self.loading_config = False
            self.refresh_timer.start(1000)

    def _read_config_file(self, path):
        digital = {}
        analog = {}
        mqtt_vals = {}
        magnet_vals = {}
        section = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        section = line[1:-1].strip().upper()
                        continue
                    if "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if section == "DIGITAL":
                        try:
                            digital[key] = int(val)
                        except Exception:
                            pass
                    elif section == "ANALOG_OPC":
                        try:
                            analog[key] = float(val.replace(",", "."))
                        except Exception:
                            pass
                    elif section == "MQTT_SETPOINTS":
                        try:
                            mqtt_vals[key] = float(val.replace(",", "."))
                        except Exception:
                            pass
                    elif section == "MAGNET":
                        try:
                            magnet_vals[key] = float(val.replace(",", "."))
                        except Exception:
                            pass
            return digital, analog, mqtt_vals, magnet_vals
        except Exception as e:
            print(f"Config read error: {e}")
            return None, None, None, None

    def _ramp_control_to(self, control, target_phys, delay=0.05):
        slider = control['slider']
        mult = control['multiplier']
        ramp_step = control.get('ramp_step', None)

        cur_phys = slider.value() / mult
        delta = target_phys - cur_phys
        if abs(delta) < 1e-6:
            return

        if ramp_step is None or ramp_step <= 0:
            n_steps = min(50, max(1, int(abs(delta))))
        else:
            n_steps = max(1, int(np.ceil(abs(delta) / ramp_step)))

        for i in range(1, n_steps + 1):
            new_phys = cur_phys + delta * (i / n_steps)
            slider.setValue(int(round(new_phys * mult)))
            QtWidgets.QApplication.processEvents()
            time.sleep(delay)




# ---------- Sample selection (stepper motor) ----------

    def load_sample_positions(self):
        """
        Load the mapping of sample names to motor positions from the text file
        into the combo box and internal dict.
        """
        self.sample_position_map.clear()
        self.sample_position_combo.clear()
        try:
            with open(self.sample_position_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    name = " ".join(parts[:-1])
                    value = parts[-1]
                    try:
                        position = int(value)
                    except ValueError:
                        # Skip malformed lines
                        continue
                    self.sample_position_map[name] = position
                    self.sample_position_combo.addItem(name)
        except Exception as e:
            QMessageBox.warning(
                self,
                "Sample positions",
                f"Could not load positions from file:\n{self.sample_position_file}\n\n{e}",
            )

        # Leading placeholder entry
        self.sample_position_combo.insertItem(0, "Select position")
        self.sample_position_combo.setCurrentIndex(0)

    def on_sample_move_clicked(self):
        """
        Read the selected sample + manual offset and emit a move request
        for the worker thread.
        """
        if not self.sample_position_map:
            QMessageBox.information(
                self,
                "Sample motor",
                "No sample positions are loaded.",
            )
            return

        name = self.sample_position_combo.currentText()
        if name not in self.sample_position_map:
            QMessageBox.information(
                self,
                "Sample motor",
                "Please choose a valid position.",
            )
            return

        base_position = self.sample_position_map[name]
        adjustment = self.sample_adjust_spin.value()
        target_position = int(base_position + adjustment)

        self.sampleMoveRequested.emit(target_position)

    def on_sample_home_clicked(self):
        """Emit a home command for the sample motor worker."""
        self.sampleHomeRequested.emit()

    def on_sample_stop_clicked(self):
        """Emit a stop command for the sample motor worker."""
        self.sampleStopRequested.emit()

    def on_sample_motor_error(self, message: str):
        """Display errors coming back from the stepper motor worker."""
        QMessageBox.warning(self, "Sample motor error", message)




    # ---------- Checkbox / slider callbacks ----------

    def on_checkbox_changed(self, state):
        checkbox = self.sender()
        if not self.client:
            self.status_label.setText("Status: Not connected – cannot set value")
            return
        new_value = (state == Qt.Checked)
        # Queue write instead of doing a blocking OPC call on every click
        self.schedule_opc_write(checkbox.node_id, new_value, VariantType.Boolean)

    def on_current_changed(self, value):
        if not self.client:
            self.status_label.setText("Status: Not connected – cannot set value")
            return
        real_value = float(value) / float(self.current_control['multiplier'])
        # Queue write to keep the UI responsive while dragging
        self.schedule_opc_write(self.current_control['node_id'], real_value, VariantType.Float)

    def on_voltage_changed(self, value):
        slider = self.sender()
        control = None
        for c in [
            self.sputter_voltage_control, self.lens2_voltage_control,
            self.ion_cooler_voltage_control, self.quad1_voltage_control,
            self.quad2_voltage_control, self.quad3_voltage_control,
            self.esa_voltage_control, self.esa_correction_control,
            self.lens4_voltage_control
        ]:
            if c['slider'] == slider:
                control = c
                break
        if not control or not self.client:
            self.status_label.setText("Status: Not connected – cannot set value")
            return
        real_value = float(value) / float(control['multiplier'])
        # Queue write instead of blocking on every slider step
        self.schedule_opc_write(control['node_id'], real_value, VariantType.Float)

    def on_extraction_voltage_changed(self, value):
        if not self.client:
            self.status_label.setText("Status: Not connected – cannot set value")
            return
        real_value = float(value) / float(self.extraction_voltage_control['multiplier'])
        # Queue write, avoid blocking while slider is moved
        self.schedule_opc_write(self.extraction_voltage_control['node_id'], real_value, VariantType.Float)
        if not self.loading_config:
            self.update_einzellinse_voltage()

    def on_einzellinse_voltage_changed(self, value):
        if not self.client:
            self.status_label.setText("Status: Not connected – cannot set value")
            return
        real_value = float(value) / float(self.einzellinse_voltage_control['multiplier'])
        # Queue write (no blocking OPC call during slider movement)
        self.schedule_opc_write(self.einzellinse_voltage_control['node_id'], real_value, VariantType.Float)

        extraction_value = self.extraction_voltage_control['slider'].value()
        extraction_voltage = extraction_value / self.extraction_voltage_control['multiplier']
        self.delta_voltage = real_value - extraction_voltage
        self.delta_display.setText(f"{self.delta_voltage:.1f} V")

    def update_einzellinse_voltage(self):
        if not self.client:
            return
        try:
            extraction_value = self.extraction_voltage_control['slider'].value()
            extraction_voltage = extraction_value / self.extraction_voltage_control['multiplier']
            new_einzellinse_voltage = extraction_voltage + self.delta_voltage

            self.einzellinse_voltage_control['slider'].blockSignals(True)
            slider_value = round(new_einzellinse_voltage * self.einzellinse_voltage_control['multiplier'])
            self.einzellinse_voltage_control['slider'].setValue(slider_value)
            self.einzellinse_voltage_control['slider'].blockSignals(False)

            # Queue OPC write instead of calling set_value synchronously
            self.schedule_opc_write(
                self.einzellinse_voltage_control['node_id'],
                new_einzellinse_voltage,
                VariantType.Float
            )

            self.delta_display.setText(f"{self.delta_voltage:.1f} V")
        except Exception as e:
            self.status_label.setText(f"Error updating Einzellens 1 voltage: {str(e)}")

    # ---------- MQTT ----------

    def init_mqtt(self):
        self.mqtt.messageReceived.connect(self.on_mqtt_msg)
        self.mqtt.connectionChanged.connect(self.on_mqtt_conn_changed)
        self.mqtt.configure(MQTT_DEFAULT_HOST, MQTT_DEFAULT_PORT)
        self.mqtt.start()
        self._connect_mqtt_slider(self.psu1_mqtt_control, "psu/1")
        self._connect_mqtt_slider(self.psu2_mqtt_control, "psu/2")
        self._connect_mqtt_slider(self.hv1_mqtt_control, "hv/1")
        self._connect_mqtt_slider(self.hv4_mqtt_control, "hv/4")

    def _connect_mqtt_slider(self, control, topic_prefix: str):
        topic = f"{topic_prefix}/cmd/set_v"

        def on_value_changed(val: int):
            real_val = float(val) / float(control['multiplier'])
            payload = f"{real_val:.1f}".replace(",", ".")
            self.mqtt.publish(topic, payload)
        control['slider'].valueChanged.connect(on_value_changed)

    def on_mqtt_conn_changed(self, ok: bool, text: str):
        self.mqtt_status_label.setText(f"MQTT: {text}")
        self.mqtt_status_label.setStyleSheet("color:#0a0" if ok else "color:#a00")

    def on_mqtt_msg(self, topic: str, payload: str):
        now = int(time.time() * 1000)
        self.mqtt_lastUpdate[topic] = now

        def fmt1(text: str) -> str:
            try:
                v = float(text.replace(",", "."))
                return f"{v:.1f}"
            except Exception:
                return text

        if topic == "psu/1/meas_v":
            self.psu1_mqtt_meas_v.setText(f"{fmt1(payload)} V")
        elif topic == "psu/2/meas_v":
            self.psu2_mqtt_meas_v.setText(f"{fmt1(payload)} V")
        elif topic == "hv/1/meas_v":
            self.hv1_mqtt_meas_v.setText(f"{fmt1(payload)} V")
        elif topic == "hv/1/meas_i_mA":
            self.hv1_mqtt_meas_i.setText(f"{fmt1(payload)} mA")
        elif topic == "hv/4/meas_v":
            self.hv4_mqtt_meas_v.setText(f"{fmt1(payload)} V")
        elif topic == "hv/4/meas_i_mA":
            self.hv4_mqtt_meas_i.setText(f"{fmt1(payload)} mA")

    def refresh_mqtt_stale(self):
        now = int(time.time() * 1000)

        def mark(label: QLabel, topics):
            latest = max([self.mqtt_lastUpdate.get(t, 0) for t in topics], default=0)
            if latest and (now - latest) < self.mqtt_staleThresholdMs:
                label.setStyleSheet("color:#000")
            else:
                label.setStyleSheet("color:#888")

        mark(self.psu1_mqtt_meas_v, ["psu/1/meas_v"])
        mark(self.psu2_mqtt_meas_v, ["psu/2/meas_v"])
        mark(self.hv1_mqtt_meas_v, ["hv/1/meas_v"])
        mark(self.hv1_mqtt_meas_i, ["hv/1/meas_i_mA"])
        mark(self.hv4_mqtt_meas_v, ["hv/4/meas_v"])
        mark(self.hv4_mqtt_meas_i, ["hv/4/meas_i_mA"])

    # ---------- Magnet / Gaussmeter low-level ----------

    def connect_magnet(self):
        """Connect to magnet PSU and sync GUI without forcing 0 A, set limit to 60 V."""
        if self.mag_sock:
            return
        try:
            self.mag_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.mag_sock.settimeout(2.0)
            self.mag_sock.connect((self.mag_host, self.mag_port))

            # Read measured current
            cur = self.mag_send_command("meas:curr?")

            current_val = 0.0
            try:
                if cur:
                    current_val = float(cur)
            except Exception:
                current_val = 0.0

            # Program 60 V limit and measured current as setpoint
            self.mag_send_command("sour:volt 60.000")
            self.mag_send_command(f"sour:curr {current_val:.4f}")

            # Sync GUI
            slider = self.magnet_control['slider']
            mult = self.magnet_control['multiplier']
            slider.blockSignals(True)
            slider.setValue(int(round(current_val * mult)))
            slider.blockSignals(False)

            self.magnet_direct_input.blockSignals(True)
            self.magnet_direct_input.setValue(current_val)
            self.magnet_direct_input.blockSignals(False)
        except Exception as e:
            print(f"Magnet connect error: {e}")
            try:
                if self.mag_sock:
                    self.mag_sock.close()
            except Exception:
                pass
            self.mag_sock = None

    def mag_send_command(self, cmd):
        try:
            if not self.mag_sock:
                return None
            self.mag_sock.sendall((cmd + "\n").encode('ascii'))
            if cmd.endswith("?"):
                return self.mag_sock.recv(1024).decode('ascii').strip()
            return None
        except Exception as e:
            print(f"Magnet cmd '{cmd}' failed: {e}")
            return None

    def connect_gaussmeter(self):
        """Connect to EX-6030 and configure to Gauss/DC/Autorange."""
        try:
            if self.gm_sock:
                try:
                    self.gm_sock.close()
                except Exception:
                    pass
                self.gm_sock = None

            s = socket.create_connection((self.gm_host, self.gm_port), timeout=2)
            s.settimeout(1.0)
            for cmd in (b"UNIT G", b"ACDC 0", b"AUTO 1"):
                s.sendall(cmd + b"\r\n")
                time.sleep(self._gm_write_delay)
                self._gm_read_line(s)
            self.gm_sock = s
        except Exception:
            self.gm_sock = None

    def _gm_read_line(self, sock):
        """Read ASCII line until CR/LF or timeout."""
        end = time.time() + self._gm_read_overall
        buf = bytearray()
        while time.time() < end:
            sock.settimeout(self._gm_read_idle)
            try:
                chunk = sock.recv(256)
            except TimeoutError:
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

    def _gm_txrx(self, cmd: str):
        """Send command, read one response line."""
        if not self.gm_sock:
            return ""
        try:
            self.gm_sock.sendall(cmd.encode("ascii") + b"\r\n")
            time.sleep(self._gm_write_delay)
            return self._gm_read_line(self.gm_sock)
        except OSError:
            return ""

    def _gm_read_field_kG(self):
        """Read field and return as kG, independent of unit and multiplier."""
        if not self.gm_sock:
            return float("nan")
        mult_map = {"µ": 1e-6, "u": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3}
        val = self._gm_txrx("FIELD?")
        mul = self._gm_txrx("FIELDM?")
        unit = self._gm_txrx("UNIT?")
        try:
            base = float((val or "").strip())
        except Exception:
            return float("nan")
        value = base * mult_map.get((mul or "").strip(), 1.0)
        if (unit or "").strip().upper().startswith("T"):
            value *= 1e4  # 1 T = 10,000 G
        return value / 1000.0  # -> kG

    # ---------- Magnet high-level ----------

    def on_magnet_slider_changed(self, value):
        """Send magnet setpoints when slider changes."""
        if self.loading_config:
            return
        current = value / self.magnet_control['multiplier']
        self.set_magnet_setpoints(current)

    def send_magnet_direct_current(self):
        """Set magnet current from manual input."""
        current = self.magnet_direct_input.value()
        if 0 <= current <= 120.0:
            mult = self.magnet_control['multiplier']
            self.magnet_control['slider'].setValue(int(round(current * mult)))
        else:
            QMessageBox.warning(
                self,
                "Invalid Value",
                "Magnet current must be between 0 and 120 A"
            )

    # ---------- Magnet write throttling ----------

    def schedule_magnet_setpoint(self, current):
        """Queue a magnet setpoint to be sent asynchronously."""
        self.pending_magnet_setpoint = current

    def process_pending_magnet_setpoint(self):
        """Apply the last queued magnet setpoint, if any."""
        if self.pending_magnet_setpoint is None:
            return
        current = self.pending_magnet_setpoint
        self.pending_magnet_setpoint = None
        self._apply_magnet_setpoint(current)

    def _apply_magnet_setpoint(self, current):
        """Internal helper that actually sends commands to the PSU."""
        if self.mag_sock is None:
            self.connect_magnet()
        if self.mag_sock is None:
            return
        voltage = 60.0
        try:
            self.mag_send_command(f"sour:curr {current:.4f}")
            self.mag_send_command(f"sour:volt {voltage:.3f}")
        except Exception as e:
            print(f"_apply_magnet_setpoint error: {e}")

    def set_magnet_setpoints(self, current):
        """Program current and voltage limit to PSU (limit always 60 V)."""
        self.schedule_magnet_setpoint(current)

    def update_magnet_measurements(self):
        # Magnet PSU
        if self.mag_sock is None:
            self.connect_magnet()
        if self.mag_sock:
            cur = self.mag_send_command("meas:curr?")
            volt = self.mag_send_command("meas:volt?")
            try:
                if cur:
                    self.mag_last_current_A = float(cur)
                    self.magnet_meas_current_label.setText(f"{self.mag_last_current_A:.4f} A")
                else:
                    self.magnet_meas_current_label.setText("--- A")
            except Exception:
                self.magnet_meas_current_label.setText("--- A")

            try:
                if volt:
                    self.mag_last_voltage_V = float(volt)
                    self.magnet_meas_voltage_label.setText(f"{self.mag_last_voltage_V:.3f} V")
                else:
                    self.magnet_meas_voltage_label.setText("--- V")
            except Exception:
                self.magnet_meas_voltage_label.setText("--- V")
        else:
            self.magnet_meas_current_label.setText("--- A")
            self.magnet_meas_voltage_label.setText("--- V")

        # Gaussmeter
        if self.gm_sock is None:
            self.connect_gaussmeter()
        if self.gm_sock:
            try:
                field_kG = self._gm_read_field_kG()
                if field_kG != field_kG:  # NaN
                    try:
                        self.gm_sock.close()
                    except Exception:
                        pass
                    self.gm_sock = None
                    self.magnet_field_label.setText("--- kG")
                else:
                    self.mag_last_field_kG = field_kG
                    self.magnet_field_label.setText(f"{field_kG:.3f} kG")
            except Exception:
                try:
                    if self.gm_sock:
                        self.gm_sock.close()
                except Exception:
                    pass
                self.gm_sock = None
                self.magnet_field_label.setText("--- kG")
        else:
            self.magnet_field_label.setText("--- kG")

    # ---------- Refresh / trace / calculator / popout ----------

    def refresh_all(self):
        if self.in_trace or self.loading_config:
            self.refresh_mqtt_stale()
            return
        if not self.client:
            self.status_label.setText("Status: Not connected – cannot read values")
            self.refresh_mqtt_stale()
            return
        try:
            # --- digitale Ausgänge in einem Rutsch lesen ---
            cb_node_ids = list(self.checkboxes.keys())
            cb_values = self.read_node_values(cb_node_ids)
            for node_id in cb_node_ids:
                checkbox = self.checkboxes[node_id]
                value = cb_values.get(node_id, False)
                checkbox.blockSignals(True)
                checkbox.setChecked(bool(value))
                checkbox.blockSignals(False)

            current_node = self.client.get_node(self.current_control['node_id'])
            current_value = current_node.get_value()
            s = self.current_control['slider']
            if not s.isSliderDown():
                s.blockSignals(True)
                s.setValue(round(current_value * self.current_control['multiplier']))
                s.blockSignals(False)

            temp_node = self.client.get_node(self.temp_display.node_id)
            temp_value = temp_node.get_value()
            self.temp_display.setText(f"{temp_value:.1f} °C")

            self.refresh_voltage(self.sputter_voltage_control)
            self.refresh_voltage_display("sputter_voltage_display", "V")
            self.refresh_voltage_display("sputter_current_display", "mA", 3)
            self.refresh_voltage_display("ionizer_current_display", "A")

            self.refresh_voltage(self.extraction_voltage_control)
            self.refresh_voltage_display("extraction_voltage_display", "V")

            self.refresh_voltage(self.einzellinse_voltage_control)
            self.refresh_voltage_display("einzellinse_voltage_display", "V")

            extraction_value = self.extraction_voltage_control['slider'].value()
            extraction_voltage = extraction_value / self.extraction_voltage_control['multiplier']
            einzellinse_value = self.einzellinse_voltage_control['slider'].value()
            einzellinse_voltage = einzellinse_value / self.einzellinse_voltage_control['multiplier']
            self.delta_voltage = einzellinse_voltage - extraction_voltage
            self.delta_display.setText(f"{self.delta_voltage:.1f} V")

            self.refresh_voltage(self.lens2_voltage_control)
            self.refresh_voltage_display("lens2_voltage_display", "V")

            self.refresh_voltage(self.ion_cooler_voltage_control)
            self.refresh_voltage_display("ion_cooler_voltage_display", "V")

            self.refresh_voltage(self.quad1_voltage_control)
            self.refresh_voltage_display("quad1_voltage_display", "V")

            self.refresh_voltage(self.quad2_voltage_control)
            self.refresh_voltage_display("quad2_voltage_display", "V")

            self.refresh_voltage(self.quad3_voltage_control)
            self.refresh_voltage_display("quad3_voltage_display", "V")

            self.refresh_voltage(self.esa_voltage_control)
            self.refresh_voltage_display("esa_voltage_display", "V")

            self.refresh_voltage(self.esa_correction_control)
            self.refresh_voltage_display("esa_correction_display", "V")

            self.refresh_voltage(self.lens4_voltage_control)
            self.refresh_voltage_display("lens4_voltage_display", "V")

            self.status_label.setText("Status: Auto-refreshing")

            if self.logging_active:
                self.write_log_entry()

            self.refresh_mqtt_stale()
        except Exception as e:
            self.status_label.setText(f"Error reading values: {str(e)}")

    def refresh_voltage(self, control):
        node_id = control['node_id']
        node = self.get_node_cached(node_id)
        value = node.get_value()
        self._opc_last_values[node_id] = value

        slider = control['slider']
        if slider.isSliderDown():
            return
        slider.blockSignals(True)
        slider.setValue(round(value * control['multiplier']))
        slider.blockSignals(False)

    def refresh_voltage_display(self, display_name, unit, decimals=1):
        display = getattr(self, display_name)
        node_id = display.node_id
        node = self.get_node_cached(node_id)
        value = node.get_value()
        self._opc_last_values[node_id] = value
        display.setText(f"{value:.{decimals}f} {unit}")

    def start_trace_dialog(self):
        if not self.client:
            QMessageBox.warning(self, "Trace", "OPC is not connected.")
            return
        if self.keithley_widget.is_measuring:
            QMessageBox.warning(
                self, "Trace",
                "Keithley is already in continuous measurement mode.\n"
                "Please stop it there first."
            )
            return

        current_values = {}
        for key, info in self.traceable_parameters.items():
            ctrl = info["control"]
            current_values[key] = ctrl['slider'].value() / ctrl['multiplier']

        cfg_dialog = TraceConfigDialog(
            self,
            {k: {"name": v["name"], "min": v["min"], "max": v["max"]}
             for k, v in self.traceable_parameters.items()},
            current_values
        )
        if cfg_dialog.exec_() != QDialog.Accepted:
            return
        cfg = cfg_dialog.get_config()
        self.run_trace(cfg)

    def run_trace(self, cfg):
        key = cfg["param_key"]
        if key not in self.traceable_parameters:
            return
        info = self.traceable_parameters[key]
        control = info["control"]

        # Magnet special handling: pause its measurement timer during trace
        mag_timer_was_active = False
        if key == "magnet_current":
            mag_timer_was_active = self.mag_measure_timer.isActive()
            self.mag_measure_timer.stop()

        slider = control['slider']
        mult = control['multiplier']

        start = cfg["start"]
        stop = cfg["stop"]
        step = cfg["step"]
        dwell = cfg["dwell"]

        if step <= 0 or stop <= start:
            QMessageBox.warning(self, "Trace", "Invalid start/end/step settings.")
            if key == "magnet_current" and mag_timer_was_active:
                self.mag_measure_timer.start(1000)
            return

        # Value list
        values = []
        v = start
        while v <= stop + 1e-9:
            values.append(v)
            v += step

        if len(values) < 2:
            QMessageBox.warning(
                self,
                "Trace",
                "The chosen start/stop/step settings result in only one point.\n"
                "Please choose a smaller step or a wider interval."
            )
            if key == "magnet_current" and mag_timer_was_active:
                self.mag_measure_timer.start(1000)
            return

        original_value = slider.value() / mult

        # Live dialog
        dlg = TraceResultDialog(self, info["name"], [], [], original_value)
        dlg.show()
        QtWidgets.QApplication.processEvents()

        self.in_trace = True
        self.refresh_timer.stop()
        self.status_label.setText("Trace running...")

        currents = []
        valid_x = []
        valid_y = []

        try:
            for i, val in enumerate(values):
                slider.setValue(int(round(val * mult)))
                QtWidgets.QApplication.processEvents()
                time.sleep(0.1)

                try:
                    avg_nA = self.keithley_widget.measure_average_current(dwell)
                except Exception as e:
                    print(f"Error during trace measurement: {e}")
                    avg_nA = None

                if avg_nA is None:
                    currents.append(float('nan'))
                else:
                    currents.append(avg_nA)

                valid_x = []
                valid_y = []
                for xv, yv in zip(values[:len(currents)], currents):
                    if yv is not None and not np.isnan(yv):
                        valid_x.append(xv)
                        valid_y.append(yv)
                if valid_x:
                    dlg.set_data(valid_x, valid_y)

                self.status_label.setText(f"Trace step {i + 1}/{len(values)}...")
                QtWidgets.QApplication.processEvents()
        finally:
            slider.setValue(int(round(original_value * mult)))
            self.status_label.setText("Trace finished – original value restored.")
            self.in_trace = False
            self.refresh_timer.start(1000)

            # restart magnet timer if needed
            if key == "magnet_current" and mag_timer_was_active:
                self.mag_measure_timer.start(1000)

        if not valid_x:
            dlg.close()
            QMessageBox.warning(self, "Trace", "No valid measurements during trace.")
            return

        dlg.enable_interaction()
        result = dlg.exec_()

        if result == QDialog.Accepted and dlg.accepted_value is not None:
            new_val = dlg.accepted_value
            slider.setValue(int(round(new_val * mult)))
            QMessageBox.information(
                self, "Trace",
                f"New value for {info['name']} has been set:\n{new_val:.3f}"
            )
        else:
            slider.setValue(int(round(original_value * mult)))
            self.status_label.setText("Trace discarded – original value restored.")

        dlg.close()

    def open_calculator(self):
        dlg = CalculatorDialog(self)
        dlg.exec_()

    def toggle_keithley_popout(self):
        if not self.keithley_detached:
            # detach to separate dialog
            idx = self.tabs.indexOf(self.keithley_widget)
            if idx != -1:
                self.tabs.removeTab(idx)

            # Create popup and reparent KeithleyWidget into it
            self.keithley_popup = KeithleyPopup(self, self.keithley_widget)
            self.keithley_popup.resize(900, 600)
            self.keithley_popup.show()

            self.keithley_detached = True
            self.keithley_pop_btn.setText("Reattach Keithley")
        else:
            # if already detached, close popup (which reattaches in closeEvent)
            if self.keithley_popup is not None:
                self.keithley_popup.close()

    def reattach_keithley_from_window(self):
        if not self.keithley_detached:
            return

        # Remove widget from popup layout and reinsert into tab widget
        if self.keithley_popup is not None:
            layout = self.keithley_popup.layout()
            if layout is not None:
                layout.removeWidget(self.keithley_widget)
            self.keithley_popup.deleteLater()
            self.keithley_popup = None

        self.keithley_widget.setParent(self.tabs)
        self.tabs.addTab(self.keithley_widget, "Keithley")
        self.tabs.setCurrentWidget(self.keithley_widget)

        self.keithley_detached = False
        self.keithley_pop_btn.setText("Pop out Keithley")


    def toggle_combi_popout(self):
        if not self.combi_detached:
            # Tab entfernen und als Popup anzeigen
            idx = self.tabs.indexOf(self.combi_tab)
            if idx != -1:
                self.tabs.removeTab(idx)

            self.combi_popup = CombiPopup(self, self.combi_tab)
            self.combi_popup.resize(1100, 800)
            self.combi_popup.show()

            self.combi_detached = True
            self.combi_pop_btn.setText("Reattach RFQ/COMBI7")
        else:
            # Wenn schon detached: Popup schließen (reattach passiert im closeEvent)
            if self.combi_popup is not None:
                self.combi_popup.close()

    def reattach_combi_from_window(self):
        if not self.combi_detached:
            return

        # Widget aus dem Popup nehmen und zurück in die Tabs legen
        if self.combi_popup is not None:
            layout = self.combi_popup.layout()
            if layout is not None:
                layout.removeWidget(self.combi_tab)
            self.combi_popup.deleteLater()
            self.combi_popup = None

        self.combi_tab.setParent(self.tabs)
        self.tabs.addTab(self.combi_tab, "RFQ / COMBI7")
        self.tabs.setCurrentWidget(self.combi_tab)

        self.combi_detached = False
        self.combi_pop_btn.setText("Pop out RFQ/COMBI7")

    # ---------- Close ----------

    def closeEvent(self, event):
        # Magnet shutdown prompt
        if self.mag_sock:
            reply = QMessageBox.question(
                self,
                'Confirm Magnet Shutdown',
                "Do you want to shut down the magnet (go to 0 A)?\n"
                "Click 'No' to keep the current values.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                try:
                    self.mag_send_command("sour:volt 0")
                    self.mag_send_command("sour:curr 0")
                except Exception:
                    pass
            try:
                self.mag_sock.close()
            except Exception:
                pass
            self.mag_sock = None

        if self.gm_sock:
            try:
                self.gm_sock.close()
            except Exception:
                pass
            self.gm_sock = None

        if self.mag_measure_timer:
            self.mag_measure_timer.stop()

        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
        if self.log_file:
            try:
                self.log_file.close()
            except Exception:
                pass
        self.refresh_timer.stop()
        try:
            self.mqtt.stop()
        except Exception:
            pass
        if self.keithley_detached:
            self.reattach_keithley_from_window()
        
        # Stop sample motor worker thread (if running)
        if hasattr(self, "sample_motor_thread") and self.sample_motor_thread is not None:
            try:
                if hasattr(self, "sample_motor_worker") and self.sample_motor_worker is not None:
                    self.sample_motor_worker.shutdown()
                self.sample_motor_thread.quit()
                self.sample_motor_thread.wait(2000)
            except Exception:
                pass
            self.sample_motor_thread = None
            self.sample_motor_worker = None

        if self.keithley_widget:
            self.keithley_widget.cleanup()

        # COMBI7-Tab ggf. wieder anheften und aufräumen
        if self.combi_detached:
            self.reattach_combi_from_window()
        if hasattr(self, "combi_tab") and self.combi_tab is not None:
            self.combi_tab.cleanup()
            
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OPCControlPanel()
    window.show()
    sys.exit(app.exec_())
