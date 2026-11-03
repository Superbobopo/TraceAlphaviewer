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
import hashlib


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))


def _load_revision(revision: str) -> None:
    commit = subprocess.check_output(
        ['git', 'rev-parse', '--verify', f'{revision}^{{commit}}'], cwd=ROOT,
        encoding='utf-8',
    ).strip()
    # Les modules concernes sont charges depuis Git sans changer le depot.
    for name in ('Models.diagnostic', 'Models.reference_index', 'Models.folder_report',
                 'Widgets.trace_panel', 'Widgets.event_panel', 'Widgets.reference_panel',
                 'Widgets.diagnostic_panel', 'Views.BaseView', 'Views.traceView', 'Views.accueilView'):
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


def frame_digest(frames):
    digest = hashlib.sha256()
    for frame in frames:
        value = json.dumps(asdict(frame), sort_keys=True, separators=(',', ':'),
                           default=_json_default, ensure_ascii=True)
        digest.update(value.encode('utf-8'))
        digest.update(b'\n')
    return digest.hexdigest()


def measure_ui(path, timeout, show, exercise_window, screenshot=None, check_navigation=False,
               measure_memory=False, group=None):
    from Main import TraceAlphaViewer
    from Views.traceView import TraceView

    app = TraceAlphaViewer()
    if not show:
        app.withdraw()
    app.update_idletasks()
    home = app.main_view
    started = None
    last_beat = None
    gaps = []
    peaks = []
    phase = 'read'
    completed = False
    error = None
    prepare_started = None
    displayed = None
    geometry_step = 0
    progress_last = 0.
    progress_samples = 0
    sampler = None
    preloaded_raw = False
    if measure_memory:
        import importlib.util
        spec = importlib.util.spec_from_file_location('_benchmark_memory', ROOT / 'TraceAlphaViewer/Models/process_memory.py')
        memory_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(memory_module)
        sampler = memory_module.MemorySampler()

    def begin():
        nonlocal started, last_beat, preloaded_raw
        if sampler:
            sampler.__enter__()
        started = last_beat = time.perf_counter()
        if group is None:
            home._load(str(path))
            preloaded_raw = getattr(home, '_preloaded_trace', None) is not None
        else:
            from unittest.mock import patch
            from Models.loading_client import LoadingSession
            original = LoadingSession.start
            def start_group(session, mode, **arguments):
                return original(session, 'folder_group', **dict(arguments, group=group))
            # Le groupe rejoint le meme TraceView, avec son vrai worker et sa trace brute.
            with patch.object(LoadingSession, 'start', start_group):
                home._load(str(path))

    def beat():
        nonlocal last_beat, completed, error, phase, prepare_started, displayed, progress_last, progress_samples
        now = time.perf_counter()
        if started is not None:
            gap = now - last_beat
            gaps.append(gap)
            if gap > 0.1:
                peaks.append((round(gap, 3), phase))
            last_beat = now
            view = app.main_view
            tracker = getattr(home, '_progress_tracker', None)
            if tracker is not None:
                fraction = tracker.fraction
                if fraction < progress_last or (fraction >= 1 and not isinstance(view, TraceView)):
                    error = 'Progression en recul ou terminee avant le viewer'
                    app.quit()
                    return
                progress_last = fraction
                progress_samples += 1
            if isinstance(view, TraceView):
                if displayed is None:
                    displayed = now
                phase = 'texte_brut'
                if not view._trace_panel._loading:
                    completed = True
                    app.quit()
                    return
            else:
                phase = home._progress_step_lbl.cget('text')
                if getattr(home, '_prepared_view', None) is not None and prepare_started is None:
                    prepare_started = now
                if not getattr(home, '_load_busy', False):
                    error = home._progress_lbl.cget('text')
                    app.quit()
                    return
            if now - started > timeout:
                error = 'Delai de chargement depasse'
                app.quit()
                return
        app.after(10, beat)

    def move_window():
        nonlocal geometry_step
        if exercise_window and started is not None and not completed:
            geometry_step += 1
            app.geometry(f'{1500 + (geometry_step % 2) * 10}x860+{20 + (geometry_step % 4) * 15}+20')
            if show and geometry_step % 25 == 0:
                app.iconify()
                app.after(80, app.deiconify)
        app.after(300, move_window)

    app.after(150, begin)
    app.after(10, beat)
    if exercise_window:
        app.after(300, move_window)
    try:
        app.mainloop()
        total = time.perf_counter() - started
        if sampler:
            sampler.__exit__(None, None, None)
        if not completed:
            raise RuntimeError(error or 'Le chargement ne se termine pas')
        view = app.main_view
        timings = dict(getattr(home, '_load_timings', {}))
        timings['preparation_vue'] = (displayed - prepare_started) if prepare_started else 0.0
        timings['texte_brut'] = time.perf_counter() - displayed
        preparation = getattr(view, 'preparation_timings', {})
        if 'affichage' in preparation:
            # La trace brute et les panneaux se preparent maintenant ensemble.
            timings['preparation_vue'] = preparation['affichage']
            timings['texte_brut'] = preparation.get('texte_brut', 0.)
            timings['preparation_complete'] = preparation['total']
        timings['total'] = total
        ordered = sorted(gaps)
        latency = {'p95_ms': ordered[int((len(ordered) - 1) * 0.95)] * 1000,
                   'max_ms': max(gaps) * 1000, 'samples': len(gaps),
                   'peaks': sorted(peaks, reverse=True)[:12], 'window_operations': geometry_step,
                   'preloaded_raw': preloaded_raw}
        if progress_samples:
            if progress_last != 1:
                raise AssertionError('La progression ne termine pas a 100 %')
            latency['progress'] = {'samples': progress_samples, 'monotonic': True, 'ready': progress_last}
        if sampler:
            latency['process_tree_memory'] = sampler.result()
        if check_navigation:
            check_view_navigation(app, view)
        if screenshot:
            from PIL import ImageGrab
            app.deiconify()
            app.update()
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            if sys.platform != 'win32':
                raise RuntimeError('La capture de la fenetre est disponible sous Windows uniquement')
            # Capturer le HWND du viewer, jamais le bureau ou une autre application.
            ImageGrab.grab(window=app.winfo_id()).save(screenshot)
        session = getattr(view, '_load_session', None)
        # Le benchmark garde les fichiers pendant son eventuelle empreinte.
        view._load_session = None
        return (view._frames, view._events, view._diagnostics, view._references,
                view._trace_panel._total_lines, timings, latency, session)
    finally:
        if sampler and getattr(sampler, 'thread', None) and sampler.thread.is_alive():
            sampler.__exit__(None, None, None)
        app.destroy()
        if not completed:
            session = getattr(home, '_load_session', None)
            if session is not None:
                session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--revision', help='Version Git des modules concernes, chargee en memoire')
    parser.add_argument('--source-tree', type=Path, help='Copie locale des sources servant de reference')
    parser.add_argument('--resource-mode', choices=('auto', 'reference', 'candidate'), default='auto')
    parser.add_argument('--measure-memory', action='store_true', help='Mesurer aussi la memoire simultanee du processus et de ses descendants')
    parser.add_argument('--group-alpha', help='Selectionner un groupe de dossier pour mesurer son ouverture complete')
    parser.add_argument('--results-json', type=Path, help='Resultats complets a conserver localement')
    parser.add_argument('--compare-results', type=Path, help='Resultats precedents a verifier')
    parser.add_argument('--show', action='store_true', help='Afficher la fenetre pendant la mesure')
    parser.add_argument('--timeout', type=float, default=120, help='Delai maximal du texte brut (s)')
    parser.add_argument('--ui-latency', action='store_true', help="Mesurer l'ouverture reelle depuis l'accueil")
    parser.add_argument('--exercise-window', action='store_true', help='Deplacer, redimensionner et reduire la fenetre')
    parser.add_argument('--frame-digest', action='store_true', help='Empreinte de tous les champs de toutes les frames')
    parser.add_argument('--verify-frames', action='store_true', help='Comparer toutes les frames au parser direct hors mesure')
    parser.add_argument('--verify-analyses', action='store_true', help='Comparer filtres et rapport entre stockage et liste hors mesure')
    parser.add_argument('--require-responsive', action='store_true', help='Exiger p95 <100ms et maximum <500ms')
    parser.add_argument('--check-navigation', action='store_true', help='Verifier navigation, recherche CIP et lecture hors mesure')
    parser.add_argument('--screenshot', type=Path, help='Capture locale du viewer charge')
    args = parser.parse_args()
    path = args.trace.resolve()
    if not path.exists() or (path.is_dir() and not args.group_alpha):
        parser.error('Le fichier trace est introuvable')
    if args.timeout <= 0:
        parser.error('Le delai doit etre positif')
    if args.source_tree:
        if args.revision or not (args.source_tree / 'Models').is_dir():
            parser.error('--source-tree attend une copie des sources, sans --revision')
        sys.path.insert(0, str(args.source_tree.resolve()))
    if args.revision:
        _load_revision(args.revision)
    if args.resource_mode != 'auto':
        try:
            from Models import resource_policy
        except ImportError:
            if args.resource_mode == 'candidate':
                raise
        else:
            resource_policy.QUALIFIED_FILE_MIN_BYTES = 0 if args.resource_mode == 'candidate' else None
            resource_policy.QUALIFIED_FOLDER_WORKERS = 4 if args.resource_mode == 'candidate' else 2
            resource_policy._governor = resource_policy.ResourceGovernor(limit=None)

    if args.exercise_window and not args.ui_latency:
        parser.error('--exercise-window exige --ui-latency')
    if args.require_responsive and not args.ui_latency:
        parser.error('--require-responsive exige --ui-latency')
    if (args.verify_frames or args.verify_analyses) and not args.ui_latency:
        parser.error('--verify-frames et --verify-analyses exigent --ui-latency')
    if (args.check_navigation or args.screenshot) and not args.ui_latency:
        parser.error('--check-navigation et --screenshot exigent --ui-latency')
    if args.ui_latency:
        group = None
        if path.is_dir():
            from Models.folder_catalog import catalog_folder
            groups = [item for item in catalog_folder(path)['groups']
                      if (item.get('identity') or {}).get('alpha_number') == args.group_alpha]
            if len(groups) != 1:
                parser.error('Le numero Alpha doit selectionner exactement un groupe')
            group = groups[0]
        values = measure_ui(path, args.timeout, args.show,
                            args.exercise_window, args.screenshot, args.check_navigation, args.measure_memory, group)
        frames, events, diagnostics, references, total_lines, timings, latency, session = values
        try:
            print(f'Total : {timings["total"]:.3f} s | p95 : {latency["p95_ms"]:.1f} ms | '
                  f'maximum : {latency["max_ms"]:.1f} ms', flush=True)
            print('Pauses >100ms : ' + str(latency['peaks']), flush=True)
            digest = frame_digest(frames) if args.frame_digest else None
            save_results(args, path, frames, events, diagnostics, references, total_lines,
                         timings, latency=latency, digest=digest)
            if args.verify_frames or args.verify_analyses:
                verify_storage(path, frames, events, diagnostics, args.verify_analyses)
            if args.require_responsive and (latency['p95_ms'] >= 100 or latency['max_ms'] >= 500):
                raise AssertionError('Les objectifs de reactivite ne sont pas atteints')
        finally:
            if session is not None:
                session.close()
                if not session.cleaned.wait(15):
                    raise RuntimeError('Le nettoyage de la session ne se termine pas')
                if session.cleanup_error:
                    raise RuntimeError(session.cleanup_error)
        return

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

    digest = frame_digest(frames) if args.frame_digest else None
    save_results(args, path, frames, events, diagnostics, references, total_lines, timings, digest=digest)


