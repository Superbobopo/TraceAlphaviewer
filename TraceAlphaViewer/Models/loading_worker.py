"""Worker autonome : aucun import de Tk ni de module Views."""
from __future__ import annotations

from pathlib import Path
import pickle
import sys
import time

from Models.diagnostic import build_diagnostics
from Models.folder_report import _collect_events, find_trace_files
from Models.frame_store import FrameStore, write_frame_store
from Models.reference_index import build_reference_records
from Parser.trace_parser import parse_file


def run(request, send):
    mode = request['mode']
    if mode in ('business', 'report'):
        with FrameStore(request['store']) as frames:
            if mode == 'business':
                from Models.event_cycles import build_business_events
                items = build_business_events(frames, frames.read_events(), request['belt'])
                for start in range(0, len(items), 500):
                    send('items', items[start:start + 500])
            else:
                from Models.diagnostic_report import write_diagnostic_report
                output_dir = Path(request['output_dir']) if request.get('output_dir') else None
                path = write_diagnostic_report(request['incidents'], output_dir=output_dir, frames=frames)
                send('result', str(path.resolve()))
        send('done', {})
        return

    path = Path(request['path']).resolve()
    files = [path] if mode == 'file' else find_trace_files(path)
    timings = {}
    for number, filepath in enumerate(files):
        filename = filepath.name
        title = f'Analyse de la trace : {filename}' if mode == 'file' else f'Analyse du dossier : {path.name}'
        suffix = '' if mode == 'file' else f' ({number + 1}/{len(files)} : {filename})'

        def step(key, detail):
            send('step', (title, detail + suffix, key))

        def measure(key, operation):
            started = time.perf_counter()
            result = operation()
            timings[key] = timings.get(key, 0.0) + time.perf_counter() - started
            return result

        def progress(done, total):
            ratio = done / max(total, 1)
            send('progress', ratio if mode == 'file' else (number + ratio) / max(len(files), 1))

        step('read', 'Lecture du fichier trace...')
        entry = {'filepath': str(filepath), 'name': filename,
                 'modified_ts': filepath.stat().st_mtime, 'parse_error': '', 'store': None}
        try:
            frames = measure('parsing', lambda: parse_file(str(filepath), progress_cb=progress, min_dt=0.0))
        except Exception as exc:
            if mode == 'file':
                raise
            entry['parse_error'] = str(exc)
            send('entry', entry)
            send('entry_done', {'frames': 0, 'events': 0, 'diagnostics': 0, 'references': 0})
            continue
        step('events', 'Construction des evenements...')
        events = measure('evenements', lambda: _collect_events(frames))
        step('diagnostic', 'Analyse diagnostic...')
        diagnostics = measure('diagnostics', lambda: build_diagnostics(frames, events))
        step('references', 'Index references...')
        references = measure('references', lambda: build_reference_records(frames, events)) if mode == 'file' else []
        step('display', "Preparation de l'affichage...")
        directory = Path(request['session']) / f'entry-{number}'
        count = len(frames)
        measure('stockage', lambda: write_frame_store(frames, directory, release=True))
        del frames
        with (directory / 'events.pkl').open('wb') as output:
            pickle.dump(events, output, protocol=pickle.HIGHEST_PROTOCOL)
        entry['store'] = str(directory)
        send('entry', entry)
        for key, items in (('events', events), ('diagnostics', diagnostics), ('references', references)):
            for start in range(0, len(items), 500):
                send(key, items[start:start + 500])
        send('entry_done', {'frames': count, 'events': len(events),
                            'diagnostics': len(diagnostics), 'references': len(references)})
    send('done', {'mode': mode, 'directory': str(path), 'timings': timings})


def main(request_path=None) -> None:
    with Path(request_path or sys.argv[1]).open('rb') as source:
        request = pickle.load(source)

    if sys.stdout is None:
        # Le mode Windows sans console conserve le pipe natif herite du parent.
        import ctypes
        from ctypes import wintypes
        import msvcrt
        import os
        get_handle = ctypes.windll.kernel32.GetStdHandle
        get_handle.argtypes = [wintypes.DWORD]
        get_handle.restype = wintypes.HANDLE
        handle = get_handle(-11)
        descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
        output = os.fdopen(descriptor, 'wb', buffering=0)
    else:
        output = sys.stdout.buffer

    def send(kind, payload):
        pickle.dump((request['job_id'], kind, payload), output,
                    protocol=pickle.HIGHEST_PROTOCOL)
        output.flush()

    try:
        run(request, send)
    except Exception as exc:
        send('error', str(exc))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
