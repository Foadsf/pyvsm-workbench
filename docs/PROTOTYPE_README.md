> Historical Antigravity prototype README. Its broad capability claims are audited in HISTORY_AUDIT.md and are not the current MVP contract.

# OpenVSM: Open-Source Virtual System Modelling (Proteus VSM Alternative) in Python

OpenVSM is an open-source, hardware-agnostic desktop co-simulation suite replicating the features, workflows, and visual aesthetics of **Proteus ISIS Schematic Capture** and **Proteus VSM (Virtual System Modelling)** using modern Python 3 and FLOSS components.

---

## 🏛 Architecture Overview

```
+--------------------------------------------------------------------------------------------------+
|                                    OpenVSM Studio (PySide6)                                      |
|  +--------------+  +--------------------------------------------------+  +--------------------+  |
|  | DEVICES Bin  |  |  Interactive ISIS Schematic Canvas               |  | Floating / Docked  |  |
|  | - PIC18F452  |  |  - Manhattan Orthogonal Wire Router (Red/Blue)   |  | Instruments:       |  |
|  | - ATMEGA328P |  |  - HD44780 LCD, POT-HG, Pushbutton, 7-Seg        |  | - 4-Ch DSO Scope   |  |
|  | - 24LC256    |  |  - Frequency Meter (8-Digit) & DC Voltmeter      |  | - Source Debugger  |  |
|  | - LM016L LCD |  |  - I2C Protocol Analyser (SDA/SCL State Machine) |  | - CPU Variables    |  |
|  | - KiCad Sym  |  +--------------------------------------------------+  | - UART Terminal    |  |
|  +--------------+                            │                           +--------------------+  |
+----------------------------------------------│---------------------------------------------------+
                                               ▼
+--------------------------------------------------------------------------------------------------+
|                    Graph-to-SPICE Netlist Compiler (Union-Find Node Extractor)                   |
+--------------------------------------------------------------------------------------------------+
                       │                                               │
                       ▼                                               ▼
+---------------------------------------------+ +--------------------------------------------------+
|         Analog / Mixed-Signal Core          | |      Hardware-Agnostic Multi-MCU Subsystem       |
| - libngspice C-FFI (circbyline / alter)     | | - Microchip PIC18F452 (libgpsim C-FFI / Core)    |
| - Subcircuit (.subckt) & MNA Transient Core | | - Atmel AVR ATmega328P (libsimavr C-FFI / Core)  |
| - Dynamic RC, Divider & Switch Modeling     | | - ARM Cortex-M3 STM32 (Unicorn / Thumb-2 Core)   |
+---------------------------------------------+ +--------------------------------------------------+
```

---

## 🚀 Key Features

1. **Interactive ISIS Schematic Capture & Orthogonal Router:**
   * Click any two component pin terminals (`ProteusPinSquare`) to route Manhattan orthogonal wires with 90-degree corners.
   * Moving components automatically updates attached wire geometries.
   * Real-time logic-level wire coloring: Red (Logic HIGH $\ge 2.5\text{V}$), Blue (Logic LOW $\le 0.5\text{V}$), Green (Analog / intermediate voltage), Grey (Hi-Z).

2. **Graph-to-SPICE Dynamic Netlist Compiler:**
   * Utilizes a Union-Find (`DisjointSet`) algorithm to extract electrical connectivity graphs across pins and wires.
   * Compiles dynamic SPICE decks (`circbyline`) loaded into the analog simulation engine upon running.

3. **High-Precision SPICE Mixed-Mode Engine:**
   * Dynamic C-FFI bindings to native `libngspice` (`ngspice.dll` / `libngspice.so` / `libngspice.dylib`).
   * Built-in deterministic Modified Nodal Analysis (MNA) transient solver fallback for out-of-the-box cross-platform operation.
   * Supports runtime parameter alteration (`alter`) for potentiometers, switches, and sources.

4. **Hardware-Agnostic Multi-Architecture MCU Engine:**
   * Supports **Microchip PIC18F452** (40 MHz), **Atmel AVR ATmega328P** (16 MHz), and **ARM Cortex-M3 STM32F103** (72 MHz).
   * Native C-FFI probing for `libgpsim` and `libsimavr`.
   * Built-in cycle-accurate instruction stepper, Intel HEX parser, and SRAM/SFR symbol watch.

5. **In-Canvas Source-Level & Disassembly Debugger:**
   * Replicates Proteus `CPU Source Code - U1` and `CPU Variables - U1`.
   * Side-by-side assembly disassembly and C source listing with program counter (`➡`) indicator.
   * Interactive breakpoint toggling (`🔴`) and single-step instruction execution (`F11`).

