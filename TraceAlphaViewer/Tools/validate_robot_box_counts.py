"""Controle les boites evacuees, les confirmations robot et leurs preuves."""
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.robot_drain import analyze_robot_boxes, drain_box_text
from Models.state import MachineState
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload

REQUEST = 'OMEGA:T5-DemVidageComplet'
START = 'T5v: Une demande de vidage complet de T5 est demandee ...'
CLEAR = 'Suppression de toutes les boites/goul. en attente sur le tampon: X99 ...'
END = 'envoi en UDP la liste des boites valides sur T5.  0 boite(s)'
ORIGIN = datetime(2026, 10, 21, 20, 8, 44)


def removed(identity, barcode='CIP-COMMUN'):
    return f'- supp. de T5 la boite Id:{identity} ref:{barcode} lot:FICTIF'


def frames_for(texts):
    return [MachineState(line_num=i + 1, timestamp=i / 10, timestamp_str=f'20:08:{44+i//10:02d}',
                         raw_lines=[(i + 1, text)]) for i, text in enumerate(texts)]


def fixture():
    return frames_for(['OMEGA:T5-DEL-PACK@Ok@1', '-suppression de la boite ID:1',
                       'OMEGA:T5-DEL-PACK@Ok@1', REQUEST, START, CLEAR,
                       removed(32340), removed(32341), removed(32342), END,
                       START, CLEAR, removed(99), END,
                       'photoCamT4 FinTrsfT3-T4-ERREUR',
                       "Création de la boite 'CIP' FICTIF x=942 (60x30x100) IdA:1",
                       'OMEGA:T5-DEL-PACK@Ok@1', REQUEST, START, CLEAR, removed(100)])


