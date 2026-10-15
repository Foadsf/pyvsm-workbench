# Six PDF-derived MWE source mappings

Sections 1-3 were written by Codex on 15 Oct 2026; sections 4-6 were added afterwards by Claude Code. Implementations and measurements are in the sibling `VSM_Python/pyvsm_replica/docs/PDF_MWE_ADAPTATIONS.md`.

All page numbers below are **physical PDF pages, counted from 1**. Read-only source review; no simulator run or app implementation was performed. Local text extractions were reused. Circuit connections and screenshots were checked against locally rendered PDF pages. The PDFs, their text extractions and the page renders are third-party material and are not part of this repository; every claim below cites a physical page instead.

## 1. exp-6.pdf: Example 2, 555 astable

Source: physical p9 (also printed p9), lower circuit. Exact title: "Example 2: Simulation of astable operation of a 555 timer."

Exact visible circuit:

- U1 = 555. Pin 8 VCC and pin 4 RESET tied to the positive power net; pin 1 to ground; pin 5 CV left open.
- R1 = 39k from VCC to pin 7 DISCHARGE. R2 = 68k from pin 7 to timing node T. C1 = 10u from T to ground. Pins 2 TRIGGER and 6 THRESHOLD both connect to T.
- Pin 3 OUTPUT = OUT. R3 = 220R from VCC to D1 anode; D1 cathode to OUT. R4 = 220R from OUT to D2 anode; D2 cathode to ground. Both D1 and D2 explicitly have the model label `LED-BIBY` (retain it in provenance; ordinary single-color LED substitution is an adaptation).
- J1 = CONN-H2: pin 1 VCC, pin 2 ground. This is a supply connector, not a stated voltage source.

Source-stated expected behavior: astable operation. Supply voltage, numerical frequency, duty cycle, and LED optical/color model parameters: **NOT FOUND on p9 or in the extracted example text**.

Independent checks (predictions, not measured results): ideal steady-state threshold crossings at VCC/3 and 2VCC/3; high time ln(2)*(39k+68k)*10u = 0.7417 s; low time ln(2)*68k*10u = 0.4713 s; period 1.2130 s; frequency 0.8244 Hz; high duty 61.14%. Startup need not have the steady-state first interval. D2 conducts predominantly while OUT high, D1 while OUT low. A 5 V supply would be an explicit implementation choice, not a PDF value. Capture T and OUT over >=6 s, and measure periods after startup. Negative controls: hold RESET low (oscillation must stop), or double C1 (steady-state period must double).

Measurement: inspected the full rendered p9 and its extracted text. Verdict: topology and passive values recoverable; exact original supply and LED model behavior unresolved.

## 2. PROTEUS-d.pdf: Diodes and Rectification (7), bridge + smoothing capacitor

Source: physical pp5-8, figures 08-17 (p5, p6 with a detail crop of its dialog, and p8 were rendered and inspected). This preserves the tutorial's actual bridge-rectifier exercise and capacitor modification.

Exact visible circuit, p5 figure 08:

- AC2 above AC1 in a series stack. AC2 upper terminal is bridge AC_TOP; its lower terminal joins grounded center node MID. AC1 upper terminal joins MID; its lower terminal is bridge AC_BOTTOM. Both source symbols display value `12`.
- D1 anode AC_TOP, cathode DC_PLUS; D2 anode AC_BOTTOM, cathode DC_PLUS; D4 anode DC_MINUS, cathode AC_TOP; D3 anode DC_MINUS, cathode AC_BOTTOM. Labels are generic `DIODE`; semiconductor part/model is not specified.
- Ammeter AM1 in series from DC_PLUS to lamp upper terminal. Lamp lower terminal returns to DC_MINUS. VM1 across lamp, positive lead on upper terminal.
- IMPORTANT: DC_MINUS is **not** grounded. MID is grounded. Do not collapse these two nets.
- P6 figure 09 AC2 edit dialog has component value `12`, **Amplitude `6V`**, Frequency `0.2`. This is legible in the detailed render. The adjacent Russian instruction says to set Frequency to **50** and change the second generator too. Do not interpret the displayed component value `12` as a demonstrated 12 V peak amplitude.
- P8 figure 14 initially shows C1 = 1000u while placing it. The later p8 instruction explicitly says to change capacitance to **500 uF**, with capacitor upper plate on rectified positive rail and lower plate on return. It then says to change **both generators back to 0.2 Hz** to see charging/discharging slowly.

Source-stated behavior, exact English caption embedded in p5 figure08: "In this circuit a diode bridge is used to produce a full wave rectified output." Following sentence states that current flows in both halves of the AC cycle. P8 Russian text states that visible plate charges indicate capacitor charge and that the slow simulation displays capacitor charge/discharge dynamics.

Unspecified: lamp rating/model, AC1 amplitude dialog, source phase convention, diode model, initial capacitor condition. P5 screenshot displays approximately +10.0 V and +417 mA at one instant; this is not an average or RMS specification. Their ratio is about 24 ohm, but a fixed 24 ohm resistor is an **inferred load substitution**, not a source-stated lamp parameter. Likewise using 6 V peak on both generators is a symmetry inference from the explicitly shown AC2 dialog.

