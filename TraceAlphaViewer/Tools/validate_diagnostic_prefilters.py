"""Compare les prefiltres aux regex completes, y compris leur casse Unicode."""
from pathlib import Path
from dataclasses import asdict
from datetime import datetime
import sys
import random
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Models import diagnostic as model
from Models.trace_calendar import TraceLines


def lines_for(text):
    samples = [text, text.upper(), text.lower(), text.swapcase(),
               text.upper().replace('I', '\u0130'), text.upper().replace('S', '\u017f'),
               text.replace(': ', ':\t'), 'Ligne sans fait', text[:12]]
    return TraceLines((index, value, model.DiagnosticState(float(index), '00:00:01', 0))
                      for index, value in enumerate(samples, 1))


class DiagnosticPrefilterTests(unittest.TestCase):
    def test_state_collector_matches_independent_scans(self):
        rng = random.Random(763)
        for trial in range(20):
            frames = []
            timestamp = 0.
            for index in range(300):
                timestamp += rng.choice((0., .5, 8., 120., -1.))
                frames.append(model.MachineState(
                    line_num=index + 1, timestamp=timestamp, timestamp_str=str(timestamp),
                    state_tT3_T4=rng.choice(('REPOS', 'WAIT-COND', 'WAIT-A', 'WAIT-B')),
                    state_T5=rng.choice(('REPOS', 'WAIT-COND', 'WAIT-A', 'WAIT-B')),
                    state_T2=rng.choice(('REPOS', 'WAIT-COND-TRSF', 'WAIT-FIN-TRSF')),
                    C2=rng.randrange(2), C3=rng.randrange(2), C4=rng.randrange(2),
                    C6=rng.randrange(2), C9=rng.randrange(2)))
            collector = model.StateIncidentCollector()
            for frame in frames:
                collector.consume(frame)
            expected = model._build_wait_incidents(frames) + model._build_t2_blocked_before_ea_incidents(frames)
            self.assertEqual([asdict(row) for row in collector.finish()],
                             [asdict(row) for row in expected], trial)

    def test_t4_initializations(self):
        lines = lines_for('InitMachine: demande initialisation de T4')
        expected = [number for number, text, _ in lines if model._TRACE_T4_INIT_REQUEST.search(text)]
        actual = model._build_t4_init_loop_incidents(lines, [])
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0].event_lines, expected)
        self.assertEqual(actual[0].count, len(expected))

    def test_c9_measurements(self):
        lines = lines_for('T5: largeur lue sur T5 < 2mm et C9=1')
        expected = [number for number, text, _ in lines if model._T5_WIDTH_C9_INVALID.search(text)]
        actual = model._build_c9_invalid_width_incidents(lines)
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0].event_lines, expected)

    def test_numbered_messages(self):
        for code, pattern, text in (
            ('017-Avt', model._TRACE_017, '017-Avt: boite coincXee sur C4 aprXs 3 ejects'),
            ('118-Vide T5', model._TRACE_118, '118-Vide T5 suite blocage poubelle')):
            lines = lines_for(text)
            expected = [number for number, value, _ in lines if pattern.search(value)]
            actual = [row for row in model._build_text_pattern_incidents(lines) if row.code == code]
            self.assertEqual(len(actual), 1)
            self.assertEqual(actual[0].event_lines, expected)

    def test_robot_requests(self):
        lines = lines_for('OMEGA:T5-DemVidageComplet')
        expected = [number for number, text, _ in lines if model._TRACE_T5_DEM_VIDAGE.search(text)]
        actual = model._build_robot_drain_incidents(lines)
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0].event_lines, expected)

    def test_shared_robot_calendar_matches_independent_calendar(self):
        for origin in (datetime(2024, 2, 28, 23, 59, 59), datetime(2026, 12, 31, 23, 59, 59)):
            for bounds in (None, (-1., 100000.)):
                rows = [(index, 'OMEGA:T5-DemVidageComplet' if index % 2 else 'Attente',
                         model.DiagnosticState(value, '00:00:00', 0))
                        for index, value in enumerate((0., .1, 2., 86400., 0., 10.), 1)]
                expected_period, actual_period = {}, {}
                expected = model._build_robot_drain_incidents(rows, origin, bounds, expected_period)
                actual = model._build_robot_drain_incidents(TraceLines(rows), origin, bounds, actual_period)
                self.assertEqual([asdict(row) for row in actual], [asdict(row) for row in expected])
                self.assertEqual(actual_period, expected_period)


if __name__ == '__main__':
    unittest.main()
