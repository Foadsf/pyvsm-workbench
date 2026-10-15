import json
import os
from typing import Dict, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGraphicsScene,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

try:
    from ..core.models import SourceInstruction
    from ..core.disjoint_set import DisjointSet
    from ..core.netlist_compiler import NetlistCompiler
    from ..core.spice_bridge import NgSpiceBridge
    from ..core.mcu.multi_mcu import MultiMCUBackend
    from ..core.co_simulation import LockstepWorker
    from ..core.kicad_importer import (
        KiCadSymbolImporter,
        SAMPLE_KICAD_SYM_S_EXPR,
        SAMPLE_SPICE_SUBCKT,
    )
except (ImportError, ValueError):
    from core.models import SourceInstruction
    from core.disjoint_set import DisjointSet
    from core.netlist_compiler import NetlistCompiler
    from core.spice_bridge import NgSpiceBridge
    from core.mcu.multi_mcu import MultiMCUBackend
    from core.co_simulation import LockstepWorker
    from core.kicad_importer import (
        KiCadSymbolImporter,
        SAMPLE_KICAD_SYM_S_EXPR,
        SAMPLE_SPICE_SUBCKT,
    )

from .pins import ProteusPinSquare
from .wires import SchematicWireItem
from .canvas import InteractiveSchematicCanvas
from .components.base import MovableSchematicNode
from .components.mcu_item import SchematicMCUItem
from .components.lcd_item import HD44780LCDItem
from .components.potentiometer_item import RotaryPotentiometerItem
from .components.button_item import InteractiveButtonItem
from .components.voltmeter_item import VirtualVoltmeterItem
from .components.seven_seg_item import SevenSegmentDisplayItem
from .components.frequency_meter_item import FrequencyMeterItem
from .components.i2c_analyzer_item import I2CProtocolAnalyserItem
from .components.kicad_symbol_item import CustomKiCadSymbolItem

from .instruments.oscilloscope import DigitalStorageOscilloscope
from .instruments.debugger import SourceDebuggerWidget
from .instruments.terminal import VirtualTerminalWidget

