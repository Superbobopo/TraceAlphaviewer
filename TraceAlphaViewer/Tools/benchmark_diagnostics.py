"""Mesure les diagnostics sans profileur et compare tous leurs resultats."""
from pathlib import Path
from dataclasses import asdict, is_dataclass
import argparse
import ctypes
import hashlib
import json
import sys
import tempfile
import time
from types import ModuleType
from array import array

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'TraceAlphaViewer'))


def json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, array):
        return list(value)
    if type(value).__name__ == 'LineIndex':
        return vars(value)
    raise TypeError(type(value).__name__)


def digest(value):
    result = hashlib.sha256()
    for chunk in json.JSONEncoder(sort_keys=True, default=json_default).iterencode(value):
        result.update(chunk.encode('utf-8'))
    return result.hexdigest()


def peak_memory():
    if sys.platform != 'win32':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
            'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess
    process.restype = ctypes.c_void_p
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if not get_info(process(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return counters.PeakWorkingSetSize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--baseline-dir', type=Path)
    parser.add_argument('--results-json', type=Path, required=True)
    parser.add_argument('--compare-results', type=Path)
    parser.add_argument('--full', action='store_true', help='Inclure references, identite et stockage du chargement')
    args = parser.parse_args()
    if args.baseline_dir:
        import Models
        for name in ('robot_drain', 'trace_calendar', 'c2_analysis', 'c5_analysis',
                     'trace_observations', 't5_drive_analysis', 'diagnostic'):
            path = args.baseline_dir/f'{name}.py'
            module = ModuleType('Models.' + name)
            module.__file__ = str(path.resolve())
            sys.modules[module.__name__] = module
            setattr(Models, name, module)
            exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    from Parser.trace_parser import parse_file
    from Models.loading_worker import _collect_events, prepare_navigation
    from Models.measurement_analysis import analyze_measurements
    from Models.robot_drain import read_trace_origin
    import Models.diagnostic as diagnostic
    timings, families, depth = {}, {}, [0]
    for name in list(vars(diagnostic)):
        fn = getattr(diagnostic, name)
        if not callable(fn) or not (name.startswith('_build_') or name in ('_frame_line_states', '_camera_stats')):
            continue
        def wrapped(*values, _fn=fn, _name=name, **kwargs):
            start = time.perf_counter()
            outer = depth[0] == 0
            depth[0] += 1
            try:
                return _fn(*values, **kwargs)
            finally:
                depth[0] -= 1
                if outer:
                    families[_name] = families.get(_name, 0) + time.perf_counter() - start
        setattr(diagnostic, name, wrapped)
    def measure(label, operation):
        start = time.perf_counter()
        value = operation()
        timings[label] = time.perf_counter() - start
        print(f'{label}: {timings[label]:.3f} s', flush=True)
        return value
    started = time.perf_counter()
    metadata = {}
    frames = measure('parsing', lambda: parse_file(str(args.trace), min_dt=0.0, source_metadata_output=metadata))
    count = len(frames)
    events = measure('evenements', lambda: _collect_events(frames))
    analysis = measure('mesures', lambda: analyze_measurements(frames))
    camera, period = {}, {}
    incidents = measure('diagnostics', lambda: diagnostic.build_diagnostics(frames, events, analysis,
        camera_report_output=camera, trace_origin=read_trace_origin(args.trace), trace_metadata_output=period))
    references = []
    navigation = {}
    if args.full:
        from Models.reference_index import build_reference_records
        from Models.folder_catalog import read_source_identity
        from Models.frame_store import write_frame_store
        references = measure('references', lambda: build_reference_records(frames, events))
        metadata['identity'] = measure('identite', lambda: read_source_identity(args.trace))
        navigation = measure('navigation', lambda: prepare_navigation(events, incidents, references))
        with tempfile.TemporaryDirectory(dir=ROOT/'TraceAlphaViewer/.trace_work') as temporary:
            measure('stockage', lambda: write_frame_store(frames, Path(temporary), release=True,
                measurement_summary=analysis['summary'], trace_period=period, source_metadata=metadata))
    timings['total'] = time.perf_counter() - started
    memory = peak_memory()
    result = {'frames': count, 'events': digest(events), 'diagnostics': [asdict(row) for row in incidents],
        'measurements': digest(analysis), 'camera': digest(camera), 'references': digest(references),
        'navigation': digest(navigation), 'period': period, 'metadata': digest(metadata)}
    if args.compare_results:
        previous = json.loads(args.compare_results.read_text(encoding='utf-8'))
        for key, value in result.items():
            if previous[key] != value:
                raise AssertionError(f'Resultats differents : {key}')
        print('Resultats integralement identiques', flush=True)
        print(f"Gain diagnostic x{previous['timings']['diagnostics']/timings['diagnostics']:.2f}", flush=True)
    result.update(timings=timings, diagnostic_families=families, peak_memory_bytes=memory)
    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    args.results_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Total {timings["total"]:.3f} s ; pic memoire {memory/1024**2:.1f} Mio', flush=True)
    for name, seconds in sorted(families.items(), key=lambda row: -row[1]):
        print(f'  {name}: {seconds:.3f} s', flush=True)


if __name__ == '__main__':
    main()
