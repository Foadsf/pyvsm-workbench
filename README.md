# pyvsm-workbench

Companion repository to [PyVSM](https://github.com/Foadsf/pyvsm): its launcher, the historical prototype, the specification and history audit, and the page-cited source mapping of the tutorial-derived demo circuits. It was developed locally under the name OpenVSM, which still appears in older documents and file names.

Run `python main.py` from this directory. It launches the modular MVP (the PyVSM package) from a `pyvsm` clone beside this folder, from the original local `VSM_Python/pyvsm_replica` layout, or from an installed `pyvsm` package. The MVP package also runs independently with `python -m pyvsm`.

The scope is VSM circuit simulation and schematic capture. PCB layout and fabrication are excluded.

The MVP offers a Proteus-style light schematic workspace, editable components and wires, undo/redo, JSON projects, graph probes and real ngspice DC/transient results. Firmware workbenches use actual external backends and identify their supported targets and limits. See the sibling package README for backend requirements and commands.

For integrated firmware circuits, choose **Demos > PIC12F629 firmware + LED** (or ATmega328P / PIC18F452), then **Run / F12**. These are editable circuits executing real firmware. AVR/PIC18 electrical feedback is sampled, normally every 1 ms; PIC12 uses native XSPICE co-simulation. The sibling package's `docs/SCHEMATIC_ACCEPTANCE.md` records the tests and limits.

Six exercises adapted from three tutorial PDFs (not included here) are under **Demos > PDF: ...**: the exp-6 generator + oscilloscope, 555 astable and 0-99 counter, the PROTEUS-d bridge rectifier and PIC16F84A LED blinker (an original program with the PDF exercise's timing), and the vsmtut 741 amplifier. `docs/mwe-sources/SOURCE-MAPPING.md` maps each to its pages; the MVP package's `docs/PDF_MWE_ADAPTATIONS.md` records chosen values and measurements.

The original scripts and `core/` / `ui/` demonstration remain available with `python main.py --prototype`. They contain scripted behavior and are not general firmware/circuit simulators. The previous README is preserved in `docs/PROTOTYPE_README.md` as historical evidence.

Read `docs/HISTORY_AUDIT.md` for the Antigravity history and unsupported claims. Read the MVP package's `docs/ENGINE_AUDIT.md`, `docs/UI_ACCEPTANCE.md` and firmware reports for measurements and controls.

## License

Copyright (C) 2026 Foad S. Farimani.

pyvsm-workbench is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see [LICENSE](LICENSE) for the full text.

Proteus and VSM are trademarks of Labcenter Electronics Ltd. This is an independent project, not affiliated with or endorsed by Labcenter, and it contains no Labcenter software, libraries or documentation.
