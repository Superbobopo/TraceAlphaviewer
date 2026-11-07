"""Vérifie la copie depuis le rapport et son fichier autonome, sans toucher au presse-papiers."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Models.diagnostic_report import write_diagnostic_report
from Models.report_bridge import ReportBridge
from Models.report_clipboard import report_filename


class ReportClipboardTests(unittest.TestCase):
    def test_filename(self):
        payload = {'source': {'name': 'Trace client.old', 'identity': {'pharmacy': 'Pharmacie des Écoles'}},
                   'generated_at': '06/11/2026 12:20:28'}
        self.assertEqual(report_filename(payload), 'Rapport_Trace client_Pharmacie des Écoles_2026-11-06_12-20-28.html')
        payload['source']['name'] = '../Trace:client.old'
        payload['source']['identity']['pharmacy'] = 'Pharmacie / test*'
        name = report_filename(payload)
        self.assertEqual(Path(name).name, name)
        self.assertFalse(any(char in name for char in '<>:"/\\|?*'))

    def test_copy_and_offline_report(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as directory:
            report = write_diagnostic_report([], Path(directory))
            bridge = ReportBridge()
            try:
                url = bridge.register(report)
                endpoint = url.rsplit('/', 1)[0] + '/copy-report'
                with patch('Models.report_clipboard.copy_report_file') as copy:
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(endpoint, method='POST', headers={'Origin': 'http://example.invalid'}))
                    self.assertEqual(error.exception.code, 403)
                    copy.assert_not_called()
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(channel='msedge', headless=True)
                        page = browser.new_page()
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(url)
                        page.wait_for_function("document.querySelector('#report,[data-connected=true]')?.dataset.connected === 'true' || document.querySelector('[data-connected=true]')")
                        button = page.get_by_role('button', name='Copier le rapport web comme fichier')
                        button.focus()
                        page.keyboard.press('Enter')
                        page.get_by_role('status').filter(has_text='Rapport web copié').wait_for()
                        copy.assert_called_once()
                        standalone = copy.call_args.args[0]
                        self.assertTrue(standalone.is_file())
                        isolated = Path(directory) / 'client' / standalone.name
                        isolated.parent.mkdir()
                        isolated.write_bytes(standalone.read_bytes())
                        bridge.close()
                        page.goto(isolated.as_uri())
                        page.get_by_role('heading', name='Rapport d’analyse Alpha').wait_for()
                        page.get_by_role('button', name='Copier le rapport web comme fichier').click()
                        page.get_by_role('status').filter(has_text='viewer actif').wait_for()
                        self.assertEqual(page.locator('script[src],link[rel=stylesheet]').count(), 0)
                        self.assertFalse(errors, errors)
                        browser.close()
            finally:
                bridge.close()


if __name__ == '__main__':
    unittest.main()
