from typing import Optional
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem
from .pins import ProteusPinSquare

class SchematicWireItem(QGraphicsPathItem):
    """
    Orthogonal (Manhattan) routed wire linking two ProteusPinSquare instances.
    Automatically updates geometry when components move and colors itself by voltage.
    """

    def __init__(self, pin_start: ProteusPinSquare, pin_end: Optional[ProteusPinSquare] = None):
        super().__init__()
        self.pin_start = pin_start
        self.pin_end = pin_end
        self.temp_end_pos: QPointF = pin_start.scenePos()
        self.voltage: float = 0.0
        self.setZValue(-10)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        self.pin_start.connected_wires.append(self)
        if self.pin_end:
            self.pin_end.connected_wires.append(self)
        self.update_orthogonal_path()

    def update_orthogonal_path(self):
        p1 = self.pin_start.scenePos()
        p2 = self.pin_end.scenePos() if self.pin_end else self.temp_end_pos

        # Snap mid-segment to 10px grid for clean Manhattan Z/L routing
        mid_x = round(((p1.x() + p2.x()) / 2.0) / 10.0) * 10.0
        path = QPainterPath(p1)
        path.lineTo(mid_x, p1.y())
        path.lineTo(mid_x, p2.y())
        path.lineTo(p2)
        self.setPath(path)

    def paint(self, painter: QPainter, option, widget=None):
        if self.isSelected():
            color = QColor("#FF00FF")
            width = 2.5
        elif self.voltage >= 2.5:
            color = QColor("#CC1111")  # Live HIGH wire
            width = 1.8
        elif self.voltage <= 0.5:
            color = QColor("#1144AA")  # Live LOW wire
            width = 1.6
        else:
            color = QColor("#007722")  # Analog intermediate wire
            width = 1.8

        painter.setPen(QPen(color, width))
        painter.drawPath(self.path())