Independent checks (predictions): with same-phase 6 V sine sources oriented as above, AC_TOP minus AC_BOTTOM has 12 V peak. V(DC_PLUS, DC_MINUS) should remain nonnegative with two charging peaks per input cycle: 100 Hz at 50 Hz input; 0.4 Hz at the final 0.2 Hz setting. Peaks approach 12 V minus two diode drops, subject to load. With C1=500u, ripple should decrease relative to the same circuit with C1 removed, and increase when load current increases. Use differential output voltage, not just voltage to ground. Negative control: open one bridge diode; one charging half-cycle must be lost. Do not require the snapshot readings with a substituted load/model.

Measurement: inspected p5 bridge, p6 source dialog, p8 capacitor instructions. Verdict: meaningful bridge/filter topology and parameter-edit sequence recoverable; exact lamp/model reproduction unresolved. A resistor load implementation must be labeled as an adaptation.

## 3. vsmtut.pdf: Graph Based Tutorial, single-supply 741 audio amplifier

Source: physical pp40-51 (printed pp36-47). Main circuit description p40; generator p42; run window p45; gain/fall-time p47; frequency response p49. Pages 40, 41, 42, 46 and 47 were rendered and inspected.

Source-stated design, p40: "running from a single 5 volt supply." It names U1=741, feedback resistors R3/R4 for gain about 10, and bias R1/R2/C1 for false ground at non-inverting input. P50 (the swept-resistor and noise-analysis steps) establishes **R1=R2=470k** in the intended amplifier. The generator high voltage is **10mV** (p42); source claims output step a little above **100mV** and fall time a little under **10us** (p47), feedback-current step **10uA** (p48), passband gain just over **20dB** and usable frequency range approximately **50Hz-20kHz** (p49).

**Material source inconsistency: do not call an invented complete circuit an exact reproduction.** The p41 image is captioned "A Screenshot if a section from the ISISTUT.DSN" and actually shows a **different circuit fragment**: U1 741, +12 V pin7, -12 V pin4, DAC1 into pin3, DAC2 into pin2, R1=1k feedback OUT to pin2, R2=1k pin3 to ground, R3=56k leaving OUT toward a cropped region. This is not the single-5-V R1/R2/C1 amplifier described on p40. It is visibly cropped and cannot provide the missing intended wiring.

Second inconsistency: p42 says pulse width **0.5s**, whereas p45 discusses about **10kHz**, **100us** total period and stop time **100us**; p47 places low/high measurements at 20-30us and 70-80us. Do not silently use 0.5s and claim the 100us graph verified those edges. A 50us pulse width / 100us period is an explicit correction inferred from intended timing.

Exact R3/R4 values, C1 value, full bias/feedback connections, input edge rates, and intended source delay: **NOT FOUND in physical pp40-51 text and rendered circuit fragments**. The referenced canonical design files are `Samples/Tutorials/ASIMTUT1.DSN` and `ASIMTUT2.DSN`; these PDFs do not include those files.

Recommended MWE scope: preserve the intended biased single-supply 741 pulse amplifier and explicitly document recovered vs chosen component values and timing. Retrieve the installed ASIMTUT design if available before claiming exact reconstruction. A generic ideal/behavioral opamp may demonstrate bias and gain, but cannot establish the PDF's 741 fall time, bandwidth, noise, or input-bias-current effects. The p41 +/-12 V fragment is not a valid substitute for the p40 intended example.

Independent checks for an explicitly completed adaptation: non-inverting DC bias near midrail; approximately 10mV input step and approximately 100mV output step without rail clipping; measured closed-loop gain consistent with chosen feedback ratio; no DC saturation. Negative control: set input pulse amplitude to zero (pulse response disappears), or change feedback ratio (gain changes quantitatively). Use separate device-fidelity checks for fall time and frequency response; do not mark those passed with an ideal amplifier.

Measurement: text search and visual inspection establish contradictory schematic and timing. Verdict: tutorial intent and observable targets recoverable, **exact working circuit NOT PROVEN from this PDF alone**.

## 4. exp-6.pdf: Example 1, function generator and oscilloscope

Source: physical p9 (printed p9), upper circuit, rendered by reading the PDF page directly. Exact title: "Example 1: Use of function generator and oscilloscope."

