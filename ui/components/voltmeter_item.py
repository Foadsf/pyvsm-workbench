from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from .base import MovableSchematicNode
from ..pins import ProteusPinSquare

class VirtualVoltmeterItem(MovableSchematicNode):
    """
    Proteus Round DC Voltmeter Instrument.
    Features classic circular housing, phosphor digital readout display, and V+ input pin.
    """

    def __init__(self, label: str = "DC Volts"):
        super().__init__()
        self.label = label
        self.voltage = 0.0
        self.pins["V+"] = ProteusPinSquare("V+", "v_load", is_analog=True, parent=self)
        self.pins["V+"].setPos(0, 55)

    def boundingRect(self) -> QRectF:
        return QRectF(-15, -20, 135, 135)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111"))
        painter.drawText(4, -5, self.label)

        # Round meter bezel
        painter.setPen(QPen(QColor("#6E1E14"), 3.5))
        painter.setBrush(QBrush(QColor("#E6E2CE")))
        painter.drawEllipse(5, 5, 100, 100)

        # Digital display bezel
        painter.setPen(QPen(QColor("#00AA22"), 1.5))
        painter.setBrush(QBrush(QColor("#062006")))
        painter.drawRect(20, 32, 70, 26)

        # Readout
        painter.setFont(QFont("Consolas", 11, QFont.Bold))
        painter.setPen(QColor("#22FF55"))
        sign = "+" if self.voltage >= 0 else ""
        painter.drawText(QRectF(20, 32, 70, 26), Qt.AlignCenter, f"{sign}{self.voltage:4.2f}")

        # Unit
        font_unit = QFont("Georgia", 10)
        font_unit.setItalic(True)
        painter.setFont(font_unit)
        painter.setPen(QColor("#5A1810"))
        painter.drawText(QRectF(5, 64, 100, 22), Qt.AlignCenter, "Volts")
