"""Valide les fantomes T5 sur frames, transport natif et canvas masque."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.state import BoxInfo, MachineState
from Models.t5_ghosts import (
    BELT_WIDTH_PX, BELT_HEIGHT_PX, ENTRY_FROM_RIGHT_PX, SCALE,
    advance_ghosts, remember_deleted, reconcile_ghosts, box_size_px,
)
from Parser.trace_parser import _update, _is_significant, parse_file


def fixture():
    texts = [
        'T5: AUTO eT5=10 larg:40 C9:0 pT5:100 eT5useO:0 eT5useA:0',
        "BdD: Création de la boite 'ALPHA-INC-001' Inconnue x=4125 (40x50x70) IdA:123",
        'AjoutBtT5.idA123.idB3',
        'MAJ (BUTEE-T5) boite Id:123 ref:ALPHA-INC-001 nvlle dim:40x50 X:4125',
        'T5: AUTO eT5=10 larg:40 C9:0 pT5:120 eT5useO:0 eT5useA:0',
        'T5: AUTO eT5=10 larg:40 C9:0 pT5:180 eT5useO:0 eT5useA:0',
        'Suppr. la boite IdA:123', 'Suppr. la boite IdA:123',
        'T5: AUTO eT5=10 larg:40 C9:0 pT5:280 eT5useO:0 eT5useA:0',
        'ALPHA:T5-LIST-PACK@FP',
        'T5: AUTO eT5=10 larg:40 C9:0 pT5:230 eT5useO:0 eT5useA:0',
        "BdD: Création de la boite 'ALPHA-INC-001' Autre x=4275 (40x50x70) IdA:124",
        '-suppression de la boite ID:124',
        'T5: AUTO eT5=10 larg:40 C9:0 pT5:290 eT5useO:0 eT5useA:0',
        "BdD: Création de la boite 'ALPHA-INC-001' Inconnue x=4125 (40x50x70) IdA:123",
        'supp. de T5 la boite Id:123 ref:ALPHA-INC-001',
        'T5: AUTO eT5=10 larg:40 C9:0 pT5:2290 eT5useO:0 eT5useA:0',
    ]
    return '\n'.join(f' 05|09:00:{i:02}.0  {text}' for i, text in enumerate(texts)) + '\n'


class GhostTests(unittest.TestCase):
    def test_frames_and_native_transport(self):
        from Tools.validate_native_parser import validate
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='ghosts-') as name:
            directory = Path(name)
            path = directory / 'fictive.old'
            path.write_text(fixture(), encoding='latin-1')
            frames = parse_file(str(path), min_dt=0.0)
            by_line = {frame.line_num: frame for frame in frames}
            self.assertFalse(by_line[7].boxes_on_T5)
            first = by_line[7].t5_ghost_boxes[0]
            self.assertEqual(first.t5_deleted_line, 7)
            self.assertEqual(len(by_line[8].t5_ghost_boxes), 1)
            self.assertAlmostEqual(by_line[9].t5_ghost_boxes[0].t5_ghost_x_mm, first.t5_ghost_x_mm + 100)
            self.assertAlmostEqual(by_line[11].t5_ghost_boxes[0].t5_ghost_x_mm, first.t5_ghost_x_mm + 50)
            self.assertEqual(len(by_line[13].t5_ghost_boxes), 2)
            self.assertEqual([g.id_alpha for g in by_line[15].t5_ghost_boxes], [124])
            self.assertFalse(frames[-1].t5_ghost_boxes)
            from Models.diagnostic import build_diagnostics
            from Models.reference_index import build_reference_records
            events = [event for frame in frames for event in frame.events]
            without_ghosts = [frame.deep_copy() for frame in frames]
            for frame in without_ghosts:
                frame.t5_ghost_boxes = []
            self.assertEqual(build_diagnostics(frames, events), build_diagnostics(without_ghosts, events))
            self.assertEqual(build_reference_records(frames, events), build_reference_records(without_ghosts, events))
            validate(path, directory, analyses=True)
            empty = directory / 'suivante.old'
            empty.write_text(' 05|10:00:00.0  T0: AUTO eT0:0 C0:0\n', encoding='latin-1')
            self.assertFalse(parse_file(str(empty), min_dt=0.0)[0].t5_ghost_boxes)

    def test_identity_and_removal_formats(self):
        for text in ('Suppr. la boite IdA:1', '-suppression de la boite ID:1',
                     'supp. de T5 la boite Id:1 ref:ALPHA-INC-001'):
            state = MachineState(boxes_on_T5=[
                BoxInfo(id_alpha=1, barcode='ALPHA-INC-001', x_pos=1100),
                BoxInfo(id_alpha=2, barcode='ALPHA-INC-001', x_pos=1200),
            ])
            _update(state, text, {}, 10)
            self.assertEqual([b.id_alpha for b in state.boxes_on_T5], [2])
            self.assertEqual([b.id_alpha for b in state.t5_ghost_boxes], [1])
        state = MachineState(boxes_on_T5=[
            BoxInfo(id_alpha=1, barcode='ALPHA-INC-001', identified_barcode='DEMO', x_pos=1100),
            BoxInfo(id_alpha=2, barcode='DEMO', source_ref='ALPHA-INC-002', x_pos=1200),
        ])
        _update(state, 'Suppr. la boite IdA:1', {}, 11)
        _update(state, 'Suppr. la boite IdA:2', {}, 12)
        self.assertFalse(state.t5_ghost_boxes)
        unknown = BoxInfo(id_alpha=3, id_b=4, t5_transfer_id=5, barcode='-unknow', x_pos=1100)
        remember_deleted(state, unknown, 13)
        for changes in ({'id_alpha': 6}, {'id_b': 7}, {'t5_transfer_id': 8}):
            other = unknown.clone()
            other.__dict__.update(changes)
            state.boxes_on_T5 = [other]
            reconcile_ghosts(state)
            self.assertEqual(len(state.t5_ghost_boxes), 1)
        state.boxes_on_T5 = [unknown.clone()]
        reconcile_ghosts(state)
        self.assertFalse(state.t5_ghost_boxes)
        state.boxes_on_T5 = [BoxInfo(barcode='-unknow', id_alpha=i) for i in (1, 2)]
        _update(state, 'supp. de T5 la boite Id:0 ref:-unknow', {}, 14)
        self.assertEqual(len(state.boxes_on_T5), 2)
        self.assertFalse(state.t5_ghost_boxes)

    def test_motion_snapshots_and_clipping(self):
        for entry in (False, True):
            for origin in (0, 1000, 4125):
                state = MachineState(t5_x_butee=origin, t5_visual_offset_mm=50)
                box = BoxInfo(barcode='-unknow', x_pos=origin + 100 if origin else 1100,
                              width_mm=50, length_mm=80, t5_entry_aligned=entry)
                remember_deleted(state, box, 10)
                before = state.deep_copy()
                advance_ghosts(state, 100)
                self.assertAlmostEqual(state.t5_ghost_boxes[0].t5_ghost_x_mm,
                                       before.t5_ghost_boxes[0].t5_ghost_x_mm + 100)
                self.assertTrue(_is_significant(before, state))
                advance_ghosts(state, -100)
                self.assertAlmostEqual(state.t5_ghost_boxes[0].t5_ghost_x_mm,
                                       before.t5_ghost_boxes[0].t5_ghost_x_mm)
                advance_ghosts(state, 2000)
                self.assertFalse(state.t5_ghost_boxes)
                advance_ghosts(before, -2000)
                self.assertFalse(before.t5_ghost_boxes)

    def test_canvas_reuse_hover_and_interpolation(self):
        import tkinter as tk
        from Widgets.machine_canvas import (
            MachineCanvas, L, _t5_physical_scale, _t5_entry_visual_x,
            _t5_box_dims_px, _draw_t5_box, _t5_render_x_pos, _t5_visual_origin,
        )
        from Views.traceView import TraceView
        self.assertEqual(L['T5'][2] - L['T5'][0], BELT_WIDTH_PX)
        self.assertEqual(L['T5'][3] - L['T5'][1], BELT_HEIGHT_PX)
        self.assertEqual(L['T5'][2] - (L['T4'][0] + L['T4'][2]) // 2, ENTRY_FROM_RIGHT_PX)
        self.assertEqual(_t5_physical_scale(), SCALE)
        root = tk.Tk()
        root.withdraw()
        try:
            cv = MachineCanvas(root)
            state = MachineState(boxes_on_T5=[BoxInfo(id_alpha=2, barcode='DEMO', x_pos=1200)])
            for entry in (False, True):
                for origin in (0, 1000, 4125):
                    state.t5_x_butee = origin
                    state.t5_visual_offset_mm = 50
                    box = BoxInfo(id_alpha=1, barcode='ALPHA-INC-001', x_pos=origin + 100 if origin else 1100,
                                  width_mm=50, length_mm=80, t5_entry_aligned=entry)
                    width, height = _t5_box_dims_px(box, L['T5'], SCALE)
                    x = (_t5_entry_visual_x(state, box, width) if entry else
                         L['T5'][2] - int((_t5_render_x_pos(state, box) - _t5_visual_origin(state)) * SCALE) - width)
                    expected = _draw_t5_box(cv, L['T5'], x, width, height, box)
                    state.t5_ghost_boxes = []
                    remember_deleted(state, box, 10)
                    ghost = state.t5_ghost_boxes[0]
                    x = L['T5'][2] - round(ghost.t5_ghost_x_mm * SCALE) - width
                    self.assertEqual(_draw_t5_box(cv, L['T5'], x, width, height, ghost), expected)
            cv.delete('all')
            cv.update_state(state)
            reused = [(cv.type(i), cv.coords(i), cv.itemcget(i, 'state')) for i in cv.find_all()]
            cv.update_state(state)
            self.assertEqual(reused, [(cv.type(i), cv.coords(i), cv.itemcget(i, 'state')) for i in cv.find_all()])
            rectangles = [i for i in cv.find_all() if cv.type(i) == 'rectangle' and cv.itemcget(i, 'stipple') == 'gray25']
            self.assertTrue(rectangles)
            complete = MachineCanvas(root)
            complete._draw(state)
            def primitives(canvas):
                return [(canvas.type(i), canvas.coords(i),
                         {key: option[-1] for key, option in canvas.itemconfigure(i).items()})
                        for i in canvas.find_all()]
            self.assertEqual(primitives(cv), primitives(complete))
            complete.destroy()
            cv._show_t5_tooltip(300, 450, ghost)
            self.assertIn('présence physique supposée', '\n'.join(cv.itemcget(i, 'text') for i in cv.find_withtag('t5_tooltip') if cv.type(i) == 'text'))
            start = state.deep_copy()
            end = state.deep_copy()
            advance_ghosts(end, 100)
            view = TraceView.__new__(TraceView)
            middle = view._interpolated_state(start, end, 0.5)
            self.assertAlmostEqual(middle.t5_ghost_boxes[0].t5_ghost_x_mm, ghost.t5_ghost_x_mm + 50)
            end.raw_lines = [(11, 'Suppr. la boite IdA:2')]
            middle = view._interpolated_state(start, end, 0.5)
            self.assertEqual(middle.t5_ghost_boxes, start.t5_ghost_boxes)
            cv.destroy()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
