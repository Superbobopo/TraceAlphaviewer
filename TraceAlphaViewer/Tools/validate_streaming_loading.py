"""Compare les workers sur des traces fictives et leurs progressions reelles."""
from __future__ import annotations

import os
from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
import unittest


APP = Path(__file__).resolve().parents[1]
BASELINE = APP / '.trace_work/loading-baseline-20261026'


def _capture(source_tree, request_path, output_path):
    sys.path.insert(0, str(Path(source_tree).resolve()))
    from Models.frame_store import FrameStore
    from Models.loading_worker import run
    with Path(request_path).open('rb') as stream:
        request = pickle.load(stream)
    messages = []
    run(request, lambda kind, payload: messages.append((kind, payload)))
    if 'tkinter' in sys.modules or any(name.startswith('Views.') for name in sys.modules):
        raise AssertionError('Le worker ne doit importer ni Tk ni Views')
    entries = [payload for kind, payload in messages if kind == 'entry']
    counts = [payload for kind, payload in messages if kind == 'entry_done']
    if len(entries) != 1 or len(counts) != 1 or not any(kind == 'done' for kind, _ in messages):
        raise AssertionError('Resultat de chargement incomplet')
    entry = entries[0]
    items = {key: [item for kind, payload in messages if kind == key for item in payload]
             for key in ('events', 'diagnostics', 'references')}
    with FrameStore(entry['store']) as frames:
        artifacts = dict(items, frames=list(frames), counts=counts[0],
                         stored_events=frames.read_events(), measurements=frames.read_measurements(),
                         camera=frames.read_camera_report(), period=frames.trace_period,
                         metadata=frames.source_metadata, summary=frames.measurement_summary,
                         navigation={key: vars(value) if type(value).__name__ == 'LineIndex' else value
                                     for key, value in entry['navigation'].items()})
    with Path(output_path).open('wb') as stream:
        pickle.dump({'artifacts': artifacts,
                     'progress': [payload for kind, payload in messages if kind == 'progress']},
                    stream, protocol=pickle.HIGHEST_PROTOCOL)


def _row(index, text, day=24):
    hour, seconds = divmod(index, 3600)
    minute, second = divmod(seconds, 60)
    return f'  {day:02d}|{hour:02d}:{minute:02d}:{second:02d}.0 {text}\n'


def _trace(count, day=24):
    if not count:
        return ''
    prefix = [
        'CubeStop:N',
        'BOITE-LOAD',
        'CB1: ajout Hist_LectCB boite n1 1code(s) lu(s)',
        'idCB1: --> Réf:3400000000001 lot:LOT-FICTIF',
        'le transfert (EA->T3) est termine',
        "idCB2: Identif. sur le lecteur1 Ok '3400000000001' (Nboite=42)",
        'transfert T3->T4 termine longueur=100 mm idB=42',
        "Demande le transfert (physique) T4 vers T5 '3400000000001'",
        'la boite est rendu (physiquement) sur T5',
        'AjoutBtT5.idA7.idB42',
        "BdD: Création de la boite '3400000000001' PRODUIT FICTIF x=942 (20x30x100) IdA:7",
        'T2: WAIT-COND eT2:-88 C2:1 C3:0 C4:0',
    ]
    header = (f'OUVERTURE DE LA TRACE le {day:02d}/10/2026\n'
              'BASEALPHA_#2026.031.MDB BASEFIC1234FICTIVE.MDB\n')
    return header + ''.join(_row(index, prefix[index] if index < len(prefix)
                                else 'Message sans effet', day) for index in range(count))


