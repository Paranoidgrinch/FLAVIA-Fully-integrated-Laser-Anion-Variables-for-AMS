import sys
import math
import socket
import time

import numpy as np
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtGui import QTextCursor

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Optional SSH
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

# Pi / LC controller (fixed SSH credentials)
PI_HOST_DEFAULT = "raspberrypi.local"
PI_USER_DEFAULT = "pi"
PI_PASSWORD_DEFAULT = "raspberry"

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

    def test_connection(self, timeout=1.0) -> bool:
        """
        Lightweight connectivity test: just open a TCP connection and close it.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((self.ip, self.port))
            return True
        except Exception:
            return False

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


class RFQWorker(QtCore.QObject):
    # --- Signale zur GUI ---
    fgStatus = QtCore.pyqtSignal(float, float)          # freq, ampl
    fgError = QtCore.pyqtSignal(str)

    piStatus = QtCore.pyqtSignal(bool, str)             # ok, message
    lcReadResult = QtCore.pyqtSignal(float, str, float, str)  # c_val, c_err, l_val, l_err
    lcSendResult = QtCore.pyqtSignal(float, float, str, str)  # C_pF, L_uH, errC, errL
    lcError = QtCore.pyqtSignal(str)

    scopeStatus = QtCore.pyqtSignal(bool)
    scopeMeasurement = QtCore.pyqtSignal(float, float, object, object)  # vpp2, vpp3, wave2, wave3
    scopeError = QtCore.pyqtSignal(str)

    sweepProgress = QtCore.pyqtSignal(int, int, float)  # step_idx, total, L_uH
    sweepLog = QtCore.pyqtSignal(str)
    sweepResult = QtCore.pyqtSignal(
        object, object, object, object, object, float, float, str
    )  # L_meas, Vpp2_list, Vpp3_list, best_wave2, best_wave3, best_L, max_vpp2, msg
    sweepError = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fg = DS345Client()
        self.scope = ScopeClient()
        self.lc = LCSSHClient()
        self._sweep_cancelled = False

    # ---------- FG ----------

    @QtCore.pyqtSlot()
    def request_fg_status(self):
        try:
            f = self.fg.get_frequency()
            a = self.fg.get_amplitude()
            self.fgStatus.emit(f, a)
        except Exception as e:
            self.fgError.emit(str(e))

    @QtCore.pyqtSlot(float, float)
    def set_fg(self, freq, vpp):
        try:
            self.fg.set_frequency(freq)
            self.fg.set_amplitude(vpp)
        except Exception as e:
            self.fgError.emit(str(e))

    # ---------- LC / SSH ----------

    @QtCore.pyqtSlot()
    def connect_pi(self):
        if paramiko is None:
            self.piStatus.emit(False, "paramiko not installed")
            return
        try:
            self.lc.connect(PI_HOST_DEFAULT, PI_USER_DEFAULT, PI_PASSWORD_DEFAULT)
            self.piStatus.emit(True, f"SSH to {PI_HOST_DEFAULT} established.")
        except Exception as e:
            self.piStatus.emit(False, f"SSH error: {e}")

    @QtCore.pyqtSlot(float, float)
    def set_lc(self, C_pF, L_uH):
        if not self.lc.is_connected():
            self.lcError.emit("Not connected to Pi.")
            return
        try:
            outC, errC = self.lc.set_value("C", C_pF)
            outL, errL = self.lc.set_value("L", L_uH)
            self.lcSendResult.emit(C_pF, L_uH, errC, errL)
        except Exception as e:
            self.lcError.emit(str(e))

    @QtCore.pyqtSlot()
    def read_lc(self):
        if not self.lc.is_connected():
            self.lcError.emit("Not connected to Pi.")
            return
        try:
            c_val, c_err = self.lc.get_value("C")
            l_val, l_err = self.lc.get_value("L")
            self.lcReadResult.emit(c_val, c_err, l_val, l_err)
        except Exception as e:
            self.lcError.emit(str(e))

    # ---------- Scope ----------

    @QtCore.pyqtSlot()
    def test_scope(self):
        try:
            ok = self.scope.test_connection()
        except Exception:
            ok = False
        self.scopeStatus.emit(ok)

    @QtCore.pyqtSlot()
    def measure_scope(self):
        try:
            vpp2, vpp3, wave2, wave3 = self.scope.measure_ch2_ch3()
            self.scopeMeasurement.emit(vpp2, vpp3, wave2, wave3)
        except Exception as e:
            self.scopeError.emit(str(e))

    # ---------- L-Sweep ----------

    @QtCore.pyqtSlot(float, float, float, float, bool)
    def run_sweep_L(self, center_L, span, step, dwell_ms, measure_scope):
        if not self.lc.is_connected():
            self.sweepError.emit("Not connected to Pi (SSH).")
            return
        if span <= 0 or step <= 0 or dwell_ms <= 0:
            self.sweepError.emit("Span, step and dwell time must be > 0.")
            return

        dwell_s = dwell_ms / 1000.0

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

        self.sweepLog.emit(
            f"Starting L sweep around {center_L:.3f} µH: "
            f"from {start:.3f} to {stop:.3f} in steps of {step:.3f} µH."
        )

        L_meas = []
        Vpp2_list = []
        Vpp3_list = []
        max_vpp2 = -1.0
        best_L = None
        best_wave2 = None
        best_wave3 = None

        L_max_uH = 512.0
        L_step_hw = 0.25
        self._sweep_cancelled = False

        for idx, val in enumerate(values):
            if self._sweep_cancelled:
                self.sweepLog.emit("Sweep cancelled by user.")
                break

            if val < 0.0 or val >= L_max_uH:
                continue

            index = round(val / L_step_hw)
            L_uH = index * L_step_hw
            if L_uH >= L_max_uH:
                L_uH = L_max_uH - L_step_hw

            try:
                self.lc.set_value("L", L_uH)
            except Exception as e:
                self.sweepLog.emit(f"Sweep: error setting L: {e}")
                continue

            self.sweepLog.emit(f"Sweep step {idx+1}/{len(values)}: L={L_uH:.3f} µH")
            self.sweepProgress.emit(idx + 1, len(values), L_uH)

            time.sleep(dwell_s)

            if measure_scope:
                try:
                    vpp2, vpp3, wave2, wave3 = self.scope.measure_ch2_ch3()
                    self.sweepLog.emit(
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
                    self.sweepLog.emit(f"Sweep: scope error: {e}")

        if measure_scope and L_meas and best_L is not None:
            msg_txt = (
                f"Max CH2 Vpp during sweep: {max_vpp2:.3f} V\n"
                f"at L = {best_L:.3f} µH"
            )
            self.sweepLog.emit("[Sweep finished] " + msg_txt)
            self.sweepResult.emit(
                L_meas,
                Vpp2_list,
                Vpp3_list,
                best_wave2,
                best_wave3,
                best_L,
                max_vpp2,
                msg_txt,
            )
        elif measure_scope:
            msg = "Sweep finished, but no valid scope data were collected."
            self.sweepLog.emit("[Sweep finished] " + msg)
            self.sweepResult.emit([], [], [], None, None, float("nan"), float("nan"), msg)
        else:
            msg = "Sweep finished (scope measurement disabled)."
            self.sweepLog.emit("[Sweep finished] " + msg)
            self.sweepResult.emit([], [], [], None, None, float("nan"), float("nan"), msg)

    @QtCore.pyqtSlot()
    def cancel_sweep(self):
        self._sweep_cancelled = True

    # ---------- Shutdown ----------

    @QtCore.pyqtSlot()
    def shutdown(self):
        try:
            self.fg.close()
        except Exception:
            pass
        try:
            self.lc.close()
        except Exception:
            pass


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
# GUI MAIN WINDOW
# ============================================================

class RFQUnifiedGUI(QtWidgets.QMainWindow):
    requestFgStatus = QtCore.pyqtSignal()
    setFgRequested = QtCore.pyqtSignal(float, float)

    requestPiConnect = QtCore.pyqtSignal()
    requestLcSend = QtCore.pyqtSignal(float, float)
    requestLcRead = QtCore.pyqtSignal()

    requestScopeTest = QtCore.pyqtSignal()
    requestScopeMeasure = QtCore.pyqtSignal()

    requestSweepL = QtCore.pyqtSignal(float, float, float, float, bool)
    cancelSweep = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RFQ – Mathieu, FG, LC (SSH), Scope + L-sweep")
        self.resize(1250, 800)

        # Use embedded resonance presets
        self.resonance_presets = RESONANCE_PRESETS

        self._build_ui()

        # ---------- Worker-Thread für Hardware ----------
        self.worker_thread = QtCore.QThread(self)
        self.worker = RFQWorker()
        self.worker.moveToThread(self.worker_thread)

        # GUI-Signale -> Worker-Slots
        self.requestFgStatus.connect(self.worker.request_fg_status)
        self.setFgRequested.connect(self.worker.set_fg)

        self.requestPiConnect.connect(self.worker.connect_pi)
        self.requestLcSend.connect(self.worker.set_lc)
        self.requestLcRead.connect(self.worker.read_lc)

        self.requestScopeTest.connect(self.worker.test_scope)
        self.requestScopeMeasure.connect(self.worker.measure_scope)

        self.requestSweepL.connect(self.worker.run_sweep_L)
        self.cancelSweep.connect(self.worker.cancel_sweep)

        # Worker-Signale -> GUI-Slots
        self.worker.fgStatus.connect(self._on_fg_status)
        self.worker.fgError.connect(self._on_fg_error)

        self.worker.piStatus.connect(self._on_pi_status)
        self.worker.lcReadResult.connect(self._on_lc_read_result)
        self.worker.lcSendResult.connect(self._on_lc_send_result)
        self.worker.lcError.connect(self._on_lc_error)

        self.worker.scopeStatus.connect(self._on_scope_status)
        self.worker.scopeMeasurement.connect(self._on_scope_measurement)
        self.worker.scopeError.connect(self._on_scope_error)

        self.worker.sweepLog.connect(self.append_log)
        self.worker.sweepProgress.connect(self._on_sweep_progress)
        self.worker.sweepResult.connect(self._on_sweep_result)
        self.worker.sweepError.connect(self._on_sweep_error)

        self.worker_thread.start()

        # FG update timer (fragt nur den Worker)
        self.timer_fg = QtCore.QTimer(self)
        self.timer_fg.timeout.connect(self.update_fg_display)
        self.timer_fg.start(2000)

        # Automatic initial connections/status via Worker
        self._connect_pi()          # nutzt jetzt den Worker
        self.update_scope_status()  # nutzt jetzt den Worker

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
        group = QtWidgets.QGroupBox("Mathieu Parameter Calculator")
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

        btn_q_from_f = QtWidgets.QPushButton("Compute Mathieu Parameter for given Frequency")
        btn_q_from_f.clicked.connect(self.on_q_from_f)

        btn_f_from_q = QtWidgets.QPushButton("Compute Frequency for given Mathieu Parameter")
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
        group = QtWidgets.QGroupBox("Function Generator")
        layout = QtWidgets.QFormLayout(group)

        self.lbl_fg_status = QtWidgets.QLabel("Status: unknown")
        self.lbl_fg_status.setStyleSheet("color: red;")

        self.lbl_fg_freq = QtWidgets.QLabel("f = --- Hz")
        self.lbl_fg_ampl = QtWidgets.QLabel("Vpp = --- V")

        btn_fg_read = QtWidgets.QPushButton("Readout Function Generator")
        btn_fg_read.clicked.connect(self.update_fg_display)

        btn_fg_send = QtWidgets.QPushButton("Set calculated Frequency and Amplitude")
        btn_fg_send.clicked.connect(self.on_fg_send)

        layout.addRow(self.lbl_fg_status)
        layout.addRow("FG frequency:", self.lbl_fg_freq)
        layout.addRow("FG amplitude:", self.lbl_fg_ampl)
        layout.addRow(btn_fg_read)
        layout.addRow(btn_fg_send)

        return group

    def update_fg_display(self):
        # nur Anfrage an den Worker, Ergebnis kommt in _on_fg_status
        self.requestFgStatus.emit()

    def _on_fg_status(self, f, a):
        if math.isnan(f) or math.isnan(a):
            self.lbl_fg_status.setText("Status: not connected")
            self.lbl_fg_status.setStyleSheet("color: red;")
            self.lbl_fg_freq.setText("f = --- Hz")
            self.lbl_fg_ampl.setText("Vpp = --- V")
        else:
            self.lbl_fg_status.setText("Status: connected")
            self.lbl_fg_status.setStyleSheet("color: green;")
            self.lbl_fg_freq.setText(f"f = {f:.1f} Hz")
            self.lbl_fg_ampl.setText(f"Vpp = {a:.3f} V")

    def _on_fg_error(self, msg: str):
        self.append_log(f"FG error: {msg}")
        self.lbl_fg_status.setText("Status: not connected")
        self.lbl_fg_status.setStyleSheet("color: red;")

    def on_fg_send(self):
        try:
            f = float(self.edit_freq.text())
        except ValueError:
            self.append_log("FG send: frequency f is invalid.")
            return

        Vpp_FG = float(self.spin_amp.value())
        self.append_log(f"Sent to FG: f={f:.1f} Hz, Vpp={Vpp_FG:.2f} V")
        self.setFgRequested.emit(f, Vpp_FG)
        # Anzeige wird beim nächsten Timer-Tick aktualisiert

    # ---------- Config-Helfer für FG ----------

    def get_fg_config_values(self):
        """
        Liefert (freq_hz, vpp) für Config-Speicherung.
        """
        try:
            f_hz = float(self.edit_freq.text())
        except ValueError:
            f_hz = float("nan")
        vpp = float(self.spin_amp.value())
        return f_hz, vpp

    def apply_fg_config_values(self, freq_hz: float, vpp: float):
        """
        Setzt Frequenz und Vpp im GUI und sendet sie an den FG.
        """
        if freq_hz > 0:
            self.edit_freq.setText(f"{freq_hz:.3f}")
        # begrenzen wie in on_fg_send / set_amplitude
        vpp = max(0.0, min(10.0, float(vpp)))
        self.spin_amp.setValue(vpp)
        # direkt an den FG schicken
        self.on_fg_send()


    # ---------- Config-Helfer für LC ----------

    def get_lc_config_values(self):
        """
        Liefert (C_pF, L_uH) für Config-Speicherung.
        """
        try:
            c_pf = float(self.edit_C_pF.text())
        except ValueError:
            c_pf = float("nan")
        try:
            l_uh = float(self.edit_L_uH.text())
        except ValueError:
            l_uh = float("nan")
        return c_pf, l_uh

    def apply_lc_config_values(self, c_pf: float, l_uh: float):
        """
        Setzt C und L im GUI und schickt sie via SSH an den Pi.
        """
        if c_pf > 0:
            self.edit_C_pF.setText(f"{c_pf:.3f}")
        if l_uh > 0:
            self.edit_L_uH.setText(f"{l_uh:.3f}")
        # an den Pi senden
        self.on_lc_send()



    # ---------- LC group (SSH + resonance presets + L sweep) ----------

    def _build_lc_group(self):
        group = QtWidgets.QGroupBox("LC Circuit")
        vlayout = QtWidgets.QVBoxLayout(group)

        form = QtWidgets.QFormLayout()
        vlayout.addLayout(form)

        # SSH status
        self.lbl_pi_status = QtWidgets.QLabel("Status: not connected")
        self.lbl_pi_status.setStyleSheet("color: red;")

        btn_pi_connect = QtWidgets.QPushButton("Reconnect to Pi")
        btn_pi_connect.clicked.connect(self.on_pi_connect)

        # LC values
        self.edit_C_pF = QtWidgets.QLineEdit("1300.0")  # C in pF
        self.edit_L_uH = QtWidgets.QLineEdit("31.0")    # L in µH

        btn_L_from_C = QtWidgets.QPushButton("Compute L from Frequency and C")
        btn_L_from_C.clicked.connect(self.on_L_from_C)

        btn_C_from_L = QtWidgets.QPushButton("Compute C from Frequency and L")
        btn_C_from_L.clicked.connect(self.on_C_from_L)

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
        form.addRow(btn_pi_connect)
        form.addRow(self.lbl_pi_status)

        form.addRow("Resonance preset:", self.combo_resonance)

        form.addRow("C (pF):", self.edit_C_pF)
        form.addRow("L (µH):", self.edit_L_uH)

        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(btn_L_from_C)
        hl.addWidget(btn_C_from_L)
        form.addRow(hl)

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
        sweep_layout.addRow("Time per step (ms):", self.edit_sweep_dwell_ms)
        sweep_layout.addRow(self.check_sweep_scope)
        sweep_layout.addRow(btn_sweep)

        vlayout.addWidget(sweep_group)

        return group

    def _connect_pi(self):
        """
        Startet SSH-Verbindung zum Pi im Worker-Thread.
        """
        if paramiko is None:
            self.lbl_pi_status.setText("Status: paramiko not installed")
            self.lbl_pi_status.setStyleSheet("color: red;")
            self.append_log("SSH error: paramiko is not installed (pip install paramiko).")
            return

        self.lbl_pi_status.setText("Status: connecting...")
        self.lbl_pi_status.setStyleSheet("color: orange;")
        self.append_log("SSH: connecting to Pi...")
        self.requestPiConnect.emit()

    def on_pi_connect(self):
        self._connect_pi()



    def _on_pi_status(self, ok: bool, msg: str):
        if ok:
            self.lbl_pi_status.setText(f"Status: connected to {PI_HOST_DEFAULT}")
            self.lbl_pi_status.setStyleSheet("color: green;")
        else:
            self.lbl_pi_status.setText("Status: connection error")
            self.lbl_pi_status.setStyleSheet("color: red;")
        if msg:
            self.append_log(msg)
    

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
        self.append_log(info)

    def on_lc_send(self):
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

        # an den Worker senden
        self.requestLcSend.emit(C_pF, L_uH)


    def _on_lc_send_result(self, C_pF, L_uH, errC, errL):
        self.append_log(
            f"LC sent to Pi: C={C_pF:.3f} pF, L={L_uH:.3f} µH "
            f"(rounded to 0.5 pF / 0.25 µH). "
            f"C-err={errC!r} | L-err={errL!r}"
        )

    def _on_lc_error(self, msg: str):
        self.lbl_pi_status.setText("Status: connection error")
        self.lbl_pi_status.setStyleSheet("color: red;")
        self.append_log(f"LC error: {msg}")



    def on_lc_read(self):
        self.requestLcRead.emit()

    def _on_lc_read_result(self, c_val, c_err, l_val, l_err):
        if not math.isnan(c_val):
            self.edit_C_pF.setText(f"{c_val:.3f}")
        if not math.isnan(l_val):
            self.edit_L_uH.setText(f"{l_val:.3f}")
        self.append_log(f"LC from Pi: C={c_val} pF (err={c_err}), L={l_val} µH (err={l_err})")

    # ---------- L sweep ----------

    def on_sweep_L(self):
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

        measure_scope = self.check_sweep_scope.isChecked()

        self.append_log(
            f"Starting L sweep around {center_L:.3f} µH "
            f"(span={span:.3f}, step={step:.3f}, dwell={dwell_ms:.0f} ms)."
        )

        # Sweep im Worker starten
        self.requestSweepL.emit(center_L, span, step, dwell_ms, measure_scope)




    def _on_sweep_progress(self, step_idx: int, total: int, L_uH: float):
        # Nur GUI-Update: aktuelle L in das Feld schreiben
        self.edit_L_uH.setText(f"{L_uH:.3f}")

    def _on_sweep_result(
        self,
        L_meas,
        Vpp2_list,
        Vpp3_list,
        best_wave2,
        best_wave3,
        best_L,
        max_vpp2,
        msg_txt,
    ):
        # Ergebnis wie bisher visualisieren
        if L_meas and best_L is not None and not math.isnan(best_L):
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
        else:
            QtWidgets.QMessageBox.information(self, "Sweep result", msg_txt)

    def _on_sweep_error(self, msg: str):
        QtWidgets.QMessageBox.warning(self, "Sweep error", msg)
        self.append_log(f"Sweep error: {msg}")



    
    # ---------- Scope / Plot group ----------

    def _build_scope_group(self):
        group = QtWidgets.QGroupBox("Oscilloscope")
        layout = QtWidgets.QFormLayout(group)

        self.lbl_scope_status = QtWidgets.QLabel("Status: unknown")
        self.lbl_scope_status.setStyleSheet("color: red;")

        self.lbl_vpp2 = QtWidgets.QLabel("CH2 Vpp = --- V")
        self.lbl_vpp3 = QtWidgets.QLabel("CH3 Vpp = --- V")
        self.lbl_q_meas = QtWidgets.QLabel("q_meas (from CH2) = ---")

        btn_measure = QtWidgets.QPushButton("Measure CH2 & CH3 + plot")
        btn_measure.clicked.connect(self.on_measure_scope)

        layout.addRow(self.lbl_scope_status)
        layout.addRow(btn_measure)
        layout.addRow(self.lbl_vpp2)
        layout.addRow(self.lbl_vpp3)
        layout.addRow(self.lbl_q_meas)

        return group

    def update_scope_status(self):
        self.requestScopeTest.emit()

    def _on_scope_status(self, ok: bool):
        if ok:
            self.lbl_scope_status.setText("Status: connected")
            self.lbl_scope_status.setStyleSheet("color: green;")
        else:
            self.lbl_scope_status.setText("Status: not connected")
            self.lbl_scope_status.setStyleSheet("color: red;")

    def _build_plot_group(self):
        group = QtWidgets.QGroupBox("Waveform plot (CH2 & CH3)")
        layout = QtWidgets.QVBoxLayout(group)

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        return group

    def on_measure_scope(self):
        self.requestScopeMeasure.emit()

    def _on_scope_measurement(self, vpp2, vpp3, wave2, wave3):
        self.lbl_scope_status.setText("Status: connected")
        self.lbl_scope_status.setStyleSheet("color: green;")

        self.lbl_vpp2.setText(f"CH2 Vpp = {vpp2:.3f} V")
        self.lbl_vpp3.setText(f"CH3 Vpp = {vpp3:.3f} V")
        self.append_log(f"Scope: CH2 Vpp={vpp2:.3f} V, CH3 Vpp={vpp3:.3f} V")

        # q_meas wie bisher
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

        # Plot aktualisieren
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

    def _on_scope_error(self, msg: str):
        self.append_log(f"Scope error: {msg}")
        self.lbl_scope_status.setText("Status: not connected")
        self.lbl_scope_status.setStyleSheet("color: red;")
        self.lbl_vpp2.setText("CH2 Vpp = NaN")
        self.lbl_vpp3.setText("CH3 Vpp = NaN")
        self.lbl_q_meas.setText("q_meas (from CH2) = NaN")

    # ---------- Logging & close ----------

    def append_log(self, text):
        self.log.append(text)
        self.log.moveCursor(QTextCursor.End)

    def closeEvent(self, event):
        # Timer stoppen
        try:
            self.timer_fg.stop()
        except Exception:
            pass

        # Worker sauber herunterfahren
        if hasattr(self, "worker_thread"):
            try:
                self.cancelSweep.emit()
            except Exception:
                pass
            try:
                self.worker.shutdown()
            except Exception:
                pass
            self.worker_thread.quit()
            self.worker_thread.wait(2000)

        event.accept()