def check_view_navigation(app, view):
    view._go_end()
    if view._idx != len(view._frames) - 1:
        raise AssertionError('Navigation derniere frame incorrecte')
    if view._references:
        record = next((item for item in view._references if item.barcode.isdigit()), view._references[0])
        view._on_reference_click(record)
        panel = view._trace_panel
        panel._search_var.set(record.barcode)
        deadline = time.perf_counter() + 30
        while panel._search_job is not None and time.perf_counter() < deadline:
            app.update()
            time.sleep(0.003)
        if panel._search_job is not None or not panel._search_matches:
            raise AssertionError('La recherche CIP ne se termine pas ou ne trouve pas la reference')
        panel._navigate_search(1)
        line = int(panel._search_matches[panel._search_index][0].split('.')[0])
        if view._idx != view._frame_for_file_line(line):
            raise AssertionError('La recherche CIP ne synchronise pas les frames')
    view._go_start()
    view._start_playback()
    app.update()
    view._stop_playback()
    print('Navigation, recherche CIP et lecture : OK', flush=True)


def reference_with_health_observations(frames, diagnostics=None, origin=None):
    """Recalcule aussi les observations du bilan pour comparer un rapport complet."""
    from Models.segment_collector import SegmentCollector
    class ObservedFrames(list):
        pass
    result = ObservedFrames(frames)
    collector = SegmentCollector()
    for frame in result:
        collector.consume(frame)
    if diagnostics is None:
        from Models.diagnostic import build_diagnostics
        diagnostics = build_diagnostics(result, collector.events, collector.finish(),
            trace_origin=origin, line_states=collector.lines, state_incidents=collector.states.finish())
    result.health_observations = collector.health.finish(diagnostics, collector.lines, origin)
    return result