class StreamingLoadingTests(unittest.TestCase):
    def setUp(self):
        (APP / '.trace_work').mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='validate-streaming-', dir=APP / '.trace_work')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sequence = 0

    def capture(self, source_tree, request):
        self.sequence += 1
        directory = self.root / f'capture-{self.sequence}'
        directory.mkdir()
        request = dict(request, session=str(directory / 'session'), job_id='validation')
        request_path, result_path = directory / 'request.pkl', directory / 'result.pkl'
        with request_path.open('wb') as stream:
            pickle.dump(request, stream, protocol=pickle.HIGHEST_PROTOCOL)
        environment = dict(os.environ, TRACE_ALPHA_FOLDER_ENGINE='python')
        # Les hooks d'autres validations ne doivent pas precharger les modules courants.
        environment.pop('PYTHONPATH', None)
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--capture',
                                 str(source_tree), str(request_path), str(result_path)],
                                cwd=APP.parent, env=environment, capture_output=True,
                                text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with result_path.open('rb') as stream:
            return pickle.load(stream)

    def assert_progress(self, result, mode, expected_sources):
        from Models.loading_progress import ProgressTracker
        progress = result['progress']
        self.assertTrue(progress)
        self.assertTrue(all(isinstance(payload, dict) for payload in progress))
        tracker = ProgressTracker(mode)
        values = [tracker.update(payload) for payload in progress]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(value < 1 for value in values))
        self.assertEqual(tracker.phase_state('read'), 'done')
        self.assertEqual(tracker.phase_state('diagnostic'), 'done')
        self.assertEqual(tracker.phase_state('references'), 'done')
        self.assertNotEqual(tracker.phase_state('raw'), 'done')
        self.assertFalse(any(row['phase'] == 'raw' and row.get('state') == 'done' for row in progress))
        self.assertEqual(set(tracker._segments), set(expected_sources))
        for source in expected_sources:
            for phase in ('read', 'diagnostic', 'references'):
                rows = [row for row in progress if row['phase'] == phase and row['segment'] == source]
                self.assertTrue(rows, (phase, source))
                fractions = [1 if row.get('state') == 'done' else row['done'] / row['total']
                             for row in rows if row.get('state') == 'done' or row.get('total')]
                self.assertEqual(fractions, sorted(fractions), (phase, source))

    def assert_reference(self, result, request):
        if not (BASELINE / 'Models/loading_worker.py').is_file():
            return
        expected = self.capture(BASELINE, request)['artifacts']
        # Seuls ces trois titres ont ete enrichis ; toutes les donnees restent comparees.
        from dataclasses import replace
        titles = {
            'T2 eT:-88 - Err: boite deja C4': 'T2 eT:-88 - Err: boite deja C4 (boite deja presente sur C4 avant transfert)',
            'T3 eT:-43 - Err: boite coincee': 'T3 eT:-43 - Err: boite coincee (passage de C4 vers T3 non libere)',
            'T4 eT:-17 - Err: index non degage': "T4 eT:-17 - Err: index non degage (C6 reste actif pendant l'initialisation de T4)",
        }
        expected['diagnostics'] = [replace(row, title=titles.get(row.title, row.title))
                                   for row in expected['diagnostics']]
        actual = result['artifacts']
        self.assertEqual(set(actual), set(expected))
        self.assertEqual(len(actual['frames']), len(expected['frames']))
        for index, (frame, old_frame) in enumerate(zip(actual['frames'], expected['frames'])):
            with self.subTest(frame=index):
                # La reference historique precede le suivi des fantomes T5.
                if not hasattr(old_frame, 't5_ghost_boxes'):
                    old_frame.t5_ghost_boxes = []
                self.assertEqual(frame, old_frame)
        for key in set(actual) - {'frames'}:
            with self.subTest(artifact=key):
                self.assertEqual(actual[key], expected[key])

    def test_file_empty_single_and_incomplete_blocks(self):
        for count in (0, 1, 503, 1003):
            with self.subTest(frames=count):
                path = self.root / f'fictive-{count}.old'
                path.write_text(_trace(count), encoding='latin-1')
                request = {'mode': 'file', 'path': str(path)}
                result = self.capture(APP, request)
                self.assertEqual(result['artifacts']['counts']['frames'], count)
                self.assert_progress(result, 'file', [str(path.resolve())])
                self.assert_reference(result, request)

    def test_folder_two_segments_and_parallel_detail(self):
        from Models.folder_catalog import catalog_folder
        directory = self.root / 'sources'
        directory.mkdir()
        for index in range(2):
            (directory / f'fictive-{index}.old').write_text(_trace(503, 24 + index), encoding='latin-1')
        catalog = catalog_folder(directory)
        self.assertEqual(len(catalog['groups']), 1)
        group = catalog['groups'][0]
        self.assertEqual(len(group['sources']), 2)
        request = {'mode': 'folder_group', 'path': str(directory), 'group': group}
        result = self.capture(APP, request)
        artifacts = result['artifacts']
        self.assertEqual(artifacts['counts']['frames'], 1006)
        self.assertEqual(len(artifacts['metadata']['segments']), 2)
        self.assertEqual(len(artifacts['references']), 2)
        self.assertNotEqual(artifacts['references'][0].key, artifacts['references'][1].key)
        self.assertEqual(artifacts['metadata']['segments'][1]['first_frame'], 503)
        self.assertEqual(artifacts['frames'][502].boxes_on_T5[0].id_alpha, 7)
        self.assertEqual(artifacts['frames'][503].boxes_on_T5, [])
        self.assert_progress(result, 'folder_group',
                             [str(Path(source['filepath']).resolve()) for source in group['sources']])
        self.assert_reference(result, request)


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--capture':
        _capture(*sys.argv[2:])
    else:
        sys.path.insert(0, str(APP))
        unittest.main(verbosity=2)
