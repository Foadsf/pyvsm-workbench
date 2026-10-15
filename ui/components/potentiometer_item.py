from typing import Callable
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from .base import MovableSchematicNode
from ..pins import ProteusPinSquare

class RotaryPotentiometerItem(MovableSchematicNode):
    """
    Proteus Interactive Potentiometer (POT-HG 10k).
    Supports mouse clicks on schematic +/- buttons and wheel scrolling to alter
    wiper position and notify the SPICE engine dynamically.
    """

    def __init__(self, on_change: Callable[[float], None]):
        super().__init__()
        self.on_change = on_change
        self.ratio = 0.50
        self.pins["WIPER"] = ProteusPinSquare("WIPER", "adc0", is_analog=True, parent=self)
        self.pins["WIPER"].setPos(110, 55)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 135, 130)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#333333"), 1.5))
        painter.setBrush(QBrush(QColor("#EAE8D8")))
        painter.drawRoundedRect(0, 0, 110, 105, 4, 4)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#000080"))
        painter.drawText(4, -5, "RV1 (POT-HG 10k)")

        # Resistor body
        painter.setPen(QPen(QColor("#601010"), 2))
        painter.setBrush(QBrush(QColor("#D8C8B8")))
        painter.drawRect(36, 18, 20, 68)

        # Wiper arrow
        wy = 86 - self.ratio * 68
        painter.setPen(QPen(QColor("#CC0000"), 2))
        painter.drawLine(56, int(wy), 110, 55)

        # Interactive +/- buttons
        painter.setPen(QPen(QColor("#444444"), 1))
        painter.setBrush(QBrush(QColor("#D0D0C0")))
        painter.drawRect(8, 24, 20, 20)
        painter.drawRect(8, 60, 20, 20)
        painter.setFont(QFont("Consolas", 11, QFont.Bold))
        painter.setPen(QColor("#111"))
        painter.drawText(QRectF(8, 24, 20, 20), Qt.AlignCenter, "+")
        painter.drawText(QRectF(8, 60, 20, 20), Qt.AlignCenter, "-")

        # Readout text
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.setPen(QColor("#800000"))
        painter.drawText(
            QRectF(0, 88, 110, 16),
            Qt.AlignCenter,
            f"{int(self.ratio * 100)}% ({self.ratio * 5.0:4.2f}V)",
        )

    def mousePressEvent(self, event):
        pos = event.pos()
        if QRectF(8, 24, 20, 20).contains(pos):
            self.set_ratio(self.ratio + 0.05)
            event.accept()
            return
        if QRectF(8, 60, 20, 20).contains(pos):
            self.set_ratio(self.ratio - 0.05)
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        delta = 0.05 if event.delta() > 0 else -0.05
        self.set_ratio(self.ratio + delta)
        event.accept()

    def set_ratio(self, r: float):
        self.ratio = max(0.0, min(1.0, r))
        self.pins["WIPER"].voltage = self.ratio * 5.0
        self.on_change(self.ratio)
        self.update()