class BoxCountsTests(unittest.TestCase):
    def test_month_rollover_keeps_same_drain(self):
        origin = datetime(2026, 10, 31, 23, 59, 59)
        frames = frames_for([REQUEST, START, CLEAR, removed(1), END])
        frames[-2].timestamp = -31 * 86400 + 1
        frames[-1].timestamp = -31 * 86400 + 2
        counts = analyze_robot_boxes([(n, t, f) for f in frames for n, t in f.raw_lines], origin)
        self.assertEqual(counts['rejected_boxes_count'], 1)
        self.assertEqual(counts['box_daily']['2026-11-01']['rejected_boxes_count'], 1)

    def test_browser_viewer_pdf_and_registered_proofs(self):
        import customtkinter as ctk
        import pypdfium2 as pdfium
        from playwright.sync_api import sync_playwright
        from Models.diagnostic_report import write_diagnostic_report
        from Models.report_bridge import ReportBridge
        from Widgets.diagnostic_panel import DiagnosticPanel
        texts = [REQUEST] * 8 + [text for frame in fixture() for _, text in frame.raw_lines]
        frames = frames_for(texts)
        incidents = build_diagnostics(frames, [], trace_origin=ORIGIN)
        robot = next(row for row in incidents if row.code == 'DemVidageComplet')
        self.assertEqual((robot.count, robot.severity), (10, 'error'))
        root = ctk.CTk()
        root.withdraw()
        try:
            panel = DiagnosticPanel(root, incidents, frames, on_measurement_click=lambda line: None)
            self.assertIn('3 boîte(s)', panel._details.get('1.0', 'end'))
            panel._show_details(robot)
            self.assertIn('32342', panel._details.get('1.0', 'end'))
            self.assertTrue(panel._details.tag_ranges('robot-pick-line-9'))
            panel.destroy()
        finally:
            root.destroy()
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            report = write_diagnostic_report(incidents, Path(directory), frames, source_name='BOITES FICTIVES')
            bridge = ReportBridge()
            try:
                url = bridge.register(report)
                registered = next(iter(bridge.reports.values()))['examples']
                self.assertTrue(any(key.startswith('robot-pick:') for key in registered))
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel='msedge', headless=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(url)
                    group = page.locator('details[data-group^="DemVidageComplet:"]')
                    self.assertIn('3 boîte(s)', group.locator(':scope > summary').inner_text())
                    group.locator(':scope > summary').click()
                    group.locator('.robot-day > summary').first.click()
                    self.assertIn('32342', group.inner_text())
                    self.assertGreater(group.locator('[data-source-navigate]').count(), 0)
                    with page.expect_download() as download:
                        page.locator('[data-pdf]').click()
                    pdf = Path(directory) / 'robot.pdf'
                    download.value.save_as(pdf)
                    document = pdfium.PdfDocument(pdf)
                    text = '\n'.join(p.get_textpage().get_text_range() for p in document)
                    self.assertNotIn('32342', text)
                    self.assertIn('Prises robot confirmées', text)
                    document.close()
                    self.assertFalse(errors)
                    browser.close()
            finally:
                bridge.close()

    def test_explicit_confirmations_three_boxes_manual_and_truncated(self):
        frames = fixture()
        rows = [(line, text, frame) for frame in frames for line, text in frame.raw_lines]
        counts = analyze_robot_boxes(rows, ORIGIN)
        self.assertEqual(counts['rejected_boxes_count'], 3)
        self.assertEqual(counts['robot_picked_boxes_count'], 2)
        self.assertEqual(counts['unattributed_removed_boxes_count'], 2)
        self.assertEqual(counts['unattributed_request_count'], 1)
        episode = next(row for row in counts['drain_episodes'] if row['attributed'])
        self.assertEqual([row['id_alpha'] for row in episode['boxes']], [32340, 32341, 32342])
        self.assertEqual(episode['request_lines'], [4])
        self.assertEqual(episode['box_count'], 3)

    def test_zero_boxes_repeated_requests_and_limits_unchanged(self):
        frames = frames_for([REQUEST] * 10 + [START, CLEAR, END])
        incident = next(row for row in build_diagnostics(frames, [], trace_origin=ORIGIN) if row.code == 'DemVidageComplet')
        self.assertEqual((incident.count, incident.severity), (10, 'error'))
        self.assertEqual(incident.metrics['rejected_boxes_count'], 0)
        self.assertEqual(incident.metrics['unattributed_request_count'], 0)
        self.assertEqual(len(incident.metrics['daily'][0]['examples']), 10)

    def test_stale_request_and_restart_do_not_attribute_later_block(self):
        for middle in ('version logiciel VBalpha: TEST', 'FinTrsfT3-T4-ERREUR'):
            frames = frames_for([REQUEST, middle, CLEAR, removed(1), END])
            if middle.startswith('Fin'):
                for frame in frames[1:]:
                    frame.timestamp += 121
            counts = analyze_robot_boxes([(n, t, f) for f in frames for n, t in f.raw_lines], ORIGIN)
            self.assertEqual(counts['rejected_boxes_count'], 0)
            self.assertEqual(counts['unattributed_request_count'], 1)

    def test_report_exports_complete_sources_and_legacy_is_not_zero(self):
        frames = fixture()
        incidents = build_diagnostics(frames, [], trace_origin=ORIGIN)
        payload = build_report_payload(incidents, frames)
        group = next(row for row in payload['groups'] if row['code'] == 'DemVidageComplet')
        self.assertIn('3 boîte(s)', group['box_summary'])
        proof = group['examples'][0]
        self.assertEqual(proof['box_ids'], [32340, 32341, 32342])
        self.assertTrue({4, 6, 7, 8, 9, 10}.issubset({row['line'] for row in proof['context']}))
        self.assertTrue(all(row['navigation_id'].startswith('source:') for row in proof['context']))
        self.assertEqual(len(group['pick_examples']), 2)
        self.assertTrue(all(row['context'] for row in group['pick_examples']))
        self.assertEqual(drain_box_text({}), 'Données indisponibles — régénérer le rapport')

    def test_group_boundaries_and_pick_only_segment(self):
        from Models.group_analysis import analyze_group
        from Models.frame_store import write_frame_store
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            base = Path(directory)
            sources = []
            for i, texts in enumerate(([REQUEST, START, CLEAR, removed(1)],
                                       [CLEAR, removed(2), END, 'OMEGA:T5-DEL-PACK@Ok@3'])):
                frames = frames_for(texts)
                path = base / f'{i}.old'
                path.write_text('\n'.join(texts), encoding='latin-1')
                store = base / f'store-{i}'
                write_frame_store(frames, store)
                sources.append({'filepath': str(path), 'store': str(store), 'start': f'2026-10-{21+i}T20:08:44'})
            result = analyze_group(sources, base / 'group')
            metrics = next(row.metrics for row in result['diagnostics'] if row.code == 'DemVidageComplet')
            self.assertEqual(metrics['rejected_boxes_count'], 0)
            self.assertEqual(metrics['robot_picked_boxes_count'], 1)
            self.assertEqual(metrics['unattributed_removed_boxes_count'], 2)


if __name__ == '__main__':
    unittest.main()
