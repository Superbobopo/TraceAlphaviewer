"""Verifie le travail diagnostique annonce et les prefiltres d'identification."""
from dataclasses import asdict
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Models import diagnostic, identification_analysis as identification
from Tools.validate_motor_dp import dp_rows
from Tools.validate_reference_absent import cycle_lines, frames_for


def projected_lines(rows):
    return diagnostic.TraceLines((i, text, diagnostic.DiagnosticState(i, '09:00:00', 0))
                                 for i, text in enumerate(rows, 1))


class DiagnosticProgressTests(unittest.TestCase):
    def test_common_state_collector_matches_historical_passes(self):
        rng = random.Random(73)
        frames = []
        elapsed = 0
        for index in range(250):
            elapsed += rng.choice((0, 1, 8, 120, 121, 86400))
            frames.append(diagnostic.MachineState(timestamp=elapsed,
                timestamp_str=str(elapsed), line_num=index + 1,
                state_T2=rng.choice(('WAIT-COND-TRSF', 'WAIT-FIN-TRSF', 'INIT')),
                state_tT3_T4=rng.choice(('WAIT-COND', 'WAIT-FIN', 'WAIT-TRSF', 'INIT')),
                state_T5=rng.choice(('WAIT-COND', 'WAIT-FIN', 'WAIT-TRSF', 'INIT')),
                C2=1, C3=1, C4=rng.randrange(2), C6=rng.randrange(2), C9=rng.randrange(2)))
        expected = (diagnostic._build_wait_incidents(frames)
                    + diagnostic._build_t2_blocked_before_ea_incidents(frames))
        collector = diagnostic.StateIncidentCollector()
        for frame in frames:
            collector.consume(frame)
        self.assertEqual([asdict(row) for row in collector.finish()], [asdict(row) for row in expected])

    def test_progress_is_cumulative_and_results_unchanged(self):
        frames = frames_for([text for _, text in dp_rows()])
        before_camera, after_camera, progress = {}, {}, []
        expected = diagnostic.build_diagnostics(frames, [], camera_report_output=before_camera)
        actual = diagnostic.build_diagnostics(frames, [], camera_report_output=after_camera,
            progress_cb=lambda family, done, total: progress.append((family, done, total)))
        self.assertEqual([asdict(row) for row in actual], [asdict(row) for row in expected])
        self.assertEqual(after_camera, before_camera)
        fractions = [done / total for _, done, total in progress]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(progress[0][1], 0)
        self.assertEqual(progress[-1], ('finished', 1, 1))
        self.assertTrue(all(value < 1 for value in fractions[:-1]))

    def test_failed_family_never_announces_finished(self):
        progress = []
        with patch.object(diagnostic, '_build_c5_incidents', side_effect=RuntimeError('fictif')):
            with self.assertRaisesRegex(RuntimeError, 'fictif'):
                diagnostic.build_diagnostics([], [], progress_cb=lambda *row: progress.append(row))
        self.assertNotIn('finished', [row[0] for row in progress])
        self.assertLess(progress[-1][1], progress[-1][2])

    def test_camera_progress_counts_visited_rows(self):
        frames = frames_for(['Message sans lecture'] * 9000 + cycle_lines(1, known=True))
        lines = diagnostic._frame_line_states(frames)
        progress = []
        stats = diagnostic._camera_stats(lines, progress_cb=lambda *row: progress.append(row))
        self.assertEqual(stats['decoding_distribution']['total'], 1)
        self.assertIn(4096, [row[0] for row in progress])
        self.assertIn(8192, [row[0] for row in progress])
        self.assertEqual(progress[-1], (1, 1))
        fractions = [done / total if total else 0 for done, total in progress]
        self.assertEqual(fractions, sorted(fractions))

    def test_shared_camera_collection_matches_full_scan(self):
        rows = cycle_lines(1, known=True) + cycle_lines(2, recovered=True)
        rows += ['idCB1: on a recu PR<Soh>1<Dc2>code<Dc2>',
                 'idCB2: on a recu PR/Soh/3 suite PR\x013',
                 'idCB1: PR<Soh>6 texte accentue e\u0301',
                 'IDCB2: PR<Soh>3', 'idCB1: sans PR', 'Message Cb1: divers']
        lines = projected_lines(rows)
        expected_hist, expected_success = [], {'CB1': {}, 'CB2': {}}
        for line, text, state in lines:
            if 'cb' not in text.lower():
                continue
            if diagnostic._CAMERA_HIST.search(text):
                expected_hist.append((line, state.timestamp, state.timestamp_str))
            match = diagnostic._CAMERA_SUCCESS_READER.search(text)
            if match and 'PR' in text:
                reader = 'CB' + match[1]
                for token in diagnostic._CAMERA_SUCCESS_TOKEN.finditer(text):
                    camera = token[1]
                    if camera in diagnostic._CAMERA_EXPECTED[reader]:
                        expected_success[reader][camera] = expected_success[reader].get(camera, 0) + 1
        stats = diagnostic._camera_stats(lines)
        self.assertEqual(stats['hist_samples'], expected_hist)
        self.assertEqual(stats['success_by_reader'], expected_success)

    def test_prefilter_matches_unfiltered_cycles_and_unicode(self):
        rows = cycle_lines(1, known=True) + cycle_lines(2, recovered=True)
        rows += [text for _, text in dp_rows(id_b=9, id_a=31)]
        rows += ['version logiciel VBalpha: 1',
                 'CB1: ajout Hi\u017ft_LectCB lecture 1code(s) lu(s)',
                 'idCB1: --> R\u00e9f:3400000000001',
                 'Cr\u00e9ation de la boite \'3400000000001\' FICTIF IdA:42',
                 'T2: Transfert de T2->EA termine']
        lines = projected_lines(rows)
        output, unfiltered_output = {}, {}
        actual = identification.identification_cycles(lines, dp_output=output)
        with patch.object(identification, '_identification_candidates', return_value=identification._ALL_ROWS):
            expected = identification.identification_cycles(lines, dp_output=unfiltered_output)
        self.assertEqual([asdict(row) for row in actual], [asdict(row) for row in expected])
        self.assertEqual(output, unfiltered_output)
        self.assertEqual(identification._identification_candidates('Message sans lecture'), 0)
        self.assertEqual(identification._identification_candidates('Hi\u017ft'), identification._ALL_ROWS)

    def test_timeouts_and_restarts_remain_independent_of_text_cache(self):
        rows = [text for _, text in dp_rows()]
        rows += ['Message sans lecture'] * 1500
        rows += ['version logiciel VBalpha: 1'] + [text for _, text in dp_rows()]
        lines = diagnostic._frame_line_states(frames_for(rows))
        actual_output, expected_output = {}, {}
        actual = identification.identification_cycles(lines, dp_output=actual_output)
        with patch.object(identification, '_identification_candidates', return_value=identification._ALL_ROWS):
            expected = identification.identification_cycles(lines, dp_output=expected_output)
        self.assertEqual([asdict(row) for row in actual], [asdict(row) for row in expected])
        self.assertEqual(actual_output, expected_output)
        self.assertEqual(len(actual), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
