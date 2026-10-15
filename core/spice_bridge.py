import ctypes
import ctypes.util
from typing import Callable, Dict, List, Optional
from .models import (
    SEND_CHAR_CB,
    SEND_STAT_CB,
    CONTROLLED_EXIT_CB,
    SEND_DATA_CB,
    SEND_INIT_DATA_CB,
    BG_THREAD_RUNNING_CB,
    VecValuesAll,
    VectorInfo,
)

class NgSpiceBridge:
    """
    Interfaces with shared library libngspice (.so / .dll / .dylib) via C-FFI,
    or runs deterministic Modified Nodal Analysis (MNA) transient integration.
    """

    def __init__(self, log_cb: Optional[Callable[[str], None]] = None):
        self.log_cb = log_cb or (lambda msg: None)
        self.lib = None
        self.native_active = False
        self.pot_ratio: float = 0.50
        self.total_pot_r: float = 10000.0
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

        # Keep persistent references to avoid Python GC collecting C callbacks
        self._cb_char = SEND_CHAR_CB(self._on_char)
        self._cb_stat = SEND_STAT_CB(self._on_stat)
        self._cb_exit = CONTROLLED_EXIT_CB(self._on_exit)
        self._cb_data = SEND_DATA_CB(self._on_data)
        self._cb_init = SEND_INIT_DATA_CB(self._on_init)
        self._cb_bg = BG_THREAD_RUNNING_CB(self._on_bg)

        self._init_dll()

    def _on_char(self, msg_ptr: bytes, ident: int, user_data: int) -> int:
        if msg_ptr:
            txt = msg_ptr.decode("utf-8", errors="ignore").strip()
            if txt:
                self.log_cb(f"[ngspice] {txt}")
        return 0

    def _on_stat(self, stat_ptr: bytes, ident: int, user_data: int) -> int:
        return 0

    def _on_exit(self, status: int, immediate: bool, quit_exit: bool, ident: int, user_data: int) -> int:
        self.log_cb(f"[ngspice] Controlled exit (status={status})")
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

    def _on_init(self, init_ptr, ident: int, user_data: int) -> int:
        return 0

    def _on_bg(self, running: bool, ident: int, user_data: int) -> int:
        return 0

    def _init_dll(self):
        candidates = [
            ctypes.util.find_library("ngspice"),
            "libngspice.so",
            "libngspice.so.0",
            "ngspice.dll",
            "libngspice.dylib",
        ]
        for cand in candidates:
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
                self.lib.ngSpice_Init.restype = ctypes.c_int

                self.lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
                self.lib.ngSpice_Command.restype = ctypes.c_int

                self.lib.ngGet_Vec_Info.argtypes = [ctypes.c_char_p]
                self.lib.ngGet_Vec_Info.restype = ctypes.POINTER(VectorInfo)

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

    def send_command(self, cmd: str):
        if self.native_active and self.lib:
            self.lib.ngSpice_Command(cmd.encode("utf-8"))

    def load_compiled_deck(self, deck: List[str]):
        if self.native_active and self.lib:
            self.send_command("destroy all")
            for line in deck:
                self.send_command(f"circbyline {line}")
            self.send_command("op")
        else:
            self.step(0.005)
        self.log_cb(f"[Netlist Compiler] Loaded {len(deck)} SPICE deck statements.")

    def set_potentiometer(self, ratio: float):
        """Dynamically updates POT-HG resistance values in the SPICE netlist."""
        self.pot_ratio = max(0.0, min(1.0, ratio))
        r_top = max(1.0, (1.0 - self.pot_ratio) * self.total_pot_r)
        r_bot = max(1.0, self.pot_ratio * self.total_pot_r)
        if self.native_active:
            self.send_command(f"alter r_pot_top = {r_top:.2f}")
            self.send_command(f"alter r_pot_bot = {r_bot:.2f}")
        self.log_cb(
            f"[SPICE Netlist] POT-HG Wiper={int(self.pot_ratio * 100)}% "
            f"(R_top={r_top:.0f}Ω, R_bot={r_bot:.0f}Ω)"
        )

    def set_button(self, pressed: bool):
        """Updates PB_2 switch contact resistance in the SPICE netlist."""
        self.button_pressed = pressed
        r_btn = 0.01 if pressed else 100e6
        if self.native_active:
            self.send_command(f"alter r_btn_sw = {r_btn}")
        self.node_voltages["pb2"] = 0.0 if pressed else 5.0

    def set_mcu_pin_voltage(self, node_name: str, voltage: float):
        node = node_name.lower()
        self.node_voltages[node] = voltage
        if self.native_active and node == "pb0":
            self.send_command(f"alter v_pb0 = {voltage:.3f}")

    def step(self, dt: float):
        """Advances analog simulation time by dt seconds."""
        # 1. Potentiometer voltage divider calculation
        r_top = max(1.0, (1.0 - self.pot_ratio) * self.total_pot_r)
        r_bot = max(1.0, self.pot_ratio * self.total_pot_r)
        v_vcc = 5.0
        self.node_voltages["adc0"] = v_vcc * (r_bot / (r_top + r_bot))
        self.node_voltages["pb2"] = 0.0 if self.button_pressed else 5.0

        # 2. First-order RC transient integration for v_load node:
        # dV_load/dt = (V_pb0 - V_load) / RC
        v_pb0 = self.node_voltages.get("pb0", 0.0)
        v_load = self.node_voltages.get("v_load", 0.0)
        tau = 470.0 * 10e-6  # R=470 Ohm, C=10uF -> tau = 4.7ms
        alpha = min(1.0, dt / (tau + dt))
        self.node_voltages["v_load"] = v_load + alpha * (v_pb0 - v_load)

        if self.native_active:
            self.send_command("op")
