"""Mesure le rapport sur une session locale de benchmark, sans profileur."""
from pathlib import Path
import argparse
import json
import pickle
import statistics
import sys
import time
import subprocess
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--prepare', type=Path)
    parser.add_argument('--refresh-camera', action='store_true')
    parser.add_argument('--label', required=True)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--revision')
    args = parser.parse_args()
    if args.revision:
        revision = subprocess.check_output(['git', 'rev-parse', '--verify', args.revision + '^{commit}'],
                                           cwd=ROOT, text=True).strip()
        for name in ('Models.diagnostic', 'Models.frame_store', 'Models.diagnostic_report', 'Models.loading_worker'):
            path = 'TraceAlphaViewer/' + name.replace('.', '/') + '.py'
            source = subprocess.check_output(['git', 'show', f'{revision}:{path}'], cwd=ROOT)
            module = ModuleType(name)
            module.__file__ = str(ROOT / path)
            sys.modules[name] = module
            exec(compile(source, module.__file__, 'exec'), module.__dict__)
    from Models.frame_store import FrameStore
    from Models.diagnostic_report import write_diagnostic_report
    if args.prepare:
        from Models.loading_worker import run
        diagnostics = []
        def receive(kind, payload):
            if kind == 'diagnostics':
                diagnostics.extend(payload)
            elif kind == 'step':
                print(payload[1], flush=True)
        run({'mode': 'file', 'path': str(args.prepare.resolve()),
             'session': str(args.session.resolve())}, receive)
        with (args.session / 'diagnostics.pkl').open('wb') as output:
            pickle.dump(diagnostics, output)
    with (args.session / 'diagnostics.pkl').open('rb') as source:
        diagnostics = pickle.load(source)
    directory = args.session / 'entry-0'
    if args.refresh_camera:
        from Models.diagnostic import camera_report_stats
        with FrameStore(directory) as frames:
            stats = camera_report_stats(frames)
        with (directory / 'camera_report.pkl').open('wb') as output:
            pickle.dump(stats, output)
    class CountedStore(FrameStore):
        loads = 0
        def __getitem__(self, index):
            if isinstance(index, int):
                normalized = index if index >= 0 else len(self) + index
                if 0 <= normalized < len(self) and normalized // 500 not in self._cache:
                    self.loads += 1
            return super().__getitem__(index)
    results = []
    for attempt in range(args.runs):
        with CountedStore(directory) as frames:
            started = time.perf_counter()
            path = write_diagnostic_report(diagnostics, args.session / args.label, frames)
            elapsed = time.perf_counter() - started
            data_path = path.with_name(path.name.replace('diagnostic_report_', 'report_data_')).with_suffix('.json')
            data = json.loads(data_path.read_text(encoding='utf-8'))
            result = {'seconds': elapsed, 'block_loads': frames.loads,
                      'html_bytes': path.stat().st_size, 'json_bytes': data_path.stat().st_size,
                      'examples': sum(len(g['examples']) for g in data['groups']),
                      'counts': data['counts'], 'unknown': {key: value for key, value in
                          data.get('unknown', {}).items() if key in ('count', 'total', 'ratio', 'buckets')}}
            results.append(result)
            print(json.dumps(dict(attempt=attempt + 1, **result), ensure_ascii=True), flush=True)
    output = {'runs': results, 'median_seconds': statistics.median(r['seconds'] for r in results)}
    (args.session / (args.label + '.json')).write_text(json.dumps(output, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
