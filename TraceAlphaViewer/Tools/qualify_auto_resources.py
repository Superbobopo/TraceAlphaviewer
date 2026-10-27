"""Qualification locale repetee, sans activer ni enregistrer un profil."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys


APP = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('traces', type=Path)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reuse', action='store_true', help='Reutiliser des controles deja acquis si leurs sources sont inchangees')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = {'monistrol': args.traces / 'TracAlpha1_monistrol.txt',
             'astier': args.traces / 'astier/TracAlpha1_009.txt',
             'atout': args.traces / 'atout sud/TracAlpha1.txt',
             'lahlou': args.traces / 'lahlou'}
    summary = {}
    for name, path in cases.items():
        samples = {'reference': [], 'candidate': []}
        for index in range(1, 4):
            for mode in samples:
                result = args.output / f'auto-ui-{name}-{mode}-{index}.json'
                log = result.with_suffix('.log')
                folder = name == 'lahlou'
                reusable = args.reuse and result.exists()
                if reusable and folder:
                    reusable = 'ui_latency' in json.loads(result.read_text(encoding='utf-8'))
                if not reusable:
                    command = [sys.executable, str(APP / 'Tools/benchmark_loading.py'),
                        str(path), '--resource-mode', mode, '--results-json', str(result)]
                    if mode == 'reference':
                        command += ['--source-tree', str(args.baseline)]
                    if folder:
                        command += ['--group-alpha', '031']
                    command += ['--ui-latency', '--exercise-window', '--check-navigation',
                                '--measure-memory', '--timeout', '360']
                    reference = args.output / f'auto-ui-{name}-reference-1.json'
                    if reference.exists():
                        command += ['--compare-results', str(reference)]
                    print(f'{name} {mode} {index}/3', flush=True)
                    with log.open('w', encoding='utf-8') as output:
                        subprocess.run(command, cwd=APP, stdout=output,
                                       stderr=subprocess.STDOUT, check=True, timeout=900)
                data = json.loads(result.read_text(encoding='utf-8'))
                samples[mode].append(data)
        medians = {mode: statistics.median(row['timings']['total'] for row in rows)
                   for mode, rows in samples.items()}
        gain = 1 - medians['candidate'] / medians['reference']
        summary[name] = {'median_seconds': medians, 'gain': gain,
            'qualified': gain >= .1,
            'samples': {mode: [row['timings']['total'] for row in rows] for mode, rows in samples.items()},
            'memory': {mode: [row.get('ui_latency', {}).get('process_tree_memory',
                             row.get('process_tree_memory')) for row in rows]
                       for mode, rows in samples.items()},
            'responsive': all(row.get('ui_latency', {}).get('p95_ms', 0) < 100 and
                              row.get('ui_latency', {}).get('max_ms', 0) < 500
                              for row in samples['candidate'])}
        (args.output / 'auto-qualification.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'{name}: gain median {gain:.1%}', flush=True)


if __name__ == '__main__':
    main()
