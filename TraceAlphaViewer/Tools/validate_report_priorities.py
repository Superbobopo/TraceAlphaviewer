"""Verifie les priorites terrain, les libelles et l'ouverture immediate du dialogue."""
from pathlib import Path
from types import SimpleNamespace
import sys
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.diagnostic import DiagnosticIncident, _motor_error_title
from Models.diagnostic_report import build_report_payload
from Models.health_radar import build_health_radar
from Models.diagnostic_summary import repeated_fault_severity


def fault(code, stamp, line, segment=0):
    record = dict(first_line=line, start_time=stamp, end_time=stamp+1,
                  severity='error', id_alpha=line)
    metrics = dict(source_segment=segment)
    if code == 'MOTOR_COMM':
        metrics['episodes'] = [record]
    else:
        metrics.update(priority_impact_version=1, blocked_cycle=record)
    return dict(code=code, metrics=metrics)


class ReportPriorityTests(unittest.TestCase):
    def test_frequency_inclusive_window_and_segments(self):
        for code, threshold in [('MOTOR_COMM', 3), ('T5_STALE_UNMEASURED_BOX', 10)]:
            records = [fault(code, index * 86400 * 3, index) for index in range(4)]
            self.assertEqual(repeated_fault_severity(dict(code=code, incidents=records)), 'warning')
            records = [fault(code, 86400*index/(threshold-1), index) for index in range(threshold)]
            self.assertEqual(repeated_fault_severity(dict(code=code, incidents=records)), 'error')
            records[-1]['metrics']['episodes' if code == 'MOTOR_COMM' else 'blocked_cycle'] = (
                [dict(records[-1]['metrics']['episodes'][0], start_time=86400.01)] if code == 'MOTOR_COMM' else
                dict(records[-1]['metrics']['blocked_cycle'], start_time=86400.01))
            self.assertEqual(repeated_fault_severity(dict(code=code, incidents=records)), 'warning')
            self.assertEqual(repeated_fault_severity(dict(code=code, incidents=[records[0]]*100)), 'warning')
            separate = [fault(code, 0, i, segment=i) for i in range(threshold)]
            self.assertEqual(repeated_fault_severity(dict(code=code, incidents=separate)), 'warning')

    def test_rare_t5_cycles_do_not_dominate_repeated_faults(self):
        from Tools.validate_priority_impact import stale, c5
        rare = [stale(line=i+1, start=i*86400*3, end=i*86400*3+10000, count=100000) for i in range(4)]
        payload = build_report_payload(rare+[c5()], [])
        t5 = next(group for group in payload['groups'] if group['code']=='T5_STALE_UNMEASURED_BOX')
        self.assertEqual(t5['field_severity'], 'warning')
        self.assertEqual(t5['priority_impact']['cycles'], 4)
        self.assertEqual(payload['priority'][0]['code'], 'C5_SIGNAL_ANOMALY')
        unknown = DiagnosticIncident('warning', 'Lectures inconnues', 'IDENTIF', 'UNKNOWN', count=100)
        payload = build_report_payload(rare+[unknown], [])
        self.assertEqual(payload['priority'][0]['code'], 'UNKNOWN')

    def test_alpha_without_reset_is_green_on_analyzed_trace(self):
        observations = dict(version=2, counts=dict(transfers=10, alpha=0), duration_seconds=3600)
        alpha = build_health_radar(observations, [])['axes'][-1]
        self.assertEqual(alpha['value'], 1)
        self.assertIn('Aucun reset', ' '.join(alpha['limits']))
        self.assertEqual(alpha['numerator'], 0)

    def test_et_labels_keep_firmware_and_add_context(self):
        for belt, code, context in [('T4','-17','C6 reste actif'), ('T3','-43','C4 vers T3'), ('T2','-88','presente sur C4')]:
            text = _motor_error_title(belt, code)
            self.assertIn(f'{belt} eT:{code} - Err:', text)
            self.assertIn(context, text)

    def test_dialog_does_not_scan_and_remembers_selection(self):
        from Views.accueilView import AccueilView
        master = SimpleNamespace()
        home = SimpleNamespace(master=master, _load=Mock(), _load_folder=Mock())
        for method, chooser, selected in [(AccueilView._open_file, 'askopenfilename', str(ROOT/'build'/'demo.old')),
                                           (AccueilView._open_folder, 'askdirectory', str(ROOT/'build'))]:
            with patch('Views.accueilView._find_trace_files', side_effect=AssertionError('Parcours interdit au clic')) as scan, \
                 patch('Views.accueilView.filedialog.'+chooser, return_value=selected) as dialog:
                started=time.perf_counter()
                method(home)
                self.assertLess(time.perf_counter()-started, .1)
                scan.assert_not_called()
                self.assertEqual(master._trace_dialog_directory, ROOT/'build')
                dialog.assert_called_once()
        with patch('Views.accueilView.filedialog.askopenfilename', return_value='') as dialog:
            home = SimpleNamespace(master=master, _load=Mock())
            AccueilView._open_file(home)
            self.assertEqual(dialog.call_args.kwargs['initialdir'], str(ROOT/'build'))
            home._load.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
