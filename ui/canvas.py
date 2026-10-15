from typing import Optional
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView
from .pins import ProteusPinSquare
from .wires import SchematicWireItem

class InteractiveSchematicCanvas(QGraphicsView):
    """
    Proteus ISIS interactive schematic canvas.
    Supports point-and-click Manhattan orthogonal wiring between component pins,
    wire selection and deletion, ivory/dot grid background, and zoom/pan.
    """

    topology_changed = Signal()

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QBrush(QColor("#F4F2E6")))  # Proteus signature background
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.grid_step = 20
        self.active_wire: Optional[SchematicWireItem] = None

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor("#DEDAC4"), 0.7))
        left = int(rect.left()) - (int(rect.left()) % self.grid_step)
        top = int(rect.top()) - (int(rect.top()) % self.grid_step)
        for x in range(left, int(rect.right()), self.grid_step):
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, int(rect.bottom()), self.grid_step):
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            clicked_item = self.itemAt(event.position().toPoint())
            if isinstance(clicked_item, ProteusPinSquare):
                if self.active_wire is None:
                    # Start orthogonal wire from this pin
                    self.active_wire = SchematicWireItem(clicked_item)
                    self.scene().addItem(self.active_wire)
                elif clicked_item != self.active_wire.pin_start:
                    # Complete orthogonal wire on target pin
                    self.active_wire.pin_end = clicked_item
                    clicked_item.connected_wires.append(self.active_wire)
                    self.active_wire.update_orthogonal_path()
                    self.active_wire = None
                    self.topology_changed.emit()
                event.accept()
                return
            elif self.active_wire is not None:
                # Cancel in-progress wire on empty canvas click
                if self.active_wire in self.active_wire.pin_start.connected_wires:
                    self.active_wire.pin_start.connected_wires.remove(self.active_wire)
                self.scene().removeItem(self.active_wire)
                self.active_wire = None
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_wire is not None:
            self.active_wire.temp_end_pos = self.mapToScene(event.position().toPoint())
            self.active_wire.update_orthogonal_path()
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            deleted = False
            selected = list(self.scene().selectedItems())

            # 1. Remove any selected wires
            for item in selected:
                if isinstance(item, SchematicWireItem):
                    self._remove_wire(item)
                    deleted = True

            # 2. Remove any selected schematic components and their attached wires
            for item in selected:
                if hasattr(item, "pins") and isinstance(item.pins, dict):
                    for pin in list(item.pins.values()):
                        for wire in list(pin.connected_wires):
                            self._remove_wire(wire)
                    if item.scene() is not None:
                        self.scene().removeItem(item)
                    deleted = True

            if deleted:
                self.topology_changed.emit()
                event.accept()
                return
        super().keyPressEvent(event)

    def _remove_wire(self, wire: SchematicWireItem):
        if wire.pin_start and wire in wire.pin_start.connected_wires:
            wire.pin_start.connected_wires.remove(wire)
        if wire.pin_end and wire in wire.pin_end.connected_wires:
            wire.pin_end.connected_wires.remove(wire)
        if wire.scene() is not None:
            self.scene().removeItem(wire)


    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)
