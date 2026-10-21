"""Regressions des passages camera et des references absentes, sur traces fictives."""
from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.diagnostic import build_diagnostics, camera_report_stats
from Models.diagnostic_report import build_report_payload
from Parser.trace_parser import parse_file


CIP = '3400000000001'


def refusal(reader, cip=CIP):
    return (f"idCB{reader}: la réf. {cip} n'est pas dans les tables, elle est donc 'A DETRUIRE' "
            '(pas dans BdD, refus de création dans param)')


def cycle_lines(index, *, missing=(), known=False, recovered=False, direct=False):
    first = f'ALPHA-DET-A{index}' if 1 in missing else CIP if known else f'ALPHA-INC-A{index}'
    final = CIP if recovered or known else f'ALPHA-DET-B{index}' if 2 in missing else first
    rows = [f'CB1: ajout Hist_LectCB (lecture n°1 boite n°1 {int(known or 1 in missing)}code(s) lu(s))']
    if 1 in missing:
        rows.append(refusal(1))
    rows += [f'idCB1: --> Réf:{first} lot: SN: DP:12/2099',
             f"tEA-T3: demande le transfert de EA->T3 '{first}' ..."]
    if direct:
        rows.append(f"idCB2: Identif. sur le lecteur1 Ok '{first}' (Nboite= {index})")
    else:
        rows += [f'idCB2: Lance identification (car idCB1.Ref:{first}) ...',
                 f'CB2: ajout Hist_LectCB (lecture n°1 boite n°1 {int(known or recovered or 2 in missing)}code(s) lu(s))']
        if 2 in missing:
            rows.append(refusal(2))
        rows += [f'idCB2: --> Réf:{final} lot: SN: DP:12/2099', f'idCB2: (Nboite= {index})']
    rows += [f"tT3/T4: demande le transfert de T3->T4 C5:1 C6:0 '{final}' ...",
             f'tT3/T4: transfert T3->T4 terminé, longueur=90 mm (idB={index})',
             f"tT4*T5: Demande le transfert (physique) de la boite de T4 vers T5 '{final}' ...",
             f"BdD: Création de la boite '{final}' {'PRODUIT FICTIF' if final == CIP else '-unknow'} x=1000 (0x0x90) IdA:{100 + index}",
             f'photoCamT5 AjoutBtT5.idA{100 + index}.idB{index}']
    return rows


def frames_for(rows):
    with tempfile.TemporaryDirectory(prefix='identification-') as directory:
        path = Path(directory) / 'fictive.old'
        path.write_text('\n'.join(f' 01|09:{i // 600:02d}:{i // 10 % 60:02d}.{i % 10} {text}'
                                  for i, text in enumerate(rows)), encoding='cp1252')
        return parse_file(str(path), min_dt=0.0)


