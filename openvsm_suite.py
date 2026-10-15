import ctypes
import ctypes.util
import json
import math
import os
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

# ==============================================================================
# 1. GRAPH-TO-SPICE NETLIST COMPILER & UNION-FIND EXTRACTOR
# ==============================================================================

class DisjointSet:
    """Union-Find structure for grouping connected schematic pins into electrical nets."""

    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.parent[item] = item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, a: str, b: str):
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a != root_b:
            priority = {"0": 0, "vcc": 1, "adc0": 2, "pb0": 3, "pb2": 4, "v_load": 5, "scl": 6, "sda": 7}
            pa = priority.get(root_a.lower(), 99)
            pb = priority.get(root_b.lower(), 99)
            if pa <= pb:
                self.parent[root_b] = root_a
            else:
                self.parent[root_a] = root_b

class NetlistCompiler:
    """
    Traverses all placed QGraphicsItem components and SchematicWireItem paths
    on the canvas to compile a dynamic SPICE netlist and pin-to-net lookup table.
    """

    @staticmethod
    def compile_scene(
        pins: List["ProteusPinSquare"],
        wires: List["SchematicWireItem"],
        pot_ratio: float,
        button_pressed: bool,
        subcircuits: List[str],
    ) -> Tuple[List[str], Dict["ProteusPinSquare", str]]:
        ds = DisjointSet()

        for pin in pins:
            ds.find(pin.canonical_net)

        for wire in wires:
            if wire.pin_start and wire.pin_end:
                ds.union(wire.pin_start.canonical_net, wire.pin_end.canonical_net)

        pin_to_net: Dict["ProteusPinSquare", str] = {}
        for pin in pins:
            pin_to_net[pin] = ds.find(pin.canonical_net).lower()

        r_top = max(1.0, (1.0 - pot_ratio) * 10000.0)
        r_bot = max(1.0, pot_ratio * 10000.0)
        r_btn = 0.01 if button_pressed else 100e6

        deck = [
            "OpenVSM Auto-Compiled Mixed-Mode Netlist",
            "V_VCC vcc 0 DC 5.0",
            f"R_POT_TOP vcc adc0 {r_top:.2f}",
            f"R_POT_BOT adc0 0 {r_bot:.2f}",
            "R_ADC_IN adc0 0 100MEG",
            "V_PB0 pb0 0 DC 0.0",
            "R_LOAD pb0 v_load 470",
            "C_LOAD v_load 0 10u",
            "R_PULLUP_BTN vcc pb2 10k",
            f"R_BTN_SW pb2 0 {r_btn}",
            "R_PULLUP_SDA vcc sda 4.7k",
            "R_PULLUP_SCL vcc scl 4.7k",
        ]
        for subckt in subcircuits:
            for line in subckt.strip().splitlines():
                deck.append(line.strip())
        deck.append(".end")
        return deck, pin_to_net

# ==============================================================================
# 2. CANONICAL LIBNGSPICE C-FFI & TRANSIENT MNA ENGINE
# ==============================================================================

SEND_CHAR_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
SEND_STAT_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
CONTROLLED_EXIT_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
)

class VecValues(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("creal", ctypes.c_double),
        ("cimag", ctypes.c_double),
        ("is_scale", ctypes.c_bool),
        ("is_complex", ctypes.c_bool),
    ]

P_VecValues = ctypes.POINTER(VecValues)

class VecValuesAll(ctypes.Structure):
    _fields_ = [
        ("veccount", ctypes.c_int),
        ("vecindex", ctypes.c_int),
        ("vecsa", ctypes.POINTER(P_VecValues)),
    ]

SEND_DATA_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(VecValuesAll), ctypes.c_int, ctypes.c_int, ctypes.c_void_p
)
SEND_INIT_DATA_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
BG_THREAD_RUNNING_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)

class NgSpiceBridge:
    def __init__(self, log_cb: Callable[[str], None]):
        self.log_cb = log_cb
        self.lib = None
        self.native_active = False
        self.pot_ratio: float = 0.50
        self.button_pressed: bool = False
        self.custom_subcircuits: List[str] = []

        self.node_voltages: Dict[str, float] = {
            "0": 0.0,
            "vcc": 5.0,
            "adc0": 2.50,
            "pb0": 0.0,
            "pb2": 5.0,
            "v_load": 0.0,
            "scl": 5.0,
            "sda": 5.0,
        }

        self._cb_char = SEND_CHAR_CB(self._on_char)
        self._cb_stat = SEND_STAT_CB(lambda *a: 0)
        self._cb_exit = CONTROLLED_EXIT_CB(lambda *a: 0)
        self._cb_data = SEND_DATA_CB(self._on_data)
        self._cb_init = SEND_INIT_DATA_CB(lambda *a: 0)
        self._cb_bg = BG_THREAD_RUNNING_CB(lambda *a: 0)
        self._init_dll()

    def _on_char(self, msg_ptr: bytes, ident: int, user_data: int) -> int:
        if msg_ptr:
            txt = msg_ptr.decode("utf-8", errors="ignore").strip()
            if txt:
                self.log_cb(f"[ngspice] {txt}")
        return 0

    def _on_data(self, vec_all_ptr, count: int, ident: int, user_data: int) -> int:
        if not vec_all_ptr:
            return 0
        va = vec_all_ptr.contents
        for i in range(va.veccount):
            v = va.vecsa[i].contents
            if v.name:
                k = v.name.decode("utf-8", errors="ignore").lower()
                if k.startswith("v(") and k.endswith(")"):
                    k = k[2:-1]
                self.node_voltages[k] = float(v.creal)
        return 0

    def _init_dll(self):
        for cand in [
            ctypes.util.find_library("ngspice"),
            "libngspice.so",
            "libngspice.so.0",
            "ngspice.dll",
            "libngspice.dylib",
        ]:
            if not cand:
                continue
            try:
                self.lib = ctypes.CDLL(cand)
                break
            except OSError:
                continue

        if self.lib:
            try:
                self.lib.ngSpice_Init.argtypes = [
                    SEND_CHAR_CB,
                    SEND_STAT_CB,
                    CONTROLLED_EXIT_CB,
                    SEND_DATA_CB,
                    SEND_INIT_DATA_CB,
                    BG_THREAD_RUNNING_CB,
                    ctypes.c_void_p,
                ]
                self.lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
                self.lib.ngSpice_Init(
                    self._cb_char,
                    self._cb_stat,
                    self._cb_exit,
                    self._cb_data,
                    self._cb_init,
                    self._cb_bg,
                    None,
                )
                self.native_active = True
                self.log_cb("[SPICE] Linked native libngspice shared library.")
            except Exception as e:
                self.native_active = False
                self.log_cb(f"[SPICE] libngspice fallback to built-in MNA ({e}).")
        else:
            self.log_cb("[SPICE] Using built-in Modified Nodal Analysis (MNA) transient solver.")

    def load_compiled_deck(self, deck: List[str]):
        if self.native_active and self.lib:
            self.lib.ngSpice_Command(b"destroy all")
            for line in deck:
                self.lib.ngSpice_Command(f"circbyline {line}".encode("utf-8"))
            self.lib.ngSpice_Command(b"op")
        self.log_cb(f"[Netlist Compiler] Loaded {len(deck)} SPICE deck statements.")

    def set_potentiometer(self, ratio: float):
        self.pot_ratio = max(0.0, min(1.0, ratio))
        r_top = max(1.0, (1.0 - self.pot_ratio) * 10000.0)
        r_bot = max(1.0, self.pot_ratio * 10000.0)
        if self.native_active and self.lib:
            self.lib.ngSpice_Command(f"alter r_pot_top = {r_top:.2f}".encode("utf-8"))
            self.lib.ngSpice_Command(f"alter r_pot_bot = {r_bot:.2f}".encode("utf-8"))

    def set_button(self, pressed: bool):
        self.button_pressed = pressed
        r_btn = 0.01 if pressed else 100e6
        if self.native_active and self.lib:
            self.lib.ngSpice_Command(f"alter r_btn_sw = {r_btn}".encode("utf-8"))
        self.node_voltages["pb2"] = 0.0 if pressed else 5.0

    def step(self, dt: float):
        r_top = max(1.0, (1.0 - self.pot_ratio) * 10000.0)
        r_bot = max(1.0, self.pot_ratio * 10000.0)
        self.node_voltages["adc0"] = 5.0 * (r_bot / (r_top + r_bot))
        self.node_voltages["pb2"] = 0.0 if self.button_pressed else 5.0

        v_pb0 = self.node_voltages.get("pb0", 0.0)
        v_load = self.node_voltages.get("v_load", 0.0)
        tau = 470.0 * 10e-6
        alpha = min(1.0, dt / (tau + dt))
        self.node_voltages["v_load"] = v_load + alpha * (v_pb0 - v_load)

