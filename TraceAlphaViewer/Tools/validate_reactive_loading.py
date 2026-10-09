"""Verifie le stockage, les workers et le cycle de vie du chargement Tk."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import pickle
from queue import Empty
import random
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

import customtkinter as ctk
from Main import TraceAlphaViewer
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload
from Models.event_cycles import build_business_events
from Models.folder_report import _collect_events
from Models.frame_store import BLOCK_SIZE, FrameStore, write_frame_store
from Models.loading_client import LoadingSession
from Models.reference_index import build_reference_records
from Models.state import BoxInfo, MachineEvent, MachineState
from Parser.trace_parser import parse_file
from Views.BaseView import BaseView
from Views.folderTraceView import FolderTraceView
from Views.traceView import TraceView
from Widgets.event_panel import EventPanel


def receive(task, timeout=20):
    messages = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            kind, payload = task.results.get(timeout=0.1)
        except Empty:
            continue
        messages.append((kind, payload))
        if kind in ('done', 'error'):
            return messages
    raise AssertionError('Le worker ne termine pas sa reponse')


def close_session(session):
    session.close()
    if not session.cleaned.wait(15) or session.cleanup_error or session.directory.exists():
        raise AssertionError(f'Nettoyage incomplet : {session.cleanup_error}')


class FrameStoreTests(unittest.TestCase):
    def test_all_fields_random_blocks_slices_and_independent_readers(self):
        frames = [MachineState(
            line_num=i * 2 + 4, timestamp=i / 10, timestamp_str=str(i),
            boxes_on_T5=[BoxInfo(id_alpha=i, barcode='CIP', x_pos=i)],
            raw_lines=[(i * 2 + 4, 'Texte avec accents et \u00b6')],
            events=[MachineEvent(i, i / 10, str(i), 'info', 'BOITE', 'titre')],
        ) for i in range(BLOCK_SIZE * 4 + 7)]
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            write_frame_store(frames, directory)
            with FrameStore(directory) as store, FrameStore(directory) as other:
                self.assertEqual(len(store), len(frames))
                indices = list(range(len(frames)))
                random.Random(17).shuffle(indices)
                for index in indices:
                    self.assertEqual(asdict(store[index]), asdict(frames[index]))
                    self.assertLessEqual(len(store._cache), 2)
                self.assertEqual(store[498:503], frames[498:503])
                self.assertEqual(store[::-97], frames[::-97])
                self.assertEqual(store[-1], frames[-1])
                self.assertEqual(other[500], frames[500])
                self.assertIsNot(store[500], other[500])
                self.assertEqual(store.frame_index_for_line(0), 0)
                self.assertEqual(store.frame_index_for_line(1003), 499)
                self.assertEqual(store.frame_index_for_line(999999), len(frames) - 1)
                self.assertEqual(store.start_time_str, frames[0].timestamp_str)
                self.assertEqual(store.end_time_str, frames[-1].timestamp_str)
                for index in (-len(frames) - 1, len(frames)):
                    with self.assertRaises(IndexError):
                        store[index]
                with self.assertRaises(TypeError):
                    store[0.5]
            with self.assertRaises(OSError):
                store[0]
            self.assertTrue(all(isinstance(frame, MachineState) for frame in frames))

    def test_empty_corrupt_and_release(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            write_frame_store([], directory)
            with FrameStore(directory) as store:
                self.assertEqual(list(store), [])
                self.assertEqual(store.start_time_str, '--:--:--')
            frames = [MachineState(line_num=i) for i in range(1001)]
            write_frame_store(frames, directory, release=True)
            self.assertEqual(frames, [None] * 1001)
            with FrameStore(directory) as store:
                self.assertEqual(store[1000].line_num, 1000)
            (directory / 'frames.bin').write_bytes(b'')
            with FrameStore(directory) as store:
                with self.assertRaises(OSError):
                    store[0]
            (directory / 'index.pkl').write_bytes(b'')
            with self.assertRaises(OSError):
                FrameStore(directory)


class WorkerTests(unittest.TestCase):
    def test_pure_imports(self):
        result = subprocess.run([sys.executable, '-c',
            "import sys; import Models.loading_worker; "
            "assert not any(m.startswith(('tkinter', 'customtkinter', 'Views')) for m in sys.modules)"],
            cwd=ROOT / 'TraceAlphaViewer', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_errors_unexpected_exit_and_cancel_bounded_queue(self):
        session = LoadingSession()
        try:
            task = session.start('file', path=session.directory / 'absent.old')
            self.assertEqual(receive(task)[-1][0], 'error')
            original = subprocess.Popen
            def exit_process(*args, **kwargs):
                return original([sys.executable, '-c', 'pass'], **kwargs)
            with patch('Models.loading_client.subprocess.Popen', side_effect=exit_process):
                task = session.start('file', path='absent.old')
                self.assertIn('sans resultat', receive(task)[-1][1])
                self.assertTrue(task.finished.wait(5))
            # Le worker doit pouvoir s'arreter avant meme le lancement du processus.
            task = session.start('file', path='absent.old')
            task.cancel()
            self.assertTrue(task.finished.wait(5))
            self.assertEqual(task.results.maxsize, 4)
            with self.assertRaises(OSError):
                session.open_store(ROOT)
        finally:
            close_session(session)
        with self.assertRaises(RuntimeError):
            session.start('file', path='absent.old')

    def test_cancel_with_full_queue_and_cleanup_retry(self):
        session = LoadingSession()
        original = subprocess.Popen
        script = (
            "import sys,pickle,time; r=pickle.load(open(sys.argv[1],'rb')); "
            "[(pickle.dump((r['job_id'],'progress',i),sys.stdout.buffer),"
            "sys.stdout.buffer.flush()) for i in range(1000)]; time.sleep(30)"
        )
        def progress_process(args, **kwargs):
            return original([sys.executable, '-u', '-c', script, args[-1]], **kwargs)
        try:
            with patch('Models.loading_client.subprocess.Popen', side_effect=progress_process):
                task = session.start('file', path='absent.old')
                deadline = time.monotonic() + 5
                while not task.results.full() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(task.results.full())
                started = time.perf_counter()
                task.cancel()
                self.assertLess(time.perf_counter() - started, 0.1)
                self.assertTrue(task.finished.wait(5))
                self.assertIsNotNone(task.process.poll())
            import shutil
            remove = shutil.rmtree
            calls = []
            def temporarily_locked(path):
                calls.append(path)
                if len(calls) == 1:
                    raise PermissionError('Handle temporaire de test')
                return remove(path)
            with patch('Models.loading_client.shutil.rmtree', side_effect=temporarily_locked):
                close_session(session)
                self.assertEqual(len(calls), 2)
        finally:
            close_session(session)

    def test_storage_failure_and_empty_folder(self):
        from Models.loading_worker import run
        session = LoadingSession()
        try:
            blocker = session.directory / 'not-a-directory'
            blocker.write_text('test', encoding='utf-8')
            with patch('Models.loading_worker.parse_file', return_value=[MachineState(line_num=1)]):
                with self.assertRaises(OSError):
                    run({'mode': 'file', 'path': str(blocker), 'session': str(blocker)}, lambda *args: None)
            empty = session.directory / 'empty'
            empty.mkdir()
            messages = receive(session.start('folder', path=empty))
            self.assertEqual(messages[-1][0], 'done')
            self.assertFalse(any(kind == 'entry' for kind, _ in messages))
        finally:
            close_session(session)

    def test_file_frames_analyses_business_and_report(self):
        path = ROOT / 'TraceAlphaViewer' / 'TracAlpha1 - Domineuc.txt'
        if not path.exists():
            self.skipTest('Trace Domineuc absente')
        expected = parse_file(str(path), min_dt=0.0)
        events = _collect_events(expected)
        diagnostics = build_diagnostics(expected, events)
        references = build_reference_records(expected, events)
        session = LoadingSession()
        try:
            messages = receive(session.start('file', path=path))
            self.assertEqual(messages[-1][0], 'done', messages[-1])
            entry = next(value for kind, value in messages if kind == 'entry')
            store = session.open_store(entry['store'])
            self.assertEqual(list(store), expected)
            for key, items in (('events', events), ('diagnostics', diagnostics), ('references', references)):
                actual = [item for kind, batch in messages if kind == key for item in batch]
                self.assertEqual(actual, items, key)
            for belt in ('T0', 'T1', 'T2', 'T3', 'T4', 'T5'):
                messages = receive(session.start('business', store=str(store.directory), belt=belt))
                self.assertEqual(messages[-1][0], 'done')
                actual = [item for kind, batch in messages if kind == 'items' for item in batch]
                self.assertEqual(actual, build_business_events(expected, events, belt), belt)
            output = session.directory / 'report'
            messages = receive(session.start('report', store=str(store.directory),
                              incidents=diagnostics, output_dir=str(output)))
            self.assertEqual(messages[-1][0], 'done', messages[-1])
            report_path = next(value for kind, value in messages if kind == 'result')
            self.assertTrue(Path(report_path).is_file())
            actual = json.loads(next(output.glob('report_data_*.json')).read_text(encoding='utf-8'))
            wanted = build_report_payload(diagnostics, frames=expected)
            actual.pop('generated_at')
            wanted.pop('generated_at')
            self.assertEqual(actual, wanted)
        finally:
            close_session(session)


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = TraceAlphaViewer()
        cls.app.withdraw()
        original = ctk.CTkToplevel.__init__
        def hidden_window(window, *args, **kwargs):
            original(window, *args, **kwargs)
            window.withdraw()
        cls.hidden_windows = patch.object(ctk.CTkToplevel, '__init__', hidden_window)
        cls.hidden_windows.start()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()
        cls.hidden_windows.stop()

    def setUp(self):
        from Views.accueilView import AccueilView
        self.app.switch_view(AccueilView(self.app))
        self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)

    def tearDown(self):
        from Views.accueilView import AccueilView
        self.app.switch_view(AccueilView(self.app))
        self.assertEqual(self.errors, [])

    def pump(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.003)
        self.assertTrue(predicate(), 'Traitement Tk incomplet')

    def fixture(self, session):
        path = session.directory / 'test.old'
        path.write_text('\n'.join(
            f'24|08:00:{i:02d} ALPHA:T5-LIST-PACK IdA:{i} X:942 CIP:3400931234567'
            for i in range(20)), encoding='latin-1')
        return path

    def test_real_home_folder_popup_and_cleanup(self):
        session = LoadingSession()
        path = self.fixture(session)
        try:
            home = self.app.main_view
            home._load_folder(str(path.parent))
            owner = home._load_session
            self.pump(lambda: isinstance(self.app.main_view, FolderTraceView))
            view = self.app.main_view
            self.assertFalse(view._event_panel.loading)
            view._open_selected_trace()
            borrowed = view._viewer_view
            self.assertIsNotNone(borrowed)
            self.assertIs(borrowed._frames, view._selected_entry.frames)
            view._close_viewer_window()
            self.assertFalse(owner.closed.is_set())
            view._close()
            close_session(owner)
        finally:
            close_session(session)

    def test_close_home_during_load_and_preparation_error(self):
        session = LoadingSession()
        path = self.fixture(session)
        try:
            home = self.app.main_view
            home._load(str(path))
            owner = home._load_session
            self.app.switch_view(BaseView(self.app))
            close_session(owner)
            from Views.accueilView import AccueilView
            home = AccueilView(self.app)
            self.app.switch_view(home)
            with patch.object(TraceView, '_build_split_layout', side_effect=OSError('Erreur stockage test')):
                home._load(str(path))
                owner = home._load_session
                self.pump(lambda: not home._load_busy)
                self.assertIn('Erreur stockage test', home._progress_lbl.cget('text'))
                close_session(owner)
            home._load(str(path))
            owner = home._load_session
            self.pump(lambda: isinstance(self.app.main_view, TraceView))
            self.app.main_view._close()
            close_session(owner)
        finally:
            close_session(session)

    def test_retained_view_keeps_session_and_filters_cancel(self):
        session = LoadingSession()
        path = self.fixture(session)
        frames = [MachineState(line_num=i + 1) for i in range(1100)]
        directory = session.directory / 'frames'
        write_frame_store(frames, directory)
        with (directory / 'events.pkl').open('wb') as output:
            pickle.dump([], output)
        store = session.open_store(directory)
        view = TraceView(self.app, str(path), store, events=[], diagnostics=[], references=[], load_session=session)
        self.app.switch_view(view)
        retained = TraceView(self.app, str(path), [MachineState(line_num=1)],
                             events=[], diagnostics=[], references=[], return_view=view)
        self.app.switch_view(retained)
        self.assertFalse(session.closed.is_set())
        self.assertEqual(store[-1], frames[-1])
        retained._close()
        self.assertIs(self.app.main_view, view)
        panel = view._event_panel
        panel._set_belt_filter('T5')
        task = panel._filter_task
        panel._set_belt_filter('Tous')
        self.assertTrue(task.cancelled.is_set())
        self.assertEqual(panel._visible_events, [])
        panel._set_belt_filter('T3')
        self.pump(lambda: not panel.loading)
        view._close()
        close_session(session)

    def test_close_during_hidden_preparation_and_raw_loading(self):
        session = LoadingSession()
        path = self.fixture(session)
        try:
            home = self.app.main_view
            home._load(str(path))
            owner = home._load_session
            self.pump(lambda: home._prepared_view is not None)
            self.assertIs(self.app.main_view, home)
            prepared = home._prepared_view
            self.app.switch_view(BaseView(self.app))
            self.assertTrue(prepared._disposed.is_set())
            close_session(owner)
            from Views.accueilView import AccueilView
            home = AccueilView(self.app)
            self.app.switch_view(home)
            # Suspendre la reception Tk : un petit fichier peut finir avant l'assertion.
            with patch('Widgets.trace_panel.TracePanel._poll_results', return_value=None):
                home._load(str(path))
                owner = home._load_session
                self.pump(lambda: isinstance(self.app.main_view, TraceView))
                self.assertTrue(self.app.main_view._trace_panel._loading)
                self.app.main_view._close()
                close_session(owner)
        finally:
            close_session(session)

    def test_deferred_folder_selection_and_list_rendering(self):
        from Models.folder_report import TraceReportEntry
        from Widgets.folder_panels import GroupedItemPanel, GroupSection, TraceListPanel
        entries = [TraceReportEntry(str(i), f'trace-{i}') for i in range(2000)]
        panel = TraceListPanel(self.app)
        grouped = GroupedItemPanel(self.app, title='test', item_label=str, detail_label=str)
        try:
            panel.set_entries(entries)
            panel.highlight_entry(entries[-1].filepath)
            grouped.set_groups([GroupSection('test', entries)])
            grouped.select_item(entries[-1])
            self.pump(lambda: not panel.loading and not grouped.loading)
            self.assertEqual(len(panel._line_to_entry), len(entries))
            self.assertEqual(str(panel._text.tag_ranges('selected')[0]), '3999.0')
            self.assertEqual(str(grouped._list.tag_ranges('selected')[0]), '2001.0')
            self.assertIn('trace-1999', grouped._details.get('1.0', 'end'))
        finally:
            panel.destroy()
            grouped.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
