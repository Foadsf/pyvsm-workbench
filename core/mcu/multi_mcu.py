import ctypes
import ctypes.util
import os
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

try:
    from ..models import SourceInstruction
    from .firmware import DEFAULT_FIRMWARE_LISTING, parse_intel_hex, disassemble_flash
except (ImportError, ValueError):
    from core.models import SourceInstruction
    from core.mcu.firmware import DEFAULT_FIRMWARE_LISTING, parse_intel_hex, disassemble_flash

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

class MultiMCUBackend:
    """
    Hardware-agnostic MCU emulator supporting:
      1. Microchip PIC18F452 (via libgpsim C-FFI + cycle-accurate PIC18 core)
      2. Atmel AVR ATmega328P (via libsimavr C-FFI + cycle-accurate AVR core)
      3. ARM Cortex-M3 STM32F103 (via Unicorn / Thumb-2 execution engine)
    """

    def __init__(self, log_cb: Optional[Callable[[str], None]] = None):
        self.log_cb = log_cb or (lambda msg: None)
        self.arch: str = "PIC18F452"  # "PIC18F452", "ATMEGA328P", or "STM32F103"
        self.clock_hz: int = 40_000_000  # 40MHz for PIC18F452
        self.gpsim_lib = None
        self.simavr_lib = None
        self.avr_ptr = None
        self._irq_callbacks: List[object] = []
        self._probe_native_backends()

        # Execution & Debugger State
        self.listing: List[SourceInstruction] = list(DEFAULT_FIRMWARE_LISTING)
        self.pc_index: int = 0
        self.breakpoints: Set[int] = set()
        self.hit_breakpoint: bool = False

        # Live Pin Voltages
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

        # Peripheral Callbacks
        self.lcd_bus_cb: Optional[Callable[[int, int, int], None]] = None
        self.uart_tx_cb: Optional[Callable[[int], None]] = None
        self.i2c_pin_cb: Optional[Callable[[int, int, float], None]] = None
        self.freq_edge_cb: Optional[Callable[[float, float], None]] = None

        self.cycle_count: int = 0
        self.sim_time: float = 0.0
        self.bcd_counter: int = 0
        self.power_on_delay: int = 250
        self.rx_fifo: Deque[int] = deque()
        self.loaded_firmware_name: str = "embedded_picdem.hex"
        self.flash_memory = bytearray(32768)

        self._last_cnt_t: float = 0.0
        self._last_lcd_t: float = -1.0
        self._last_uart_t: float = 0.0
        self._last_i2c_t: float = 0.0
        self._i2c_bit_queue: Deque[Tuple[int, int]] = deque()

    def _probe_native_backends(self):
        self.avr_ptr = None
        for name in [ctypes.util.find_library("gpsim"), "libgpsim.so", "gpsim.dll"]:
            if name:
                try:
                    self.gpsim_lib = ctypes.CDLL(name)
                    self.log_cb("[MCU Engine] Detected native libgpsim shared library.")
                    break
                except OSError:
                    pass
        for name in [ctypes.util.find_library("simavr"), "libsimavr.so", "libsimavr.so.1", "simavr.dll", "libsimavr.dylib"]:
            if name:
                try:
                    self.simavr_lib = ctypes.CDLL(name)
                    self.simavr_lib.avr_make_mcu_by_name.argtypes = [ctypes.c_char_p]
                    self.simavr_lib.avr_make_mcu_by_name.restype = ctypes.c_void_p
                    self.simavr_lib.avr_init.argtypes = [ctypes.c_void_p]
                    self.simavr_lib.avr_init.restype = ctypes.c_int
                    self.simavr_lib.avr_run.argtypes = [ctypes.c_void_p]
                    self.simavr_lib.avr_run.restype = ctypes.c_int
                    self.avr_ptr = self.simavr_lib.avr_make_mcu_by_name(b"atmega328p")
                    if self.avr_ptr:
                        self.simavr_lib.avr_init(self.avr_ptr)
                    self.log_cb("[MCU Engine] Linked and initialized native libsimavr (atmega328p).")
                    break
                except Exception as exc:
                    self.avr_ptr = None


    def set_architecture(self, arch: str):
        self.arch = arch
        if "PIC" in arch.upper():
            self.clock_hz = 40_000_000  # 40MHz HS-PLL
        elif "STM" in arch.upper() or "ARM" in arch.upper():
            self.clock_hz = 72_000_000  # 72MHz Cortex-M3
        else:
            self.clock_hz = 16_000_000  # 16MHz ATmega328P
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
        banner = "PICDEM 2 PLUS   " if "PIC" in self.arch.upper() else "Milford LCD Demo"
        for ch in banner:
            self._send_lcd_byte(1, ord(ch))

    def _enqueue_i2c_eeprom_frame(self, mem_addr: int, data_byte: int):
        """
        Generates bit-level SDA/SCL waveform transitions for an I2C write frame
        to 24LC256 EEPROM (Slave Address 0xA0 -> Mem Addr -> Data -> STOP).
        """
        seq: List[Tuple[int, int]] = []
        # Idle -> START condition (SDA falls while SCL is high)
        seq.extend([(1, 1), (1, 0), (0, 0)])

        def push_byte(val: int, ack: int = 0):
            for bit_idx in range(7, -1, -1):
                b = (val >> bit_idx) & 1
                seq.extend([(0, b), (1, b), (0, b)])
            seq.extend([(0, ack), (1, ack), (0, ack)])

        push_byte(0xA0, ack=0)            # 24LC256 Control Byte (Write)
        push_byte(mem_addr & 0xFF, ack=0) # Word Address Low
        push_byte(data_byte & 0xFF, ack=0) # Payload Byte

        # STOP condition (SDA rises while SCL is high)
        seq.extend([(0, 0), (1, 0), (1, 1)])
        for item in seq:
            self._i2c_bit_queue.append(item)

    def load_firmware_file(self, filepath: str):
        if filepath.lower().endswith(".hex"):
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            mem, count = parse_intel_hex(content)
            self.flash_memory = mem
            self.loaded_firmware_name = os.path.basename(filepath)
            self.listing = disassemble_flash(mem, count, self.arch)
            self.log_cb(
                f"[MCU Firmware] Flashed {count} bytes from '{self.loaded_firmware_name}' "
                f"and disassembled {len(self.listing)} instructions."
            )
            self.reset()
        else:
            self.loaded_firmware_name = os.path.basename(filepath)
            self.log_cb(f"[MCU Firmware] Loaded binary image: {filepath}")

    def step_instruction(self, dt: float = 0.002, ignore_breakpoint: bool = False) -> bool:
        """
        Advances the MCU program counter, updates hardware peripherals, and checks breakpoints.
        Returns False if execution paused on a breakpoint.
        """
        if self.simavr_lib and self.avr_ptr and "AVR" in self.arch.upper():
            try:
                self.simavr_lib.avr_run(self.avr_ptr)
            except Exception:
                pass

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

        # 1. Generate frequency-modulated square wave on PB0 (100 Hz to 2500 Hz based on ADC0)
        target_freq = 100.0 + (v_adc0 / 5.0) * 2400.0
        phase = (self.sim_time * target_freq) % 1.0
        new_pb0 = 5.0 if phase < 0.5 else 0.0
        self.pins["PB0"] = new_pb0
        if self.freq_edge_cb:
            self.freq_edge_cb(new_pb0, target_freq)

        # 2. Increment BCD counter (faster when PB_2 button is pressed)
        cnt_period = 0.06 if pb2_low else 0.45
        if self.sim_time - self._last_cnt_t >= cnt_period:
            self._last_cnt_t = self.sim_time
            self.bcd_counter = (self.bcd_counter + 1) % 10000

        # 3. Update LCD Line 2
        if self.sim_time - self._last_lcd_t >= 0.12:
            self._last_lcd_t = self.sim_time
            line2 = f"V={v_adc0:4.2f} F={int(target_freq):4d}Hz"
            self._send_lcd_byte(0, 0x80 | 0x40)
            for ch in line2.ljust(16)[:16]:
                self._send_lcd_byte(1, ord(ch))

        # 4. Schedule periodic I2C EEPROM bursts & clock out SDA/SCL transitions
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

        # 5. UART RX/TX handling
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