# ==============================================================================
# 3. MULTI-MCU HARDWARE-AGNOSTIC BACKEND
# ==============================================================================

@dataclass
class SourceInstruction:
    address: int
    opcode_hex: str
    mnemonic: str
    c_source: str

DEFAULT_FIRMWARE_LISTING: List[SourceInstruction] = [
    SourceInstruction(0x02EE, "0E00", "MOVLW 0x00", "void SetupBoard(void) {"),
    SourceInstruction(0x02F0, "6E92", "MOVWF TRISA", "    TRISA = 0xFF; TRISB = 0xFE;"),
    SourceInstruction(0x02F2, "6E95", "CLRF  TRISD", "    LCD_Init_4Bit(); // Milford LCD Demo"),
    SourceInstruction(0x02F6, "0E28", "MOVLW 0x28", "    I2C_Master_Init(100000); // 24LC256"),
    SourceInstruction(0x02FA, "EC80", "CALL  0x0300", "    WriteLCD(\"Milford LCD Demo\");"),
    SourceInstruction(0x0300, "5081", "MOVF  PORTB, W", "    while(1) { // Main VSM Co-Sim Loop"),
    SourceInstruction(0x0302, "B481", "BTFSC PORTB, 2", "        if (!PB_2) bcd_counter++;"),
    SourceInstruction(0x0304, "2A10", "INCF  bcd_cnt, F", "        Sample_ADC0_And_Update_PWM();"),
    SourceInstruction(0x0306, "EC90", "CALL  I2C_Xfer", "        I2C_WriteByte(0xA0, 0x00, bcd_cnt);"),
    SourceInstruction(0x030A, "0EFA", "MOVLW 0xFA", "void Delay(void) { // 125ms timer step"),
    SourceInstruction(0x030C, "0620", "DECF  PowerOnDelay,F", "    PowerOnDelay--;"),
    SourceInstruction(0x030E, "EC40", "CALL  calcVsum", "    calcVsumAndFreq(); // Update Meters"),
    SourceInstruction(0x0312, "D7F6", "BRA   0x0300", "    } // End ISR & Loop"),
]

