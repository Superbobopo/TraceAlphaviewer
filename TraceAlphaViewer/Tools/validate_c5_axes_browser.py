"""Verifie les nouveaux compteurs et blocages dans React, le secours HTML et le PDF."""
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import write_diagnostic_report, build_diagnostic_report_html
from Models.report_bridge import ReportBridge
from Tools.validate_measurement_report import samples
from Tools.validate_c5_blockage import ERROR, POSITIVE
from Tools.validate_c2_signal import frames_for


class BrowserTests(unittest.TestCase):
    def test_axis_totals_and_blockage_proofs_on_both_renderers(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        axes = samples(12, -7)
        for frame in axes[:10]:
            frame.boxes_on_T5[0].measured_t5_width_mm -= 4
        blocked = frames_for([(0, ERROR), (30, 'InitMachine: demande initialisation de T4 ...'),
                              (60, POSITIVE), (120, POSITIVE)])
        bridge = ReportBridge()
        try:
            with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temporary, sync_playwright() as pw:
                output = Path(temporary)
                browser = pw.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1080})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for name, frames, code in (('axes', axes, 'T4_LENGTH'), ('blocage', blocked, 'C5_SIGNAL_ANOMALY')):
                    incidents = build_diagnostics(frames, [])
                    report = write_diagnostic_report(incidents, output, frames, source_name='DONNEES FICTIVES')
                    fallback = output / f'{name}-secours.html'
                    fallback.write_text(build_diagnostic_report_html(incidents, frames), encoding='utf-8')
                    for index, url in enumerate((bridge.register(report), fallback.as_uri())):
                        page.goto(url)
                        group = page.locator(f'details[data-group^="{code}:"]')
                        text = group.locator(':scope > summary').inner_text()
                        self.assertIn('Critique', text)
                        if name == 'axes':
                            self.assertIn('12', page.locator('[data-axis=length] .axis-count').inner_text())
                            self.assertIn('12/12', re.sub(r'\s+', '', text))
                            self.assertEqual(page.locator('details[data-group^="GLOBAL:"]').count(), 0)
                        else:
                            self.assertIn('bloqué', text)
                            group.locator(':scope > summary').click()
                            group.locator('.incident-series > summary').first.click()
                            group.locator('.sample-technical > summary').first.click()
                            self.assertIn('code moteur positif sans reprise', group.inner_text())
                            button = group.locator('[data-navigate]').first
                            if index == 0:
                                received = []
                                def respond():
                                    target, done, result = bridge.commands.get(timeout=10)
                                    received.append(target)
                                    result.update(ok=True, line=target['line'])
                                    done.set()
                                thread = threading.Thread(target=respond)
                                thread.start()
                                button.click()
                                thread.join(10)
                                self.assertEqual(received[0]['code'], code)
                            else:
                                self.assertTrue(button.is_disabled())
                        with page.expect_download() as downloaded:
                            page.get_by_role('button', name='Exporter PDF').click()
                        pdf = output / f'{name}-{index}.pdf'
                        downloaded.value.save_as(pdf)
                        document = pdfium.PdfDocument(pdf)
                        content = '\n'.join(p.get_textpage().get_text_range() for p in document)
                        document.close()
                        self.assertIn('Longueur' if name == 'axes' else 'bloqué', content)
                        self.assertFalse(errors, errors)
                browser.close()
        finally:
            bridge.close()


if __name__ == '__main__':
    unittest.main()
