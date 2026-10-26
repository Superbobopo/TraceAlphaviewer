"""Regressions des relectures, copies de trace et identites T5 provisoires."""
from pathlib import Path
import pickle
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.diagnostic import _frame_line_states, _camera_stats, camera_report_stats
from Models.frame_store import FrameStore, write_frame_store
from Models.measurement_analysis import analyze_measurements
from Models.state import BoxInfo, MachineState
from Parser.trace_parser import parse_file
from Parser.trace_source import canonical_lines
from validate_reference_absent import cycle_lines, frames_for, CIP


class PassageCountingTests(unittest.TestCase):
    def test_failed_transfers_keep_one_passage_and_all_reads(self):
        rows = cycle_lines(1, known=True, direct=True)
        attempt = rows[:3] + ['tEA-T3: ERREUR transfert EA->T3 -43']
        frames = frames_for(attempt * 80 + rows)
        cycles = _camera_stats(_frame_line_states(frames))['cycles']
        self.assertEqual(len(cycles), 1)
        self.assertEqual(len(cycles[0].codes['CB1']), 81)
        self.assertEqual(sum('ERREUR transfert EA->T3' in text
                             for frame in frames for _, text, *_ in frame.raw_lines), 80)

    def test_new_arrivals_same_cip_and_confirmed_transfers_stay_distinct(self):
        rows = []
        for index in (1, 2):
            cycle = cycle_lines(index, known=True, direct=True)
            rows += ['T2: Transfert de T2->EA termine'] + cycle[:3]
            rows += ['tEA-T3: le transfert (EA->T3) est termine'] + cycle[3:]
        self.assertEqual(camera_report_stats(frames_for(rows))['total_boxes'], 2)

    def test_failed_transfer_at_eof_is_one_passage(self):
        rows = cycle_lines(1, known=True)[:3]
        rows += ['tEA-T3: ERREUR transfert EA->T3 -43']
        self.assertEqual(camera_report_stats(frames_for(rows * 4))['total_boxes'], 1)

    def test_new_box_on_ea_does_not_replace_box_on_t3(self):
        first = cycle_lines(1, known=True, direct=True)
        second = cycle_lines(2, known=True, direct=True)
        rows = first[:3] + ['tEA-T3: le transfert (EA->T3) est termine']
        rows += ['T2: Transfert de T2->EA termine'] + second[:2]
        rows += first[3:] + second[2:]
        self.assertEqual(camera_report_stats(frames_for(rows))['total_boxes'], 2)

    def test_anonymous_transfer_does_not_inherit_camera_or_create_second_box(self):
        rows = [f'idCB1: --> Ref:{CIP} lot:',
                "tT4*T5: Demande le transfert (physique) de la boite de T4 vers T5 '' ...",
                'tT4*T5: la boite est rendu (physiquement) sur T5',
                'tT4*T5: => longueur boite (BdD)=0 (T2T)=0 (T4C)=108 (T4T)=113 diffT4=-5mm (valable si FW>=v0.50)',
                "BdD: Creation de la boite '' -unknow x=1060 (0x0x108) IdA:101",
                'photoCamT5 AjoutBtT5.idA101.idB0']
        from Parser.trace_parser import _update
        state = MachineState(box_on_T4=BoxInfo(barcode=CIP, identified_barcode=CIP,
                             camera_identity_line=1, camera_identity_source='CB1'))
        ctx = {}; frames = []
        for line, text in enumerate(rows[1:], 2):
            state.line_num = line
            _update(state, text, ctx, line)
            frames.append(state.deep_copy())
        self.assertEqual(len(state.boxes_on_T5), 1)
        box = state.boxes_on_T5[0]
        self.assertEqual(box.id_alpha, 101)
        self.assertEqual(box.measured_t4_length_mm, 108)
        self.assertFalse(box.camera_identity_line)
        self.assertFalse(box.identified_barcode)
        summary = analyze_measurements(frames)['summary']
        self.assertEqual(summary['cycle_count'], 1)
        self.assertEqual(summary['excluded']['unknown'], 1)

    def test_provisional_token_never_merges_distinct_alpha_ids(self):
        one = BoxInfo(barcode=CIP, t5_transfer_id=1)
        frames = [MachineState(boxes_on_T5=[one.clone()])]
        one.id_alpha = 101
        frames.append(MachineState(boxes_on_T5=[one.clone()]))
        other = BoxInfo(barcode=CIP, id_alpha=102, t5_transfer_id=1)
        frames.append(MachineState(boxes_on_T5=[one.clone(), other]))
        self.assertEqual(analyze_measurements(frames)['summary']['cycle_count'], 2)

    def test_creation_wait_is_consumed_and_never_reuses_same_cip(self):
        from Parser.trace_parser import _update
        state = MachineState(box_on_T4=BoxInfo(barcode=CIP))
        ctx = {}
        _update(state, 'tT4*T5: la boite est rendu (physiquement) sur T5', ctx, 1)
        for line, ida in ((2, 101), (3, 102)):
            _update(state, f"BdD: Creation de la boite '{CIP}' PRODUIT x=1060 (0x0x90) IdA:{ida}", ctx, line)
        self.assertEqual([box.id_alpha for box in state.boxes_on_T5], [101, 102])

    def test_restart_does_not_reuse_pending_t5_box(self):
        from Parser.trace_parser import _update
        state = MachineState(box_on_T4=BoxInfo(barcode=CIP))
        ctx = {}
        _update(state, 'tT4*T5: la boite est rendu (physiquement) sur T5', ctx, 1)
        _update(state, 'version logiciel VBalpha: DEMO', ctx, 2)
        _update(state, f"BdD: Creation de la boite '{CIP}' PRODUIT x=1060 (0x0x90) IdA:101", ctx, 3)
        self.assertEqual(len(state.boxes_on_T5), 2)
        self.assertNotEqual(state.boxes_on_T5[0].id_alpha, 101)

    def test_transfer_without_source_cancels_previous_length_wait(self):
        from Parser.trace_parser import _update
        state = MachineState(box_on_T4=BoxInfo(barcode=CIP, id_b=1))
        ctx = {}
        _update(state, 'tT4*T5: la boite est rendu (physiquement) sur T5', ctx, 1)
        _update(state, 'tT4*T5: la boite est rendu (physiquement) sur T5', ctx, 2)
        _update(state, 'tT4*T5: => longueur boite (BdD)=90 (T2T)=90 (T4C)=99 (T4T)=98 diffT4=1mm (valable si FW>=v0.50)', ctx, 3)
        self.assertEqual(state.boxes_on_T5[0].measured_t4_line, 0)