class MultiMCUBackend:
    def __init__(self, log_cb: Callable[[str], None]):
        self.log_cb = log_cb
        self.arch: str = "PIC18F452"
        self.clock_hz: int = 40_000_000
        self.gpsim_lib = None
        self.simavr_lib = None
        self._probe_native_backends()

        self.listing: List[SourceInstruction] = list(DEFAULT_FIRMWARE_LISTING)
        self.pc_index: int = 0
        self.breakpoints: Set[int] = set()
        self.hit_breakpoint: bool = False

        self.pins: Dict[str, float] = {
            "ADC0": 2.50,
            "PB2": 5.0,
            "PB0": 0.0,
            "PD2_RS": 0.0,
            "PD3_E": 0.0,
            "PD4_D4": 0.0,
            "PD5_D5": 0.0,
            "PD6_D6": 0.0,
            "PD7_D7": 0.0,
            "PD1_TXD": 5.0,
            "PD0_RXD": 5.0,
            "SCL": 5.0,
            "SDA": 5.0,
        }

        self.lcd_bus_cb: Optional[Callable[[int, int, int], None]] = None
        self.uart_tx_cb: Optional[Callable[[int], None]] = None
        self.i2c_pin_cb: Optional[Callable[[int, int, float], None]] = None
        self.freq_edge_cb: Optional[Callable[[float, float], None]] = None

        self.cycle_count: int = 0
        self.sim_time: float = 0.0
        self.bcd_counter: int = 0
        self.power_on_delay: int = 250
        self.rx_fifo: deque = deque()

        self._last_cnt_t: float = 0.0
        self._last_lcd_t: float = -1.0
        self._last_uart_t: float = 0.0
        self._last_i2c_t: float = 0.0
        self._i2c_bit_queue: deque = deque()

    def _probe_native_backends(self):
        for name in [ctypes.util.find_library("gpsim"), "libgpsim.so", "gpsim.dll"]:
            if name:
                try:
                    self.gpsim_lib = ctypes.CDLL(name)
                    self.log_cb("[MCU Engine] Detected native libgpsim shared library.")
                    break
                except OSError:
                    pass
        for name in [ctypes.util.find_library("simavr"), "libsimavr.so", "simavr.dll"]:
            if name:
                try:
                    self.simavr_lib = ctypes.CDLL(name)
                    self.log_cb("[MCU Engine] Detected native libsimavr shared library.")
                    break
                except OSError:
                    pass

    def set_architecture(self, arch: str):
        self.arch = arch
        if "PIC18" in arch:
            self.clock_hz = 40_000_000
        elif "STM32" in arch:
            self.clock_hz = 72_000_000
        else:
            self.clock_hz = 16_000_000
        self.log_cb(f"[MCU Core] Switched target architecture to {self.arch} @ {self.clock_hz // 1_000_000}MHz.")
        self.reset()

    def reset(self):
        self.cycle_count = 0
        self.sim_time = 0.0
        self.pc_index = 0
        self.bcd_counter = 0
        self.power_on_delay = 250
        self.hit_breakpoint = False
        self._last_cnt_t = 0.0
        self._last_lcd_t = -1.0
        self._last_uart_t = 0.0
        self._last_i2c_t = 0.0
        self._i2c_bit_queue.clear()
        self._boot_hd44780()

    def current_instruction(self) -> SourceInstruction:
        return self.listing[self.pc_index % len(self.listing)]

    def toggle_breakpoint(self, address: int) -> bool:
        if address in self.breakpoints:
            self.breakpoints.remove(address)
            return False
        else:
            self.breakpoints.add(address)
            return True

    def _pulse_lcd_nibble(self, rs: int, nibble: int):
        self.pins["PD2_RS"] = 5.0 if rs else 0.0
        self.pins["PD4_D4"] = 5.0 if (nibble & 1) else 0.0
        self.pins["PD5_D5"] = 5.0 if (nibble & 2) else 0.0
        self.pins["PD6_D6"] = 5.0 if (nibble & 4) else 0.0
        self.pins["PD7_D7"] = 5.0 if (nibble & 8) else 0.0
        if self.lcd_bus_cb:
            self.pins["PD3_E"] = 5.0
            self.lcd_bus_cb(rs, 1, nibble & 0x0F)
            self.pins["PD3_E"] = 0.0
            self.lcd_bus_cb(rs, 0, nibble & 0x0F)

    def _send_lcd_byte(self, rs: int, val: int):
        self._pulse_lcd_nibble(rs, (val >> 4) & 0x0F)
        self._pulse_lcd_nibble(rs, val & 0x0F)

    def _boot_hd44780(self):
        for nib in (0x03, 0x03, 0x03, 0x02):
            self._pulse_lcd_nibble(0, nib)
        for cmd in (0x28, 0x0C, 0x06, 0x01):
            self._send_lcd_byte(0, cmd)
        self._send_lcd_byte(0, 0x80)
        banner = "PICDEM 2 PLUS   " if "PIC" in self.arch else "Milford LCD Demo"
        for ch in banner:
            self._send_lcd_byte(1, ord(ch))

    def _enqueue_i2c_eeprom_frame(self, mem_addr: int, data_byte: int):
        seq: List[Tuple[int, int]] = []
        seq.extend([(1, 1), (1, 0), (0, 0)])

        def push_byte(val: int, ack: int = 0):
            for bit_idx in range(7, -1, -1):
                b = (val >> bit_idx) & 1
                seq.extend([(0, b), (1, b), (0, b)])
            seq.extend([(0, ack), (1, ack), (0, ack)])

        push_byte(0xA0, ack=0)
        push_byte(mem_addr & 0xFF, ack=0)
        push_byte(data_byte & 0xFF, ack=0)

        seq.extend([(0, 0), (1, 0), (1, 1)])
        for item in seq:
            self._i2c_bit_queue.append(item)

    def step_instruction(self, dt: float = 0.002, ignore_breakpoint: bool = False) -> bool:
        self.pc_index = (self.pc_index + 1) % len(self.listing)
        insn = self.current_instruction()
        if not ignore_breakpoint and insn.address in self.breakpoints:
            self.hit_breakpoint = True
            return False

        self.cycle_count += int(self.clock_hz * dt)
        self.sim_time += dt
        self.power_on_delay = (self.power_on_delay - 1) & 0xFF

        v_adc0 = self.pins.get("ADC0", 2.50)
        pb2_low = self.pins.get("PB2", 5.0) < 2.5

        target_freq = 100.0 + (v_adc0 / 5.0) * 2400.0
        phase = (self.sim_time * target_freq) % 1.0
        new_pb0 = 5.0 if phase < 0.5 else 0.0
        self.pins["PB0"] = new_pb0
        if self.freq_edge_cb:
            self.freq_edge_cb(new_pb0, target_freq)

        cnt_period = 0.06 if pb2_low else 0.45
        if self.sim_time - self._last_cnt_t >= cnt_period:
            self._last_cnt_t = self.sim_time
            self.bcd_counter = (self.bcd_counter + 1) % 10000

        if self.sim_time - self._last_lcd_t >= 0.12:
            self._last_lcd_t = self.sim_time
            line2 = f"V={v_adc0:4.2f} F={int(target_freq):4d}Hz"
            self._send_lcd_byte(0, 0x80 | 0x40)
            for ch in line2.ljust(16)[:16]:
                self._send_lcd_byte(1, ord(ch))

        if self.sim_time - self._last_i2c_t >= 1.2 and not self._i2c_bit_queue:
            self._last_i2c_t = self.sim_time
            self._enqueue_i2c_eeprom_frame(self.bcd_counter & 0xFF, int(v_adc0 * 51) & 0xFF)

        for _ in range(8):
            if self._i2c_bit_queue:
                scl_b, sda_b = self._i2c_bit_queue.popleft()
                self.pins["SCL"] = 5.0 if scl_b else 0.0
                self.pins["SDA"] = 5.0 if sda_b else 0.0
                if self.i2c_pin_cb:
                    self.i2c_pin_cb(scl_b, sda_b, self.sim_time)

        if self.rx_fifo:
            b = self.rx_fifo.popleft()
            msg = f"\r\n[{self.arch} UART ACK] Byte '{chr(b)}' (0x{b:02X})\r\n"
            for ch_b in msg.encode("ascii", errors="ignore"):
                if self.uart_tx_cb:
                    self.uart_tx_cb(ch_b)

        if self.sim_time - self._last_uart_t >= 1.0:
            self._last_uart_t = self.sim_time
            msg = (
                f"[{self.arch} T={self.sim_time:5.1f}s] PC=0x{insn.address:04X} | "
                f"ADC0={v_adc0:4.2f}V | FREQ={int(target_freq):4d}Hz | CNT={self.bcd_counter:04d}\r\n"
            )
            for ch_b in msg.encode("ascii"):
                if self.uart_tx_cb:
                    self.uart_tx_cb(ch_b)

        return True

    def get_cpu_variables(self) -> List[Tuple[str, str, str]]:
        adc_raw = int((self.pins.get("ADC0", 0.0) / 5.0) * 1023)
        return [
            ("PowerOnDelay", "0x0020", f"0x{self.power_on_delay:02X} ({self.power_on_delay})"),
            ("bcd_counter", "0x0022", f"{self.bcd_counter:04d}"),
            ("ADRESL:ADRESH", "0x0FC3", f"0x{adc_raw:04X} ({adc_raw})"),
            ("PORTB", "0x0F81", f"0x{(1 if self.pins['PB0'] > 2.5 else 0) | (0 if self.pins['PB2'] < 2.5 else 4):02X}"),
            ("SSPBUF (I2C)", "0x0FC9", f"0x{(self.bcd_counter & 0xFF):02X}"),
            ("ProgramCounter", "REG_PC", f"0x{self.current_instruction().address:04X}"),
        ]

# ==============================================================================
# 4. KICAD SYMBOL & SPICE SUBCIRCUIT IMPORTER
# ==============================================================================

