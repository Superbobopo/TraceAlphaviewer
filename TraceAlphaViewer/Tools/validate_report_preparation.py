"""Controle les transitions du rapport sans ouvrir de navigateur."""
from pathlib import Path
from queue import Queue
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch
import sys
import unittest
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Widgets.diagnostic_panel import DiagnosticPanel
from Models.frame_store import FrameStore
from Models.resource_policy import Resources, GIB


class PreparationTests(unittest.TestCase):
    def test_real_worker_and_session_cleanup(self):
        from Models.loading_client import LoadingSession
        from Models.frame_store import write_frame_store
        from Models.state import MachineState
        from Models.diagnostic_report import build_report_payload, report_files_available
        session = LoadingSession()
        try:
            directory = session.directory / 'store'
            frames = [MachineState(line_num=1, timestamp_str='12:00:00')]
            write_frame_store(frames, directory)
            output = session.directory / 'prepared'
            task = session.start('report', store=str(directory), incidents=[],
                                 source_name='FICTIF', output_dir=str(output))
            result = None
            while True:
                kind, payload = task.results.get(timeout=30)
                if kind == 'result':
                    result = Path(payload)
                elif kind == 'error':
                    self.fail(payload)
                elif kind == 'done':
                    break
            self.assertTrue(report_files_available(result))
            data = next(output.glob('report_data_*.json'))
            actual = json.loads(data.read_text(encoding='utf-8'))
            with FrameStore(directory) as store:
                expected = build_report_payload([], frames=store, source_name='FICTIF')
            actual.pop('generated_at', None)
            expected.pop('generated_at', None)
            self.assertEqual(actual, json.loads(json.dumps(expected)))
        finally:
            session.close()
            self.assertTrue(session.cleaned.wait(10))
            self.assertIsNone(session.cleanup_error)
            self.assertFalse(session.directory.exists())

    def panel(self):
        store = object.__new__(FrameStore)
        store.directory = Path('fictif')
        task = SimpleNamespace(results=Queue())
        session = SimpleNamespace(directory=Path('session'), start=Mock(return_value=task))
        panel = SimpleNamespace(_frames=store, _report_directory=None,
            _report_prepare_job=None, _report_task=None, _report_path=None,
            _report_requested=False, _report_retained=False, _report_promoting=False,
            _report_btn=Mock(), _load_session=session, _incidents=[], _source_name='FICTIF',
            after=Mock(return_value='callback'), _launch_report=Mock())
        for name in ('prepare_web_report', '_prepare_web_report', '_start_report',
                     '_report_failed', '_retain_report', '_open_web_report', '_poll_report'):
            setattr(panel, name, MethodType(getattr(DiagnosticPanel, name), panel))
        return panel, task

    def complete(self, panel, task, path):
        task.results.put(('result', str(path)))
        task.results.put(('done', {}))
        panel._poll_report()

    @patch('Widgets.diagnostic_panel.report_files_available', return_value=True)
    def test_click_during_preparation_and_reuse(self, available):
        panel, task = self.panel()
        panel._start_report()
        panel._open_web_report()
        panel._open_web_report()
        self.assertEqual(panel._load_session.start.call_count, 1)
        self.complete(panel, task, Path('session/report.html'))
        self.assertEqual(panel._load_session.start.call_args.args, ('retain_report',))
        panel._launch_report.assert_not_called()
        self.complete(panel, task, Path('permanent/report.html'))
        self.assertTrue(panel._report_retained)
        panel._open_web_report()
        self.assertEqual(panel._launch_report.call_count, 2)
        self.assertEqual(panel._load_session.start.call_count, 2)

    @patch('Widgets.diagnostic_panel.report_files_available', return_value=True)
    def test_preparation_without_click_stays_temporary(self, available):
        panel, task = self.panel()
        panel._start_report()
        self.complete(panel, task, Path('session/report.html'))
        panel._launch_report.assert_not_called()
        self.assertEqual(panel._load_session.start.call_count, 1)
        panel._open_web_report()
        self.assertTrue(panel._report_promoting)

    @patch('Widgets.diagnostic_panel.messagebox.showerror')
    def test_failure_is_silent_until_requested_and_retry(self, error):
        panel, task = self.panel()
        panel._start_report()
        task.results.put(('error', 'Echec fictif'))
        panel._poll_report()
        error.assert_not_called()
        panel._open_web_report()
        self.assertEqual(panel._load_session.start.call_count, 2)
        task.results.put(('error', 'Echec demande'))
        panel._poll_report()
        error.assert_called_once()

    def test_memory_pressure_defers_preparation(self):
        panel, _ = self.panel()
        with patch('Models.resource_policy.detect_resources',
                   return_value=Resources(32 * GIB, GIB, 16, True)):
            panel._prepare_web_report()
        panel._load_session.start.assert_not_called()
        panel.after.assert_called_with(1000, panel._prepare_web_report)


if __name__ == '__main__':
    unittest.main(verbosity=2)
