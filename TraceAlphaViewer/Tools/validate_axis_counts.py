"""Compare diagnostics par axe, bilan unique et preuves de mesures multiaxes."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload
from Models.measurement_analysis import analyze_measurements
from Parser.trace_parser import _classify_alpha_measurement
from Tools.validate_measurement_report import samples


class AxisCountsTests(unittest.TestCase):
    def test_legacy_incident_requests_regeneration_without_recounting(self):
        frames = samples(12, -7)
        rows = build_diagnostics(frames, [])
        row = next(item for item in rows if item.code == 'T4_LENGTH')
        row.measurement_stats = dict(row.measurement_stats)
        row.measurement_stats.pop('axis_diagnostics_version')
        row.count = 1
        group = next(item for item in build_report_payload(rows, frames)['groups'] if item['code'] == 'T4_LENGTH')
        self.assertTrue(group['requires_regeneration'])
        self.assertIn('rechargez', group['affected_label'])
        self.assertEqual(group['occurrence_count'], 1)

    def test_mixed_axes_share_population_and_keep_global_unique(self):
        frames = samples(2535, 0)
        for i, frame in enumerate(frames):
            box = frame.boxes_on_T5[0]
            box.measured_t4_length_mm += -7 if i < 2004 else 7 if i < 2009 else 0
            if i < 1977:
                box.measured_t5_width_mm -= 4
            _classify_alpha_measurement(box)
        analysis = analyze_measurements(frames)
        rows = build_diagnostics(frames, [], analysis)
        axes = {row.code: row for row in rows if row.code in {'T4_LENGTH', 'T5_WIDTH', 'T5_HEIGHT', 'GLOBAL'}}
        self.assertNotIn('GLOBAL', axes)
        self.assertEqual(axes['T4_LENGTH'].count, 2009)
        self.assertEqual(axes['T5_WIDTH'].count, 1977)
        self.assertEqual(axes['T4_LENGTH'].severity, 'error')
        self.assertEqual(analysis['summary']['global']['outside_count'], 2009)
        self.assertEqual(len(axes['T4_LENGTH'].event_lines), 2009)
        payload = build_report_payload(rows, frames)
        for group in payload['groups']:
            if group['code'] == 'T4_LENGTH':
                self.assertEqual(group['occurrence_count'], 2009)
                self.assertAlmostEqual(group['affected_ratio'], 2009/2535)
                self.assertEqual(group['field_severity'], 'error')
                self.assertFalse(group['requires_regeneration'])
                self.assertEqual(len(group['examples']), 2009)
                self.assertTrue(any(sample['code'] == 'GLOBAL' for sample in group['examples']))

    def test_limits_three_axes_and_exclusions(self):
        frames = samples(5, 0)
        changes = [(3, 3, 2), (4, 4, 3), (-4, 0, 0), (0, -4, 0), (0, 0, -3)]
        for frame, (length, width, height) in zip(frames, changes):
            box = frame.boxes_on_T5[0]
            box.measured_t4_length_mm += length
            box.measured_t5_width_mm += width
            box.measured_t5_height_mm += height
            _classify_alpha_measurement(box)
        rows = {row.code: row for row in build_diagnostics(frames, [])}
        self.assertEqual([rows[key].count for key in ('T4_LENGTH', 'T5_WIDTH', 'T5_HEIGHT')], [2, 2, 2])
        self.assertEqual(analyze_measurements(frames)['summary']['global']['outside_count'], 4)
        self.assertTrue(all(rows[key].severity == 'warning' for key in ('T4_LENGTH', 'T5_WIDTH', 'T5_HEIGHT')))
        frames[1].boxes_on_T5[0].camera_identity_line = 0
        self.assertEqual(analyze_measurements(frames)['summary']['comparable_count'], 4)


if __name__ == '__main__':
    unittest.main()