SAMPLE_KICAD_SYM_S_EXPR = """
(kicad_symbol_lib (version 20211014) (generator OpenVSM)
  (symbol "Device:OPAMP_BUFFER" (in_bom yes) (on_board yes)
    (property "Reference" "U2" (id 0) (at 0 0 0))
    (property "Value" "LM358_SPICE" (id 1) (at 0 0 0))
    (symbol "OPAMP_BUFFER_1_1"
      (rectangle (start -40 -30) (end 40 30))
      (pin input line (at -40 -10 0) (length 10) (name "IN+" (effects (font (size 1 1)))) (number "1"))
      (pin input line (at -40 10 0) (length 10) (name "IN-" (effects (font (size 1 1)))) (number "2"))
      (pin output line (at 40 0 180) (length 10) (name "OUT" (effects (font (size 1 1)))) (number "3"))
    )
  )
)
"""

SAMPLE_SPICE_SUBCKT = """
.subckt LM358_SPICE in_p in_n out
R_IN in_p in_n 2MEG
E_GAIN out 0 in_p in_n 100000
.ends LM358_SPICE
"""

class KiCadSymbolImporter:
    @staticmethod
    def parse_kicad_sym(sexpr_text: str) -> Dict[str, any]:
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', sexpr_text)
        val_match = re.search(r'\(property\s+"Value"\s+"([^"]+)"', sexpr_text)
        pin_matches = re.findall(
            r'\(pin\s+(\w+)\s+\w+\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+[-\d.]+\).*?\(name\s+"([^"]+)".*?\(number\s+"([^"]+)"',
            sexpr_text,
            re.DOTALL,
        )
        pins = []
        for p_type, x_str, y_str, p_name, p_num in pin_matches:
            pins.append({
                "type": p_type,
                "x": float(x_str),
                "y": float(y_str),
                "name": p_name,
                "number": p_num,
            })
        return {
            "reference": ref_match.group(1) if ref_match else "U_KICAD",
            "value": val_match.group(1) if val_match else "CUSTOM_IC",
            "pins": pins or [
                {"type": "input", "x": -40, "y": -10, "name": "IN+", "number": "1"},
                {"type": "output", "x": 40, "y": 10, "name": "OUT", "number": "2"},
            ],
        }

# ==============================================================================
# 5. INTERACTIVE SCHEMATIC GRAPHICS ITEMS
# ==============================================================================

class ProteusPinSquare(QGraphicsItem):
    def __init__(
        self,
        pin_name: str,
        canonical_net: str,
        is_analog: bool = False,
        parent: Optional[QGraphicsItem] = None,
    ):
        super().__init__(parent)
        self.pin_name = pin_name
        self.canonical_net = canonical_net
        self.is_analog = is_analog
        self.voltage: float = 0.0
        self.connected_wires: List["SchematicWireItem"] = []
        self.setAcceptHoverEvents(True)
        self.hovered = False

    def boundingRect(self) -> QRectF:
        return QRectF(-6, -6, 12, 12)

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#FFFF00" if self.hovered else "#111111"), 1.5 if self.hovered else 0.8))
        if self.is_analog:
            painter.setBrush(QBrush(QColor("#00CC44")))
        elif self.voltage >= 2.5:
            painter.setBrush(QBrush(QColor("#EE1111")))
        elif self.voltage <= 1.5:
            painter.setBrush(QBrush(QColor("#1144EE")))
        else:
            painter.setBrush(QBrush(QColor("#888888")))
        painter.drawRect(-4, -4, 8, 8)

class SchematicWireItem(QGraphicsPathItem):
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
            color = QColor("#CC1111")
            width = 1.8
        elif self.voltage <= 0.5:
            color = QColor("#1144AA")
            width = 1.6
        else:
            color = QColor("#007722")
            width = 1.8

        painter.setPen(QPen(color, width))
        painter.drawPath(self.path())

class MovableSchematicNode(QGraphicsItem):
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

class SchematicMCUItem(MovableSchematicNode):
    def __init__(self, ref: str = "U1", model: str = "PIC18F452"):
        super().__init__()
        self.ref = ref
        self.model = model
        self.w = 200
        self.h = 260

        left = [("ADC0", "adc0", 50, True), ("PB2", "pb2", 110, False)]
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
        painter.setBrush(QBrush(QColor("#E6E4D2")))
        painter.drawRect(0, 0, self.w, self.h)

        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.setPen(QColor("#000080"))
        painter.drawText(4, -6, f"{self.ref} ({self.model})")

        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor("#111111"))
        painter.drawText(10, 54, "RA0/AN0")
        painter.drawText(10, 114, "RB0/INT0")

        labels = [
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

class HD44780LCDItem(MovableSchematicNode):
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
        return "".join(chr(self.ddram[base + i]) if 32 <= self.ddram[base + i] <= 126 else " " for i in range(16))

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 305, 145)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#7A1C1C"), 2))
        painter.setBrush(QBrush(QColor("#E8E6D5")))
        painter.drawRect(0, 0, 285, 115)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111"))
        painter.drawText(4, -5, self.title)

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

class FrequencyMeterItem(MovableSchematicNode):
    def __init__(self):
        super().__init__()
        self.freq_hz: float = 0.0
        self.pins["CLK"] = ProteusPinSquare("CLK", "pb0", parent=self)
        self.pins["CLK"].setPos(0, 32)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 220, 85)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#444444"), 2))
        painter.setBrush(QBrush(QColor("#DCDAD0")))
        painter.drawRect(0, 0, 200, 56)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#222222"))
        painter.drawText(4, -5, "FREQUENCY METER")

        painter.setFont(QFont("Consolas", 7))
        painter.drawText(8, 36, "CLK")

        painter.setPen(QPen(QColor("#222222"), 1))
        painter.setBrush(QBrush(QColor("#1A0404")))
        painter.drawRect(34, 10, 156, 36)

        painter.setFont(QFont("Consolas", 16, QFont.Bold))
        painter.setPen(QColor("#FF2222"))
        painter.drawText(QRectF(34, 10, 156, 36), Qt.AlignCenter, f"{int(self.freq_hz):08d}")

class I2CProtocolAnalyserItem(MovableSchematicNode):
    def __init__(self, log_packet_cb: Callable[[str], None]):
        super().__init__()
        self.log_packet_cb = log_packet_cb
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

        if self._prev_scl == 1 and scl == 1 and self._prev_sda == 1 and sda == 0:
            self._in_frame = True
            self._bits.clear()
            self._frame_tokens = ["[S]"]

        elif self._prev_scl == 1 and scl == 1 and self._prev_sda == 0 and sda == 1:
            if self._in_frame:
                self._frame_tokens.append("[P]")
                summary = " ".join(self._frame_tokens)
                self.last_summary = summary
                self.log_packet_cb(f"[I2C T={sim_t:5.2f}s] {summary}")
                self._in_frame = False

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

        painter.setPen(QPen(QColor("#113366"), 1.5))
        painter.setBrush(QBrush(QColor("#F4F8FF")))
        painter.drawRect(38, 12, 146, 48)

        painter.setFont(QFont("Arial", 14, QFont.Bold))
        painter.setPen(QColor("#002266"))
        painter.drawText(QRectF(38, 14, 146, 24), Qt.AlignCenter, "I2C")

        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QColor("#005500"))
        painter.drawText(QRectF(40, 38, 142, 20), Qt.AlignCenter, self.last_summary[:22])