def verify_storage(path, frames, events, diagnostics, analyses):
    from Parser.trace_parser import parse_file
    from Models.folder_report import _collect_events
    source_metadata = {}
    direct = parse_file(str(path), min_dt=0.0, source_metadata_output=source_metadata)
    if hasattr(frames, 'health_observations'):
        from Models.robot_drain import read_trace_origin
        direct = reference_with_health_observations(direct, diagnostics, read_trace_origin(path))
        if direct.health_observations != frames.health_observations:
            raise AssertionError('Observations du bilan differentes')
        from Models.folder_catalog import read_source_identity
        source_metadata['identity'] = read_source_identity(path)
        direct.source_metadata = source_metadata
        if source_metadata != frames.source_metadata:
            raise AssertionError('Metadonnees de source differentes')
    if len(direct) != len(frames):
        raise AssertionError('Nombre de frames different')
    for index, (expected, actual) in enumerate(zip(direct, frames)):
        if expected != actual:
            raise AssertionError(f'Frame differente : {index}, ligne {expected.line_num}')
    if _collect_events(direct) != events:
        raise AssertionError('Evenements differents')
    print(f'Tous les champs des {len(frames)} frames et evenements sont identiques', flush=True)
    if analyses:
        from Models.event_cycles import build_business_events
        from Models.diagnostic_report import build_report_payload
        for belt in ('T0', 'T1', 'T2', 'T3', 'T4', 'T5'):
            expected = build_business_events(direct, events, belt)
            actual = build_business_events(frames, events, belt)
            if expected != actual:
                raise AssertionError(f'Filtre different : {belt}')
            print(f'Filtre {belt} identique : {len(actual)} elements', flush=True)
        expected = build_report_payload(diagnostics, frames=direct,
            **({'trace_period': frames.trace_period} if hasattr(frames, 'trace_period') else {}))
        actual = build_report_payload(diagnostics, frames=frames)
        expected.pop('generated_at')
        actual.pop('generated_at')
        if expected != actual:
            raise AssertionError('Rapport different')
        print('Rapport integralement identique (hors date de generation)', flush=True)


def save_results(args, path, frames, events, diagnostics, references, total_lines, timings,
                 latency=None, digest=None):
    stat = path.stat()
    results = {
        'source': {'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns},
        'frames': len(frames), 'events': len(events), 'lines': total_lines,
        'diagnostics': [asdict(item) for item in diagnostics],
        'references': [asdict(item) for item in references],
    }
    # Normalise les ensembles avant la comparaison avec un export JSON.
    results = json.loads(json.dumps(results, default=_json_default))
    if digest is not None:
        results['frame_digest'] = digest
    if args.compare_results:
        previous = json.loads(args.compare_results.read_text(encoding='utf-8'))
        for key, value in results.items():
            if previous[key] != value:
                raise AssertionError(f'Regression : resultats differents pour {key}')
        ratio = previous['timings']['total'] / max(timings['total'], 1e-9)
        print(f'Resultats integralement identiques | acceleration : x{ratio:.2f}', flush=True)
    if args.results_json:
        results['timings'] = timings
        if latency is not None:
            results['ui_latency'] = latency
        args.results_json.parent.mkdir(parents=True, exist_ok=True)
        args.results_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
