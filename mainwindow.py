# gui/mainwindow.py
import math
import numpy as np
import time
from typing import Any, Dict, List
from PyQt5 import QtWidgets, QtCore, QtGui
import os
from datetime import datetime
from mpl_toolkits.mplot3d import Axes3D  # für 3D-Plots (Side-Effect-Import)


from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QFormLayout, QFileDialog, QComboBox, QSlider,
    QFrame,QSpinBox,QDoubleSpinBox, QDialog, QGridLayout, QSizePolicy,QInputDialog,QMessageBox
)

from backend import Backend
from backend.config import CHANNELS
from .qt_adapter import QtBackendAdapter
from .rfq_mathieu_lc import RFQUnifiedGUI
from .laser_gui import LaserWindow
from .pressure_monitor import Main as PressureWindow    

SAMPLE_WHEEL_DIR = r"C:\Users\ALIS\Desktop\Samplel Wheel Lists"



class ScrollableSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.control = None  # wird durch create_slider_control gesetzt

    def wheelEvent(self, event):
        if not self.control:
            return
        delta = event.angleDelta().y()
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








#gauge tab
class GaugeWidget(QtWidgets.QWidget):
    """
    Analog half-circle gauge for instantaneous current.
    Scale via set_range(), value via set_value().
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 280)

        self.value = 0.0
        self.min_value = 0.0
        self.max_value = 100.0
        self.unit = "nA"

        # Colors
        self.gauge_color = QtGui.QColor(240, 240, 240)  # background
        self.value_color = QtGui.QColor(0, 150, 255)    # value arc
        self.text_color = QtGui.QColor(0, 0, 0)         # text
        self.needle_color = QtGui.QColor(255, 50, 50)   # needle

    def set_range(self, min_val, max_val, unit):
        self.min_value = float(min_val)
        self.max_value = float(max_val)
        self.unit = unit
        self.update()

    def set_value(self, value):
        self.value = float(value)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        width = self.width()
        height = self.height()

        # Move origin to bottom center so the half circle sits nicely
        painter.translate(width / 2, height * 0.9)

        # Scale so the drawing always fits
        scale = min(width / 220.0, height / 140.0)
        painter.scale(scale, scale)

        # Half-circle from 180° (left) to 0° (right)
        start_angle = 180.0
        end_angle = 0.0
        span_angle = 180.0

        # Angle for current value
        if self.max_value > self.min_value:
            value_angle = start_angle - span_angle * (self.value - self.min_value) / (
                self.max_value - self.min_value
            )
        else:
            value_angle = start_angle

        value_angle = max(end_angle, min(start_angle, value_angle))

        rect = QtCore.QRectF(-100, -100, 200, 200)

        # Background
        painter.setPen(QtGui.QPen(self.gauge_color, 2))
        painter.setBrush(self.gauge_color)
        painter.drawChord(rect, int(start_angle * 16), int(-span_angle * 16))

        # Base arc
        painter.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100), 3))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawArc(rect, int(start_angle * 16), int(-span_angle * 16))

        # Value arc
        painter.setPen(QtGui.QPen(self.value_color, 4))
        painter.drawArc(
            rect,
            int(start_angle * 16),
            int((value_angle - start_angle) * 16),
        )

        # Needle
        needle_angle_rad = math.radians(value_angle)
        needle_length = 85.0
        x = needle_length * math.cos(needle_angle_rad)
        y = needle_length * math.sin(needle_angle_rad)

        painter.setPen(QtGui.QPen(self.needle_color, 3))
        painter.setBrush(self.needle_color)
        painter.drawLine(QtCore.QLineF(0.0, 0.0, x, -y))
        painter.drawEllipse(QtCore.QPointF(0.0, 0.0), 5.0, 5.0)

        # Ticks
        painter.setPen(QtGui.QPen(self.text_color, 2))
        for i in range(11):
            angle = start_angle - i * (span_angle / 10.0)
            rad = math.radians(angle)
            inner = 80.0
            outer = 95.0

            x1 = inner * math.cos(rad)
            y1 = inner * math.sin(rad)
            x2 = outer * math.cos(rad)
            y2 = outer * math.sin(rad)
            painter.drawLine(
                QtCore.QPointF(x1, -y1),
                QtCore.QPointF(x2, -y2),
            )

            # Label every second tick
            if i % 2 == 0:
                if self.max_value > self.min_value:
                    val = self.min_value + (i / 10.0) * (self.max_value - self.min_value)
                else:
                    val = self.min_value
                if (self.max_value - self.min_value) > 10:
                    text = f"{val:.0f}"
                else:
                    text = f"{val:.1f}"

                text_r = 60.0
                tx = text_r * math.cos(rad)
                ty = text_r * math.sin(rad)
                font = painter.font()
                font.setPointSize(7)
                painter.setFont(font)
                painter.drawText(
                    QtCore.QRectF(tx - 20, -ty - 10, 40, 20),
                    QtCore.Qt.AlignCenter,
                    text,
                )

        # Value text
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        value_text = f"{self.value:.2f} {self.unit}"
        painter.drawText(
            QtCore.QRectF(-60, -120, 120, 30),
            QtCore.Qt.AlignCenter,
            value_text,
        )

#plot dialogklasse

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtWidgets import QCheckBox, QVBoxLayout


class KeithleyPlotWindow(QDialog):
    """Popup mit Plot: Interval-Mittel ± Sigma."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keithley Current Plot")

        self.figure = Figure(figsize=(7, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel("Time [s]")
        self.ax.set_ylabel("Current [nA]")

        (self.avg_line,) = self.ax.plot([], [], label="Avg(interval)")
        (self.upper_line,) = self.ax.plot([], [], linestyle="--", label="+σ")
        (self.lower_line,) = self.ax.plot([], [], linestyle="--", label="-σ")
        self.ax.legend(loc="best")

        self.cb_show_error = QCheckBox("Show error bands")
        self.cb_show_error.setChecked(True)
        self.cb_show_error.toggled.connect(self.on_error_band_toggled)

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.addWidget(self.cb_show_error)
        self.setLayout(layout)

        self.xs: list[float] = []
        self.avg_vals: list[float] = []
        self.sigma_vals: list[float] = []

        self.max_points = 3000  # max Punkte im Plot

    def add_point(self, t: float, mean: float, sigma: float):
        self.xs.append(t)
        self.avg_vals.append(mean)
        self.sigma_vals.append(sigma)

        # --- NEU: auf max_points begrenzen ---
        if len(self.xs) > self.max_points:
            overflow = len(self.xs) - self.max_points
            # Älteste Punkte wegschneiden
            self.xs = self.xs[overflow:]
            self.avg_vals = self.avg_vals[overflow:]
            self.sigma_vals = self.sigma_vals[overflow:]
        # -------------------------------------

        lower = [a - s for a, s in zip(self.avg_vals, self.sigma_vals)]
        upper = [a + s for a, s in zip(self.avg_vals, self.sigma_vals)]

        self.avg_line.set_data(self.xs, self.avg_vals)
        self.upper_line.set_data(self.xs, upper)
        self.lower_line.set_data(self.xs, lower)

        show = self.cb_show_error.isChecked()
        self.upper_line.set_visible(show)
        self.lower_line.set_visible(show)

        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    def on_error_band_toggled(self, checked: bool):
        self.upper_line.set_visible(checked)
        self.lower_line.set_visible(checked)
        self.canvas.draw_idle()

#gauge fenster für keithley

class KeithleyGaugeWindow(QDialog):
    """Popup mit analogem Gauge für den Keithley-Strom."""

    def __init__(self, adapter, parent=None):
        super().__init__(parent)
        self.adapter = adapter
        self.setWindowTitle("Keithley Gauge")

        self.ranges = [
            (0, 100, "pA"),
            (0, 300, "pA"),
            (0, 1, "nA"),
            (0, 3, "nA"),
            (0, 10, "nA"),
            (0, 30, "nA"),
            (0, 100, "nA"),
            (0, 300, "nA"),
            (0, 1, "µA"),
            (0, 3, "µA"),
            (0, 10, "µA"),
            (0, 30, "µA"),
        ]
        self.current_range_index = 6  # 0–100 nA
        self.last_current_nA: float | None = None

        layout = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(QLabel("Scale:"))
        self.range_combo = QComboBox()
        for i, (min_val, max_val, unit) in enumerate(self.ranges):
            self.range_combo.addItem(f"0–{max_val} {unit}", userData=i)
        self.range_combo.setCurrentIndex(self.current_range_index)
        self.range_combo.currentIndexChanged.connect(self.on_range_changed)
        top.addWidget(self.range_combo)
        top.addStretch()
        layout.addLayout(top)

        self.gauge = GaugeWidget()
        min_val, max_val, unit = self.ranges[self.current_range_index]
        self.gauge.set_range(min_val, max_val, unit)
        layout.addWidget(self.gauge)

        self.setLayout(layout)

        # auf Kanal abonnieren
        self.adapter.channelUpdated.connect(self.on_channel_updated)
        self.adapter.register_channel("keithley_current_nA")

    def on_range_changed(self, index: int):
        self.current_range_index = index
        min_val, max_val, unit = self.ranges[index]
        self.gauge.set_range(min_val, max_val, unit)
        if self.last_current_nA is not None:
            self._update_gauge(self.last_current_nA)

    def on_channel_updated(self, name: str, value):
        if name != "keithley_current_nA":
            return
        try:
            current_nA = float(value)
        except (TypeError, ValueError):
            current_nA = 0.0
        self.last_current_nA = current_nA
        self._update_gauge(current_nA)

    def _update_gauge(self, current_nA: float):
        min_val, max_val, unit = self.ranges[self.current_range_index]
        if unit == "pA":
            display_value = current_nA * 1000.0
        elif unit == "nA":
            display_value = current_nA
        elif unit == "µA":
            display_value = current_nA / 1000.0
        else:
            display_value = current_nA
        clamped = max(min_val, min(max_val, display_value))
        self.gauge.set_value(clamped)



#magnet calculator
class MagnetCalculatorDialog(QDialog):
    """Popup-Dialog für den Magnet-Calculator."""

    def __init__(self, backend: Backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.setWindowTitle("Magnet Calculator")
        self.setModal(False)
        self.setMinimumWidth(400)

        layout = QGridLayout()

        # Eingaben
        self.mass_input = QDoubleSpinBox()
        self.mass_input.setRange(1, 500)
        self.mass_input.setValue(1.0)
        self.mass_input.setSuffix(" u")
        self.mass_input.valueChanged.connect(self.update_calculations)

        self.extraction_input = QDoubleSpinBox()
        self.extraction_input.setRange(0, 100000)
        self.extraction_input.setValue(1000)
        self.extraction_input.setSuffix(" V")
        self.extraction_input.valueChanged.connect(self.update_calculations)

        self.sputter_input = QDoubleSpinBox()
        self.sputter_input.setRange(0, 100000)
        self.sputter_input.setValue(1000)
        self.sputter_input.setSuffix(" V")
        self.sputter_input.valueChanged.connect(self.update_calculations)

        # Anzeigen
        self.b_field_label = QLabel("0.00 kG")
        self.b_field_label.setStyleSheet("font-weight:bold; color:#2E86C1;")

        self.current_label = QLabel("0.0000 A")
        self.current_label.setStyleSheet("font-weight:bold; color:#27AE60;")

        # Button
        self.set_btn = QPushButton("Set Magnet Current")
        self.set_btn.clicked.connect(self.apply_current)

        # Layout
        row = 0
        layout.addWidget(QLabel("Mass:"), row, 0)
        layout.addWidget(self.mass_input, row, 1)

        row += 1
        layout.addWidget(QLabel("Extraction Voltage:"), row, 0)
        layout.addWidget(self.extraction_input, row, 1)

        row += 1
        layout.addWidget(QLabel("Sputter Voltage:"), row, 0)
        layout.addWidget(self.sputter_input, row, 1)

        row = 0
        layout.addWidget(QLabel("Calculated B Field:"), row, 2)
        layout.addWidget(self.b_field_label, row, 3)

        row += 1
        layout.addWidget(QLabel("Required Current:"), row, 2)
        layout.addWidget(self.current_label, row, 3)

        row += 1
        layout.addWidget(self.set_btn, row, 2, 1, 2)

        self.setLayout(layout)
        self.update_calculations()

    def update_calculations(self):
        try:
            mass_u = self.mass_input.value()
            extraction_v = self.extraction_input.value()
            sputter_v = self.sputter_input.value()

            mass_kg = mass_u * 1.66054e-27  # kg
            total_energy_ev = extraction_v + sputter_v

            # B-Feld-Berechnung (wie in deinem Code)
            q = 1.60218e-19
            b_field_tesla = np.sqrt(
                2 * total_energy_ev * q * mass_kg
            ) / (q * 0.5)

            b_field_kG = b_field_tesla * 10.0  # 1 T = 10 kG

            # Stromberechnung (Kalibrier-Formel)
            current = (b_field_kG - 0.0937) / 0.1055

            self.b_field_label.setText(f"{b_field_kG:.2f} kG")
            self.current_label.setText(f"{current:.4f} A")
        except Exception:
            self.b_field_label.setText("ERR")
            self.current_label.setText("ERR")

    def apply_current(self):
        """Berechneten Strom an das Backend schicken."""
        try:
            text = self.current_label.text()
            value = float(text.split()[0])
            self.backend.set_magnet_current(value)
        except Exception:
            pass




class TracerDialog(QDialog):
    """Popup-Dialog zum Tracen eines analogen Parameters gegen Keithley-Avg."""

    def __init__(self, main_window: "OPCControlPanel"):
        super().__init__(main_window)
        self.main = main_window
        self.backend = main_window.backend
        self.setWindowTitle("Parameter Tracer")
        self.setModal(False)
        self.resize(800, 500)

        # Zustand
        self.param_key: str | None = None
        self.param_info: dict | None = None

        self.original_value: float | None = None
        self.applied_value: float | None = None  # wird gesetzt, wenn User "Apply" drückt

        self.step_values: list[float] = []
        self.current_step_index: int = -1
        self.step_elapsed: float = 0.0
        self.dwell_time: float = 1.0

        self.tracing_active: bool = False

        self.x_values: list[float] = []
        self.y_values: list[float] = []
        self.selected_index: int | None = None

        self._build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_tick)

        # Initial: ersten Parameter auswählen
        if self.param_combo.count() > 0:
            self.param_combo.setCurrentIndex(0)
            self._update_param_fields()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- obere Leiste: Parameterauswahl + Zahlen ---
        form = QGridLayout()
        row = 0

        form.addWidget(QLabel("Parameter:"), row, 0)
        self.param_combo = QComboBox()
        for key, info in self.main.tracer_params.items():
            self.param_combo.addItem(info["label"], userData=key)
        self.param_combo.currentIndexChanged.connect(self._on_param_changed)
        form.addWidget(self.param_combo, row, 1, 1, 3)

        row += 1
        form.addWidget(QLabel("Start:"), row, 0)
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setDecimals(3)
        self.start_spin.setSingleStep(0.1)
        form.addWidget(self.start_spin, row, 1)

        form.addWidget(QLabel("End:"), row, 2)
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setDecimals(3)
        self.end_spin.setSingleStep(0.1)
        form.addWidget(self.end_spin, row, 3)

        row += 1
        form.addWidget(QLabel("Step size:"), row, 0)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setDecimals(3)
        self.step_spin.setSingleStep(0.1)
        self.step_spin.setMinimum(0.0001)
        form.addWidget(self.step_spin, row, 1)

        form.addWidget(QLabel("Dwell per step (s):"), row, 2)
        self.dwell_spin = QDoubleSpinBox()
        self.dwell_spin.setDecimals(1)
        self.dwell_spin.setSingleStep(0.5)
        self.dwell_spin.setRange(1.0, 600.0)  # min 1 s, damit 1-s-Avg sinnvoll
        self.dwell_spin.setValue(2.0)
        form.addWidget(self.dwell_spin, row, 3)

        row += 1
        self.status_label = QLabel("Ready.")
        form.addWidget(self.status_label, row, 0, 1, 4)

        layout.addLayout(form)

        # --- Plot ---
        self.figure = Figure(figsize=(6, 3), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel("Setpoint")
        self.ax.set_ylabel("Keithley avg [nA]")

        (self.trace_line,) = self.ax.plot([], [], marker="o")
        self.vline = self.ax.axvline(0.0, color="red", visible=False)
        self.canvas.mpl_connect("button_press_event", self._on_plot_click)

        layout.addWidget(self.canvas, stretch=1)

        # --- untere Buttons ---
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Trace")
        self.start_btn.clicked.connect(self.start_trace)
        btn_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_trace)
        btn_row.addWidget(self.stop_btn)

        btn_row.addStretch()

        self.apply_btn = QPushButton("Apply & Close")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply_and_close)
        btn_row.addWidget(self.apply_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(self.cancel_btn)

        layout.addLayout(btn_row)

    # ---------------- Parameterauswahl ----------------

    def _on_param_changed(self, index: int):
        self._update_param_fields()

    def _update_param_fields(self):
        key = self.param_combo.currentData()
        if not key:
            return
        info = self.main.tracer_params.get(key)
        if not info:
            return
        self.param_key = key
        self.param_info = info

        # Bereich und aktuellen Wert übernehmen
        vmin = info["min"]
        vmax = info["max"]
        current = info["read"]()

        for spin in (self.start_spin, self.end_spin, self.step_spin):
            spin.blockSignals(True)
            spin.setRange(vmin, vmax)
            spin.blockSignals(False)

        self.start_spin.setValue(current)
        self.end_spin.setValue(current)
        # sinnvolle Default-Stepgröße
        span = vmax - vmin
        default_step = span / 20.0 if span > 0 else 1.0
        self.step_spin.setValue(max(default_step, 0.001))

        self.status_label.setText(f"Ready for {info['label']} (current={current:.3f}).")

    # ---------------- Tracing-Logik ----------------

    def start_trace(self):
        if self.tracing_active:
            return
        if self.param_info is None or self.param_key is None:
            return

        start = self.start_spin.value()
        end = self.end_spin.value()
        step = self.step_spin.value()
        dwell = self.dwell_spin.value()

        if step <= 0:
            QtWidgets.QMessageBox.warning(self, "Tracer", "Step size must be > 0.")
            return
        if start == end:
            QtWidgets.QMessageBox.warning(self, "Tracer", "Start and End must differ.")
            return

        # Step-Liste erzeugen
        values: list[float] = []
        if start < end:
            v = start
            while v < end - 1e-9:
                values.append(v)
                v += step
            values.append(end)
        else:
            v = start
            while v > end + 1e-9:
                values.append(v)
                v -= step
            values.append(end)

        if not values:
            QtWidgets.QMessageBox.warning(self, "Tracer", "No steps generated.")
            return

        # ursprünglichen Wert merken
        self.original_value = float(self.param_info["read"]())

        self.step_values = values
        self.dwell_time = float(dwell)
        self.current_step_index = -1
        self.step_elapsed = 0.0

        self.x_values.clear()
        self.y_values.clear()
        self.selected_index = None
        self.applied_value = None
        self._update_plot()

        self.tracing_active = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.apply_btn.setEnabled(False)

        self.status_label.setText(
            f"Tracing {self.param_info['label']} over {len(values)} steps "
            f"(dwell {self.dwell_time:.1f} s)."
        )

        # Timer starten und ersten Step setzen
        self.timer.start(1000)
        self._next_step()

    def _next_step(self):
        """Nächsten Setpoint setzen oder Trace beenden."""
        self.current_step_index += 1
        if self.current_step_index >= len(self.step_values):
            # fertig
            self._finish_trace()
            return

        value = float(self.step_values[self.current_step_index])
        # Setzen des Parameters
        if self.param_info is not None:
            self.param_info["set"](value)

        self.step_elapsed = 0.0
        self.status_label.setText(
            f"Step {self.current_step_index+1}/{len(self.step_values)}: "
            f"setpoint = {value:.3f}, waiting..."
        )

    def _on_timer_tick(self):
        if not self.tracing_active:
            return

        self.step_elapsed += 1.0
        remaining = max(0.0, self.dwell_time - self.step_elapsed)
        self.status_label.setText(
            f"Step {self.current_step_index+1}/{len(self.step_values)}: "
            f"waiting... ({remaining:.0f} s left)"
        )

        if self.step_elapsed < self.dwell_time:
            return

        # Dwell-Zeit vorbei -> 1-s-Avg vom Keithley holen
        avg = self.main.get_keithley_avg_last_1s()
        if avg is None:
            avg = float("nan")

        setpoint = self.step_values[self.current_step_index]
        self.x_values.append(setpoint)
        self.y_values.append(avg)
        self._update_plot()

        # Nächsten Schritt
        self._next_step()

    def _finish_trace(self):
        self.tracing_active = False
        self.timer.stop()
        self.stop_btn.setEnabled(False)

        if self.x_values:
            # Default: Maximum auswählen
            max_idx = max(range(len(self.x_values)), key=lambda i: self.y_values[i])
            self._select_index(max_idx)
            self.apply_btn.setEnabled(True)
            self.status_label.setText(
                f"Trace finished. Max at {self.x_values[max_idx]:.3f}, "
                f"Keithley={self.y_values[max_idx]:.2f} nA."
            )
        else:
            self.status_label.setText("Trace finished (no data).")

        # erneutes Starten wäre möglich
        self.start_btn.setEnabled(True)

    def stop_trace(self):
        """Tracer vorzeitig stoppen, Fenster bleibt offen."""
        if not self.tracing_active:
            return
        self.tracing_active = False
        self.timer.stop()
        self.stop_btn.setEnabled(False)

        # <<< HIER neu: Start-Button wieder freigeben
        self.start_btn.setEnabled(True)

        if self.x_values:
            max_idx = max(range(len(self.x_values)), key=lambda i: self.y_values[i])
            self._select_index(max_idx)
            self.apply_btn.setEnabled(True)
            self.status_label.setText(
                f"Trace stopped early. Max at {self.x_values[max_idx]:.3f}, "
                f"Keithley={self.y_values[max_idx]:.2f} nA."
            )
        else:
            self.status_label.setText("Trace stopped (no data yet).")

    # ---------------- Plot / Auswahl ----------------

    def _update_plot(self):
        """Trace-Linie + vertikale Auswahl-Linie aktualisieren und Achsen neu skalieren."""
        # Trace-Daten in bestehende Linie schreiben
        self.trace_line.set_data(self.x_values, self.y_values)

        # Vertikale Linie je nach Auswahl setzen/ausblenden
        if self.selected_index is not None and self.x_values:
            xsel = self.x_values[self.selected_index]
            # axvline ist eine Line2D mit zwei x-Punkten
            self.vline.set_xdata([xsel, xsel])
            self.vline.set_visible(True)
        else:
            self.vline.set_visible(False)

        # Nur wenn Daten vorhanden sind, skalieren
        if self.x_values:
            xmin = min(self.x_values)
            xmax = max(self.x_values)
            if xmin == xmax:
                # Sonderfall: nur ein Punkt
                xmin -= 0.5
                xmax += 0.5
            span_x = xmax - xmin
            pad_x = 0.05 * span_x
            self.ax.set_xlim(xmin - pad_x, xmax + pad_x)

            ymin = min(self.y_values)
            ymax = max(self.y_values)
            if ymin == ymax:
                ymin -= 0.5
                ymax += 0.5
            span_y = ymax - ymin
            pad_y = 0.1 * span_y
            self.ax.set_ylim(ymin - pad_y, ymax + pad_y)

        self.canvas.draw_idle()

    def _on_plot_click(self, event):
        """Klick in den Plot: nächstgelegenen Punkt auswählen."""
        if event.inaxes != self.ax:
            return
        if not self.x_values:
            return
        if event.xdata is None:
            return

        x_click = float(event.xdata)
        # nächster Setpoint
        idx = min(range(len(self.x_values)),
                  key=lambda i: abs(self.x_values[i] - x_click))
        self._select_index(idx)

    def _select_index(self, idx: int):
        if not (0 <= idx < len(self.x_values)):
            return

        self.selected_index = idx
        xsel = self.x_values[idx]
        ysel = self.y_values[idx]

        # Plot aktualisieren (setzt auch die vertikale Linie)
        self._update_plot()

        self.status_label.setText(
            f"Selected setpoint = {xsel:.3f}, Keithley={ysel:.2f} nA."
        )
        self.apply_btn.setEnabled(True)

    # ---------------- Apply / Close ----------------

    def apply_and_close(self):
        """Gewählten Wert setzen und Dialog schließen."""
        if self.param_info is None or self.selected_index is None:
            self.close()
            return
        value = float(self.x_values[self.selected_index])
        self.param_info["set"](value)
        self.applied_value = value
        self.close()

    def closeEvent(self, event):
        # Tracing ggf. stoppen
        if self.tracing_active:
            self.tracing_active = False
            self.timer.stop()

        # Wenn nichts angewendet wurde -> ursprünglichen Wert wiederherstellen
        if self.applied_value is None and self.original_value is not None and self.param_info is not None:
            self.param_info["set"](self.original_value)

        super().closeEvent(event)

class Tracer2DDialog(QDialog):
    """
    2D-Parameter-Tracer:
      - Parameter 1: Start/End/Step/Dwell
      - Parameter 2: Start/End/Step/Dwell
      - Scan: für jeden Wert von Param2 alle Werte von Param1
      - Pro Kombination: 1-s-Keithley-Avg
      - Ergebnis: 3D-Plot + 1D-Plot (Index vs. Strom) mit vertikalem Marker.
    """

    def __init__(self, main_window: "OPCControlPanel"):
        super().__init__(main_window)
        self.main = main_window
        self.backend = main_window.backend

        self.setWindowTitle("2D Parameter Tracer")
        self.setModal(False)
        self.resize(1400, 800)

        # --- Zustand / Parameter-Auswahl ---
        self.param1_key: str | None = None
        self.param2_key: str | None = None
        self.param1_info: dict | None = None
        self.param2_info: dict | None = None

        self.original_val1: float | None = None
        self.original_val2: float | None = None
        self.applied_values: tuple[float, float] | None = None

        # Schrittlisten
        self.param1_values: list[float] = []
        self.param2_values: list[float] = []

        # Indizes im Scan
        self.idx1: int = -1  # Index in param1_values
        self.idx2: int = -1  # Index in param2_values

        # Zeit / Dwell
        self.step_elapsed: float = 0.0
        self.dwell1: float = 1.0  # Param1 dwell (innerer Loop)
        self.dwell2: float = 1.0  # Param2 dwell (äußerer Loop)
        self.phase: str = ""      # "outer_dwell" oder "inner_dwell"

        self.tracing_active: bool = False

        # Messdaten
        self.x_values: list[float] = []  # Param1
        self.y_values: list[float] = []  # Param2
        self.z_values: list[float] = []  # Keithley-Avg
        self.selected_index: int | None = None

        self._build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_tick)

        # Parameterauswahl initialisieren
        if self.param1_combo.count() > 0:
            self.param1_combo.setCurrentIndex(0)
            self._update_param1_fields()
        if self.param2_combo.count() > 1:
            self.param2_combo.setCurrentIndex(1)
            self._update_param2_fields()

    # ---------------- UI-Aufbau ----------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- Oben: Parameterauswahl und Zahlen ---
        grid = QGridLayout()
        row = 0

        # Parameter 1
        grid.addWidget(QLabel("Parameter 1:"), row, 0)
        self.param1_combo = QComboBox()
        for key, info in self.main.tracer_params.items():
            self.param1_combo.addItem(info["label"], userData=key)
        self.param1_combo.currentIndexChanged.connect(self._on_param1_changed)
        grid.addWidget(self.param1_combo, row, 1, 1, 3)

        row += 1
        grid.addWidget(QLabel("Start 1:"), row, 0)
        self.start1_spin = QDoubleSpinBox()
        self.start1_spin.setDecimals(3)
        self.start1_spin.setSingleStep(0.1)
        grid.addWidget(self.start1_spin, row, 1)

        grid.addWidget(QLabel("End 1:"), row, 2)
        self.end1_spin = QDoubleSpinBox()
        self.end1_spin.setDecimals(3)
        self.end1_spin.setSingleStep(0.1)
        grid.addWidget(self.end1_spin, row, 3)

        row += 1
        grid.addWidget(QLabel("Step 1:"), row, 0)
        self.step1_spin = QDoubleSpinBox()
        self.step1_spin.setDecimals(3)
        self.step1_spin.setSingleStep(0.1)
        self.step1_spin.setMinimum(0.0001)
        grid.addWidget(self.step1_spin, row, 1)

        grid.addWidget(QLabel("Dwell 1 (s):"), row, 2)
        self.dwell1_spin = QDoubleSpinBox()
        self.dwell1_spin.setDecimals(1)
        self.dwell1_spin.setSingleStep(0.5)
        self.dwell1_spin.setRange(1.0, 600.0)
        self.dwell1_spin.setValue(2.0)
        grid.addWidget(self.dwell1_spin, row, 3)

        # Parameter 2
        row += 1
        grid.addWidget(QLabel("Parameter 2:"), row, 0)
        self.param2_combo = QComboBox()
        for key, info in self.main.tracer_params.items():
            self.param2_combo.addItem(info["label"], userData=key)
        self.param2_combo.currentIndexChanged.connect(self._on_param2_changed)
        grid.addWidget(self.param2_combo, row, 1, 1, 3)

        row += 1
        grid.addWidget(QLabel("Start 2:"), row, 0)
        self.start2_spin = QDoubleSpinBox()
        self.start2_spin.setDecimals(3)
        self.start2_spin.setSingleStep(0.1)
        grid.addWidget(self.start2_spin, row, 1)

        grid.addWidget(QLabel("End 2:"), row, 2)
        self.end2_spin = QDoubleSpinBox()
        self.end2_spin.setDecimals(3)
        self.end2_spin.setSingleStep(0.1)
        grid.addWidget(self.end2_spin, row, 3)

        row += 1
        grid.addWidget(QLabel("Step 2:"), row, 0)
        self.step2_spin = QDoubleSpinBox()
        self.step2_spin.setDecimals(3)
        self.step2_spin.setSingleStep(0.1)
        self.step2_spin.setMinimum(0.0001)
        grid.addWidget(self.step2_spin, row, 1)

        grid.addWidget(QLabel("Dwell 2 (s):"), row, 2)
        self.dwell2_spin = QDoubleSpinBox()
        self.dwell2_spin.setDecimals(1)
        self.dwell2_spin.setSingleStep(0.5)
        self.dwell2_spin.setRange(1.0, 600.0)
        self.dwell2_spin.setValue(2.0)
        grid.addWidget(self.dwell2_spin, row, 3)

        row += 1
        self.status_label = QLabel("Ready.")
        grid.addWidget(self.status_label, row, 0, 1, 4)

        layout.addLayout(grid)

        # --- Plotbereich: großer Landscape-Plot mit 3D oben, 1D unten ---
        self.figure = Figure(figsize=(11, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)

        # 2 Zeilen, 1 Spalte: oben 3D, unten 1D
        gs = self.figure.add_gridspec(2, 1, height_ratios=[3, 1])

        # Großer 3D-Plot oben
        self.ax3d = self.figure.add_subplot(gs[0, 0], projection="3d")

        # Schmaler 1D-Plot unten für die Auswahllinie
        self.ax1d = self.figure.add_subplot(gs[1, 0])

        # Etwas Rand & wenig Abstand zwischen den beiden Plots
        self.figure.subplots_adjust(
            left=0.07,
            right=0.98,
            top=0.96,
            bottom=0.08,
            hspace=0.05,   # geringer vertikaler Abstand
        )

        layout.addWidget(self.canvas, stretch=1)

        # --- Buttons unten ---
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start 2D Trace")
        self.start_btn.clicked.connect(self.start_trace)
        btn_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_trace)
        btn_row.addWidget(self.stop_btn)

        btn_row.addStretch()

        self.apply_btn = QPushButton("Apply & Close")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply_and_close)
        btn_row.addWidget(self.apply_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(self.cancel_btn)

        layout.addLayout(btn_row)

    # ---------------- Parameter-Felder aktualisieren ----------------

    def _on_param1_changed(self, index: int):
        self._update_param1_fields()

    def _on_param2_changed(self, index: int):
        self._update_param2_fields()

    def _update_param1_fields(self):
        key = self.param1_combo.currentData()
        if not key:
            return
        info = self.main.tracer_params.get(key)
        if not info:
            return
        self.param1_key = key
        self.param1_info = info

        vmin = info["min"]
        vmax = info["max"]
        current = float(info["read"]())

        for spin in (self.start1_spin, self.end1_spin, self.step1_spin):
            spin.blockSignals(True)
            spin.setRange(vmin, vmax)
            spin.blockSignals(False)

        self.start1_spin.setValue(current)
        self.end1_spin.setValue(current)
        span = vmax - vmin
        default_step = span / 20.0 if span > 0 else 1.0
        self.step1_spin.setValue(max(default_step, 0.001))

        self.status_label.setText(
            f"Ready for {info['label']} as Parameter 1 (current={current:.3f})."
        )

    def _update_param2_fields(self):
        key = self.param2_combo.currentData()
        if not key:
            return
        info = self.main.tracer_params.get(key)
        if not info:
            return
        self.param2_key = key
        self.param2_info = info

        vmin = info["min"]
        vmax = info["max"]
        current = float(info["read"]())

        for spin in (self.start2_spin, self.end2_spin, self.step2_spin):
            spin.blockSignals(True)
            spin.setRange(vmin, vmax)
            spin.blockSignals(False)

        self.start2_spin.setValue(current)
        self.end2_spin.setValue(current)
        span = vmax - vmin
        default_step = span / 20.0 if span > 0 else 1.0
        self.step2_spin.setValue(max(default_step, 0.001))

        self.status_label.setText(
            f"Ready for {info['label']} as Parameter 2 (current={current:.3f})."
        )

    # ---------------- Start / Scan-Logik ----------------

    def start_trace(self):
        if self.tracing_active:
            return
        if self.param1_info is None or self.param2_info is None:
            return

        if self.param1_key == self.param2_key:
            QtWidgets.QMessageBox.warning(
                self, "2D Tracer",
                "Parameter 1 und Parameter 2 dürfen nicht identisch sein."
            )
            return

        start1 = self.start1_spin.value()
        end1 = self.end1_spin.value()
        step1 = self.step1_spin.value()
        dwell1 = self.dwell1_spin.value()

        start2 = self.start2_spin.value()
        end2 = self.end2_spin.value()
        step2 = self.step2_spin.value()
        dwell2 = self.dwell2_spin.value()

        if step1 <= 0 or step2 <= 0:
            QtWidgets.QMessageBox.warning(self, "2D Tracer", "Step sizes must be > 0.")
            return
        if start1 == end1 or start2 == end2:
            QtWidgets.QMessageBox.warning(
                self, "2D Tracer", "Start and End for both parameters must differ."
            )
            return

        # --- Step-Listen erzeugen (wie im 1D-Tracer) ---
        def build_values(start, end, step):
            vals = []
            if start < end:
                v = start
                while v < end - 1e-9:
                    vals.append(v)
                    v += step
                vals.append(end)
            else:
                v = start
                while v > end + 1e-9:
                    vals.append(v)
                    v -= step
                vals.append(end)
            return vals

        values1 = build_values(start1, end1, step1)
        values2 = build_values(start2, end2, step2)

        if not values1 or not values2:
            QtWidgets.QMessageBox.warning(self, "2D Tracer", "No steps generated.")
            return

        # Ursprüngliche Werte merken
        self.original_val1 = float(self.param1_info["read"]())
        self.original_val2 = float(self.param2_info["read"]())

        self.param1_values = values1
        self.param2_values = values2
        self.dwell1 = float(dwell1)
        self.dwell2 = float(dwell2)

        self.idx1 = -1
        self.idx2 = 0
        self.step_elapsed = 0.0
        self.phase = "outer_dwell"

        self.x_values.clear()
        self.y_values.clear()
        self.z_values.clear()
        self.selected_index = None
        self.applied_values = None
        self._update_plot()

        # Param2 auf ersten Wert setzen
        if self.param2_info is not None:
            self.param2_info["set"](self.param2_values[self.idx2])

        self.tracing_active = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.apply_btn.setEnabled(False)

        self.status_label.setText(
            f"2D-Tracing: {self.param1_info['label']} × {self.param2_info['label']} "
            f"({len(values1)} × {len(values2)} Punkte)."
        )

        self.timer.start(1000)  # 1 s Takt

    def _on_timer_tick(self):
        if not self.tracing_active:
            return

        self.step_elapsed += 1.0

        if self.phase == "outer_dwell":
            # Warten nach Param2-Wechsel
            remaining = max(0.0, self.dwell2 - self.step_elapsed)
            self.status_label.setText(
                f"Param2 {self.idx2+1}/{len(self.param2_values)}: "
                f"outer dwell... ({remaining:.0f} s left)"
            )
            if self.step_elapsed < self.dwell2:
                return
            # Außen-Dwell fertig -> ersten inneren Schritt starten
            self.step_elapsed = 0.0
            self._start_next_inner_step()
            return

        if self.phase == "inner_dwell":
            remaining = max(0.0, self.dwell1 - self.step_elapsed)
            self.status_label.setText(
                f"Param2 {self.idx2+1}/{len(self.param2_values)}, "
                f"Param1 {self.idx1+1}/{len(self.param1_values)}: "
                f"inner dwell... ({remaining:.0f} s left)"
            )
            if self.step_elapsed < self.dwell1:
                return

            # Dwell für Param1 vorbei -> Messung
            set1 = self.param1_values[self.idx1]
            set2 = self.param2_values[self.idx2]

            avg = self.main.get_keithley_avg_last_1s()
            if avg is None:
                avg = float("nan")

            self.x_values.append(set1)
            self.y_values.append(set2)
            self.z_values.append(avg)
            self._update_plot()

            # Nächster innerer Schritt
            self._start_next_inner_step()
            return

    def _start_next_inner_step(self):
        """Nächsten Wert von Param1 (innerer Loop) setzen oder auf nächste Param2-Zeile springen."""
        self.idx1 += 1
        if self.idx1 >= len(self.param1_values):
            # Diese Zeile fertig -> nächste Zeile (Param2)
            self.idx2 += 1
            if self.idx2 >= len(self.param2_values):
                # Alles fertig
                self._finish_trace()
                return

            # Nächsten Param2-Wert setzen, dann outer dwell
            if self.param2_info is not None:
                self.param2_info["set"](self.param2_values[self.idx2])
            self.idx1 = -1
            self.step_elapsed = 0.0
            self.phase = "outer_dwell"
            return

        # Param1 auf neuen Wert setzen, inner dwell starten
        if self.param1_info is not None:
            self.param1_info["set"](self.param1_values[self.idx1])
        self.step_elapsed = 0.0
        self.phase = "inner_dwell"

    def _finish_trace(self):
        self.tracing_active = False
        self.timer.stop()
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(True)

        if self.z_values:
            # Maximales Signal automatisch auswählen
            max_idx = max(
                range(len(self.z_values)),
                key=lambda i: (self.z_values[i] if self.z_values[i] is not None else float("-inf"))
            )
            self._select_index(max_idx)
            self.apply_btn.setEnabled(True)
            xsel = self.x_values[max_idx]
            ysel = self.y_values[max_idx]
            zsel = self.z_values[max_idx]
            self.status_label.setText(
                f"2D-Trace finished. Max at "
                f"({xsel:.3f}, {ysel:.3f}), Keithley={zsel:.2f} nA."
            )
        else:
            self.status_label.setText("2D-Trace finished (no data).")

    def stop_trace(self):
        """2D-Tracer vorzeitig stoppen, Fenster bleibt offen."""
        if not self.tracing_active:
            return
        self.tracing_active = False
        self.timer.stop()
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(True)

        if self.z_values:
            max_idx = max(
                range(len(self.z_values)),
                key=lambda i: (self.z_values[i] if self.z_values[i] is not None else float("-inf"))
            )
            self._select_index(max_idx)
            self.apply_btn.setEnabled(True)
            xsel = self.x_values[max_idx]
            ysel = self.y_values[max_idx]
            zsel = self.z_values[max_idx]
            self.status_label.setText(
                f"2D-Trace stopped early. Max at "
                f"({xsel:.3f}, {ysel:.3f}), Keithley={zsel:.2f} nA."
            )
        else:
            self.status_label.setText("2D-Trace stopped (no data yet).")

    # ---------------- Plot / Auswahl ----------------

    def _update_plot(self):
        self.ax3d.clear()
        self.ax1d.clear()

        # 3D-Plot
        self.ax3d.set_xlabel(
            self.param1_info["label"] if self.param1_info else "Param1"
        )
        self.ax3d.set_ylabel(
            self.param2_info["label"] if self.param2_info else "Param2"
        )
        self.ax3d.set_zlabel("Keithley avg [nA]")

        if self.x_values:
            xs = np.array(self.x_values, dtype=float)
            ys = np.array(self.y_values, dtype=float)
            zs = np.array(self.z_values, dtype=float)

            # Alle Punkte
            self.ax3d.scatter(xs, ys, zs, s=20)

            # Optional: angenehme 3D-Ansicht
            self.ax3d.view_init(elev=25, azim=-60)

            # 1D-Plot (Index vs. Strom) unten
            indices = np.arange(len(zs))
            self.ax1d.plot(indices, zs, marker="o")
            self.ax1d.set_xlabel("Step index")
            self.ax1d.set_ylabel("Keithley avg [nA]")

            # Auswahl-Highlight
            if self.selected_index is not None and 0 <= self.selected_index < len(zs):
                idx = self.selected_index
                xsel = xs[idx]
                ysel = ys[idx]
                zsel = zs[idx]

                # Vertikale Linie im 1D-Plot
                self.ax1d.axvline(idx, color="red")

                # Selektierten Punkt im 3D-Plot hervorheben
                zmin = float(np.nanmin(zs))
                zmax = float(np.nanmax(zs))
                self.ax3d.plot(
                    [xsel, xsel],
                    [ysel, ysel],
                    [zmin, zmax],
                    color="red",
                )
                self.ax3d.scatter([xsel], [ysel], [zsel], color="red", s=50)

        self.canvas.draw_idle()

    def _on_plot_click(self, event):
        """Klick im unteren (1D-)Plot: nächstgelegenen Index auswählen."""
        if event.inaxes != self.ax1d:
            return
        if not self.z_values:
            return
        if event.xdata is None:
            return

        x_click = float(event.xdata)
        idx = int(round(x_click))
        if idx < 0 or idx >= len(self.z_values):
            return
        self._select_index(idx)

    def _select_index(self, idx: int):
        if not (0 <= idx < len(self.z_values)):
            return
        self.selected_index = idx
        xsel = self.x_values[idx]
        ysel = self.y_values[idx]
        zsel = self.z_values[idx]
        self.status_label.setText(
            f"Selected ({xsel:.3f}, {ysel:.3f}), Keithley={zsel:.2f} nA."
        )
        self.apply_btn.setEnabled(True)
        self._update_plot()

    # ---------------- Apply / Close ----------------

    def apply_and_close(self):
        """Gewählte Kombination setzen und Dialog schließen."""
        if (
            self.param1_info is None
            or self.param2_info is None
            or self.selected_index is None
        ):
            self.close()
            return

        xsel = float(self.x_values[self.selected_index])
        ysel = float(self.y_values[self.selected_index])

        self.param1_info["set"](xsel)
        self.param2_info["set"](ysel)
        self.applied_values = (xsel, ysel)
        self.close()

    def closeEvent(self, event):
        # Laufenden Trace stoppen
        if self.tracing_active:
            self.tracing_active = False
            self.timer.stop()

        # Falls nichts angewendet wurde -> ursprüngliche Werte wiederherstellen
        if self.applied_values is None:
            if self.param1_info is not None and self.original_val1 is not None:
                self.param1_info["set"](self.original_val1)
            if self.param2_info is not None and self.original_val2 is not None:
                self.param2_info["set"](self.original_val2)

        super().closeEvent(event)


class OPCControlPanel(QMainWindow):
    def __init__(self, backend: Backend, adapter: QtBackendAdapter):
        super().__init__()
        self.setWindowTitle("FLAVIA – Fully integrated Laser & Anion Variables Interface for AMS")
        self.setGeometry(100, 100, 800, 800)

        self.backend = backend
        self.adapter = adapter

        # Overlay für "Loading..." beim Start
        self.loading_overlay = None

        # Status-Flags
        self.opc_ok = False
        self.mqtt_ok = False

        # Magnet-/Gauss-Status
        self.magnet_ok = False
        self.gauss_ok = False

        # damit wir den Slider nur einmal beim Start mit dem Messwert synchronisieren
        self.magnet_slider_initialized = False

        # Keithley / Picoammeter
        self.keithley_connected = False
        self.keithley_avg_interval = 1.0
        self.keithley_bucket_start = None
        self.keithley_bucket_values = []
        self.keithley_t0 = None  # Zeit-Nullpunkt für Plot

        self.keithley_plot_window: KeithleyPlotWindow | None = None
        self.keithley_gauge_window: KeithleyGaugeWindow | None = None

        # Samples für Tracer (1-s-Avg)
        self.keithley_trace_samples = []  # Liste aus (timestamp, current_nA)
        self.keithley_trace_max_age = 5.0  # wir halten max. 5 s Historie

        # Magnet-Calculator Dialog
        self.magnet_calc_dialog = None
 
        # Tracer-Dialog
        self.tracer_dialog = None
        self.tracer2d_dialog = None

        #pressure zeugs
        self.pressure_window = None


        # RFQ (Mathieu + LC) Fenster
        self.rfq_window = None

        #laser fenster  
        self.laser_window = None

        # Magnet-Calculator Dialog
        self.magnet_calc_dialog = None

        # Sample Selection / Stepper
        self.sample_position_file = r"C:\\Users\\ALIS\\Desktop\\ALIS_LABVIEW\\ALIS_Positionen.txt"
        # Position -> Steps (Motorschritte)
        self.sample_positions: Dict[int, int] = {}
        # Position -> Label aus ALIS_Positionen.txt (z.B. "1", "Pos 1", ...)
        self.sample_labels: Dict[int, str] = {}
        # Position -> Material aus Sample-Wheel-List
        self.sample_materials: Dict[int, str] = {}
        # Reihenfolge der Positionen für das Combobox-Listing
        self.sample_index_order: List[int] = []
        # Merkt sich zuletzt geladene Wheel-List (optional)
        self.sample_wheel_list_path: str | None = None

        # Schrittgrößen
        self.allowed_steps = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]

        # Config-Speicher (GUI-Konfigurationen)
        self.config_base_dir = r"C:\Users\ALIS\Desktop\FLAVIA Configs"
        self.config_ramp_timer: QTimer | None = None
        self.config_ramp_total_secs = 60
        self.config_ramp_step_index = 0
        self.config_ramp_entries: list[dict] = []

        # Mapping: Channel -> Widgets/Controls
        self.checkbox_by_channel: Dict[str, QCheckBox] = {}
        self.slider_controls_by_channel: Dict[str, Dict[str, Any]] = {}
        self.measurement_labels_by_channel: Dict[str, QLabel] = {}

        # für MQTT-Stale-Anzeige
        self.mqtt_staleThresholdSecs = 3.0

        self.init_ui()

        

        # Backend-Kanalupdates hören
        self.adapter.channelUpdated.connect(self.on_channel_updated)

        # GUI-Timer für MQTT-Stale
        self.gui_timer = QTimer(self)
        self.gui_timer.timeout.connect(self.refresh_mqtt_stale)
        self.gui_timer.start(1000)

    #append status für rfq logging
    def append_status(self, text: str):
        """
        Kleine Hilfsmethode für Status-/Log-Meldungen,
        damit die RFQ-Config-Helfer nicht jedes Mal direkt
        an status_label / Log schreiben müssen.
        """
        # Statuszeile aktualisieren
        try:
            self.status_label.setText(text)
        except AttributeError:
            pass

        # Optional: wenn du ein Text-Log im Hauptfenster hast, hier auch reinschreiben:
        # try:
        #     self.log.append(text)
        # except AttributeError:
        #     pass

        # Optional zusätzlich in die Konsole:
        # print(text)


    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        main_layout.setSpacing(3)
        central_widget.setLayout(main_layout)

        # --------- Status + Buttons -----------------------------------
        self.status_label = QLabel("Status: Starting backend...")
        self.status_label.setStyleSheet("color:#666")
        self.adapter.register_channel("opc_connected")

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(5)

        self.refresh_btn = QPushButton("Force OPC Poll")
        self.refresh_btn.clicked.connect(self.force_opc_poll)

        self.connect_btn = QPushButton("Reconnect OPC")
        self.connect_btn.clicked.connect(self.reconnect_opc)

        self.log_btn = QPushButton("Start Logging")
        self.log_btn.setCheckable(True)
        self.log_btn.clicked.connect(self.toggle_logging)

        self.save_config_btn = QPushButton("Save Config")
        self.save_config_btn.clicked.connect(self.save_config)

        self.load_config_btn = QPushButton("Load Config")
        self.load_config_btn.clicked.connect(self.load_config)

        self.magnet_calc_btn = QPushButton("Magnet Calculator")
        self.magnet_calc_btn.clicked.connect(self.open_magnet_calculator)

        self.keithley_gauge_btn = QPushButton("Keithley Gauge")
        self.keithley_gauge_btn.clicked.connect(self.open_keithley_gauge)

        self.keithley_plot_btn = QPushButton("Keithley Plot")
        self.keithley_plot_btn.clicked.connect(self.open_keithley_plot)

        self.pressure_btn = QtWidgets.QPushButton("Pressure Monitor")
        self.pressure_btn.clicked.connect(self.open_pressure_window)

        self.mathieu_btn = QPushButton("Mathieu+LC")
        self.mathieu_btn.clicked.connect(self.open_mathieu_lc)

        self.tracer_btn = QPushButton("Tracer")
        self.tracer_btn.clicked.connect(self.open_tracer)

        self.trace2d_btn = QtWidgets.QPushButton("Tracer 2D")
        self.trace2d_btn.clicked.connect(self.open_tracer2d_dialog)

        self.btn_laser = QtWidgets.QPushButton("Start Laser")
        self.btn_laser.clicked.connect(self.open_laser_window)

        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.connect_btn)
        btn_layout.addWidget(self.log_btn)
        btn_layout.addWidget(self.save_config_btn)
        btn_layout.addWidget(self.load_config_btn)
        btn_layout.addWidget(self.magnet_calc_btn)
        btn_layout.addWidget(self.keithley_gauge_btn)
        btn_layout.addWidget(self.keithley_plot_btn)
        btn_layout.addWidget(self.pressure_btn)
        btn_layout.addWidget(self.tracer_btn)
        btn_layout.addWidget(self.trace2d_btn)
        btn_layout.addWidget(self.mathieu_btn)
        btn_layout.addWidget(self.btn_laser)

        # *** HIER neu: Abstand und Status rechts in der gleichen Zeile ***
        btn_layout.addStretch()
        btn_layout.addWidget(self.status_label)

        main_layout.addLayout(btn_layout)

        # --------- Digital Controls -----------------------------------
        bool_group = QGroupBox("Digital Controls")
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
                font-weight: bold;
            }
        """)
        bool_layout = QHBoxLayout()
        bool_layout.setSpacing(15)

        left_column = QVBoxLayout()
        left_column.setSpacing(3)
        right_column = QVBoxLayout()
        right_column.setSpacing(3)

        self.controls: List[tuple[str, str]] = [
            ("do_attenuator", "Attenuator"),
            ("do_cup1", "Cup 1"),
            ("do_cup2", "Cup 2"),
            ("do_cup3", "Cup 3"),
            ("do_cup4", "Cup 4"),
            ("do_cup5", "Cup 5"),
            ("do_quick_cool", "Quick-Cool")
        ]

        # linke Spalte
        for ch_name, description in self.controls[:4]:
            hbox = QHBoxLayout()
            hbox.setSpacing(5)
            label = QLabel(description)
            checkbox = QCheckBox()
            checkbox.channel_name = ch_name
            checkbox.stateChanged.connect(self.on_checkbox_changed)
            hbox.addWidget(label)
            hbox.addWidget(checkbox)
            left_column.addLayout(hbox)

            self.checkbox_by_channel[ch_name] = checkbox
            self.adapter.register_channel(ch_name)

        # rechte Spalte
        for ch_name, description in self.controls[4:]:
            hbox = QHBoxLayout()
            hbox.setSpacing(5)
            label = QLabel(description)
            checkbox = QCheckBox()
            checkbox.channel_name = ch_name
            checkbox.stateChanged.connect(self.on_checkbox_changed)
            hbox.addWidget(label)
            hbox.addWidget(checkbox)
            right_column.addLayout(hbox)

            self.checkbox_by_channel[ch_name] = checkbox
            self.adapter.register_channel(ch_name)

        bool_layout.addLayout(left_column)
        bool_layout.addLayout(right_column)
        bool_group.setLayout(bool_layout)
        bool_group.setLayout(bool_layout)

        # --------- Sample Selection (Stepper) -------------------------
        sample_group = QGroupBox("Sample Selection")
        sample_group.setStyleSheet("""
            QGroupBox {
                background-color: #fff7d6;       /* andere Farbe als die anderen Gruppen */
                border: 1px solid gray;
                border-radius: 3px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
                font-weight: bold;
            }
        """)
        sample_layout = QFormLayout()
        sample_layout.setVerticalSpacing(4)
        sample_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Sample-Auswahl
        self.sample_combo = QComboBox()
        sample_layout.addRow("Sample:", self.sample_combo)


        # Button zum Laden der Sample-Wheel-Liste
        self.sample_list_btn = QPushButton("Choose Sample Wheel List")
        self.sample_list_btn.clicked.connect(self.on_choose_sample_wheel_list)
        sample_layout.addRow("Wheel list:", self.sample_list_btn)

        # Manueller Offset in Steps
        self.sample_offset_spin = QSpinBox()
        self.sample_offset_spin.setRange(-10000, 10000)
        self.sample_offset_spin.setValue(-200)
        self.sample_offset_spin.setSuffix(" steps")
        sample_layout.addRow("Offset:", self.sample_offset_spin)

        # Buttons Go / Home / Stop
        sample_btn_row = QHBoxLayout()
        self.sample_go_btn = QPushButton("Go")
        self.sample_home_btn = QPushButton("Home")
        self.sample_stop_btn = QPushButton("Stop")
        self.sample_stop_btn.setStyleSheet("background-color:#d9534f; color:white;")

        self.sample_go_btn.clicked.connect(self.on_sample_go_clicked)
        self.sample_home_btn.clicked.connect(self.on_sample_home_clicked)
        self.sample_stop_btn.clicked.connect(self.on_sample_stop_clicked)

        sample_btn_row.addWidget(self.sample_go_btn)
        sample_btn_row.addWidget(self.sample_home_btn)
        sample_btn_row.addWidget(self.sample_stop_btn)

        sample_layout.addRow(sample_btn_row)

        # Statuslabels
        self.sample_status_label = QLabel("Stepper: unknown")
        self.sample_status_label.setStyleSheet("color:#666;")
        self.sample_position_label = QLabel("Position: -")
        self.sample_position_label.setStyleSheet("color:#333;")

        sample_layout.addRow("Status:", self.sample_status_label)
        sample_layout.addRow("Actual:", self.sample_position_label)

        sample_group.setLayout(sample_layout)

        # Digitale Gruppe und Sample-Gruppe nebeneinander anordnen
        top_row_layout = QHBoxLayout()
        top_row_layout.addWidget(bool_group, stretch=2)
        top_row_layout.addWidget(sample_group, stretch=1)
        main_layout.addLayout(top_row_layout)


         # --------- Keithley small group --------------------------------
        self.keithley_group = QGroupBox("Keithley")
        self.keithley_group.setStyleSheet("""
            QGroupBox {
                background-color: #fff4e6;
                border: 1px solid gray;
                border-radius: 3px;
                margin-top: 6px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
                font-weight: bold;
            }
        """)

        # auch hier: flach halten
        self.keithley_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.keithley_group.setMaximumHeight(120)  # nach Geschmack anpassen

        keith_layout = QGridLayout()
        keith_layout.setContentsMargins(8, 4, 8, 4)
        keith_layout.setHorizontalSpacing(6)
        keith_layout.setVerticalSpacing(2)

        # Status rechts oben
        self.keithley_status_label = QLabel("Not connected")
        self.keithley_status_label.setStyleSheet("color:#a00; font-weight:bold;")
        keith_layout.addWidget(self.keithley_status_label, 0, 0, 1, 3,
                               alignment=Qt.AlignRight)

        row = 1
        self.keithley_current_label = QLabel("Current: --- nA")
        keith_layout.addWidget(self.keithley_current_label, row, 0, 1, 2)

        row += 1
        keith_layout.addWidget(QLabel("Averaging interval (s):"), row, 0)
        self.keithley_interval_spin = QDoubleSpinBox()
        self.keithley_interval_spin.setRange(0.1, 600.0)
        self.keithley_interval_spin.setDecimals(1)
        self.keithley_interval_spin.setSingleStep(0.1)
        self.keithley_interval_spin.setValue(self.keithley_avg_interval)
        self.keithley_interval_spin.valueChanged.connect(self.on_keithley_interval_changed)
        keith_layout.addWidget(self.keithley_interval_spin, row, 1)

        row += 1
        self.keithley_interval_label = QLabel(
            f"Interval avg ({self.keithley_avg_interval:.1f} s): --- ± --- nA"
        )
        keith_layout.addWidget(self.keithley_interval_label, row, 0, 1, 2)

        self.keithley_group.setLayout(keith_layout)

        # Keithley-Kanäle beim Adapter registrieren
        self.adapter.register_channel("keithley_connected")
        self.adapter.register_channel("keithley_current_nA")



        



        # Sample-Positionen aus Datei laden
        self.load_sample_positions()

        # Stepper-Status aus Backend empfangen
        self.adapter.register_channel("stepper_connected")
        self.adapter.register_channel("stepper_position_meas")

        # --------- Oven Temperature Control ---------------------------
        temp_group = QGroupBox("Oven Temperature Control")
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
                font-weight: bold;
            }
        """)
        temp_layout = QFormLayout()
        temp_layout.setVerticalSpacing(2)
        temp_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.current_control = self.create_slider_control(
            0, 2, 100, "A", default_step=0.01, decimals=2
        )
        self.current_control['set_channel'] = "oven_current_set"
        self.slider_controls_by_channel["oven_current_set"] = self.current_control
        self.adapter.register_channel("oven_current_set")

        self.current_control['slider'].valueChanged.connect(
            lambda val, ctl=self.current_control: self.on_opc_setpoint_slider_changed(
                "oven_current_set", ctl, val)
        )
        temp_layout.addRow("Oven Current [A]:", self.current_control['container'])

        self.temp_display = QLabel("--")
        self.temp_display.setAlignment(Qt.AlignLeft)
        self.register_measurement_label("oven_temp_meas", self.temp_display)
        temp_layout.addRow("Current Temperature [°C]:", self.temp_display)

        temp_group.setLayout(temp_layout)
        main_layout.addWidget(temp_group)

        # --------- Ion Source Controls --------------------------------
        source_group = QGroupBox("Ion Source Controls")
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
                font-weight: bold;
            }
        """)
        source_layout = QFormLayout()
        source_layout.setVerticalSpacing(1)
        source_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Sputter Voltage
        self.sputter_voltage_control = self.create_slider_control(0, 10000, 10, "V", default_step=10.0)
        self.sputter_voltage_control['set_channel'] = "sputter_voltage_set"
        self.slider_controls_by_channel["sputter_voltage_set"] = self.sputter_voltage_control
        self.adapter.register_channel("sputter_voltage_set")
        self.sputter_voltage_control['slider'].valueChanged.connect(
            lambda val, ctl=self.sputter_voltage_control:
                self.on_opc_setpoint_slider_changed("sputter_voltage_set", ctl, val)
        )
        source_layout.addRow("Sputter Voltage Control [V]:", self.sputter_voltage_control['container'])

        self.sputter_voltage_display = QLabel("--")
        self.register_measurement_label("sputter_voltage_meas", self.sputter_voltage_display)
        source_layout.addRow("Sputter Voltage Indicator [V]:", self.sputter_voltage_display)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        source_layout.addRow(separator)

        self.sputter_current_display = QLabel("--")
        self.register_measurement_label("sputter_current_meas", self.sputter_current_display)
        source_layout.addRow("Sputter Current Indicator [mA]:", self.sputter_current_display)

        self.ionizer_current_display = QLabel("--")
        self.register_measurement_label("ionizer_current_meas", self.ionizer_current_display)
        source_layout.addRow("Ionizer Current Indicator [A]:", self.ionizer_current_display)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        source_layout.addRow(separator)

        # Extraction / Einzellinse
        self.extraction_voltage_control = self.create_slider_control(0, 30000, 10, "V", default_step=10.0)
        self.extraction_voltage_control['set_channel'] = "extraction_voltage_set"
        self.slider_controls_by_channel["extraction_voltage_set"] = self.extraction_voltage_control
        self.adapter.register_channel("extraction_voltage_set")
        self.extraction_voltage_control['slider'].valueChanged.connect(
            lambda val, ctl=self.extraction_voltage_control:
                self.on_extraction_slider_changed(ctl, val)
        )
        source_layout.addRow("Extraction Voltage Control [V]:", self.extraction_voltage_control['container'])

        self.extraction_voltage_display = QLabel("--")
        self.register_measurement_label("extraction_voltage_meas", self.extraction_voltage_display)
        source_layout.addRow("Extraction Voltage Indicator [V]:", self.extraction_voltage_display)

        self.delta_display = QLabel("--")
        self.adapter.register_channel("delta_voltage")
        source_layout.addRow("Delta Voltage [V]:", self.delta_display)

        self.einzellinse_voltage_control = self.create_slider_control(0, 30000, 10, "V", default_step=10.0)
        self.einzellinse_voltage_control['set_channel'] = "einzellinse_voltage_set"
        self.slider_controls_by_channel["einzellinse_voltage_set"] = self.einzellinse_voltage_control
        self.adapter.register_channel("einzellinse_voltage_set")
        self.einzellinse_voltage_control['slider'].valueChanged.connect(
            lambda val, ctl=self.einzellinse_voltage_control:
                self.on_einzellinse_slider_changed(ctl, val)
        )
        source_layout.addRow("Einzellinse Voltage Control [V]:", self.einzellinse_voltage_control['container'])

        self.einzellinse_voltage_display = QLabel("--")
        self.register_measurement_label("einzellinse_voltage_meas", self.einzellinse_voltage_display)
        source_layout.addRow("Einzellinse Voltage Indicator [V]:", self.einzellinse_voltage_display)

        source_group.setLayout(source_layout)
        main_layout.addWidget(source_group)

        # --------- Ion Optics Controls --------------------------------
        optics_group = QGroupBox("Ion Optics Controls")
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
                font-weight: bold;
            }
        """)
        optics_layout = QFormLayout()
        optics_layout.setVerticalSpacing(1)
        optics_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Lens 2
        self.lens2_voltage_control = self.create_slider_control(0, 12500, 10, "V", default_step=10.0)
        self.lens2_voltage_control['set_channel'] = "lens2_voltage_set"
        self.slider_controls_by_channel["lens2_voltage_set"] = self.lens2_voltage_control
        self.adapter.register_channel("lens2_voltage_set")
        self.lens2_voltage_control['slider'].valueChanged.connect(
            lambda val, ctl=self.lens2_voltage_control:
                self.on_opc_setpoint_slider_changed("lens2_voltage_set", ctl, val)
        )
        optics_layout.addRow("Lens 2 Voltage Control [V]:", self.lens2_voltage_control['container'])

        self.lens2_voltage_display = QLabel("--")
        self.register_measurement_label("lens2_voltage_meas", self.lens2_voltage_display)
        optics_layout.addRow("Lens 2 Voltage Indicator [V]:", self.lens2_voltage_display)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # Ion Cooler
        self.ion_cooler_voltage_control = self.create_slider_control(0, 40000, 10, "V", default_step=10.0)
        self.ion_cooler_voltage_control['set_channel'] = "ion_cooler_voltage_set"
        self.slider_controls_by_channel["ion_cooler_voltage_set"] = self.ion_cooler_voltage_control
        self.adapter.register_channel("ion_cooler_voltage_set")
        self.ion_cooler_voltage_control['slider'].valueChanged.connect(
            lambda val, ctl=self.ion_cooler_voltage_control:
                self.on_opc_setpoint_slider_changed("ion_cooler_voltage_set", ctl, val)
        )
        optics_layout.addRow("Ion Cooler Voltage Control [V]:", self.ion_cooler_voltage_control['container'])

        self.ion_cooler_voltage_display = QLabel("--")
        self.register_measurement_label("ion_cooler_voltage_meas", self.ion_cooler_voltage_display)
        optics_layout.addRow("Ion Cooler Voltage Indicator [V]:", self.ion_cooler_voltage_display)

        # --- MQTT PSU/HV innerhalb Optics-Group ----------------------
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        self.mqtt_status_label = QLabel("MQTT: unknown")
        self.mqtt_status_label.setStyleSheet("color:#666")
        self.adapter.register_channel("mqtt_connected")
        optics_layout.addRow("MQTT Status:", self.mqtt_status_label)

        # Guidefield 1
        self.psu1_mqtt_control = self.create_slider_control(
            0, 30, 10, "V", default_step=0.1, decimals=1
        )
        self.psu1_mqtt_control['set_channel'] = "gf1_set"
        self.slider_controls_by_channel["gf1_set"] = self.psu1_mqtt_control
        self.adapter.register_channel("gf1_set")
        self.psu1_mqtt_control['slider'].valueChanged.connect(
            lambda val, ctl=self.psu1_mqtt_control:
                self.on_mqtt_setpoint_slider_changed("gf1_set", ctl, val)
        )
        self.psu1_mqtt_meas_v = QLabel("-- V")
        self.register_measurement_label("gf1_meas_v", self.psu1_mqtt_meas_v)
        optics_layout.addRow("Guidefield 1 Set [V]:", self.psu1_mqtt_control['container'])
        optics_layout.addRow("Guidefield 1 Meas [V]:", self.psu1_mqtt_meas_v)

        # Guidefield 2
        self.psu2_mqtt_control = self.create_slider_control(
            0, 75, 10, "V", default_step=0.1, decimals=1
        )
        self.psu2_mqtt_control['set_channel'] = "gf2_set"
        self.slider_controls_by_channel["gf2_set"] = self.psu2_mqtt_control
        self.adapter.register_channel("gf2_set")
        self.psu2_mqtt_control['slider'].valueChanged.connect(
            lambda val, ctl=self.psu2_mqtt_control:
                self.on_mqtt_setpoint_slider_changed("gf2_set", ctl, val)
        )
        self.psu2_mqtt_meas_v = QLabel("-- V")
        self.register_measurement_label("gf2_meas_v", self.psu2_mqtt_meas_v)
        optics_layout.addRow("Guidefield 2 Set [V]:", self.psu2_mqtt_control['container'])
        optics_layout.addRow("Guidefield 2 Meas [V]:", self.psu2_mqtt_meas_v)

        # Separator vor HV
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # HV1
        self.hv1_mqtt_control = self.create_slider_control(
            0, 6500, 10, "V", default_step=10.0, decimals=1
        )
        self.hv1_mqtt_control['set_channel'] = "hv1_set"
        self.slider_controls_by_channel["hv1_set"] = self.hv1_mqtt_control
        self.adapter.register_channel("hv1_set")
        self.hv1_mqtt_control['slider'].valueChanged.connect(
            lambda val, ctl=self.hv1_mqtt_control:
                self.on_mqtt_setpoint_slider_changed("hv1_set", ctl, val)
        )
        self.hv1_mqtt_meas_v = QLabel("-- V")
        self.hv1_mqtt_meas_i = QLabel("-- mA")
        self.register_measurement_label("hv1_meas_v", self.hv1_mqtt_meas_v)
        self.register_measurement_label("hv1_meas_i", self.hv1_mqtt_meas_i)
        optics_layout.addRow("HV1 Set [V]:", self.hv1_mqtt_control['container'])
        optics_layout.addRow("HV1 Meas [V]:", self.hv1_mqtt_meas_v)
        optics_layout.addRow("HV1 Meas [mA]:", self.hv1_mqtt_meas_i)

        # HV4
        self.hv4_mqtt_control = self.create_slider_control(
            0, 6500, 10, "V", default_step=10.0, decimals=1
        )
        self.hv4_mqtt_control['set_channel'] = "hv4_set"
        self.slider_controls_by_channel["hv4_set"] = self.hv4_mqtt_control
        self.adapter.register_channel("hv4_set")
        self.hv4_mqtt_control['slider'].valueChanged.connect(
            lambda val, ctl=self.hv4_mqtt_control:
                self.on_mqtt_setpoint_slider_changed("hv4_set", ctl, val)
        )
        self.hv4_mqtt_meas_v = QLabel("-- V")
        self.hv4_mqtt_meas_i = QLabel("-- mA")
        self.register_measurement_label("hv4_meas_v", self.hv4_mqtt_meas_v)
        self.register_measurement_label("hv4_meas_i", self.hv4_mqtt_meas_i)
        optics_layout.addRow("HV4 Set [V]:", self.hv4_mqtt_control['container'])
        optics_layout.addRow("HV4 Meas [V]:", self.hv4_mqtt_meas_v)
        optics_layout.addRow("HV4 Meas [mA]:", self.hv4_mqtt_meas_i)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # Quadrupole 1..3
        self.quad1_voltage_control = self.create_slider_control(0, 6000, 10, "V", default_step=10.0)
        self.quad1_voltage_control['set_channel'] = "quad1_voltage_set"
        self.slider_controls_by_channel["quad1_voltage_set"] = self.quad1_voltage_control
        self.adapter.register_channel("quad1_voltage_set")
        self.quad1_voltage_control['slider'].valueChanged.connect(
            lambda val, ctl=self.quad1_voltage_control:
                self.on_opc_setpoint_slider_changed("quad1_voltage_set", ctl, val)
        )
        optics_layout.addRow("Quadrupole 1 Voltage Control [V]:", self.quad1_voltage_control['container'])

        self.quad1_voltage_display = QLabel("--")
        self.register_measurement_label("quad1_voltage_meas", self.quad1_voltage_display)
        optics_layout.addRow("Quadrupole 1 Voltage Indicator [V]:", self.quad1_voltage_display)

        self.quad2_voltage_control = self.create_slider_control(0, 6000, 10, "V", default_step=10.0)
        self.quad2_voltage_control['set_channel'] = "quad2_voltage_set"
        self.slider_controls_by_channel["quad2_voltage_set"] = self.quad2_voltage_control
        self.adapter.register_channel("quad2_voltage_set")
        self.quad2_voltage_control['slider'].valueChanged.connect(
            lambda val, ctl=self.quad2_voltage_control:
                self.on_opc_setpoint_slider_changed("quad2_voltage_set", ctl, val)
        )
        optics_layout.addRow("Quadrupole 2 Voltage Control [V]:", self.quad2_voltage_control['container'])

        self.quad2_voltage_display = QLabel("--")
        self.register_measurement_label("quad2_voltage_meas", self.quad2_voltage_display)
        optics_layout.addRow("Quadrupole 2 Voltage Indicator [V]:", self.quad2_voltage_display)

        self.quad3_voltage_control = self.create_slider_control(0, 6000, 10, "V", default_step=10.0)
        self.quad3_voltage_control['set_channel'] = "quad3_voltage_set"
        self.slider_controls_by_channel["quad3_voltage_set"] = self.quad3_voltage_control
        self.adapter.register_channel("quad3_voltage_set")
        self.quad3_voltage_control['slider'].valueChanged.connect(
            lambda val, ctl=self.quad3_voltage_control:
                self.on_opc_setpoint_slider_changed("quad3_voltage_set", ctl, val)
        )
        optics_layout.addRow("Quadrupole 3 Voltage Control [V]:", self.quad3_voltage_control['container'])

        self.quad3_voltage_display = QLabel("--")
        self.register_measurement_label("quad3_voltage_meas", self.quad3_voltage_display)
        optics_layout.addRow("Quadrupole 3 Voltage Indicator [V]:", self.quad3_voltage_display)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # ESA
        self.esa_voltage_control = self.create_slider_control(0, 3000, 10, "V", default_step=10.0)
        self.esa_voltage_control['set_channel'] = "esa_voltage_set"
        self.slider_controls_by_channel["esa_voltage_set"] = self.esa_voltage_control
        self.adapter.register_channel("esa_voltage_set")
        self.esa_voltage_control['slider'].valueChanged.connect(
            lambda val, ctl=self.esa_voltage_control:
                self.on_opc_setpoint_slider_changed("esa_voltage_set", ctl, val)
        )
        optics_layout.addRow("ESA Voltage Control [V]:", self.esa_voltage_control['container'])

        self.esa_voltage_display = QLabel("--")
        self.register_measurement_label("esa_voltage_meas", self.esa_voltage_display)
        optics_layout.addRow("ESA Voltage Indicator [V]:", self.esa_voltage_display)

        self.esa_correction_control = self.create_slider_control(0, 1000, 10, "V", default_step=10.0)
        self.esa_correction_control['set_channel'] = "esa_correction_set"
        self.slider_controls_by_channel["esa_correction_set"] = self.esa_correction_control
        self.adapter.register_channel("esa_correction_set")
        self.esa_correction_control['slider'].valueChanged.connect(
            lambda val, ctl=self.esa_correction_control:
                self.on_opc_setpoint_slider_changed("esa_correction_set", ctl, val)
        )
        optics_layout.addRow("ESA Voltage Correction Control [V]:", self.esa_correction_control['container'])

        self.esa_correction_display = QLabel("--")
        self.register_measurement_label("esa_correction_meas", self.esa_correction_display)
        optics_layout.addRow("ESA Voltage Correction Indicator [V]:", self.esa_correction_display)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        optics_layout.addRow(separator)

        # Lens 4
        self.lens4_voltage_control = self.create_slider_control(0, 10000, 10, "V", default_step=10.0)
        self.lens4_voltage_control['set_channel'] = "lens4_voltage_set"
        self.slider_controls_by_channel["lens4_voltage_set"] = self.lens4_voltage_control
        self.adapter.register_channel("lens4_voltage_set")
        self.lens4_voltage_control['slider'].valueChanged.connect(
            lambda val, ctl=self.lens4_voltage_control:
                self.on_opc_setpoint_slider_changed("lens4_voltage_set", ctl, val)
        )
        optics_layout.addRow("Lens 4 Voltage Control [V]:", self.lens4_voltage_control['container'])

        self.lens4_voltage_display = QLabel("--")
        self.register_measurement_label("lens4_voltage_meas", self.lens4_voltage_display)
        optics_layout.addRow("Lens 4 Voltage Indicator [V]:", self.lens4_voltage_display)

        optics_group.setLayout(optics_layout)
        




        # --------- Magnet Controls ------------------------------------
        self.magnet_group = QGroupBox("Magnet")
        self.magnet_group.setStyleSheet("""
            QGroupBox {
                background-color: #e6f7ff;   /* neue Hintergrundfarbe */
                border: 1px solid gray;
                border-radius: 3px;
                margin-top: 6px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
                font-weight: bold;
            }
        """)

        # Wichtig: nicht in der Höhe wachsen lassen
        self.magnet_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.magnet_group.setMaximumHeight(120)  # ggf. anpassen

        magnet_layout = QGridLayout()
        magnet_layout.setContentsMargins(8, 4, 8, 4)
        magnet_layout.setHorizontalSpacing(6)
        magnet_layout.setVerticalSpacing(2)

        # Statuslabel oben rechts im GroupBox-Inhalt
        self.magnet_status_label = QLabel("Not connected")
        self.magnet_status_label.setStyleSheet("color:#a00; font-weight:bold;")
        magnet_layout.addWidget(self.magnet_status_label, 0, 0, 1, 5,
                                alignment=Qt.AlignRight)

        # Slider (0..120 A)
        self.magnet_current_control = self.create_slider_control(
            0, 120, 1000, "A", default_step=0.1, decimals=3
        )
        self.magnet_current_control['set_channel'] = "magnet_current_set"
        self.slider_controls_by_channel["magnet_current_set"] = self.magnet_current_control
        self.adapter.register_channel("magnet_current_set")

        self.magnet_current_control['slider'].valueChanged.connect(
            lambda val, ctl=self.magnet_current_control:
                self.on_magnet_slider_changed(ctl, val)
        )

        row = 1  # Zeile nach dem Statuslabel
        magnet_layout.addWidget(QLabel("Target Current [A]:"), row, 0)
        magnet_layout.addWidget(self.magnet_current_control['container'], row, 1, 1, 4)

        # Direct Inputs + Messwerte
        row += 1
        self.magnet_input1 = QDoubleSpinBox()
        self.magnet_input1.setRange(0.0, 120.0)
        self.magnet_input1.setDecimals(4)
        self.magnet_input1.setSuffix(" A")
        self.magnet_input1.setValue(0.0)

        self.magnet_send1 = QPushButton("Send 1")
        self.magnet_send1.clicked.connect(self.on_magnet_send1_clicked)

        self.magnet_meas_current = QLabel("--- A")
        self.magnet_meas_voltage = QLabel("--- V")
        self.magnet_meas_field = QLabel("--- kG")

        self.register_measurement_label("magnet_current_meas", self.magnet_meas_current)
        self.register_measurement_label("magnet_voltage_meas", self.magnet_meas_voltage)
        self.register_measurement_label("magnet_field_meas", self.magnet_meas_field)

        magnet_layout.addWidget(QLabel("Direct Input 1:"), row, 0)
        magnet_layout.addWidget(self.magnet_input1, row, 1)
        magnet_layout.addWidget(self.magnet_send1, row, 2)
        magnet_layout.addWidget(QLabel("Current:"), row, 3)
        magnet_layout.addWidget(self.magnet_meas_current, row, 4)

        row += 1
        self.magnet_input2 = QDoubleSpinBox()
        self.magnet_input2.setRange(0.0, 120.0)
        self.magnet_input2.setDecimals(4)
        self.magnet_input2.setSuffix(" A")
        self.magnet_input2.setValue(0.0)

        self.magnet_send2 = QPushButton("Send 2")
        self.magnet_send2.clicked.connect(self.on_magnet_send2_clicked)

        magnet_layout.addWidget(QLabel("Direct Input 2:"), row, 0)
        magnet_layout.addWidget(self.magnet_input2, row, 1)
        magnet_layout.addWidget(self.magnet_send2, row, 2)
        magnet_layout.addWidget(QLabel("Voltage:"), row, 3)
        magnet_layout.addWidget(self.magnet_meas_voltage, row, 4)

        row += 1
        magnet_layout.addWidget(QLabel("Magnetic Field:"), row, 3)
        magnet_layout.addWidget(self.magnet_meas_field, row, 4)

        # Magnet- / Gauss-Status vom Backend bekommen
        self.adapter.register_channel("magnet_connected")
        self.adapter.register_channel("gaussmeter_connected")

        self.magnet_group.setLayout(magnet_layout)
        self.update_magnet_status()



        # --------- Tracer Parameter Mapping ---------------------------
        # Alle analogen, regelbaren Parameter (ohne Digital, ohne DeltaVoltage)
        self.tracer_params = {
            "OvenCurrent": {
                "label": "Oven Current [A]",
                "read": lambda: self._get_slider_real_value(self.current_control),
                "set": lambda v: self.backend.set_opc_analog("oven_current_set", v),
                "min": 0.0,
                "max": 2.0,
            },
            "SputterVoltage": {
                "label": "Sputter Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.sputter_voltage_control),
                "set": lambda v: self.backend.set_opc_analog("sputter_voltage_set", v),
                "min": 0.0,
                "max": 10000.0,
            },
            "ExtractionVoltage": {
                "label": "Extraction Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.extraction_voltage_control),
                "set": lambda v: self.backend.set_extraction_voltage(v),
                "min": 0.0,
                "max": 30000.0,
            },
            "EinzellinseVoltage": {
                "label": "Einzellinse Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.einzellinse_voltage_control),
                "set": lambda v: self.backend.set_einzellinse_voltage(v),
                "min": 0.0,
                "max": 30000.0,
            },
            "Lens2Voltage": {
                "label": "Lens 2 Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.lens2_voltage_control),
                "set": lambda v: self.backend.set_opc_analog("lens2_voltage_set", v),
                "min": 0.0,
                "max": 12500.0,
            },
            "IonCoolerVoltage": {
                "label": "Ion Cooler Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.ion_cooler_voltage_control),
                "set": lambda v: self.backend.set_opc_analog("ion_cooler_voltage_set", v),
                "min": 0.0,
                "max": 40000.0,
            },
            "Quad1Voltage": {
                "label": "Quadrupole 1 Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.quad1_voltage_control),
                "set": lambda v: self.backend.set_opc_analog("quad1_voltage_set", v),
                "min": 0.0,
                "max": 6000.0,
            },
            "Quad2Voltage": {
                "label": "Quadrupole 2 Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.quad2_voltage_control),
                "set": lambda v: self.backend.set_opc_analog("quad2_voltage_set", v),
                "min": 0.0,
                "max": 6000.0,
            },
            "Quad3Voltage": {
                "label": "Quadrupole 3 Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.quad3_voltage_control),
                "set": lambda v: self.backend.set_opc_analog("quad3_voltage_set", v),
                "min": 0.0,
                "max": 6000.0,
            },
            "ESAVoltage": {
                "label": "ESA Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.esa_voltage_control),
                "set": lambda v: self.backend.set_opc_analog("esa_voltage_set", v),
                "min": 0.0,
                "max": 3000.0,
            },
            "ESACorrVoltage": {
                "label": "ESA Correction Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.esa_correction_control),
                "set": lambda v: self.backend.set_opc_analog("esa_correction_set", v),
                "min": 0.0,
                "max": 1000.0,
            },
            "Lens4Voltage": {
                "label": "Lens 4 Voltage [V]",
                "read": lambda: self._get_slider_real_value(self.lens4_voltage_control),
                "set": lambda v: self.backend.set_opc_analog("lens4_voltage_set", v),
                "min": 0.0,
                "max": 10000.0,
            },
            "Guidefield1": {
                "label": "Guidefield 1 [V]",
                "read": lambda: self._get_slider_real_value(self.psu1_mqtt_control),
                "set": lambda v: self.backend.set_mqtt_setpoint("gf1_set", v),
                "min": 0.0,
                "max": 30.0,
            },
            "Guidefield2": {
                "label": "Guidefield 2 [V]",
                "read": lambda: self._get_slider_real_value(self.psu2_mqtt_control),
                "set": lambda v: self.backend.set_mqtt_setpoint("gf2_set", v),
                "min": 0.0,
                "max": 75.0,
            },
            "HV1": {
                "label": "HV1 [V]",
                "read": lambda: self._get_slider_real_value(self.hv1_mqtt_control),
                "set": lambda v: self.backend.set_mqtt_setpoint("hv1_set", v),
                "min": 0.0,
                "max": 6500.0,
            },
            "HV4": {
                "label": "HV4 [V]",
                "read": lambda: self._get_slider_real_value(self.hv4_mqtt_control),
                "set": lambda v: self.backend.set_mqtt_setpoint("hv4_set", v),
                "min": 0.0,
                "max": 6500.0,
            },
            "MagnetCurrent": {
                "label": "Magnet Current [A]",
                "read": lambda: self._get_slider_real_value(self.magnet_current_control),
                "set": lambda v: self.backend.set_magnet_current(v),
                "min": 0.0,
                "max": 120.0,
            },
        }


        # --------- Magnet + Keithley in einer Zeile --------------------
        magnet_keith_row = QHBoxLayout()
        magnet_keith_row.addWidget(self.magnet_group, stretch=2)
        magnet_keith_row.addWidget(self.keithley_group, stretch=1)
        main_layout.addLayout(magnet_keith_row)

        # Ion Optics darunter, mit Stretch, damit sie den Restplatz bekommt
        main_layout.addWidget(optics_group, stretch=1)

        



        

    # ------------------------------------------------------------------
    # Hilfsfunktionen für UI-Bausteine
    # ------------------------------------------------------------------


    #pressure fenster methode
    def open_pressure_window(self):
        """Öffnet das Ion-Cooler/ESA-Pressure-Fenster als Popup."""
        if self.pressure_window is None:
            self.pressure_window = PressureWindow()
            # beim Schließen Objekt zerstören lassen und Referenz zurücksetzen
            self.pressure_window.setAttribute(QtCore.Qt.WA_DeleteOnClose)
            self.pressure_window.destroyed.connect(self._on_pressure_window_destroyed)
        self.pressure_window.show()
        self.pressure_window.raise_()
        self.pressure_window.activateWindow()

    def _on_pressure_window_destroyed(self, *args):
        self.pressure_window = None



    #laser fenster methode

    def open_laser_window(self):
        """
        Öffnet das Laser-Fenster als Popup.
        Die komplette Startup-Sequenz (Connect, Keyswitch, Faults, LBO-Warmup)
        wird einmalig ausgeführt. Wenn der Nutzer abbricht oder der Laser
        nicht erreichbar ist, wird kein Fenster offen gelassen.
        """
        # Falls das Fenster schon existiert, nur nach vorne holen
        if self.laser_window is not None:
            self.laser_window.show()
            self.laser_window.raise_()
            self.laser_window.activateWindow()
            return

        # Neues Laser-Fenster erzeugen
        win = LaserWindow(self)

        # Startup-Sequenz ausführen (Verbindung, Keyswitch, Faults, LBO)
        ok = win.run_startup_sequence()
        if not ok:
            # Start wurde abgebrochen oder Verbindung fehlgeschlagen
            # -> Laser-Verbindung schließen und Fenster entsorgen
            win.laser.close()
            win.deleteLater()
            return

        # Wenn alles OK ist: Fenster merken, Fault-Monitor starten und anzeigen
        self.laser_window = win
        self.laser_window.destroyed.connect(self._on_laser_destroyed)

        self.laser_window.start_status_timer()
        self.laser_window.show()
        self.laser_window.raise_()
        self.laser_window.activateWindow()


    def _on_laser_destroyed(self, *args):
        """Wird aufgerufen, wenn das Laser-Fenster endgültig geschlossen wurde."""
        self.laser_window = None


    #mathieu zeugs methode

    def open_mathieu_lc(self):
        """
        Öffnet das RFQ (Mathieu+LC)-Fenster.
        Es wird nur einmal erzeugt; beim Schließen wird self.rfq_window wieder auf None gesetzt.
        """
        if self.rfq_window is None:
            self.rfq_window = RFQUnifiedGUI(self)
            # Wenn das Fenster endgültig zerstört ist, Referenz löschen
            self.rfq_window.destroyed.connect(self._on_rfq_destroyed)
        self.rfq_window.show()
        self.rfq_window.raise_()
        self.rfq_window.activateWindow()

    def _on_rfq_destroyed(self, *args):
        self.rfq_window = None




    #keithley
    def open_keithley_gauge(self):
        if self.keithley_gauge_window is None:
            self.keithley_gauge_window = KeithleyGaugeWindow(self.adapter, self)
        self.keithley_gauge_window.show()
        self.keithley_gauge_window.raise_()
        self.keithley_gauge_window.activateWindow()

    def open_keithley_plot(self):
        if self.keithley_plot_window is None:
            self.keithley_plot_window = KeithleyPlotWindow(self)
        self.keithley_plot_window.show()
        self.keithley_plot_window.raise_()
        self.keithley_plot_window.activateWindow()


    def update_keithley_status(self):
        if not hasattr(self, "keithley_status_label"):
            return
        if self.keithley_connected:
            text = "Connected"
            style = "color:#0a0; font-weight:bold;"
        else:
            text = "Not connected"
            style = "color:#a00; font-weight:bold;"
        self.keithley_status_label.setText(text)
        self.keithley_status_label.setStyleSheet(style)

    def on_keithley_interval_changed(self, value: float):
        self.keithley_avg_interval = float(value)
        self.keithley_bucket_start = None
        self.keithley_bucket_values = []
        self.keithley_t0 = None
        self.keithley_interval_label.setText(
            f"Interval avg ({self.keithley_avg_interval:.1f} s): --- ± --- nA"
        )

    def _keithley_update_instant(self, current_nA: float):
        self.keithley_current_label.setText(f"Current: {current_nA:.2f} nA")

    def _keithley_update_aggregation(self, current_nA: float):
        interval = self.keithley_avg_interval
        if interval <= 0:
            return

        now = time.perf_counter()
        if self.keithley_bucket_start is None:
            self.keithley_bucket_start = now
            self.keithley_bucket_values = [current_nA]
            return

        self.keithley_bucket_values.append(current_nA)

        if now - self.keithley_bucket_start >= interval:
            values = self.keithley_bucket_values
            n = len(values)
            if n == 0:
                self.keithley_bucket_start = now
                self.keithley_bucket_values = []
                return

            mean = sum(values) / n
            if n > 1:
                var = sum((v - mean) ** 2 for v in values) / n
            else:
                var = 0.0
            sigma = math.sqrt(max(var, 0.0))

            if self.keithley_t0 is None:
                self.keithley_t0 = self.keithley_bucket_start
            t_point = (self.keithley_bucket_start + interval / 2.0) - self.keithley_t0

            self.keithley_interval_label.setText(
                f"Interval avg ({interval:.1f} s): {mean:.2f} ± {sigma:.2f} nA (n={n})"
            )

            if self.keithley_plot_window is not None:
                self.keithley_plot_window.add_point(t_point, mean, sigma)

            self.keithley_bucket_start = now
            self.keithley_bucket_values = [current_nA]

    

    #magnet calculator
    def open_magnet_calculator(self):
        if self.magnet_calc_dialog is None:
            self.magnet_calc_dialog = MagnetCalculatorDialog(self.backend, self)
        self.magnet_calc_dialog.show()
        self.magnet_calc_dialog.raise_()
        self.magnet_calc_dialog.activateWindow()



    def open_tracer(self):
        """Tracer-Popup öffnen (ein Exemplar)."""
        if self.tracer_dialog is None:
            self.tracer_dialog = TracerDialog(self)
            # Referenz zurücksetzen, wenn der Dialog zerstört wird
            self.tracer_dialog.destroyed.connect(
                lambda *_: setattr(self, "tracer_dialog", None)
            )
        self.tracer_dialog.show()
        self.tracer_dialog.raise_()
        self.tracer_dialog.activateWindow()


    def open_tracer2d_dialog(self):
        """Öffnet den 2D-Tracer-Dialog."""
        if self.tracer2d_dialog is None:
            self.tracer2d_dialog = Tracer2DDialog(self)
            # wenn der Dialog endgültig zerstört wird, Referenz löschen
            self.tracer2d_dialog.destroyed.connect(self._on_tracer2d_destroyed)
        self.tracer2d_dialog.show()
        self.tracer2d_dialog.raise_()
        self.tracer2d_dialog.activateWindow()

    def _on_tracer2d_destroyed(self, *args):
        self.tracer2d_dialog = None
    


    def load_sample_positions(self):
        """Sample-Positionen (Index -> Steps) aus Textdatei laden."""
        self.sample_positions.clear()
        self.sample_labels.clear()
        self.sample_index_order.clear()
        self.sample_materials.clear()
        self.sample_combo.clear()

        try:
            with open(self.sample_position_file, "r") as f:
                idx_counter = 1
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue

                    # Letztes Feld: Steps
                    try:
                        steps = int(parts[-1])
                    except ValueError:
                        continue

                    # Versuche, erstes Feld als Positionsindex zu interpretieren
                    try:
                        pos_idx = int(parts[0])
                        label = " ".join(parts[:-1])  # kompletter Text ohne Steps
                    except ValueError:
                        # Kein numerischer Index vorne -> intern durchnummerieren
                        pos_idx = idx_counter
                        idx_counter += 1
                        label = " ".join(parts[:-1])

                    if not label:
                        label = f"Pos {pos_idx}"

                    self.sample_positions[pos_idx] = steps
                    self.sample_labels[pos_idx] = label
                    self.sample_index_order.append(pos_idx)

            if self.sample_positions:
                self.sample_status_label.setText(
                    f"Stepper: loaded {len(self.sample_positions)} samples"
                )
                self.sample_status_label.setStyleSheet("color:#666;")
            else:
                self.sample_status_label.setText("Stepper: no positions found")
                self.sample_status_label.setStyleSheet("color:#a00;")
        except Exception as e:
            self.sample_status_label.setText(f"Stepper: error loading positions ({e})")
            self.sample_status_label.setStyleSheet("color:#a00;")

        # Combobox mit (eventuell später) Material neu aufbauen
        self.refresh_sample_combo_labels()



    def refresh_sample_combo_labels(self):
        """Combobox-Einträge aus Position-Labels + Materialien aktualisieren."""
        self.sample_combo.blockSignals(True)
        self.sample_combo.clear()
        self.sample_combo.addItem("Select sample", userData=None)

        for pos_idx in self.sample_index_order:
            base_label = self.sample_labels.get(pos_idx, f"Pos {pos_idx}")
            mat = self.sample_materials.get(pos_idx)
            if mat:
                display = f"{base_label} – {mat}"
            else:
                display = base_label
            self.sample_combo.addItem(display, userData=pos_idx)

        self.sample_combo.setCurrentIndex(0)
        self.sample_combo.blockSignals(False)



    def on_choose_sample_wheel_list(self):
        """Sample-Wheel-Liste auswählen und Material-Spalte einlesen."""
        base_dir = SAMPLE_WHEEL_DIR

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Sample Wheel List",
            base_dir,
            "Sample wheel lists (*.ods *.xlsx *.xls *.csv *.txt);;All files (*)"
        )
        if not path:
            return

        try:
            materials = self._parse_sample_wheel_list(path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error reading wheel list",
                f"Could not read sample wheel list:\n{e}"
            )
            return

        self.sample_wheel_list_path = path
        self.sample_materials = materials

        # Combobox-Labels aktualisieren (Position-Label + Material)
        self.refresh_sample_combo_labels()

        self.sample_status_label.setText(
            f"Stepper: wheel list loaded ({len(materials)} entries)"
        )
        self.sample_status_label.setStyleSheet("color:#333;")




    def _parse_sample_wheel_list(self, path: str) -> Dict[int, str]:
        """
        Liest eine Sample-Wheel-Liste (ODS/XLSX/XLS/CSV/TXT) ein und
        gibt ein Dict {position_index -> material_string} zurück.

        Erwartet eine Spalte 'position' und eine Spalte 'Material'
        (Groß-/Kleinschreibung egal).
        """
        _, ext = os.path.splitext(path)
        ext = ext.lower()

        try:
            import pandas as pd  # lazy import
        except ImportError as e:
            raise RuntimeError(
                "Reading sample wheel lists requires the 'pandas' package "
                "(and 'odfpy' for .ods). Please install via:\n"
                "  pip install pandas odfpy"
            ) from e

        # Datei einlesen
        try:
            if ext in (".ods", ".xlsx", ".xls"):
                if ext == ".ods":
                    df = pd.read_excel(path, engine="odf")
                else:
                    df = pd.read_excel(path)
            else:
                # CSV/TXT – Separator automatisch erkennen
                df = pd.read_csv(path, sep=None, engine="python")
        except Exception as e:
            raise RuntimeError(f"Error reading table file: {e}") from e

        if df.empty:
            raise RuntimeError("File is empty.")

        # Spaltennamen normalisieren
        col_map = {
            (str(c).strip().lower() if isinstance(c, str) else ""): c
            for c in df.columns
        }

        pos_col = None
        mat_col = None

        for key, orig in col_map.items():
            if "position" in key:
                pos_col = orig
            if "material" in key:
                mat_col = orig

        if pos_col is None:
            raise RuntimeError("No column named 'position' found.")
        if mat_col is None:
            raise RuntimeError("No column named 'Material' found.")

        materials: Dict[int, str] = {}

        for _, row in df.iterrows():
            pos_val = row[pos_col]
            mat_val = row[mat_col]

            if pd.isna(pos_val) or pd.isna(mat_val):
                continue

            # Position -> int
            try:
                pos_idx = int(pos_val)
            except Exception:
                s = str(pos_val).strip()
                if not s:
                    continue
                digits = "".join(ch for ch in s if ch.isdigit())
                if not digits:
                    continue
                pos_idx = int(digits)

            mat_str = str(mat_val).strip()
            if not mat_str:
                continue

            materials[pos_idx] = mat_str

        if not materials:
            raise RuntimeError("No (position, Material) entries found.")

        return materials



    def create_slider_control(self, min_val, max_val, multiplier, unit,
                              default_step=1.0, decimals=1):
        """Erzeugt Slider mit Step-Selector und Value-Label."""
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

        control: Dict[str, Any] = {
            'container': container,
            'slider': slider,
            'decrease_btn': decrease_btn,
            'increase_btn': increase_btn,
            'step_selector': step_selector,
            'value_label': value_label,
            'multiplier': multiplier,
            'decimals': decimals,
            'unit': unit,
        }

        slider.control = {
            'step_selector': step_selector,
            'multiplier': multiplier
        }

        def update_value(value: int):
            real_value = value / multiplier
            value_label.setText(f"{real_value:.{decimals}f} {unit}")

        control['update_value'] = update_value

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

        return control
    
    #get real slider werte
    def _get_slider_real_value(self, control: Dict[str, Any]) -> float:
        """Liest den aktuellen Realwert eines Slider-Controls (mit multiplier)."""
        slider: QSlider = control['slider']
        mult = control['multiplier']
        return float(slider.value()) / float(mult)

    def register_measurement_label(self, channel_name: str, label: QLabel):
        self.measurement_labels_by_channel[channel_name] = label
        self.adapter.register_channel(channel_name)



    #get keithley last 1s average
    def get_keithley_avg_last_1s(self) -> float | None:
        """Gibt den Mittelwert der letzten 1 s Keithley-Daten (nA) zurück."""
        if not self.keithley_trace_samples:
            return None
        now_t = time.perf_counter()
        cutoff = now_t - 1.0
        vals = [v for (t, v) in self.keithley_trace_samples if t >= cutoff]
        if not vals:
            return None
        return sum(vals) / len(vals)

    # ------------------------------------------------------------------
    # GUI-Event-Handler
    # ------------------------------------------------------------------

    def on_magnet_slider_changed(self, control: Dict[str, Any], value: int):
        real_value = float(value) / float(control['multiplier'])
        self.backend.set_magnet_current(real_value)

    def on_magnet_send1_clicked(self):
        value = float(self.magnet_input1.value())
        self.backend.set_magnet_current(value)

    def on_magnet_send2_clicked(self):
        value = float(self.magnet_input2.value())
        self.backend.set_magnet_current(value)


    def on_sample_go_clicked(self):
        """Sample aus Liste + Offset -> Stepper bewegen."""
        pos_idx = self.sample_combo.currentData()
        if not isinstance(pos_idx, int):
            self.sample_status_label.setText("Stepper: please select a valid sample")
            self.sample_status_label.setStyleSheet("color:#a00;")
            return

        base_pos = self.sample_positions.get(pos_idx)
        if base_pos is None:
            self.sample_status_label.setText("Stepper: no position for selected sample")
            self.sample_status_label.setStyleSheet("color:#a00;")
            return

        offset = self.sample_offset_spin.value()
        target = base_pos + offset

        label = self.sample_labels.get(pos_idx, f"Pos {pos_idx}")
        material = self.sample_materials.get(pos_idx)
        if material:
            sample_name = f"{label} ({material})"
        else:
            sample_name = label

        self.backend.move_sample_to_position(target)
        self.sample_status_label.setText(
            f"Stepper: moving to '{sample_name}' (pos {target})"
        )
        self.sample_status_label.setStyleSheet("color:#333;")

    def on_sample_stop_clicked(self):
        """Stepper-Bewegung stoppen."""
        self.backend.stop_stepper()
        self.sample_status_label.setText("Stepper: stop requested")
        self.sample_status_label.setStyleSheet("color:#d68b00;")

    def on_sample_home_clicked(self):
        """Stepper in Home-Position fahren."""
        self.backend.home_stepper()
        self.sample_status_label.setText("Stepper: home requested")
        self.sample_status_label.setStyleSheet("color:#333;")





    def on_checkbox_changed(self, state: int):
        checkbox: QCheckBox = self.sender()
        ch_name = getattr(checkbox, "channel_name", None)
        if not ch_name:
            return
        new_value = (state == Qt.Checked)
        self.backend.set_digital_output(ch_name, new_value)

    def on_opc_setpoint_slider_changed(self, channel_name: str, control: Dict[str, Any], value: int):
        real_value = float(value) / float(control['multiplier'])
        self.backend.set_opc_analog(channel_name, real_value)

    def on_extraction_slider_changed(self, control: Dict[str, Any], value: int):
        real_value = float(value) / float(control['multiplier'])
        self.backend.set_extraction_voltage(real_value)

    def on_einzellinse_slider_changed(self, control: Dict[str, Any], value: int):
        real_value = float(value) / float(control['multiplier'])
        self.backend.set_einzellinse_voltage(real_value)

    def on_mqtt_setpoint_slider_changed(self, channel_name: str, control: Dict[str, Any], value: int):
        real_value = float(value) / float(control['multiplier'])
        self.backend.set_mqtt_setpoint(channel_name, real_value)

    def force_opc_poll(self):
        self.backend.force_opc_poll()
        self.status_label.setText("Status: Forced OPC poll requested")

    def reconnect_opc(self):
        self.backend.request_opc_reconnect()
        self.status_label.setText("Status: OPC reconnect requested")

    def toggle_logging(self):
        if self.log_btn.isChecked():
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Select Log File", "", "Text Files (*.txt);;All Files (*)"
            )
            if not file_path:
                self.log_btn.setChecked(False)
                return
            try:
                self.backend.start_logging(file_path, interval=1.0)
                self.log_btn.setText("Stop Logging")
                self.status_label.setText(f"Status: Logging to {file_path}")
            except Exception as e:
                self.log_btn.setChecked(False)
                self.status_label.setText(f"Error starting logging: {e}")
        else:
            self.backend.stop_logging()
            self.log_btn.setText("Start Logging")
            self.status_label.setText("Status: Logging stopped")




    # ------------------------------------------------------------------
    # Config speichern / laden
    # ------------------------------------------------------------------

    def save_config(self):
        """Aktuelle GUI-Konfiguration in eine .txt-Datei schreiben."""
        # Sicherstellen, dass der Ordner existiert
        try:
            os.makedirs(self.config_base_dir, exist_ok=True)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Save Config Error",
                f"Could not create config directory:\n{self.config_base_dir}\n\n{e}"
            )
            return

        # Name vom User abfragen
        name, ok = QInputDialog.getText(
            self,
            "Save Config",
            "Config name (ohne .txt):",
        )
        if not ok or not name.strip():
            return

        # Windows-ungeeignete Zeichen rausfiltern
        safe_name = "".join(c for c in name.strip() if c not in r'\/:*?"<>|')
        if not safe_name:
            QtWidgets.QMessageBox.warning(
                self, "Save Config", "Ungültiger Dateiname."
            )
            return

        file_path = os.path.join(self.config_base_dir, safe_name + ".txt")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# Config saved {timestamp}\n")

                # ------------------ DIGITAL ----------------------
                f.write("[DIGITAL]\n")
                f.write(f"Attenuator={int(self.checkbox_by_channel['do_attenuator'].isChecked())}\n")
                f.write(f"Cup1={int(self.checkbox_by_channel['do_cup1'].isChecked())}\n")
                f.write(f"Cup2={int(self.checkbox_by_channel['do_cup2'].isChecked())}\n")
                f.write(f"Cup3={int(self.checkbox_by_channel['do_cup3'].isChecked())}\n")
                f.write(f"Cup4={int(self.checkbox_by_channel['do_cup4'].isChecked())}\n")
                f.write(f"Cup5={int(self.checkbox_by_channel['do_cup5'].isChecked())}\n")
                f.write(f"QuickCool={int(self.checkbox_by_channel['do_quick_cool'].isChecked())}\n")
                f.write("\n")

                # ------------------ ANALOG_OPC -------------------
                f.write("[ANALOG_OPC]\n")
                f.write(f"OvenCurrent={self._get_slider_real_value(self.current_control):.6f}\n")
                f.write(f"SputterVoltage={self._get_slider_real_value(self.sputter_voltage_control):.6f}\n")
                f.write(f"ExtractionVoltage={self._get_slider_real_value(self.extraction_voltage_control):.6f}\n")
                f.write(f"EinzellinseVoltage={self._get_slider_real_value(self.einzellinse_voltage_control):.6f}\n")
                f.write(f"Lens2Voltage={self._get_slider_real_value(self.lens2_voltage_control):.6f}\n")
                f.write(f"IonCoolerVoltage={self._get_slider_real_value(self.ion_cooler_voltage_control):.6f}\n")
                f.write(f"Quad1Voltage={self._get_slider_real_value(self.quad1_voltage_control):.6f}\n")
                f.write(f"Quad2Voltage={self._get_slider_real_value(self.quad2_voltage_control):.6f}\n")
                f.write(f"Quad3Voltage={self._get_slider_real_value(self.quad3_voltage_control):.6f}\n")
                f.write(f"ESAVoltage={self._get_slider_real_value(self.esa_voltage_control):.6f}\n")
                f.write(f"ESACorrVoltage={self._get_slider_real_value(self.esa_correction_control):.6f}\n")
                f.write(f"Lens4Voltage={self._get_slider_real_value(self.lens4_voltage_control):.6f}\n")

                # DeltaVoltage: wird nur als Information gespeichert (keine direkte Stellgröße)
                delta_text = self.delta_display.text().replace("V", "").strip()
                try:
                    delta_val = float(delta_text)
                except Exception:
                    delta_val = 0.0
                f.write(f"DeltaVoltage={delta_val:.6f}\n")
                f.write("\n")

                # ------------------ MQTT_SETPOINTS ---------------
                f.write("[MQTT_SETPOINTS]\n")
                f.write(f"Guidefield1={self._get_slider_real_value(self.psu1_mqtt_control):.6f}\n")
                f.write(f"Guidefield2={self._get_slider_real_value(self.psu2_mqtt_control):.6f}\n")
                f.write(f"HV1={self._get_slider_real_value(self.hv1_mqtt_control):.6f}\n")
                f.write(f"HV4={self._get_slider_real_value(self.hv4_mqtt_control):.6f}\n")
                f.write("\n")

                # ------------------ MAGNET ------------------------
                f.write("[MAGNET]\n")
                f.write(f"MagnetCurrent={self._get_slider_real_value(self.magnet_current_control):.6f}\n")


                # ---------------- RFQ (FG + LC) ----------------
                rfq_section = self._get_rfq_config_section()
                if rfq_section:
                    f.write("\n[RFQ]\n")
                    # Frequenz und Vpp
                    if "FG_Frequency" in rfq_section:
                        f.write(f"FG_Frequency={rfq_section['FG_Frequency']:.6f}\n")
                    if "FG_Vpp" in rfq_section:
                        f.write(f"FG_Vpp={rfq_section['FG_Vpp']:.6f}\n")
                    # LC C und L
                    if "C_pF" in rfq_section:
                        f.write(f"C_pF={rfq_section['C_pF']:.6f}\n")
                    if "L_uH" in rfq_section:
                        f.write(f"L_uH={rfq_section['L_uH']:.6f}\n")

                    # optional: Logging in der Main-GUI
                    self.append_status(
                        "RFQ config saved: "
                        f"f={rfq_section.get('FG_Frequency', float('nan')):.1f} Hz, "
                        f"Vpp={rfq_section.get('FG_Vpp', float('nan')):.3f} V, "
                        f"C={rfq_section.get('C_pF', float('nan')):.3f} pF, "
                        f"L={rfq_section.get('L_uH', float('nan')):.3f} µH"
                    )
                else:
                    self.append_status("RFQ window not open or no RFQ values – RFQ section not saved.")

            self.status_label.setText(f"Status: Config saved to {file_path}")
            self.status_label.setStyleSheet("color:#0a0")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Save Config Error",
                f"Error saving config file:\n{file_path}\n\n{e}"
            )



    def load_config(self):
        """Config-Datei auswählen und Rampenfahrt starten."""
        try:
            os.makedirs(self.config_base_dir, exist_ok=True)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Load Config Error",
                f"Could not create/access config directory:\n{self.config_base_dir}\n\n{e}"
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Config",
            self.config_base_dir,
            "Config Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return

        try:
            cfg = self._parse_config_file(file_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Load Config Error",
                f"Error parsing config file:\n{file_path}\n\n{e}"
            )
            return

        # 60s Ramp
        self._start_config_ramp(cfg, duration_secs=60)

    def _parse_config_file(self, path: str) -> Dict[str, Dict[str, float]]:
        """Einfache Parser für das Config-Format."""
        result: Dict[str, Dict[str, float]] = {
            "DIGITAL": {},
            "ANALOG_OPC": {},
            "MQTT_SETPOINTS": {},
            "MAGNET": {},
            "RFQ": {},
        }
        current_section = None

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    sec = line[1:-1].strip().upper()
                    if sec in result:
                        current_section = sec
                    else:
                        current_section = None
                    continue
                if "=" in line and current_section:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if current_section == "DIGITAL":
                        try:
                            result["DIGITAL"][key] = int(val)
                        except ValueError:
                            result["DIGITAL"][key] = 0
                    else:
                        try:
                            result[current_section][key] = float(val)
                        except ValueError:
                            # ignorieren
                            pass

        return result
    

    def _apply_digital_config(self, digital_cfg: Dict[str, int]):
        """DIGITAL-Teil der Config sofort setzen."""
        mapping = {
            "Attenuator": "do_attenuator",
            "Cup1": "do_cup1",
            "Cup2": "do_cup2",
            "Cup3": "do_cup3",
            "Cup4": "do_cup4",
            "Cup5": "do_cup5",
            "QuickCool": "do_quick_cool",
        }
        for key, ch_name in mapping.items():
            if key not in digital_cfg:
                continue
            target_bool = bool(int(digital_cfg[key]))
            cb = self.checkbox_by_channel.get(ch_name)
            if cb is not None:
                cb.blockSignals(True)
                cb.setChecked(target_bool)
                cb.blockSignals(False)
            # direkt ans Backend schicken
            self.backend.set_digital_output(ch_name, target_bool)

    # ---------------------------------------------------------
    # RFQ-Config-Helfer (Mathieu+LC-Fenster)
    # ---------------------------------------------------------
    def _get_rfq_config_section(self) -> dict:
        """
        Liest FG- und LC-Werte aus dem RFQ-Fenster und gibt sie
        als Dict zurück, das in die Config-Datei geschrieben wird.
        Wird das RFQ-Fenster nicht geöffnet sein, gibt es ein leeres Dict.
        """
        if self.rfq_window is None:
            return {}

        try:
            freq, vpp = self.rfq_window.get_fg_config_values()
            c_pf, l_uh = self.rfq_window.get_lc_config_values()
        except Exception:
            # falls das Fenster gerade nicht sauber initialisiert ist
            return {}

        section = {}
        if freq is not None and not math.isnan(freq):
            section["FG_Frequency"] = float(freq)
        if vpp is not None:
            section["FG_Vpp"] = float(vpp)
        if c_pf is not None and not math.isnan(c_pf):
            section["C_pF"] = float(c_pf)
        if l_uh is not None and not math.isnan(l_uh):
            section["L_uH"] = float(l_uh)
        return section

    def _apply_rfq_config_section(self, rfq_cfg: dict):
        """
        Wendet RFQ-Config sofort an (ohne Rampenfahrt):
        - FG-Frequenz + Vpp
        - LC C + L
        """
        if self.rfq_window is None:
            # optional: Hinweis, dass RFQ-Fenster nicht offen ist
            self.append_status("RFQ section present, but RFQ window is not open – skipping.")
            return

        # FG
        freq = rfq_cfg.get("FG_Frequency", None)
        vpp  = rfq_cfg.get("FG_Vpp", None)
        if freq is not None and vpp is not None:
            try:
                self.rfq_window.apply_fg_config_values(float(freq), float(vpp))
                self.append_status(
                    f"Applied RFQ FG: f={freq:.1f} Hz, Vpp={vpp:.3f} V"
                )
            except Exception as e:
                self.append_status(f"Error applying RFQ FG config: {e}")

        # LC
        c_pf = rfq_cfg.get("C_pF", None)
        l_uh = rfq_cfg.get("L_uH", None)
        if c_pf is not None and l_uh is not None:
            try:
                self.rfq_window.apply_lc_config_values(float(c_pf), float(l_uh))
                self.append_status(
                    f"Applied RFQ LC: C={c_pf:.3f} pF, L={l_uh:.3f} µH"
                )
            except Exception as e:
                self.append_status(f"Error applying RFQ LC config: {e}")


    def _start_config_ramp(self, cfg: Dict[str, Dict[str, float]], duration_secs: int = 60):
        """Erzeugt eine 60s-Rampe von aktuellen auf Zielwerte aus der Config."""

        # Laufende Rampe abbrechen
        if self.config_ramp_timer is not None:
            try:
                self.config_ramp_timer.stop()
                self.config_ramp_timer.deleteLater()
            except Exception:
                pass
            self.config_ramp_timer = None

        steps = max(1, int(duration_secs))
        self.config_ramp_total_secs = steps
        self.config_ramp_step_index = 0
        self.config_ramp_entries = []

        # ---------------- DIGITAL sofort setzen -----------------
        self._apply_digital_config(cfg.get("DIGITAL", {}))

        analog = cfg.get("ANALOG_OPC", {})
        mqtt = cfg.get("MQTT_SETPOINTS", {})
        magnet = cfg.get("MAGNET", {})
        rfq = cfg.get("RFQ", {})

        def add_entry(start: float, target: float, apply_func):
            entry = {
                "start": float(start),
                "target": float(target),
                "delta": (float(target) - float(start)) / float(steps),
                "apply": apply_func,
            }
            self.config_ramp_entries.append(entry)

        # --------------- ANALOG_OPC (OPC / Spezial) -------------
        # OvenCurrent (OPC analog)
        if "OvenCurrent" in analog:
            start = self._get_slider_real_value(self.current_control)
            target = analog["OvenCurrent"]
            add_entry(start, target,
                      lambda v: self.backend.set_opc_analog("oven_current_set", v))

        # SputterVoltage (OPC analog)
        if "SputterVoltage" in analog:
            start = self._get_slider_real_value(self.sputter_voltage_control)
            target = analog["SputterVoltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_opc_analog("sputter_voltage_set", v))

        # ExtractionVoltage (Spezialsetter)
        if "ExtractionVoltage" in analog:
            start = self._get_slider_real_value(self.extraction_voltage_control)
            target = analog["ExtractionVoltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_extraction_voltage(v))

        # EinzellinseVoltage (Spezialsetter)
        if "EinzellinseVoltage" in analog:
            start = self._get_slider_real_value(self.einzellinse_voltage_control)
            target = analog["EinzellinseVoltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_einzellinse_voltage(v))

        # Lens2Voltage
        if "Lens2Voltage" in analog:
            start = self._get_slider_real_value(self.lens2_voltage_control)
            target = analog["Lens2Voltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_opc_analog("lens2_voltage_set", v))

        # IonCoolerVoltage
        if "IonCoolerVoltage" in analog:
            start = self._get_slider_real_value(self.ion_cooler_voltage_control)
            target = analog["IonCoolerVoltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_opc_analog("ion_cooler_voltage_set", v))

        # Quad1..3
        if "Quad1Voltage" in analog:
            start = self._get_slider_real_value(self.quad1_voltage_control)
            target = analog["Quad1Voltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_opc_analog("quad1_voltage_set", v))

        if "Quad2Voltage" in analog:
            start = self._get_slider_real_value(self.quad2_voltage_control)
            target = analog["Quad2Voltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_opc_analog("quad2_voltage_set", v))

        if "Quad3Voltage" in analog:
            start = self._get_slider_real_value(self.quad3_voltage_control)
            target = analog["Quad3Voltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_opc_analog("quad3_voltage_set", v))

        # ESA + Korrektur
        if "ESAVoltage" in analog:
            start = self._get_slider_real_value(self.esa_voltage_control)
            target = analog["ESAVoltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_opc_analog("esa_voltage_set", v))

        if "ESACorrVoltage" in analog:
            start = self._get_slider_real_value(self.esa_correction_control)
            target = analog["ESACorrVoltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_opc_analog("esa_correction_set", v))

        # Lens4
        if "Lens4Voltage" in analog:
            start = self._get_slider_real_value(self.lens4_voltage_control)
            target = analog["Lens4Voltage"]
            add_entry(start, target,
                      lambda v: self.backend.set_opc_analog("lens4_voltage_set", v))

        # DeltaVoltage wird nur gespeichert, hat aber keinen direkten Setter -> hier ignoriert

        # --------------- MQTT_SETPOINTS -------------------------
        if "Guidefield1" in mqtt:
            start = self._get_slider_real_value(self.psu1_mqtt_control)
            target = mqtt["Guidefield1"]
            add_entry(start, target,
                      lambda v: self.backend.set_mqtt_setpoint("gf1_set", v))

        if "Guidefield2" in mqtt:
            start = self._get_slider_real_value(self.psu2_mqtt_control)
            target = mqtt["Guidefield2"]
            add_entry(start, target,
                      lambda v: self.backend.set_mqtt_setpoint("gf2_set", v))

        if "HV1" in mqtt:
            start = self._get_slider_real_value(self.hv1_mqtt_control)
            target = mqtt["HV1"]
            add_entry(start, target,
                      lambda v: self.backend.set_mqtt_setpoint("hv1_set", v))

        if "HV4" in mqtt:
            start = self._get_slider_real_value(self.hv4_mqtt_control)
            target = mqtt["HV4"]
            add_entry(start, target,
                      lambda v: self.backend.set_mqtt_setpoint("hv4_set", v))

        # --------------- MAGNET -------------------------------
        if "MagnetCurrent" in magnet:
            start = self._get_slider_real_value(self.magnet_current_control)
            target = magnet["MagnetCurrent"]
            add_entry(start, target,
                      lambda v: self.backend.set_magnet_current(v))
            
        # --------------- RFQ (FG + LC, ohne Rampe) ------------------
        if rfq:
            self._apply_rfq_config_section(rfq)

        if not self.config_ramp_entries:
            self.status_label.setText("Status: Config loaded (nothing to ramp).")
            self.status_label.setStyleSheet("color:#666")
            return

        # Timer starten
        self.config_ramp_timer = QTimer(self)
        self.config_ramp_timer.timeout.connect(self._config_ramp_step)
        self.config_ramp_timer.start(1000)

        self.status_label.setText(
            f"Status: Applying config... {self.config_ramp_total_secs} s remaining"
        )
        self.status_label.setStyleSheet("color:#d68b00")

    def _config_ramp_step(self):
        """Ein Sekundenschritt der Rampenfahrt."""
        if not self.config_ramp_entries or self.config_ramp_timer is None:
            return

        self.config_ramp_step_index += 1
        step = self.config_ramp_step_index
        steps = self.config_ramp_total_secs

        final_step = (step >= steps)

        for entry in self.config_ramp_entries:
            if final_step:
                value = entry["target"]
            else:
                value = entry["start"] + entry["delta"] * step
            entry["apply"](value)

        remaining = max(0, steps - step)
        if remaining > 0:
            self.status_label.setText(
                f"Status: Applying config... {remaining} s remaining"
            )
            self.status_label.setStyleSheet("color:#d68b00")
        else:
            # fertig
            try:
                self.config_ramp_timer.stop()
                self.config_ramp_timer.deleteLater()
            except Exception:
                pass
            self.config_ramp_timer = None
            self.status_label.setText("Status: Config ramp finished.")
            self.status_label.setStyleSheet("color:#0a0")



    #status label updates

    def update_status_labels(self):
        # MQTT-Status
        if self.mqtt_ok:
            self.mqtt_status_label.setText("MQTT: running")
            self.mqtt_status_label.setStyleSheet("color:#0a0")  # grün
        else:
            self.mqtt_status_label.setText("MQTT: stopped")
            self.mqtt_status_label.setStyleSheet("color:#a00")  # rot

        # Gesamtstatus
        if self.opc_ok and self.mqtt_ok:
            self.status_label.setText("Status: running")
            self.status_label.setStyleSheet("color:#0a0")
        elif self.opc_ok or self.mqtt_ok:
            self.status_label.setText("Status: partially running")
            self.status_label.setStyleSheet("color:#d68b00")  # orange
        else:
            self.status_label.setText("Status: stopped")
            self.status_label.setStyleSheet("color:#a00")





    # ------------------------------------------------------------------
    # Backend -> GUI: Update bei Channel-Änderungen
    # ------------------------------------------------------------------


    def update_magnet_status(self):
        """Aktualisiert den Text/Farbe des Statuslabels im Magnet-Block."""
        if not hasattr(self, "magnet_status_label"):
            return

        if self.magnet_ok and self.gauss_ok:
            text = "Connected"
            style = "color:#0a0; font-weight:bold;"
        elif self.magnet_ok or self.gauss_ok:
            text = "Partial"
            style = "color:#d68b00; font-weight:bold;"
        else:
            text = "Not connected"
            style = "color:#a00; font-weight:bold;"

        self.magnet_status_label.setText(text)
        self.magnet_status_label.setStyleSheet(style)



    def on_channel_updated(self, name: str, value: Any):
        # OPC-Status
        if name == "opc_connected":
            self.opc_ok = bool(value)
            self.update_status_labels()
            return

        # MQTT-Status
        if name == "mqtt_connected":
            self.mqtt_ok = bool(value)
            self.update_status_labels()
            return
        


        # Magnet-Status
        if name == "magnet_connected":
            self.magnet_ok = bool(value)
            self.update_magnet_status()
            return

        # Gaussmeter-Status
        if name == "gaussmeter_connected":
            self.gauss_ok = bool(value)
            self.update_magnet_status()
            return
        

        #keithley status
        if name == "keithley_connected":
            self.keithley_connected = bool(value)
            self.update_keithley_status()
            return

        if name == "keithley_current_nA":
            try:
                current_nA = float(value)
            except (TypeError, ValueError):
                current_nA = 0.0
            self._keithley_update_instant(current_nA)
            self._keithley_update_aggregation(current_nA)
            # Samples für Tracer sammeln (mit Zeitstempel)
            now_t = time.perf_counter()
            self.keithley_trace_samples.append((now_t, current_nA))
            cutoff = now_t - self.keithley_trace_max_age
            # Alte Samples wegwerfen
            while self.keithley_trace_samples and self.keithley_trace_samples[0][0] < cutoff:
                self.keithley_trace_samples.pop(0)

            return
        

    


        # Stepper-Verbindungsstatus
        if name == "stepper_connected":
            if value:
                self.sample_status_label.setText("Stepper: connected")
                self.sample_status_label.setStyleSheet("color:#0a0;")
            else:
                self.sample_status_label.setText("Stepper: disconnected")
                self.sample_status_label.setStyleSheet("color:#a00;")
            return

        # Stepper-Position
        if name == "stepper_position_meas":
            try:
                pos = int(value)
                self.sample_position_label.setText(f"Position: {pos} steps")
            except Exception:
                self.sample_position_label.setText("Position: -")
            return




        # Delta-Spannung
        if name == "delta_voltage":
            if isinstance(value, (int, float)):
                self.delta_display.setText(f"{float(value):.1f} V")
            else:
                self.delta_display.setText("--")
            return

        # Digitale Kanäle -> Checkboxen
        if name in self.checkbox_by_channel:
            cb = self.checkbox_by_channel[name]
            cb.blockSignals(True)
            cb.setChecked(bool(value))
            cb.blockSignals(False)
            return

        # OPC/MQTT Setpoints -> Slider
        if name in self.slider_controls_by_channel and isinstance(value, (int, float)):
            control = self.slider_controls_by_channel[name]
            slider: QSlider = control['slider']
            multiplier = control['multiplier']
            int_val = round(float(value) * multiplier)
            if not slider.isSliderDown():
                slider.blockSignals(True)
                slider.setValue(int_val)
                # Anzeige aktualisieren
                control['update_value'](int_val)
                slider.blockSignals(False)



        # Magnet-Strom-Messwert: beim ersten gültigen Wert den Slider auf diesen Wert ziehen
        if name == "magnet_current_meas":
            try:
                v = float(value)
            except (TypeError, ValueError):
                v = None

            if v is not None and not self.magnet_slider_initialized:
                ctl = self.slider_controls_by_channel.get("magnet_current_set")
                if ctl:
                    slider: QSlider = ctl['slider']
                    multiplier = ctl['multiplier']
                    int_val = round(v * multiplier)

                    # WICHTIG: Signale blocken, damit kein set_magnet_current() ausgelöst wird
                    slider.blockSignals(True)
                    slider.setValue(int_val)
                    ctl['update_value'](int_val)  # Label neben dem Slider aktualisieren
                    slider.blockSignals(False)

                # Nur ein einziges Mal beim Start synchronisieren
                self.magnet_slider_initialized = True





        # Messwerte -> Labels
        if name in self.measurement_labels_by_channel:
            label = self.measurement_labels_by_channel[name]
            cfg = CHANNELS.get(name)
            unit = cfg.unit if cfg else ""
            decimals = cfg.decimals if cfg else 1
            if value is None or (isinstance(value, float) and (value != value)):  # NaN
                label.setText("--")
            else:
                try:
                    v = float(value)
                    label.setText(f"{v:.{decimals}f} {unit}".strip())
                except Exception:
                    label.setText(str(value))

    # ------------------------------------------------------------------
    # MQTT-Stale-Anzeige
    # ------------------------------------------------------------------
    def refresh_mqtt_stale(self):
        now = time.time()

        def mark(label: QLabel, channel_names: List[str]):
            latest = 0.0
            for ch_name in channel_names:
                ch = self.backend.model.get(ch_name)
                if ch and ch.timestamp > latest:
                    latest = ch.timestamp
            if latest and (now - latest) < self.mqtt_staleThresholdSecs:
                label.setStyleSheet("color:#000")
            else:
                label.setStyleSheet("color:#888")

        mark(self.psu1_mqtt_meas_v, ["gf1_meas_v"])
        mark(self.psu2_mqtt_meas_v, ["gf2_meas_v"])
        mark(self.hv1_mqtt_meas_v, ["hv1_meas_v"])
        mark(self.hv1_mqtt_meas_i, ["hv1_meas_i"])
        mark(self.hv4_mqtt_meas_v, ["hv4_meas_v"])
        mark(self.hv4_mqtt_meas_i, ["hv4_meas_i"])

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        try:
            self.gui_timer.stop()
        except Exception:
            pass
        try:
            self.backend.stop()
        except Exception:
            pass
        event.accept()
