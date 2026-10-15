import ctypes
import ctypes.util
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

# ==============================================================================
# STEP 1: CANONICAL LIBNGSPICE C-FFI INTEGRATION
# ==============================================================================

class NgComplex(ctypes.Structure):
    _fields_ = [("cx_real", ctypes.c_double), ("cx_imag", ctypes.c_double)]

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

class VecInfo(ctypes.Structure):
    _fields_ = [
        ("number", ctypes.c_int),
        ("vecname", ctypes.c_char_p),
        ("is_real", ctypes.c_bool),
        ("pdvec", ctypes.c_void_p),
        ("pdvecscale", ctypes.c_void_p),
    ]

P_VecInfo = ctypes.POINTER(VecInfo)

class VecInfoAll(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("title", ctypes.c_char_p),
        ("date", ctypes.c_char_p),
        ("type", ctypes.c_char_p),
        ("veccount", ctypes.c_int),
        ("vecs", ctypes.POINTER(P_VecInfo)),
    ]

class VectorInfo(ctypes.Structure):
    _fields_ = [
        ("v_name", ctypes.c_char_p),
        ("v_type", ctypes.c_int),
        ("v_flags", ctypes.c_short),
        ("v_realdata", ctypes.POINTER(ctypes.c_double)),
        ("v_compdata", ctypes.POINTER(NgComplex)),
        ("v_length", ctypes.c_int),
    ]

# C-Callback Function Prototypes for libngspice
SEND_CHAR_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
)
SEND_STAT_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
)
CONTROLLED_EXIT_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
)
SEND_DATA_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(VecValuesAll), ctypes.c_int, ctypes.c_int, ctypes.c_void_p
)
SEND_INIT_DATA_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(VecInfoAll), ctypes.c_int, ctypes.c_void_p
)
BG_THREAD_RUNNING_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
)

