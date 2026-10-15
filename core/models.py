from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable
import ctypes

@dataclass
class PinState:
    pin_id: str
    voltage: float = 0.0
    is_digital: bool = True
    logic_level: int = 0  # 0: Low, 1: High, -1: Hi-Z

@dataclass
class SourceInstruction:
    address: int
    opcode_hex: str
    mnemonic: str
    c_source: str

class NgComplex(ctypes.Structure):
    _fields_ = [("cx_real", ctypes.c_double), ("cx_imag", ctypes.c_double)]

class VecValues(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("creal", ctypes.c_double),
        ("cimag", ctypes.c_double),
        ("is_scale", ctypes.c_bool),
        ("is_complex", ctypes.c_bool),
    ]

P_VecValues = ctypes.POINTER(VecValues)

class VecValuesAll(ctypes.Structure):
    _fields_ = [
        ("veccount", ctypes.c_int),
        ("vecindex", ctypes.c_int),
        ("vecsa", ctypes.POINTER(P_VecValues)),
    ]

class VecInfo(ctypes.Structure):
    _fields_ = [
        ("number", ctypes.c_int),
        ("vecname", ctypes.c_char_p),
        ("is_real", ctypes.c_bool),
        ("pdvec", ctypes.c_void_p),
        ("pdvecscale", ctypes.c_void_p),
    ]

P_VecInfo = ctypes.POINTER(VecInfo)

class VecInfoAll(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("title", ctypes.c_char_p),
        ("date", ctypes.c_char_p),
        ("type", ctypes.c_char_p),
        ("veccount", ctypes.c_int),
        ("vecs", ctypes.POINTER(P_VecInfo)),
    ]

class VectorInfo(ctypes.Structure):
    _fields_ = [
        ("v_name", ctypes.c_char_p),
        ("v_type", ctypes.c_int),
        ("v_flags", ctypes.c_short),
        ("v_realdata", ctypes.POINTER(ctypes.c_double)),
        ("v_compdata", ctypes.POINTER(NgComplex)),
        ("v_length", ctypes.c_int),
    ]

# C-Callback Function Prototypes for libngspice
SEND_CHAR_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
)
SEND_STAT_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
)
CONTROLLED_EXIT_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
)
SEND_DATA_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(VecValuesAll), ctypes.c_int, ctypes.c_int, ctypes.c_void_p
)
SEND_INIT_DATA_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(VecInfoAll), ctypes.c_int, ctypes.c_void_p
)
BG_THREAD_RUNNING_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
)

# C-Callback Function Prototypes for libsimavr
AVR_IRQ_NOTIFY_CB = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p
)
