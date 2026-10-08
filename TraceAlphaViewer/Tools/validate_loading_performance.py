"""Controle le contexte local et l'absence de fiches sans identite."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.diagnostic import _DIMENSION_CONTEXT_PATTERNS, _dimension_context_labels
from Models import reference_index
from Models.state import BoxInfo, MachineState


class ContextTests(unittest.TestCase):
    def test_inclusive_bounds_and_label_order(self):
        state = MachineState()
        lines = [(69, 'Une demande de vidage complet', state),
                 (70, 'Suppr. la boite', state),
                 (90, 'trop proche et FlagPoubellePleineLong', state),
                 (100, 'trop proche', state),
                 (130, 'T5-DemVidageComplet', state),
                 (131, 'Une demande de vidage complet', state)]
        self.assertEqual(_dimension_context_labels(lines, 100),
                         ['suppression T5', 'boite trop proche',
                          'poubelle pleine longue', 'vidage T5'])
        self.assertEqual(_dimension_context_labels(lines, 100, margin=0), ['boite trop proche'])

    def test_matches_full_scan_with_gaps_and_empty_windows(self):
        state = MachineState()
        lines = [(number, text, state) for number, text in (
            (1, 'A DETRUIRE'), (11, 'supp. de T5'), (40, 'T5-DemVidageComplet'),
            (80, 'FlagPoubellePleineLong trop proche'), (120, 'sans contexte'))]
        for data in ([], lines):
            for number in (0, 1, 10, 40, 75, 100, 120, 200):
                for margin in (0, 1, 30, 100):
                    expected = []
                    for current, text, _ in data:
                        if number - margin <= current <= number + margin:
                            for label, pattern in _DIMENSION_CONTEXT_PATTERNS:
                                if label not in expected and pattern.search(text):
                                    expected.append(label)
                    with self.subTest(line=number, margin=margin, empty=not data):
                        self.assertEqual(_dimension_context_labels(data, number, margin), expected)

    def test_local_lookup_does_not_visit_whole_trace(self):
        class CountedLines(list):
            visits = 0

            def __iter__(self):
                for item in super().__iter__():
                    self.visits += 1
                    yield item

            def __getitem__(self, key):
                result = super().__getitem__(key)
                self.visits += len(result) if isinstance(key, slice) else 1
                return result

        state = MachineState()
        lines = CountedLines((number, 'trop proche', state) for number in range(100_000))
        self.assertEqual(_dimension_context_labels(lines, 50_000), ['boite trop proche'])
        self.assertLess(lines.visits, 200, 'Une recherche locale parcourt trop de lignes')


class ReferenceAllocationTests(unittest.TestCase):
    def test_repeated_empty_boxes_allocate_no_records(self):
        empty = BoxInfo(name='sans identite', width_mm=20, x_pos=942)
        frames = [MachineState(line_num=i + 1, box_in_EA=empty, box_on_T3=empty,
                               box_on_T4=empty, boxes_on_T5=[empty]) for i in range(1000)]
        with patch.object(reference_index, 'ReferenceRecord', wraps=reference_index.ReferenceRecord) as records:
            self.assertEqual(reference_index.build_reference_records(frames, []), [])
            records.assert_not_called()

    def test_each_identity_alone_is_kept(self):
        boxes = [BoxInfo(id_alpha=1), BoxInfo(id_b=2),
                 BoxInfo(barcode='CIP'), BoxInfo(source_ref='ALPHA-INC-001')]
        frames = [MachineState(line_num=i + 1, box_on_T3=box) for i, box in enumerate(boxes)]
        records = reference_index.build_reference_records(frames, [])
        self.assertEqual([record.main_ref() for record in records],
                         ['IdA:1', 'idB:2', 'CIP', 'ALPHA-INC-001'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
