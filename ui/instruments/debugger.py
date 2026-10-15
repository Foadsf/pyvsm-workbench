from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
try:
    from ...core.mcu.multi_mcu import MultiMCUBackend
except (ImportError, ValueError):
    from core.mcu.multi_mcu import MultiMCUBackend

class SourceDebuggerWidget(QWidget):
    """
    Replicates Proteus 'CPU Source Code - U1' and 'CPU Variables - U1'.
    Provides interactive breakpoint management, single-step execution highlighting,
    disassembly listing, C source code mapping, and live SFR/variable inspection.
    """

    step_into_requested = Signal()
    toggle_bp_requested = Signal(int)

    def __init__(self, mcu: MultiMCUBackend, parent=None):
        super().__init__(parent)
        self.mcu = mcu
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Toolbar controls
        ctrl_row = QHBoxLayout()
        btn_step = QPushButton("Step Into (F11)")
        btn_step.clicked.connect(self.step_into_requested.emit)

        self.bp_combo = QComboBox()
        for insn in self.mcu.listing:
            self.bp_combo.addItem(f"0x{insn.address:04X}: {insn.mnemonic}", insn.address)

        btn_bp = QPushButton("🔴 Toggle Breakpoint")
        btn_bp.clicked.connect(self._on_bp_clicked)

        ctrl_row.addWidget(btn_step)
        ctrl_row.addWidget(self.bp_combo)
        ctrl_row.addWidget(btn_bp)
        layout.addLayout(ctrl_row)

        # Disassembly + C Source Table
        self.src_table = QTableWidget(len(self.mcu.listing), 4)
        self.src_table.setHorizontalHeaderLabels(["BP/PC", "Addr", "Opcode / ASM", "C Source Code"])
        self.src_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.src_table.verticalHeader().setVisible(False)
        self.src_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.src_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.src_table.setStyleSheet("font-family: Consolas; font-size: 11px; background-color: #FFFFF4;")
        layout.addWidget(self.src_table)

        # CPU Variables Table
        lbl_vars = QLabel("CPU Variables & Special Function Registers:")
        lbl_vars.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_vars)

        self.var_table = QTableWidget(6, 3)
        self.var_table.setHorizontalHeaderLabels(["Name", "Address", "Value"])
        self.var_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.var_table.verticalHeader().setVisible(False)
        self.var_table.setMaximumHeight(155)
        self.var_table.setStyleSheet("font-family: Consolas; font-size: 11px;")
        layout.addWidget(self.var_table)

        self.refresh_debugger()

    def _on_bp_clicked(self):
        addr = self.bp_combo.currentData()
        if addr is not None:
            self.toggle_bp_requested.emit(int(addr))

    def refresh_debugger(self):
        cur_addr = self.mcu.current_instruction().address
        for row, insn in enumerate(self.mcu.listing):
            is_pc = insn.address == cur_addr
            has_bp = insn.address in self.mcu.breakpoints
            marker = ("🔴" if has_bp else "") + ("➡" if is_pc else "")

            items = [
                QTableWidgetItem(marker),
                QTableWidgetItem(f"{insn.address:04X}"),
                QTableWidgetItem(f"{insn.opcode_hex}  {insn.mnemonic}"),
                QTableWidgetItem(insn.c_source),
            ]
            bg = QColor("#CFE8FF") if is_pc else (QColor("#FFD6D6") if has_bp else QColor("#FFFFF4"))
            for col, it in enumerate(items):
                it.setBackground(QBrush(bg))
                if col == 3:
                    it.setForeground(QBrush(QColor("#007700")))
                self.src_table.setItem(row, col, it)

        for row, (name, addr, val) in enumerate(self.mcu.get_cpu_variables()):
            self.var_table.setItem(row, 0, QTableWidgetItem(name))
            self.var_table.setItem(row, 1, QTableWidgetItem(addr))
            self.var_table.setItem(row, 2, QTableWidgetItem(val))
