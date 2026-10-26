"""Worker autonome : aucun import de Tk ni de module Views."""
from __future__ import annotations

from pathlib import Path
import pickle
import os
import sys
import time

from Models.diagnostic import build_diagnostics
from Models.folder_report import _collect_events, find_trace_files
from Models.frame_store import FrameStore, write_frame_store
from Models.reference_index import build_reference_records
from Models.measurement_analysis import analyze_measurements
from Models.robot_drain import read_trace_origin
from Parser.trace_parser import parse_file
from Models.list_navigation import LineIndex, prepare_navigation


def run(request, send):
    mode = request['mode']
    if mode == 'segment_analysis':
        from Models.group_analysis import analyze_segment
        previous = [None, 0.0]

        def progress(*payload):
            now = time.perf_counter()
            if payload[:2] != previous[0] or now - previous[1] >= 0.2:
                send('segment_progress', payload)
                previous[:] = [payload[:2], now]

        result = analyze_segment(request['store'], request['segment'], request['origin'],
            request['index'], request['total'], request['name'], progress)
        send('segment_result', result)
        send('done', {})
        return
    if mode in ('folder_catalog', 'folder_group'):
        _run_native_folder(request, send)
        return
    if mode in ('business', 'report', 'measurement_references'):
        with FrameStore(request['store']) as frames:
            if mode == 'business':
                from Models.group_analysis import build_group_business_events
                items = build_group_business_events(frames, frames.read_events(), request['belt'])
                for start in range(0, len(items), 500):
                    send('items', items[start:start + 500])
                send('navigation', LineIndex(items))
            elif mode == 'measurement_references':
                from Models.measurement_analysis import reference_page
                page = reference_page(frames.read_measurements(), request['axis'], request['side'],
                                      request.get('page', 0), request.get('barcode', ''))
                for sample in page.get('samples', []) + page.get('representatives', []):
                    source_lines = set(sample['sources'].values()) - {0}
                    sample['context'] = []
                    for line in sorted(source_lines):
                        frame = frames[frames.frame_index_for_line(line)]
                        sample['context'].extend({'line': n, 'text': text} for n, text, *_ in frame.raw_lines if n == line)
                send('result', page)
            else:
                from Models.diagnostic_report import write_diagnostic_report
                output_dir = Path(request['output_dir']) if request.get('output_dir') else None
                path = write_diagnostic_report(request['incidents'], output_dir=output_dir, frames=frames,
                                               source_name=request.get('source_name', ''))
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
        source_metadata = {}
        try:
            frames = measure('parsing', lambda: parse_file(str(filepath), progress_cb=progress, min_dt=0.0,
                                                         source_metadata_output=source_metadata))
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
        measurements = measure('mesures', lambda: analyze_measurements(frames))
        camera_report = {}
        trace_metadata = {}
        diagnostics = measure('diagnostics', lambda: build_diagnostics(
            frames, events, measurements, camera_report_output=camera_report,
            trace_origin=read_trace_origin(filepath), trace_metadata_output=trace_metadata))
        step('references', 'Index references...')
        references = measure('references', lambda: build_reference_records(frames, events)) if mode == 'file' else []
        step('display', "Preparation de l'affichage...")
        from Models.folder_catalog import read_source_identity
        source_metadata['identity'] = measure('identite', lambda: read_source_identity(filepath))
        directory = Path(request['session']) / f'entry-{number}'
        count = len(frames)
        measure('stockage', lambda: write_frame_store(frames, directory, release=True,
                                                     measurement_summary=measurements['summary'], trace_period=trace_metadata,
                                                     source_metadata=source_metadata))
        with (directory / 'camera_report.pkl').open('wb') as output:
            pickle.dump(camera_report, output, protocol=pickle.HIGHEST_PROTOCOL)
        with (directory / 'measurements.pkl').open('wb') as output:
            pickle.dump(measurements, output, protocol=pickle.HIGHEST_PROTOCOL)
        del measurements
        del frames
        with (directory / 'events.pkl').open('wb') as output:
            pickle.dump(events, output, protocol=pickle.HIGHEST_PROTOCOL)
        entry['store'] = str(directory)
        entry['navigation'] = measure('navigation', lambda: prepare_navigation(events, diagnostics, references))
        send('entry', entry)
        for key, items in (('events', events), ('diagnostics', diagnostics), ('references', references)):
            for start in range(0, len(items), 500):
                send(key, items[start:start + 500])
        send('entry_done', {'frames': count, 'events': len(events),
                            'diagnostics': len(diagnostics), 'references': len(references)})
    send('done', {'mode': mode, 'directory': str(path), 'timings': timings})


