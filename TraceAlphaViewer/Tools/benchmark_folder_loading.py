"""Compare les deux moteurs sur un meme bilan de dossier, sans interface."""
from dataclasses import asdict
import argparse
import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.native_folder import native_frames, run_native
from Models.frame_store import FrameStore, write_frame_store, write_frame_store_iter
from Models.group_analysis import analyze_group
from Parser.trace_parser import parse_file


def measure(group, directory, mode):
    started = time.perf_counter()
    sources = group['sources']
    phases = {}
    if mode == 'rust':
        sources = run_native('parse_group', ROOT, directory / 'native', sources=sources)['sources']
    phases['parsing'] = time.perf_counter() - started if mode == 'rust' else 0
    converted = []
    phases['stockage_conversion'] = 0
    for index, source in enumerate(sources):
        store = directory / f'source-{index}'
        metadata = {}
        if mode == 'python':
            tick = time.perf_counter()
            frames = parse_file(source['filepath'], min_dt=0.0, source_metadata_output=metadata)
            phases['parsing'] += time.perf_counter() - tick
        tick = time.perf_counter()
        if mode == 'rust':
            write_frame_store_iter(native_frames(source), store,
                source_metadata={'duplicate_ranges': source.get('duplicate_ranges', [])})
        else:
            write_frame_store(frames, store, release=True, source_metadata=metadata)
            del frames
        phases['stockage_conversion'] += time.perf_counter() - tick
        converted.append(dict(source, store=str(store), group_name=group['label']))
    tick = time.perf_counter()
    result = analyze_group(converted, directory / 'analysis')
    phases['analyses'] = time.perf_counter() - tick
    phases['total'] = time.perf_counter() - started
    # La comparaison et le nettoyage sont exclus des durees.
    with FrameStore(result['store']) as frames:
        value = {'events': [asdict(row) for row in result['events']],
                 'diagnostics': [asdict(row) for row in result['diagnostics']],
                 'references': [asdict(row) for row in result['references']],
                 'measurements': frames.read_measurements(), 'camera': frames.read_camera_report()}
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, default=sorted).encode()).hexdigest()
    gc.collect()
    return phases, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--group', required=True, help='Fragment du libelle du groupe')
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    results = {'python': [], 'rust': []}
    with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='folder-benchmark-') as temporary:
        base = Path(temporary)
        tick = time.perf_counter()
        catalog = run_native('catalog', args.directory, base / 'catalog')
        catalog_seconds = time.perf_counter() - tick
        groups = [row for row in catalog['groups'] if args.group.casefold() in row['label'].casefold()]
        if len(groups) != 1:
            raise SystemExit('Le filtre doit designer un groupe unique')
        group = groups[0]
        expected = None
        for run in range(args.runs):
            for mode in (('python', 'rust') if run % 2 == 0 else ('rust', 'python')):
                timings, digest = measure(group, base / f'{run}-{mode}', mode)
                if expected is not None and expected != digest:
                    raise AssertionError('Les bilans des deux moteurs different')
                expected = digest
                results[mode].append(timings)
                print(mode, run + 1, json.dumps(timings), flush=True)
        results.update(catalog_seconds=catalog_seconds, group=group['label'], sources=len(group['sources']))
    results['median_seconds'] = {mode: statistics.median(row['total'] for row in results[mode])
                                 for mode in ('python', 'rust')}
    results['speedup'] = results['median_seconds']['python'] / results['median_seconds']['rust']
    if args.output:
        args.output.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results['median_seconds']), f"gain x{results['speedup']:.2f}", flush=True)


if __name__ == '__main__':
    main()
