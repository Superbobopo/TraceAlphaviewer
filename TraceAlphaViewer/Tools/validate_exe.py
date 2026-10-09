"""Verifie le .exe local : workers, analyses, rapport et fermeture Windows."""
from dataclasses import asdict
from pathlib import Path
from queue import Empty
import ctypes
from ctypes import wintypes
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))


def receive(task, timeout=60):
    messages = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            kind, value = task.results.get(timeout=0.1)
        except Empty:
            continue
        messages.append((kind, value))
        if kind in ('done', 'error'):
            assert task.finished.wait(10), 'Le worker ne se ferme pas'
            return messages
    task.cancel()
    raise AssertionError('Le worker .exe ne repond pas')


def launch_window(executable, directory):
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                  wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    process = subprocess.Popen([str(executable)], cwd=directory,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    windows = []

    @callback_type
    def inspect_window(hwnd, _):
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value == 'TraceAlpha Viewer':
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            handle = kernel32.OpenProcess(0x1000, False, pid.value)
            if handle:
                try:
                    image = ctypes.create_unicode_buffer(32768)
                    size = wintypes.DWORD(len(image))
                    if (kernel32.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size))
                            and Path(image.value).resolve() == executable.resolve()):
                        windows.append(hwnd)
                finally:
                    kernel32.CloseHandle(handle)
        return True

    try:
        deadline = time.monotonic() + 30
        while not windows and time.monotonic() < deadline and process.poll() is None:
            user32.EnumWindows(inspect_window, 0)
            time.sleep(0.1)
        assert windows, 'La fenetre du .exe ne demarre pas'
        for hwnd in windows:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        assert process.wait(timeout=15) == 0, 'La fermeture du .exe echoue'
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def main():
    executable = ROOT / 'dist' / 'TraceAlphaViewer.exe'
    if sys.platform != 'win32' or not executable.is_file():
        print('IGNORE : validation du .exe (construction Windows locale absente)')
        return
    from Models import loading_client
    from Models.diagnostic import build_diagnostics
    from Models.diagnostic_report import build_report_payload
    from Models.event_cycles import build_business_events
    from Models.folder_report import _collect_events
    from Models.reference_index import build_reference_records
    from Parser.trace_parser import parse_file
    from generate_user_manual import demonstration

    work = ROOT / 'build'
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='validation exe ', dir=work) as temporary:
        directory = Path(temporary)
        copy = directory / 'TraceAlphaViewer test.exe'
        shutil.copy2(executable, copy)
        traces = directory / 'donnees fictives'
        traces.mkdir()
        path, *_ = demonstration(traces)
        expected_frames = parse_file(str(path), min_dt=0.0)
        expected_events = _collect_events(expected_frames)
        expected_diagnostics = build_diagnostics(expected_frames, expected_events)
        expected_references = build_reference_records(expected_frames, expected_events)
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(copy)):
            session = loading_client.LoadingSession()
            try:
                messages = receive(session.start('file', path=path))
                assert messages[-1][0] == 'done', messages[-1]
                entry = next(value for kind, value in messages if kind == 'entry')
                frames = session.open_store(entry['store'])
                assert [asdict(frame) for frame in frames] == [asdict(frame) for frame in expected_frames]
                assert frames.read_events() == expected_events
                for name, expected in (('diagnostics', expected_diagnostics), ('references', expected_references)):
                    actual = [item for kind, values in messages if kind == name for item in values]
                    assert actual == expected, name
                for belt in ('T0', 'T1', 'T2', 'T3', 'T4', 'T5'):
                    result = receive(session.start('business', store=str(frames.directory), belt=belt))
                    assert result[-1][0] == 'done', result[-1]
                    actual = [item for kind, values in result if kind == 'items' for item in values]
                    assert actual == build_business_events(expected_frames, expected_events, belt), belt
                result = receive(session.start('report', store=str(frames.directory),
                    incidents=expected_diagnostics, output_dir=str(directory / 'rapport')))
                assert result[-1][0] == 'done', result[-1]
                report = Path(next(value for kind, value in result if kind == 'result'))
                assert report.is_file() and (report.parent / '_next').is_dir(), 'Rapport React absent'
                import json
                payload = json.loads(next(report.parent.glob('report_data_*.json')).read_text(encoding='utf-8'))
                expected = build_report_payload(expected_diagnostics, frames=expected_frames)
                payload.pop('generated_at', None)
                expected.pop('generated_at', None)
                assert payload == expected, 'Rapport different du code source'
                result = receive(session.start('folder', path=traces))
                assert result[-1][0] == 'done' and sum(kind == 'entry' for kind, _ in result) == 1
                result = receive(session.start('file', path=traces / 'absent.old'))
                assert result[-1][0] == 'error', 'Erreur fichier absent perdue'
            finally:
                session.close()
                assert session.cleaned.wait(15) and not session.cleanup_error, session.cleanup_error
                assert not session.directory.exists(), 'Session non nettoyee'
        launch_window(copy, directory)
    print('Executable : lancement, fermeture, frames, analyses, filtres, dossier, rapport React et nettoyage valides')


if __name__ == '__main__':
    main()
