import re
from typing import Dict, Any, List

SAMPLE_KICAD_SYM_S_EXPR = """
(kicad_symbol_lib (version 20211014) (generator OpenVSM)
  (symbol "Device:OPAMP_BUFFER" (in_bom yes) (on_board yes)
    (property "Reference" "U2" (id 0) (at 0 0 0))
    (property "Value" "LM358_SPICE" (id 1) (at 0 0 0))
    (symbol "OPAMP_BUFFER_1_1"
      (rectangle (start -40 -30) (end 40 30))
      (pin input line (at -40 -10 0) (length 10) (name "IN+" (effects (font (size 1 1)))) (number "1"))
      (pin input line (at -40 10 0) (length 10) (name "IN-" (effects (font (size 1 1)))) (number "2"))
      (pin output line (at 40 0 180) (length 10) (name "OUT" (effects (font (size 1 1)))) (number "3"))
    )
  )
)
"""

SAMPLE_SPICE_SUBCKT = """
.subckt LM358_SPICE in_p in_n out
R_IN in_p in_n 2MEG
E_GAIN out 0 in_p in_n 100000
.ends LM358_SPICE
"""

class KiCadSymbolImporter:
    """Parses KiCad v6+ .kicad_sym S-expressions into placeable schematic definitions."""

    @staticmethod
    def parse_kicad_sym(sexpr_text: str) -> Dict[str, Any]:
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', sexpr_text)
        val_match = re.search(r'\(property\s+"Value"\s+"([^"]+)"', sexpr_text)
        pin_matches = re.findall(
            r'\(pin\s+(\w+)\s+\w+\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+[-\d.]+\).*?\(name\s+"([^"]+)".*?\(number\s+"([^"]+)"',
            sexpr_text,
            re.DOTALL,
        )
        pins: List[Dict[str, Any]] = []
        for p_type, x_str, y_str, p_name, p_num in pin_matches:
            pins.append({
                "type": p_type,
                "x": float(x_str),
                "y": float(y_str),
                "name": p_name,
                "number": p_num,
            })
        return {
            "reference": ref_match.group(1) if ref_match else "U_KICAD",
            "value": val_match.group(1) if val_match else "CUSTOM_IC",
            "pins": pins or [
                {"type": "input", "x": -40.0, "y": -10.0, "name": "IN+", "number": "1"},
                {"type": "output", "x": 40.0, "y": 10.0, "name": "OUT", "number": "2"},
            ],
        }
