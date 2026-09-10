"""Foreground-window info on Windows: title + process name.

This is cheap, local, and often a more reliable signal for "what app is this"
than the vision model. Returns empty strings on failure or non-Windows.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

try:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _psapi = ctypes.windll.psapi
    _AVAILABLE = True
except (AttributeError, OSError):  # not Windows
    _AVAILABLE = False


def foreground_window() -> tuple[str, str]:
    """(window_title, process_name) for the focused window, or ("", "")."""
    if not _AVAILABLE:
        return "", ""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return "", ""

        length = _user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""

        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = _process_name(pid.value)
        return title, proc
    except Exception:
        return "", ""


# PROCESS_QUERY_LIMITED_INFORMATION
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _process_name(pid: int) -> str:
    if not pid:
        return ""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.split("\\")[-1]
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def focus_hint() -> str:
    """A short 'Notepad.exe — Untitled' style hint, or '' if unavailable."""
    title, proc = foreground_window()
    if proc and title:
        return f"{proc} — {title}"
    return proc or title