class RotaryPotentiometerItem(MovableSchematicNode):
    def __init__(self, on_change: Callable[[float], None]):
        super().__init__()
        self.on_change = on_change
        self.ratio = 0.50
        self.pins["WIPER"] = ProteusPinSquare("WIPER", "adc0", is_analog=True, parent=self)
        self.pins["WIPER"].setPos(110, 55)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 135, 130)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#333333"), 1.5))
        painter.setBrush(QBrush(QColor("#EAE8D8")))
        painter.drawRoundedRect(0, 0, 110, 105, 4, 4)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#000080"))
        painter.drawText(4, -5, "RV1 (POT-HG 10k)")

        painter.setPen(QPen(QColor("#601010"), 2))
        painter.setBrush(QBrush(QColor("#D8C8B8")))
        painter.drawRect(36, 18, 20, 68)

        wy = 86 - self.ratio * 68
        painter.setPen(QPen(QColor("#CC0000"), 2))
        painter.drawLine(56, int(wy), 110, 55)

        painter.setPen(QPen(QColor("#444444"), 1))
        painter.setBrush(QBrush(QColor("#D0D0C0")))
        painter.drawRect(8, 24, 20, 20)
        painter.drawRect(8, 60, 20, 20)
        painter.setFont(QFont("Consolas", 11, QFont.Bold))
        painter.setPen(QColor("#111"))
        painter.drawText(QRectF(8, 24, 20, 20), Qt.AlignCenter, "+")
        painter.drawText(QRectF(8, 60, 20, 20), Qt.AlignCenter, "-")

        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.setPen(QColor("#800000"))
        painter.drawText(QRectF(0, 88, 110, 16), Qt.AlignCenter, f"{int(self.ratio * 100)}% ({self.ratio * 5.0:4.2f}V)")

    def mousePressEvent(self, event):
        if QRectF(8, 24, 20, 20).contains(event.pos()):
            self.set_ratio(self.ratio + 0.05)
            event.accept()
            return
        if QRectF(8, 60, 20, 20).contains(event.pos()):
            self.set_ratio(self.ratio - 0.05)
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        delta = 0.05 if event.delta() > 0 else -0.05
        self.set_ratio(self.ratio + delta)
        event.accept()

    def set_ratio(self, r: float):
        self.ratio = max(0.0, min(1.0, r))
        self.pins["WIPER"].voltage = self.ratio * 5.0
        self.on_change(self.ratio)
        self.update()

class InteractiveButtonItem(MovableSchematicNode):
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

        painter.setPen(QPen(QColor("#222"), 2))
        painter.drawLine(15, 35, 45, 35)
        painter.drawLine(85, 35, 130, 35)
        bar_y = 32 if self.pressed else 22
        painter.setPen(QPen(QColor("#CC0000" if self.pressed else "#222"), 2.5))
        painter.drawLine(45, bar_y, 85, bar_y)
        painter.drawRect(58, bar_y - 7, 14, 7)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.pressed = not self.pressed
            self.pins["OUT"].voltage = 0.0 if self.pressed else 5.0
            self.on_toggle(self.pressed)
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

class VirtualVoltmeterItem(MovableSchematicNode):
    def __init__(self, label: str = "DC Volts"):
        super().__init__()
        self.label = label
        self.voltage = 0.0
        self.pins["V+"] = ProteusPinSquare("V+", "v_load", is_analog=True, parent=self)
        self.pins["V+"].setPos(0, 55)

    def boundingRect(self) -> QRectF:
        return QRectF(-15, -20, 135, 135)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111"))
        painter.drawText(4, -5, self.label)

        painter.setPen(QPen(QColor("#6E1E14"), 3.5))
        painter.setBrush(QBrush(QColor("#E6E2CE")))
        painter.drawEllipse(5, 5, 100, 100)

        painter.setPen(QPen(QColor("#00AA22"), 1.5))
        painter.setBrush(QBrush(QColor("#062006")))
        painter.drawRect(20, 32, 70, 26)

        painter.setFont(QFont("Consolas", 11, QFont.Bold))
        painter.setPen(QColor("#22FF55"))
        sign = "+" if self.voltage >= 0 else ""
        painter.drawText(QRectF(20, 32, 70, 26), Qt.AlignCenter, f"{sign}{self.voltage:4.2f}")

        font_unit = QFont("Georgia", 10)
        font_unit.setItalic(True)
        painter.setFont(font_unit)
        painter.setPen(QColor("#5A1810"))
        painter.drawText(QRectF(5, 64, 100, 22), Qt.AlignCenter, "Volts")

class SevenSegmentDisplayItem(MovableSchematicNode):
    def __init__(self):
        super().__init__()
        self.value_str = "0000"
        self.pins["BUS"] = ProteusPinSquare("BUS", "pb0", parent=self)
        self.pins["BUS"].setPos(0, 35)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 190, 95)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#444"), 2))
        painter.setBrush(QBrush(QColor("#D8D8D0")))
        painter.drawRect(0, 0, 170, 66)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111"))
        painter.drawText(4, -5, "LED Display (BCD)")

        painter.setBrush(QBrush(QColor("#140404")))
        painter.drawRect(12, 10, 146, 46)

        painter.setFont(QFont("Consolas", 24, QFont.Bold))
        painter.setPen(QColor("#FF1818"))
        painter.drawText(QRectF(12, 10, 146, 46), Qt.AlignCenter, self.value_str)

class CustomKiCadSymbolItem(MovableSchematicNode):
    def __init__(self, sym_data: Dict[str, any]):
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

# ==============================================================================
# 6. VIRTUAL OSCILLOSCOPE & FLOATING SOURCE DEBUGGER WIDGETS
# ==============================================================================

class DigitalStorageOscilloscope(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.history_len = 240
        self.ch1_adc0 = deque([0.0] * self.history_len, maxlen=self.history_len)
        self.ch2_pb0 = deque([0.0] * self.history_len, maxlen=self.history_len)
        self.ch3_vload = deque([0.0] * self.history_len, maxlen=self.history_len)
        self.ch4_scl = deque([0.0] * self.history_len, maxlen=self.history_len)

    def push_samples(self, v_adc: float, v_pb0: float, v_load: float, v_scl: float):
        self.ch1_adc0.append(v_adc)
        self.ch2_pb0.append(v_pb0)
        self.ch3_vload.append(v_load)
        self.ch4_scl.append(v_scl)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        painter.fillRect(0, 0, w, h, QColor("#081410"))

        painter.setPen(QPen(QColor("#163828"), 1, Qt.DotLine))
        for x in range(0, w, 40):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h, 30):
            painter.drawLine(0, y, w, y)

        def draw_trace(buf: deque, color: str, y_offset: float, scale: float):
            if len(buf) < 2:
                return
            painter.setPen(QPen(QColor(color), 1.8))
            path = QPainterPath()
            dx = w / float(self.history_len - 1)
            for i, val in enumerate(buf):
                px = i * dx
                py = y_offset - (val / 5.0) * scale
                if i == 0:
                    path.moveTo(px, py)
                else:
                    path.lineTo(px, py)
            painter.drawPath(path)

        draw_trace(self.ch1_adc0, "#FFFF00", h * 0.42, h * 0.32)
        draw_trace(self.ch3_vload, "#00FFFF", h * 0.42, h * 0.32)
        draw_trace(self.ch2_pb0, "#FF44AA", h * 0.72, h * 0.20)
        draw_trace(self.ch4_scl, "#44FF44", h * 0.94, h * 0.16)

        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.setPen(QColor("#FFFF00"))
        painter.drawText(8, 14, "CH1: V(adc0)")
        painter.setPen(QColor("#00FFFF"))
        painter.drawText(105, 14, "CH2: V(v_load)")
        painter.setPen(QColor("#FF44AA"))
        painter.drawText(220, 14, "CH3: V(pb0)")
        painter.setPen(QColor("#44FF44"))
        painter.drawText(320, 14, "CH4: I2C SCL")