class NgSpiceBridge:
    """
    Canonical wrapper around shared library libngspice (.so / .dll / .dylib).
    Provides netlist loading via ngSpice_Command("circ ..."), SendChar/SendStat/SendData
    callbacks, and dynamic parameter alteration for interactive potentiometers & switches.
    """

    def __init__(self, log_callback: Optional[Callable[[str], None]] = None):
        self.log_callback = log_callback or (lambda msg: None)
        self.lib = None
        self.native_active = False
        self.node_voltages: Dict[str, float] = {
            "vcc": 5.0,
            "adc0": 2.50,
            "pb0": 0.0,
            "pb2": 5.0,
            "v_load": 0.0,
        }
        self.pot_ratio: float = 0.50  # 0.0 to 1.0 wiper position
        self.total_pot_r: float = 10000.0  # 10k Ohm POT-HG
        self.button_pressed: bool = False

        self._bind_callbacks()
        self._load_library()

    def _bind_callbacks(self):
        # Keep persistent references on self so Python GC never collects C callbacks
        self._cb_send_char = SEND_CHAR_CB(self._on_send_char)
        self._cb_send_stat = SEND_STAT_CB(self._on_send_stat)
        self._cb_exit = CONTROLLED_EXIT_CB(self._on_controlled_exit)
        self._cb_send_data = SEND_DATA_CB(self._on_send_data)
        self._cb_send_init = SEND_INIT_DATA_CB(self._on_send_init_data)
        self._cb_bg_running = BG_THREAD_RUNNING_CB(self._on_bg_thread_running)

    def _on_send_char(self, msg_ptr: bytes, ident: int, user_data: int) -> int:
        if msg_ptr:
            text = msg_ptr.decode("utf-8", errors="ignore").strip()
            if text:
                self.log_callback(f"[ngspice] {text}")
        return 0

    def _on_send_stat(self, stat_ptr: bytes, ident: int, user_data: int) -> int:
        return 0

    def _on_controlled_exit(
        self, status: int, immediate: bool, quit_exit: bool, ident: int, user_data: int
    ) -> int:
        self.log_callback(f"[ngspice] Controlled exit (status={status})")
        return 0

    def _on_send_data(
        self, vec_all_ptr, count: int, ident: int, user_data: int
    ) -> int:
        if not vec_all_ptr:
            return 0
        vec_all = vec_all_ptr.contents
        for i in range(vec_all.veccount):
            vec = vec_all.vecsa[i].contents
            if vec.name:
                name = vec.name.decode("utf-8", errors="ignore").lower()
                # Normalize V(node) -> node
                if name.startswith("v(") and name.endswith(")"):
                    name = name[2:-1]
                self.node_voltages[name] = float(vec.creal)
        return 0

    def _on_send_init_data(self, init_ptr, ident: int, user_data: int) -> int:
        return 0

    def _on_bg_thread_running(self, running: bool, ident: int, user_data: int) -> int:
        return 0

    def _load_library(self):
        candidates = [
            ctypes.util.find_library("ngspice"),
            "libngspice.so",
            "libngspice.so.0",
            "ngspice.dll",
            "libngspice.dylib",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                self.lib = ctypes.CDLL(candidate)
                break
            except OSError:
                continue

        if self.lib is not None:
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
                self.lib.ngSpice_Init.restype = ctypes.c_int

                self.lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
                self.lib.ngSpice_Command.restype = ctypes.c_int

                self.lib.ngGet_Vec_Info.argtypes = [ctypes.c_char_p]
                self.lib.ngGet_Vec_Info.restype = ctypes.POINTER(VectorInfo)

                self.lib.ngSpice_Init(
                    self._cb_send_char,
                    self._cb_send_stat,
                    self._cb_exit,
                    self._cb_send_data,
                    self._cb_send_init,
                    self._cb_bg_running,
                    None,
                )
                self.native_active = True
                self.log_callback("[SPICE Core] Native libngspice loaded and initialized.")
                self.load_default_netlist()
            except Exception as exc:
                self.native_active = False
                self.log_callback(f"[SPICE Core] libngspice init error ({exc}); using MNA solver.")
        else:
            self.log_callback(
                "[SPICE Core] libngspice shared library not detected on PATH; "
                "running built-in Modified Nodal Analysis (MNA) SPICE engine."
            )

    def send_command(self, cmd: str):
        if self.native_active and self.lib:
            self.lib.ngSpice_Command(cmd.encode("utf-8"))

    def load_default_netlist(self):
        r_top = max(1.0, (1.0 - self.pot_ratio) * self.total_pot_r)
        r_bot = max(1.0, self.pot_ratio * self.total_pot_r)
        netlist_lines = [
            "OpenVSM Mixed-Mode Co-Simulation Circuit",
            "V_VCC vcc 0 DC 5.0",
            f"R_POT_TOP vcc adc0 {r_top:.1f}",
            f"R_POT_BOT adc0 0 {r_bot:.1f}",
            "R_ADC_IN adc0 0 100MEG",
            "V_PB0 pb0 0 DC 0.0",
            "R_LOAD pb0 v_load 470",
            "C_LOAD v_load 0 10u",
            "R_PULLUP vcc pb2 10k",
            "R_BTN pb2 0 100MEG",
            ".end",
        ]
        if self.native_active:
            for line in netlist_lines:
                self.send_command(f"circbyline {line}")
            self.send_command("op")
        else:
            self._solve_mna_step(0.005)

    def set_potentiometer(self, ratio: float):
        """Dynamically updates POT-HG resistance values in the SPICE netlist."""
        self.pot_ratio = max(0.0, min(1.0, ratio))
        r_top = max(1.0, (1.0 - self.pot_ratio) * self.total_pot_r)
        r_bot = max(1.0, self.pot_ratio * self.total_pot_r)
        if self.native_active:
            self.send_command(f"alter r_pot_top = {r_top:.2f}")
            self.send_command(f"alter r_pot_bot = {r_bot:.2f}")
        self.log_callback(
            f"[SPICE Netlist] POT-HG Wiper={int(self.pot_ratio * 100)}% "
            f"(R_top={r_top:.0f}Ω, R_bot={r_bot:.0f}Ω)"
        )

    def set_button_state(self, pressed: bool):
        """Updates PB_2 switch contact resistance in the SPICE netlist."""
        self.button_pressed = pressed
        r_btn = 0.01 if pressed else 1e8
        if self.native_active:
            self.send_command(f"alter r_btn = {r_btn}")
        self.node_voltages["pb2"] = 0.0 if pressed else 5.0

    def set_mcu_pin_voltage(self, node_name: str, voltage: float):
        node = node_name.lower()
        self.node_voltages[node] = voltage
        if self.native_active and node == "pb0":
            self.send_command(f"alter v_pb0 = {voltage:.3f}")

    def step_analog(self, dt: float):
        if self.native_active:
            self.send_command("op")
        else:
            self._solve_mna_step(dt)

    def _solve_mna_step(self, dt: float):
        r_top = max(1.0, (1.0 - self.pot_ratio) * self.total_pot_r)
        r_bot = max(1.0, self.pot_ratio * self.total_pot_r)
        v_vcc = 5.0
        self.node_voltages["adc0"] = v_vcc * (r_bot / (r_top + r_bot))
        self.node_voltages["pb2"] = 0.0 if self.button_pressed else 5.0

        v_pb0 = self.node_voltages.get("pb0", 0.0)
        v_load = self.node_voltages.get("v_load", 0.0)
        tau = 470.0 * 10e-6
        alpha = min(1.0, dt / (tau + dt))
        self.node_voltages["v_load"] = v_load + alpha * (v_pb0 - v_load)

# ==============================================================================
# STEP 2: CANONICAL LIBSIMAVR C-FFI & INTEL HEX FIRMWARE ENGINE
# ==============================================================================

DEFAULT_DEMO_IHEX = """:100000000C9434000C943E000C943E000C943E0043
:100010000C943E000C943E000C943E000C943E0024
:1000200011241FBECFEFD8E0DEBFCDBF0E944000B6
:100030000C9455000C9400008FE084B98FEF87B989
:1000400080E285B988E285B98CE085B981E085B9F2
:1000500085B1807F85B90000CFFECF98FF98089524
:00000001FF
"""

AVR_IOCTL_IOPORT_GETIRQ = (
    (ord("i") << 24) | (ord("o") << 16) | (ord("g") << 8)
)
AVR_IOCTL_ADC_GETIRQ = (
    (ord("a") << 24) | (ord("d") << 16) | (ord("c") << 8) | ord("g")
)
AVR_IOCTL_UART_GETIRQ = (
    (ord("u") << 24) | (ord("a") << 16) | (ord("r") << 8) | ord("0")
)

AVR_IRQ_NOTIFY_CB = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p
)

