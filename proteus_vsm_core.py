import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
from PySide6.QtCore import Qt, QThread, Signal, QRectF, QPointF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QMainWindow,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

# ==============================================================================
# 1. CO-SIMULATION BUS & BACKEND INTERFACES
# ==============================================================================

@dataclass
class PinState:
    pin_id: str
    voltage: float
    is_digital: bool = True
    logic_level: int = 0  # 0: Low, 1: High, -1: Hi-Z

class VirtualMCU:
    """
    Lightweight MCU bridge mock. In production, this interfaces directly
    with libsimavr or Renode via ctypes/CFFI.
    """
    def __init__(self, mcu_type: str = "ATmega328P", clock_hz: int = 16_000_000):
        self.mcu_type = mcu_type
        self.clock_hz = clock_hz
        self.pins: Dict[str, PinState] = {
            "PB0": PinState("PB0", 0.0, True, 0),
            "PB1": PinState("PB1", 5.0, True, 1),
            "ADC0": PinState("ADC0", 0.0, False, 0),
        }
        self.tick_counter = 0

    def step(self, delta_time_s: float):
        # Advance instruction cycles
        cycles = int(self.clock_hz * delta_time_s)
        self.tick_counter += cycles

        # Simulating MCU Firmware: Toggle PB0 every ~500ms
        toggle_threshold = self.clock_hz // 2
        if (self.tick_counter // toggle_threshold) % 2 == 0:
            self.pins["PB0"].voltage = 5.0
            self.pins["PB0"].logic_level = 1
        else:
            self.pins["PB0"].voltage = 0.0
            self.pins["PB0"].logic_level = 0

    def set_input_voltage(self, pin_id: str, voltage: float):
        if pin_id in self.pins:
            self.pins[pin_id].voltage = voltage
            self.pins[pin_id].logic_level = 1 if voltage > 2.5 else 0

class SimulationWorker(QThread):
    """
    Lockstep engine thread executing MCU and mixed-mode circuits.
    """
    state_updated = Signal(dict)
    log_message = Signal(str)

    def __init__(self, mcu: VirtualMCU):
        super().__init__()
        self.mcu = mcu
        self.running = False
        self.step_size = 0.005  # 5ms real-time step for demonstrator

    def run(self):
        self.running = True
        self.log_message.emit("Simulation started: Co-simulation sync locked.")
        while self.running:
            start_t = time.perf_counter()

            # 1. Step MCU Instructions
            self.mcu.step(self.step_size)

            # 2. Package current net/pin status for UI refresh
            snapshot = {pin: PinState(p.pin_id, p.voltage, p.is_digital, p.logic_level)
                        for pin, p in self.mcu.pins.items()}
            self.state_updated.emit(snapshot)

            # Keep execution at fixed cadence
            elapsed = time.perf_counter() - start_t
            sleep_duration = max(0.0, self.step_size - elapsed)
            time.sleep(sleep_duration)

    def stop(self):
        self.running = False
        self.wait()
        self.log_message.emit("Simulation stopped.")

# ==============================================================================
# 2. CAD GRAPHICS ELEMENTS (PROTEUS ISIS AESTHETICS)
# ==============================================================================

class ProteusPinItem(QGraphicsItem):
    """
    Renders standard Proteus pin indicator:
    - Red Box: Logic HIGH (Vcc)
    - Blue Box: Logic LOW (GND)
    - Grey Box: Floating / Hi-Z
    """
    def __init__(self, pin_name: str, parent=None):
        super().__init__(parent)
        self.pin_name = pin_name
        self.state = PinState(pin_name, 0.0, True, 0)

    def boundingRect(self) -> QRectF:
        return QRectF(-4, -4, 8, 8)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(Qt.NoPen)
        if not self.state.is_digital:
            brush = QBrush(QColor("#00FF00"))  # Green for Analog
        elif self.state.logic_level == 1:
            brush = QBrush(QColor("#FF0000"))  # Red = 5V
        elif self.state.logic_level == 0:
            brush = QBrush(QColor("#0000FF"))  # Blue = 0V
        else:
            brush = QBrush(QColor("#808080"))  # Grey = Floating
        painter.setBrush(brush)
        painter.drawRect(-3, -3, 6, 6)

class SchematicMCUItem(QGraphicsItem):
    """Microcontroller visual representation with dynamic I/O pins."""
    def __init__(self, name: str, part_num: str):
        super().__init__()
        self.name = name
        self.part_num = part_num
        self.width = 160
        self.height = 220
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        # Pin map
        self.pins: Dict[str, ProteusPinItem] = {}
        self._setup_pins()

    def _setup_pins(self):
        coords = {
            "PB0": (self.width, 40),
            "PB1": (self.width, 70),
            "ADC0": (0, 40),
        }
        for name, (x, y) in coords.items():
            pin_item = ProteusPinItem(name, self)
            pin_item.setPos(x, y)
            self.pins[name] = pin_item

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -10, self.width + 20, self.height + 20)

    def paint(self, painter: QPainter, option, widget=None):
        # Body
        painter.setPen(QPen(QColor("#333333"), 2))
        painter.setBrush(QBrush(QColor("#E8E8DF")))  # Proteus IC beige
        painter.drawRect(0, 0, self.width, self.height)

        # Labels
        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.setPen(QColor("#000080"))
        painter.drawText(QRectF(10, 10, self.width - 20, 20), Qt.AlignCenter, self.name)
        painter.setFont(QFont("Arial", 8))
        painter.setPen(QColor("#222222"))
        painter.drawText(QRectF(10, 30, self.width - 20, 20), Qt.AlignCenter, self.part_num)

        # Pin Text Labels
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(10, 45, "ADC0")
        painter.drawText(self.width - 35, 45, "PB0")
        painter.drawText(self.width - 35, 75, "PB1")

