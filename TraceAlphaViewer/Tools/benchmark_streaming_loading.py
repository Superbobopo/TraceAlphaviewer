"""Mesure le worker complet sans Tk, puis compare ses artefacts hors mesure."""
from __future__ import annotations

import argparse
from array import array
import ctypes
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time


APP = Path(__file__).resolve().parents[1]


def json_default(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, array):
        return list(value)
    # Les champs des objets metier sont parcourus sans recopier les dataclasses.
    return vars(value)


ENCODER = json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                           ensure_ascii=True, default=json_default)


def digest(value):
    result = hashlib.sha256()
    for chunk in ENCODER.iterencode(value):
        result.update(chunk.encode('ascii'))
    return result.hexdigest()


def frame_digest(frames):
    result = hashlib.sha256()
    for frame in frames:
        result.update(ENCODER.encode(frame).encode('ascii'))
        result.update(b'\n')
    return result.hexdigest()


def peak_memory():
    if sys.platform != 'win32':
        import resource
        memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return memory if sys.platform == 'darwin' else memory * 1024

    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in (
                'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                'PagefileUsage', 'PeakPagefileUsage')]

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
    parser.add_argument('--source-tree', type=Path,
                        help='Racine applicative figee contenant Models et Parser')
    parser.add_argument('--results-json', type=Path, required=True)
    parser.add_argument('--compare-results', type=Path)
    parser.add_argument('--skip-frame-digest', action='store_true',
                        help='Omettre seulement le parcours des frames apres la mesure')
    parser.add_argument('--resource-mode', choices=('auto', 'reference', 'candidate'), default='auto')
    parser.add_argument('--workers', type=int, choices=(1, 2, 3, 4))
    parser.add_argument('--group-alpha', help='Numero Alpha du groupe de dossier a mesurer')
    parser.add_argument('--navigation-cache', action='store_true', help='Mesurer hors chargement les retours sur vingt blocs')
    args = parser.parse_args()
    path = args.trace.resolve()
    if not path.exists():
        parser.error('Le fichier trace est introuvable')
    source_tree = (args.source_tree or APP).resolve()
    if not all((source_tree / directory).is_dir() for directory in ('Models', 'Parser')):
        parser.error('--source-tree doit contenir Models et Parser')
    sys.path.insert(0, str(source_tree))
    from Models import loading_worker
    from Models.frame_store import FrameStore
    import importlib.util
    spec = importlib.util.spec_from_file_location('_benchmark_memory', APP / 'Models/process_memory.py')
    memory_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(memory_module)
    MemorySampler = memory_module.MemorySampler
    try:
        from Models.resource_policy import detect_resources, budget_for, execution_policy
    except ImportError:
        detect_resources = None
    if 'tkinter' in sys.modules or any(name.startswith('Views.') for name in sys.modules):
        raise AssertionError('Le worker autonome ne doit importer ni Tk ni Views')

    events, diagnostics, references = [], [], []
    entries, entry_counts = [], []
    completed = []

    def send(kind, payload):
        if kind == 'entry':
            entries.append(payload)
        elif kind == 'events':
            events.extend(payload)
        elif kind == 'diagnostics':
            diagnostics.extend(payload)
        elif kind == 'references':
            references.extend(payload)
        elif kind == 'entry_done':
            entry_counts.append(payload)
        elif kind == 'done':
            completed.append(payload)
        elif kind == 'error':
            raise RuntimeError(payload)
        # Les messages de progression anciens et structures sont hors resultat.

    temporary_root = APP / '.trace_work'
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='benchmark-streaming-', dir=temporary_root) as temporary:
        request = {'mode': 'file', 'path': str(path), 'session': temporary, 'job_id': 'benchmark'}
        if path.is_dir():
            from Models.folder_catalog import catalog_folder
            groups = catalog_folder(path)['groups']
            groups = [group for group in groups if not args.group_alpha or
                      (group.get('identity') or {}).get('alpha_number') == args.group_alpha]
            if len(groups) != 1:
                raise ValueError('Selectionner un groupe unique avec --group-alpha')
            request.update(mode='folder_group', group=groups[0])
        policy = {}
        if detect_resources:
            resources = detect_resources()
            size = max((row['bytes'] for row in request['group']['sources']), default=0) if path.is_dir() else path.stat().st_size
            policy = execution_policy(resources, budget_for(resources), request['mode'], size,
                                      candidate=args.resource_mode == 'candidate')
            if args.resource_mode == 'reference':
                policy['max_workers'] = 2 if path.is_dir() else 1
            if args.workers:
                policy['max_workers'] = args.workers
            request['resource_policy'] = policy
        sampler = MemorySampler()
        sampler.__enter__()
        started = time.perf_counter()
        try:
            loading_worker.run(request, send)
            total = time.perf_counter() - started
        finally:
            if MemorySampler:
                sampler.__exit__(None, None, None)
        memory = peak_memory()
        if len(entries) != 1 or len(completed) != 1 or len(entry_counts) != 1:
            raise AssertionError('Le worker doit publier une entree complete et un resultat final')
        entry = entries[0]
        if entry.get('parse_error') or not entry.get('store'):
            raise AssertionError(entry.get('parse_error') or 'Stockage de frames absent')
        timings = dict(completed[0].get('timings', {}), total=total)
        print(f'Worker complet : {total:.3f} s ; pic memoire {memory / 1024**2:.1f} Mio', flush=True)
        for name, seconds in timings.items():
            if name != 'total':
                print(f'  {name}: {seconds:.3f} s', flush=True)

        # Toutes les lectures et empreintes suivantes sont exclues du chronometre.
        with FrameStore(entry['store']) as frames:
            result = {
                'version': 1,
                'frames': len(frames),
                'frame_digest': None if args.skip_frame_digest else frame_digest(frames),
                'events': digest(events),
                'stored_events': digest(frames.read_events()),
                'diagnostics': diagnostics,
                'references': digest(references),
                'measurements': digest(frames.read_measurements()),
                'camera': digest(frames.read_camera_report()),
                'navigation': digest(entry.get('navigation', {})),
                'period': frames.trace_period,
                'metadata': digest(frames.source_metadata),
                'measurement_summary': digest(frames.measurement_summary),
                'entry_counts': entry_counts[0],
            }
        if result['events'] != result['stored_events']:
            raise AssertionError('Les evenements transmis different des evenements stockes')
        expected_counts = {'frames': result['frames'], 'events': len(events),
                           'diagnostics': len(diagnostics), 'references': len(references)}
        if result['entry_counts'] != expected_counts:
            raise AssertionError('Les effectifs publies different des artefacts complets')
        result.update(timings=timings, peak_memory_bytes=memory)
        if args.navigation_cache:
            from Models.resource_policy import ResourceGovernor
            governor = ResourceGovernor(monitor=False)
            indices = [min(result['frames'] - 1, (index * max(1, result['frames'] // 20)) // 500 * 500)
                       for index in range(20)] if result['frames'] else []
            indices = indices * 10
            navigation = {}
            expected = None
            for name, cache_governor in [('deux_blocs', None), ('automatique', governor)]:
                with FrameStore(entry['store'], cache_governor=cache_governor) as frames:
                    started_navigation = time.perf_counter()
                    observations = [frames[index].line_num for index in indices]
                    elapsed = time.perf_counter() - started_navigation
                    navigation[name] = dict(seconds=elapsed, hits=frames.cache_hits,
                        misses=frames.cache_misses, extra_bytes=sum(governor._caches.values()))
                    if expected is not None and observations != expected:
                        raise AssertionError('Navigation differente avec le cache automatique')
                    expected = observations
            result['navigation_benchmark'] = navigation
        if MemorySampler:
            result['process_tree_memory'] = sampler.result()
            result['resource_policy'] = policy
        args.results_json.parent.mkdir(parents=True, exist_ok=True)
        args.results_json.write_text(json.dumps(result, default=json_default,
                                     ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Empreintes hors mesure terminees : {result["frames"]} frames, '
              f'{len(diagnostics)} diagnostics, {len(references)} references', flush=True)

    if args.compare_results:
        previous = json.loads(args.compare_results.read_text(encoding='utf-8'))
        actual = json.loads(args.results_json.read_text(encoding='utf-8'))
        ignored = {'timings', 'peak_memory_bytes', 'process_tree_memory', 'resource_policy', 'navigation_benchmark'}
        differences = [key for key in sorted((set(previous) | set(actual)) - ignored)
                       if previous.get(key) != actual.get(key)]
        if differences:
            raise AssertionError('Resultats differents : ' + ', '.join(differences))
        print('Tous les artefacts sont identiques a la reference.', flush=True)
        print(f'Gain worker x{previous["timings"]["total"] / total:.2f} ; '
              f'memoire x{previous["peak_memory_bytes"] / max(memory, 1):.2f}', flush=True)


if __name__ == '__main__':
    main()
