"""Verifie le rangement des rapports et le transfert sans perte des archives."""
from pathlib import Path
from datetime import datetime
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Models.report_storage import pharmacy_directory, UNKNOWN_PHARMACY, file_digest, retain_prepared_report
from Models.diagnostic_report import write_diagnostic_report, report_files_available
from Tools.migrate_reports import migrate, repair_missing_assets


class StorageTests(unittest.TestCase):
    def test_prepared_report_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary, permanent = Path(directory)/'session', Path(directory)/'reports'
            report = write_diagnostic_report([], output_dir=temporary, frames=[])
            original = report.read_bytes()
            self.assertFalse(permanent.exists())
            retained = retain_prepared_report(report, permanent)
            self.assertTrue(report_files_available(retained))
            self.assertEqual(retained.read_bytes(), original)
            self.assertEqual(retain_prepared_report(report, permanent), retained)
            retained.write_text('conflit', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                retain_prepared_report(report, permanent)
            self.assertEqual(report.read_bytes(), original)

    def test_default_pharmacy_dates_and_explicit_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {'source': {'identity': {'pharmacy': 'Pharmacie fictive'}}, 'groups': []}
            with patch('Models.diagnostic_report.reports_dir', return_value=root), \
                 patch('Models.diagnostic_report.build_report_payload', return_value=payload), \
                 patch('Models.diagnostic_report.datetime') as clock:
                clock.now.return_value = datetime(2026, 10, 26, 17, 0, 0)
                one = write_diagnostic_report([])
                two = write_diagnostic_report([])
                explicit = write_diagnostic_report([], output_dir=root/'test')
            self.assertEqual(one.parent.name, 'Pharmacie fictive')
            self.assertNotEqual(one, two)
            self.assertRegex(one.name, r'diagnostic_report_\d{4}-\d{2}-\d{2}_')
            self.assertTrue(report_files_available(one))
            self.assertEqual(explicit.parent, root/'test')
            self.assertEqual(pharmacy_directory(root, {}).name, UNKNOWN_PHARMACY)
            for name in ('../autre', 'CON', 'A/B', 'A\\B'):
                destination = pharmacy_directory(root, {'source': {'identity': {'pharmacy': name}}})
                self.assertEqual(destination.parent, root.resolve())
            self.assertNotEqual(pharmacy_directory(root, {'source': {'identity': {'pharmacy': 'A/B'}}}),
                                pharmacy_directory(root, {'source': {'identity': {'pharmacy': 'A\\B'}}}))

    def test_migration_preserves_files_resources_and_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            source, root = Path(directory)/'ancien', Path(directory)/'Alpha reports'
            source.mkdir()
            for number, pharmacy in ((1, 'Fictive'), (2, 'Fictive'), (3, None)):
                html = source/f'diagnostic_report_20260101_{number}.html'
                html.write_text('<html>FICTIF<script src="./_next/app.js"></script></html>', encoding='utf-8')
                data = html.with_name(html.name.replace('diagnostic_report_', 'report_data_')).with_suffix('.json')
                data.write_text(json.dumps({'source': {'identity': {'pharmacy': pharmacy}}}), encoding='utf-8')
                html.with_suffix('.manifest.json').write_text(json.dumps([html.name, data.name, '_next/app.js']), encoding='utf-8')
            (source/'_next').mkdir()
            (source/'_next/app.js').write_text('/* FICTIF */', encoding='utf-8')
            (source/'diagnostic_report_ancien.html').write_text('<html>ARCHIVE FICTIVE</html>', encoding='utf-8')
            hashes = {p.name: file_digest(p) for p in source.glob('*') if p.is_file()}
            result = migrate(source, root)
            self.assertEqual(result['reports'], 4)
            self.assertFalse(source.exists())
            self.assertEqual(len(list((root/'Fictive').glob('*.html'))), 2)
            self.assertEqual(len(list((root/UNKNOWN_PHARMACY).glob('*.html'))), 2)
            for path in root.rglob('*'):
                if path.is_file() and path.name in hashes:
                    self.assertEqual(file_digest(path), hashes[path.name])
            self.assertTrue(report_files_available(next((root/'Fictive').glob('*.html'))))
            self.assertEqual(migrate(source, root)['reports'], 0)
            with self.assertRaises(ValueError):
                migrate(root, root/'interdit')

    def test_missing_assets_repair_preserves_original_and_payload(self):
        from Models.diagnostic_report import build_report_payload
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'diagnostic_report_ancien.html'
            path.write_text('<html><script src="./_next/absent.js"></script></html>', encoding='utf-8')
            original = path.read_bytes()
            data = root/'report_data_ancien.json'
            payload = build_report_payload([], [])
            data.write_text(json.dumps(payload), encoding='utf-8')
            digest = file_digest(data)
            self.assertEqual(repair_missing_assets(root), 1)
            self.assertEqual(path.with_suffix('.html.original').read_bytes(), original)
            self.assertEqual(file_digest(data), digest)
            self.assertTrue(report_files_available(path))
            self.assertEqual(repair_missing_assets(root), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