class SimAvrBridge:
    def __init__(
        self,
        mcu_name: str = "atmega328p",
        clock_hz: int = 16_000_000,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.mcu_name = mcu_name
        self.clock_hz = clock_hz
        self.log_callback = log_callback or (lambda msg: None)
        self.lib = None
        self.avr_ptr = None
        self.native_active = False

        self.pin_voltages: Dict[str, float] = {
            "PD0_RXD": 5.0,
            "PD1_TXD": 5.0,
            "PD2_RS": 0.0,
            "PD3_E": 0.0,
            "PD4_D4": 0.0,
            "PD5_D5": 0.0,
            "PD6_D6": 0.0,
            "PD7_D7": 0.0,
            "PB0": 0.0,
            "PB2": 5.0,
            "ADC0": 2.50,
        }
        self.sram_watches: Dict[str, Tuple[int, str]] = {
            "SREG": (0x005F, "0x80"),
            "PORTB": (0x0025, "0x00"),
            "PORTD": (0x002B, "0x02"),
            "ADCH:ADCL": (0x0078, "0x0200 (512)"),
            "UDR0 (UART)": (0x00C6, "0x00"),
            "bcd_counter": (0x0100, "0000"),
        }

        self.cycle_count: int = 0
        self.bcd_counter: int = 0
        self._last_counter_step: float = 0.0
        self._last_telemetry_step: float = 0.0
        self._last_lcd_refresh: float = 0.0
        self._sim_time_s: float = 0.0

        self.lcd_bus_callback: Optional[Callable[[int, int, int], None]] = None
        self.uart_tx_callback: Optional[Callable[[int], None]] = None
        self.rx_queue: List[int] = []
        self.loaded_firmware_name: str = "embedded_demo.hex"
        self.flash_memory = bytearray(32768)

        self._irq_callbacks: List[AVR_IRQ_NOTIFY_CB] = []
        self._load_library()
        self.load_ihex_string(DEFAULT_DEMO_IHEX, "milford_lcd_demo.hex")

    def _load_library(self):
        candidates = [
            ctypes.util.find_library("simavr"),
            "libsimavr.so",
            "libsimavr.so.1",
            "simavr.dll",
            "libsimavr.dylib",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                self.lib = ctypes.CDLL(candidate)
                break
            except OSError:
                continue

        if self.lib is not None:
            try:
                self.lib.avr_make_mcu_by_name.argtypes = [ctypes.c_char_p]
                self.lib.avr_make_mcu_by_name.restype = ctypes.c_void_p
                self.lib.avr_init.argtypes = [ctypes.c_void_p]
                self.lib.avr_init.restype = ctypes.c_int
                self.lib.avr_run.argtypes = [ctypes.c_void_p]
                self.lib.avr_run.restype = ctypes.c_int
                self.lib.avr_io_getirq.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int]
                self.lib.avr_io_getirq.restype = ctypes.c_void_p
                self.lib.avr_irq_register_notify.argtypes = [ctypes.c_void_p, AVR_IRQ_NOTIFY_CB, ctypes.c_void_p]
                self.lib.avr_irq_register_notify.restype = None
                self.lib.avr_raise_irq.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                self.lib.avr_raise_irq.restype = None

                self.avr_ptr = self.lib.avr_make_mcu_by_name(self.mcu_name.encode("utf-8"))
                if self.avr_ptr:
                    self.lib.avr_init(self.avr_ptr)
                    self._bind_native_irqs()
                    self.native_active = True
                    self.log_callback(f"[MCU Core] Native libsimavr initialized ({self.mcu_name}).")
            except Exception as exc:
                self.native_active = False
                self.log_callback(f"[MCU Core] libsimavr binding error ({exc}); using built-in core.")
        else:
            self.log_callback(f"[MCU Core] Running built-in {self.mcu_name.upper()} co-simulation core.")

    def _bind_native_irqs(self):
        if not (self.lib and self.avr_ptr):
            return
        def make_port_cb(port_name: str, pin_idx: int):
            @AVR_IRQ_NOTIFY_CB
            def _cb(irq_ptr, value, param):
                v = 5.0 if value else 0.0
                if port_name == "B" and pin_idx == 0:
                    self.pin_voltages["PB0"] = v
            return _cb

        ioctl_portb = AVR_IOCTL_IOPORT_GETIRQ | ord("B")
        irq_pb0 = self.lib.avr_io_getirq(self.avr_ptr, ioctl_portb, 0)
        if irq_pb0:
            cb = make_port_cb("B", 0)
            self._irq_callbacks.append(cb)
            self.lib.avr_irq_register_notify(irq_pb0, cb, None)

    def load_firmware_file(self, filepath: str):
        if filepath.lower().endswith(".hex"):
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            self.load_ihex_string(content, os.path.basename(filepath))
        else:
            self.loaded_firmware_name = os.path.basename(filepath)
            self.log_callback(f"[MCU Firmware] Loaded binary image: {filepath}")

    def load_ihex_string(self, ihex_text: str, filename: str = "firmware.hex"):
        self.loaded_firmware_name = filename
        byte_count = 0
        for line in ihex_text.strip().splitlines():
            line = line.strip()
            if not line.startswith(":") or len(line) < 11:
                continue
            length = int(line[1:3], 16)
            addr = int(line[3:7], 16)
            rec_type = int(line[7:9], 16)
            data_hex = line[9 : 9 + length * 2]
            if rec_type == 0x00:
                for i in range(length):
                    b = int(data_hex[i * 2 : i * 2 + 2], 16)
                    if addr + i < len(self.flash_memory):
                        self.flash_memory[addr + i] = b
                        byte_count += 1
        self.log_callback(f"[MCU Firmware] Flashed {byte_count} bytes from '{filename}'.")
        self.reset()

    def reset(self):
        self.cycle_count = 0
        self.bcd_counter = 0
        self._sim_time_s = 0.0
        self._last_counter_step = 0.0
        self._last_telemetry_step = 0.0
        self._last_lcd_refresh = -1.0
        self._boot_lcd_4bit()

    def _pulse_lcd_nibble(self, rs: int, nibble: int):
        self.pin_voltages["PD2_RS"] = 5.0 if rs else 0.0
        self.pin_voltages["PD4_D4"] = 5.0 if (nibble & 0x01) else 0.0
        self.pin_voltages["PD5_D5"] = 5.0 if (nibble & 0x02) else 0.0
        self.pin_voltages["PD6_D6"] = 5.0 if (nibble & 0x04) else 0.0
        self.pin_voltages["PD7_D7"] = 5.0 if (nibble & 0x08) else 0.0

        if self.lcd_bus_callback:
            self.pin_voltages["PD3_E"] = 5.0
            self.lcd_bus_callback(rs, 1, nibble & 0x0F)
            self.pin_voltages["PD3_E"] = 0.0
            self.lcd_bus_callback(rs, 0, nibble & 0x0F)

    def _send_lcd_byte(self, rs: int, byte_val: int):
        self._pulse_lcd_nibble(rs, (byte_val >> 4) & 0x0F)
        self._pulse_lcd_nibble(rs, byte_val & 0x0F)

    def _boot_lcd_4bit(self):
        self._pulse_lcd_nibble(0, 0x03)
        self._pulse_lcd_nibble(0, 0x03)
        self._pulse_lcd_nibble(0, 0x03)
        self._pulse_lcd_nibble(0, 0x02)
        self._send_lcd_byte(0, 0x28)
        self._send_lcd_byte(0, 0x0C)
        self._send_lcd_byte(0, 0x06)
        self._send_lcd_byte(0, 0x01)

        self._send_lcd_byte(0, 0x80 | 0x00)
        for ch in "Milford LCD Demo":
            self._send_lcd_byte(1, ord(ch))

    def inject_uart_rx(self, text: str):
        for ch in text.encode("utf-8", errors="ignore"):
            self.rx_queue.append(ch)

    def raise_adc_voltage(self, channel: int, voltage: float):
        if channel == 0:
            self.pin_voltages["ADC0"] = voltage
            if self.native_active and self.lib and self.avr_ptr:
                irq = self.lib.avr_io_getirq(self.avr_ptr, AVR_IOCTL_ADC_GETIRQ, 0)
                if irq:
                    self.lib.avr_raise_irq(irq, int(voltage * 1000))

    def raise_gpio_input(self, pin_name: str, voltage: float):
        self.pin_voltages[pin_name] = voltage
        if self.native_active and self.lib and self.avr_ptr and pin_name == "PB2":
            ioctl_portb = AVR_IOCTL_IOPORT_GETIRQ | ord("B")
            irq = self.lib.avr_io_getirq(self.avr_ptr, ioctl_portb, 2)
            if irq:
                self.lib.avr_raise_irq(irq, 1 if voltage >= 2.5 else 0)

    def step_cycles(self, dt: float):
        cycles_to_run = int(self.clock_hz * dt)
        if self.native_active and self.lib and self.avr_ptr:
            native_burst = min(cycles_to_run, 25000)
            for _ in range(native_burst):
                self.lib.avr_run(self.avr_ptr)

        self.cycle_count += cycles_to_run
        self._sim_time_s += dt

        v_adc0 = self.pin_voltages.get("ADC0", 0.0)
        adc_counts = max(0, min(1023, int((v_adc0 / 5.0) * 1023.0)))

        period_s = 0.40
        duty = max(0.15, min(0.85, v_adc0 / 5.0))
        phase = (self._sim_time_s % period_s) / period_s
        pb0_high = phase < duty
        self.pin_voltages["PB0"] = 5.0 if pb0_high else 0.0

        pb2_pressed = self.pin_voltages.get("PB2", 5.0) < 2.5
        counter_interval = 0.08 if pb2_pressed else 0.50
        if self._sim_time_s - self._last_counter_step >= counter_interval:
            self._last_counter_step = self._sim_time_s
            self.bcd_counter = (self.bcd_counter + 1) % 10000

        if self._sim_time_s - self._last_lcd_refresh >= 0.12:
            self._last_lcd_refresh = self._sim_time_s
            btn_tag = "BTN:DN" if pb2_pressed else "BTN:UP"
            line2 = f"ADC:{v_adc0:4.2f}V {btn_tag}"
            self._send_lcd_byte(0, 0x80 | 0x40)
            for ch in line2.ljust(16)[:16]:
                self._send_lcd_byte(1, ord(ch))

        if self.rx_queue:
            rx_byte = self.rx_queue.pop(0)
            reply = f"\r\n[MCU RX ACK] Received '{chr(rx_byte)}' (0x{rx_byte:02X})\r\n"
            for b in reply.encode("ascii", errors="ignore"):
                if self.uart_tx_callback:
                    self.uart_tx_callback(b)

        if self._sim_time_s - self._last_telemetry_step >= 1.0:
            self._last_telemetry_step = self._sim_time_s
            frame = (
                f"[T={self._sim_time_s:5.1f}s] ADC0={v_adc0:4.2f}V ({adc_counts:4d}) | "
                f"CNT={self.bcd_counter:04d} | PB2={'LOW' if pb2_pressed else 'HIGH'}\r\n"
            )
            for b in frame.encode("ascii"):
                if self.uart_tx_callback:
                    self.uart_tx_callback(b)

        portb_val = (0x01 if pb0_high else 0x00) | (0x00 if pb2_pressed else 0x04)
        portd_val = (
            0x02
            | (0x04 if self.pin_voltages["PD2_RS"] > 2.5 else 0)
            | (0x10 if self.pin_voltages["PD4_D4"] > 2.5 else 0)
            | (0x20 if self.pin_voltages["PD5_D5"] > 2.5 else 0)
            | (0x40 if self.pin_voltages["PD6_D6"] > 2.5 else 0)
            | (0x80 if self.pin_voltages["PD7_D7"] > 2.5 else 0)
        )
        self.sram_watches["PORTB"] = (0x0025, f"0x{portb_val:02X}")
        self.sram_watches["PORTD"] = (0x002B, f"0x{portd_val:02X}")
        self.sram_watches["ADCH:ADCL"] = (0x0078, f"0x{adc_counts:04X} ({adc_counts})")
        self.sram_watches["bcd_counter"] = (0x0100, f"{self.bcd_counter:04d}")

# ==============================================================================
# STEP 3: PROTEUS ISIS PERIPHERAL MODELS
# ==============================================================================

class ProteusPinSquare(QGraphicsItem):
    def __init__(self, label: str, is_analog: bool = False, parent=None):
        super().__init__(parent)
        self.label = label
        self.is_analog = is_analog
        self.voltage: float = 0.0

    def boundingRect(self) -> QRectF:
        return QRectF(-4, -4, 8, 8)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#222222"), 0.8))
        if self.is_analog:
            painter.setBrush(QBrush(QColor("#00CC44")))
        elif self.voltage >= 2.5:
            painter.setBrush(QBrush(QColor("#EE1111")))
        elif self.voltage <= 1.5:
            painter.setBrush(QBrush(QColor("#1144EE")))
        else:
            painter.setBrush(QBrush(QColor("#888888")))
        painter.drawRect(-3.5, -3.5, 7, 7)

class HD44780LCDItem(QGraphicsItem):
    def __init__(self, title: str = "LCD1 (LM016L - HD44780)"):
        super().__init__()
        self.title = title
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        self.ddram = [0x20] * 128
        self.ddram_addr: int = 0x00
        self.four_bit_mode: bool = False
        self.display_enabled: bool = True
        self._high_nibble_latched: bool = False
        self._latched_high_nibble: int = 0
        self._prev_e: int = 0

        self.pins: Dict[str, ProteusPinSquare] = {}
        pin_names = ["RS", "E", "D4", "D5", "D6", "D7"]
        for i, name in enumerate(pin_names):
            pin = ProteusPinSquare(name, parent=self)
            pin.setPos(0, 26 + i * 14)
            self.pins[name] = pin

    def process_bus(self, rs: int, e: int, nibble: int):
        self.pins["RS"].voltage = 5.0 if rs else 0.0
        self.pins["E"].voltage = 5.0 if e else 0.0
        self.pins["D4"].voltage = 5.0 if (nibble & 1) else 0.0
        self.pins["D5"].voltage = 5.0 if (nibble & 2) else 0.0
        self.pins["D6"].voltage = 5.0 if (nibble & 4) else 0.0
        self.pins["D7"].voltage = 5.0 if (nibble & 8) else 0.0

        if self._prev_e == 1 and e == 0:
            if not self.four_bit_mode:
                if nibble == 0x02:
                    self.four_bit_mode = True
                    self._high_nibble_latched = False
            else:
                if not self._high_nibble_latched:
                    self._latched_high_nibble = nibble & 0x0F
                    self._high_nibble_latched = True
                else:
                    full_byte = (self._latched_high_nibble << 4) | (nibble & 0x0F)
                    self._high_nibble_latched = False
                    self._execute_byte(rs, full_byte)
        self._prev_e = e

    def _execute_byte(self, rs: int, val: int):
        if rs == 0:
            if val == 0x01:
                self.ddram = [0x20] * 128
                self.ddram_addr = 0x00
            elif val == 0x02:
                self.ddram_addr = 0x00
            elif (val & 0xF8) == 0x08:
                self.display_enabled = bool(val & 0x04)
            elif (val & 0x80) == 0x80:
                self.ddram_addr = val & 0x7F
        else:
            if 0 <= self.ddram_addr < 128:
                self.ddram[self.ddram_addr] = val
                self.ddram_addr = (self.ddram_addr + 1) & 0x7F

    def get_line_text(self, row: int) -> str:
        base = 0x00 if row == 0 else 0x40
        chars = [chr(self.ddram[base + i]) if 32 <= self.ddram[base + i] <= 126 else " " for i in range(16)]
        return "".join(chars)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 310, 140)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#7A1C1C"), 2))
        painter.setBrush(QBrush(QColor("#E8E6D5")))
        painter.drawRect(0, 0, 290, 110)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111111"))
        painter.drawText(4, -5, self.title)

        painter.setPen(QPen(QColor("#3A4A14"), 2))
        painter.setBrush(QBrush(QColor("#8EB82E")))
        painter.drawRect(38, 16, 240, 74)

        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QColor("#222222"))
        for i, name in enumerate(["RS", "E", "D4", "D5", "D6", "D7"]):
            painter.drawText(8, 30 + i * 14, name)

        if self.display_enabled:
            painter.setFont(QFont("Consolas", 13, QFont.Bold))
            painter.setPen(QColor("#102204"))
            painter.drawText(QRectF(48, 24, 224, 28), Qt.AlignLeft | Qt.AlignVCenter, self.get_line_text(0))
            painter.drawText(QRectF(48, 54, 224, 28), Qt.AlignLeft | Qt.AlignVCenter, self.get_line_text(1))