class ReferenceAbsentTests(unittest.TestCase):
    def analyze(self, rows):
        frames = frames_for(rows)
        incidents = build_diagnostics(frames, [])
        return frames, {item.code: item for item in incidents}

    def test_reused_hist_counters_count_physical_passages(self):
        frames, incidents = self.analyze(cycle_lines(1) + cycle_lines(2, known=True, direct=True)
                                         + cycle_lines(3, missing=(2,)))
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 3)
        self.assertEqual(incidents['UNKNOWN'].count, 1)
        self.assertEqual(incidents['UNKNOWN'].metrics['total_boxes'], 3)
        self.assertEqual(incidents['UNKNOWN'].metrics['unknown_buckets']['CB1+CB2'], 1)
        self.assertEqual(sum(incidents['UNKNOWN'].metrics['unknown_buckets'].values()), 1)
        self.assertEqual(incidents['REFERENCE_ABSENT'].count, 1)

    def test_both_readers_count_one_absent_reference_cycle(self):
        frames, incidents = self.analyze(cycle_lines(1, missing=(1, 2)))
        incident = incidents['REFERENCE_ABSENT']
        self.assertEqual(incident.count, 1)
        self.assertEqual(incident.metrics['refusal_count'], 2)
        self.assertEqual(incident.metrics['references'], [CIP])
        self.assertEqual(incident.examples[0]['readers'], ['CB1', 'CB2'])
        self.assertEqual(incident.examples[0]['technical_references'], ['ALPHA-DET-A1', 'ALPHA-DET-B1'])
        self.assertIn('IdA:101', incident.examples[0]['box'])
        self.assertNotIn('UNKNOWN', incidents)
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 1)

    def test_cb1_refusal_survives_direct_cb2(self):
        frames, incidents = self.analyze(cycle_lines(1, missing=(1,), direct=True))
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 1)
        self.assertEqual(incidents['REFERENCE_ABSENT'].count, 1)
        self.assertNotIn('UNKNOWN', incidents)

    def test_same_cip_on_several_boxes_is_not_merged(self):
        frames, incidents = self.analyze(cycle_lines(1, missing=(2,)) + cycle_lines(2, missing=(2,)))
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 2)
        self.assertEqual(incidents['REFERENCE_ABSENT'].count, 2)
        self.assertEqual(incidents['REFERENCE_ABSENT'].metrics['reference_count'], 1)

    def test_interleaved_readers_preserve_original_cip_per_box(self):
        first = cycle_lines(1, missing=(2,))
        second_cip = '3400000000002'
        second = [row.replace(CIP, second_cip) for row in cycle_lines(2, missing=(1,))]
        frames, incidents = self.analyze(first[:3] + second[:3] + first[3:] + second[3:])
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 2)
        item = incidents['REFERENCE_ABSENT']
        self.assertEqual(item.metrics['reference_count'], 2)
        self.assertEqual({sample['barcode'] for sample in item.examples}, {CIP, second_cip})
        self.assertEqual({sample['box'] for sample in item.examples}, {'idB:1 · IdA:101', 'idB:2 · IdA:102'})

    def test_camera_threshold_stays_strictly_above_seven_percent(self):
        rows = [row for index in range(1, 101) for row in cycle_lines(index, known=index > 7, direct=index > 7)]
        _, incidents = self.analyze(rows)
        self.assertNotIn('UNKNOWN', incidents)
        _, incidents = self.analyze(rows + cycle_lines(101))
        self.assertEqual(incidents['UNKNOWN'].count, 8)

    def test_refusal_before_end_of_trace_is_reported(self):
        _, incidents = self.analyze([refusal(2)])
        item = incidents['REFERENCE_ABSENT']
        self.assertEqual(item.count, 1)
        self.assertEqual(item.examples[0]['barcode'], CIP)
        self.assertEqual(item.examples[0]['technical_references'], [])

    def test_successful_reread_does_not_count_as_final_unknown(self):
        frames, incidents = self.analyze(cycle_lines(1, recovered=True))
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 1)
        self.assertNotIn('UNKNOWN', incidents)
        self.assertNotIn('REFERENCE_ABSENT', incidents)

    def test_later_success_keeps_historical_refusal(self):
        frames, incidents = self.analyze(cycle_lines(1, missing=(1,), recovered=True)
                                         + cycle_lines(2, known=True))
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 2)
        self.assertEqual(incidents['REFERENCE_ABSENT'].count, 1)
        self.assertNotIn('UNKNOWN', incidents)

    def test_dimension_rejection_is_not_an_absent_reference(self):
        rows = [text.replace('ALPHA-INC-A1', 'ALPHA-DET-001[DINH]') for text in cycle_lines(1)]
        _, incidents = self.analyze(rows)
        self.assertNotIn('REFERENCE_ABSENT', incidents)

    def test_file_reopening_preserves_current_passage(self):
        rows = cycle_lines(1)
        rows.insert(5, '#################### OUVERTURE DE LA TRACE ####################')
        frames, incidents = self.analyze(rows)
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 1)
        self.assertEqual(incidents['UNKNOWN'].count, 1)

    def test_software_restart_starts_new_identity_namespace(self):
        frames, incidents = self.analyze(cycle_lines(1, missing=(2,))
            + ['version logiciel VBalpha: DEMO'] + cycle_lines(1, missing=(2,)))
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 2)
        self.assertEqual(incidents['REFERENCE_ABSENT'].count, 2)

    def test_missing_t5_transfer_or_added_line_never_reuses_closed_box(self):
        rows = cycle_lines(1, known=True) + cycle_lines(2, known=True)
        rows = [row for row in rows if 'AjoutBtT5' not in row and 'transfert (physique)' not in row]
        frames, incidents = self.analyze(rows)
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 2)
        self.assertNotIn('UNKNOWN', incidents)

    def test_reused_technical_reference_keeps_distinct_alpha_ids(self):
        rows = cycle_lines(1) + [row.replace('ALPHA-INC-A2', 'ALPHA-INC-A1') for row in cycle_lines(2)]
        frames, incidents = self.analyze(rows)
        self.assertEqual(camera_report_stats(frames)['total_boxes'], 2)
        self.assertEqual(incidents['UNKNOWN'].count, 2)

    def test_report_keeps_original_cip_and_sources(self):
        frames, incidents = self.analyze(cycle_lines(1, missing=(1, 2)))
        payload = build_report_payload(list(incidents.values()), frames)
        group = next(group for group in payload['groups'] if group['code'] == 'REFERENCE_ABSENT')
        self.assertEqual(group['family'], 'references')
        self.assertEqual(group['field_severity'], 'warning')
        self.assertIn('chargement manuel', group['field_action'])
        self.assertIn('1 référence(s)', group['metric'])
        self.assertEqual(len(group['examples']), 1)
        sample = group['examples'][0]
        self.assertEqual(sample['barcode'], CIP)
        self.assertGreaterEqual(len(sample['context']), 5)
        self.assertIn('refus_2', sample['sources'])

    def test_hidden_software_details_and_example_navigation(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        frames, incidents = self.analyze(cycle_lines(1, missing=(2,)) + cycle_lines(2, missing=(2,)))
        item = incidents['REFERENCE_ABSENT']
        root = ctk.CTk()
        root.withdraw()
        received = []
        try:
            panel = DiagnosticPanel(root, list(incidents.values()), frames, on_incident_click=received.append)
            panel.pack()
            root.update()
            panel._show_details(item)
            text = panel._details.get('1.0', 'end')
            self.assertIn(CIP, text)
            self.assertIn('IdA:102', text)
            self.assertIn('Voir dans la trace', text)
            panel._open_reference_example(item, item.examples[1]['line'])
            self.assertEqual(received[0].first_line, item.examples[1]['line'])
            self.assertEqual(item.first_line, item.examples[0]['line'])
        finally:
            root.destroy()

    @unittest.skipUnless(os.environ.get('TRACE_ALPHA_REFERENCE_TRACE'), 'Trace terrain facultative non fournie')
    def test_local_trace(self):
        frames = parse_file(os.environ['TRACE_ALPHA_REFERENCE_TRACE'], min_dt=0.0)
        incidents = {item.code: item for item in build_diagnostics(frames, [])}
        stats = camera_report_stats(frames)
        self.assertEqual(stats['total_boxes'], 161)
        self.assertEqual((stats['unknown']['count'], stats['unknown']['total']), (80, 161))
        self.assertEqual(incidents['UNKNOWN'].count, 80)
        self.assertEqual(incidents['REFERENCE_ABSENT'].count, 17)
        self.assertEqual(incidents['REFERENCE_ABSENT'].metrics['references'], ['3400930307472'])
        self.assertEqual(sum(incidents['UNKNOWN'].metrics['unknown_buckets'].values()), 80)
        readers = {row['reader']: row for row in stats['reader_stats']}
        self.assertEqual((readers['CB1']['boxes'], readers['CB2']['boxes']), (161, 131))
        from Models.diagnostic import _camera_stats, _frame_line_states
        cycles = _camera_stats(_frame_line_states(frames))['cycles']
        self.assertEqual(sum(bool(cycle.creation and cycle.creation[1].isdigit()) for cycle in cycles), 64)
        payload = build_report_payload(list(incidents.values()), frames)
        absent = next(group for group in payload['groups'] if group['code'] == 'REFERENCE_ABSENT')
        self.assertEqual(len(absent['examples']), 10)
        self.assertEqual(absent['series'][0]['evidence_count'], 17)


if __name__ == '__main__':
    unittest.main()
