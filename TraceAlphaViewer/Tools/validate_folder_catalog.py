"""Verifie le catalogue Python et l'absence de dependance native par defaut."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.folder_catalog import catalog_folder, validate_source
from Tools.validate_alpha_folder_ui import fixture


class CatalogTests(unittest.TestCase):
    def test_identity_copies_overlap_and_changed_source(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temporary:
            path = Path(temporary)
            fixture(path)
            shutil.copyfile(path / 'alpha31-a.old', path / 'copie.old')
            result = catalog_folder(path)
            self.assertEqual(len(result['groups']), 2)
            group = next(row for row in result['groups'] if row['identity']['alpha_number'] == '031')
            self.assertEqual(len(group['sources']), 2)
            self.assertEqual(len(group['duplicates']), 1)
            source = group['sources'][0]
            validate_source(source)
            original = Path(source['filepath'])
            original.write_bytes(original.read_bytes().replace(b'100 mn', b'101 mn'))
            with self.assertRaises(OSError):
                validate_source(source)
            result = catalog_folder(path)
            self.assertEqual(len(result['groups']), 4)
            self.assertEqual(sum(row['status'] == 'verify' for row in result['groups']), 2)

    def test_unknown_conflict_and_year_rollover(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temporary:
            path = Path(temporary)
            fixture(path)
            original = path / 'alpha31-a.old'
            data = original.read_bytes()
            original.write_bytes(data + b'01|09:00:09.0 C:\\APOTEKA\\BASEALPHA_#2025.032.MDB\n')
            (path / 'inconnu.old').write_bytes(b'01|09:00:00.0 T2: INIT\n')
            (path / 'annee.old').write_bytes(
                b'31|23:59:59.0 OUVERTURE DE LA TRACE le 31/12/2025\n'
                b'31|23:59:59.1 C:\\BASEALPHA2_#0061.MDB C:\\BASEFICTEST.MDB\n'
                b'L01|00:00:01.0 T2: INIT\n')
            groups = catalog_folder(path)['groups']
            self.assertEqual(sum(row['status'] == 'verify' for row in groups), 2)
            year = next(row for row in groups if row.get('identity') and row['identity']['alpha_number'] == '0061')
            self.assertTrue(year['end'].startswith('2026-01-01'))

    def test_default_catalog_never_launches_native_engine(self):
        from Models.loading_worker import run
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temporary:
            path = Path(temporary)
            fixture(path)
            messages = []
            with patch.dict('os.environ', {'TRACE_ALPHA_FOLDER_ENGINE': 'python'}), patch(
                    'Models.native_folder.run_native', side_effect=AssertionError('Rust appele par defaut')):
                run({'mode': 'folder_catalog', 'path': str(path), 'session': str(path)},
                    lambda kind, payload: messages.append((kind, payload)))
            self.assertEqual(messages[-1][0], 'done')
            self.assertEqual(len(next(value for kind, value in messages if kind == 'catalog')['groups']), 2)


if __name__ == '__main__':
    unittest.main()