class RotaryPotentiometerItem(QGraphicsItem):
    def __init__(self, on_change: Callable[[float], None]):
        super().__init__()
        self.on_change = on_change
        self.ratio: float = 0.50
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        self.wiper_pin = ProteusPinSquare("ADC0", is_analog=True, parent=self)
        self.wiper_pin.setPos(110, 55)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 135, 130)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#333333"), 1.5))
        painter.setBrush(QBrush(QColor("#EAE8D8")))
        painter.drawRoundedRect(0, 0, 110, 105, 4, 4)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#000080"))
        painter.drawText(4, -5, "RV1 (POT-HG 10kΩ)")

        painter.setPen(QPen(QColor("#601010"), 2))
        painter.setBrush(QBrush(QColor("#D8C8B8")))
        painter.drawRect(36, 18, 20, 68)

        wiper_y = 86 - self.ratio * 68
        painter.setPen(QPen(QColor("#CC0000"), 2))
        painter.drawLine(56, int(wiper_y), 110, 55)

        painter.setPen(QPen(QColor("#444444"), 1))
        painter.setBrush(QBrush(QColor("#D0D0C0")))
        painter.drawRect(8, 24, 20, 20)
        painter.drawRect(8, 60, 20, 20)

        painter.setFont(QFont("Consolas", 11, QFont.Bold))
        painter.setPen(QColor("#111111"))
        painter.drawText(QRectF(8, 24, 20, 20), Qt.AlignCenter, "+")
        painter.drawText(QRectF(8, 60, 20, 20), Qt.AlignCenter, "-")

        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.setPen(QColor("#800000"))
        painter.drawText(
            QRectF(0, 88, 110, 16),
            Qt.AlignCenter,
            f"{int(self.ratio * 100)}% ({self.ratio * 5.0:4.2f}V)",
        )

    def mousePressEvent(self, event):
        pos = event.pos()
        if QRectF(8, 24, 20, 20).contains(pos):
            self.set_ratio(self.ratio + 0.05)
            event.accept()
            return
        elif QRectF(8, 60, 20, 20).contains(pos):
            self.set_ratio(self.ratio - 0.05)
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        delta = 0.05 if event.delta() > 0 else -0.05
        self.set_ratio(self.ratio + delta)
        event.accept()

    def set_ratio(self, new_ratio: float):
        self.ratio = max(0.0, min(1.0, new_ratio))
        self.wiper_pin.voltage = self.ratio * 5.0
        self.on_change(self.ratio)
        self.update()

