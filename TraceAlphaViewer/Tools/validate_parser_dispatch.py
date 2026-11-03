"""Compare le decodage selectif, les copies et le point fixe des references."""
from dataclasses import fields
import gc
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Models import reference_index
from Models.state import BoxInfo, MachineState
from Models.worker_gc import loading_collections
from Parser import trace_parser
from Parser.trace_source import canonical_lines


class LineDispatchTests(unittest.TestCase):
    def test_clock_base_reuse_preserves_timestamps_and_labels(self):
        stamps = [('28', '23', '59', '59', '0'), ('28', '23', '59', '59', '0'),
                  ('28', '23', '59', '59', '9'), ('29', '00', '00', '00', '0'),
                  ('29', '00', '00', '00', '10'), ('29', '00', '00', '01', '0'),
                  ('29', '00', '00', '01', '5'), ('01', '00', '00', '00', '0'),
                  ('01', '00', '00', '00', '0'), ('01', '00', '00', '00', '01'),
                  ('01', '00', '00', '00', '1'), ('01', '99', '99', '99', '1234')]
        expected = []
        first = trace_parser._ts(*stamps[0])
        previous = None
        rows = []
        for stamp in stamps:
            day, h, m, s, ds = stamp
            value = trace_parser._ts(*stamp)
            if value != previous:
                expected.append((value - first, f'{h}:{m}:{s}'))
                previous = value
            rows.append(f' {day}|{h}:{m}:{s}.{ds} T0: WAIT-COND eT0:2 C0:0\n')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fictive.old'
            path.write_text(''.join(rows), encoding='latin-1')
            frames = trace_parser.parse_file(str(path), min_dt=0.)
        self.assertEqual([(frame.timestamp, frame.timestamp_str) for frame in frames], expected)

    def test_every_rule_and_combined_lines(self):
        examples = [
            'CubeStop:Y', 'mvt CubeStop vers le HAUT (EA)',
            'CB1: ajout Hist_LectCB boite n1 1code(s) lu(s)',
            'T0: WAIT-COND eT0:2 C0:1', 'T1: WAIT-COND eT1:2',
            'T2: WAIT-COND eT2:2 C2:1 C3:0 C4:0',
            'tEA-T3: WAIT-COND C4:1 C5:0 fgBfinT3:0 eT3:2 pT3:-10mm',
            'tT3/T4: WAIT-COND eT4:2 C6:0 pT3:1mm pT4:2mm LgBtT4:10,5mm',
            'tT4*T5: WAIT-COND C6:1 fgBfinT4:0 pT4:2mm',
            'T5: WAIT-COND eT5=2 larg:20 C9:1 pT5:10 eT5useO:0 eT5useA:1',
            'largeur lue sur T5 < 2mm et C9=1',
            'sur T5: CIP FICTIF lot:LOT date x=942',
            "Création de la boite 'CIP' FICTIF x=942 (20x30x100) IdA:1",
            'supp. de T5 la boite Id:1 ref:CIP', '-suppression de la boite ID:1',
            'Suppr. la boite IdA:1',
            'MAJ (BUTEE-T5) boite Id:1 ref:CIP nvlle dim:20x30 X:942',
            "MAJ (APRES-MESURE-LARG) bt IdA:1 'CIP' nvlle lxH:20x30 [x100] X:942",
            'Déplace toutes les boites sur -10 mm', 'DeplBtSurT5.-10mm.RefCIP.idA1',
            'Rech. infos pour CIP', '--> FICTIF 20x30x100 40g',
            'idCB1: --> Réf:CIP lot:LOT', 'idCB2: (Nboite=1)',
            "idCB2: Identif. Ok 'CIP' (Nboite=1)",
            'transfert T3->T4 termine longueur=100 mm idB=1',
            "Demande le transfert (physique) T4 vers T5 'CIP'", 'AjoutBtT5.idA1.idB1',
            'longueur boite (BdD)=100 (T2T)=101 (T4C)=100 (T4T)=99 diffT4=1mm',
            'capteurC1=1', 'FlagPoubellePleine = faux', 'LzB:30', 'erreur',
        ]
        covered = set()
        samples = examples + [' / '.join(examples)]
        for original in list(samples):
            samples.extend((original.upper(), original.lower(), original.replace(' ', '\t'),
                            original.replace('i', 'İ').replace('s', 'ſ'),
                            'préfixe ' + original + ' suffixe', original[:len(original) // 2]))
        for text in samples:
            expected = {rule: match for rule, _ in trace_parser._LINE_RULES
                        if (match := rule.search(text))}
            decoded = trace_parser._line_matches(text)
            actual = {pattern: match for (pattern, _), match in zip(trace_parser._LINE_RULES, decoded)
                      if match is not None}
            covered.update(expected)
            with self.subTest(text=text):
                self.assertEqual(set(expected), set(actual))
                for rule, match in expected.items():
                    self.assertEqual((actual[rule].span(), actual[rule].groups()),
                                     (match.span(), match.groups()))
        self.assertEqual(covered, {rule for rule, _ in trace_parser._LINE_RULES})
        for name, (rule, _) in zip(trace_parser._LineMatches._fields, trace_parser._LINE_RULES):
            self.assertIs(getattr(trace_parser, '_' + name), rule)

    def test_compilation_preserves_integer_measurement_evidence(self):
        state = MachineState()
        trace_parser._update(state,
            "MAJ (APRES-MESURE-LARG) bt IdA:7 'CIP-FICTIF' nvlle lxH:60x37 [x106] X:6803",
            {}, 1)
        event = next(row for row in state.events if row.title.startswith('MAJ mesure T5'))
        self.assertEqual(event.detail, 'IdA:7 X:6803 60x37x106')

    def test_snapshot_fields_and_mutable_independence(self):
        box = BoxInfo(id_alpha=7, barcode='CIP', measured_t4_line=42)
        # Un nouveau champ mutable exige de revoir la copie des boites.
        self.assertTrue(all(isinstance(getattr(box, field.name), (str, int, float, bool, type(None)))
                            for field in fields(BoxInfo)))
        source = MachineState(box_in_EA=box, box_on_T3=box, box_on_T4=box,
                              boxes_on_T5=[box], raw_lines=[(1, 'texte', True)])
        copies = [source.deep_copy(), source.deep_copy()]
        self.assertEqual(source, copies[0])
        self.assertEqual(source, copies[1])
        copies[0].boxes_on_T5[0].barcode = 'MODIFIE'
        copies[0].box_in_EA.id_alpha = 9
        copies[0].raw_lines.append((2, 'nouveau', False))
        copies[0].events.append(None)
        self.assertEqual(source, copies[1])
        self.assertEqual(copies[0].box_on_T3.id_alpha, 7)
        self.assertEqual(copies[0].box_on_T4.id_alpha, 7)


class ReferenceFixedPointTests(unittest.TestCase):
    def compare(self, frames):
        optimized, exhaustive = reference_index.ReferenceCollector(), reference_index.ReferenceCollector()
        for frame in frames:
            exhaustive._repeat_records = None
            exhaustive.consume(frame)
            optimized.consume(frame)
            self.assertEqual(optimized.records, exhaustive.records)
            self.assertEqual(optimized.alias_to_key, exhaustive.alias_to_key)
            self.assertEqual(optimized.active_keys, exhaustive.active_keys)
        self.assertEqual(optimized.finish([]), exhaustive.finish([]))

    def test_collisions_reidentifications_departures_and_repeated_states(self):
        rng = random.Random(5012026)
        frames = []
        choices = [None, BoxInfo(), BoxInfo(barcode='CIP-A'), BoxInfo(barcode='CIP-B'),
                   BoxInfo(source_ref='ALPHA-INC-1'), BoxInfo(id_b=1, barcode='CIP-A'),
                   BoxInfo(id_b=2, barcode='CIP-A'), BoxInfo(id_alpha=1, id_b=1, barcode='CIP-A'),
                   BoxInfo(id_alpha=2, id_b=1, barcode='CIP-B'),
                   BoxInfo(id_alpha=1, barcode='CIP-B', source_ref='ALPHA-INC-1')]
        for index in range(120):
            boxes = rng.choices(choices, k=6)
            frame = MachineState(box_in_EA=boxes[0], box_on_T3=boxes[1], box_on_T4=boxes[2],
                                 boxes_on_T5=[box for box in boxes[3:] if box is not None])
            for repeat in range(5):
                snapshot = frame.deep_copy()
                snapshot.line_num = len(frames) + 1
                snapshot.timestamp_str = str(snapshot.line_num)
                frames.append(snapshot)
        self.compare(frames)

    def test_stable_aliases_stop_matching_and_keep_last_line(self):
        collector = reference_index.ReferenceCollector()
        with patch.object(reference_index, '_record_for_box', wraps=reference_index._record_for_box) as resolve:
            for line in range(1, 101):
                collector.consume(MachineState(line_num=line, timestamp_str=str(line),
                    boxes_on_T5=[BoxInfo(barcode='CIP-A'), BoxInfo(id_alpha=1, barcode='CIP-B')]))
            self.assertLessEqual(resolve.call_count, 4)
        self.assertEqual({record.last_line for record in collector.records.values()}, {100})
        self.assertEqual({record.last_time_str for record in collector.records.values()}, {'100'})


class SourcePositionTests(unittest.TestCase):
    def test_byte_positions_after_failed_and_successful_duplicate_searches(self):
        header = b'OUVERTURE DE LA TRACE le 24/10/2026\r\n'
        first = [header] + [f'24|08:00:0{i}.0 première série\r\n'.encode('latin-1') for i in range(3)]
        second = [header] + [f'24|09:00:0{i}.0 deuxième série\n'.encode('latin-1') for i in range(3)]
        rows = first + second + second + [b'24|10:00:00.0 fin sans retour']
        offsets, total = [], 0
        for row in rows:
            total += len(row)
            offsets.append(total)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fictive.old'
            path.write_bytes(b''.join(rows))
            metadata = {}
            actual = list(canonical_lines(path, metadata))
        kept = [*range(1, 9), 13]
        self.assertEqual([number for number, _, _ in actual], kept)
        self.assertEqual([position for _, _, position in actual], [offsets[number - 1] for number in kept])
        self.assertEqual(metadata['duplicate_ranges'],
                         [{'first_line': 9, 'last_line': 12, 'source_first_line': 5}])


class WorkerCollectionsTests(unittest.TestCase):
    def test_thresholds_are_restored_after_nested_calls_and_failure(self):
        thresholds, enabled = gc.get_threshold(), gc.isenabled()
        with self.assertRaisesRegex(RuntimeError, 'test'):
            with loading_collections():
                inside = gc.get_threshold()
                self.assertEqual(gc.isenabled(), enabled)
                with loading_collections():
                    self.assertEqual(gc.get_threshold(), inside)
                self.assertEqual(gc.get_threshold(), inside)
                raise RuntimeError('test')
        self.assertEqual(gc.get_threshold(), thresholds)
        self.assertEqual(gc.isenabled(), enabled)

    def test_disabled_collections_are_respected(self):
        enabled = gc.isenabled()
        thresholds = gc.get_threshold()
        try:
            gc.disable()
            with loading_collections():
                self.assertFalse(gc.isenabled())
                self.assertEqual(gc.get_threshold(), thresholds)
        finally:
            if enabled:
                gc.enable()


if __name__ == '__main__':
    unittest.main(verbosity=2)