class CopiedTraceTests(unittest.TestCase):
    def block(self):
        return [b'* 01|09:00:00.0 OUVERTURE DE LA TRACE le 01/10/2026\n',
                b' 01|09:00:00.1 version logiciel VBalpha: DEMO\n',
                b' 01|09:00:00.2 CB1: ajout Hist_LectCB (1code(s) lu(s))\n',
                b' 01|09:00:00.3 idCB1: --> Ref:3400000000001 lot:\n']

    def read(self, raw):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fictive.old'
            path.write_bytes(b''.join(raw))
            meta = {}
            lines = list(canonical_lines(path, meta))
            return lines, meta

    def test_complete_partial_and_repeated_copies(self):
        block = self.block()
        for copy in (block, block[:3], block + block):
            lines, meta = self.read(block + copy)
            self.assertEqual([line for _, line, _ in lines], [x.decode().rstrip() for x in block])
            self.assertTrue(meta['duplicate_ranges'])

    def test_new_content_after_copy_keeps_original_line_numbers(self):
        block = self.block()
        lines, meta = self.read(block + block + [b' 01|09:00:01.0 DONNEE INEDITE\n'])
        self.assertEqual(lines[-1][0], 9)
        self.assertIn('DONNEE INEDITE', lines[-1][1])
        self.assertEqual(meta['duplicate_ranges'], [dict(first_line=5, last_line=8, source_first_line=1)])

    def test_same_messages_other_dates_and_single_repeated_lines_are_kept(self):
        block = self.block()
        other = [line.replace(b'01/10/2026', b'02/10/2026').replace(b'01|', b'02|') for line in block]
        lines, meta = self.read(block + other + [other[-1]])
        self.assertEqual(len(lines), 9)
        self.assertFalse(meta['duplicate_ranges'])
        lines, meta = self.read(block + [block[0], b' 01|09:00:02.0 DIFFERENT\n'])
        self.assertEqual(len(lines), 6)
        self.assertFalse(meta['duplicate_ranges'])

    def test_parser_store_navigation_and_old_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fictive.old'
            raw = b''.join(self.block() * 2)
            path.write_bytes(raw)
            meta = {}
            frames = parse_file(str(path), min_dt=0.0, source_metadata_output=meta)
            self.assertEqual(camera_report_stats(frames)['total_boxes'], 1)
            store = Path(directory) / 'store'
            write_frame_store(frames, store, source_metadata=meta)
            with FrameStore(store) as reader:
                self.assertEqual(reader.frame_index_for_line(8), reader.frame_index_for_line(4))
            self.assertEqual(path.read_bytes(), raw)
            with (store / 'index.pkl').open('rb') as source:
                old = pickle.load(source)
            old.pop('source_metadata')
            with (store / 'index.pkl').open('wb') as output:
                pickle.dump(old, output)
            with FrameStore(store) as reader:
                self.assertEqual(reader.source_metadata, {})

    def test_worker_publishes_canonical_metadata_and_analyses(self):
        from Models.loading_worker import run
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fictive.old'
            path.write_bytes(b''.join(self.block() * 2))
            messages = []
            run(dict(mode='file', path=str(path), session=directory),
                lambda kind, value: messages.append((kind, value)))
            entry = next(value for kind, value in messages if kind == 'entry')
            with FrameStore(entry['store']) as store:
                self.assertTrue(store.source_metadata['duplicate_ranges'])
                self.assertEqual(store.frame_index_for_line(8), store.frame_index_for_line(4))
                self.assertEqual(store.read_camera_report()['total_boxes'], 1)


