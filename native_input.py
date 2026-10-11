"""Read-only Windows joystick input, with a harmless fallback on other systems.

WinMM is built into Windows. This module neither installs drivers nor changes
controller configuration. Device and axis indices are exposed for UI mapping.
"""
from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass
from typing import Any


def normalize_axis(value: int, minimum: int, maximum: int) -> float:
    """Normalize a device's reported range, including unusual driver ranges."""
    if maximum <= minimum:
        return 0.0
    return max(-1.0, min(1.0, 2.0 * (value - minimum) / (maximum - minimum) - 1.0))


class JoyCaps(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.c_uint16), ("wPid", ctypes.c_uint16),
        ("szPname", ctypes.c_wchar * 32),
        *[(name, ctypes.c_uint32) for name in (
            "wXmin", "wXmax", "wYmin", "wYmax", "wZmin", "wZmax",
            "wNumButtons", "wPeriodMin", "wPeriodMax", "wRmin", "wRmax",
            "wUmin", "wUmax", "wVmin", "wVmax", "wCaps", "wMaxAxes",
            "wNumAxes", "wMaxButtons")],
        ("szRegKey", ctypes.c_wchar * 32),
        ("szOEMVxD", ctypes.c_wchar * 260),
    ]


class JoyInfoEx(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "dwSize", "dwFlags", "dwXpos", "dwYpos", "dwZpos", "dwRpos",
        "dwUpos", "dwVpos", "dwButtons", "dwButtonNumber", "dwPOV",
        "dwReserved1", "dwReserved2")]


@dataclass(frozen=True)
class Device:
    id: int
    name: str
    buttons: int
    ranges: tuple[tuple[str, int, int], ...]

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "buttons": self.buttons,
                "axes": len(self.ranges), "axisNames": [item[0] for item in self.ranges]}


def device_from_caps(device_id: int, caps: JoyCaps) -> Device:
    # WinMM exposes X/Y unconditionally; its capability bits identify the rest.
    names = ["X", "Y"][:max(0, min(2, caps.wNumAxes))]
    names.extend(name for bit, name in ((1, "Z"), (2, "R"), (4, "U"), (8, "V"))
                 if caps.wCaps & bit)
    return Device(device_id, caps.szPname.strip() or f"Controller {device_id + 1}",
                  max(0, min(32, caps.wNumButtons)),
                  tuple((name, getattr(caps, f"w{name}min"),
                         getattr(caps, f"w{name}max")) for name in names))


class NativeInput:
    """A small WinMM adapter. Passing an API makes hardware-free tests possible."""

    def __init__(self, api: Any = None):
        self.api = api
        self.devices: dict[int, Device] = {}
        if api is None and sys.platform == "win32":
            try:
                self.api = ctypes.WinDLL("winmm")
                self.api.joyGetNumDevs.argtypes = []
                self.api.joyGetNumDevs.restype = ctypes.c_uint32
                self.api.joyGetDevCapsW.argtypes = [ctypes.c_size_t,
                                                  ctypes.POINTER(JoyCaps),
                                                  ctypes.c_uint32]
                self.api.joyGetDevCapsW.restype = ctypes.c_uint32
                self.api.joyGetPosEx.argtypes = [ctypes.c_uint32,
                                               ctypes.POINTER(JoyInfoEx)]
                self.api.joyGetPosEx.restype = ctypes.c_uint32
            except (OSError, AttributeError):
                self.api = None

    @property
    def supported(self) -> bool:
        return self.api is not None

    def _position(self, device_id: int) -> JoyInfoEx | None:
        info = JoyInfoEx()
        info.dwSize = ctypes.sizeof(info)
        info.dwFlags = 0xFF  # JOY_RETURNALL
        try:
            if self.api is not None and self.api.joyGetPosEx(device_id, ctypes.byref(info)) == 0:
                return info
        except (OSError, ValueError):
            pass
        return None

    def scan(self) -> list[dict[str, Any]]:
        found: dict[int, Device] = {}
        if self.api is not None:
            try:
                count = max(0, min(64, int(self.api.joyGetNumDevs())))
                for index in range(count):
                    caps = JoyCaps()
                    if self.api.joyGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                        if self._position(index) is not None:
                            found[index] = device_from_caps(index, caps)
            except (OSError, ValueError):
                pass
        self.devices = found
        return [device.public() for device in found.values()]

    def poll(self, device_id: int) -> dict[str, Any] | None:
        device = self.devices.get(device_id)
        if device is None:
            return None
        info = self._position(device_id)
        if info is None:
            return None
        return {
            "type": "input", "device": device_id,
            "buttons": [bool(info.dwButtons & (1 << bit)) for bit in range(device.buttons)],
            "axes": [normalize_axis(getattr(info, f"dw{name}pos"), low, high)
                     for name, low, high in device.ranges],
            "time": time.time_ns() / 1_000_000,
        }
