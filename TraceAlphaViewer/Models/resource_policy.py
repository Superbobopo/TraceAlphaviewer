"""Budget partage des accelerations ; aucune dependance a l'interface."""
from dataclasses import dataclass
from pathlib import Path
import ctypes
import os
import threading
import uuid
import weakref


MIB = 1024 ** 2
GIB = 1024 ** 3
# Profils qualifies localement ; ne pas les elargir sans mesures completes.
QUALIFIED_FILE_MIN_BYTES = 64 * MIB
QUALIFIED_FOLDER_WORKERS = 4


@dataclass(frozen=True)
class Resources:
    total: int = 0
    available: int = 0
    cpus: int = 1
    reliable: bool = False


def detect_resources():
    if os.name != 'nt':
        return Resources()
    class Status(ctypes.Structure):
        _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
            (name, ctypes.c_uint64) for name in ('total', 'available', 'page', 'page_available',
                                               'virtual', 'virtual_available', 'extended')]
    value = Status()
    value.length = ctypes.sizeof(value)
    try:
        count = getattr(os, 'process_cpu_count', os.cpu_count)() or 1
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)) and 0 <= value.available <= value.total:
            return Resources(value.total, value.available, count, bool(value.total))
    except (OSError, AttributeError):
        pass
    return Resources()


def budget_for(resources, limit=None):
    if not resources.reliable:
        return 0
    reserve = max(2 * GIB, resources.total // 5)
    budget = max(0, min(8 * GIB, resources.available // 2, resources.available - reserve))
    return min(budget, limit) if limit is not None else budget


def cpu_limit(resources):
    return max(1, min(4, resources.cpus - 2)) if resources.reliable else 1


def source_bytes(request):
    if request.get('mode') == 'folder_group':
        return max((int(row.get('bytes', 0)) for row in request.get('group', {}).get('sources', [])), default=0)
    try:
        return Path(request.get('path', '')).stat().st_size
    except OSError:
        return 0


def worker_estimate(size):
    return max(512 * MIB, size * 12 + 256 * MIB)


def execution_policy(resources, budget, mode='file', size=0, candidate=False):
    maximum = cpu_limit(resources)
    if mode not in ('file', 'folder_group'):
        maximum = 1
    if not candidate:
        if mode == 'file' and (QUALIFIED_FILE_MIN_BYTES is None or size < QUALIFIED_FILE_MIN_BYTES):
            maximum = 1
        elif mode == 'folder_group':
            maximum = min(maximum, QUALIFIED_FOLDER_WORKERS)
    maximum = min(maximum, 1 + max(0, budget) // worker_estimate(size))
    if not candidate and mode == 'file' and maximum < 4:
        maximum = 1
    if not candidate and mode == 'folder_group' and maximum == 3:
        maximum = 2
    return dict(version=1, budget_bytes=max(0, budget), max_workers=maximum,
                worker_bytes=worker_estimate(size), reserve_bytes=max(2 * GIB, resources.total // 5),
                reliable=resources.reliable)


def launch_capacity(policy, *, additional=False):
    """Recontrole les prochains lancements sans retirer de travail deja actif."""
    resources = detect_resources()
    if not resources.reliable:
        return 0 if additional else 1
    maximum = max(1, min(4, policy.get('max_workers', 1)))
    estimate = max(1, policy.get('worker_bytes', 512 * MIB))
    budget = min(budget_for(resources), policy.get('budget_bytes', (maximum - 1) * estimate))
    if additional:
        return min(maximum - 1, budget // estimate)
    maximum = min(maximum, 1 + budget // estimate)
    return 2 if maximum == 3 else maximum


class ResourceGovernor:
    """Une enveloppe commune aux sessions, jamais une enveloppe par lecteur."""
    def __init__(self, probe=detect_resources, limit=None, monitor=True):
        self.probe, self.limit = probe, limit
        self._lock = threading.RLock()
        self._leases = {}
        self._caches = weakref.WeakKeyDictionary()
        self._owners = 0
        self._stop = threading.Event()
        self._monitor = monitor
        self._thread = None
        self.resources = self.probe()
        self.budget = budget_for(self.resources, self.limit)

    def attach(self):
        with self._lock:
            self._owners += 1
            if self._monitor and (self._stop.is_set() or self._thread is None or not self._thread.is_alive()):
                self._stop = threading.Event()
                self._thread = threading.Thread(target=self._watch, daemon=True)
                self._thread.start()

    def detach(self):
        with self._lock:
            self._owners = max(0, self._owners - 1)
            if not self._owners:
                self._stop.set()

    def _watch(self):
        stop = self._stop
        while not stop.wait(1):
            self.refresh()

    def refresh(self):
        resources = self.probe()
        with self._lock:
            self.resources = resources
            self.budget = budget_for(resources, self.limit)
            used = sum(row[0] for row in self._leases.values()) + sum(self._caches.values())
            caches = list(self._caches) if used > self.budget else []
        # Le verrou des lecteurs ne doit pas etre pris sous celui du gouverneur.
        for cache in caches:
            cache.trim_extra_cache()

    def reserve(self, request, cancel=None):
        cancel = cancel or threading.Event()
        while True:
            self.refresh()
            with self._lock:
                occupied = sum(row[1] for row in self._leases.values())
                if occupied < cpu_limit(self.resources):
                    return self._reserve(request, occupied)
            if cancel.wait(.1):
                raise InterruptedError('Chargement annule avant le lancement')

    def _reserve(self, request, occupied):
        with self._lock:
            remaining = max(0, self.budget - sum(row[0] for row in self._leases.values()) - sum(self._caches.values()))
            policy = execution_policy(self.resources, remaining, request.get('mode', ''), source_bytes(request))
            policy['max_workers'] = min(policy['max_workers'], max(1, cpu_limit(self.resources) - occupied))
            if request.get('mode') == 'file' and policy['max_workers'] < 4:
                policy['max_workers'] = 1
            if request.get('mode') == 'folder_group':
                count = len(request.get('group', {}).get('sources', []))
                policy['max_workers'] = min(policy['max_workers'], max(1, count))
                if policy['max_workers'] == 3:
                    policy['max_workers'] = 2
            identifier = uuid.uuid4().hex
            extra = max(0, policy['max_workers'] - 1) * policy['worker_bytes']
            self._leases[identifier] = extra, policy['max_workers']
            # Le worker ne peut pas se reattribuer tout le budget du PC.
            policy['budget_bytes'] = extra
            return identifier, policy

    def release(self, identifier):
        with self._lock:
            self._leases.pop(identifier, None)

    def cache_allowance(self, cache, desired):
        with self._lock:
            current = self._caches.get(cache, 0)
            used = sum(row[0] for row in self._leases.values()) + sum(self._caches.values()) - current
            maximum = min(256 * MIB, self.budget // 8, max(0, self.budget - used))
            granted = min(maximum, max(0, desired))
            self._caches[cache] = granted
            return granted

    def release_cache(self, cache):
        with self._lock:
            self._caches.pop(cache, None)


_governor = None
_governor_lock = threading.Lock()


def get_governor():
    global _governor
    with _governor_lock:
        if _governor is None:
            _governor = ResourceGovernor()
        return _governor
