"""Copie d'un rapport autonome comme fichier dans le presse-papiers Windows."""
import ctypes
from ctypes import wintypes
import os
import struct
import re
from datetime import datetime
from pathlib import Path


def report_filename(payload):
    source = payload.get('source') or {}
    identity = source.get('identity') or {}

    def clean(value, fallback):
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value or '')).strip(' .')
        return value[:65].rstrip(' .') or fallback

    trace = str(source.get('name') or '').replace('\\', '/').rsplit('/', 1)[-1]
    if trace.lower().endswith('.old'):
        trace = trace[:-4]
    try:
        date = datetime.strptime(payload.get('generated_at', ''), '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d_%H-%M-%S')
    except (ValueError, TypeError):
        date = 'date inconnue'
    return f"Rapport_{clean(trace, 'Trace')}_{clean(identity.get('pharmacy'), 'Pharmacie non identifiée')}_{date}.html"


def copy_report_file(path):
    if os.name != 'nt':
        raise OSError('La copie de fichier nécessite Windows.')
    path = Path(path).resolve(strict=True)
    data = struct.pack('<IiiII', 20, 0, 0, 0, 1) + (str(path) + '\0\0').encode('utf-16-le')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    user.CreateWindowExW.restype = wintypes.HWND
    user.DestroyWindow.argtypes = [wintypes.HWND]
    user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user.SetClipboardData.restype = wintypes.HANDLE
    handle = kernel.GlobalAlloc(0x0042, len(data))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        pointer = kernel.GlobalLock(handle)
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            kernel.GlobalUnlock(handle)
        # Fenêtre invisible du worker : propriétaire valide, sans appel Tk.
        owner = user.CreateWindowExW(0, 'STATIC', '', 0, 0, 0, 0, 0, -3, None, None, None)
        if not owner:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not user.OpenClipboard(owner):
                raise OSError('Presse-papiers occupé ; réessayez.')
            try:
                if not user.EmptyClipboard() or not user.SetClipboardData(15, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                handle = None  # Windows possède désormais la mémoire.
            finally:
                user.CloseClipboard()
        finally:
            user.DestroyWindow(owner)
    finally:
        if handle:
            kernel.GlobalFree(handle)