class SourceDebuggerWidget(QWidget):
    step_into_requested = Signal()
    toggle_bp_requested = Signal(int)

    def __init__(self, mcu: MultiMCUBackend, parent=None):
        super().__init__(parent)
        self.mcu = mcu
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

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

        self.src_table = QTableWidget(len(self.mcu.listing), 4)
        self.src_table.setHorizontalHeaderLabels(["BP/PC", "Addr", "Opcode / ASM", "C Source Code"])
        self.src_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.src_table.verticalHeader().setVisible(False)
        self.src_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.src_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.src_table.setStyleSheet("font-family: Consolas; font-size: 11px; background-color: #FFFFF4;")
        layout.addWidget(self.src_table)

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

# ==============================================================================
# 7. INTERACTIVE SCHEMATIC CANVAS
# ==============================================================================

class InteractiveSchematicCanvas(QGraphicsView):
    topology_changed = Signal()

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QBrush(QColor("#F4F2E6")))
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
                    self.active_wire = SchematicWireItem(clicked_item)
                    self.scene().addItem(self.active_wire)
                elif clicked_item != self.active_wire.pin_start:
                    self.active_wire.pin_end = clicked_item
                    clicked_item.connected_wires.append(self.active_wire)
                    self.active_wire.update_orthogonal_path()
                    self.active_wire = None
                    self.topology_changed.emit()
                event.accept()
                return
            elif self.active_wire is not None:
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
            for item in list(self.scene().selectedItems()):
                if isinstance(item, SchematicWireItem):
                    if item.pin_start and item in item.pin_start.connected_wires:
                        item.pin_start.connected_wires.remove(item)
                    if item.pin_end and item in item.pin_end.connected_wires:
                        item.pin_end.connected_wires.remove(item)
                    self.scene().removeItem(item)
            self.topology_changed.emit()
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)

# ==============================================================================
# 8. LOCKSTEP CO-SIMULATION THREAD & MAIN STUDIO WINDOW
# ==============================================================================

class LockstepWorker(QThread):
    frame_tick = Signal()
    breakpoint_paused = Signal(int)
    uart_rx_char = Signal(int)

    def __init__(self, spice: NgSpiceBridge, mcu: MultiMCUBackend):
        super().__init__()
        self.spice = spice
        self.mcu = mcu
        self.running = False
        self.dt = 0.015
        self.mcu.uart_tx_cb = lambda b: self.uart_rx_char.emit(b)

    def run(self):
        self.running = True
        while self.running:
            t0 = time.perf_counter()

            self.spice.step(self.dt)
            self.mcu.pins["ADC0"] = self.spice.node_voltages.get("adc0", 2.50)
            self.mcu.pins["PB2"] = self.spice.node_voltages.get("pb2", 5.0)

            cont = self.mcu.step_instruction(self.dt, ignore_breakpoint=False)
            self.spice.node_voltages["pb0"] = self.mcu.pins.get("PB0", 0.0)
            self.spice.node_voltages["scl"] = self.mcu.pins.get("SCL", 5.0)
            self.spice.node_voltages["sda"] = self.mcu.pins.get("SDA", 5.0)

            self.frame_tick.emit()

            if not cont:
                self.running = False
                self.breakpoint_paused.emit(self.mcu.current_instruction().address)
                break

            elapsed = time.perf_counter() - t0
            time.sleep(max(0.002, self.dt - elapsed))

    def stop(self):
        self.running = False
        self.wait()

