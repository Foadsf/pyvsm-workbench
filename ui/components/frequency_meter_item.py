from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from .base import MovableSchematicNode
from ..pins import ProteusPinSquare

class FrequencyMeterItem(MovableSchematicNode):
    """
    Proteus 8-Digit Red LED FREQUENCY METER Instrument.
    Measures and displays the live frequency in Hz of signal connected to its CLK pin.
    """

    def __init__(self):
        super().__init__()
        self.freq_hz: float = 0.0
        self.pins["CLK"] = ProteusPinSquare("CLK", "pb0", parent=self)
        self.pins["CLK"].setPos(0, 32)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 220, 85)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#444444"), 2))
        painter.setBrush(QBrush(QColor("#DCDAD0")))
        painter.drawRect(0, 0, 200, 56)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#222222"))
        painter.drawText(4, -5, "FREQUENCY METER")

        painter.setFont(QFont("Consolas", 7))
        painter.drawText(8, 36, "CLK")

        # 8-Digit Red LED Bezel
        painter.setPen(QPen(QColor("#222222"), 1))
        painter.setBrush(QBrush(QColor("#1A0404")))
        painter.drawRect(34, 10, 156, 36)

        painter.setFont(QFont("Consolas", 16, QFont.Bold))
        painter.setPen(QColor("#FF2222"))
        painter.drawText(QRectF(34, 10, 156, 36), Qt.AlignCenter, f"{int(self.freq_hz):08d}")
