from typing import Callable
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from .base import MovableSchematicNode
from ..pins import ProteusPinSquare

class InteractiveButtonItem(MovableSchematicNode):
    """
    Proteus Pushbutton (B2 / PB_2).
    Clicking toggles between open (pulled up to 5V) and closed (grounded to 0V).
    """

    def __init__(self, name: str, on_toggle: Callable[[bool], None]):
        super().__init__()
        self.name = name
        self.on_toggle = on_toggle
        self.pressed = False
        self.pins["OUT"] = ProteusPinSquare("OUT", "pb2", parent=self)
        self.pins["OUT"].voltage = 5.0
        self.pins["OUT"].setPos(130, 35)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 155, 85)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#333333"), 1.5))
        painter.setBrush(QBrush(QColor("#EAE8D8")))
        painter.drawRoundedRect(0, 0, 130, 62, 4, 4)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111"))
        painter.drawText(4, -5, f"{self.name} (Click Toggle)")

        # Contacts
        painter.setPen(QPen(QColor("#222"), 2))
        painter.drawLine(15, 35, 45, 35)
        painter.drawLine(85, 35, 130, 35)
        painter.drawEllipse(QPointF(48, 35), 3, 3)
        painter.drawEllipse(QPointF(82, 35), 3, 3)

        # Contact plunger
        bar_y = 35 if self.pressed else 22
        painter.setPen(QPen(QColor("#CC0000" if self.pressed else "#222"), 2.5))
        painter.drawLine(45, bar_y, 85, bar_y)
        painter.drawRect(58, bar_y - 7, 14, 7)

    def toggle(self, state: bool = None):
        self.pressed = (not self.pressed) if state is None else state
        self.pins["OUT"].voltage = 0.0 if self.pressed else 5.0
        self.on_toggle(self.pressed)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle()
            event.accept()
            return
        super().mousePressEvent(event)

