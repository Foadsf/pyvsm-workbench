import time
from PySide6.QtCore import QThread, Signal
from .spice_bridge import NgSpiceBridge
from .mcu.multi_mcu import MultiMCUBackend

class LockstepWorker(QThread):
    """
    Lockstep time-slice coordinator synchronizing NgSpiceBridge and MultiMCUBackend.
    Advances simulation by fixed time delta slices (dt), exchanging pin voltages and node voltages.
    """

    frame_tick = Signal()
    breakpoint_paused = Signal(int)
    uart_rx_char = Signal(int)

    def __init__(self, spice: NgSpiceBridge, mcu: MultiMCUBackend, dt: float = 0.015, input_sync_cb=None):
        super().__init__()
        self.spice = spice
        self.mcu = mcu
        self.dt = dt
        self.input_sync_cb = input_sync_cb
        self.running = False
        self.mcu.uart_tx_cb = lambda b: self.uart_rx_char.emit(b)

    def run(self):
        self.running = True
        while self.running:
            t0 = time.perf_counter()

            # 1. Step SPICE analog solver
            self.spice.step(self.dt)

            # 2. Transfer SPICE node voltages to MCU analog/digital inputs
            if self.input_sync_cb:
                self.input_sync_cb()
            else:
                self.mcu.pins["ADC0"] = self.spice.node_voltages.get("adc0", 2.50)
                self.mcu.pins["PB2"] = self.spice.node_voltages.get("pb2", 5.0)

            # 3. Step MCU instruction & check breakpoints
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
