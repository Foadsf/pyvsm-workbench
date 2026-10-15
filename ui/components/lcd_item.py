from typing import Dict
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from .base import MovableSchematicNode
from ..pins import ProteusPinSquare

class HD44780LCDItem(MovableSchematicNode):
    """
    16x2 Alphanumeric LCD (LM016L / Milford 2x16) Peripheral Model.
    Decodes RS, E, and D4-D7 pin transitions via hardware state machine,
    maintains an 80-byte DDRAM buffer, and renders the classic backlit dot-matrix LCD panel.
    """

    def __init__(self, title: str = "LCD1 (LM016L)"):
        super().__init__()
        self.title = title
        self.ddram = [0x20] * 128
        self.ddram_addr = 0
        self.four_bit = False
        self.disp_on = True
        self._hi_latched = False
        self._hi_nib = 0
        self._prev_e = 0

        pin_defs = [
            ("RS", "lcd_rs"),
            ("E", "lcd_e"),
            ("D4", "lcd_d4"),
            ("D5", "lcd_d5"),
            ("D6", "lcd_d6"),
            ("D7", "lcd_d7"),
        ]
        for idx, (name, net) in enumerate(pin_defs):
            p = ProteusPinSquare(name, net, parent=self)
            p.setPos(0, 20 + idx * 16)
            self.pins[name] = p

    def process_bus(self, rs: int, e: int, nib: int):
        self.pins["RS"].voltage = 5.0 if rs else 0.0
        self.pins["E"].voltage = 5.0 if e else 0.0
        for i, k in enumerate(["D4", "D5", "D6", "D7"]):
            self.pins[k].voltage = 5.0 if ((nib >> i) & 1) else 0.0

        if self._prev_e == 1 and e == 0:
            if not self.four_bit:
                if nib == 0x02:
                    self.four_bit = True
                    self._hi_latched = False
            else:
                if not self._hi_latched:
                    self._hi_nib = nib & 0x0F
                    self._hi_latched = True
                else:
                    byte_val = (self._hi_nib << 4) | (nib & 0x0F)
                    self._hi_latched = False
                    self._exec(rs, byte_val)
        self._prev_e = e

    def _exec(self, rs: int, val: int):
        if rs == 0:
            if val == 0x01:
                self.ddram = [0x20] * 128
                self.ddram_addr = 0
            elif val == 0x02:
                self.ddram_addr = 0
            elif (val & 0x80) == 0x80:
                self.ddram_addr = val & 0x7F
        else:
            if 0 <= self.ddram_addr < 128:
                self.ddram[self.ddram_addr] = val
                self.ddram_addr = (self.ddram_addr + 1) & 0x7F

    def get_row(self, r: int) -> str:
        base = 0x00 if r == 0 else 0x40
        return "".join(
            chr(self.ddram[base + i]) if 32 <= self.ddram[base + i] <= 126 else " "
            for i in range(16)
        )

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 305, 145)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#7A1C1C"), 2))
        painter.setBrush(QBrush(QColor("#E8E6D5")))
        painter.drawRect(0, 0, 285, 115)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111"))
        painter.drawText(4, -5, self.title)

        # Backlit Green-Yellow matrix (#8EB82E)
        painter.setPen(QPen(QColor("#3A4A14"), 2))
        painter.setBrush(QBrush(QColor("#8EB82E")))
        painter.drawRect(36, 16, 238, 76)

        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QColor("#222"))
        for i, k in enumerate(["RS", "E", "D4", "D5", "D6", "D7"]):
            painter.drawText(8, 24 + i * 16, k)

        if self.disp_on:
            painter.setFont(QFont("Consolas", 13, QFont.Bold))
            painter.setPen(QColor("#102204"))
            painter.drawText(QRectF(44, 22, 224, 30), Qt.AlignLeft | Qt.AlignVCenter, self.get_row(0))
            painter.drawText(QRectF(44, 54, 224, 30), Qt.AlignLeft | Qt.AlignVCenter, self.get_row(1))