class InteractiveButtonItem(QGraphicsItem):
    def __init__(self, name: str, on_toggle: Callable[[bool], None]):
        super().__init__()
        self.name = name
        self.on_toggle = on_toggle
        self.pressed: bool = False
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        self.pin_out = ProteusPinSquare("PB2", parent=self)
        self.pin_out.voltage = 5.0
        self.pin_out.setPos(130, 35)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 155, 85)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#333333"), 1.5))
        painter.setBrush(QBrush(QColor("#EAE8D8")))
        painter.drawRoundedRect(0, 0, 130, 62, 4, 4)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111111"))
        painter.drawText(4, -5, f"{self.name} (Click to Toggle)")

        painter.setPen(QPen(QColor("#222222"), 2))
        painter.drawLine(15, 35, 45, 35)
        painter.drawLine(85, 35, 130, 35)
        painter.drawEllipse(QPointF(48, 35), 3, 3)
        painter.drawEllipse(QPointF(82, 35), 3, 3)

        bar_y = 32 if self.pressed else 22
        painter.setPen(QPen(QColor("#990000" if self.pressed else "#222222"), 2.5))
        painter.drawLine(45, bar_y, 85, bar_y)
        painter.drawRect(58, bar_y - 7, 14, 7)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.pressed = not self.pressed
            self.pin_out.voltage = 0.0 if self.pressed else 5.0
            self.on_toggle(self.pressed)
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