class VirtualVoltmeterItem(QGraphicsItem):
    """Proteus round dynamic voltmeter instrument."""
    def __init__(self, ref_des: str = "DC Volts"):
        super().__init__()
        self.ref_des = ref_des
        self.voltage = 0.0
        self.setFlag(QGraphicsItem.ItemIsMovable, True)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, 110, 110)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        # Bezel
        painter.setPen(QPen(QColor("#5A2A18"), 4))
        painter.setBrush(QBrush(QColor("#EFEBD6")))
        painter.drawEllipse(5, 5, 100, 100)

        # Display Frame
        painter.setPen(QPen(QColor("#00AA00"), 1.5))
        painter.setBrush(QBrush(QColor("#000000")))
        painter.drawRect(20, 30, 70, 26)

        # Voltage Readout
        painter.setFont(QFont("Segment7", 10, QFont.Bold))
        painter.setPen(QColor("#00FF44"))
        sign = "+" if self.voltage >= 0 else ""
        txt = f"{sign}{self.voltage:4.2f}"
        painter.drawText(QRectF(20, 30, 70, 26), Qt.AlignCenter, txt)

        font_unit = QFont("Georgia", 11)
        font_unit.setItalic(True)
        painter.setFont(font_unit)
        painter.setPen(QColor("#4A2010"))
        painter.drawText(QRectF(0, 65, 110, 20), Qt.AlignCenter, "Volts")

# ==============================================================================
# 3. INTERACTIVE CANVAS & MAIN WINDOW
# ==============================================================================

class SchematicView(QGraphicsView):
    """Hardware accelerated interactive canvas supporting pan & grid."""
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#F5F4E8")))  # Proteus background color
        self.grid_size = 20

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor("#DCD7BD"), 0.5))

        left = int(rect.left()) - (int(rect.left()) % self.grid_size)
        top = int(rect.top()) - (int(rect.top()) % self.grid_size)

        for x in range(left, int(rect.right()), self.grid_size):
            for y in range(top, int(rect.bottom()), self.grid_size):
                painter.drawPoint(x, y)

    def wheelEvent(self, event):
        zoom_in_factor = 1.15
        zoom_out_factor = 1.0 / zoom_in_factor
        if event.angleDelta().y() > 0:
            self.scale(zoom_in_factor, zoom_in_factor)
        else:
            self.scale(zoom_out_factor, zoom_out_factor)

class ProteusVSMApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenVSM Studio - Virtual System Modelling [Python/FLOSS]")
        self.resize(1380, 880)

        # Engine Components
        self.mcu = VirtualMCU()
        self.worker = SimulationWorker(self.mcu)

        # UI Architecture
        self._init_canvas()
        self._init_docks()
        self._init_toolbars()
        self._connect_signals()

    def _init_canvas(self):
        self.scene = QGraphicsScene(-2000, -2000, 4000, 4000)
        self.view = SchematicView(self.scene, self)
        self.setCentralWidget(self.view)

        # Populate Default Schematic Circuit
        self.mcu_item = SchematicMCUItem("U1", "ATMEGA328P")
        self.mcu_item.setPos(100, 100)
        self.scene.addItem(self.mcu_item)

        self.meter_item = VirtualVoltmeterItem()
        self.meter_item.setPos(340, 70)
        self.scene.addItem(self.meter_item)

    def _init_docks(self):
        # 1. Output & Debug Log (Proteus bottom panel)
        self.log_dock = QDockWidget("Simulation Advisor / Log", self)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #1E1E1E; color: #D4D4D4; font-family: Consolas;")
        self.log_dock.setWidget(self.log_text)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)

        # 2. Virtual Terminal / Watch Window
        self.watch_dock = QDockWidget("Variables & Memory Watch", self)
        self.watch_view = QTextEdit()
        self.watch_view.setReadOnly(True)
        self.watch_view.setStyleSheet("background-color: #FAFAFA; font-family: Consolas;")
        self.watch_dock.setWidget(self.watch_view)
        self.addDockWidget(Qt.RightDockWidgetArea, self.watch_dock)

    def _init_toolbars(self):
        tb = QToolBar("Simulation Controls")
        self.addToolBar(Qt.TopToolBarArea, tb)

        self.btn_run = tb.addAction("▶ Run Simulation")
        self.btn_run.triggered.connect(self.start_sim)

        self.btn_stop = tb.addAction("⏹ Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.triggered.connect(self.stop_sim)

        tb.addSeparator()
        self.btn_inject_adc = tb.addAction("Toggle ADC0 (Analog In)")
        self.btn_inject_adc.triggered.connect(self.toggle_adc)
        self.adc_val = 0.0

    def _connect_signals(self):
        self.worker.state_updated.connect(self.on_state_update)
        self.worker.log_message.connect(self.log_text.append)

    def start_sim(self):
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.worker.start()

    def stop_sim(self):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.worker.stop()

    def toggle_adc(self):
        self.adc_val = 4.25 if self.adc_val == 0.0 else 0.0
        self.mcu.set_input_voltage("ADC0", self.adc_val)
        self.log_text.append(f"[Hardware Net] Injected {self.adc_val}V to Net 'ADC0'")

    def on_state_update(self, pin_states: Dict[str, PinState]):
        # Update Pin Squares
        for pin_id, state in pin_states.items():
            if pin_id in self.mcu_item.pins:
                self.mcu_item.pins[pin_id].state = state
                self.mcu_item.pins[pin_id].update()

        # Update Meter
        pb0_state = pin_states.get("PB0")
        if pb0_state:
            self.meter_item.voltage = pb0_state.voltage
            self.meter_item.update()

        # Update Watches
        txt = f"MCU Time Tick: {self.mcu.tick_counter}\n"
        for pin_id, state in pin_states.items():
            txt += f"{pin_id:6}: {state.voltage:4.2f} V  (Logic {state.logic_level})\n"
        self.watch_view.setPlainText(txt)

    def closeEvent(self, event):
        self.worker.stop()
        event.accept()

# ==============================================================================
# 4. ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ProteusVSMApp()
    window.show()
    sys.exit(app.exec())
