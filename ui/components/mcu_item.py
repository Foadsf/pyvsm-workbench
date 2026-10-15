from typing import Dict, List, Tuple
from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from .base import MovableSchematicNode
from ..pins import ProteusPinSquare

class SchematicMCUItem(MovableSchematicNode):
    """
    Configurable Microcontroller schematic package (PIC18F452, ATmega328P, STM32F103).
    Displays analog ADC inputs, digital I/O, UART, LCD control bus, and I2C lines.
    """

    def __init__(self, ref: str = "U1", model: str = "PIC18F452"):
        super().__init__()
        self.ref = ref
        self.model = model
        self.w = 200
        self.h = 260

        left = [
            ("ADC0", "adc0", 50, True),
            ("PB2", "pb2", 110, False),
        ]
        right = [
            ("PD2_RS", "lcd_rs", 35, False),
            ("PD3_E", "lcd_e", 55, False),
            ("PD4_D4", "lcd_d4", 75, False),
            ("PD5_D5", "lcd_d5", 95, False),
            ("PD6_D6", "lcd_d6", 115, False),
            ("PD7_D7", "lcd_d7", 135, False),
            ("PB0", "pb0", 170, False),
            ("SCL", "scl", 205, False),
            ("SDA", "sda", 225, False),
            ("PD1_TXD", "txd", 245, False),
        ]
        for name, net, y, analog in left:
            p = ProteusPinSquare(name, net, is_analog=analog, parent=self)
            p.setPos(0, y)
            self.pins[name] = p
        for name, net, y, analog in right:
            p = ProteusPinSquare(name, net, is_analog=analog, parent=self)
            p.setPos(self.w, y)
            self.pins[name] = p

    def boundingRect(self) -> QRectF:
        return QRectF(-15, -25, self.w + 30, self.h + 35)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#222288"), 2))
        painter.setBrush(QBrush(QColor("#E6E4D2")))  # Proteus IC beige
        painter.drawRect(0, 0, self.w, self.h)

        # Title Label
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.setPen(QColor("#000080"))
        painter.drawText(4, -6, f"{self.ref} ({self.model})")

        # Left Pin Labels
        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor("#111111"))
        if "PIC" in self.model.upper():
            painter.drawText(10, 54, "RA0/AN0")
            painter.drawText(10, 114, "RB0/INT0")
        else:
            painter.drawText(10, 54, "PC0/ADC0")
            painter.drawText(10, 114, "PB2/INT0")

        # Right Pin Labels
        labels: List[Tuple[str, int]] = [
            ("RD2 (LCD_RS)", 39),
            ("RD3 (LCD_E)", 59),
            ("RD4 (LCD_D4)", 79),
            ("RD5 (LCD_D5)", 99),
            ("RD6 (LCD_D6)", 119),
            ("RD7 (LCD_D7)", 139),
            ("RB1/CCP1 (PWM)", 174),
            ("RC3/SCK/SCL", 209),
            ("RC4/SDI/SDA", 229),
            ("RC6/TX/CK", 249),
        ]
        for txt, y in labels:
            painter.drawText(self.w - 102, y, txt)
