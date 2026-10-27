"""Mesures instantanees du PC, sans dependance Tk."""
import ctypes
import os

from Models.resource_policy import detect_resources


class SystemUsage:
    def __init__(self):
        self.previous = None

    def sample(self):
        cpu = None
        if os.name == 'nt':
            idle, kernel, user = (ctypes.c_uint64() for _ in range(3))
            try:
                if ctypes.windll.kernel32.GetSystemTimes(
                        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                    current = (idle.value, kernel.value + user.value)
                    if self.previous is not None:
                        elapsed = current[1] - self.previous[1]
                        if elapsed > 0:
                            cpu = max(0., min(1., 1 - (current[0] - self.previous[0]) / elapsed))
                    self.previous = current
            except (OSError, AttributeError):
                self.previous = None
        resources = detect_resources()
        return cpu, resources
