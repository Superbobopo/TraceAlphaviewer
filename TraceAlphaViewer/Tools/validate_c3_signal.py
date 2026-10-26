"""Valide le signal C3 sur donnees fictives et son independance vis-a-vis de C2."""
from pathlib import Path
import re
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Tools.validate_c2_signal import frames_for, RELAUNCH, SNAPSHOT as C2_SNAPSHOT

SNAPSHOT = 'Capteurs C2:0 C3:1 C4:0 C5:0 C6:0 C9:0'


def blinking(count=11, step=30, duplicate=False):
    rows = [(0, 'OUVERTURE DE LA TRACE le 01/06/2026')]
    for i in range(count):
        rows.append((i * step, f'T2: WAIT-FIN-CHG eT2:43 C2:0 C3:{i%2} C4:0'))
        if duplicate:
            rows.append(rows[-1])
    return rows


def signal(frames):
    return next((i for i in build_diagnostics(frames, []) if i.code == 'C3_SIGNAL_ANOMALY'), None)


def combined_frames():
    rows = [(0, 'OUVERTURE DE LA TRACE le 01/06/2026'), (1, RELAUNCH),
            (2, C2_SNAPSHOT), (3, 'T2: BOITE-LOAD')]
    rows += [(seconds + 10, text) for seconds, text in blinking()[1:]]
    rows += [(311, RELAUNCH), (312, SNAPSHOT),
             (313, 'InitMachine: demande initialisation de T2'),
             (313, 'InitMachine: demande initialisation de T4'),
             (314, 'Vid: Fin de vidage de la machine'),
             (315, 'T2: WAIT-FIN-CHG eT2:43 C2:1 C3:0 C4:0'),
             (400, RELAUNCH), (401, SNAPSHOT), (402, 'T2: TRANSFERT-TERMINE')]
    return frames_for(rows)


