"""Sleep-inclusive local clock; no opener/provider/permission requests.

Use real kernel identity, never a test's mocked sys.platform. No wall fallback.
"""
from __future__ import annotations

import os
import time
from functools import lru_cache


@lru_cache(maxsize=1)
def _darwin_clock():
    import ctypes
    class Timebase(ctypes.Structure):
        _fields_ = [('numer', ctypes.c_uint32), ('denom', ctypes.c_uint32)]
    library = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
    continuous = library.mach_continuous_time
    continuous.argtypes = []
    continuous.restype = ctypes.c_uint64
    info = library.mach_timebase_info
    info.argtypes = [ctypes.POINTER(Timebase)]
    info.restype = ctypes.c_int
    base = Timebase()
    if info(ctypes.byref(base)) or not base.numer or not base.denom:
        raise RuntimeError('native_continuous_clock_unavailable')
    return continuous, int(base.numer), int(base.denom)


def continuous_ns():
    try:
        if os.uname().sysname == 'Darwin':
            clock, numer, denom = _darwin_clock()
            return int(clock()) * numer // denom
        if hasattr(time, 'CLOCK_BOOTTIME'):
            return time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError, ValueError):
        raise RuntimeError('native_continuous_clock_unavailable') from None
    raise RuntimeError('native_continuous_clock_unavailable')
