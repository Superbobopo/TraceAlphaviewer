"""Parcours Rust, viewer partage et export complet sur des traces fictives."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from queue import Empty, Queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.diagnostic_report import build_report_payload
from Models.loading_client import LoadingSession
from Models.native_folder import engine_path


def receive(task, timeout=25):
    messages = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            message = task.results.get(timeout=0.05)
        except Empty:
            continue
        messages.append(message)
        if message[0] in ('done', 'error'):
            return messages
    task.cancel()
    raise AssertionError('Le worker du dossier ne termine pas')


def close_session(session):
    session.close()
    if not session.cleaned.wait(15) or session.cleanup_error or session.directory.exists():
        raise AssertionError(f'Nettoyage incomplet : {session.cleanup_error}')


def fixture(directory):
    def trace(path, alpha, pharmacy, day, hour):
        path.parent.mkdir(parents=True, exist_ok=True)
        messages = [f'OUVERTURE DE LA TRACE le {day:02d}/01/2025',
                    fr'C:\APOTEKA\BASEALPHA_#2025.{alpha}.MDB',
                    fr'C:\APOTEKA\BASEFIC{pharmacy}.MDB',
                    'T2: ERREUR eT2:-88 C2:0 C3:0 C4:0',
                    "Création de la boite '3400931234567' PRODUIT FICTIF x=942 (60x30x100) IdA:17",
                    'OMEGA:T5-DemVidageComplet',
                    'Temps depuis RESET carte ALPHA : 100 mn',
                    'Temps depuis RESET carte ALPHA : 0 mn']
        path.write_bytes(''.join(f'{day:02d}|{hour:02d}:00:{index:02d}.0 {message}\r\n'
                                 for index, message in enumerate(messages)).encode('latin-1'))
    trace(directory / 'alpha31-a.old', '031', '1560LAHLOU', 1, 9)
    trace(directory / 'sous-dossier' / 'alpha31-b.TXT', '031', '1560LAHLOU', 3, 9)
    trace(directory / 'alpha009.OLD', '009', 'MOTTE', 1, 10)
    (directory / 'sans-trace.csv').write_text('fichier ignore', encoding='utf-8')


def catalog(session, directory):
    messages = receive(session.start('folder_catalog', path=directory))
    if messages[-1][0] != 'done':
        raise AssertionError(messages[-1])
    return next(value for kind, value in messages if kind == 'catalog')


def group_index(catalogue, alpha='031'):
    return next(index for index, group in enumerate(catalogue['groups'])
                if group.get('identity', {}).get('alpha_number') == alpha)


def group_data(session, directory, group):
    messages = receive(session.start('folder_group', path=directory, group=group))
    if messages[-1][0] != 'done':
        raise AssertionError(messages[-1])
    data = dict(next(value for kind, value in messages if kind == 'entry'))
    for key in ('events', 'diagnostics', 'references'):
        data[key] = [item for kind, batch in messages if kind == key for item in batch]
    data['frames'] = session.open_store(data['store'])
    return data


class FolderWorkerTests(unittest.TestCase):
    def setUp(self):
        engine_path()
        self.temporary = tempfile.TemporaryDirectory(prefix='tracealpha-folder-worker-test-')
        self.directory = Path(self.temporary.name)
        fixture(self.directory)
        self.session = LoadingSession()

    def tearDown(self):
        close_session(self.session)
        self.temporary.cleanup()

    def test_catalog_is_lazy_and_groups_only_the_same_alpha(self):
        data = catalog(self.session, self.directory)
        self.assertEqual(data['files'], 3)
        self.assertEqual(len(data['groups']), 2)
        alpha = data['groups'][group_index(data)]
        self.assertEqual(alpha['label'], 'Alpha 031 — Pharmacie Lahlou')
        self.assertEqual(len(alpha['sources']), 2)
        self.assertLess(alpha['sources'][0]['start'], alpha['sources'][1]['start'])
        self.assertEqual(data['groups'][group_index(data, '009')]['label'], 'Alpha 009 — Pharmacie Motte')
        self.assertEqual(list(self.session.directory.rglob('index.pkl')), [])
        self.assertEqual(list(self.session.directory.rglob('block-*.msgpack')), [])

    def test_group_worker_report_provenance_and_unobserved_days(self):
        catalogue = catalog(self.session, self.directory)
        data = group_data(self.session, self.directory, catalogue['groups'][group_index(catalogue)])
        frames = data['frames']
        self.assertEqual(len(frames.source_metadata['segments']), 2)
        self.assertEqual(len(data['references']), 2)
        self.assertNotEqual(data['references'][0].key, data['references'][1].key)
        drains, = [row for row in data['diagnostics'] if row.code == 'DemVidageComplet']
        self.assertEqual([day['count'] for day in drains.metrics['daily']], [1, None, 1])
        payload = build_report_payload(data['diagnostics'], frames, source_name=data['name'])
        self.assertEqual([row['name'] for row in payload['source']['files']], ['alpha31-a.old', 'alpha31-b.TXT'])
        self.assertEqual(len(payload['source']['gaps']), 1)
        examples = [sample for group in payload['groups'] for sample in group['examples']]
        self.assertTrue(examples)
        self.assertTrue(any(sample['source_label'].startswith('alpha31-b.TXT') for sample in examples))
        for sample in examples:
            source = frames.source_location(sample['line'])
            for context in sample.get('context', []):
                self.assertEqual(frames.source_location(context['line'])['segment'], source['segment'])
                self.assertIn(' · L.', context['source_label'])
        messages = receive(self.session.start('report', store=data['store'], incidents=data['diagnostics'],
                           source_name=data['name'], output_dir=str(self.session.directory / 'report')))
        self.assertEqual(messages[-1][0], 'done', messages[-1])
        path = Path(next(value for kind, value in messages if kind == 'result'))
        data_path = path.with_name(path.name.replace('diagnostic_report_', 'report_data_')).with_suffix('.json')
        exported = json.loads(data_path.read_text(encoding='utf-8'))
        robot = next(group for group in exported['groups'] if group['code'] == 'DemVidageComplet')
        self.assertIsNone(robot['daily'][1]['count'])
        self.assertFalse(robot['daily'][1]['observed'])

    def test_changed_source_fails_and_cancelled_worker_finishes(self):
        catalogue = catalog(self.session, self.directory)
        group = catalogue['groups'][group_index(catalogue)]
        Path(group['sources'][0]['filepath']).unlink()
        messages = receive(self.session.start('folder_group', path=self.directory, group=group))
        self.assertEqual(messages[-1][0], 'error')
        self.assertFalse(any(kind == 'entry' for kind, _ in messages))
        task = self.session.start('folder_catalog', path=self.directory)
        task.cancel()
        self.assertTrue(task.finished.wait(5))
        if task.process is not None:
            self.assertIsNotNone(task.process.poll())


class AlphaFolderUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import customtkinter as ctk
        from Main import TraceAlphaViewer
        engine_path()
        original = ctk.CTkToplevel.__init__
        def hidden(window, *args, **kwargs):
            original(window, *args, **kwargs)
            window.withdraw()
        cls.hidden_windows = patch.object(ctk.CTkToplevel, '__init__', hidden)
        cls.hidden_windows.start()
        cls.app = TraceAlphaViewer()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()
        cls.hidden_windows.stop()

    def setUp(self):
        from Views.accueilView import AccueilView
        self.app.switch_view(AccueilView(self.app))
        self.temporary = tempfile.TemporaryDirectory(prefix='tracealpha-folder-ui-test-')
        self.directory = Path(self.temporary.name)
        fixture(self.directory)
        self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        self.dialogs = patch('tkinter.messagebox.showerror')
        self.error_dialog = self.dialogs.start()
        self.sessions = []

    def tearDown(self):
        from Views.accueilView import AccueilView
        self.app.switch_view(AccueilView(self.app))
        for session in self.sessions:
            close_session(session)
        self.dialogs.stop()
        self.temporary.cleanup()
        self.assertEqual(self.errors, [])

    def pump(self, predicate, timeout=25):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.003)
        self.assertTrue(predicate(), 'Parcours Tk incomplet')

    def folder(self):
        from Views.alphaFolderView import AlphaFolderView
        home = self.app.main_view
        home._load_folder(str(self.directory))
        self.sessions.append(home._load_session)
        self.pump(lambda: isinstance(self.app.main_view, AlphaFolderView))
        return self.app.main_view

    def viewer(self, folder, index):
        from Views.traceView import TraceView
        folder._selected = index
        folder._open_selected()
        self.pump(lambda: isinstance(self.app.main_view, TraceView))
        return self.app.main_view

    def test_lazy_catalog_cached_return_and_report_source_link(self):
        from Models.report_bridge import ReportBridge
        folder = self.folder()
        self.assertFalse(folder._cache)
        self.assertIsNone(folder._task)
        index = group_index(folder._catalog)
        viewer = self.viewer(folder, index)
        owner = folder._load_session
        self.assertFalse(viewer._owns_load_session)
        self.assertIs(viewer._frames, folder._cache[index]['frames'])
        line = viewer._frames.source_metadata['sources'][1]['first_line'] + 3
        bridge = ReportBridge()
        viewer._report_bridge = bridge
        complete, result = threading.Event(), {}
        bridge.commands.put(({'line': line, 'source_line': True, 'code': '-88',
                              'first_line': folder._cache[index]['diagnostics'][0].first_line}, complete, result))
        with patch.object(self.app, 'deiconify'), patch.object(self.app, 'lift'):
            viewer._poll_report_bridge()
        self.assertTrue(complete.is_set())
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(viewer._frames.segment_index_for_frame(viewer._idx), 1)
        self.assertIn('alpha31-b.TXT', viewer._lbl_line.cget('text'))
        self.assertIn('L.4', viewer._lbl_line.cget('text'))
        viewer._close()
        self.assertIs(self.app.main_view, folder)
        self.assertFalse(owner.closed.is_set())
        with patch.object(owner, 'start', side_effect=AssertionError('Le cache relance un worker')):
            viewer = self.viewer(folder, index)
            viewer._close()
        folder._close()
        self.assertTrue(owner.closed.is_set())

    def test_csv_analyzes_missing_groups_and_never_exports_partial_data(self):
        folder = self.folder()
        index = group_index(folder._catalog)
        self.viewer(folder, index)._close()
        self.assertEqual(len(folder._cache), 1)
        output = self.directory / 'bilans.csv'
        heartbeat = []
        self.app.after(1, lambda: heartbeat.append(True))
        with patch('Views.alphaFolderView.filedialog.asksaveasfilename', return_value=str(output)), \
                patch.object(folder, '_open_viewer', side_effect=AssertionError('Un export ouvre un viewer')):
            folder._export_csv()
            self.assertFalse(output.exists())
            self.pump(lambda: output.exists() and folder._export_path is None)
        self.assertEqual(len(folder._cache), 2)
        self.assertTrue(heartbeat)
        with output.open(encoding='utf-8', newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(rows)
        self.assertEqual({row['fichier'] for row in rows}, {group['label'] for group in folder._groups})
        self.assertFalse(self.error_dialog.called)

    def test_cancel_error_and_preparation_guard_keep_ready_cache(self):
        from Views.traceView import TraceView
        folder = self.folder()
        cached = group_index(folder._catalog)
        other = group_index(folder._catalog, '009')
        self.viewer(folder, cached)._close()
        class Pending:
            results = Queue()
            cancelled = threading.Event()
            def cancel(self):
                self.cancelled.set()
        pending = Pending()
        with patch.object(folder._load_session, 'start', return_value=pending):
            folder._selected = other
            folder._open_selected()
            folder._cancel_loading()
        self.assertTrue(pending.cancelled.is_set())
        self.assertEqual(set(folder._cache), {cached})
        self.assertIsNone(folder._task)
        pending = Pending()
        pending.results = Queue()
        pending.results.put(('error', 'Erreur fictive du moteur Rust'))
        with patch.object(folder._load_session, 'start', return_value=pending):
            folder._open_selected()
            self.pump(lambda: self.error_dialog.called)
        self.assertIsNone(folder._task)
        self.assertEqual(set(folder._cache), {cached})
        self.assertIn('Erreur fictive', folder._status.cget('text'))
        callbacks = []
        with patch.object(TraceView, 'prepare', side_effect=lambda ready, on_error=None: callbacks.append((ready, on_error))):
            folder._selected = cached
            folder._open_selected()
            prepared = folder._prepared_view
            self.assertIsNotNone(prepared)
            with patch.object(folder._load_session, 'start', side_effect=AssertionError('Action concurrente')), \
                    patch('Views.alphaFolderView.filedialog.asksaveasfilename') as save:
                folder._tree.selection_set(str(other))
                folder._on_select()
                folder._open_selected()
                folder._export_csv()
                self.assertFalse(save.called)
            self.assertEqual(folder._selected, cached)
            folder._cancel_loading()
            self.assertTrue(prepared._disposed.is_set())
            self.assertFalse(folder._load_session.closed.is_set())

    def test_cancel_or_error_during_complete_export_preserves_existing_file(self):
        folder = self.folder()
        cached = group_index(folder._catalog)
        self.viewer(folder, cached)._close()
        output = self.directory / 'existant.csv'
        output.write_text('EXPORT PRECEDENT\n', encoding='utf-8')
        class Pending:
            def __init__(self):
                self.results = Queue()
                self.cancelled = threading.Event()
            def cancel(self):
                self.cancelled.set()
        for fail in (False, True):
            pending = Pending()
            if fail:
                pending.results.put(('error', 'Erreur fictive avant export complet'))
            with patch.object(folder._load_session, 'start', return_value=pending), \
                    patch('Views.alphaFolderView.filedialog.asksaveasfilename', return_value=str(output)):
                folder._export_csv()
                self.assertIsNotNone(folder._task)
                if fail:
                    self.pump(lambda: folder._task is None)
                else:
                    folder._cancel_loading()
                self.assertTrue(pending.cancelled.is_set())
                self.assertIsNone(folder._export_path)
                self.assertEqual(output.read_text(encoding='utf-8'), 'EXPORT PRECEDENT\n')
                self.assertEqual(set(folder._cache), {cached})


if __name__ == '__main__':
    unittest.main(verbosity=2)
