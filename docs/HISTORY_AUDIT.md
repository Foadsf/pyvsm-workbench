# Prototype claims and history audit

Scope: Windows host measurements on 2026-10-14. VSM simulation only; PCB layout, footprints and fabrication are excluded. Historical evidence is retained; unsupported claims below refer to the old demonstration, not the new runtime.

## Responsible Antigravity instances

The running Antigravity manager was inspected with `agyui.py status`, `sidebar`, `open` and `read`. The selected conversation was restored afterward. No prompts were sent.

- `61c03f77-a702-4227-8250-444fe43dc810`: **Open-Source Proteus VSM Implementation**, workspace Proteus_Python. Local summary database: 386 steps, idle, last modified 2026-10-14 07:36:27 UTC.
- `bc2d5035-fcad-4f27-8ed0-5d207b354791`: **Python Proteus VSM Replica Implementation**, workspace VSM_Python. Local summary database: 126 steps, idle, last modified 2026-10-14 10:33:37 UTC.

Raw local exports are under `_local/history/` (gitignored). The GUI read for the second chat initially exposed only the final 525 characters, including `Individual quota reached`; it was not a complete history. The local full-text index supplied seven chunks, covering OpenVSM steps 0-385 and PyVSM steps 0-118. Coverage after PyVSM step 118 is NOT VERIFIED. These stores were searched only for these two identified conversations. The extracted agent claims are in `docs/antigravity-claims.txt`.

`docs/antigravity-claims.txt:4` says `implemented the complete open-source Proteus VSM suite`. `:26` promises `execute instructions cycle-by-cycle`. The second chat later explicitly admits that the microcontroller is a hard-coded script and the external tools are not connected. Its modular implementation then stopped during a quota limit, leaving an unfinished but useful editor/engine package.

## Observed claims versus behavior

| Claim | Measurement / source evidence | Verdict |
|---|---|---|
| General topology-driven SPICE extraction | `core/netlist_compiler.py:39`: `"V_VCC vcc 0 DC 5.0"`; :40 and :44 construct a fixed divider and RC load. Connecting previously separate pins changes the pin map but produces exactly the same SPICE deck. | FAIL for general circuit extraction; union-find bookkeeping alone is insufficient. |
| General MNA transient solver | `core/spice_bridge.py:183`: `v_vcc = 5.0`; :191: `tau = 470.0 * 10e-6`. Loading a 12 V circuit does not produce its custom node. | FAIL; this is a useful fixed-circuit calculation, not general MNA. |
| Cycle-accurate multi-MCU firmware execution | `core/mcu/multi_mcu.py:232`: `self.pc_index = (self.pc_index + 1) % len(self.listing)`; :239: `self.cycle_count += int(self.clock_hz * dt)`. Output generation is Python logic, not opcode execution. The native AVR run condition uses `"AVR" in self.arch.upper()` even though the selectable architecture is `ATMEGA328P`. | FAIL for real PIC18/AVR/ARM execution. A library probe is not a bound firmware emulator. |
| Loaded HEX is validated firmware | `core/mcu/firmware.py:44-47` reads record fields without checksum verification. Deliberately corrupt record `:0100000000FE` is accepted as one data byte. | FAIL; malformed firmware is accepted. |
| Source debugger | Hand-authored C-source strings and partial disassembly are displayed beside synthetic PC progress; ELF/DWARF source binding is NOT FOUND in the inspected original MCU loader. | NOT VERIFIED for source debugging; listing navigation/breakpoint UI is real. |
| Instruments prove simulated hardware | Frequency, LCD, I2C and UART callbacks originate in Python demo logic; I2C frame generation is `MultiMCUBackend._enqueue_i2c_eeprom_frame`. | Display widgets are useful; real firmware/peripheral coupling is NOT VERIFIED. |
| Arbitrary project persistence | `ui/main_window.py:417` loads through a fixed component map instead of reconstructing arbitrary placed components. | PARTIAL; default-demo layout restoration is not general project loading. |
| All tests green means all claimed subsystems work | `python -m unittest discover -v`: 10 tests pass, while the graph/deck and malformed-HEX controls above still fail. | FAIL as a completion gate. The test result is real but supports a narrower claim. |

Raw measurements: `docs/evidence/prototype-audit.txt`. The check reports measurement separately from verdict. This is evidence of overstated completion and weak verification, including a false-green/reward-hacking pattern; it does not establish the agents' intent.

## Inputs reviewed and preserved

Both supplied Markdown blueprints were read selectively as conversation/code proposals, not executable acceptance evidence. The later `Gemini_MVP_Prompt.md` supplied the modular editor/real-ngspice scope and explicitly excluded PCB work. The PDFs were converted locally: `vsmtut.pdf` 52 pages, 97.8% text coverage; `exp-6.pdf` 10 pages, 89.9%; `PROTEUS-d.pdf` 26 pages, initial 40.3% extraction recovered to 18,833 characters through PyMuPDF. The extracted documents and a reference-page render were kept under `docs/` in the local research copy; they are third-party material and are not distributed.

Installed example inspected and copied before the backend extension: Windows-only `C:\Program Files\Qucs-S\share\qucs-s\examples\templates_ngspice\genericopa.cir` -> `docs/prior-art/qucs-genericopa.cir`. This is a shipped op-amp example, retained as prior art; it is not silently substituted for the MVP's approximate behavioral model. Its model attribution is in its header; license in that individual file is NOT STATED. The engine regression's separate RC case is a local qualification fixture, labelled accordingly.

## What remains unverified

Pixel-identical Proteus appearance, arbitrary MCU family support, full source-level debugging, universal peripheral libraries, real-time/cycle lockstep for every MCU, nonlinear device state preservation across interactive SPICE slices, and commercial Proteus file compatibility. New backend acceptance reports state the narrower measured capabilities. Physical hardware agreement has not been tested.
