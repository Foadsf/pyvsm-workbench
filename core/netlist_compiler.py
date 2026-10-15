from typing import Dict, List, Tuple, Any
from .disjoint_set import DisjointSet

class NetlistCompiler:
    """
    Traverses all placed QGraphicsItem components and SchematicWireItem paths
    on the canvas to compile a dynamic SPICE netlist and pin-to-net lookup table.
    """

    @staticmethod
    def compile_scene(
        pins: List[Any],
        wires: List[Any],
        pot_ratio: float,
        button_pressed: bool,
        subcircuits: List[str],
    ) -> Tuple[List[str], Dict[Any, str]]:
        ds = DisjointSet()

        # Seed default canonical net aliases for every pin
        for pin in pins:
            ds.find(pin.canonical_net)

        # Merge nets linked by user-drawn or pre-routed wires
        for wire in wires:
            if getattr(wire, "pin_start", None) and getattr(wire, "pin_end", None):
                ds.union(wire.pin_start.canonical_net, wire.pin_end.canonical_net)

        pin_to_net: Dict[Any, str] = {}
        for pin in pins:
            pin_to_net[pin] = ds.find(pin.canonical_net).lower()

        r_top = max(1.0, (1.0 - pot_ratio) * 10000.0)
        r_bot = max(1.0, pot_ratio * 10000.0)
        r_btn = 0.01 if button_pressed else 100e6

        deck = [
            "OpenVSM Auto-Compiled Mixed-Mode Netlist",
            "V_VCC vcc 0 DC 5.0",
            f"R_POT_TOP vcc adc0 {r_top:.2f}",
            f"R_POT_BOT adc0 0 {r_bot:.2f}",
            "R_ADC_IN adc0 0 100MEG",
            "V_PB0 pb0 0 DC 0.0",
            "R_LOAD pb0 v_load 470",
            "C_LOAD v_load 0 10u",
            "R_PULLUP_BTN vcc pb2 10k",
            f"R_BTN_SW pb2 0 {r_btn}",
            "R_PULLUP_SDA vcc sda 4.7k",
            "R_PULLUP_SCL vcc scl 4.7k",
        ]
        for subckt in subcircuits:
            for line in subckt.strip().splitlines():
                if line.strip():
                    deck.append(line.strip())
        deck.append(".end")
        return deck, pin_to_net
