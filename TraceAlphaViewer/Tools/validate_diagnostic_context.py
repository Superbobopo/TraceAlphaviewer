"""Verifie la chronologie partagee et les controles sur les lignes ignorees."""
from pathlib import Path
from datetime import datetime, timedelta
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Models.trace_calendar import TraceLines, observation_clock, TimedObservation
from Models.robot_drain import TraceCalendar
from Models.diagnostic import DiagnosticState, _frame_line_states
from Models.c5_analysis import analyze_c5
from Models.c2_analysis import _signal_facts, analyze_c2, analyze_c3
from Tools.validate_c5_blockage import signal_rows
from Tools.validate_c2_signal import frames_for


class ContextTests(unittest.TestCase):
    def test_month_rollover_fractional_time_and_isolated_segments(self):
        origin = datetime(2026, 1, 31, 23, 59, 58, 500000)
        moments = [origin, origin+timedelta(seconds=1), origin+timedelta(seconds=2),
                   origin+timedelta(seconds=2), origin+timedelta(days=1, seconds=2)]
        def raw_seconds(moment):
            return moment.day*86400+moment.hour*3600+moment.minute*60+moment.second+moment.microsecond/1e6
        times = [raw_seconds(moment)-raw_seconds(origin) for moment in moments]
        lines = TraceLines((i, 'ligne quelconque', DiagnosticState(value, moment.strftime('%H:%M:%S'), 0))
                           for i, (value, moment) in enumerate(zip(times, moments), 1))
        previous = TraceCalendar(origin)
        expected = [(previous.at(value)-origin).total_seconds() for value in times]
        clock = observation_clock(lines, origin)
        self.assertEqual(list(clock.times), expected)
        self.assertIs(observation_clock(lines, origin), clock)
        for i, (line, text, state) in enumerate(lines):
            obs = TimedObservation(clock, line, expected[i], state.timestamp_str, text)
            self.assertIsNone(obs.label)
            self.assertEqual(dict(obs)['time_str'], moments[i].strftime('%d/%m/%Y à %H:%M:%S'))
        self.assertIsNot(observation_clock(TraceLines(lines), origin), clock)
        self.assertIsNot(observation_clock(lines, origin+timedelta(days=1)), clock)

    def test_ignored_lines_still_close_c5_context_and_keep_sources(self):
        frames = frames_for(signal_rows()+[(30, 'Message sans capteur'), (160, 'Autre message')])
        lines = _frame_line_states(frames)
        metrics, examples = analyze_c5(lines)
        episode = metrics['episodes'][0]
        filler_line = next(line for line, text, _ in lines if 'Message sans capteur' in text)
        self.assertEqual(episode['sources']['fin du contexte'], filler_line)
        self.assertIn('Interruption', episode['end_reason'])
        json.dumps((metrics, examples))

    def test_sensor_facts_shared_without_merging_detectors(self):
        frames = frames_for([(0, 'T2: WAIT-COND C2:1 C3:0 C4:0'),
                             (120, 'Message quelconque'), (121, 'T2: WAIT-COND C2:0 C3:1 C4:0')])
        lines = _frame_line_states(frames)
        facts = _signal_facts(lines)
        analyze_c2(lines)
        analyze_c3(lines)
        self.assertIs(_signal_facts(lines), facts)
        self.assertIsNot(_signal_facts(TraceLines(lines)), facts)

    def test_filtered_lines_do_not_create_an_artificial_gap(self):
        rows = signal_rows()+[(i, 'Message sans rapport') for i in (60, 120, 180, 240)]
        rows += signal_rows(250)
        metrics, _ = analyze_c5(_frame_line_states(frames_for(rows)))
        self.assertEqual(metrics['signal_episode_count'], 1)
        self.assertEqual(metrics['transitions'], 20)

    def test_repeated_text_keeps_distinct_times_and_sources(self):
        from Tools.validate_c5_blockage import ERROR
        metrics, _ = analyze_c5(_frame_line_states(frames_for([(i, ERROR) for i in (0, 60, 120)])))
        block = metrics['episodes'][0]
        self.assertEqual(block['duration_seconds'], 120)
        self.assertNotEqual(block['first_line'], block['last_line'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
