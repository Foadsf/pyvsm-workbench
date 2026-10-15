from collections import deque
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

class DigitalStorageOscilloscope(QWidget):
    """
    4-Channel Digital Storage Oscilloscope (DSO).
    Renders real-time analog and digital waveforms with dark CRT phosphor aesthetics,
    dot graticule grid, and multi-channel trace overlay.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.history_len = 240
        self.ch1_adc0 = deque([0.0] * self.history_len, maxlen=self.history_len)
        self.ch2_pb0 = deque([0.0] * self.history_len, maxlen=self.history_len)
        self.ch3_vload = deque([0.0] * self.history_len, maxlen=self.history_len)
        self.ch4_scl = deque([0.0] * self.history_len, maxlen=self.history_len)

    def push_samples(self, v_adc: float, v_pb0: float, v_load: float, v_scl: float):
        self.ch1_adc0.append(v_adc)
        self.ch2_pb0.append(v_pb0)
        self.ch3_vload.append(v_load)
        self.ch4_scl.append(v_scl)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # CRT Phosphor Dark Screen
        painter.fillRect(0, 0, w, h, QColor("#081410"))

        # Graticule Grid
        painter.setPen(QPen(QColor("#163828"), 1, Qt.DotLine))
        for x in range(0, w, 40):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h, 30):
            painter.drawLine(0, y, w, y)

        def draw_trace(buf: deque, color: str, y_offset: float, scale: float):
            if len(buf) < 2:
                return
            painter.setPen(QPen(QColor(color), 1.8))
            path = QPainterPath()
            dx = w / float(self.history_len - 1)
            for i, val in enumerate(buf):
                px = i * dx
                py = y_offset - (val / 5.0) * scale
                if i == 0:
                    path.moveTo(px, py)
                else:
                    path.lineTo(px, py)
            painter.drawPath(path)

        draw_trace(self.ch1_adc0, "#FFFF00", h * 0.42, h * 0.32)   # CH1 Yellow: ADC0
        draw_trace(self.ch3_vload, "#00FFFF", h * 0.42, h * 0.32)  # CH2 Cyan: RC Filtered V_LOAD
        draw_trace(self.ch2_pb0, "#FF44AA", h * 0.72, h * 0.20)    # CH3 Magenta: PB0 PWM
        draw_trace(self.ch4_scl, "#44FF44", h * 0.94, h * 0.16)    # CH4 Green: I2C SCL

        # Channel Legend Overlay
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.setPen(QColor("#FFFF00"))
        painter.drawText(8, 14, "CH1: V(adc0)")
        painter.setPen(QColor("#00FFFF"))
        painter.drawText(105, 14, "CH2: V(v_load)")
        painter.setPen(QColor("#FF44AA"))
        painter.drawText(220, 14, "CH3: V(pb0)")
        painter.setPen(QColor("#44FF44"))
        painter.drawText(320, 14, "CH4: I2C SCL")
