from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

class VirtualTerminalWidget(QWidget):
    """
    Canonical Proteus Virtual Terminal (UART Serial Console).
    Displays real-time incoming serial frames from MCU TXD and transmits keystrokes/commands to RXD.
    """

    tx_key_pressed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet(
            "background-color: #081008; color: #33FF55; "
            "font-family: Consolas, monospace; font-size: 11px; border: 2px inset #333;"
        )
        layout.addWidget(self.console)

        input_row = QHBoxLayout()
        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("Send serial byte/command to MCU RXD (Press Enter)...")
        self.input_line.returnPressed.connect(self._send_line)

        btn_send = QPushButton("Send TX")
        btn_send.clicked.connect(self._send_line)

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self.console.clear)

        input_row.addWidget(self.input_line)
        input_row.addWidget(btn_send)
        input_row.addWidget(btn_clear)
        layout.addLayout(input_row)

        self._buffer = ""

    def append_serial_byte(self, byte_val: int):
        ch = chr(byte_val) if 32 <= byte_val <= 126 or byte_val in (10, 13) else "."
        self._buffer += ch
        if "\n" in self._buffer or len(self._buffer) > 80:
            cursor = self.console.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.insertText(self._buffer.replace("\r", ""))
            self.console.setTextCursor(cursor)
            self.console.ensureCursorVisible()
            self._buffer = ""

    def _send_line(self):
        txt = self.input_line.text()
        if txt:
            self.tx_key_pressed.emit(txt)
            self.input_line.clear()