class C3Tests(unittest.TestCase):
    def test_warning_thresholds_duplicates_and_raw_values(self):
        frames = frames_for(blinking(duplicate=True))
        for frame in frames:
            frame.C3 = 0; frame.C2 = 1; frame.C4 = 1
        incident = signal(frames)
        self.assertEqual((incident.severity, incident.count, incident.metrics['transitions']), ('warning', 1, 10))
        self.assertEqual(incident.metrics['episodes'][0]['duration_seconds'], 300)
        self.assertIn('C2 et C4 à zéro', incident.examples[0]['detail'])
        for rows in (blinking(10, step=40), blinking(11, step=29), blinking(1)):
            self.assertIsNone(signal(frames_for(rows)))
        self.assertIsNone(signal(frames_for([(0, 'T2: WAIT-FIN-CHG C3:1 C4:0')]*20)))

    def test_normal_progression_restart_and_other_sensors(self):
        for boundary in ('T2: BOITE-LOAD', 'T2: TRANSFERT-TERMINE',
                         'T2: Transfert de T2->EA terminé',
                         'T2: WAIT-FIN-CHG C2:1 C3:1 C4:0',
                         'T2: WAIT-FIN-CHG C2:0 C3:1 C4:1',
                         'version logiciel VBalpha: 1.0'):
            with self.subTest(boundary=boundary):
                rows = blinking(6) + [(151, boundary)]
                rows += [(seconds + 180, text) for seconds, text in blinking(6)[1:]]
                self.assertIsNone(signal(frames_for(rows)))
        rows = blinking()[:6] + [(121, 'OUVERTURE DE LA TRACE le 01/06/2026')] + blinking()[6:]
        self.assertEqual(signal(frames_for(rows)).count, 1)

    def test_gaps_and_truncated_trace(self):
        for offset, expected in ((270, True), (271, False)):
            rows = blinking(6) + [(seconds + offset, text) for seconds, text in blinking(6)[1:]]
            self.assertEqual(signal(frames_for(rows)) is not None, expected)
        incident = signal(frames_for(blinking()))
        self.assertIsNone(incident.metrics['episodes'][0]['recovery'])
        self.assertIn('résolution non observée', incident.examples[0]['detail'])
        self.assertIsNone(signal(frames_for([(0, RELAUNCH)])))

    def test_critical_complete_state_and_physical_time_limits(self):
        for delay, fillers in ((0, 0), (2, 2)):
            frames = frames_for([(0, RELAUNCH)] + [(0, 'autre')]*fillers + [(delay, SNAPSHOT), (delay, SNAPSHOT)])
            incident = signal(frames)
            self.assertEqual((incident.severity, incident.count), ('error', 1))
            self.assertEqual(incident.metrics['drain_relaunches'], 1)
            self.assertEqual(incident.metrics['transitions'], 0)
            self.assertIn('C2:0 C3:1 C4:0 C5:0 C6:0 C9:0', incident.examples[0]['detail'])
        for delay, fillers in ((2.1, 0), (1, 3)):
            self.assertIsNone(signal(frames_for([(0, RELAUNCH)] + [(0, 'autre')]*fillers + [(delay, SNAPSHOT)])))
        frames = frames_for([(0, RELAUNCH), (1, SNAPSHOT)])
        frames[-1].raw_lines = [(5, SNAPSHOT)]
        self.assertIsNone(signal(frames))

    def test_incomplete_states_and_multiple_active_sensors(self):
        for snapshot in ('Capteurs C2:0 C3:1 C4:0', C2_SNAPSHOT,
                         *[SNAPSHOT.replace(f'{key}:0', f'{key}:1') for key in ('C2', 'C4', 'C5', 'C6', 'C9')]):
            with self.subTest(snapshot=snapshot):
                frames = frames_for([(0, RELAUNCH), (1, snapshot)])
                self.assertIsNone(signal(frames))
                if 'C2:1 C3:1' in snapshot:
                    self.assertFalse(build_diagnostics(frames, []))

    def test_c2_activation_is_not_a_recovery(self):
        frames = combined_frames()
        incident = signal(frames)
        first, second = incident.metrics['episodes']
        self.assertIsNone(first['recovery'])
        self.assertIn('fin_contexte', first['sources'])
        self.assertNotIn('reprise', first['sources'])
        self.assertIn('reprise T2 non attestée', first['detail'])
        self.assertNotIn('Reprise observée', first['detail'])
        self.assertIsNotNone(second['recovery'])
        self.assertIn('Reprise observée', second['detail'])
        self.assertEqual(incident.metrics['initialization_requests'], 1)

    def test_separate_cards_episode_counts_and_limited_examples(self):
        frames = combined_frames()
        payload = build_report_payload(build_diagnostics(frames, []), frames)
        groups = {group['code']: group for group in payload['groups']}
        c2, c3 = groups['C2_SIGNAL_ANOMALY'], groups['C3_SIGNAL_ANOMALY']
        self.assertEqual((c2['occurrence_count'], c3['occurrence_count']), (1, 2))
        self.assertEqual((c2['field_priority'], c3['field_priority']), (501, 502))
        self.assertEqual(c3['series'][0]['evidence_count'], 2)
        self.assertEqual(c3['family'], 't2')
        self.assertIn('C3 seul actif', c3['metric'])
        self.assertIn('devant C3', c3['field_action'])
        self.assertTrue(c3['examples'][0]['context'])
        for changes in (10, 1000):
            frames = frames_for(blinking(changes+1, step=300/changes))
            group = build_report_payload(build_diagnostics(frames, []), frames)['groups'][0]
            self.assertEqual(group['field_priority'], 191)
        frames = frames_for([(index*1000+delta, text) for index in range(12)
                             for delta, text in ((0, RELAUNCH), (1, SNAPSHOT))])
        group = build_report_payload(build_diagnostics(frames, []), frames)['groups'][0]
        self.assertEqual((group['occurrence_count'], len(group['examples'])), (12, 10))
        self.assertEqual(group['series'][0]['evidence_count'], 12)

    def test_viewer_c3_proof_navigation(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        frames = combined_frames()
        incident = signal(frames)
        root = ctk.CTk(); root.withdraw()
        received = []
        try:
            panel = DiagnosticPanel(root, build_diagnostics(frames, []), frames, on_incident_click=received.append)
            panel._show_details(incident)
            self.assertIn(incident.summary, panel._details.get('1.0', 'end'))
            line = incident.examples[0]['sources']['fin_contexte']
            script = panel._details.tk.call(panel._details._w, 'tag', 'bind', f'c3-source-{line}', '<Button-1>')
            command = re.search(r'\[([^\s]+)', script)[1]
            panel._details.tk.call(command, *(['0'] * len(panel._details._subst_format)))
            self.assertEqual((received[0].code, received[0].first_line), ('C3_SIGNAL_ANOMALY', line))
            panel.destroy()
        finally:
            for job in root.tk.call('after', 'info'):
                root.tk.call('after', 'cancel', job)
            root.destroy()

    def test_browser_both_cards_navigation_and_pdf(self):
        from playwright.sync_api import sync_playwright
        from Models.report_bridge import ReportBridge
        import pypdfium2 as pdfium
        frames = combined_frames()
        incidents = build_diagnostics(frames, [])
        output = ROOT/'build/c3-validation'; output.mkdir(parents=True, exist_ok=True)
        report = write_diagnostic_report(incidents, output, frames, source_name='DONNEES FICTIVES C2/C3')
        fallback = output/'fallback.html'
        fallback.write_text(build_diagnostic_report_html(incidents, frames), encoding='utf-8')
        bridge = ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width':1600, 'height':1000})
                errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                for url in (bridge.register(report), fallback.as_uri()):
                    page.goto(url)
                    for sensor in ('C2', 'C3'):
                        self.assertEqual(page.locator(f'details[data-group^="{sensor}_SIGNAL_ANOMALY:"]').count(), 1)
                    detail = page.locator('details[data-group^="C3_SIGNAL_ANOMALY:"]')
                    detail.locator('> summary').click()
                    detail.locator('.incident-series').evaluate('(node)=>node.open=true')
                    self.assertIn('10 bascule(s) C3', detail.inner_text())
                    self.assertIn('C3 seul actif', detail.inner_text())
                    self.assertIn('reprise T2 non attestée', detail.inner_text())
                    self.assertIn('Reprise observée', detail.inner_text())
                    for node in detail.locator('.sample-technical').all():
                        node.evaluate('(node)=>node.open=true')
                    line = signal(frames).examples[0]['sources']['fin_contexte']
                    link = detail.locator(f'[data-source-navigate="source:{line}"]').first
                    if url.startswith('http:'):
                        page.wait_for_function("!document.querySelector('[data-source-navigate]').disabled")
                        received = []
                        def receive():
                            target, done, result = bridge.commands.get(timeout=5)
                            received.append(target); result.update(ok=True, line=target['line']); done.set()
                        worker = threading.Thread(target=receive); worker.start()
                        link.click(); worker.join(5)
                        self.assertEqual(received[0]['line'], line)
                        self.assertTrue(received[0]['source_line'])
                    else:
                        self.assertTrue(link.is_disabled())
                    detail.screenshot(path=str(output/'c3-large.png'))
                    page.set_viewport_size({'width':390, 'height':900})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    detail.screenshot(path=str(output/'c3-etroit.png'))
                    page.set_viewport_size({'width':1600, 'height':1000})
                    with page.expect_download() as download:
                        page.locator('[data-pdf]').click()
                    pdf = output/'rapport.pdf'; download.value.save_as(pdf)
                    document = pdfium.PdfDocument(pdf)
                    text = '\n'.join(document[i].get_textpage().get_text_range() for i in range(len(document)))
                    for expected in ('Capteur C2', 'Capteur C3', '10 bascule(s) C3', 'C3 seul actif',
                                     'Synthèse terrain', 'Mesures et présentation'):
                        self.assertIn(expected, text)
                    self.assertNotIn('fin_contexte', text)
                    document.close()
                self.assertFalse(errors)
                browser.close()
        finally:
            bridge.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