6. **Proteus Virtual Instruments:**
   * **4-Channel Digital Storage Oscilloscope (DSO):** Phosphor CRT aesthetic, dot graticule grid, and multi-channel trace overlay (`V(adc0)`, `V(v_load)`, `V(pb0)`, and `I2C SCL`).
   * **I2C Protocol Analyser:** Live state machine decoding `START [S]`, 7-bit slave address, `ACK/NAK`, data payload, and `STOP [P]` for EEPROMs (such as 24LC256).
   * **8-Digit Frequency Meter:** Counts edge transitions and measures live clock/PWM frequency on `PB0`.
   * **Virtual Terminal:** ANSI UART console with interactive character transmission and telemetry output.
   * **HD44780 Alphanumeric LCD (LM016L):** 4-bit nibble state machine, 80-byte DDRAM, and 16x2 backlit character matrix.
   * **POT-HG 10k Rotary Potentiometer:** Interactive mouse wheel and `+`/`-` buttons adjusting analog divider voltages.
   * **Interactive Pushbutton (`PB_2`):** Momentary/toggle mechanical contacts with pull-up resistor.
   * **Analog DC Voltmeter & 4-Digit 7-Segment LED Display.**

7. **KiCad Symbol & SPICE Subcircuit Importer:**
   * Parses KiCad v6+ `.kicad_sym` S-expressions directly into schematic symbols.
   * Binds SPICE `.subckt` definitions into the active circuit deck.

---

## 📁 Directory Structure

```
OpenVSM/
├── core/
│   ├── models.py             # Data classes, C structs, callback prototypes
│   ├── disjoint_set.py       # Union-Find netlist extraction algorithm
│   ├── netlist_compiler.py   # Schematic graph-to-SPICE netlist compiler
│   ├── spice_bridge.py       # libngspice C-FFI & MNA transient solver
│   ├── co_simulation.py      # Lockstep co-simulation QThread worker
│   ├── kicad_importer.py     # KiCad S-expression symbol & .subckt parser
│   └── mcu/
│       ├── multi_mcu.py      # Multi-MCU hardware-agnostic backend
│       └── firmware.py       # Intel HEX parser and demo firmware listings
├── ui/
│   ├── canvas.py             # InteractiveSchematicCanvas (grid, zoom/pan, routing)
│   ├── pins.py               # ProteusPinSquare interactive pin terminal
│   ├── wires.py              # SchematicWireItem orthogonal Manhattan wire
│   ├── components/           # Schematic component visual items
│   │   ├── base.py           # MovableSchematicNode
│   │   ├── mcu_item.py       # SchematicMCUItem (PIC18F452 / ATmega328P)
│   │   ├── lcd_item.py       # HD44780LCDItem (16x2 backlit LCD)
│   │   ├── potentiometer_item.py # RotaryPotentiometerItem (POT-HG)
│   │   ├── button_item.py    # InteractiveButtonItem (PB_2)
│   │   ├── voltmeter_item.py # VirtualVoltmeterItem (DC Volts)
│   │   ├── seven_seg_item.py # SevenSegmentDisplayItem (BCD)
│   │   ├── frequency_meter_item.py # FrequencyMeterItem (8-digit)
│   │   ├── i2c_analyzer_item.py    # I2CProtocolAnalyserItem
│   │   └── kicad_symbol_item.py    # CustomKiCadSymbolItem
│   ├── instruments/          # Dockable virtual instruments
│   │   ├── oscilloscope.py   # DigitalStorageOscilloscope (4-Ch DSO)
│   │   ├── debugger.py       # SourceDebuggerWidget (Disasm, C source, SFRs)
│   │   └── terminal.py       # VirtualTerminalWidget (UART Console)
│   └── main_window.py        # OpenVSMStudio main window
├── tests/
│   ├── test_openvsm.py       # Core unit tests (DisjointSet, MNA, MCU, KiCad)
│   └── test_gui.py           # Headless GUI automated tests
├── main.py                   # Main studio entry point
├── openvsm_suite.py          # Complete standalone monolithic suite
├── openvsm_canonical.py      # Canonical 3-stage co-simulation script
├── proteus_vsm_core.py       # Proof-of-concept initial prototype
└── requirements.txt          # Python dependencies
```

---

## ⚡ Quick Start

### Installation

```bash
pip install -r requirements.txt
```

*(PySide6 and numpy are required. Native libraries `libngspice`, `libsimavr`, `libgpsim` are detected automatically if installed on the host system).*

### Running OpenVSM Studio

To launch the full modular desktop environment:
```bash
python main.py
```

Or run any of the standalone canonical scripts:
```bash
python openvsm_suite.py
python openvsm_canonical.py
python proteus_vsm_core.py
```

### Running Test Suite

```bash
python -m unittest discover -s tests -v
```
