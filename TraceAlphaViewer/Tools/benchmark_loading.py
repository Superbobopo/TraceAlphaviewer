"""Mesure l'ouverture complete et compare les analyses a une version Git."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))


def _load_revision(revision: str) -> None:
    commit = subprocess.check_output(
        ['git', 'rev-parse', '--verify', f'{revision}^{{commit}}'], cwd=ROOT,
        encoding='utf-8',
    ).strip()
    # Seuls les trois modules optimises sont remplaces, sans changer le depot.
    for name in ('Models.diagnostic', 'Models.reference_index', 'Widgets.trace_panel'):
        path = 'TraceAlphaViewer/' + name.replace('.', '/') + '.py'
        source = subprocess.check_output(['git', 'show', f'{commit}:{path}'], cwd=ROOT)
        module = ModuleType(name)
        module.__file__ = str(ROOT / path)
        sys.modules[name] = module
        exec(compile(source, module.__file__, 'exec'), module.__dict__)


def _json_default(value):
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f'Type non exportable : {type(value).__name__}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--revision', help='Version Git des trois modules, chargee en memoire')
    parser.add_argument('--results-json', type=Path, help='Resultats complets a conserver localement')
    parser.add_argument('--compare-results', type=Path, help='Resultats precedents a verifier')
    parser.add_argument('--show', action='store_true', help='Afficher la fenetre pendant la mesure')
    parser.add_argument('--timeout', type=float, default=120, help='Delai maximal du texte brut (s)')
    args = parser.parse_args()
    path = args.trace.resolve()
    if not path.is_file():
        parser.error('Le fichier trace est introuvable')
    if args.timeout <= 0:
        parser.error('Le delai doit etre positif')
    if args.revision:
        _load_revision(args.revision)

    import customtkinter as ctk
    from Models.diagnostic import build_diagnostics
    from Models.reference_index import build_reference_records
    from Parser.trace_parser import parse_file
    from Views.accueilView import _collect_events
    from Views.traceView import TraceView

    timings = {}

    def measure(label, operation):
        start = time.perf_counter()
        result = operation()
        timings[label] = time.perf_counter() - start
        print(f'{label} : {timings[label]:.3f} s', flush=True)
        return result

    print(f'Trace : {path.name} | version : {args.revision or "travail courant"}', flush=True)
    started = time.perf_counter()
    frames = measure('parsing', lambda: parse_file(str(path), min_dt=0.0))
    events = measure('evenements', lambda: _collect_events(frames))
    diagnostics = measure('diagnostics', lambda: build_diagnostics(frames, events))
    references = measure('references', lambda: build_reference_records(frames, events))
    root = None
    view = None
    try:
        def prepare():
            nonlocal root, view
            root = ctk.CTk()
            if not args.show:
                root.withdraw()
            root.geometry('1500x860')
            view = TraceView(root, str(path), frames, events=events,
                             diagnostics=diagnostics, references=references)
            view.show()

        measure('preparation_vue', prepare)

        def load_text():
            deadline = time.perf_counter() + args.timeout
            while view._trace_panel._loading:
                if time.perf_counter() >= deadline:
                    raise TimeoutError('Le chargement de la trace brute ne se termine pas')
                root.update()
                time.sleep(0.005)
            root.update()
            return view._trace_panel._total_lines

        total_lines = measure('texte_brut', load_text)
        timings['total'] = time.perf_counter() - started
        print(f'Total : {timings["total"]:.3f} s | {len(frames)} frames | '
              f'{len(events)} evenements | {len(diagnostics)} diagnostics | '
              f'{len(references)} references | {total_lines} lignes', flush=True)
    finally:
        if view is not None:
            view.destroy()
        if root is not None:
            root.destroy()

    stat = path.stat()
    results = {
        'source': {'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns},
        'frames': len(frames), 'events': len(events), 'lines': total_lines,
        'diagnostics': [asdict(item) for item in diagnostics],
        'references': [asdict(item) for item in references],
    }
    # Normalise les ensembles avant la comparaison avec un export JSON.
    results = json.loads(json.dumps(results, default=_json_default))
    if args.compare_results:
        previous = json.loads(args.compare_results.read_text(encoding='utf-8'))
        for key, value in results.items():
            if previous[key] != value:
                raise AssertionError(f'Regression : resultats differents pour {key}')
        ratio = previous['timings']['total'] / max(timings['total'], 1e-9)
        print(f'Resultats integralement identiques | acceleration : x{ratio:.2f}', flush=True)
    if args.results_json:
        results['timings'] = timings
        args.results_json.parent.mkdir(parents=True, exist_ok=True)
        args.results_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
