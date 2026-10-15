from typing import Any, Dict
from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from .base import MovableSchematicNode
from ..pins import ProteusPinSquare

class CustomKiCadSymbolItem(MovableSchematicNode):
    """
    Dynamically rendered schematic component imported from a KiCad (.kicad_sym) symbol library.
    Generates input/output pins dynamically and links into the active SPICE netlist.
    """

    def __init__(self, sym_data: Dict[str, Any]):
        super().__init__()
        self.ref = sym_data.get("reference", "U_K")
        self.val = sym_data.get("value", "CUSTOM")
        self.w = 120
        self.h = 80
        for idx, p in enumerate(sym_data.get("pins", [])):
            name = p["name"]
            pin_sq = ProteusPinSquare(name, f"net_{name.lower()}", is_analog=True, parent=self)
            side_x = 0 if p["x"] < 0 else self.w
            pin_sq.setPos(side_x, 22 + (idx % 3) * 20)
            self.pins[name] = pin_sq

    def boundingRect(self) -> QRectF:
        return QRectF(-15, -20, self.w + 30, self.h + 30)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#800000"), 2))
        painter.setBrush(QBrush(QColor("#FDFCE8")))
        painter.drawRect(0, 0, self.w, self.h)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#000080"))
        painter.drawText(4, -5, f"{self.ref} ({self.val})")

        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor("#222"))
        for idx, name in enumerate(self.pins.keys()):
            painter.drawText(10, 26 + (idx % 3) * 20, name)