class OpenVSMStudio(QMainWindow):
    """
    OpenVSM Main Application Window.
    Implements a full 1:1 FLOSS desktop suite replicating Proteus ISIS Schematic Capture
    and Proteus VSM co-simulation with libngspice, libsimavr/libgpsim/Unicorn multi-MCU engines,
    Manhattan wire router, virtual instruments, and in-canvas source debugger.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle(
            "OpenVSM Studio — Open-Source Proteus VSM in Python [PySide6 / FLOSS]"
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

        # Connect peripheral callbacks
        self.mcu.lcd_bus_cb = self.lcd_item.process_bus
        self.mcu.i2c_pin_cb = self.i2c_item.sample_bus
        self.mcu.freq_edge_cb = self._on_freq_update
        self.mcu.reset()

        self.worker = LockstepWorker(self.spice, self.mcu, input_sync_cb=self._sync_mcu_inputs)
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

        # Top Toolbar
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
        act_load_hex = QAction("📂 Load Firmware (.hex / .elf)...", self)
        act_load_hex.triggered.connect(self.prompt_load_firmware)
        tb.addAction(act_load_hex)

        act_kicad = QAction("🧩 Import KiCad Symbol (.kicad_sym / Demo)", self)
        act_kicad.triggered.connect(self.import_kicad_symbol)
        tb.addAction(act_kicad)

        act_save = QAction("💾 Save Project JSON", self)
        act_save.triggered.connect(self.save_project_json)
        tb.addAction(act_save)

        act_load_proj = QAction("📂 Load Project JSON", self)
        act_load_proj.triggered.connect(self.load_project_json)
        tb.addAction(act_load_proj)

        # Left Dock: Proteus 'DEVICES' Bin
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

        # Right Dock: Tabbed Source Debugger + Virtual Instruments
        right_dock = QDockWidget("Source Debugger & Virtual Instruments", self)
        self.right_tabs = QTabWidget()

        self.debugger_widget = SourceDebuggerWidget(self.mcu, self)
        self.debugger_widget.step_into_requested.connect(self.step_single_instruction)
        self.debugger_widget.toggle_bp_requested.connect(self._on_toggle_bp)
        self.right_tabs.addTab(self.debugger_widget, "🐞 CPU Source & Variables")

        # Oscilloscope + UART + I2C Log Panel
        inst_panel = QWidget()
        inst_layout = QVBoxLayout(inst_panel)
        self.dso_widget = DigitalStorageOscilloscope(self)
        inst_layout.addWidget(QLabel("4-Channel Digital Storage Oscilloscope (DSO):"))
        inst_layout.addWidget(self.dso_widget)

        inst_layout.addWidget(QLabel("Virtual Terminal (UART):"))
        self.terminal_widget = VirtualTerminalWidget(self)
        self.terminal_widget.tx_key_pressed.connect(self._on_terminal_tx)
        inst_layout.addWidget(self.terminal_widget)

        # Backward compatibility aliases
        self.term_edit = self.terminal_widget.console
        self.uart_input = self.terminal_widget.input_line


        self.right_tabs.addTab(inst_panel, "📈 Oscilloscope & Protocol Console")
        right_dock.setWidget(self.right_tabs)
        self.addDockWidget(Qt.RightDockWidgetArea, right_dock)

        # Bottom Dock: Netlist & Co-Simulation Advisor
        bot_dock = QDockWidget("SPICE Netlist Compiler & Simulation Log", self)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(130)
        self.log_edit.setStyleSheet(
            "background-color: #1A1A1A; color: #CCCCCC; font-family: Consolas; font-size: 11px;"
        )
        bot_dock.setWidget(self.log_edit)
        self.addDockWidget(Qt.BottomDockWidgetArea, bot_dock)

        for msg in self.logs:
            self.log_edit.append(msg)
        self.logs.clear()

        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage(
            "Ready — Click any two pins to route wires, or press '▶ Run' to start co-simulation."
        )

    def _build_default_circuit(self):
        self.mcu_item = SchematicMCUItem("U1", "PIC18F452")
        self.mcu_item.ref_id = "U1"
        self.mcu_item.setPos(220, 40)
        self.scene.addItem(self.mcu_item)

        self.pot_item = RotaryPotentiometerItem(on_change=self.spice.set_potentiometer)
        self.pot_item.ref_id = "RV1"
        self.pot_item.setPos(20, 20)
        self.scene.addItem(self.pot_item)

        self.btn_item = InteractiveButtonItem("B2 (PB_2)", on_toggle=self.spice.set_button)
        self.btn_item.ref_id = "B2"
        self.btn_item.setPos(15, 175)
        self.scene.addItem(self.btn_item)

        self.lcd_item = HD44780LCDItem("LCD1 (LM016L - PICDEM 2 PLUS)")
        self.lcd_item.ref_id = "LCD1"
        self.lcd_item.setPos(500, 10)
        self.scene.addItem(self.lcd_item)

        self.freq_item = FrequencyMeterItem()
        self.freq_item.ref_id = "FREQ1"
        self.freq_item.setPos(500, 155)
        self.scene.addItem(self.freq_item)

        self.i2c_item = I2CProtocolAnalyserItem(log_packet_cb=self._on_i2c_packet)
        self.i2c_item.ref_id = "I2C1"
        self.i2c_item.setPos(500, 240)
        self.scene.addItem(self.i2c_item)

        self.voltmeter_item = VirtualVoltmeterItem("Filtered V_LOAD")
        self.voltmeter_item.ref_id = "VM1"
        self.voltmeter_item.setPos(745, 15)
        self.scene.addItem(self.voltmeter_item)

        self.seg_item = SevenSegmentDisplayItem()
        self.seg_item.ref_id = "SEG1"
        self.seg_item.setPos(735, 175)
        self.scene.addItem(self.seg_item)


        # Pre-route Manhattan orthogonal wires connecting the schematic
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

    def prompt_load_firmware(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select MCU Firmware Binary",
            "",
            "Firmware Files (*.hex *.elf);;All Files (*)",
        )
        if path:
            self.mcu.load_firmware_file(path)
            self._on_frame_tick()

    def import_kicad_symbol(self, use_builtin: bool = False):
        sexpr = SAMPLE_KICAD_SYM_S_EXPR
        if not use_builtin:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Import KiCad Symbol (.kicad_sym) or Cancel for Built-in LM358 Demo",
                "",
                "KiCad Symbol (*.kicad_sym);;All Files (*)",
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
        self._append_log(
            f"[KiCad Importer] Placed symbol '{sym_data['reference']} ({sym_data['value']})' & linked SPICE .subckt."
        )
        self._compile_netlist()

    def save_project_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save OpenVSM Project", "project_vsm.json", "JSON (*.json)"
        )
        if not path:
            return
        nodes = []
        comp_to_id = {}
        for it in self.scene.items():
            if isinstance(it, MovableSchematicNode):
                cid = getattr(it, "ref_id", None) or it.__class__.__name__
                comp_to_id[it] = cid
                nodes.append({
                    "id": cid,
                    "type": it.__class__.__name__,
                    "x": it.pos().x(),
                    "y": it.pos().y(),
                })
        wires_data = []
        for w in self.wires:
            if w.pin_start and w.pin_end:
                comp_s = w.pin_start.parentItem()
                comp_e = w.pin_end.parentItem()
                if comp_s in comp_to_id and comp_e in comp_to_id:
                    wires_data.append({
                        "start_comp": comp_to_id[comp_s],
                        "start_pin": w.pin_start.pin_name,
                        "end_comp": comp_to_id[comp_e],
                        "end_pin": w.pin_end.pin_name,
                    })
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "mcu": self.mcu.arch,
                "pot_ratio": self.spice.pot_ratio,
                "nodes": nodes,
                "wires": wires_data,
            }, f, indent=2)
        self._append_log(f"[Project Saved] Exported schematic layout and {len(wires_data)} wires to {path}")

    def load_project_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load OpenVSM Project", "", "JSON (*.json);;All Files (*)"
        )
        if not path or not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if self.worker.isRunning():
            self.pause_sim()

        if "mcu" in data:
            self._on_arch_changed(data["mcu"])
        if "pot_ratio" in data and hasattr(self, "pot_item"):
            self.pot_item.set_ratio(data["pot_ratio"])

        comp_map = {
            "U1": getattr(self, "mcu_item", None),
            "RV1": getattr(self, "pot_item", None),
            "B2": getattr(self, "btn_item", None),
            "LCD1": getattr(self, "lcd_item", None),
            "FREQ1": getattr(self, "freq_item", None),
            "I2C1": getattr(self, "i2c_item", None),
            "VM1": getattr(self, "voltmeter_item", None),
            "SEG1": getattr(self, "seg_item", None),
            "SchematicMCUItem": getattr(self, "mcu_item", None),
            "RotaryPotentiometerItem": getattr(self, "pot_item", None),
            "InteractiveButtonItem": getattr(self, "btn_item", None),
            "HD44780LCDItem": getattr(self, "lcd_item", None),
            "FrequencyMeterItem": getattr(self, "freq_item", None),
            "I2CProtocolAnalyserItem": getattr(self, "i2c_item", None),
            "VirtualVoltmeterItem": getattr(self, "voltmeter_item", None),
            "SevenSegmentDisplayItem": getattr(self, "seg_item", None),
        }

        for node in data.get("nodes", []):
            cid = node.get("id") or node.get("type")
            comp = comp_map.get(cid)
            if comp and "x" in node and "y" in node:
                comp.setPos(node["x"], node["y"])

        if "wires" in data:
            for w in list(self.wires):
                self.canvas._remove_wire(w)
            self.wires.clear()
            for wdata in data["wires"]:
                s_comp = comp_map.get(wdata.get("start_comp"))
                e_comp = comp_map.get(wdata.get("end_comp"))
                if s_comp and e_comp:
                    p_start = s_comp.pins.get(wdata.get("start_pin"))
                    p_end = e_comp.pins.get(wdata.get("end_pin"))
                    if p_start and p_end:
                        wire = SchematicWireItem(p_start, p_end)
                        self.scene.addItem(wire)
                        self.wires.append(wire)

        self._compile_netlist()
        self._on_frame_tick()
        self._append_log(f"[Project Loaded] Restored schematic layout and {len(self.wires)} wires from {path}")

    def _pins_connected(self, pin_a: Optional[ProteusPinSquare], pin_b: Optional[ProteusPinSquare]) -> bool:
        """Returns True only if a wire path connects pin_a and pin_b on the schematic."""
        if pin_a is None or pin_b is None:
            return False
        visited = set()
        queue = [pin_a]
        while queue:
            cur = queue.pop(0)
            if cur is pin_b:
                return True
            visited.add(cur)
            for w in cur.connected_wires:
                other = w.pin_end if w.pin_start is cur else w.pin_start
                if other and other not in visited:
                    queue.append(other)
        return False

    def _sync_mcu_inputs(self):
        if hasattr(self, "pot_item") and hasattr(self, "mcu_item"):
            if self._pins_connected(self.pot_item.pins.get("WIPER"), self.mcu_item.pins.get("ADC0")):
                self.mcu.pins["ADC0"] = self.spice.node_voltages.get("adc0", 2.50)
            else:
                self.mcu.pins["ADC0"] = 0.0

        if hasattr(self, "btn_item") and hasattr(self, "mcu_item"):
            if self._pins_connected(self.btn_item.pins.get("OUT"), self.mcu_item.pins.get("PB2")):
                self.mcu.pins["PB2"] = self.spice.node_voltages.get("pb2", 5.0)
            else:
                self.mcu.pins["PB2"] = 5.0

    def _on_arch_changed(self, text: str):
        arch_code = text.split()[0]
        self.mcu.set_architecture(arch_code)
        self.mcu_item.model = arch_code
        self.mcu_item.update()
        self.debugger_widget.refresh_debugger()

    def _on_freq_update(self, pb0_v: float, freq_hz: float):
        self.freq_item.freq_hz = freq_hz

    def _on_i2c_packet(self, summary: str):
        self.terminal_widget.console.append(summary)

    def _on_uart_byte(self, b: int):
        self.terminal_widget.append_serial_byte(b)

    def _on_terminal_tx(self, txt: str):
        for b in txt.encode("ascii", errors="ignore"):
            self.mcu.rx_fifo.append(b)

    def _send_uart(self):
        txt = self.uart_input.text()
        if txt:
            self._on_terminal_tx(txt)
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
        self._sync_mcu_inputs()
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
        # 1. Check live schematic connectivity before feeding SPICE nodes into MCU
        self._sync_mcu_inputs()

        # 2. Update MCU Pin Squares
        for pname, pin_sq in self.mcu_item.pins.items():
            pin_sq.voltage = self.mcu.pins.get(pname, 0.0)
            pin_sq.update()

        # 3. Propagate voltages across wires to connected peripheral pins
        for wire in self.wires:
            wire.voltage = wire.pin_start.voltage
            if wire.pin_end:
                wire.pin_end.voltage = wire.voltage
                wire.pin_end.update()
            wire.update()

        # 4. Update Peripherals based on live wire connections
        if not self._pins_connected(self.mcu_item.pins.get("PB0"), self.freq_item.pins.get("CLK")):
            self.freq_item.freq_hz = 0.0

        self.lcd_item.update()
        self.freq_item.update()
        self.i2c_item.update()

        self.voltmeter_item.voltage = self.spice.node_voltages.get("v_load", 0.0)
        self.voltmeter_item.pins["V+"].voltage = self.voltmeter_item.voltage
        self.voltmeter_item.update()

        self.seg_item.value_str = f"{self.mcu.bcd_counter:04d}"
        self.seg_item.update()

        # 5. Push samples to 4-Channel DSO Scope
        self.dso_widget.push_samples(
            self.mcu.pins.get("ADC0", 0.0),
            self.mcu.pins.get("PB0", 0.0),
            self.spice.node_voltages.get("v_load", 0.0),
            self.mcu.pins.get("SCL", 5.0),
        )

        # 6. Refresh Debugger Table
        self.debugger_widget.refresh_debugger()

    def closeEvent(self, event):
        self.worker.stop()
        event.accept()

