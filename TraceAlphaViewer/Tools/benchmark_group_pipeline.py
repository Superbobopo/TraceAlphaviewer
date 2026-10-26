"""Mesure un groupe complet et conserve une reference locale comparable."""
from pathlib import Path
import argparse
import ast
from dataclasses import asdict
import hashlib
import json
import pickle
import shutil
import sys
import time


ROOT = Path(__file__).resolve().parents[2]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=sorted,
                                    ensure_ascii=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--snapshot', action='store_true')
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--filters', action='store_true')
    parser.add_argument('--reuse-filter-checks', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_root = ROOT / 'TraceAlphaViewer'
    if args.snapshot:
        snapshot = output / 'sources'
        for folder in ('Models', 'Parser', 'Widgets', 'Views'):
            shutil.copytree(source_root / folder, snapshot / folder,
                            ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
        source_root = snapshot
    sys.path.insert(0, str(source_root))
    from Models.folder_catalog import catalog_folder
    from Models.loading_worker import run
    from Models.frame_store import FrameStore
    from Models.diagnostic_report import build_report_payload
    from Models.group_analysis import build_group_business_events

    timings = {}
    started = time.perf_counter()
    catalog = catalog_folder(args.directory)
    timings['catalogue'] = time.perf_counter() - started
    if len(catalog['groups']) != 1:
        raise ValueError('Ce benchmark attend un groupe unique')
    data = {'events': [], 'diagnostics': [], 'references': []}

    def receive(kind, payload):
        if kind == 'step':
            print(payload[1], flush=True)
        elif kind == 'entry':
            data.update(payload)
        elif kind in ('events', 'diagnostics', 'references'):
            data[kind].extend(payload)
        elif kind == 'done':
            timings.update(payload.get('timings', {}))

    started = time.perf_counter()
    run({'mode': 'folder_group', 'path': str(args.directory), 'session': str(output / 'session'),
         'job_id': 'benchmark', 'group': catalog['groups'][0]}, receive)
    timings['groupe'] = time.perf_counter() - started
    print(json.dumps({'timings_pipeline': timings}), flush=True)
    with (output / 'result.pkl').open('wb') as stream:
        pickle.dump(data, stream, protocol=pickle.HIGHEST_PROTOCOL)
    checks = {key: digest([asdict(row) for row in data[key]])
              for key in ('events', 'diagnostics', 'references')}
    with FrameStore(data['store']) as frames:
        started = time.perf_counter()
        report = build_report_payload(data['diagnostics'], frames=frames,
                                      source_name=data['name'])
        timings['rapport'] = time.perf_counter() - started
        checks.update(measurements=digest(frames.read_measurements()),
                      cameras=digest(frames.read_camera_report()))
        if args.filters:
            checks['filters'] = {belt: digest([asdict(row) for row in
                build_group_business_events(frames, data['events'], belt)])
                for belt in ('T0', 'T1', 'T2', 'T3', 'T4', 'T5')}
        if args.compare:
            with (args.compare / 'result.pkl').open('rb') as stream:
                before = pickle.load(stream)
            with FrameStore(before['store']) as previous:
                if len(previous) != len(frames):
                    raise AssertionError('Nombre de frames different')
                for index, (old, new) in enumerate(zip(previous, frames)):
                    if old != new:
                        raise AssertionError(f'Frame differente : {index}')
        report_info = [{'code': g['code'], 'incidents': g['incident_count'],
                        'occurrences': g['occurrence_count'], 'examples': len(g['examples'])}
                       for g in report['groups']]
        counts = {'frames': len(frames), **{key: len(data[key]) for key in
                  ('events', 'diagnostics', 'references')}}
    result = dict(timings=timings, checks=checks, counts=counts, report=report_info)
    if args.compare:
        before = json.loads((args.compare / 'summary.json').read_text())
        if args.reuse_filter_checks:
            if checks['events'] != before['checks']['events']:
                raise AssertionError('Les evenements des filtres ont change')
            old_root = args.compare / 'sources' / 'Models'
            new_root = source_root / 'Models'
            if (old_root / 'event_cycles.py').read_bytes() != (new_root / 'event_cycles.py').read_bytes():
                raise AssertionError('Le moteur des filtres a change : relancer --filters')
            def filter_code(path):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                return [ast.dump(node) for node in tree.body if getattr(node, 'name', '') in
                        ('_SegmentFrames', 'build_group_business_events')]
            if filter_code(old_root / 'group_analysis.py') != filter_code(new_root / 'group_analysis.py'):
                raise AssertionError('Le parcours des filtres a change : relancer --filters')
            checks['filters'] = before['checks']['filters']
            result['filter_validation'] = 'Resultats reutilises : toutes les frames et evenements identiques, moteur et parcours inchanges'
        if checks != before['checks']:
            raise AssertionError('Les analyses ou filtres different de la reference')
    (output / 'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(dict(timings=timings, counts=counts)), flush=True)


if __name__ == '__main__':
    main()
