from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from .base import MovableSchematicNode
from ..pins import ProteusPinSquare

class SevenSegmentDisplayItem(MovableSchematicNode):
    """
    Proteus 4-Digit Red 7-Segment LED Display.
    Renders live 4-digit BCD counter in vibrant 7-segment style.
    """

    def __init__(self, title: str = "LED Display (BCD)"):
        super().__init__()
        self.title = title
        self.value_str = "0000"
        self.pins["BUS"] = ProteusPinSquare("BUS", "pb0", parent=self)
        self.pins["BUS"].setPos(0, 35)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 190, 95)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#444"), 2))
        painter.setBrush(QBrush(QColor("#D8D8D0")))
        painter.drawRect(0, 0, 170, 66)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111"))
        painter.drawText(4, -5, self.title)

        # LED cavity
        painter.setBrush(QBrush(QColor("#140404")))
        painter.drawRect(12, 10, 146, 46)

        # 7-Segment text
        painter.setFont(QFont("Consolas", 24, QFont.Bold))
        painter.setPen(QColor("#FF1818"))
        painter.drawText(QRectF(12, 10, 146, 46), Qt.AlignCenter, self.value_str)
