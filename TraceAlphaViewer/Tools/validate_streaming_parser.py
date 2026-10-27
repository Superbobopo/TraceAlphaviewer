"""Verifie les snapshots du parser progressif et leur equivalence locale."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import weakref

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from Parser import trace_parser


def _row(tick: int, text: str, day: int = 24) -> str:
    seconds, fraction = divmod(tick, 10)
    hour, seconds = divmod(seconds, 3600)
    minute, second = divmod(seconds, 60)
    return f'  {day:02d}|{hour:02d}:{minute:02d}:{second:02d}.{fraction} {text}\n'


def _fingerprint(frame) -> str:
    data = json.dumps(asdict(frame), sort_keys=True, ensure_ascii=True).encode('ascii')
    return hashlib.sha256(data).hexdigest()


def _load_baseline(path: Path):
    spec = importlib.util.spec_from_file_location('_streaming_parser_baseline', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASELINE = None


class StreamingParserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'fictive.old'

    def write(self, text: str):
        self.path.write_bytes(text.encode('latin-1'))

    def compare(self, text: str, min_dt: float = 0.0):
        self.write(text)
        metadata = {}
        progress = []
        frames = list(trace_parser.iter_frames(str(self.path),
                      lambda done, total: progress.append((done, total)), min_dt, metadata))
        if BASELINE is not None:
            old_metadata = {}
            old_progress = []
            expected = BASELINE.parse_file(str(self.path),
                         lambda done, total: old_progress.append((done, total)), min_dt, old_metadata)
            self.assertEqual(len(frames), len(expected))
            for index, (actual, previous) in enumerate(zip(frames, expected)):
                with self.subTest(frame=index):
                    if _fingerprint(actual) != _fingerprint(previous):
                        self.assertEqual(asdict(actual), asdict(previous))
            self.assertEqual(metadata, old_metadata)
            self.assertEqual(progress, old_progress)
        self.assertEqual([asdict(f) for f in trace_parser.parse_file(str(self.path), min_dt=min_dt)],
                         [asdict(f) for f in frames])
        self.assertEqual(progress[-1], (self.path.stat().st_size, self.path.stat().st_size))
        return frames, metadata

    def test_empty_single_and_final_frame(self):
        frames, _ = self.compare('Entete sans horodatage\nLigne incomplete 24|\n')
        self.assertEqual(frames, [])
        frames, _ = self.compare(_row(0, 'CubeStop:Y'))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[-1].cubestop_present, 1)
        frames, _ = self.compare(_row(0, 'CubeStop:Y') + _row(1, 'Message final'))
        self.assertEqual(frames[-1].raw_lines, [(2, 'Message final', False)])

    def test_more_than_two_complete_blocks(self):
        frames, _ = self.compare(''.join(_row(i, 'Message sans effet') for i in range(1003)))
        self.assertEqual(len(frames), 1003)
        self.assertEqual(frames[-1].line_num, 1003)

    def test_same_timestamp_and_minimum_interval(self):
        source = (_row(0, 'Message initial') + _row(0, 'CubeStop:Y') +
                  _row(0, 'Deuxieme message') +
                  ''.join(_row(i, 'Message sans effet') for i in range(1, 36)))
        dense, _ = self.compare(source, 0.0)
        sparse, _ = self.compare(source, 2.0)
        self.assertEqual(len(dense), 36)
        self.assertEqual(len(dense[0].raw_lines), 3)
        self.assertEqual([f.timestamp for f in sparse], [0.0, 2.0, 3.5])

    def test_date_change_interruptions_and_restart(self):
        source = (_row(863999, 'CubeStop:Y', 31) + _row(0, 'CubeStop:Y', 1) +
                  _row(6000, 'version logiciel VBalpha: 1.0', 1) +
                  _row(6001, 'T2: WAIT-COND eT2:2 C2:1 C3:0 C4:0', 1))
        frames, _ = self.compare(source)
        self.assertEqual([frame.line_num for frame in frames], [1, 2, 3, 4])
        self.assertEqual(frames[-1].C2, 1)

    def test_exact_copied_section_preserves_source_lines(self):
        section = ('OUVERTURE DE LA TRACE le 24/10/2026\n' +
                   _row(0, 'CubeStop:Y') + _row(1, 'Message sans effet') +
                   _row(2, 'Message sans effet'))
        frames, metadata = self.compare(section + section + _row(3, 'Derniere ligne'))
        self.assertEqual(metadata['duplicate_ranges'],
                         [{'first_line': 5, 'last_line': 8, 'source_first_line': 1}])
        self.assertEqual([frame.line_num for frame in frames], [2, 3, 4, 9])

    def test_identity_transfers_and_independent_snapshots(self):
        texts = [
            'BOITE-LOAD',
            'idCB1: --> Ref:ALPHA-INC-001 lot:LOT',
            'le transfert (EA->T3) est termine',
            "idCB2: Identif. sur le lecteur1 Ok '3400000000001' (Nboite=42)",
            'transfert T3->T4 termine longueur=100 mm idB=42',
            "Demande le transfert (physique) T4 vers T5 '3400000000001'",
            'la boite est rendu (physiquement) sur T5',
            'AjoutBtT5.idA7.idB42',
            "BdD: Creation de la boite '3400000000001' FICTIF x=942 (20x30x100) IdA:7",
            'MAJ (BUTEE-T5) boite Id:7 ref:3400000000001 nvlle dim:20x100 X:900',
        ]
        self.write(''.join(_row(i, text) for i, text in enumerate(texts)))
        stream = trace_parser.iter_frames(str(self.path), min_dt=0.0)
        previous = []
        for frame in stream:
            for snapshot, digest in previous:
                self.assertEqual(_fingerprint(snapshot), digest)
            previous.append((frame, _fingerprint(frame)))
        frames, _ = self.compare(''.join(_row(i, text) for i, text in enumerate(texts)))
        self.assertEqual(frames[3].box_on_T3.id_b, 42)
        self.assertEqual(frames[-1].boxes_on_T5[0].id_alpha, 7)
        self.assertEqual(frames[2].box_on_T3.barcode, 'ALPHA-INC-001')
        self.assertEqual(frames[3].box_on_T3.source_ref, 'ALPHA-INC-001')
        self.assertNotEqual(frames[-1].boxes_on_T5[0].x_pos, frames[-2].boxes_on_T5[0].x_pos)

    def test_progress_bytes_and_repeated_keyword_cache(self):
        text = ''.join(_row(i, 'Message sans effet ' + ('x' * 1024)) for i in range(2100))
        frames, _ = self.compare(text)
        self.assertTrue(all(not frame.raw_lines[0][2] for frame in frames))
        frames, _ = self.compare(''.join(_row(i, f'Autre texte {i}') for i in range(2100)) +
                                 _row(2100, 'CubeStop:Y') + _row(2101, 'CubeStop:Y'))
        self.assertEqual(frames[-1].cubestop_present, 1)

    def test_stream_does_not_retain_consumed_snapshots(self):
        self.write(''.join(_row(i, 'Message sans effet') for i in range(1100)))
        stream = trace_parser.iter_frames(str(self.path), min_dt=0.0)
        snapshot = next(stream)
        consumed = weakref.ref(snapshot)
        del snapshot
        for _ in range(1000):
            next(stream)
        gc.collect()
        self.assertIsNone(consumed())
        stream.close()

    def test_close_generator_closes_source(self):
        self.write(''.join(_row(i, 'Message sans effet') for i in range(3)))
        original = trace_parser.canonical_lines
        closed = []

        def tracked(*args, **kwargs):
            try:
                yield from original(*args, **kwargs)
            finally:
                closed.append(True)

        with patch.object(trace_parser, 'canonical_lines', tracked):
            stream = trace_parser.iter_frames(str(self.path), min_dt=0.0)
            next(stream)
            self.assertEqual(closed, [])
            stream.close()
        self.assertEqual(closed, [True])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-parser', type=Path,
                        default=APP / '.trace_work/loading-baseline-20261026/Parser/trace_parser.py')
    options, remaining = parser.parse_known_args()
    if options.baseline_parser.is_file():
        BASELINE = _load_baseline(options.baseline_parser)
        print(f'Comparaison avec le parser de reference : {options.baseline_parser}')
    else:
        print('Reference locale absente : verification des invariants fictifs uniquement.')
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
