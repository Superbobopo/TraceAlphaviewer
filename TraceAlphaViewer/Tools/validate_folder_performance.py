"""Verifie pagination, preuves bornees et equivalence des attentes en flux."""
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.diagnostic import (DiagnosticIncident, StateIncidentCollector, build_diagnostics,
                              _build_wait_incidents, _build_t2_blocked_before_ea_incidents,
                              _build_missing_t5_creation_incidents)
from Models.diagnostic_report import build_report_payload
from Models.list_navigation import LineIndex
from Models.reference_index import ReferenceRecord, ReferenceCollector
from Models.measurement_analysis import MeasurementCollector
from Models.state import MachineEvent, MachineState, BoxInfo


class PerformanceTests(unittest.TestCase):
    def test_state_accumulator_keeps_thresholds_and_end_of_segment(self):
        frames = [MachineState(line_num=i + 1, timestamp=float(i), state_T5='WAIT-SENSOR',
            C9=0, state_tT3_T4='WAIT-C6', C6=int(i >= 125),
            state_T2='WAIT-COND-TRSF', C2=1, C3=1, C4=int(20 <= i < 30)) for i in range(151)]
        collector = StateIncidentCollector()
        for frame in frames:
            collector.consume(frame)
        self.assertEqual(collector.finish(),
            _build_wait_incidents(frames) + _build_t2_blocked_before_ea_incidents(frames))

    def test_ten_proofs_across_151_days_keep_totals_and_original_incidents(self):
        incidents = [DiagnosticIncident(severity='error', title='Initialisation T4', code='INIT-C6',
            belt='T4', first_line=i * 20 + 1, last_line=i * 20 + 10,
            start_time=i * 86400., end_time=i * 86400. + 9, count=10,
            event_lines=list(range(i * 20 + 1, i * 20 + 11))) for i in range(151)]
        group = build_report_payload(incidents)['groups'][0]
        self.assertEqual((group['occurrence_count'], group['incident_count']), (1510, 151))
        self.assertEqual((len(group['examples']), group['evidence_total']), (10, 1510))
        self.assertEqual((group['examples'][0]['line'], group['examples'][-1]['line']), (1, 3010))
        self.assertLessEqual(len(group['series']), 10)
        self.assertLessEqual(len(group['incidents']), 10)
        self.assertEqual(sum(len(row.event_lines) for row in incidents), 1510)

    def test_line_index_unsorted_and_duplicate_lines(self):
        rows = [MachineEvent(n, 0., '', 'info', '', '') for n in (15, 2, 15, 8)]
        index = LineIndex(rows)
        self.assertIsNone(index.position_for_line(1))
        self.assertEqual(index.position_for_line(14), 3)
        self.assertEqual(index.position_for_line(15), 0)

    def test_creation_window_is_inclusive_with_unsorted_events(self):
        def transfer(line):
            return MachineEvent(line, 0., '', 'info', 'TRANSFERT', 'T4 vers T5 termine')
        def creation(line):
            return MachineEvent(line, 0., '', 'info', 'BOITE', 'T4->T5 fictif')
        events = [transfer(100), creation(80), transfer(10), creation(121),
                  transfer(31), transfer(60), creation(30)]
        self.assertEqual([row.first_line for row in _build_missing_t5_creation_incidents(events)], [100,31])

    def test_stationary_shortcuts_equal_full_matching_with_identity_changes(self):
        base = BoxInfo(id_alpha=17, id_b=1, barcode='3400000000001', identified_barcode='3400000000001',
            identity_line=1, identity_source='CB2', camera_identity_line=1, camera_identity_source='CB2',
            bdd_reference='3400000000001', bdd_source_line=2, bdd_width_mm=30, bdd_height_mm=20,
            bdd_length_mm=50, measured_t4_length_mm=50, measured_t5_width_mm=30,
            measured_t5_height_mm=20, measured_t4_line=3, measured_t5_line=4, measured_height_line=5)
        fast, full = MeasurementCollector(), MeasurementCollector()
        fast_refs, full_refs = ReferenceCollector(), ReferenceCollector()
        for index in range(200):
            box = base.clone()
            box.x_pos = 942 + index
            if index >= 40:
                box.measured_t4_length_mm, box.measured_t4_line = 55, 42
            box.identity_conflict = 80 <= index < 100
            box.measurement_status = 'c9_error' if 120 <= index < 140 else ''
            boxes = [box, box.clone()] if 50 <= index < 55 else [box]
            if 160 <= index < 170:
                boxes = [BoxInfo(barcode='REFERENCE-AMBIGUE'), BoxInfo(barcode='REFERENCE-AMBIGUE')]
            frame = MachineState(line_num=index + 10, timestamp=float(index), timestamp_str=str(index),
                                 boxes_on_T5=boxes, box_on_T3=box if index < 25 else None)
            full._repeat_safe = False
            full_refs._repeat_records = None
            fast.consume(index, frame);full.consume(index, frame)
            fast_refs.consume(frame);full_refs.consume(frame)
        self.assertEqual(fast.finish(), full.finish())
        self.assertEqual(fast_refs.finish([]), full_refs.finish([]))


class PaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import customtkinter as ctk
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        for job in cls.root.tk.call('after', 'info'):
            cls.root.after_cancel(job)
        cls.root.destroy()

    def wait_panel(self, panel):
        deadline = time.monotonic() + 10
        while panel.loading and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.002)
        self.assertFalse(panel.loading)

    def test_event_pages_filters_navigation_and_cancellation(self):
        from Widgets.event_panel import EventPanel
        for count in (0, 500, 501, 5000):
            rows = [MachineEvent(i + 1, float(i), '', 'error', 'T4' if i % 2 else 'T5', 'titre')
                    for i in range(count)]
            panel = EventPanel(self.root, rows, navigation=LineIndex(rows))
            self.wait_panel(panel)
            self.assertEqual(len(panel._line_to_event), min(500, count))
            if count > 500:
                panel._set_page(1)
                self.wait_panel(panel)
                self.assertEqual(next(iter(panel._line_to_event.values())).line_num, 501)
                panel.highlight_for_line(count)
                self.wait_panel(panel)
                self.assertEqual(panel._page, (count - 1) // 500)
                panel._set_belt_filter('T4')
                self.wait_panel(panel)
                self.assertEqual(len(panel._visible_events), count // 2)
                self.assertEqual(panel._page, 0)
                panel._set_page(1)
                panel._set_page(0)
                self.wait_panel(panel)
                self.assertLessEqual(len(panel._line_to_event), 500)
            panel.destroy()

    def test_reference_search_covers_all_pages(self):
        from Widgets.reference_panel import ReferencePanel
        rows = [ReferenceRecord(key=str(i), barcode=f'CIP{i}', first_line=i + 1) for i in range(1201)]
        panel = ReferencePanel(self.root, rows, navigation=LineIndex(rows, 'first_line'))
        self.wait_panel(panel)
        panel.highlight_for_line(1201)
        self.wait_panel(panel)
        self.assertEqual(panel._page, 2)
        panel._search_var.set('CIP1200')
        self.wait_panel(panel)
        self.assertEqual(len(panel._visible_records), 1)
        self.assertEqual(panel._page, 0)
        panel.destroy()


if __name__ == '__main__':
    unittest.main()