Exact visible circuit: a Proteus SIGNAL GENERATOR whose + output drives R1 = 10k; R1's far end is the tap; R2 = 2k from the tap to ground; generator − output to ground. OSCILLOSCOPE channel A wired to the generator + output, channel B to the tap; C and D unused. The generator's waveform, amplitude and frequency, and the scope settings: **NOT FOUND** (the scope icon's colored traces are the instrument symbol, not a capture).

Independent prediction: B = A × 2k/(10k + 2k) = A/6 at every instant, same frequency. Negative control: change R2 (10k gives B/A = 1/2).

## 5. PROTEUS-d.pdf: PIC16F84A LED (figure 20, LED.asm)

Source: physical pp10-14. P10 figure 20 schematic; p11 component edits (R1 = R2 = 1k, digital model type); pp12-13 the `LED.asm` listing; p13 "PROCESSOR CLOCK FREQUENCY ... 4 МГц" and "Замигал светодиод?" (did the LED blink?); p14 debugger screenshot.

Exact visible circuit: U1 PIC16F84A; RB0/INT → R2 1k → D1 LED-RED → ground; RB1 → R1 1k → push-button → ground. VDD/VSS, MCLR and oscillator pins are not drawn (Proteus hides power pins). Firmware: `list p=16f84`, `#include <p16F84A.inc>`, `__CONFIG _CP_OFF & _WDT_OFF & _PWRTE_ON & _HS_OSC`; LED = PORTB,0; DelayL/M/H at 0x0C/0x0D/0x0E; set LED, call Delay500, clear LED, call Delay500, loop. Delay500 loads DelayH = 3 with DelayL = DelayM = 0 (256 counts each). Note the p14 screenshot shows `equ 0x20/0x21/0x22` and opcodes `01A0...` for the same lines: the screenshot was taken from a variant of the listing; the printed text (0x0C...) is used.

Supply voltage: **NOT FOUND** (implementation uses 5 V). Independent prediction: Delay500 ≈ 3 × 256 × (256 × 3 + 3) cycles ≈ 592 k instruction cycles = 0.592 s at 4 MHz, so RB0 toggles every ≈ 0.59 s despite the routine's name. gpasm reproduces config word 0x3FF2, matching the p14 screenshot. Negative controls: rebuild with DelayH = 1 (period ÷ 3); cut the RB0 wire (LED dark, RB0 still toggles).

## 6. exp-6.pdf: Example 3, 0-99 counter

Source: physical p10 (printed p10), rendered at 200 dpi and inspected at 400 dpi. Exact title: "Example 3: 0-99 Counter." The page has the schematic only; there is no prose.

Exact visible circuit:

- U1 = 4518 dual BCD counter, drawn as U1:A (pins 1 CLK, 2 E, 7 MR, 3-6 Q0-Q3) and U1:B (9 CLK, 10 E, 15 MR, 11-14 Q0-Q3). Power pins hidden.
- U1:A CLK from a DCLOCK generator terminal labelled `U1:A(CLK)` (square-wave icon). No frequency is shown.
- A DC generator terminal `R2(1)` (dashed DC icon) feeds both E pins and the top of R2 = 1k. Its voltage is not shown.
- Both MR pins (7 and 15) join and go to ground. **MR is not driven by Q1**: there is no reset network.
- Q1 = 2N2222A, emitter grounded. R1 = 1k from U1:A Q3 (the same net as U2's D input, junction dot) to Q1's base. Q1's collector joins R2's lower end and U1:B CLK. Q1 is therefore an inverting carry: when the units fall from 9 to 0, Q3 falls, Q1 turns off and the tens CLK rises.
- U2 = 7448 decodes U1:A (A..D = pins 7, 1, 2, 6) and drives the right-hand display; U4 = 7448 decodes U1:B and drives the left-hand display. QA..QG (pins 13, 12, 11, 10, 9, 15, 14) go to the display segment pins in order. BI/RBO (4), RBI (5) and LT (3) have stub leads only (unconnected; TTL inputs float high).
- Two 7-segment displays; each has one lower terminal to ground (common cathode). No decimal point pin is drawn.

Source-stated behaviour: the title only (counts 0 to 99). Clock frequency, supply voltage, display type and 7448 control-pin intent: **NOT FOUND**; the open control pins and the grounded common terminals imply normal (unblanked) decoding into common-cathode displays.

Independent predictions: with E high and MR low, the units advance on each rising clock edge; the tens advance once per 10 clocks, when the units go 9 → 0; the displays wrap 99 → 00 on the 100th edge. The 7448 shows 6 without the top bar and 9 without the bottom bar. Negative controls: change the clock frequency (wrap time scales as 1/f); cut the Q1-collector-to-U1:B-CLK wire (the tens stay 0 and the units repeat 0-9); ground a 7448 LT (that display shows 8).

Measurement: visual inspection of the rendered page; the extracted PDF text gives the same pin numbers and labels. Verdict: topology and component values recoverable; clock frequency and supply are implementation choices. An earlier brief described Q1/R1/R2 as an MR reset network; the drawing contradicts that and the implementation follows the drawing.

## Verification status and limits

Local rendering command exited 0 with output: `Rendered source pages and contact sheet`. Detailed rendering exited 0 with output: `Rendered detail and measurement pages`. These confirm file production only. Circuit diagrams were then visually inspected. The renders stay with the local research copy and are not distributed. This was source research; no circuit acceptance command was run and no simulation PASS is claimed.

Unverified: actual Proteus models and their default settings; installed ASIMTUT design availability; original lamp/LED behavior; simulator parity; amplifier's missing complete topology and component values. Numeric predictions above are independent analytical expectations, not results from running the PDFs' designs.
