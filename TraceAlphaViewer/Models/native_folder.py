"""Interface du moteur Rust reserve a l'ouverture des dossiers."""
from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path
import subprocess
import sys
import uuid

from Models.state import BoxInfo, MachineEvent, MachineState


PROTOCOL_VERSION = 1


def engine_path() -> Path:
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    path = root / 'bin' / ('tracealpha-folder-worker.exe' if sys.platform == 'win32' else 'tracealpha-folder-worker')
    if not path.is_file():
        raise OSError("Moteur Rust du dossier absent. Construisez-le avec python TraceAlphaViewer/Tools/build_folder_engine.py.")
    return path


class _ProcessLifetime:
    """La fermeture du worker Windows arrete aussi son enfant Rust."""
    def __init__(self, process):
        self.handle = None
        if sys.platform != 'win32':
            return
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t),
                        ('maximum', ctypes.c_size_t), ('processes', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', Counters), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                        ('peak_job', ctypes.c_size_t)]

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000
        if (not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not kernel.AssignProcessToJobObject(handle, wintypes.HANDLE(int(process._handle)))):
            error = ctypes.WinError(ctypes.get_last_error())
            kernel.CloseHandle(handle)
            raise error
        self.handle, self.kernel = handle, kernel

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run_native(operation, directory, session, sources=None, on_message=None):
    """Echange les commandes legeres ; les frames restent dans les blocs binaires."""
    session = Path(session).resolve()
    session.mkdir(parents=True, exist_ok=True)
    identifier = uuid.uuid4().hex
    request = {'protocol_version': PROTOCOL_VERSION, 'job_id': identifier,
               'operation': operation, 'path': str(Path(directory).resolve()),
               'session': str(session), 'sources': sources or []}
    request_path = session / ('native-' + identifier + '.json')
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
    result = None
    finished = False
    lifetime = None
    with (session / ('native-' + identifier + '.log')).open('wb') as errors:
        process = subprocess.Popen([str(engine_path()), '--request', str(request_path)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
                                   text=True, encoding='utf-8', errors='strict',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            lifetime = _ProcessLifetime(process)
            for line in process.stdout:
                message = json.loads(line)
                if message.get('protocol_version') != PROTOCOL_VERSION:
                    raise OSError('Version du moteur Rust incompatible ; reconstruisez le moteur du dossier.')
                if message.get('job_id') != identifier:
                    raise OSError('Reponse Rust etrangere au chargement courant')
                kind, payload = message['kind'], message.get('payload')
                if kind == 'error':
                    raise OSError(payload.get('message', str(payload)) if isinstance(payload, dict) else str(payload))
                if kind in ('catalog', 'result'):
                    result = payload
                elif kind == 'done':
                    finished = True
                if on_message is not None:
                    on_message(kind, payload)
            code = process.wait()
            if code or not finished or result is None:
                raise OSError(f'Le moteur Rust a quitte sans resultat complet (code {code}).')
            return result
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait()
            process.stdout.close()
            if lifetime is not None:
                lifetime.close()


def native_frames(source):
    """Reconstruit les dataclasses sans introspection par frame ni perte de tuples."""
    try:
        import msgpack
    except ImportError as exc:
        raise OSError('La dependance msgpack manque pour le moteur Rust du dossier.') from exc
    directory = Path(source['store']).resolve()
    blocks = source.get('blocks')
    if blocks is None:
        blocks = [path.name for path in sorted(directory.glob('block-*.msgpack'))]
    count = 0
    schemas = {model: {item.name for item in fields(model)} for model in (MachineState, BoxInfo, MachineEvent)}
    checked = set()

    def decode(value):
        model = (MachineState if 'boxes_on_T5' in value else
                 BoxInfo if 'id_alpha' in value else MachineEvent)
        if model not in checked:
            if set(value) != schemas[model]:
                raise OSError('Schema des frames Rust incompatible avec les modeles Python')
            checked.add(model)
        if model is MachineState:
            value['raw_lines'] = [tuple(row) for row in value['raw_lines']]
        result = model.__new__(model)
        result.__dict__ = value
        return result

    for filename in blocks:
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory):
            raise OSError('Bloc natif hors du stockage de session')
        checked.clear()
        batch = msgpack.unpackb(path.read_bytes(), raw=False, object_hook=decode)
        if not isinstance(batch, list) or not 0 < len(batch) <= 500:
            raise OSError('Bloc de frames Rust incomplet ou trop grand')
        for value in batch:
            if not isinstance(value, MachineState):
                raise OSError('Frame Rust invalide')
            count += 1
            yield value
    if count != source['frame_count']:
        raise OSError('Nombre de frames Rust incomplet')
