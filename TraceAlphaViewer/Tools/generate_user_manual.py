"""Reproduit les captures fictives et le PDF du manuel, sans modifier le viewer."""
from __future__ import annotations

import argparse
import copy
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / 'TraceAlphaViewer'
MANUAL = ROOT / 'docs' / 'manuel-utilisateur'
sys.path.insert(0, str(APP_ROOT))


def browser_path():
    candidates = [
        Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
        Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Microsoft/Edge/Application/msedge.exe',
        Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
    ]
    return next((path for path in candidates if path.exists()), None)


def run_browser(browser, url, *arguments):
    work = APP_ROOT / '.trace_work'
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='manual-browser-', dir=work) as profile:
        result = subprocess.run([
            str(browser), '--headless', '--disable-gpu', '--no-first-run',
            '--no-default-browser-check', '--disable-background-networking',
            '--disable-extensions', '--disable-sync', '--hide-scrollbars',
            '--allow-file-access-from-files', '--virtual-time-budget=5000',
            f'--user-data-dir={profile}', *arguments, url,
        ], capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=60)
        if result.returncode:
            raise RuntimeError(f'Le navigateur a quitte avec le code {result.returncode}')


def demonstration(directory):
    from Models.state import BoxInfo, MachineEvent, MachineState
    from Models.folder_report import _collect_events
    from Models.diagnostic import build_diagnostics
    from Models.reference_index import build_reference_records

    frames = []
    known_cip = '3400000000001'
    active_t5 = []

    def add(text, kind='INFO', severity='info', **values):
        index = len(frames)
        timestamp = index * 2
        hour = f'09:{timestamp // 60:02d}:{timestamp % 60:02d}'
        state = MachineState(line_num=index + 1, timestamp=timestamp, timestamp_str=hour,
            state_T0='MODE-AUTO', state_T1='WAIT-COND', state_T2='WAIT-COND',
            state_tEA_T3='WAIT-COND', state_tT3_T4='WAIT-COND', state_tT4_T5='WAIT-COND',
            state_T5='WAIT-COND', eT0=4, eT1=44, eT2=49, eT3=49, eT4=49, eT5=89)
        state.boxes_on_T5 = copy.deepcopy(active_t5)
        for key, value in values.items():
            setattr(state, key, copy.deepcopy(value))
        raw = f'* 01|{hour}.0 {text}'
        state.raw_lines = [(index + 1, raw)]
        state.events = [MachineEvent(index + 1, timestamp, hour, severity, kind, text)]
        frames.append(state)

    add('DEMONSTRATION - DONNEES FICTIVES POUR LA FORMATION')
    for cycle in range(1, 4):
        barcode = known_cip if cycle < 3 else 'ALPHA-INC-DEMO003'
        name = 'PRODUIT DEMO' if cycle < 3 else 'REFERENCE INCONNUE'
        box = BoxInfo(barcode=barcode, name=name, id_b=100 + cycle,
            length_mm=70, width_mm=40, height_mm=25,
            bdd_length_mm=70, bdd_width_mm=40, bdd_height_mm=25,
            measured_t4_length_mm=70, measured_t5_width_mm=40,
            measured_t5_height_mm=25, measured_t5_length_mm=70)
        add(f'Boite idB:{box.id_b} sur EA ref:{barcode}', 'TRANSFERT', box_in_EA=box, C4=1)
        if cycle == 3:
            add(f'idCB1: --> Ref:{barcode}', 'CAMERA')
        add(f'CB1: ajout Hist_LectCB pour la boite n{cycle} {1 if cycle < 3 else 0}code(s) lu(s)', 'CAMERA')
        add(f'Boite idB:{box.id_b} sur T3 ref:{barcode}', 'TRANSFERT', box_on_T3=box, C5=1, eT3=43)
        if cycle == 3:
            add(f'idCB2: --> Ref:{barcode}', 'CAMERA')
        add(f'CB2: ajout Hist_LectCB pour la boite n{cycle} {1 if cycle < 3 else 0}code(s) lu(s)', 'CAMERA')
        if cycle == 3:
            add(f"Creation de la boite '{barcode}' -unknow", 'CAMERA', 'warning')
        add(f'Boite idB:{box.id_b} sur T4 ref:{barcode}', 'T4', box_on_T4=box, C6=1, pT4=120, eT4=43)
        box.id_alpha = 200 + cycle
        box.x_pos = 942 + (cycle - 1) * 200
        box.t5_visual_x_pos = box.x_pos
        box.measurement_status = 'ok' if cycle < 3 else ''
        active_t5.append(box)
        add(f'AjoutBtT5.idA{box.id_alpha}.idB{box.id_b}', 'T5', C9=1, eT5=8)
        add(f"MAJ (APRES-MESURE-LARG) bt IdA:{box.id_alpha} '{barcode}' nvlle lxH:40x25 [x70] X:{box.x_pos}",
            'T5', C9=1, eT5=89)
    for _ in range(3):
        add('InitMachine: demande initialisation de T4 - controle C6', 'T4', 'warning', C6=1, eT4=1)
    add('T4 en erreur eT:-18 - Err: index non trouve', 'ERREUR', 'error', C6=1, eT4=-18)
    add('Robot prend IdA=201 X:942', 'BOITE')
    active_t5.pop(0)
    add('Fin de la demonstration - retour au repos', 'T5')
    path = directory / 'Demonstration - donnees fictives.old'
    path.write_text('\n'.join(frame.raw_lines[0][1] for frame in frames) + '\n', encoding='latin-1')
    events = _collect_events(frames)
    diagnostics = build_diagnostics(frames, events)
    records = build_reference_records(frames, events)
    if len([record for record in records if record.barcode == known_cip]) != 2:
        raise AssertionError('La demonstration doit distinguer deux cycles du meme CIP')
    if not any(incident.code == 'INIT-C6' for incident in diagnostics):
        raise AssertionError('La demonstration doit comporter le diagnostic INIT-C6')
    return path, frames, events, diagnostics, records