class LocalTraceTests(unittest.TestCase):
    @unittest.skipUnless((ROOT / 'TraceAlphaViewer/TracAlpha1_001.old').exists(), 'Trace locale absente')
    def test_001_counts_provenance_retries_and_navigation(self):
        meta = {}
        frames = parse_file(str(ROOT / 'TraceAlphaViewer/TracAlpha1_001.old'), min_dt=0.0,
                            source_metadata_output=meta)
        lines = _frame_line_states(frames)
        stats = _camera_stats(lines)
        self.assertEqual(len(stats['cycles']), 1609)
        self.assertEqual(camera_report_stats(frames, stats=stats)['unknown']['count'], 44)
        summary = analyze_measurements(frames)['summary']
        self.assertEqual((summary['cycle_count'], summary['comparable_count'], summary['excluded_count']),
                         (1609, 1361, 248))
        for ida, count in ((533742, 2), (533843, 80)):
            cycle, = [cycle for cycle in stats['cycles'] if cycle.id_alpha == ida]
            self.assertEqual(len(cycle.codes['CB1']), count)
        self.assertEqual(sum('ERREUR transfert EA->T3 -43' in text for _, text, _ in lines), 80)
        after = next(frame for frame in frames if frame.line_num == 297068)
        self.assertEqual(len(after.boxes_on_T5), 1)
        self.assertEqual(after.boxes_on_T5[0].id_alpha, 533511)
        self.assertFalse(after.boxes_on_T5[0].camera_identity_line)
        with tempfile.TemporaryDirectory() as directory:
            write_frame_store(frames, Path(directory), source_metadata=meta)
            with FrameStore(directory) as store:
                for span in meta['duplicate_ranges']:
                    self.assertEqual(store.frame_index_for_line(span['last_line']),
                                     store.frame_index_for_line(span['source_first_line'] +
                                                               span['last_line'] - span['first_line']))


if __name__ == '__main__':
    unittest.main()
