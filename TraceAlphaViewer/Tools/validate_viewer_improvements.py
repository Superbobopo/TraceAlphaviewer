"""Controle les identites, la recherche CIP et le cycle de vie des vues."""
from __future__ import annotations

import gc
import sys
import tempfile
import time
import unittest
import weakref
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

import customtkinter as ctk

from Main import TraceAlphaViewer
from Models.reference_index import build_reference_records
from Models.state import BoxInfo, MachineEvent, MachineState
from Parser.trace_parser import parse_file
from Views.BaseView import BaseView
from Views.traceView import TraceView
from Widgets.machine_canvas import MachineCanvas
from Widgets.reference_panel import ReferencePanel
from Widgets.trace_panel import TracePanel


def frame(line, box=None, stage='box_on_T3'):
    return MachineState(line_num=line, timestamp_str=f'08:00:{line:02d}', **{stage: box})


class ReferenceTests(unittest.TestCase):
    def test_same_cip_different_boxes(self):
        boxes = [BoxInfo(barcode='3400931234567', id_b=i) for i in (101, 102)]
        records = build_reference_records([frame(i, box) for i, box in enumerate(boxes, 1)], [])
        self.assertEqual([r.id_b for r in records], [101, 102])

    def test_identification_and_robot(self):
        frames = [
            frame(1, BoxInfo(barcode='ALPHA-INC-001'), 'box_in_EA'),
            frame(2, BoxInfo(barcode='3400931234567', source_ref='ALPHA-INC-001', id_b=101)),
            MachineState(line_num=3, boxes_on_T5=[BoxInfo(barcode='3400931234567', id_b=101, id_alpha=201)]),
        ]
        event = MachineEvent(4, 1.0, '08:00:04', 'info', 'BOITE', 'Robot prend IdA=201 X:942')
        records = build_reference_records(frames, [event])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].id_alpha, 201)
        self.assertEqual(records[0].stages, {'EA', 'T3', 'T5', 'ROBOT'})
        self.assertEqual(records[0].robot_line, 4)
        self.assertEqual(records[0].barcode, '3400931234567')

    def test_distinct_alpha_ids_and_ambiguous_cip(self):
        boxes = [BoxInfo(barcode='CIP', id_alpha=i) for i in (201, 202)]
        frames = [MachineState(line_num=1, boxes_on_T5=boxes),
                  frame(2, BoxInfo(barcode='CIP'), 'box_in_EA')]
        records = build_reference_records(frames, [])
        self.assertEqual(len(records), 3)

    def test_anonymous_cycle_ends_when_absent(self):
        records = build_reference_records([frame(1, BoxInfo(barcode='CIP')),
                                           frame(2), frame(3, BoxInfo(barcode='CIP'))], [])
        self.assertEqual(len(records), 2)

    def test_empty_boxes_do_not_create_references(self):
        records = build_reference_records([frame(1, BoxInfo()), frame(2), frame(3, BoxInfo())], [])
        self.assertEqual(records, [])

    def test_new_pre_t5_box_does_not_join_alpha_only_box(self):
        records = build_reference_records([
            MachineState(line_num=1, boxes_on_T5=[BoxInfo(barcode='CIP', id_alpha=201)]),
            frame(2, BoxInfo(barcode='CIP', id_b=102)),
        ], [])
        self.assertEqual(len(records), 2)

    def test_alpha_identity_has_priority(self):
        records = build_reference_records([
            frame(1, BoxInfo(barcode='CIP', id_alpha=201, id_b=101)),
            frame(2, BoxInfo(barcode='CIP', id_alpha=201, id_b=102)),
        ], [])
        self.assertEqual(len(records), 1)


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def pump_until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.assertTrue(predicate(), 'Le traitement asynchrone ne se termine pas')

    def test_cip_filter_lists_each_box(self):
        records = build_reference_records([
            frame(1, BoxInfo(barcode='3400931234567', id_b=101)),
            frame(2, BoxInfo(barcode='3400931234567', id_b=102)),
        ], [])
        clicked = []
        panel = ReferencePanel(self.root, records, on_reference_click=clicked.append)
        try:
            panel._search_var.set('3400931234567')
            self.assertEqual(len(panel._visible_records), 2)
            panel._open_first_result()
            self.assertEqual(clicked[0].first_line, 1)
            panel._search_var.set('idB:102')
            self.assertEqual([r.id_b for r in panel._visible_records], [102])
        finally:
            panel.destroy()

    def test_trace_search_reload_and_close(self):
        clicked = []
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            a, b = Path(directory) / 'a.old', Path(directory) / 'b.old'
            a.write_text('08:00:01 CIP:3400931234567\n08:00:02 CIP:3400931234567\n', encoding='latin-1')
            b.write_text('08:00:03 CIP:3400937654321\n', encoding='latin-1')
            panel = TracePanel(self.root, on_line_click=clicked.append)
            try:
                panel.load_file(str(a))
                panel._search_var.set('3400931234567')
                self.pump_until(lambda: not panel._loading and panel._search_job is None)
                self.assertEqual(len(panel._search_matches), 2)
                panel._navigate_search(1)
                panel._navigate_search(1)
                panel._navigate_search(1)
                panel._navigate_search(-1)
                self.assertEqual(clicked, [1, 2, 1, 2])
                panel._search_var.set('absent')
                self.pump_until(lambda: panel._search_job is None)
                self.assertEqual(panel._search_matches, [])
                panel.load_file(str(a))
                panel.load_file(str(b))
                panel._search_var.set('3400937654321')
                self.pump_until(lambda: not panel._loading and panel._search_job is None)
                self.assertEqual(len(panel._search_matches), 1)
                self.assertNotIn('3400931234567', panel._text.get('1.0', 'end'))
                panel.load_file(str(a))
            finally:
                panel.destroy()
            self.root.update()

    def test_trace_blocks_preserve_text_tags_and_navigation(self):
        clicked = []
        lines = [(i, 'CIP:3400931234567 ete' if i in (3000, 3001) else '')
                 for i in range(1, 3006)]
        lines[0] = (1, 'Premiere ligne accentuee : \u00e9')
        panel = TracePanel(self.root, on_line_click=clicked.append)
        try:
            panel._loading = True
            panel._start_insert(lines)
            self.assertTrue(panel._loading)
            self.assertIsNotNone(panel._insert_job)
            panel.highlight_lines(3000, 3001)
            panel._search_var.set('3400931234567')
            self.pump_until(lambda: not panel._loading and panel._search_job is None)
            expected = ''.join(f'L.{number:<7} {text}\n' for number, text in lines)
            self.assertEqual(panel._text.get('1.0', 'end-1c'), expected)
            for line in (1, 2, 3000, 3001, 3005):
                self.assertIn('linenum', panel._text.tag_names(f'{line}.0'))
                self.assertNotIn('known', panel._text.tag_names(f'{line}.0'))
            for line in (1, 3000, 3001):
                self.assertIn('known', panel._text.tag_names(f'{line}.10'))
                self.assertNotIn('linenum', panel._text.tag_names(f'{line}.10'))
            self.assertIn('hi', panel._text.tag_names('3000.10'))
            self.assertIn('hi_linenum', panel._text.tag_names('3001.0'))
            panel.mark_unknown_lines([1])
            self.assertIn('unknown', panel._text.tag_names('1.10'))
            self.assertNotIn('known', panel._text.tag_names('1.10'))
            panel._navigate_search(1)
            panel._navigate_search(1)
            self.assertEqual(clicked, [3000, 3001])
        finally:
            panel.destroy()
        self.root.update()

    def test_reload_cancels_pending_text_block(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'replacement.old'
            path.write_text('nouvelle trace\n', encoding='latin-1')
            panel = TracePanel(self.root)
            try:
                panel._loading = True
                panel._start_insert([(i, 'ancienne trace') for i in range(1, 6001)])
                self.assertIsNotNone(panel._insert_job)
                panel.load_file(str(path))
                self.pump_until(lambda: not panel._loading)
                self.assertEqual(panel._text.get('1.0', 'end-1c'), 'L.1       nouvelle trace\n')
                panel._loading = True
                panel._start_insert([(i, 'a fermer') for i in range(1, 6001)])
                self.assertIsNotNone(panel._insert_job)
            finally:
                panel.destroy()
            self.root.update()

    def test_discarded_view_releases_frames_and_callbacks(self):
        class Preview(BaseView):
            def __init__(self, master):
                super().__init__(master)
                self.frames = [MachineState()]
        host = ctk.CTkFrame(self.root)
        host.main_view = Preview(host)
        old = weakref.ref(host.main_view)
        state = weakref.ref(host.main_view.frames[0])
        invoked = []
        host.main_view.after(1, lambda: invoked.append(True))
        host.main_view.bind_shortcut('<Left>', lambda: None)
        try:
            for _ in range(3):
                TraceAlphaViewer.switch_view(host, Preview(host))
            gc.collect()
            self.assertIsNone(old())
            self.assertIsNone(state())
            self.root.update()
            self.assertEqual(invoked, [])
            self.assertEqual(len(host.winfo_children()), 1)
        finally:
            host.destroy()

    def test_complete_view_search_navigates_frames(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'trace.old'
            path.write_text('08:00:01 CIP:3400931234567\n08:00:02 CIP:3400931234567\n', encoding='latin-1')
            frames = [frame(i, BoxInfo(barcode='3400931234567', id_b=100+i)) for i in (1, 2)]
            view = TraceView(self.root, str(path), frames, events=[], diagnostics=[])
            try:
                view.show()
                view._trace_panel._search_var.set('3400931234567')
                self.pump_until(lambda: not view._trace_panel._loading and view._trace_panel._search_job is None)
                view._trace_panel._navigate_search(1)
                view._trace_panel._navigate_search(1)
                self.assertEqual(view._idx, 1)
                view._on_reference_click(view._references[0])
                self.assertEqual(view._idx, 0)
                view._start_playback()
                view.hide()
                self.assertFalse(view._playing)
            finally:
                view.destroy()
            self.root.update()

    def test_reused_canvas_matches_full_drawing(self):
        cached, fresh = MachineCanvas(self.root), MachineCanvas(self.root)
        def snapshot(canvas):
            return [(canvas.type(item), canvas.coords(item),
                     {key: value[-1] for key, value in canvas.itemconfigure(item).items()})
                    for item in canvas.find_all()]
        states = [MachineState(), MachineState(C4=True, C6=True, C9=True,
                  box_in_EA=BoxInfo(name='EA'), box_on_T4=BoxInfo(id_b=101, length_mm=70),
                  boxes_on_T5=[BoxInfo(id_alpha=201, x_pos=942, width_mm=40, length_mm=70)]),
                  MachineState(eT4=-44, flag_poubelle_pleine=True, lzb=50), MachineState()]
        try:
            trace = ROOT / 'TraceAlphaViewer' / 'TracAlpha1_012.old'
            if trace.exists():
                frames = parse_file(str(trace), min_dt=0.0)
                windows = (('08:31:15', '08:31:18'), ('08:31:52', '08:31:55'), ('08:15:02', '08:15:03'))
                selected = [f for f in frames if any(start <= f.timestamp_str[:8] <= end for start, end in windows)]
                self.assertTrue(selected, 'Les sequences T5 critiques sont absentes')
                for marker in ('MAJ (APRES-MESURE-LARG)', 'AjoutBtT5', 'place toutes les boites'):
                    selected.extend([f for f in frames if any(marker in str(raw[1]) for raw in f.raw_lines)][:6])
                states.extend(selected)
                print(f'Canvas T5 : comparaison de {len(selected)} frames des sequences critiques')
            for state in states:
                cached.update_state(state)
                fresh.delete('all')
                fresh._draw(state)
                self.assertEqual(snapshot(cached), snapshot(fresh), state.timestamp_str)
            ids = cached.find_all()
            cached.update_state(states[-1])
            self.assertEqual(cached.find_all(), ids)
            start = time.perf_counter()
            for _ in range(100):
                cached.update_state(states[-1])
            reused = time.perf_counter() - start
            start = time.perf_counter()
            for _ in range(100):
                fresh.delete('all')
                fresh._draw(states[-1])
            complete = time.perf_counter() - start
            print(f'Canvas identique, 100 rendus : reutilise {reused:.3f}s, complet {complete:.3f}s')
        finally:
            cached.destroy()
            fresh.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