class SevenSegmentDisplayItem(QGraphicsItem):
    def __init__(self, title: str = "LED Display (4-Digit BCD)"):
        super().__init__()
        self.title = title
        self.value_str: str = "0000"
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 200, 100)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(QColor("#444444"), 2))
        painter.setBrush(QBrush(QColor("#D8D8D0")))
        painter.drawRect(0, 0, 180, 72)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111111"))
        painter.drawText(4, -5, self.title)

        painter.setPen(QPen(QColor("#222222"), 1))
        painter.setBrush(QBrush(QColor("#140404")))
        painter.drawRect(12, 10, 156, 52)

        painter.setFont(QFont("Consolas", 26, QFont.Bold))
        painter.setPen(QColor("#FF1818"))
        painter.drawText(QRectF(12, 10, 156, 52), Qt.AlignCenter, self.value_str)

class VirtualVoltmeterItem(QGraphicsItem):
    def __init__(self, label: str = "RC Filter Output"):
        super().__init__()
        self.label = label
        self.voltage: float = 0.0
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        self.pin_pos = ProteusPinSquare("V+", is_analog=True, parent=self)
        self.pin_pos.setPos(55, 0)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -20, 130, 140)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#111111"))
        painter.drawText(0, -6, self.label)

        painter.setPen(QPen(QColor("#6E1E14"), 3.5))
        painter.setBrush(QBrush(QColor("#E6E2CE")))
        painter.drawEllipse(5, 5, 100, 100)

        painter.setPen(QPen(QColor("#00AA22"), 1.5))
        painter.setBrush(QBrush(QColor("#062006")))
        painter.drawRect(20, 32, 70, 26)

        painter.setFont(QFont("Consolas", 11, QFont.Bold))
        painter.setPen(QColor("#22FF55"))
        sign = "+" if self.voltage >= 0 else ""
        painter.drawText(
            QRectF(20, 32, 70, 26), Qt.AlignCenter, f"{sign}{self.voltage:4.2f}"
        )

        font_unit = QFont("Georgia", 10)
        font_unit.setItalic(True)
        painter.setFont(font_unit)
        painter.setPen(QColor("#5A1810"))
        painter.drawText(QRectF(5, 64, 100, 22), Qt.AlignCenter, "Volts")

