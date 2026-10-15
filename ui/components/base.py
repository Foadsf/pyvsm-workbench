from typing import Dict
from PySide6.QtWidgets import QGraphicsItem
from ..pins import ProteusPinSquare

class MovableSchematicNode(QGraphicsItem):
    """
    Base class for schematic symbols.
    Maintains an internal pin dictionary and automatically notifies attached
    wires to recompute their Manhattan paths whenever the component is moved.
    """

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.pins: Dict[str, ProteusPinSquare] = {}

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for pin in self.pins.values():
                for w in pin.connected_wires:
                    w.update_orthogonal_path()
        return super().itemChange(change, value)
