"""Verifie le rapport React, le secours hors ligne et le PDF sur donnees fictives."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Tools.validate_measurement_report import samples
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import write_diagnostic_report, build_diagnostic_report_html
from Models.report_bridge import ReportBridge


class BrowserTests(unittest.TestCase):
    def test_react_fallback_navigation_pagination_and_pdf(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        output = ROOT / 'build' / 'report-validation'
        output.mkdir(parents=True, exist_ok=True)
        frames = samples()
        incidents = build_diagnostics(frames, [])
        report = write_diagnostic_report(incidents, output, frames, source_name='DEMONSTRATION FICTIVE')
        fallback = output / 'secours.html'
        fallback.write_text(build_diagnostic_report_html(incidents, frames), encoding='utf-8')
        bridge = ReportBridge()
        try:
            url = bridge.register(report)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1080})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url)
                page.get_by_role('heading', name='Comprendre cette trace').wait_for()
                page.locator('details[data-group] > summary').first.click()
                button = page.locator('[data-navigate]').first
                page.wait_for_function("!document.querySelector('[data-navigate]').disabled")
                received = []
                def navigate():
                    target, done, result = bridge.commands.get(timeout=10)
                    received.append(target)
                    result.update(ok=True, line=target['line'])
                    done.set()
                thread = threading.Thread(target=navigate)
                thread.start()
                button.click()
                page.get_by_role('status').filter(has_text='positionné').wait_for()
                thread.join(5)
                self.assertEqual(received[0]['line'], 1)
                self.assertEqual(page.locator('.evidence .sample').count(), 3)
                page.get_by_role('button', name='Voir les 35 exemples').click()
                self.assertEqual(page.locator('.evidence .sample').count(), 25)
                page.get_by_role('button', name='Suivants').click()
                self.assertEqual(page.locator('.evidence .sample').count(), 10)
                page.get_by_role('searchbox').fill('INTROUVABLE')
                page.wait_for_timeout(300)
                self.assertEqual(page.locator('details[data-group]').count(), 0)
                page.get_by_role('searchbox').fill('DEMO-1')
                page.wait_for_timeout(300)
                self.assertEqual(page.locator('details[data-group]').count(), 1)
                with page.expect_download() as download:
                    page.get_by_role('button', name='Exporter PDF').click()
                pdf_path = output / 'rapport.pdf'
                download.value.save_as(pdf_path)
                document = pdfium.PdfDocument(pdf_path)
                contents = '\n'.join(p.get_textpage().get_text_range() for p in document)
                self.assertIn('35', contents)
                self.assertIn('5,0', contents)
                self.assertIn('calibrage', contents)
                document[0].render(scale=1.4).to_pil().save(output / 'pdf-page-1.png')
                document[len(document)-1].render(scale=1.4).to_pil().save(output / 'pdf-derniere-page.png')
                document.close()
                page.locator('[data-open=measurements] > summary').click()
                page.screenshot(path=str(output / 'rapport-react.png'), full_page=True)
                for width in (1920, 1280, 850):
                    page.set_viewport_size({'width':width,'height':1080})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                bridge.close()
                page.locator('details[data-group]').first.evaluate('(node) => node.open = true')
                page.locator('[data-navigate]').first.click()
                page.get_by_role('status').filter(has_text='fermée').wait_for()
                page.goto(report.as_uri())
                page.get_by_role('heading',name='Comprendre cette trace').wait_for()
                page.goto(fallback.as_uri())
                page.get_by_role('heading', name='Comprendre cette trace').wait_for()
                page.locator('details[data-group] > summary').first.click()
                self.assertTrue(page.locator('[data-navigate]').first.is_disabled())
                page.locator('[data-open=measurements] > summary').click()
                self.assertIn('35', page.locator('[data-open=measurements]').inner_text())
                self.assertFalse(errors, errors)
                browser.close()
        finally:
            bridge.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
