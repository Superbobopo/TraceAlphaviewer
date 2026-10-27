"""Valide le blocage logiciel T3/T4 sans deduire la presence physique d'une boite."""
from pathlib import Path
from dataclasses import replace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload
from Models.group_analysis import _combine_signal
from Models.priority_impact import prepare_impact
from Tools.validate_c2_signal import frames_for


ERROR = 'tT3/T4: ERREUR-TRSF-T3-T4 eT4:-47 C5:0 C6:0 pT3:-163mm pT4:272mm LgBtT4:100mm'
POSITIVE = ERROR.replace('eT4:-47', 'eT4:2')
DONE = 'tT3/T4: transfert T3->T4 terminé, longueur=123 mm, attend transfert vers T5 (idB=2826)'


def signal_rows(start=0):
    return [(start+i, f'tEA-T3: WAIT-COND C4:0 C5:{i%2} fgBfinT3:1 eT3:49 pT3:-163mm')
            for i in range(11)]


def incident(rows):
    return next((row for row in build_diagnostics(frames_for(rows), [])
                 if row.code == 'C5_SIGNAL_ANOMALY'), None)


class BlockageTests(unittest.TestCase):
    def test_refusal_before_or_after_instability(self):
        for rows in (signal_rows()+[(11, ERROR)], [(0, ERROR)]+signal_rows(1)):
            row = incident(rows)
            self.assertEqual(row.severity, 'error')
            self.assertEqual(row.metrics['blocked_transfer_count'], 1)
            self.assertEqual(row.metrics['refusal_count'], 1)
            self.assertEqual(row.metrics['suspect_cycle_count'], 0)
        row = incident(signal_rows()+[(200, ERROR)])
        self.assertEqual(row.metrics['blocked_transfer_count'], 0)
        self.assertEqual(row.severity, 'warning')

    def test_positive_code_initialization_and_arrival_do_not_resume(self):
        rows = [(0, ERROR), (30, 'InitMachine: demande initialisation de T4 ...'),
                (60, POSITIVE), (90, 'tEA-T3: le transfert (EA->T3) est terminé'),
                (120, POSITIVE), (121, DONE)]
        row = incident(rows)
        block = row.metrics['episodes'][0]
        self.assertEqual(row.severity, 'error')
        self.assertEqual(block['duration_seconds'], 120)
        self.assertTrue(block['recovered'])
        self.assertEqual(block['initialization_count'], 1)
        self.assertIn('code moteur positif sans reprise', block['sources'])
        self.assertEqual(prepare_impact([row])['cycles'], 1)
        payload = build_report_payload([row], frames_for(rows))
        group = next(g for g in payload['groups'] if g['code'] == row.code)
        self.assertEqual(group['field_severity'], 'error')
        self.assertIn('bloqué', group['metric'])
        self.assertTrue(group['examples'])

    def test_multi_day_single_episode_and_unknown_end(self):
        rows = [(i, ERROR) for i in range(0, 172801, 120)]
        row = incident(rows)
        self.assertEqual(row.metrics['blocked_transfer_count'], 1)
        self.assertEqual(row.metrics['refusal_count'], 1)
        self.assertEqual(row.metrics['blocked_duration_seconds'], 172800)
        self.assertFalse(row.metrics['episodes'][0]['recovered'])
        self.assertLessEqual(len(row.examples), 10)

    def test_initialization_commands_pair_with_requests(self):
        row = incident([(0, ERROR), (10, 'InitMachine: demande initialisation de T4 ...'),
                        (11, 'SendCde: envoi cde machine(1): T4I,255,25,50,0 --> Ok'),
                        (120, POSITIVE), (121, 'SendCde: envoi cde machine(1): T4I,255,25,50,0 --> Ok'),
                        (122, POSITIVE)])
        self.assertEqual(row.metrics['initialization_count'], 2)
        self.assertFalse(row.metrics['episodes'][0]['recovered'])

    def test_boundaries_do_not_bridge_unobserved_time(self):
        for boundary in ('version logiciel VBalpha: fictive',
                         'tT3/T4: WAIT-COND eT4:2 C5:0 C6:0'):
            rows = [(0, ERROR), (120, ERROR), (121, boundary), (122, ERROR), (242, ERROR)]
            self.assertEqual(incident(rows).metrics['blocked_transfer_count'], 2)
        row = incident([(0, ERROR), (120, ERROR), (300, ERROR), (420, ERROR)])
        self.assertEqual(row.metrics['blocked_duration_seconds'], 240)
        combined = _combine_signal([replace(row, metrics=dict(row.metrics, source_segment=index))
                                    for index in (0, 1)])[0]
        self.assertEqual(combined.metrics['blocked_transfer_count'], 4)
        self.assertEqual(combined.severity, 'error')
        self.assertEqual(prepare_impact([combined])['duration_seconds'], 480)

    def test_negative_cases_and_identity_provenance(self):
        self.assertIsNone(incident([(0, ERROR), (10, DONE)]))
        self.assertIsNone(incident([(0, POSITIVE)]))
        self.assertEqual(incident([(0, POSITIVE), (120, POSITIVE)]).severity, 'error')
        rows = [(0, 'tEA-T3: le transfert (EA->T3) est terminé'),
                (1, 'idCB2: --> Réf:CIP-FICTIF lot:L'), (2, 'idCB2: (Nboite=2826)'),
                (3, "tT3/T4: demande le transfert de T3->T4 C5:1 C6:0 'CIP-FICTIF' FICTIF"),
                (4, ERROR), (124, ERROR)]
        block = incident(rows).metrics['episodes'][0]
        self.assertEqual((block['id_b'], block['barcode']), (2826, 'CIP-FICTIF'))
        rows[3] = (3, "tT3/T4: demande le transfert de T3->T4 'AUTRE' FICTIF")
        self.assertEqual(incident(rows).metrics['episodes'][0]['id_b'], 0)

    def test_ejection_and_confirmed_product_name(self):
        rows = [(0, 'tEA-T3: Demande éjection REF-PROVISOIRE avec 50% 60ms'),
                (1, 'tEA-T3: le transfert (EA->T3) est terminé'),
                (2, 'Rech. infos existantes BdD pour CIP-FICTIF ...'),
                (3, '  --> PRODUIT FICTIF 76x27x123 23g'),
                (4, 'idCB2: --> Réf:CIP-FICTIF lot:L'), (5, 'idCB2: (Nboite=2826)'),
                (6, "tT3/T4: demande le transfert de T3->T4 'CIP-FICTIF' FICTIF"),
                (7, ERROR), (127, ERROR)]
        block = incident(rows).metrics['episodes'][0]
        self.assertEqual(block['name'], 'PRODUIT FICTIF')
        self.assertEqual(block['sources']['demande ejection EA'], 1)


if __name__ == '__main__':
    unittest.main()
