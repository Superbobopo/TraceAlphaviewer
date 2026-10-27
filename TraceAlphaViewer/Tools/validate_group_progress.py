"""Controle les progressions de segments fictifs et les callbacks historiques."""
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from Models.frame_store import write_frame_store_iter
from Models.group_analysis import analyze_group, analyze_segment
from Parser.trace_parser import iter_frames


class GroupProgressTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources = []
        for index in range(2):
            day = 24 + index
            path = self.root / f'fictive-{index}.old'
            lines = [f'OUVERTURE DE LA TRACE le {day}/10/2026\n']
            for tick in range(503):
                seconds, fraction = divmod(tick, 10)
                text = 'CubeStop:N' if tick == 0 else 'Message sans effet'
                lines.append(f'  {day}|00:00:{seconds:02d}.{fraction} {text}\n')
            path.write_text(''.join(lines), encoding='latin-1')
            store = self.root / f'store-{index}'
            write_frame_store_iter(iter_frames(str(path), min_dt=0.0), store)
            self.sources.append({'filepath': str(path), 'name': path.name, 'store': str(store),
                                 'start': datetime(2026, 10, day).isoformat()})

    def test_detailed_progress_serial_keeps_each_source_independent(self):
        detailed, legacy = [], []
        result = analyze_group(self.sources, self.root / 'detailed',
                               lambda *row: legacy.append(row), parallel=False,
                               progress_detail=lambda *row: detailed.append(row))
        self.assertEqual(result['frame_count'], 1006)
        self.assertTrue(legacy)
        self.assertTrue(all(len(row) == 4 for row in legacy))
        for source in self.sources:
            source_id = str(Path(source['filepath']).resolve())
            rows = [row for row in detailed if row[1] == source_id]
            self.assertTrue(rows)
            for phase in ('read', 'diagnostic', 'references'):
                values = [done / total for key, _, done, total, _ in rows if key == phase]
                self.assertTrue(values, phase)
                self.assertEqual(values, sorted(values), phase)
                self.assertEqual(values[0], 0.8 if phase == 'read' else 0)
                self.assertEqual(values[-1], 1, phase)
                self.assertTrue(all(0 <= value <= 1 for value in values))
            self.assertTrue(any(0.8 < done / total < 1 for phase, _, done, total, _ in rows
                                if phase == 'read'))
            self.assertTrue(any(0 < done / total <= 0.2 for phase, _, done, total, _ in rows
                                if phase == 'diagnostic'))
        self.assertEqual({row[1] for row in detailed},
                         {str(Path(source['filepath']).resolve()) for source in self.sources})

    def test_old_group_api_and_local_segment_callback_remain_compatible(self):
        old = analyze_group(self.sources, self.root / 'legacy')
        detailed = analyze_group(self.sources, self.root / 'new', progress_detail=lambda *row: None)
        for key in ('events', 'diagnostics', 'references', 'frame_count'):
            self.assertEqual(old[key], detailed[key], key)
        legacy, progress = [], []
        segment = old['metadata']['segments'][0]
        # Les anciens arguments positionnels restent acceptes.
        first = analyze_segment(old['store'], segment, datetime(2026, 10, 24), 0, 2,
                                'fictive-0.old', lambda *row: legacy.append(row))
        second = analyze_segment(old['store'], segment, datetime(2026, 10, 24), 0, 2,
                                 'fictive-0.old', progress_detail=lambda *row: progress.append(row))
        for key in set(first) - {'timings'}:
            self.assertEqual(first[key], second[key], key)
        self.assertTrue(all(len(row) == 4 for row in progress))
        self.assertTrue(all(len(row) == 4 for row in legacy))


if __name__ == '__main__':
    unittest.main(verbosity=2)