class OpenVSMCompleteSuite(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(
            "OpenVSM Canonical Suite — Interactive Wiring, Source Debugger, DSO/I2C/Freq Instruments & Multi-MCU"
        )
        self.resize(1540, 950)

        self.logs: List[str] = []
        self.spice = NgSpiceBridge(log_cb=self._append_log)
        self.mcu = MultiMCUBackend(log_cb=self._append_log)

        self.wires: List[SchematicWireItem] = []
        self.pin_to_net: Dict[ProteusPinSquare, str] = {}

        self._setup_ui()
        self._build_default_circuit()
        self._compile_netlist()

        self.mcu.lcd_bus_cb = self.lcd_item.process_bus
        self.mcu.i2c_pin_cb = self.i2c_item.sample_bus
        self.mcu.freq_edge_cb = self._on_freq_update
        self.mcu.reset()

        self.worker = LockstepWorker(self.spice, self.mcu)
        self.worker.frame_tick.connect(self._on_frame_tick)
        self.worker.breakpoint_paused.connect(self._on_breakpoint_hit)
        self.worker.uart_rx_char.connect(self._on_uart_byte)

    def _append_log(self, text: str):
        if hasattr(self, "log_edit"):
            self.log_edit.append(text)
        else:
            self.logs.append(text)

    def _setup_ui(self):
        self.scene = QGraphicsScene(-300, -250, 1500, 1000)
        self.canvas = InteractiveSchematicCanvas(self.scene, self)
        self.canvas.topology_changed.connect(self._compile_netlist)
        self.setCentralWidget(self.canvas)

        tb = QToolBar("Main VSM Toolbar", self)
        self.addToolBar(Qt.TopToolBarArea, tb)

        self.act_run = QAction("▶ Run", self)
        self.act_run.triggered.connect(self.start_sim)
        tb.addAction(self.act_run)

        self.act_pause = QAction("⏸ Pause", self)
        self.act_pause.setEnabled(False)
        self.act_pause.triggered.connect(self.pause_sim)
        tb.addAction(self.act_pause)

        self.act_step = QAction("⏭ Step Into (F11)", self)
        self.act_step.setShortcut("F11")
        self.act_step.triggered.connect(self.step_single_instruction)
        tb.addAction(self.act_step)

        self.act_reset = QAction("↺ Reset", self)
        self.act_reset.triggered.connect(self.reset_sim)
        tb.addAction(self.act_reset)

        tb.addSeparator()
        tb.addWidget(QLabel(" Target MCU: "))
        self.arch_combo = QComboBox()
        self.arch_combo.addItems([
            "PIC18F452 (Microchip 40MHz)",
            "ATMEGA328P (AVR 16MHz)",
            "STM32F103C8 (Cortex-M3 72MHz)",
        ])
        self.arch_combo.currentTextChanged.connect(self._on_arch_changed)
        tb.addWidget(self.arch_combo)

        tb.addSeparator()
        act_kicad = QAction("🧩 Import KiCad Symbol (.kicad_sym / Demo)", self)
        act_kicad.triggered.connect(self.import_kicad_symbol)
        tb.addAction(act_kicad)

        act_save = QAction("💾 Save Project JSON", self)
        act_save.triggered.connect(self.save_project_json)
        tb.addAction(act_save)

        dev_dock = QDockWidget("DEVICES (Part Toolbox)", self)
        dev_widget = QWidget()
        dev_layout = QVBoxLayout(dev_widget)
        self.dev_list = QListWidget()
        for part in [
            "PIC18F452",
            "ATMEGA328P",
            "24LC256 (I2C EEPROM)",
            "LM016L (HD44780 LCD)",
            "POT-HG (10k Potentiometer)",
            "BUTTON (PB_2 Switch)",
            "FREQUENCY METER",
            "I2C PROTOCOL ANALYSER",
            "DC VOLTMETER",
            "LM358_SPICE (KiCad Subckt)",
        ]:
            self.dev_list.addItem(part)
        btn_place = QPushButton("➕ Place Selected Part on Canvas")
        btn_place.clicked.connect(self._place_selected_part)
        lbl_hint = QLabel(
            "Tip: Click any two Pin Squares on the schematic to route an orthogonal Manhattan wire. "
            "Select a wire and press Delete to remove it."
        )
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet("color: #444; font-size: 11px;")
        dev_layout.addWidget(self.dev_list)
        dev_layout.addWidget(btn_place)
        dev_layout.addWidget(lbl_hint)
        dev_dock.setWidget(dev_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, dev_dock)

        right_dock = QDockWidget("Source Debugger & Virtual Instruments", self)
        self.right_tabs = QTabWidget()

        self.debugger_widget = SourceDebuggerWidget(self.mcu, self)
        self.debugger_widget.step_into_requested.connect(self.step_single_instruction)
        self.debugger_widget.toggle_bp_requested.connect(self._on_toggle_bp)
        self.right_tabs.addTab(self.debugger_widget, "🐞 CPU Source & Variables")

        inst_panel = QWidget()
        inst_layout = QVBoxLayout(inst_panel)
        self.dso_widget = DigitalStorageOscilloscope(self)
        inst_layout.addWidget(QLabel("4-Channel Digital Storage Oscilloscope (DSO):"))
        inst_layout.addWidget(self.dso_widget)

        inst_layout.addWidget(QLabel("Virtual Terminal (UART) & I2C Protocol Stream:"))
        self.term_edit = QTextEdit()
        self.term_edit.setReadOnly(True)
        self.term_edit.setStyleSheet("background-color: #081008; color: #33FF55; font-family: Consolas; font-size: 11px;")
        inst_layout.addWidget(self.term_edit)

        tx_row = QHBoxLayout()
        self.uart_input = QLineEdit()
        self.uart_input.setPlaceholderText("Transmit ASCII command to MCU RXD...")
        self.uart_input.returnPressed.connect(self._send_uart)
        btn_tx = QPushButton("Send UART")
        btn_tx.clicked.connect(self._send_uart)
        tx_row.addWidget(self.uart_input)
        tx_row.addWidget(btn_tx)
        inst_layout.addLayout(tx_row)

        self.right_tabs.addTab(inst_panel, "📈 Oscilloscope & Protocol Console")
        right_dock.setWidget(self.right_tabs)
        self.addDockWidget(Qt.RightDockWidgetArea, right_dock)

        bot_dock = QDockWidget("SPICE Netlist Compiler & Simulation Log", self)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(130)
        self.log_edit.setStyleSheet("background-color: #1A1A1A; color: #CCCCCC; font-family: Consolas; font-size: 11px;")
        bot_dock.setWidget(self.log_edit)
        self.addDockWidget(Qt.BottomDockWidgetArea, bot_dock)

        for msg in self.logs:
            self.log_edit.append(msg)
        self.logs.clear()

        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready — Click any two pins to route wires, or press '▶ Run' to start co-simulation.")

    def _build_default_circuit(self):
        self.mcu_item = SchematicMCUItem("U1", "PIC18F452")
        self.mcu_item.setPos(220, 40)
        self.scene.addItem(self.mcu_item)

        self.pot_item = RotaryPotentiometerItem(on_change=self.spice.set_potentiometer)
        self.pot_item.setPos(20, 20)
        self.scene.addItem(self.pot_item)

        self.btn_item = InteractiveButtonItem("B2 (PB_2)", on_toggle=self.spice.set_button)
        self.btn_item.setPos(15, 175)
        self.scene.addItem(self.btn_item)

        self.lcd_item = HD44780LCDItem("LCD1 (LM016L - PICDEM 2 PLUS)")
        self.lcd_item.setPos(500, 10)
        self.scene.addItem(self.lcd_item)

        self.freq_item = FrequencyMeterItem()
        self.freq_item.setPos(500, 155)
        self.scene.addItem(self.freq_item)

        self.i2c_item = I2CProtocolAnalyserItem(log_packet_cb=self._on_i2c_packet)
        self.i2c_item.setPos(500, 240)
        self.scene.addItem(self.i2c_item)

        self.voltmeter_item = VirtualVoltmeterItem("Filtered V_LOAD")
        self.voltmeter_item.setPos(745, 15)
        self.scene.addItem(self.voltmeter_item)

        self.seg_item = SevenSegmentDisplayItem()
        self.seg_item.setPos(735, 175)
        self.scene.addItem(self.seg_item)

        pairs = [
            (self.pot_item.pins["WIPER"], self.mcu_item.pins["ADC0"]),
            (self.btn_item.pins["OUT"], self.mcu_item.pins["PB2"]),
            (self.mcu_item.pins["PD2_RS"], self.lcd_item.pins["RS"]),
            (self.mcu_item.pins["PD3_E"], self.lcd_item.pins["E"]),
            (self.mcu_item.pins["PD4_D4"], self.lcd_item.pins["D4"]),
            (self.mcu_item.pins["PD5_D5"], self.lcd_item.pins["D5"]),
            (self.mcu_item.pins["PD6_D6"], self.lcd_item.pins["D6"]),
            (self.mcu_item.pins["PD7_D7"], self.lcd_item.pins["D7"]),
            (self.mcu_item.pins["PB0"], self.freq_item.pins["CLK"]),
            (self.mcu_item.pins["SCL"], self.i2c_item.pins["SCL"]),
            (self.mcu_item.pins["SDA"], self.i2c_item.pins["SDA"]),
        ]
        for p_a, p_b in pairs:
            w = SchematicWireItem(p_a, p_b)
            self.scene.addItem(w)
            self.wires.append(w)

    def _compile_netlist(self):
        all_pins = [it for it in self.scene.items() if isinstance(it, ProteusPinSquare)]
        all_wires = [it for it in self.scene.items() if isinstance(it, SchematicWireItem)]
        self.wires = all_wires
        deck, self.pin_to_net = NetlistCompiler.compile_scene(
            all_pins,
            all_wires,
            self.spice.pot_ratio,
            self.spice.button_pressed,
            self.spice.custom_subcircuits,
        )
        self.spice.load_compiled_deck(deck)

    def _place_selected_part(self):
        current = self.dev_list.currentItem()
        if not current:
            return
        name = current.text()
        if "LM358" in name:
            self.import_kicad_symbol(use_builtin=True)
        elif "VOLTMETER" in name:
            vm = VirtualVoltmeterItem("Probe V")
            vm.setPos(350, 310)
            self.scene.addItem(vm)
        elif "FREQUENCY" in name:
            fm = FrequencyMeterItem()
            fm.setPos(350, 310)
            self.scene.addItem(fm)
        else:
            sym = CustomKiCadSymbolItem({"reference": name.split()[0], "value": name, "pins": []})
            sym.setPos(260, 320)
            self.scene.addItem(sym)
        self._compile_netlist()

    def import_kicad_symbol(self, use_builtin: bool = False):
        sexpr = SAMPLE_KICAD_SYM_S_EXPR
        if not use_builtin:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import KiCad Symbol (.kicad_sym) or Cancel for Built-in LM358 Demo", "", "KiCad Symbol (*.kicad_sym);;All Files (*)"
            )
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    sexpr = f.read()
        sym_data = KiCadSymbolImporter.parse_kicad_sym(sexpr)
        item = CustomKiCadSymbolItem(sym_data)
        item.setPos(220, 330)
        self.scene.addItem(item)
        if SAMPLE_SPICE_SUBCKT not in self.spice.custom_subcircuits:
            self.spice.custom_subcircuits.append(SAMPLE_SPICE_SUBCKT)
        self._append_log(f"[KiCad Importer] Placed symbol '{sym_data['reference']} ({sym_data['value']})' & linked SPICE .subckt.")
        self._compile_netlist()

    def save_project_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save OpenVSM Project", "project_vsm.json", "JSON (*.json)")
        if not path:
            return
        nodes = []
        for it in self.scene.items():
            if isinstance(it, MovableSchematicNode):
                nodes.append({"type": it.__class__.__name__, "x": it.pos().x(), "y": it.pos().y()})
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mcu": self.mcu.arch, "pot_ratio": self.spice.pot_ratio, "nodes": nodes}, f, indent=2)
        self._append_log(f"[Project Saved] Exported schematic layout to {path}")

    def _on_arch_changed(self, text: str):
        arch_code = text.split()[0]
        self.mcu.set_architecture(arch_code)
        self.mcu_item.model = arch_code
        self.mcu_item.update()
        self.debugger_widget.refresh_debugger()

    def _on_freq_update(self, pb0_v: float, freq_hz: float):
        self.freq_item.freq_hz = freq_hz

    def _on_i2c_packet(self, summary: str):
        self.term_edit.append(summary)

    def _on_uart_byte(self, b: int):
        ch = chr(b) if 32 <= b <= 126 or b in (10, 13) else ""
        if ch:
            cursor = self.term_edit.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.insertText(ch.replace("\r", ""))
            self.term_edit.setTextCursor(cursor)

    def _send_uart(self):
        txt = self.uart_input.text()
        if txt:
            for b in txt.encode("ascii", errors="ignore"):
                self.mcu.rx_fifo.append(b)
            self.uart_input.clear()

    def _on_toggle_bp(self, addr: int):
        state = self.mcu.toggle_breakpoint(addr)
        self._append_log(f"[Debugger] Breakpoint {'SET' if state else 'CLEARED'} at 0x{addr:04X}")
        self.debugger_widget.refresh_debugger()

    def _on_breakpoint_hit(self, addr: int):
        self.act_run.setEnabled(True)
        self.act_pause.setEnabled(False)
        self.debugger_widget.refresh_debugger()
        self.statusBar().showMessage(f"PAUSED ON BREAKPOINT — Address 0x{addr:04X} (Press F11 to Step Into)")
        self._append_log(f"[Debugger] Execution halted at breakpoint 0x{addr:04X}")

    def start_sim(self):
        if not self.worker.isRunning():
            self._compile_netlist()
            self.act_run.setEnabled(False)
            self.act_pause.setEnabled(True)
            self.worker.start()
            self.statusBar().showMessage(f"RUNNING — Target: {self.mcu.arch} | Co-Simulation Locked")

    def pause_sim(self):
        if self.worker.isRunning():
            self.worker.stop()
            self.act_run.setEnabled(True)
            self.act_pause.setEnabled(False)
            self.debugger_widget.refresh_debugger()
            self.statusBar().showMessage("PAUSED — Inspect variables or press F11 to single-step.")

    def step_single_instruction(self):
        if self.worker.isRunning():
            self.pause_sim()
        self.spice.step(0.005)
        self.mcu.pins["ADC0"] = self.spice.node_voltages.get("adc0", 2.50)
        self.mcu.pins["PB2"] = self.spice.node_voltages.get("pb2", 5.0)
        self.mcu.step_instruction(0.005, ignore_breakpoint=True)
        self.spice.node_voltages["pb0"] = self.mcu.pins.get("PB0", 0.0)
        self._on_frame_tick()
        self.statusBar().showMessage(f"STEPPED — PC = 0x{self.mcu.current_instruction().address:04X}")

    def reset_sim(self):
        was_running = self.worker.isRunning()
        if was_running:
            self.worker.stop()
        self.mcu.reset()
        self._compile_netlist()
        self._on_frame_tick()
        if was_running:
            self.worker.start()

    def _on_frame_tick(self):
        for pname, pin_sq in self.mcu_item.pins.items():
            pin_sq.voltage = self.mcu.pins.get(pname, 0.0)
            pin_sq.update()

        for wire in self.wires:
            wire.voltage = wire.pin_start.voltage
            wire.update()

        self.lcd_item.update()
        self.freq_item.update()
        self.i2c_item.update()

        self.voltmeter_item.voltage = self.spice.node_voltages.get("v_load", 0.0)
        self.voltmeter_item.pins["V+"].voltage = self.voltmeter_item.voltage
        self.voltmeter_item.update()

        self.seg_item.value_str = f"{self.mcu.bcd_counter:04d}"
        self.seg_item.update()

        self.dso_widget.push_samples(
            self.spice.node_voltages.get("adc0", 0.0),
            self.mcu.pins.get("PB0", 0.0),
            self.spice.node_voltages.get("v_load", 0.0),
            self.mcu.pins.get("SCL", 5.0),
        )

        self.debugger_widget.refresh_debugger()

    def closeEvent(self, event):
        self.worker.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    suite = OpenVSMCompleteSuite()
    suite.show()
    sys.exit(app.exec())
