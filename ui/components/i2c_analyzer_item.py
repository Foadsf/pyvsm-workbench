from typing import Callable, List, Optional
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from .base import MovableSchematicNode
from ..pins import ProteusPinSquare

class I2CProtocolAnalyserItem(MovableSchematicNode):
    """
    Proteus I2C PROTOCOL ANALYSER Instrument.
    Monitors SCL and SDA bus transitions and decodes frames into START (S),
    address, R/W bit, ACK/NAK (A/N), data payload bytes, and STOP (P).
    """

    def __init__(self, log_packet_cb: Optional[Callable[[str], None]] = None):
        super().__init__()
        self.log_packet_cb = log_packet_cb or (lambda msg: None)
        self.pins["SCL"] = ProteusPinSquare("SCL", "scl", parent=self)
        self.pins["SCL"].setPos(0, 25)
        self.pins["SDA"] = ProteusPinSquare("SDA", "sda", parent=self)
        self.pins["SDA"].setPos(0, 50)

        self._prev_scl = 1
        self._prev_sda = 1
        self._in_frame = False
        self._bits: List[int] = []
        self._frame_tokens: List[str] = []
        self.last_summary: str = "IDLE (Waiting for START)"

    def sample_bus(self, scl: int, sda: int, sim_t: float):
        self.pins["SCL"].voltage = 5.0 if scl else 0.0
        self.pins["SDA"].voltage = 5.0 if sda else 0.0

        # START Condition: SDA 1 -> 0 while SCL == 1
        if self._prev_scl == 1 and scl == 1 and self._prev_sda == 1 and sda == 0:
            self._in_frame = True
            self._bits.clear()
            self._frame_tokens = ["[S]"]

        # STOP Condition: SDA 0 -> 1 while SCL == 1
        elif self._prev_scl == 1 and scl == 1 and self._prev_sda == 0 and sda == 1:
            if self._in_frame:
                self._frame_tokens.append("[P]")
                summary = " ".join(self._frame_tokens)
                self.last_summary = summary
                self.log_packet_cb(f"[I2C T={sim_t:5.2f}s] {summary}")
                self._in_frame = False

        # Sample SDA on Rising Edge of SCL
        elif self._in_frame and self._prev_scl == 0 and scl == 1:
            self._bits.append(sda)
            if len(self._bits) == 9:
                byte_val = 0
                for b in self._bits[:8]:
                    byte_val = (byte_val << 1) | b
                ack_bit = self._bits[8]
                ack_str = "A" if ack_bit == 0 else "N"
                self._frame_tokens.append(f"0x{byte_val:02X}({ack_str})")
                self._bits.clear()

        self._prev_scl = scl
        self._prev_sda = sda

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 215, 100)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#333333"), 2))
        painter.setBrush(QBrush(QColor("#E4E2D0")))
        painter.drawRect(0, 0, 195, 72)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111"))
        painter.drawText(4, -5, "I2C PROTOCOL ANALYSER")

        painter.setFont(QFont("Consolas", 7))
        painter.drawText(8, 29, "SCL")
        painter.drawText(8, 54, "SDA")

        # Badge Box
        painter.setPen(QPen(QColor("#113366"), 1.5))
        painter.setBrush(QBrush(QColor("#F4F8FF")))
        painter.drawRect(38, 12, 146, 48)

        painter.setFont(QFont("Arial", 14, QFont.Bold))
        painter.setPen(QColor("#002266"))
        painter.drawText(QRectF(38, 14, 146, 24), Qt.AlignCenter, "I2C")

        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QColor("#005500"))
        painter.drawText(QRectF(40, 38, 142, 20), Qt.AlignCenter, self.last_summary[:22])
