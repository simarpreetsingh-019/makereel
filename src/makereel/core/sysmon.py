"""Live computer load: total CPU, makereel's own CPU and memory, and (on Macs) the CPU temperature.

The temperature comes from the same sensors the Thermo app reads: Apple's HID temperature sensors,
through IOKit, with no admin rights. On other systems (or if the sensors can't be read) it's left out.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import platform
import threading

import psutil

_temps = None
_lock = threading.Lock()


class _MacTemps:
    """Thermo's reader (Metrics.swift), in ctypes: IOHIDEventSystemClient → temperature events."""

    def __init__(self) -> None:
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        io = ctypes.CDLL(ctypes.util.find_library("IOKit"))
        vp, i32, i64, dbl = ctypes.c_void_p, ctypes.c_int32, ctypes.c_int64, ctypes.c_double
        for fn, res, args in (
            (cf.CFStringCreateWithCString, vp, [vp, ctypes.c_char_p, ctypes.c_uint32]),
            (cf.CFNumberCreate, vp, [vp, ctypes.c_int, vp]),
            (cf.CFDictionaryCreate, vp, [vp, vp, vp, ctypes.c_long, vp, vp]),
            (cf.CFArrayGetCount, ctypes.c_long, [vp]),
            (cf.CFArrayGetValueAtIndex, vp, [vp, ctypes.c_long]),
            (cf.CFStringGetCString, ctypes.c_bool, [vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]),
            (cf.CFRelease, None, [vp]),
            (io.IOHIDEventSystemClientCreate, vp, [vp]),
            (io.IOHIDEventSystemClientSetMatching, i32, [vp, vp]),
            (io.IOHIDEventSystemClientCopyServices, vp, [vp]),
            (io.IOHIDServiceClientCopyProperty, vp, [vp, vp]),
            (io.IOHIDServiceClientCopyEvent, vp, [vp, i64, i32, i64]),
            (io.IOHIDEventGetFloatValue, dbl, [vp, i32]),
        ):
            fn.restype, fn.argtypes = res, args
        self.cf, self.io = cf, io
        utf8 = 0x08000100
        self._s = lambda text: cf.CFStringCreateWithCString(None, text.encode(), utf8)
        keys = (vp * 2)(self._s("PrimaryUsagePage"), self._s("PrimaryUsage"))
        page, usage = ctypes.c_int32(0xFF00), ctypes.c_int32(5)      # Apple vendor page, temperature sensors
        vals = (vp * 2)(cf.CFNumberCreate(None, 3, ctypes.byref(page)), cf.CFNumberCreate(None, 3, ctypes.byref(usage)))
        key_cb = ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")
        val_cb = ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")
        match = cf.CFDictionaryCreate(None, keys, vals, 2, ctypes.addressof(key_cb), ctypes.addressof(val_cb))
        self.client = io.IOHIDEventSystemClientCreate(None)
        if not self.client:
            raise OSError("no HID event system")
        io.IOHIDEventSystemClientSetMatching(self.client, match)
        self.product = self._s("Product")

    def read(self) -> dict[str, float]:
        cf, io, out = self.cf, self.io, {}
        services = io.IOHIDEventSystemClientCopyServices(self.client)
        if not services:
            return out
        try:
            for i in range(cf.CFArrayGetCount(services)):
                svc = cf.CFArrayGetValueAtIndex(services, i)
                name = f"sensor{i}"
                prop = io.IOHIDServiceClientCopyProperty(svc, self.product)
                if prop:
                    buf = ctypes.create_string_buffer(128)
                    if cf.CFStringGetCString(prop, buf, 128, 0x08000100):
                        name = buf.value.decode(errors="ignore")
                    cf.CFRelease(prop)
                ev = io.IOHIDServiceClientCopyEvent(svc, 15, 0, 0)        # 15 = temperature event
                if not ev:
                    continue
                t = io.IOHIDEventGetFloatValue(ev, 15 << 16)
                cf.CFRelease(ev)
                if 0 < t < 150:
                    out[name] = max(out.get(name, 0.0), t)
        finally:
            cf.CFRelease(services)
        return out


def cpu_temperature() -> float | None:
    """Hottest CPU/SoC sensor in °C (Macs only), or None."""
    global _temps
    if platform.system() != "Darwin":
        return None
    with _lock:
        try:
            if _temps is None:
                _temps = _MacTemps()
            sensors = _temps.read()
        except Exception:  # noqa: BLE001 - unsupported Mac / sandbox: just no temperature
            _temps = False
            return None
    names = {k.lower(): v for k, v in sensors.items() if "tcal" not in k.lower()}   # tcal: fixed calibration value
    cpu = [v for k, v in names.items() if "tdie" in k] or \
          [v for k, v in names.items() if any(w in k for w in ("tdev", "pmu", "cpu", "soc"))]
    return round(max(cpu), 1) if cpu else None


def heat_label(temp: float | None) -> str | None:
    if temp is None:
        return None
    return "hot" if temp >= 90 else "warm" if temp >= 75 else "normal"


def snapshot() -> dict:
    """One reading: total CPU %, makereel's own CPU % and memory (with its ffmpeg/yt-dlp helpers)."""
    me = psutil.Process()
    procs = [me] + me.children(recursive=True)
    own_cpu, own_mem = 0.0, 0
    for p in procs:
        try:
            own_cpu += p.cpu_percent(None)        # since the previous reading (first call: 0)
            own_mem += p.memory_info().rss
        except psutil.Error:
            pass
    temp = cpu_temperature()
    return {"cpu": psutil.cpu_percent(None), "cores": psutil.cpu_count() or 1,
            "makereel_cpu": round(own_cpu, 1), "makereel_mem": own_mem,
            "ram_used": psutil.virtual_memory().percent, "temp": temp, "heat": heat_label(temp),
            "helpers": sum(1 for p in procs[1:] if _alive(p))}


def _alive(p) -> bool:
    try:
        return p.is_running()
    except psutil.Error:
        return False