def captures():
    if sys.platform != 'win32':
        raise RuntimeError('Les captures natives de ce manuel necessitent Windows')
    from PIL import ImageGrab
    from Main import TraceAlphaViewer
    from Models.loading_client import LoadingSession
    from Models.folder_report import FolderReport, TraceReportEntry
    from Models.diagnostic_report import write_diagnostic_report
    from Views.traceView import TraceView
    from Views.folderTraceView import FolderTraceView

    assets = MANUAL / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    session = LoadingSession()
    path, frames, events, diagnostics, records = demonstration(session.directory)
    app = TraceAlphaViewer()
    app.geometry('1780x1000+10+10')
    errors = []
    app.report_callback_exception = lambda *args: errors.append(str(args[1]))
    metadata = {}

    def pump(predicate=lambda: True, timeout=10):
        deadline = time.monotonic() + timeout
        app.update()
        while not predicate() and time.monotonic() < deadline:
            app.update()
            time.sleep(0.005)
        if not predicate() or errors:
            raise AssertionError(errors or 'La preparation de la capture ne se termine pas')

    def photograph(name, settle=True):
        if settle:
            # CTkTabview termine le changement d'onglet dans un callback a 100 ms.
            ready_at = time.monotonic() + 0.2
            pump(lambda: time.monotonic() >= ready_at)
        pump()
        app.update_idletasks()
        image = ImageGrab.grab(window=app.winfo_id())
        image.save(assets / f'{name}.png')
        metadata[name] = {'width': image.width, 'height': image.height}
        print(f'Capture : {name}', flush=True)

    try:
        photograph('accueil')
        home = app.main_view
        home._load(str(path))
        photograph('chargement', settle=False)
        pump(lambda: isinstance(app.main_view, TraceView))
        pump(lambda: not app.main_view._trace_panel._loading)
        # Les etats fictifs sont injectes dans les vrais widgets de l'application.
        view = TraceView(app, str(path), frames, events=events, diagnostics=diagnostics, references=records)
        app.switch_view(view)
        pump(lambda: not view._trace_panel._loading)
        view._go_to(24)
        photograph('vue-ensemble')
        view._analysis_tabs.set('Capteurs & Tapis')
        photograph('capteurs')
        view._analysis_tabs.set('References')
        view._reference_panel._search_var.set('3400000000001')
        pump(lambda: not view._reference_panel.loading)
        assert len(view._reference_panel._visible_records) == 2
        photograph('references')
        view._on_reference_click(view._reference_panel._visible_records[1])
        assert view._frames[view._idx].line_num == view._reference_panel._visible_records[1].first_line
        view._reference_panel._search_var.set('')
        view._reference_panel._toggle_unknown_filter()
        assert len(view._reference_panel._visible_records) == 1
        photograph('unknown')
        view._trace_panel._search_var.set('3400000000001')
        pump(lambda: view._trace_panel._search_job is None)
        assert view._trace_panel._search_matches
        view._trace_panel._navigate_search(1)
        photograph('recherche-trace')
        view._analysis_tabs.set('Diagnostic')
        view._diagnostic_panel._show_global_summary()
        photograph('diagnostic-global')
        incident = next(item for item in diagnostics if item.code == 'INIT-C6')
        view._on_incident_click(incident)
        view._diagnostic_panel._show_details(incident)
        photograph('diagnostic-detail')
        view._analysis_tabs.set('Erreur')
        view._go_start()
        view._next_error()
        assert view._current_error_line is not None
        photograph('erreurs')
        view._analysis_tabs.set('Evenements')
        view._event_panel._set_belt_filter('T5')
        pump(lambda: not view._event_panel.loading)
        assert view._event_panel._visible_events
        photograph('evenements')
        view._go_end()
        assert view._idx == len(frames) - 1
        view._go_start()
        view._set_speed(0.5)
        view._start_playback()
        pump()
        view._stop_playback()
        assert not view._playing
        view._set_speed(1)

        report_paths = []
        def report_writer(incidents, frames=None):
            return write_diagnostic_report(incidents, output_dir=session.directory / 'reports', frames=frames)
        with patch('Widgets.diagnostic_panel.write_diagnostic_report', side_effect=report_writer), \
             patch('Widgets.diagnostic_panel.webbrowser.open', side_effect=lambda uri, **kwargs: report_paths.append(uri)):
            view._diagnostic_panel._open_web_report()
        assert report_paths
        report = next((session.directory / 'reports').glob('diagnostic_report_*.html'))
        browser = browser_path()
        if not browser:
            raise RuntimeError('Edge ou Chrome est requis pour capturer le rapport')
        run_browser(browser, report.as_uri(), '--window-size=1440,850',
                    f'--screenshot={assets / "rapport.png"}')
        if not (assets / 'rapport.png').exists():
            raise RuntimeError('La capture du rapport est absente')
        metadata['rapport'] = {'width': 1440, 'height': 850}
        other_path = session.directory / 'Demonstration - autre jour.old'
        other_path.write_text(path.read_text(encoding='latin-1'), encoding='latin-1')
        entries = [TraceReportEntry(str(path), path.name, frames=frames, events=events,
            diagnostics=diagnostics, error_events=[item for item in events if item.severity == 'error']),
            TraceReportEntry(str(other_path), other_path.name, frames=frames, events=events,
            diagnostics=diagnostics, error_events=[item for item in events if item.severity == 'error'])]
        folder = FolderTraceView(app, FolderReport('Dossier de demonstration', entries))
        app.switch_view(folder)
        pump(lambda: not folder._event_panel.loading and not folder._trace_panel._loading)
        photograph('dossier')
        with patch('Views.folderTraceView.filedialog.asksaveasfilename', return_value=str(session.directory / 'rapport-demo.csv')):
            folder._export_csv()
        with (session.directory / 'rapport-demo.csv').open(encoding='utf-8-sig', newline='') as source:
            rows = list(csv.DictReader(source))
        assert rows and any(row['type'] == 'diagnostic' for row in rows)
        folder._open_selected_trace()
        pump(lambda: folder._viewer_view is not None)
        folder._close_viewer_window()
        (assets / 'captures.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        print(f'Parcours verifies : {len(frames)} frames, {len(diagnostics)} diagnostics, {len(records)} references', flush=True)
    finally:
        app.destroy()
        session.close()
        if not session.cleaned.wait(15) or session.cleanup_error:
            raise RuntimeError(f'Nettoyage incomplet : {session.cleanup_error}')


def pdf():
    browser = browser_path()
    if not browser:
        raise RuntimeError('Edge ou Chrome est requis pour generer le PDF')
    output = MANUAL / 'Bien-demarrer-avec-TraceAlphaViewer.pdf'
    run_browser(browser, (MANUAL / 'index.html').as_uri(),
                '--no-pdf-header-footer', f'--print-to-pdf={output}')
    if not output.is_file() or not output.read_bytes().startswith(b'%PDF-'):
        raise RuntimeError('Le PDF du manuel est absent ou invalide')
    print(f'PDF : {output.relative_to(ROOT)} ({output.stat().st_size} octets)', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures', action='store_true', help='Reproduire les captures et verifier les parcours')
    parser.add_argument('--pdf', action='store_true', help='Generer le PDF depuis le HTML')
    args = parser.parse_args()
    if not args.captures and not args.pdf:
        parser.error('Choisir --captures et/ou --pdf')
    if args.captures:
        captures()
    if args.pdf:
        pdf()


if __name__ == '__main__':
    main()
