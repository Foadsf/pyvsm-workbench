from typing import List, Tuple

try:
    from ..models import SourceInstruction
except (ImportError, ValueError):
    from core.models import SourceInstruction

DEFAULT_DEMO_IHEX = """:100000000C9434000C943E000C943E000C943E0043
:100010000C943E000C943E000C943E000C943E0024
:1000200011241FBECFEFD8E0DEBFCDBF0E944000B6
:100030000C9455000C9400008FE084B98FEF87B989
:1000400080E285B988E285B98CE085B981E085B9F2
:1000500085B1807F85B90000CFFECF98FF98089524
:00000001FF
"""

# Default PICDEM 2 PLUS (PIC18F452) + Milford LCD Demo Firmware Source & Disassembly
DEFAULT_FIRMWARE_LISTING: List[SourceInstruction] = [
    SourceInstruction(0x02EE, "0E00", "MOVLW 0x00", "void SetupBoard(void) {"),
    SourceInstruction(0x02F0, "6E92", "MOVWF TRISA", "    TRISA = 0xFF; TRISB = 0xFE;"),
    SourceInstruction(0x02F2, "6E95", "CLRF  TRISD", "    LCD_Init_4Bit(); // Milford LCD Demo"),
    SourceInstruction(0x02F6, "0E28", "MOVLW 0x28", "    I2C_Master_Init(100000); // 24LC256"),
    SourceInstruction(0x02FA, "EC80", "CALL  0x0300", "    WriteLCD(\"Milford LCD Demo\");"),
    SourceInstruction(0x0300, "5081", "MOVF  PORTB, W", "    while(1) { // Main VSM Co-Sim Loop"),
    SourceInstruction(0x0302, "B481", "BTFSC PORTB, 2", "        if (!PB_2) bcd_counter++;"),
    SourceInstruction(0x0304, "2A10", "INCF  bcd_cnt, F", "        Sample_ADC0_And_Update_PWM();"),
    SourceInstruction(0x0306, "EC90", "CALL  I2C_Xfer", "        I2C_WriteByte(0xA0, 0x00, bcd_cnt);"),
    SourceInstruction(0x030A, "0EFA", "MOVLW 0xFA", "void Delay(void) { // 125ms timer step"),
    SourceInstruction(0x030C, "0620", "DECF  PowerOnDelay,F", "    PowerOnDelay--;"),
    SourceInstruction(0x030E, "EC40", "CALL  calcVsum", "    calcVsumAndFreq(); // Update Meters"),
    SourceInstruction(0x0312, "D7F6", "BRA   0x0300", "    } // End ISR & Loop"),
]

def parse_intel_hex(ihex_text: str, max_size: int = 32768) -> Tuple[bytearray, int]:
    """
    Parses standard Intel HEX records and returns memory buffer and total byte count.
    """
    mem = bytearray(max_size)
    byte_count = 0
    for line in ihex_text.strip().splitlines():
        line = line.strip()
        if not line.startswith(":") or len(line) < 11:
            continue
        length = int(line[1:3], 16)
        addr = int(line[3:7], 16)
        rec_type = int(line[7:9], 16)
        data_hex = line[9: 9 + length * 2]
        if rec_type == 0x00:  # Data record
            for i in range(length):
                b = int(data_hex[i * 2: i * 2 + 2], 16)
                if addr + i < len(mem):
                    mem[addr + i] = b
                    byte_count += 1
    return mem, byte_count


def disassemble_flash(flash: bytearray, byte_count: int, arch: str = "PIC18F452") -> List[SourceInstruction]:
    """
    Disassembles raw binary words from Intel HEX flash memory into SourceInstruction rows
    for PIC18 (16-bit little-endian words) or AVR (16-bit little-endian words).
    """
    listing: List[SourceInstruction] = []
    limit = min(max(byte_count, 32), len(flash))

    for addr in range(0, limit, 2):
        if addr + 1 >= len(flash):
            break
        word = flash[addr] | (flash[addr + 1] << 8)
        if word == 0x0000 and addr > 0 and (addr + 3 < len(flash)) and flash[addr + 2 : addr + 4] == b"\x00\x00":
            continue

        opcode_hex = f"{word:04X}"
        if "PIC" in arch.upper():
            # Decode core PIC18 instruction groups
            if (word & 0xFF00) == 0x0E00:
                mnemonic = f"MOVLW 0x{word & 0xFF:02X}"
            elif (word & 0xFE00) == 0x6E00:
                mnemonic = f"MOVWF 0x{word & 0xFF:02X}"
            elif (word & 0xFC00) == 0x2800:
                mnemonic = f"INCF  0x{word & 0xFF:02X}, F"
            elif (word & 0xF800) == 0xD000:
                mnemonic = f"BRA   0x{(addr + 2 + ((word & 0x7FF) << 1)) & 0xFFFF:04X}"
            elif (word & 0xFE00) == 0xEC00:
                mnemonic = f"CALL  0x{(word & 0xFF) << 1:04X}"
            else:
                mnemonic = f"DW    0x{word:04X}"
        else:
            # Decode core AVR instruction groups
            if (word & 0xF000) == 0xE000:
                reg = 16 + ((word >> 4) & 0x0F)
                val = ((word & 0x0F00) >> 4) | (word & 0x0F)
                mnemonic = f"LDI   R{reg}, 0x{val:02X}"
            elif (word & 0xF800) == 0xB800:
                mnemonic = f"OUT   0x{((word >> 5) & 0x30) | (word & 0x0F):02X}, R{(word >> 4) & 0x1F}"
            elif (word & 0xF000) == 0xC000:
                mnemonic = f"RJMP  .+{(word & 0x0FFF) * 2}"
            elif word == 0x9508:
                mnemonic = "RET"
            else:
                mnemonic = f".WORD 0x{word:04X}"

        listing.append(
            SourceInstruction(
                address=addr,
                opcode_hex=opcode_hex,
                mnemonic=mnemonic,
                c_source=f"/* Flash[0x{addr:04X}] */",
            )
        )
    return listing or list(DEFAULT_FIRMWARE_LISTING)

