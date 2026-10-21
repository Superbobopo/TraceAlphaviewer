"""Distingue les exclusions Alpha des references absentes et des echecs camera."""
from pathlib import Path
import os
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.diagnostic import build_diagnostics, camera_report_stats
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Models.report_bridge import ReportBridge
from Tools.validate_reference_absent import CIP, cycle_lines, frames_for, refusal

CODE = 'REFERENCE_NON_ALPHATISABLE'


def non_alphatisable_rows(index, readers=(2,), *, cip=CIP, recovered=False):
    rows = cycle_lines(index, missing=readers, recovered=recovered)
    for reader in readers:
        replacement = (f"idCB{reader}: la réf. {CIP} n'est pas dans les tables, elle est donc 'A DETRUIRE' "
                       f"(réf. non Alphatisable (user) '{CIP}' PRODUIT FICTIF)")
        rows = [replacement if row == refusal(reader) else row for row in rows]
    return [row.replace(CIP, cip) for row in rows]


class NonAlphatisableTests(unittest.TestCase):
    def analyze(self, rows):
        frames = frames_for(rows)
        return frames, {item.code: item for item in build_diagnostics(frames, [])}

    def test_cb1_cb2_both_and_final_unknown_exclusion(self):
        for readers in ((1,), (2,), (1, 2)):
            with self.subTest(readers=readers):
                frames, incidents = self.analyze(non_alphatisable_rows(1, readers))
                item = incidents[CODE]
                self.assertEqual(item.count, 1)
                self.assertEqual(item.metrics['refusal_count'], len(readers))
                self.assertEqual(item.metrics['references'], [CIP])
                self.assertEqual(item.examples[0]['readers'], [f'CB{i}' for i in readers])
                self.assertIn('(user)', item.examples[0]['detail'])
                self.assertIn('PRODUIT FICTIF', item.examples[0]['detail'])
                self.assertNotIn('REFERENCE_ABSENT', incidents)
                self.assertNotIn('UNKNOWN', incidents)
                stats = camera_report_stats(frames)
                self.assertEqual(stats['total_boxes'], 1)
                self.assertEqual(sum(stats['unknown']['buckets'].values()), 0)

    def test_several_boxes_and_cips_keep_physical_identities(self):
        frames, incidents = self.analyze(non_alphatisable_rows(1) + non_alphatisable_rows(2)
            + non_alphatisable_rows(3, cip='3400000000002') + cycle_lines(4, missing=(2,))
            + cycle_lines(5) + cycle_lines(6, known=True, direct=True))
        self.assertEqual(incidents[CODE].count, 3)
        self.assertEqual(incidents[CODE].metrics['reference_count'], 2)
        self.assertEqual(incidents['REFERENCE_ABSENT'].count, 1)
        self.assertEqual(incidents['UNKNOWN'].count, 1)
        stats = camera_report_stats(frames)
        self.assertEqual(stats['total_boxes'], 6)
        self.assertEqual(stats['unknown']['count'], 1)
        self.assertEqual(sum(stats['unknown']['buckets'].values()), 1)
        self.assertEqual({sample['box'] for sample in incidents[CODE].examples},
                         {'idB:1 · IdA:101', 'idB:2 · IdA:102', 'idB:3 · IdA:103'})

    def test_truncated_trace_and_historical_rejection(self):
        refusal_row = next(row for row in non_alphatisable_rows(1) if 'non Alphatisable' in row)
        _, incidents = self.analyze([refusal_row])
        self.assertEqual(incidents[CODE].count, 1)
        self.assertEqual(incidents[CODE].examples[0]['technical_references'], [])
        self.assertEqual(incidents[CODE].examples[0]['barcode'], CIP)
        _, incidents = self.analyze(non_alphatisable_rows(1, recovered=True) + cycle_lines(2, known=True))
        self.assertEqual(incidents[CODE].count, 1)
        self.assertNotIn('UNKNOWN', incidents)

    def test_no_false_positive_for_reading_dimensions_or_marker_alone(self):
        for rows in (cycle_lines(1, known=True), cycle_lines(1, recovered=True),
                     cycle_lines(1), ['Commentaire : réf. non Alphatisable (user)'],
                     [row.replace(CIP, CIP+'[Dinh]') for row in cycle_lines(1, known=True)]):
            with self.subTest(rows=rows[:1]):
                _, incidents = self.analyze(rows)
                self.assertNotIn(CODE, incidents)

    def test_camera_threshold_uses_only_decode_unknowns(self):
        rows = [row for index in range(1, 101) for row in
                (non_alphatisable_rows(index) if index == 8 else
                 cycle_lines(index, known=index > 8, direct=index > 8))]
        frames, incidents = self.analyze(rows)
        self.assertEqual(incidents[CODE].count, 1)
        self.assertNotIn('UNKNOWN', incidents)
        self.assertEqual(camera_report_stats(frames)['unknown']['count'], 7)
        self.assertFalse(camera_report_stats(frames)['unknown']['alert'])

    def test_report_keeps_original_cip_reason_and_first_ten_proofs(self):
        frames, incidents = self.analyze([row for i in range(1, 13) for row in non_alphatisable_rows(i)])
        payload = build_report_payload(list(incidents.values()), frames)
        group = next(group for group in payload['groups'] if group['code'] == CODE)
        self.assertEqual(group['field_severity'], 'warning')
        self.assertEqual(group['family'], 'references')
        self.assertEqual(group['occurrence_count'], 12)
        self.assertEqual(group['series'][0]['evidence_count'], 12)
        self.assertEqual(len(group['examples']), 10)
        self.assertNotIn('chargement manuel', str(group))
        sample = group['examples'][0]
        self.assertEqual(sample['barcode'], CIP)
        self.assertIn('(user)', sample['detail'])
        self.assertIn('creation', sample['sources'])
        self.assertTrue(any('non Alphatisable' in row['text'] for row in sample['context']))

    def test_software_card_and_example_navigation(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        frames, incidents = self.analyze(non_alphatisable_rows(1) + non_alphatisable_rows(2))
        root = ctk.CTk()
        root.withdraw()
        received = []
        try:
            panel = DiagnosticPanel(root, list(incidents.values()), frames, on_incident_click=received.append)
            panel.pack()
            root.update()
            panel._show_details(incidents[CODE])
            content = panel._details.get('1.0', 'end')
            self.assertIn('Références non alphatisables', content)
            self.assertIn(CIP, content)
            self.assertIn('(user)', content)
            self.assertNotIn('chargement manuel', content)
            panel._open_reference_example(incidents[CODE], incidents[CODE].examples[1]['line'])
            self.assertEqual(received[0].first_line, incidents[CODE].examples[1]['line'])
        finally:
            root.destroy()

    def test_react_fallback_navigation_pdf_and_sidebar(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        frames, incidents = self.analyze(cycle_lines(1) + non_alphatisable_rows(2, (1, 2))
                                         + cycle_lines(3, missing=(2,)))
        output = ROOT / 'build' / 'non-alphatisable-validation'
        output.mkdir(parents=True, exist_ok=True)
        report = write_diagnostic_report(list(incidents.values()), output, frames, 'REFERENCES FICTIVES')
        fallback = output / 'secours.html'
        fallback.write_text(build_diagnostic_report_html(list(incidents.values()), frames), encoding='utf-8')
        bridge = ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for url in (bridge.register(report), fallback.as_uri()):
                    local = url.startswith('http:')
                    page.goto(url)
                    if local:
                        page.get_by_role('status').filter(has_text='Liaison avec').wait_for()
                    self.assertIn('1 / 3', page.locator('.unknown-counter').inner_text())
                    self.assertEqual(page.locator('.camera-sidebar .camera-row').count(), 6)
                    page.locator('[data-family]').select_option('references')
                    self.assertEqual(page.locator('details[data-group]').count(), 2)
                    card = page.locator(f'[data-group^="{CODE}:"]')
                    card.locator(':scope > summary').click()
                    card.locator('.incident-series > summary').click()
                    self.assertIn('(user)', card.inner_text())
                    self.assertIn('PRODUIT FICTIF', card.inner_text())
                    self.assertIn('ALPHA-DET-B2', card.inner_text())
                    self.assertNotIn('chargement manuel', card.inner_text())
                    sample = card.locator('.evidence .sample').first
                    sample.locator('details > summary').click()
                    self.assertIn('refus_2', sample.inner_text())
                    if local:
                        received = []
                        def navigate():
                            target, done, result = bridge.commands.get(timeout=10)
                            received.append(target)
                            result.update(ok=True, line=target['line'])
                            done.set()
                        thread = threading.Thread(target=navigate)
                        thread.start()
                        sample.locator('[data-navigate]').click()
                        page.get_by_role('status').filter(has_text='positionné').wait_for()
                        thread.join(10)
                        self.assertEqual(received[0]['line'], incidents[CODE].first_line)
                    else:
                        self.assertTrue(sample.locator('[data-navigate]').is_disabled())
                    for width in (1440, 390):
                        page.set_viewport_size({'width': width, 'height': 1080})
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    card.screenshot(path=str(output / 'carte-mobile.png'))
                    with page.expect_download() as download:
                        page.get_by_role('button', name='Exporter PDF').click()
                    pdf = output / 'non-alphatisable.pdf'
                    download.value.save_as(pdf)
                    document = pdfium.PdfDocument(pdf)
                    content = ' '.join(' '.join(p.get_textpage().get_text_range() for p in document).split())
                    for text in ('Références non alphatisables', CIP, 'PRODUIT FICTIF', '(user)', 'refus_2', 'IdA:102'):
                        self.assertIn(text, content)
                    document.close()
                self.assertFalse(errors, errors)
                browser.close()
        finally:
            bridge.close()

    @unittest.skipUnless(os.environ.get('TRACE_ALPHA_NON_ALPHATISABLE_TRACE'), 'Trace terrain facultative non fournie')
    def test_current_local_trace(self):
        from Parser.trace_parser import parse_file
        from Models.folder_report import _collect_events
        frames = parse_file(os.environ['TRACE_ALPHA_NON_ALPHATISABLE_TRACE'], min_dt=0)
        incidents = {item.code: item for item in build_diagnostics(frames, _collect_events(frames))}
        item = incidents[CODE]
        self.assertEqual(item.count, 1)
        self.assertEqual(item.metrics['references'], ['3400934375361'])
        self.assertEqual(item.examples[0]['box'], 'idB:74 · IdA:536422')
        sources = item.examples[0]['sources']
        with Path(os.environ['TRACE_ALPHA_NON_ALPHATISABLE_TRACE']).open(encoding='latin-1') as trace:
            proofs = {line: text for line, text in enumerate(trace, 1) if line in set(sources.values())}
        self.assertIn('non Alphatisable (user)', proofs[sources['refus_1']])
        self.assertIn('3400934375361', proofs[sources['refus_1']])
        self.assertIn('IdA:536422', proofs[sources['creation']])
        stats = camera_report_stats(frames)
        self.assertEqual((stats['unknown']['count'], stats['total_boxes']), (35, 470))
        self.assertEqual(incidents['REFERENCE_ABSENT'].count, 2)
        self.assertEqual(incidents['UNKNOWN'].count, 35)


if __name__ == '__main__':
    unittest.main(verbosity=2)
