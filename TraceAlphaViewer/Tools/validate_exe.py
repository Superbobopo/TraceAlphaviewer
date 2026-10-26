"""Verifie le .exe local : workers, analyses, rapport et fermeture Windows."""
from dataclasses import asdict
from pathlib import Path
from queue import Empty
import ctypes
import os
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
    if os.environ.get('TRACE_ALPHA_BACKGROUND_VALIDATION', '1') == '1':
        result = subprocess.run([str(executable), '--validate-startup'], cwd=directory,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        assert result.returncode == 0, 'Le demarrage/fermeture masque du .exe echoue'
        return
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
                expected = build_report_payload(expected_diagnostics, frames=expected_frames,
                                                trace_period=frames.trace_period)
                payload.pop('generated_at', None)
                expected.pop('generated_at', None)
                assert payload == expected, 'Rapport different du code source'
                from Models.measurement_analysis import analyze_measurements, reference_page
                expected_page = reference_page(analyze_measurements(expected_frames), 'length', 'over')
                result = receive(session.start('measurement_references', store=str(frames.directory),
                                               axis='length', side='over'))
                assert result[-1][0] == 'done', result[-1]
                assert next(value for kind,value in result if kind == 'result') == expected_page, 'Liste de references differente dans le .exe'
                result = receive(session.start('folder', path=traces))
                assert result[-1][0] == 'done' and sum(kind == 'entry' for kind, _ in result) == 1
                from validate_native_folder import trace
                from Models.frame_store import FrameStore, write_frame_store
                from Models.group_analysis import analyze_group
                native_traces = traces / 'dossier Alpha'
                native_traces.mkdir()
                for day in (1, 2):
                    (native_traces / f'jour{day}.old').write_text(trace(day, frames=6, active=day == 1), encoding='latin-1')
                result = receive(session.start('folder_catalog', path=native_traces))
                assert result[-1][0] == 'done', result[-1]
                catalog = next(value for kind, value in result if kind == 'catalog')
                assert len(catalog['groups']) == 1
                group = catalog['groups'][0]
                assert group['label'] == 'Alpha 031 — Pharmacie Lahlou'
                assert len(group['sources']) == 2
                expected_sources = []
                for index, source in enumerate(group['sources']):
                    source_store = directory / f'expected-source-{index}'
                    write_frame_store(parse_file(source['filepath'], min_dt=0.0), source_store)
                    expected_sources.append(dict(source, store=str(source_store), group_name=group['label'],
                                                 raw_line_count=source['line_count']))
                expected_group = analyze_group(expected_sources, directory / 'expected-group')
                result = receive(session.start('folder_group', path=native_traces, group=group))
                assert result[-1][0] == 'done', result[-1]
                native_entry = next(value for kind, value in result if kind == 'entry')
                native_frames = session.open_store(native_entry['store'])
                with FrameStore(expected_group['store']) as expected_store:
                    assert [asdict(frame) for frame in native_frames] == [asdict(frame) for frame in expected_store]
                assert len(native_frames.source_metadata['segments']) == 2
                assert native_frames.read_events() == expected_group['events']
                for name in ('diagnostics', 'references'):
                    actual = [item for kind, values in result if kind == name for item in values]
                    assert actual == expected_group[name], f'Dossier natif .exe : {name}'
                assert native_frames.trace_period['available'], 'Calendrier du groupe absent du .exe'
                from datetime import datetime, timedelta
                from validate_c5_signal import fixture as c5_fixture
                from validate_robot_box_counts import fixture as robot_fixture, REQUEST
                from Models.robot_drain import read_trace_origin
                combined_rows = c5_fixture() + [(1000 + index / 10, text) for index, text in enumerate(
                    [REQUEST] * 8 + [text for frame in robot_fixture() for _, text in frame.raw_lines])]
                c5_path = traces / 'c5-robot-fictif.old'
                origin = datetime(2026, 10, 21, 9)
                with c5_path.open('w', encoding='latin-1') as output:
                    output.write('21|09:00:00.0 OUVERTURE DE LA TRACE le 21/10/2026\n')
                    output.write('21|09:00:00.0 C:\\APOTEKA\\BASEALPHA_#2025.031.MDB\n')
                    output.write('21|09:00:00.0 C:\\APOTEKA\\BASEFICDEMONSTRATION.MDB\n')
                    for seconds, text in combined_rows:
                        moment = origin + timedelta(seconds=seconds)
                        output.write(moment.strftime('%d|%H:%M:%S.') + str(moment.microsecond // 100000) + ' ' + text + '\n')
                c5_frames = parse_file(str(c5_path), min_dt=0.0)
                expected_c5 = build_diagnostics(c5_frames, _collect_events(c5_frames), trace_origin=read_trace_origin(c5_path))
                result = receive(session.start('file', path=c5_path))
                assert result[-1][0] == 'done', result[-1]
                actual_c5 = [row for kind, values in result if kind == 'diagnostics' for row in values]
                assert actual_c5 == expected_c5, 'Diagnostics C5/robot differents dans le .exe'
                c5 = next(row for row in actual_c5 if row.code == 'C5_SIGNAL_ANOMALY')
                assert c5.severity == 'error' and c5.metrics['suspect_cycle_count'] == 1
                c5_entry = next(value for kind, value in result if kind == 'entry')
                from validate_priority_impact import stale
                report_incidents = actual_c5 + [stale(line=5, end=10)]
                result = receive(session.start('report', store=c5_entry['store'], incidents=report_incidents,
                                               output_dir=str(directory / 'rapport-c5')))
                assert result[-1][0] == 'done', result[-1]
                c5_report = Path(next(value for kind, value in result if kind == 'result'))
                c5_payload = json.loads(next(c5_report.parent.glob('report_data_*.json')).read_text(encoding='utf-8'))
                assert c5_payload['source']['identity']['pharmacy'] == 'Demonstration'
                assert c5_payload['source']['identity']['alpha_number'] == '031'
                assert any(group['code'] == 'C5_SIGNAL_ANOMALY' and group['series'] for group in c5_payload['groups'])
                priority_codes = [group['code'] for group in c5_payload['priority']]
                assert priority_codes.index('C5_SIGNAL_ANOMALY') < priority_codes.index('T5_STALE_UNMEASURED_BOX')
                robot = next(group for group in c5_payload['groups'] if group['code'] == 'DemVidageComplet')
                assert len(robot['priority_lines']) == 2 and robot['evacuated_ratio'] == 3 / 5
                result = receive(session.start('file', path=traces / 'absent.old'))
                assert result[-1][0] == 'error', 'Erreur fichier absent perdue'
            finally:
                session.close()
                assert session.cleaned.wait(15) and not session.cleanup_error, session.cleanup_error
                assert not session.directory.exists(), 'Session non nettoyee'
        launch_window(copy, directory)
    print('Executable : lancement, fermeture, frames, analyses C5/robot, filtres, dossiers Python/Rust, rapport React et nettoyage valides')


if __name__ == '__main__':
    main()