def _run_native_folder(request, send):
    from Models.native_folder import run_native, native_frames
    from Models.frame_store import write_frame_store_iter
    from Models.worker_process_tree import own_process_tree
    own_process_tree()

    timings = {}
    native_enabled = os.environ.get('TRACE_ALPHA_FOLDER_ENGINE', 'python').lower() == 'rust'
    started = time.perf_counter()
    title = 'Identification des Alpha et pharmacies'

    def message(kind, payload):
        if kind == 'progress':
            value = (payload.get('ratio', payload.get('done', 0) / max(payload.get('total', 1), 1))
                     if isinstance(payload, dict) else payload)
            send('progress', value)

    send('step', (title, 'Lecture et classement des traces...', 'read'))
    if request['mode'] == 'folder_catalog':
        if native_enabled:
            catalog = run_native('catalog', request['path'], request['session'], on_message=message)
        else:
            from Models.folder_catalog import catalog_folder
            catalog = catalog_folder(request['path'], lambda ratio: send('progress', ratio))
        send('catalog', catalog)
        send('done', {'timings': {'catalogue': time.perf_counter() - started}})
        return

    from Models.group_analysis import analyze_group
    group = request['group']
    title = group['label']
    directory = Path(request['session']) / ('group-' + str(group['id']) + '-' + request['job_id'])
    native = (run_native('parse_group', request['path'], directory / 'native',
                         sources=group['sources'], on_message=message) if native_enabled else {'sources': group['sources']})
    timings['parsing_rust'] = time.perf_counter() - started if native_enabled else 0
    started = time.perf_counter()
    sources = []
    for index, original in enumerate(native['sources']):
        source = dict(original)
        source.setdefault('filepath', source.get('path', ''))
        source.setdefault('name', Path(source['filepath']).name)
        store = directory / f'source-{index}'
        send('step', (title, f'Lecture trace : {index + 1}/{len(native["sources"])} · {source["name"]}', 'read'))
        if native_enabled:
            count = write_frame_store_iter(native_frames(source), store,
                                          source_metadata={'duplicate_ranges': source.get('duplicate_ranges', [])})
        else:
            from Models.folder_catalog import validate_source
            validate_source(source)
            before = Path(source['filepath']).stat()
            metadata = {}
            tick = time.perf_counter()
            last_progress = [0.0]

            def parsing_progress(done, total):
                now = time.perf_counter()
                if now - last_progress[0] >= 0.1 or done == total:
                    send('progress', (index + done / max(total, 1)) / len(native['sources']))
                    last_progress[0] = now

            frames = parse_file(source['filepath'], min_dt=0.0, source_metadata_output=metadata,
                                progress_cb=parsing_progress)
            timings['parsing_python'] = timings.get('parsing_python', 0) + time.perf_counter() - tick
            after = Path(source['filepath']).stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise OSError('La trace a changé pendant sa lecture : rouvrez le dossier.')
            count = len(frames)
            tick = time.perf_counter()
            write_frame_store(frames, store, release=True, source_metadata=metadata)
            timings['stockage'] = timings.get('stockage', 0) + time.perf_counter() - tick
            del frames
        sources.append(dict(source, store=str(store), group_name=title,
                            identity=group.get('identity', {}), raw_line_count=source['line_count']))
        send('step', (title, f'Conversion des frames : {index + 1}/{len(native["sources"])} ({count} frames)', 'events'))
    timings['conversion'] = time.perf_counter() - started
    started = time.perf_counter()
    send('step', (title, 'Analyse commune des segments...', 'diagnostic'))
    last_step = [None, 0.0]

    def group_progress(phase, index, total, name):
        now = time.perf_counter()
        key = (phase, index)
        if key != last_step[0] or now - last_step[1] >= 0.2:
            label, stage = {'merge': ('Regroupement', 'events'),
                            'analysis': ('Evenements et mesures', 'diagnostic'),
                            'diagnostic': ('Diagnostic', 'diagnostic'),
                            'references': ('References', 'references')}[phase]
            send('step', (title, f'{label} : {index + 1}/{total} · {name}', stage))
            send('progress', index / max(total, 1))
            last_step[:] = [key, now]

    data = analyze_group(sources, directory / 'analysis', group_progress, timings=timings,
                         parallel=os.name == 'nt' and len(sources) > 1)
    timings['analyses_python'] = time.perf_counter() - started
    data.update(name=title, modified_ts=0.0, parse_error='')
    events, diagnostics, references = (data.pop(key) for key in ('events', 'diagnostics', 'references'))
    tick = time.perf_counter()
    data['navigation'] = prepare_navigation(events, diagnostics, references)
    timings['navigation'] = time.perf_counter() - tick
    send('step', (title, "Preparation de l'affichage...", 'display'))
    tick = time.perf_counter()
    send('entry', data)
    for key, items in (('events', events), ('diagnostics', diagnostics), ('references', references)):
        for start in range(0, len(items), 500):
            send(key, items[start:start + 500])
    with FrameStore(data['store']) as frames:
        send('entry_done', {'frames': len(frames), 'events': len(events),
                            'diagnostics': len(diagnostics), 'references': len(references)})
    timings['transmission'] = time.perf_counter() - tick
    send('done', {'timings': timings})


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
