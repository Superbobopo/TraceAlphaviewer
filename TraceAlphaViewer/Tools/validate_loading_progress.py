"""Controle la progression reelle, la preparation et les annulations Tk."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.loading_progress import PHASE_WEIGHTS, ProgressEmitter, ProgressTracker


class ProgressTests(unittest.TestCase):
    def test_weighted_segments_monotonic_and_explicit_completion(self):
        tracker = ProgressTracker('folder_group')
        tracker.register_segments([{'id': 'a', 'weight': 3}, {'id': 'b', 'weight': 1}])
        values = []
        values.append(tracker.update(dict(phase='read', segment='a', done=1, total=1)))
        self.assertAlmostEqual(tracker.fraction, PHASE_WEIGHTS['read'] * .75)
        self.assertEqual(tracker.phase_state('read'), 'running')
        values.append(tracker.update(dict(phase='read', segment='a', done=0, total=1, task='Autre tache')))
        values.append(tracker.update(dict(phase='diagnostic', segment='b', done=1, total=2)))
        self.assertEqual(tracker.phase_state('read'), 'running')
        for phase in tracker.weights:
            tracker.complete_phase(phase)
            values.append(tracker.fraction)
        self.assertEqual(values, sorted(values))
        self.assertLess(tracker.fraction, 1)
        self.assertEqual(tracker.ready(), 1)

    def test_unknown_total_does_not_invent_work_and_legacy_only_read(self):
        tracker = ProgressTracker()
        tracker.update(dict(phase='read', total=None, done=100))
        self.assertEqual(tracker.fraction, 0)
        tracker.update(.5)
        self.assertAlmostEqual(tracker.fraction, PHASE_WEIGHTS['read'] / 2)
        tracker.update(dict(phase='diagnostic', total=None, task='Traitement en cours'))
        self.assertAlmostEqual(tracker.fraction, PHASE_WEIGHTS['read'] / 2)
        self.assertEqual(tracker.phase_state('read'), 'running')
        self.assertEqual(tracker.phase_state('diagnostic'), 'running')

    def test_catalog_weights_and_throttled_messages(self):
        tracker = ProgressTracker('folder_catalog')
        tracker.complete_phase('read')
        self.assertAlmostEqual(tracker.fraction, .95)
        self.assertEqual(tracker.phase_state('diagnostic'), 'unused')
        messages = []
        tick = [0.]
        emitter = ProgressEmitter(lambda *message: messages.append(message), clock=lambda: tick[0])
        for index in range(100):
            tick[0] = index / 100
            emitter.emit('read', done=index, total=100)
        self.assertLessEqual(len(messages), 10)
        emitter.emit('read', state='done')
        self.assertEqual(messages[-1][1]['state'], 'done')


class UiProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import customtkinter as ctk
        cls.app = ctk.CTk()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()

    def pump(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.002)
        self.assertTrue(predicate(), 'Traitement Tk incomplet')

    def test_raw_progress_counts_inserted_bytes_and_empty_file(self):
        from Widgets.trace_panel import TracePanel
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'fictive.old'
            path.write_bytes(b'ligne fictive\r\n' * 1001)
            for data in (path.read_bytes(), b''):
                path.write_bytes(data)
                panel = TracePanel(self.app)
                messages, ready = [], []
                try:
                    panel.load_file(str(path), on_ready=lambda: ready.append(True), on_progress=messages.append)
                    self.pump(lambda: bool(ready))
                    self.assertFalse(panel._loading)
                    self.assertEqual(panel._total_lines, 1001 if data else 0)
                    self.assertEqual(messages[-1]['state'], 'done')
                    self.assertEqual(messages[-1]['done'], len(data))
                    self.assertEqual(messages[-1]['total'], len(data))
                    self.assertEqual(panel._loaded_filepath, str(path))
                finally:
                    panel.destroy()

    def test_prepare_waits_raw_and_show_reads_only_once(self):
        from Views.traceView import TraceView
        from Widgets.trace_panel import TracePanel
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'fictive.old'
            path.write_text('trace fictive\n' * 501, encoding='latin-1')
            view = TraceView(self.app, str(path), [], events=[], diagnostics=[], references=[])
            ready, messages, errors = [], [], []
            original = TracePanel.load_file
            calls = []

            def counted(panel, filepath, **kwargs):
                calls.append(filepath)
                return original(panel, filepath, **kwargs)

            try:
                with patch.object(TracePanel, 'load_file', counted):
                    view.prepare(lambda: ready.append(True), on_error=errors.append, on_progress=messages.append)
                    self.pump(lambda: bool(ready) or bool(errors))
                    self.assertFalse(errors)
                    self.assertFalse(view._trace_panel._loading)
                    self.assertEqual(view._trace_panel._total_lines, 501)
                    view.show()
                    self.assertEqual(calls, [str(path)])
                    self.assertTrue(any(item['phase'] == 'raw' and item['state'] == 'done' for item in messages))
                    self.assertTrue(any(item['phase'] == 'display' and item['state'] == 'done' for item in messages))
            finally:
                view.destroy()

    def test_cancel_keeps_incomplete_progress_and_stops_raw_callbacks(self):
        from Views.alphaFolderView import AlphaFolderView
        from Widgets.trace_panel import TracePanel
        folder = AlphaFolderView(self.app, str(ROOT), {'groups': []}, load_session=Mock())
        folder._build()
        try:
            folder._accept_progress(dict(phase='read', done=1, total=2))
            fraction = folder._progress_tracker.fraction
            folder._cancel_loading()
            self.assertEqual(folder._progress_tracker.fraction, fraction)
            self.assertLess(folder._progress.get(), 1)
        finally:
            folder.destroy()
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'fictive.old'
            path.write_text('fictive\n' * 2501, encoding='latin-1')
            panel = TracePanel(self.app)
            callbacks = []
            with patch.object(panel, '_poll_results', return_value=None):
                panel.load_file(str(path), on_ready=lambda: callbacks.append(True))
                cancel = panel._load_cancel
                reader = panel._load_thread
                panel.destroy()
                self.app.update()
                self.assertTrue(cancel.is_set())
                self.assertEqual(callbacks, [])
                # L'annulation UI est immediate ; la fermeture du fichier est asynchrone.
                reader.join(timeout=5)
                self.assertFalse(reader.is_alive(), 'Le lecteur brut ne termine pas apres annulation')
                path.unlink()

    def test_missing_raw_file_reports_failure_without_readiness(self):
        from Views.traceView import TraceView
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'absente.old'
            view = TraceView(self.app, str(path), [], events=[], diagnostics=[], references=[])
            ready, errors, messages = [], [], []
            try:
                view.prepare(lambda: ready.append(True), on_error=errors.append, on_progress=messages.append)
                self.pump(lambda: bool(errors))
                self.assertEqual(ready, [])
                self.assertFalse(view._prepared)
                self.assertFalse(any(item['phase'] == 'raw' and item['state'] == 'done' for item in messages))
            finally:
                view.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