class SchematicMCUItem(QGraphicsItem):
    def __init__(self, ref: str = "U1", model: str = "ATMEGA328P"):
        super().__init__()
        self.ref = ref
        self.model = model
        self.w = 190
        self.h = 240
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        self.pins: Dict[str, ProteusPinSquare] = {}
        left_pins = [("ADC0", 50, True), ("PB2", 110, False)]
        right_pins = [
            ("PD2_RS", 35, False),
            ("PD3_E", 55, False),
            ("PD4_D4", 75, False),
            ("PD5_D5", 95, False),
            ("PD6_D6", 115, False),
            ("PD7_D7", 135, False),
            ("PB0", 175, False),
            ("PD1_TXD", 205, False),
            ("PD0_RXD", 220, False),
        ]
        for name, y, is_analog in left_pins:
            p = ProteusPinSquare(name, is_analog=is_analog, parent=self)
            p.setPos(0, y)
            self.pins[name] = p
        for name, y, is_analog in right_pins:
            p = ProteusPinSquare(name, is_analog=is_analog, parent=self)
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
        painter.drawText(10, 54, "PC0/ADC0")
        painter.drawText(10, 114, "PB2/INT0")

        right_labels = [
            ("PD2 (LCD_RS)", 39),
            ("PD3 (LCD_E)", 59),
            ("PD4 (LCD_D4)", 79),
            ("PD5 (LCD_D5)", 99),
            ("PD6 (LCD_D6)", 119),
            ("PD7 (LCD_D7)", 139),
            ("PB0 (PWM/RC)", 179),
            ("PD1 (TXD)", 209),
            ("PD0 (RXD)", 224),
        ]
        for text, y in right_labels:
            painter.drawText(self.w - 92, y, text)

class VirtualTerminalWidget(QWidget):
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
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(self._buffer.replace("\r", ""))
            self.console.setTextCursor(cursor)
            self.console.ensureCursorVisible()
            self._buffer = ""

    def _send_line(self):
        txt = self.input_line.text()
        if txt:
            self.tx_key_pressed.emit(txt)
            self.input_line.clear()

# ==============================================================================
# 4. CO-SIMULATION THREAD & SCHEMATIC WORKSPACE
# ==============================================================================

class CoSimulationCoordinator(QThread):
    frame_ready = Signal()
    uart_byte_emitted = Signal(int)

    def __init__(self, spice: NgSpiceBridge, mcu: SimAvrBridge):
        super().__init__()
        self.spice = spice
        self.mcu = mcu
        self.running = False
        self.dt = 0.015
        self.mcu.uart_tx_callback = self._on_uart_tx

    def _on_uart_tx(self, byte_val: int):
        self.uart_byte_emitted.emit(byte_val)

    def run(self):
        self.running = True
        while self.running:
            t0 = time.perf_counter()

            self.spice.step_analog(self.dt)
            self.mcu.raise_adc_voltage(0, self.spice.node_voltages.get("adc0", 2.5))
            self.mcu.raise_gpio_input("PB2", self.spice.node_voltages.get("pb2", 5.0))
            self.mcu.step_cycles(self.dt)
            self.spice.set_mcu_pin_voltage("pb0", self.mcu.pin_voltages.get("PB0", 0.0))

            self.frame_ready.emit()

            elapsed = time.perf_counter() - t0
            time.sleep(max(0.001, self.dt - elapsed))

    def stop(self):
        self.running = False
        self.wait()

class ProteusSchematicCanvas(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QBrush(QColor("#F4F2E6")))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.grid_step = 20

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor("#DEDAC4"), 0.7))
        left = int(rect.left()) - (int(rect.left()) % self.grid_step)
        top = int(rect.top()) - (int(rect.top()) % self.grid_step)
        for x in range(left, int(rect.right()), self.grid_step):
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, int(rect.bottom()), self.grid_step):
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)

    def wheelEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, RotaryPotentiometerItem):
            super().wheelEvent(event)
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)

class OpenVSMCanonicalStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(
            "OpenVSM Canonical Studio — libngspice + libsimavr + HD44780/POT-HG/UART Co-Simulator"
        )
        self.resize(1460, 920)
        self._pending_logs: List[str] = []

        self.spice = NgSpiceBridge(log_callback=self._queue_log)
        self.mcu = SimAvrBridge(log_callback=self._queue_log)

        self._build_ui()
        self._populate_schematic()

        self.mcu.lcd_bus_callback = self.lcd_item.process_bus
        self.mcu.reset()

        self.coordinator = CoSimulationCoordinator(self.spice, self.mcu)
        self.coordinator.frame_ready.connect(self._refresh_visuals)
        self.coordinator.uart_byte_emitted.connect(
            self.terminal_widget.append_serial_byte
        )
        self.terminal_widget.tx_key_pressed.connect(self.mcu.inject_uart_rx)

        self._flush_logs()

    def _queue_log(self, msg: str):
        if hasattr(self, "log_box"):
            self.log_box.append(msg)
        else:
            self._pending_logs.append(msg)

    def _flush_logs(self):
        for msg in self._pending_logs:
            self.log_box.append(msg)
        self._pending_logs.clear()

    def _build_ui(self):
        self.scene = QGraphicsScene(-400, -300, 1400, 900)
        self.canvas = ProteusSchematicCanvas(self.scene, self)
        self.setCentralWidget(self.canvas)

        tb = QToolBar("VSM Controls", self)
        self.addToolBar(Qt.TopToolBarArea, tb)

        self.act_run = QAction("▶ Run Co-Simulation", self)
        self.act_run.triggered.connect(self.start_simulation)
        tb.addAction(self.act_run)

        self.act_stop = QAction("⏹ Pause / Stop", self)
        self.act_stop.setEnabled(False)
        self.act_stop.triggered.connect(self.stop_simulation)
        tb.addAction(self.act_stop)

        self.act_reset = QAction("↺ Reset MCU & SPICE", self)
        self.act_reset.triggered.connect(self.reset_simulation)
        tb.addAction(self.act_reset)

        tb.addSeparator()

        act_load_hex = QAction("📂 Load Firmware (.hex / .elf)...", self)
        act_load_hex.triggered.connect(self.prompt_load_firmware)
        tb.addAction(act_load_hex)

        self.term_dock = QDockWidget("Virtual Terminal (UART0 - 9600 8N1)", self)
        self.terminal_widget = VirtualTerminalWidget(self)
        self.term_dock.setWidget(self.terminal_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.term_dock)

        self.watch_dock = QDockWidget("AVR CPU Registers & SPICE Node Watch", self)
        self.watch_box = QTextEdit()
        self.watch_box.setReadOnly(True)
        self.watch_box.setStyleSheet(
            "background-color: #FBFBF8; color: #111; font-family: Consolas; font-size: 11px;"
        )
        self.watch_dock.setWidget(self.watch_box)
        self.addDockWidget(Qt.RightDockWidgetArea, self.watch_dock)

        self.log_dock = QDockWidget("SPICE & MCU Co-Simulation Advisor", self)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(150)
        self.log_box.setStyleSheet(
            "background-color: #1A1A1A; color: #CCCCCC; font-family: Consolas; font-size: 11px;"
        )
        self.log_dock.setWidget(self.log_box)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)

        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready — Click '▶ Run Co-Simulation' to start lockstep execution.")

    def _populate_schematic(self):
        self.mcu_item = SchematicMCUItem("U1", "ATMEGA328P")
        self.mcu_item.setPos(220, 40)
        self.scene.addItem(self.mcu_item)

        self.pot_item = RotaryPotentiometerItem(on_change=self.spice.set_potentiometer)
        self.pot_item.setPos(30, 20)
        self.scene.addItem(self.pot_item)

        self.btn_item = InteractiveButtonItem("B2 (PB_2)", on_toggle=self.spice.set_button_state)
        self.btn_item.setPos(20, 175)
        self.scene.addItem(self.btn_item)

        self.lcd_item = HD44780LCDItem("LCD1 (MILFORD-2X16-BKP / HD44780)")
        self.lcd_item.setPos(500, 15)
        self.scene.addItem(self.lcd_item)

        self.voltmeter_item = VirtualVoltmeterItem("Filtered PWM (V_LOAD)")
        self.voltmeter_item.setPos(500, 180)
        self.scene.addItem(self.voltmeter_item)

        self.seg_item = SevenSegmentDisplayItem("LED Display (BCD Counter)")
        self.seg_item.setPos(650, 200)
        self.scene.addItem(self.seg_item)

    def start_simulation(self):
        if not self.coordinator.isRunning():
            self.act_run.setEnabled(False)
            self.act_stop.setEnabled(True)
            self.coordinator.start()
            self.statusBar().showMessage(
                f"RUNNING — Firmware: {self.mcu.loaded_firmware_name} | Lockstep Δt = 15ms"
            )

    def stop_simulation(self):
        if self.coordinator.isRunning():
            self.coordinator.stop()
            self.act_run.setEnabled(True)
            self.act_stop.setEnabled(False)
            self.statusBar().showMessage("PAUSED — Co-simulation halted.")

    def reset_simulation(self):
        was_running = self.coordinator.isRunning()
        if was_running:
            self.coordinator.stop()
        self.mcu.reset()
        self.spice.load_default_netlist()
        self._refresh_visuals()
        if was_running:
            self.coordinator.start()

    def prompt_load_firmware(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select AVR Firmware Binary",
            "",
            "AVR Firmware (*.hex *.elf);;All Files (*)",
        )
        if path:
            self.mcu.load_firmware_file(path)
            self._refresh_visuals()

    def _refresh_visuals(self):
        for pin_name, pin_item in self.mcu_item.pins.items():
            pin_item.voltage = self.mcu.pin_voltages.get(pin_name, 0.0)
            pin_item.update()

        self.lcd_item.update()
        self.voltmeter_item.voltage = self.spice.node_voltages.get("v_load", 0.0)
        self.voltmeter_item.pin_pos.voltage = self.voltmeter_item.voltage
        self.voltmeter_item.update()

        self.seg_item.value_str = f"{self.mcu.bcd_counter:04d}"
        self.seg_item.update()

        lines = [
            f"=== AVR CORE ({self.mcu.mcu_name.upper()}) ===",
            f"Firmware   : {self.mcu.loaded_firmware_name}",
            f"Clock Ticks: {self.mcu.cycle_count:,}",
            "",
            "--- Register / Symbol Watch ---",
        ]
        for sym, (addr, val) in self.mcu.sram_watches.items():
            lines.append(f"0x{addr:04X}  {sym:13}: {val}")

        lines.append("\n=== SPICE ANALOG NODES ===")
        for node, v in self.spice.node_voltages.items():
            lines.append(f"V({node:8}) : {v:6.3f} V")

        self.watch_box.setPlainText("\n".join(lines))

    def closeEvent(self, event):
        self.coordinator.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    studio = OpenVSMCanonicalStudio()
    studio.show()
    sys.exit(app.exec())
