"""Controle les durees numeriques et les jours aux bornes du calendrier."""
from datetime import datetime, timedelta
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Models.diagnostic import DiagnosticState
from Models.robot_drain import TraceCalendar
from Models.trace_calendar import TraceLines, _build_calendar


class CalendarTicksTests(unittest.TestCase):
    def test_elapsed_equals_datetime_with_rollovers_and_rounding(self):
        for origin in (datetime(2024, 2, 28, 23, 59, 59), datetime(2026, 12, 31, 23, 59, 59),
                       datetime(2026, 10, 30, 12, 31, 42, 123456)):
            numeric, dated = TraceCalendar(origin), TraceCalendar(origin)
            rng = random.Random(501)
            stamps = [0., 0., .04, .05, .15, .25, .95, 1., 120., 120.000001]
            stamps.extend(index / 10 + rng.choice((0., .05, -.05)) for index in range(10000))
            stamps.extend(day * 86400 - numeric.base + fraction for day in
                          (31, 1, 2, 2, 1, 28, 29, 1) for fraction in (0., .1, 86399.9))
            for stamp in stamps:
                with self.subTest(origin=origin, timestamp=stamp):
                    self.assertEqual(numeric.elapsed(stamp), (dated.at(stamp) - origin).total_seconds())

    def test_calendar_days_at_microsecond_boundaries_and_backwards_times(self):
        origin = datetime(2024, 2, 28, 23, 59, 59)
        seconds = [0., .5, .9999994, .9999995, .9999996, 1., 86400., 86401.,
                   86399., 86401., 172801.]
        lines = TraceLines((index + 1, 'OUVERTURE DE LA TRACE le 28/02/2024' if index == 0 else '',
                            DiagnosticState(value, '23:59:59', 0)) for index, value in enumerate(seconds))
        result = _build_calendar(lines)
        moments = [origin + timedelta(seconds=value) for value in seconds]
        expected = []
        for index, moment in enumerate(moments):
            day = moment.date().isoformat()
            if not expected or expected[-1]['date'] != day:
                expected.append({'line': index + 1, 'date': day})
        self.assertEqual(result['segments'], expected)
        self.assertEqual(result['end'], moments[-1].strftime('%d/%m/%Y à %H:%M:%S'))
        self.assertEqual(result['duration_seconds'], seconds[-1])

    def test_late_anchor_empty_and_undated_sources(self):
        self.assertFalse(_build_calendar([])['available'])
        lines = TraceLines([(1, '', DiagnosticState(0., '23:59:59', 0)),
                            (2, '', DiagnosticState(.1, '23:59:59', 0)),
                            (3, '', DiagnosticState(1., '00:00:00', 0)),
                            (4, 'OUVERTURE DE LA TRACE le 01/01/2027', DiagnosticState(2., '00:00:01', 0))])
        result = _build_calendar(lines)
        self.assertEqual(result['segments'], [{'line': 1, 'date': '2026-12-31'},
                                             {'line': 3, 'date': '2027-01-01'}])
        self.assertEqual(result['start'], '31/12/2026 à 23:59:59')
        undated = _build_calendar(lines[:3])
        self.assertFalse(undated['available'])
        self.assertEqual((undated['start'], undated['end'], undated['duration_seconds']),
                         ('23:59:59', '00:00:00', 1.))


if __name__ == '__main__':
    unittest.main(verbosity=2)
