import unittest
import sys
import os

# Add parent directory to sys.path
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from core.disjoint_set import DisjointSet
from core.netlist_compiler import NetlistCompiler
from core.spice_bridge import NgSpiceBridge
from core.mcu.multi_mcu import MultiMCUBackend
from core.mcu.firmware import parse_intel_hex, DEFAULT_DEMO_IHEX
from core.kicad_importer import KiCadSymbolImporter, SAMPLE_KICAD_SYM_S_EXPR

class MockPin:
    def __init__(self, canonical_net: str):
        self.canonical_net = canonical_net

class MockWire:
    def __init__(self, pin_start, pin_end):
        self.pin_start = pin_start
        self.pin_end = pin_end

class TestOpenVSM(unittest.TestCase):
    def test_disjoint_set(self):
        ds = DisjointSet()
        ds.union("adc0", "net_pot_wiper")
        self.assertEqual(ds.find("net_pot_wiper"), "adc0")

        # Test canonical net prioritization (0 / gnd wins over other nets)
        ds.union("0", "pb2")
        self.assertEqual(ds.find("pb2"), "0")

    def test_netlist_compiler(self):
        p1 = MockPin("adc0")
        p2 = MockPin("wiper")
        wire = MockWire(p1, p2)

        deck, pin_map = NetlistCompiler.compile_scene(
            pins=[p1, p2],
            wires=[wire],
            pot_ratio=0.5,
            button_pressed=False,
            subcircuits=[],
        )
        self.assertIn("V_VCC vcc 0 DC 5.0", deck)
        self.assertIn(".end", deck)
        self.assertEqual(pin_map[p1], "adc0")
        self.assertEqual(pin_map[p2], "adc0")

    def test_spice_bridge_mna(self):
        bridge = NgSpiceBridge()
        bridge.set_potentiometer(0.50)
        bridge.step(0.015)
        # At 50% wiper, V(adc0) = 5.0 * 5000 / 10000 = 2.5V
        self.assertAlmostEqual(bridge.node_voltages["adc0"], 2.50, delta=0.05)

        bridge.set_potentiometer(0.80)
        bridge.step(0.015)
        # At 80% wiper, V(adc0) = 5.0 * 0.80 = 4.0V
        self.assertAlmostEqual(bridge.node_voltages["adc0"], 4.00, delta=0.05)

        # Test button press
        bridge.set_button(True)
        bridge.step(0.015)
        self.assertEqual(bridge.node_voltages["pb2"], 0.0)

        bridge.set_button(False)
        bridge.step(0.015)
        self.assertEqual(bridge.node_voltages["pb2"], 5.0)

        # Test RC transient integration
        bridge.set_mcu_pin_voltage("pb0", 5.0)
        v0 = bridge.node_voltages["v_load"]
        bridge.step(0.020)
        v1 = bridge.node_voltages["v_load"]
        self.assertGreater(v1, v0)

    def test_intel_hex_parser(self):
        mem, count = parse_intel_hex(DEFAULT_DEMO_IHEX)
        self.assertGreater(count, 0)
        self.assertEqual(mem[0], 0x0C)
        self.assertEqual(mem[1], 0x94)

    def test_multi_mcu_backend(self):
        mcu = MultiMCUBackend()
        self.assertEqual(mcu.arch, "PIC18F452")
        self.assertEqual(mcu.clock_hz, 40_000_000)

        # Test architecture switching
        mcu.set_architecture("ATMEGA328P")
        self.assertEqual(mcu.clock_hz, 16_000_000)

        mcu.set_architecture("STM32F103")
        self.assertEqual(mcu.clock_hz, 72_000_000)

        # Test instruction stepping
        mcu.set_architecture("PIC18F452")
        insn0 = mcu.current_instruction()
        mcu.step_instruction(dt=0.010, ignore_breakpoint=True)
        insn1 = mcu.current_instruction()
        self.assertNotEqual(insn0.address, insn1.address)

        # Test breakpoints
        target_addr = mcu.listing[3].address
        mcu.toggle_breakpoint(target_addr)
        self.assertIn(target_addr, mcu.breakpoints)

        # Step until breakpoint
        for _ in range(len(mcu.listing)):
            cont = mcu.step_instruction(dt=0.005, ignore_breakpoint=False)
            if not cont:
                break
        self.assertTrue(mcu.hit_breakpoint)

        # Test CPU variables
        vars_list = mcu.get_cpu_variables()
        self.assertTrue(any(v[0] == "PowerOnDelay" for v in vars_list))
        self.assertTrue(any(v[0] == "bcd_counter" for v in vars_list))

    def test_kicad_importer(self):
        data = KiCadSymbolImporter.parse_kicad_sym(SAMPLE_KICAD_SYM_S_EXPR)
        self.assertEqual(data["reference"], "U2")
        self.assertEqual(data["value"], "LM358_SPICE")
        self.assertEqual(len(data["pins"]), 3)
        names = [p["name"] for p in data["pins"]]
        self.assertIn("IN+", names)
        self.assertIn("IN-", names)
        self.assertIn("OUT", names)

    def test_disassembler(self):
        from core.mcu.firmware import disassemble_flash
        mem, count = parse_intel_hex(DEFAULT_DEMO_IHEX)
        listing_avr = disassemble_flash(mem, count, "ATMEGA328P")
        self.assertGreater(len(listing_avr), 0)
        self.assertIsNotNone(listing_avr[0].mnemonic)

        listing_pic = disassemble_flash(mem, count, "PIC18F452")
        self.assertGreater(len(listing_pic), 0)
        self.assertIsNotNone(listing_pic[0].mnemonic)

if __name__ == "__main__":
    unittest.main()

