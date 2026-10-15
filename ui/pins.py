from typing import List, Optional
from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem

class ProteusPinSquare(QGraphicsItem):
    """
    Interactive pin terminal supporting click-to-wire Manhattan routing
    and Proteus red/blue/green live voltage state rendering.
    """

    def __init__(
        self,
        pin_name: str,
        canonical_net: str,
        is_analog: bool = False,
        parent: Optional[QGraphicsItem] = None,
    ):
        super().__init__(parent)
        self.pin_name = pin_name
        self.canonical_net = canonical_net
        self.is_analog = is_analog
        self.voltage: float = 0.0
        self.connected_wires: List["SchematicWireItem"] = []
        self.setAcceptHoverEvents(True)
        self.hovered = False

    def boundingRect(self) -> QRectF:
        return QRectF(-6, -6, 12, 12)

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter: QPainter, option, widget=None):
        pen_color = QColor("#FFFF00") if self.hovered else QColor("#111111")
        pen_width = 1.5 if self.hovered else 0.8
        painter.setPen(QPen(pen_color, pen_width))

        if self.is_analog:
            painter.setBrush(QBrush(QColor("#00CC44")))  # Analog Green
        elif self.voltage >= 2.5:
            painter.setBrush(QBrush(QColor("#EE1111")))  # Logic HIGH Red
        elif self.voltage <= 1.5:
            painter.setBrush(QBrush(QColor("#1144EE")))  # Logic LOW Blue
        else:
            painter.setBrush(QBrush(QColor("#888888")))  # Hi-Z Float Grey

        painter.drawRect(-4, -4, 8, 8)
