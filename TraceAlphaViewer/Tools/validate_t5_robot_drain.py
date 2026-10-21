"""Valide les frequences robot, leur priorite et les alertes viewer/web/PDF."""
from pathlib import Path
import sys
import threading
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.state import MachineState
from Models.diagnostic import build_diagnostics, DiagnosticIncident, _build_text_pattern_incidents
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Models.robot_drain import drain_metrics, t5_priority_score


def frames_for(times):
    return [MachineState(line_num=i, timestamp=t, timestamp_str=f'{int(t)//86400+1:02d}|{int(t)%86400//3600:02d}:{int(t)%3600//60:02d}:{int(t)%60:02d}',
            raw_lines=[(i, 'UDP trame recu du robot: @T1@OMEGA:T5-DemVidageComplet')])
            for i, t in enumerate(times, 1)]


def stale_incident():
    return DiagnosticIncident(severity='error', title='Boite non mesuree bloquante', belt='T5',
        code='T5_STALE_UNMEASURED_BOX', count=3, first_line=1, last_line=3, event_lines=[1, 2, 3])


class RobotDrainTests(unittest.TestCase):
    def test_thresholds_and_windows(self):
        for times, critical, reinforced, hour, day in [
            ([], False, False, 0, 0), ([0], False, False, 1, 1),
            ([0, 3600], False, False, 2, 2), ([0, 3600.1], False, False, 1, 2),
            ([0, 21600, 43200, 64800, 86400], False, False, 1, 5),
            ([0, 21600, 43200, 64800, 86400.1], False, False, 1, 4),
            (list(range(0, 1500000, 100000)), False, False, 1, 1),
            (list(range(0, 84001, 6000)), True, False, 1, 15),
            ([86390, 86410], False, False, 2, 2),
            (list(range(9)), False, False, 9, 9),
            (list(range(10)), True, False, 10, 10),
            (list(range(11)), True, False, 11, 11),
            (list(range(0, 86401, 9600)), True, False, 1, 10),
            (list(range(0, 86400, 9600)) + [86400.1], False, False, 1, 9),
            (list(range(86390, 86410, 2)), True, False, 10, 10),
        ]:
            with self.subTest(times=times):
                metrics = drain_metrics([(i, t, str(t)) for i, t in enumerate(times)])
                self.assertEqual((metrics['critical'], metrics['reinforced'], metrics['hour']['count'],
                                  metrics['day']['count']), (critical, reinforced, hour, day))

    def test_detection_and_priority(self):
        for count in (1, 5, 6, 9, 10, 11, 15):
            frames = frames_for([i * 7200 for i in range(count)] if count < 15 else [i * 6000 for i in range(15)])
            frames[0].raw_lines += [(100, 'T5v: Une demande de vidage complet de T5 est demandee'),
                                    (101, '118-Vide T5 suite blocage poubelle'),
                                    (102, 'Robot prend IdA=1')]
            incidents = build_diagnostics(frames, [])
            robot = next(item for item in incidents if item.code == 'DemVidageComplet')
            self.assertEqual(robot.count, count)
            self.assertEqual(robot.severity, 'info' if count < 10 else 'error')
            payload = build_report_payload(incidents + [stale_incident()], frames)
            group = next(item for item in payload['groups'] if item['code'] == robot.code)
            self.assertEqual(group['family'], 'robot')
            self.assertLessEqual(len(group['examples']), 10)
            expected = t5_priority_score(robot.code, robot.severity, count, robot.metrics)
            self.assertEqual(group['field_priority'], expected)
            if count >= 10:
                self.assertEqual(payload['priority'][0]['code'], robot.code)
            else:
                self.assertNotIn(robot.code, [item['code'] for item in payload['priority']])
        frames = frames_for([i * 100000 for i in range(6)])
        payload = build_report_payload(build_diagnostics(frames, []) + [stale_incident()], frames)
        self.assertEqual(payload['priority'][0]['code'], 'T5_STALE_UNMEASURED_BOX')
        self.assertEqual(t5_priority_score('DemVidageComplet', 'error', 15,
            drain_metrics([(i, i * 6000, '') for i in range(15)])), 655)
        self.assertFalse(build_diagnostics([], []))

    def test_loire_source_commands(self):
        import re
        trace = ROOT / 'TraceAlphaViewer' / 'TracAlphaloire.txt'
        if not trace.exists():
            self.skipTest('Trace Loire locale absente')
        rows = []
        with trace.open(encoding='latin-1') as source:
            for line, text in enumerate(source, 1):
                if 'OMEGA:T5-DemVidageComplet' not in text:
                    continue
                match = re.search(r'(\d+)\|(\d+):(\d+):(\d+)\.(\d+)', text)
                d, h, m, s, ds = map(int, match.groups())
                state = MachineState(timestamp=d*86400+h*3600+m*60+s+ds/10,
                                     timestamp_str=match[0], line_num=line, raw_lines=[(line, text.rstrip())])
                rows.append((line, text, state))
        robot = next(item for item in _build_text_pattern_incidents(rows) if item.code == 'DemVidageComplet')
        self.assertEqual(robot.count, 58)
        payload = build_report_payload([robot], [row[2] for row in rows])
        group = payload['groups'][0]
        self.assertEqual(group['occurrence_count'], 58)
        self.assertEqual(len(group['examples']), 10)
        from Parser.trace_parser import parse_file
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / 'commandes.old'
            selected.write_text(''.join(row[1] for row in rows), encoding='latin-1')
            parsed = parse_file(str(selected), min_dt=0.0)
            parsed_robot = next(item for item in build_diagnostics(parsed, []) if item.code == robot.code)
            self.assertEqual(parsed_robot.count, 58)
            for window in ('hour', 'day'):
                self.assertEqual(parsed_robot.metrics[window]['count'], robot.metrics[window]['count'])
        print(f"Loire : {robot.summary} Fenetres : {robot.metrics['hour']} ; {robot.metrics['day']}", flush=True)

    def test_viewer_alert_and_order(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        root = ctk.CTk(); root.withdraw()
        try:
            for count in (1, 5, 6, 9, 10):
                frames = frames_for([i * 7200 for i in range(count)])
                incidents = build_diagnostics(frames, []) + [stale_incident()]
                received = []
                panel = DiagnosticPanel(root, incidents, frames, on_measurement_click=received.append)
                text = panel._details.get('1.0', 'end')
                self.assertEqual('VIDAGE COMPLET T5 DEMANDE PAR LE ROBOT' in text, count >= 10)
                ranking = text.split('A TRAITER EN PRIORITE')[1].split('TOUS LES TYPES')[0]
                if count >= 10:
                    self.assertLess(ranking.index('DemVidageComplet'), ranking.index('T5_STALE_UNMEASURED_BOX'))
                else:
                    self.assertNotIn('DemVidageComplet', ranking)
                tag = 'robot-drain-details'
                self.assertEqual(bool(panel._details.tag_ranges(tag)), count >= 10)
                robot = next(item for item in incidents if item.code == 'DemVidageComplet')
                panel._show_details(robot)
                self.assertIn('Pic sur 24 h', panel._details.get('1.0', 'end'))
                tag = 'robot-drain-line-1'
                self.assertTrue(panel._details.tag_ranges(tag))
                panel._details.tk.call(panel._measurement_bindings[tag],
                                       *(['0'] * len(panel._details._subst_format)))
                self.assertEqual(received, [1])
                panel.destroy()
        finally:
            for job in root.tk.call('after', 'info'):
                root.tk.call('after', 'cancel', job)
            root.destroy()

    def test_browser_alert_pdf_and_navigation(self):
        from playwright.sync_api import sync_playwright
        from Models.report_bridge import ReportBridge
        import pypdfium2 as pdfium
        frames = frames_for([i * 5000 for i in range(16)])
        incidents = build_diagnostics(frames, []) + [stale_incident()]
        output = ROOT / 'build' / 'robot-drain-validation'; output.mkdir(parents=True, exist_ok=True)
        report = write_diagnostic_report(incidents, output, frames, source_name='DEMONSTRATION FICTIVE')
        fallback = output / 'fallback.html'
        fallback.write_text(build_diagnostic_report_html(incidents, frames), encoding='utf-8')
        bridge = ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width':1440, 'height':1000})
                errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                for url in (bridge.register(report), fallback.as_uri()):
                    page.goto(url)
                    alert = page.locator('.robot-drain-alert')
                    self.assertTrue(alert.is_visible())
                    self.assertIn('critique', alert.inner_text().lower())
                    self.assertIn('16', alert.inner_text())
                    alert.focus(); page.keyboard.press('Enter')
                    detail = page.locator('details[data-group^="DemVidageComplet:"]')
                    self.assertTrue(detail.evaluate('(node)=>node.open'))
                    self.assertEqual(detail.locator('.incident-series .sample').count(), 10)
                    self.assertIn('demandes distinctes', detail.locator('.incident-series > summary').inner_text())
                    detail.locator('.incident-series').evaluate('(node)=>node.open=true')
                    technical = detail.locator('.sample-technical').first
                    technical.evaluate('(node)=>node.open=true')
                    link = technical.locator('.trace-line').first
                    if url.startswith('http:'):
                        page.wait_for_function("!document.querySelector('[data-source-navigate]').disabled")
                        received = []
                        def receive():
                            target, done, result = bridge.commands.get(timeout=5)
                            received.append(target); result.update(ok=True, line=target['line']); done.set()
                        worker = threading.Thread(target=receive); worker.start()
                        link.click(); worker.join(5)
                        self.assertTrue(received[0]['source_line'])
                    else:
                        self.assertTrue(link.is_disabled())
                    with page.expect_download() as download:
                        page.locator('[data-pdf]').click()
                    pdf = output / 'rapport.pdf'; download.value.save_as(pdf)
                    document = pdfium.PdfDocument(pdf)
                    text = '\n'.join(document[i].get_textpage().get_text_range() for i in range(len(document)))
                    self.assertIn('Vidage complet T5', text)
                    self.assertIn('Pic sur 24 h', text)
                    document.close()
                    page.locator('.priorities').screenshot(path=str(output / 'alerte.png'))
                    page.set_viewport_size({'width':390, 'height':900})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    page.set_viewport_size({'width':1440, 'height':1000})
                self.assertFalse(errors)
                browser.close()
        finally:
            bridge.close()


if __name__ == '__main__':
    unittest.main()
