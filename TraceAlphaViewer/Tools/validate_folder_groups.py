"""Regressions fictives des analyses multi-fichiers et de leur provenance."""
from __future__ import annotations

from dataclasses import asdict, fields
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.diagnostic import build_diagnostics
from Models import diagnostic as diagnostic_model
from Models.folder_report import _collect_events
from Models.frame_store import FrameStore, write_frame_store_iter
from Models.group_analysis import analyze_group, build_group_business_events
from Models.measurement_analysis import analyze_measurements
from Models.reference_index import build_reference_records
from Models.state import BoxInfo, MachineEvent, MachineState


class FolderGroupsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='tracealpha-group-test-')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def source(self, name, start, texts, *, motor=False, box=False, times=None):
        start = datetime.fromisoformat(start)
        raw = self.root / (name + '.old')
        frames = []
        lines = []
        for index, text in enumerate(texts):
            seconds = times[index] if times is not None else index
            moment = start + timedelta(seconds=seconds)
            line = index + 1
            stamp = moment.strftime('%H:%M:%S')
            lines.append(f'{moment.day:02d}|{stamp}.0 {text}\r\n')
            frame = MachineState(line_num=line, timestamp=seconds, timestamp_str=stamp,
                                 raw_lines=[(line, text, True)])
            if motor:
                frame.events = [MachineEvent(line, seconds, stamp, 'error', 'ERREUR', 'T2 en erreur eT:-88')]
            if box:
                frame.boxes_on_T5 = [BoxInfo(id_alpha=17, id_b=5, barcode='FICTIF',
                    identified_barcode='FICTIF', identified_name='PRODUIT FICTIF',
                    identity_source='CB2', camera_identity_source='CB2',
                    identity_line=1, camera_identity_line=1, bdd_source_line=1,
                    measured_t4_line=1, measured_t5_line=1, measured_height_line=1,
                    t5_transfer_id=1, bdd_reference='FICTIF',
                    bdd_width_mm=60, bdd_height_mm=30, bdd_length_mm=100,
                    measured_t4_length_mm=105, measured_t5_width_mm=60,
                    measured_t5_height_mm=30, length_mm=105, width_mm=60, height_mm=30)]
            frames.append(frame)
        raw.write_bytes(''.join(lines).encode('latin-1'))
        store = self.root / (name + '-store')
        write_frame_store_iter(iter(frames), store)
        return {'filepath': str(raw), 'name': raw.name, 'store': str(store),
                'start': start.isoformat(), 'identity': {'alpha': 'BASEALPHA_#2025.031.MDB',
                'pharmacy': 'BASEFIC1560LAHLOU.MDB'}, 'group_name': 'Alpha 031 — Pharmacie Lahlou'}

    def analyze(self, sources, name='group'):
        return analyze_group(sources, self.root / name)

    def test_streaming_blocks_and_legacy_metadata(self):
        count = write_frame_store_iter((MachineState(line_num=i + 1, timestamp=i)
                                       for i in range(1201)), self.root / 'stream')
        self.assertEqual(count, 1201)
        with FrameStore(self.root / 'stream') as frames:
            self.assertEqual(frames[1000].line_num, 1001)
            self.assertEqual(frames[0].line_num, 1)
            self.assertEqual(frames[-1].line_num, 1201)
            self.assertLessEqual(len(frames._cache), 2)
            self.assertEqual(frames.source_location(5)['source_line'], 5)
            self.assertEqual(frames.segment_index_for_frame(1200), 0)

    def test_segment_lines_and_camera_stats_are_computed_once(self):
        first = self.source('once1', '2025-01-01T12:00:00', ['FICTIF', 'FICTIF'])
        second = self.source('once2', '2025-01-01T13:00:00', ['FICTIF', 'FICTIF'])
        with patch.object(diagnostic_model, '_frame_line_states', wraps=diagnostic_model._frame_line_states) as lines, \
                patch.object(diagnostic_model, '_camera_stats', wraps=diagnostic_model._camera_stats) as cameras:
            self.analyze([first, second])
            self.assertEqual(lines.call_count, 0)
            self.assertEqual(cameras.call_count, 2)
            self.assertEqual([[row[0] for row in call.args[0]] for call in cameras.call_args_list],
                             [[1, 2], [3, 4]])
            self.assertTrue(all(isinstance(row[2], diagnostic_model.DiagnosticState)
                                for call in cameras.call_args_list for row in call.args[0]))

    def test_single_source_analysis_equivalence(self):
        source = self.source('single', '2025-01-01T09:00:00',
                             ['OMEGA:T5-DemVidageComplet', 'FICTIF', 'FICTIF'], motor=True, box=True)
        with FrameStore(source['store']) as frames:
            events = _collect_events(frames)
            analysis = analyze_measurements(frames)
            diagnostics = build_diagnostics(frames, events, analysis,
                                            trace_origin=datetime.fromisoformat(source['start']))
            references = build_reference_records(frames, events)
            expected_frames = [asdict(frame) for frame in frames]
        result = self.analyze([source])
        self.assertEqual([asdict(event) for event in result['events']], [asdict(event) for event in events])
        self.assertEqual([asdict(row) for row in result['diagnostics']], [asdict(row) for row in diagnostics])
        self.assertEqual([asdict(row) for row in result['references']], [asdict(row) for row in references])
        with FrameStore(result['store']) as frames:
            self.assertEqual([asdict(frame) for frame in frames], expected_frames)
            self.assertEqual(frames.read_measurements(), analysis)

    def test_reused_ids_provenance_and_inclusive_24h(self):
        texts = ['OMEGA:T5-DemVidageComplet'] * 5
        first = self.source('first', '2025-01-01T00:00:00', texts, motor=True, box=True)
        second = self.source('second', '2025-01-01T23:59:56', texts, motor=True, box=True)
        result = self.analyze([second, first])
        self.assertEqual(len(result['references']), 2)
        self.assertNotEqual(result['references'][0].key, result['references'][1].key)
        self.assertEqual(result['references'][1].first_line, 6)
        incidents = {row.code: row for row in result['diagnostics']}
        self.assertEqual(incidents['-88'].count, 10)
        self.assertEqual(incidents['-88'].metrics['max_24h_count'], 10)
        self.assertEqual(incidents['-88'].severity, 'error')
        self.assertEqual(incidents['DemVidageComplet'].metrics['day']['count'], 10)
        self.assertEqual(incidents['DemVidageComplet'].metrics['daily'][0]['count'], 9)
        self.assertEqual(incidents['DemVidageComplet'].metrics['daily'][1]['count'], 1)
        self.assertEqual(incidents['T4_LENGTH'].count, 2)
        with FrameStore(result['store']) as frames:
            self.assertEqual(list(frames.line_numbers), list(range(1, 11)))
            self.assertEqual(frames[-1].timestamp, 86400)
            box = frames[5].boxes_on_T5[0]
            for field in fields(BoxInfo):
                if field.name.endswith('_line') or field.name == 't5_transfer_id':
                    self.assertEqual(getattr(box, field.name), 6, field.name)
            self.assertEqual(frames.source_location(6)['name'], 'second.old')
            self.assertEqual(frames.source_location(6)['source_line'], 1)
            self.assertEqual(frames.segment_index_for_frame(4), 0)
            self.assertEqual(frames.segment_index_for_frame(5), 1)
            analysis = frames.read_measurements()
            self.assertEqual(analysis['summary']['cycle_count'], 2)
            self.assertEqual(analysis['summary']['comparable_count'], 2)
            self.assertEqual([row['cycle'] for row in analysis['finals']], [1, 2])
            self.assertEqual(analysis['finals'][1]['display_frame_index'], 5)
            self.assertEqual(set(analysis['finals'][1]['sources'].values()), {6})
            self.assertEqual(frames.trace_period['observed_duration_seconds'], 8)
            self.assertEqual(len(frames.trace_period['gaps']), 1)

    def test_24h_totals_do_not_make_distant_days_critical(self):
        first = self.source('day1', '2025-01-01T12:00:00', ['OMEGA:T5-DemVidageComplet'] * 5, motor=True)
        second = self.source('day4', '2025-01-04T12:00:00', ['OMEGA:T5-DemVidageComplet'] * 5, motor=True)
        result = self.analyze([first, second])
        incidents = {row.code: row for row in result['diagnostics']}
        self.assertEqual(incidents['-88'].count, 10)
        self.assertEqual(incidents['-88'].metrics['max_24h_count'], 5)
        self.assertEqual(incidents['-88'].severity, 'warning')
        self.assertEqual(incidents['DemVidageComplet'].severity, 'info')
        daily = incidents['DemVidageComplet'].metrics['daily']
        self.assertEqual([row['count'] for row in daily], [5, None, None, 5])
        self.assertEqual([row['observed'] for row in daily], [True, False, False, True])

    def test_no_cross_segment_reset_camera_or_c2_pending(self):
        first = self.source('pending', '2025-01-01T12:00:00', [
            'Temps depuis RESET carte ALPHA : 100 mn',
            'CB1: ajout Hist_LectCB boite n1 0code(s) lu(s)',
            'idCB1: --> Réf:ALPHA-INC-001',
            "demande le transfert de EA->T3 'ALPHA-INC-001'",
            'relance le vidage machine'])
        second = self.source('newfile', '2025-01-01T12:00:05', [
            'Temps depuis RESET carte ALPHA : 0 mn',
            'Capteurs C2:1 C3:0 C4:0 C5:0 C6:0 C9:0',
            'CB2: ajout Hist_LectCB boite n1 0code(s) lu(s)',
            'idCB2: --> Réf:ALPHA-INC-001',
            "Création de la boite 'ALPHA-INC-001' UNKNOWN x=942 (60x30x100) IdA:1"])
        result = self.analyze([first, second])
        incidents = {row.code: row for row in result['diagnostics']}
        self.assertEqual(incidents['ALPHA_CARD_RESET'].count, 0)
        self.assertNotIn('C2_SIGNAL_ANOMALY', incidents)
        self.assertNotIn('UNKNOWN', incidents)
        with FrameStore(result['store']) as frames:
            report = frames.read_camera_report()
            self.assertEqual(report['total_boxes'], 2)
            self.assertEqual(report['unknown']['count'], 0)
            self.assertEqual(report['unknown']['buckets']['CB2 seul'], 1)

    def test_reset_threshold_uses_calendar_day_across_segments(self):
        first = self.source('reset1', '2025-01-31T09:00:00', [
            'Temps depuis RESET carte ALPHA : 100 mn',
            'Temps depuis RESET carte ALPHA : 0 mn'])
        second = self.source('reset2', '2025-01-31T12:00:00', [
            'Temps depuis RESET carte ALPHA : 100 mn',
            'Temps depuis RESET carte ALPHA : 0 mn',
            'Temps depuis RESET carte ALPHA : 100 mn',
            'Temps depuis RESET carte ALPHA : 0 mn'])
        result = self.analyze([first, second])
        reset, = [row for row in result['diagnostics'] if row.code == 'ALPHA_CARD_RESET']
        self.assertEqual(reset.count, 3)
        self.assertEqual(reset.metrics['max_daily_count'], 3)
        self.assertEqual(reset.severity, 'error')
        third = self.source('reset3', '2025-02-01T12:00:00', [
            'Temps depuis RESET carte ALPHA : 100 mn',
            'Temps depuis RESET carte ALPHA : 0 mn'])
        result = self.analyze([first, third], 'otherdays')
        reset, = [row for row in result['diagnostics'] if row.code == 'ALPHA_CARD_RESET']
        self.assertEqual(reset.count, 2)
        self.assertEqual(reset.metrics['max_daily_count'], 1)
        self.assertEqual(reset.severity, 'warning')
        self.assertEqual(reset.metrics['trace_duration'], '0 h 00 min 02 s')

    def test_business_events_do_not_merge_reused_robot_ids(self):
        text = "Création de la boite 'FICTIF' PRODUIT FICTIF x=942 (60x30x100) IdA:17"
        first = self.source('business1', '2025-01-01T09:00:00', [text])
        second = self.source('business2', '2025-01-01T10:00:00', [text])
        result = self.analyze([first, second])
        with FrameStore(result['store']) as frames:
            events = build_group_business_events(frames, result['events'], 'T5')
            headers = [event for event in events if event.header]
            self.assertEqual(len(headers), 2)
            self.assertEqual([event.line_num for event in headers], [1, 2])

    def test_fractional_single_source_preserves_parser_floats(self):
        source = self.source('fractional', '2025-01-01T09:00:00', ['FICTIF', 'FICTIF'],
                             motor=True, times=[0, 0.10000000009313226])
        with FrameStore(source['store']) as frames:
            expected = [asdict(frame) for frame in frames]
        result = self.analyze([source])
        with FrameStore(result['store']) as frames:
            self.assertEqual([asdict(frame) for frame in frames], expected)

    def test_unknown_rate_is_recomputed_with_all_populations(self):
        unknown = self.source('unknown', '2025-01-01T09:00:00', [
            'CB1: ajout Hist_LectCB boite n1 0code(s) lu(s)',
            'idCB1: --> Réf:ALPHA-INC-001',
            "demande le transfert de EA->T3 'ALPHA-INC-001'",
            'le transfert (EA->T3) est terminé',
            'CB2: ajout Hist_LectCB boite n1 0code(s) lu(s)',
            'idCB2: --> Réf:ALPHA-INC-001',
            "Création de la boite 'ALPHA-INC-001' UNKNOWN x=942 (60x30x100) IdA:1"])
        rows = []
        for index in range(20):
            rows.extend(['T2: Transfert de T2->EA terminé',
                         f'CB1: ajout Hist_LectCB boite n{index + 1} 1code(s) lu(s)',
                         f'idCB1: --> Réf:PRODUIT-{index}'])
        known = self.source('known', '2025-01-01T10:00:00', rows)
        result = self.analyze([unknown, known])
        self.assertNotIn('UNKNOWN', [row.code for row in result['diagnostics']])
        with FrameStore(result['store']) as frames:
            stats = frames.read_camera_report()['unknown']
            self.assertEqual(stats['count'], 1)
            self.assertEqual(stats['total'], 21)
            self.assertAlmostEqual(stats['ratio'], 1 / 21)

    def test_month_rollover_normalizes_frames_and_events(self):
        source = self.source('rollover', '2025-01-31T23:59:59', ['FICTIF', 'FICTIF'], motor=True)
        with FrameStore(source['store']) as frames:
            originals = [frame.deep_copy() for frame in frames]
        originals[1].timestamp = -31 * 86400 + 1
        originals[1].events[0].timestamp = originals[1].timestamp
        write_frame_store_iter(iter(originals), Path(source['store']))
        result = self.analyze([source])
        with FrameStore(result['store']) as frames:
            self.assertEqual(frames[1].timestamp, 1)
            self.assertEqual(frames[1].events[0].timestamp, 1)
            self.assertEqual(frames.trace_period['last_date'], '2025-02-01')

    def test_unreliable_dates_are_kept_separate(self):
        first = self.source('dated', '2025-01-01T12:00:00', ['FICTIF'])
        other = self.source('undated', '2025-01-02T12:00:00', ['FICTIF'])
        other.pop('start')
        with self.assertRaisesRegex(ValueError, 'calendrier fiable'):
            self.analyze([first, other])

    def test_duplicate_ranges_keep_original_source_navigation(self):
        first = self.source('original', '2025-01-01T12:00:00', ['FICTIF', 'FICTIF'])
        second = self.source('copied', '2025-01-01T13:00:00', ['FICTIF'] * 4)
        with FrameStore(second['store']) as frames:
            content = [frame.deep_copy() for frame in frames]
        write_frame_store_iter(iter(content), Path(second['store']), source_metadata={
            'duplicate_ranges': [{'first_line': 3, 'last_line': 4, 'source_first_line': 1}]})
        result = self.analyze([first, second])
        with FrameStore(result['store']) as frames:
            self.assertEqual(frames.source_metadata['duplicate_ranges'], [
                {'first_line': 5, 'last_line': 6, 'source_first_line': 3}])
            self.assertEqual(frames.source_location(6)['name'], 'copied.old')
            self.assertEqual(frames.source_location(6)['source_line'], 2)
            self.assertEqual(frames.frame_index_for_line(6), 3)


if __name__ == '__main__':
    unittest.main()
