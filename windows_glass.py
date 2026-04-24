"""Apply Windows 11 acrylic / Mica backdrop and rounded corners via DWM.

All calls are no-ops on non-Windows or unsupported builds.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_SYSTEMBACKDROP_TYPE = 38

_DWMWCP_ROUND = 2
_DWMWCP_ROUNDSMALL = 3

_DWMSBT_MAINWINDOW = 2
_DWMSBT_TRANSIENTWINDOW = 3

# Pre-DWM-systembackdrop fallback (Win10 1803+).
_WCA_ACCENT_POLICY = 19
_ACCENT_ENABLE_BLURBEHIND = 3
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


class _AccentPolicy(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_uint),
        ("AccentFlags", ctypes.c_uint),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_uint),
    ]


class _WinCompAttrData(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.POINTER(_AccentPolicy)),
        ("SizeOfData", ctypes.c_size_t),
    ]


def _hwnd_for(tk_root) -> int:
    try:
        return int(tk_root.wm_frame(), 16)
    except Exception:
        return tk_root.winfo_id()


def _abgr(rgb_hex: str, alpha: int) -> int:
    """Pack an RGB hex + alpha into the ABGR DWORD layout DWM expects."""
    r = int(rgb_hex[1:3], 16)
    g = int(rgb_hex[3:5], 16)
    b = int(rgb_hex[5:7], 16)
    return (alpha << 24) | (b << 16) | (g << 8) | r


def apply_rounded(tk_root, small: bool = False) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        hwnd = _hwnd_for(tk_root)
        pref = ctypes.c_int(_DWMWCP_ROUNDSMALL if small else _DWMWCP_ROUND)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(_DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
        return res == 0
    except OSError:
        return False


def apply_mica(tk_root) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        hwnd = _hwnd_for(tk_root)
        val = ctypes.c_int(_DWMSBT_MAINWINDOW)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(_DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(val),
            ctypes.sizeof(val),
        )
        return res == 0
    except OSError:
        return False


def apply_acrylic(tk_root, tint_hex: str = "#101014", tint_alpha: int = 160) -> bool:
    if not sys.platform.startswith("win"):
        return False
    hwnd = _hwnd_for(tk_root)

    try:
        val = ctypes.c_int(_DWMSBT_TRANSIENTWINDOW)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(_DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(val),
            ctypes.sizeof(val),
        )
        if res == 0:
            return True
    except OSError:
        pass

    try:
        accent = _AccentPolicy()
        accent.AccentState = _ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 2
        accent.GradientColor = _abgr(tint_hex, tint_alpha)
        accent.AnimationId = 0

        data = _WinCompAttrData()
        data.Attribute = _WCA_ACCENT_POLICY
        data.Data = ctypes.pointer(accent)
        data.SizeOfData = ctypes.sizeof(accent)

        set_attr = ctypes.windll.user32.SetWindowCompositionAttribute
        set_attr.restype = ctypes.c_int
        return set_attr(wintypes.HWND(hwnd), ctypes.byref(data)) != 0
    except (OSError, AttributeError):
        return False


def set_blur_during_drag(tk_root) -> None:
    """Cheaper backdrop while the window is being dragged — acrylic stutters."""
    if not sys.platform.startswith("win"):
        return
    try:
        hwnd = _hwnd_for(tk_root)
        accent = _AccentPolicy()
        accent.AccentState = _ACCENT_ENABLE_BLURBEHIND
        accent.AccentFlags = 0
        accent.GradientColor = 0
        accent.AnimationId = 0
        data = _WinCompAttrData()
        data.Attribute = _WCA_ACCENT_POLICY
        data.Data = ctypes.pointer(accent)
        data.SizeOfData = ctypes.sizeof(accent)
        ctypes.windll.user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(data))
    except (OSError, AttributeError):
        pass
