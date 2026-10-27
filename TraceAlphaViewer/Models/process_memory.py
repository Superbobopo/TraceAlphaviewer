"""Mesures Windows du processus et de ses descendants pour les benchmarks."""
import ctypes
import os
import threading


def process_memory(pid=None):
    if os.name != 'nt':
        return 0, 0
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak_working', 'working', 'peak_paged', 'paged',
                'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    get_info = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid or os.getpid())
    if not handle:
        return 0, 0
    try:
        value = Counters()
        value.cb = ctypes.sizeof(value)
        if get_info(handle, ctypes.byref(value), value.cb):
            return value.working, value.private
        return 0, 0
    finally:
        kernel.CloseHandle(handle)


def process_tree(root):
    if os.name != 'nt':
        return [root]
    from ctypes import wintypes
    class Entry(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD), ('pid', wintypes.DWORD),
            ('heap', ctypes.c_size_t), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
            ('parent', wintypes.DWORD), ('priority', wintypes.LONG), ('flags', wintypes.DWORD),
            ('name', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        return [root]
    parents = {}
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        valid = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while valid:
            parents[entry.pid] = entry.parent
            valid = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    result = {root}
    while True:
        added = {pid for pid, parent in parents.items() if parent in result} - result
        if not added:
            return sorted(result)
        result.update(added)


class MemorySampler:
    def __init__(self):
        self.stop_event = threading.Event()
        self.working = self.private = self.processes = self.samples = 0

    def _sample(self):
        pids = process_tree(os.getpid())
        values = [process_memory(pid) for pid in pids]
        self.working = max(self.working, sum(value[0] for value in values))
        self.private = max(self.private, sum(value[1] for value in values))
        self.processes = max(self.processes, len(pids))
        self.samples += 1

    def __enter__(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def _run(self):
        while not self.stop_event.wait(.1):
            self._sample()

    def __exit__(self, *_):
        self.stop_event.set()
        self.thread.join()
        self._sample()

    def result(self):
        return dict(peak_working_bytes=self.working, peak_private_bytes=self.private,
                    max_processes=self.processes, samples=self.samples, interval_ms=100)
