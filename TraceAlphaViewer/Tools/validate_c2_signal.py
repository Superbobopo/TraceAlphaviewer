"""Valide les episodes C2, leurs limites et les preuves viewer/web/PDF."""
from pathlib import Path
from datetime import datetime
import json
import os
import re
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.state import MachineState
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Models.robot_drain import normalize_robot_incidents
from Tools.validate_report_restoration import dated_frames


RELAUNCH = 'Il y a encore au moins un capteur actif, relance le vidage machine ...'
SNAPSHOT = 'Capteurs C2:1 C3:0 C4:0 C5:0 C6:0 C9:0'


def frames_for(rows):
    frames = []
    for line, (seconds, text) in enumerate(rows, 1):
        clock = f'{int(seconds)//3600%24:02d}:{int(seconds)//60%60:02d}:{int(seconds)%60:02d}'
        frames.append(MachineState(line_num=line, timestamp=seconds, timestamp_str=clock,
                                   raw_lines=[(line, text)]))
    return frames


def blinking(count=11, step=30, duplicate=False):
    rows = [(0, 'OUVERTURE DE LA TRACE le 01/06/2026')]
    for i in range(count):
        rows.append((i * step, f'T2: WAIT-FIN-CHG eT2:43 C2:{i%2} C3:0 C4:0'))
        if duplicate:
            rows.append(rows[-1])
    return rows


def c2(frames):
    return next((i for i in build_diagnostics(frames, []) if i.code == 'C2_SIGNAL_ANOMALY'), None)


class C2Tests(unittest.TestCase):
    def test_warning_limits_duplicates_and_raw_states(self):
        incident = c2(frames_for(blinking(duplicate=True)))
        self.assertEqual((incident.severity, incident.count, incident.metrics['transitions']), ('warning', 1, 10))
        self.assertEqual(incident.metrics['episodes'][0]['duration_seconds'], 300)
        self.assertIsNone(c2(frames_for(blinking(10))))
        self.assertIsNone(c2(frames_for(blinking(11, 29))))
        frames = frames_for(blinking())
        for frame in frames:
            frame.C2 = 0; frame.C3 = 1; frame.C4 = 1
        self.assertEqual(c2(frames).metrics['transitions'], 10)

    def test_normal_progression_and_active_sensors(self):
        for boundary in ('T2: BOITE-LOAD', 'T2: TRANSFERT-TERMINE',
                         'T2: Transfert de T2->EA terminé',
                         'T2: WAIT-FIN-CHG C2:1 C3:1 C4:0',
                         'T2: WAIT-FIN-CHG C2:1 C3:0 C4:1',
                         'version logiciel VBalpha: 1.0'):
            with self.subTest(boundary=boundary):
                rows = blinking(6) + [(151, boundary)]
                rows += [(seconds + 180, text) for seconds, text in blinking(6)[1:]]
                self.assertIsNone(c2(frames_for(rows)))

    def test_gap_and_inclusive_observation_boundary(self):
        rows = blinking(6)
        rows += [(seconds + 271, text) for seconds, text in blinking(6)[1:]]
        self.assertIsNone(c2(frames_for(rows)))
        rows = blinking(6) + [(seconds + 270, text) for seconds, text in blinking(6)[1:]]
        self.assertEqual(c2(frames_for(rows)).count, 1)
        rows = blinking() + [(500, 'Fin de trace'), (510, RELAUNCH), (511, SNAPSHOT)]
        self.assertEqual(c2(frames_for(rows)).count, 2)

    def test_explicit_block_without_blinking(self):
        for delay, fillers in ((0, 0), (2, 2)):
            rows = [(0, RELAUNCH)] + [(0, 'autre ligne')]*fillers + [(delay, SNAPSHOT)]
            incident = c2(frames_for(rows))
            self.assertEqual((incident.severity, incident.count), ('error', 1))
            self.assertEqual(incident.metrics['drain_relaunches'], 1)
            self.assertEqual(incident.metrics['transitions'], 0)

    def test_incomplete_unrelated_or_late_snapshots(self):
        for snapshot, delay, fillers in (
            ('Capteurs C2:1 C3:0 C4:0', 0, 0),
            (SNAPSHOT.replace('C5:0', 'C5:1'), 0, 0),
            (SNAPSHOT.replace('C9:0', 'C9:1'), 0, 0),
            (SNAPSHOT.replace('C3:0', 'C3:1'), 0, 0),
            (SNAPSHOT, 2.1, 0), (SNAPSHOT, 1, 3)):
            with self.subTest(snapshot=snapshot, delay=delay, fillers=fillers):
                self.assertIsNone(c2(frames_for([(0, RELAUNCH)] + [(0, 'autre')]*fillers + [(delay, snapshot)])))
        frames = frames_for([(0, RELAUNCH), (1, SNAPSHOT)])
        frames[-1].raw_lines = [(5, SNAPSHOT)]
        self.assertIsNone(c2(frames))

    def test_episodes_recovery_initializations_and_priority(self):
        rows = blinking() + [(301, RELAUNCH), (302, SNAPSHOT),
            (303, 'InitMachine: demande initialisation de T2'),
            (303, 'InitMachine: demande initialisation de T4'),
            (304, 'Vid: Fin de vidage de la machine'), (305, 'T2: BOITE-LOAD')]
        frames = frames_for(rows)
        incident = c2(frames)
        self.assertEqual(incident.metrics['initialization_requests'], 1)
        self.assertIn('reprise', incident.examples[0]['sources'])
        self.assertIn('Fin de vidage', incident.examples[0]['detail'])
        payload = build_report_payload([incident], frames)
        group = payload['groups'][0]
        self.assertEqual(group['family'], 't2')
        self.assertEqual(group['field_priority'], 501)
        self.assertEqual(group['series'][0]['evidence_count'], 1)
        self.assertEqual(group['examples'][0]['detail'], incident.examples[0]['detail'])
        self.assertTrue(group['examples'][0]['context'])
        self.assertTrue(all(row['navigation_id'] for row in group['examples'][0]['context']))

    def test_example_limit_and_episode_score(self):
        rows = []
        for index in range(12):
            rows += [(index*1000, RELAUNCH), (index*1000+1, SNAPSHOT)]
        frames = frames_for(rows)
        incident = c2(frames)
        self.assertEqual(incident.count, 12)
        self.assertEqual(len(incident.examples), 10)
        group = build_report_payload([incident], frames)['groups'][0]
        self.assertEqual(group['series'][0]['evidence_count'], 12)
        self.assertEqual(group['field_priority'], 512)

    def test_robot_stale_critical_flags_are_ignored(self):
        frames = dated_frames()
        incidents = build_diagnostics(frames, [])
        robot = next(i for i in incidents if i.code == 'DemVidageComplet')
        robot.severity = 'error'
        robot.metrics.update(critical=True, reinforced=True)
        normalized = normalize_robot_incidents(incidents)
        self.assertEqual(normalized[0].severity, 'info')
        payload = build_report_payload(incidents, frames)
        self.assertFalse(payload['priority'])
        self.assertEqual(payload['groups'][0]['field_severity'], 'info')
        self.assertEqual(robot.severity, 'error')

    def test_viewer_sources_and_counts(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        frames = frames_for(blinking() + [(301, RELAUNCH), (302, SNAPSHOT), (303, 'T2: BOITE-LOAD')])
        incident = c2(frames)
        root = ctk.CTk(); root.withdraw()
        received = []
        measured = []
        try:
            panel = DiagnosticPanel(root, [incident], frames, on_incident_click=received.append,
                                    on_measurement_click=measured.append)
            panel._show_details(incident)
            text = panel._details.get('1.0', 'end')
            self.assertIn(incident.summary, text)
            line = incident.examples[0]['sources']['reprise']
            tag = f'c2-source-{line}'
            self.assertTrue(panel._details.tag_ranges(tag))
            script = panel._details.tk.call(panel._details._w, 'tag', 'bind', tag, '<Button-1>')
            command = re.search(r'\[([^\s]+)', script)[1]
            panel._details.tk.call(command, *(['0'] * len(panel._details._subst_format)))
            self.assertEqual(received[0].first_line, line)
            dated = dated_frames()
            robot = next(i for i in build_diagnostics(dated, [], trace_origin=datetime(2025, 12, 31, 23)) if i.code == 'DemVidageComplet')
            panel.set_incidents([robot])
            panel._show_details(robot)
            text = panel._details.get('1.0', 'end')
            self.assertIn('Aucune demande', text)
            self.assertIn('31 décembre 2025', text)
            self.assertTrue(panel._details.tag_ranges('robot-drain-line-2'))
            panel._details.tk.call(panel._measurement_bindings['robot-drain-line-2'],
                                   *(['0'] * len(panel._details._subst_format)))
            self.assertEqual(measured, [2])
            panel.destroy()
        finally:
            for job in root.tk.call('after', 'info'):
                root.tk.call('after', 'cancel', job)
            root.destroy()

    def test_real_trace(self):
        trace = os.environ.get('TRACE_ALPHA_C2_TRACE')
        if not trace:
            self.skipTest('Trace terrain C2 non fournie')
        from Parser.trace_parser import parse_file
        from Models.folder_report import _collect_events
        frames = parse_file(trace, min_dt=0.0)
        incidents = build_diagnostics(frames, _collect_events(frames))
        by_code = {i.code: i for i in incidents}
        self.assertNotIn('C3_SIGNAL_ANOMALY', by_code)
        self.assertEqual((by_code['DemVidageComplet'].severity, by_code['DemVidageComplet'].count), ('info', 2))
        self.assertEqual(sum(i.count for i in incidents if i.code == 'INIT-INDEX'), 28)
        incident = by_code['C2_SIGNAL_ANOMALY']
        morning = [episode for episode in incident.metrics['episodes'] if episode['first_line'] == 41240]
        self.assertEqual(morning[0]['drain_relaunches'], 19)
        self.assertEqual(morning[0]['blocks'][0]['request']['line'], 41396)
        self.assertEqual(morning[0]['blocks'][0]['state']['line'], 41397)
        self.assertEqual(incident.metrics['drain_relaunches'], 46)
        self.assertEqual(incident.metrics['transitions'], 9994)
        payload = build_report_payload(incidents, frames, source_name=Path(trace).name)
        self.assertEqual((payload['unknown']['count'], payload['unknown']['total']), (35, 470))
        self.assertEqual(by_code['REFERENCE_ABSENT'].count, 2)
        self.assertEqual(by_code['REFERENCE_NON_ALPHATISABLE'].count, 1)
        self.assertNotIn('DemVidageComplet', [g['code'] for g in payload['priority']])
        baseline = ROOT/'build/rapport-tracalpha1-non-alphatisable/payload.json'
        if baseline.exists():
            old = json.loads(baseline.read_text(encoding='utf-8'))
            for key in ('measurements', 'measurement_references', 'orientation_references', 'camera', 'unknown'):
                self.assertEqual(payload[key], old[key], key)
        output = ROOT/'build/rapport-tracalpha1-c2'; output.mkdir(parents=True, exist_ok=True)
        previous = output/'payload.json'
        if previous.exists():
            old = json.loads(previous.read_text(encoding='utf-8'))
            fresh = json.loads(json.dumps(payload))
            old.pop('generated_at', None); fresh.pop('generated_at', None)
            self.assertEqual(fresh, old, 'Les résultats terrain C2 et les autres diagnostics doivent rester identiques')
        (output/'payload.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        report = write_diagnostic_report(incidents, output, frames, source_name=Path(trace).name)
        print(f'Trace C2 : {incident.summary}. Rapport : {report}', flush=True)

    def test_browser_information_c2_pdf_and_navigation(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        from Models.report_bridge import ReportBridge
        from Models.diagnostic import DiagnosticIncident
        rows = blinking() + [(301, RELAUNCH), (302, SNAPSHOT),
            (303, 'InitMachine: demande initialisation de T2'),
            (304, 'Vid: Fin de vidage de la machine'), (305, 'T2: BOITE-LOAD'),
            (310, 'OMEGA:T5-DemVidageComplet'), (311, 'OMEGA:T5-DemVidageComplet'),
            (86400, 'Fin de démonstration fictive')]
        frames = frames_for(rows)
        incidents = build_diagnostics(frames, [], trace_origin=datetime(2026, 6, 1))
        incidents.append(DiagnosticIncident(severity='error', title='T4 - Initialisations répétées',
            belt='T4', code='INIT-INDEX', count=28, first_line=1, last_line=1))
        output = ROOT/'build/c2-validation'; output.mkdir(parents=True, exist_ok=True)
        report = write_diagnostic_report(incidents, output, frames, source_name='DONNEES FICTIVES C2')
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
                    self.assertEqual(page.locator('.robot-drain-alert').count(), 0)
                    priorities = page.locator('.priority-grid').inner_text()
                    self.assertNotIn('Vidage complet', priorities)
                    self.assertLess(priorities.index('T4 -'), priorities.index('Capteur C2'))
                    page.locator('.priorities').screenshot(path=str(output/'priorites-large.png'))
                    detail = page.locator('details[data-group^="C2_SIGNAL_ANOMALY:"]')
                    detail.locator('> summary').click()
                    detail.locator('.incident-series').evaluate('(node)=>node.open=true')
                    self.assertIn('10 bascule(s)', detail.inner_text())
                    self.assertIn('Blocage confirmé', detail.inner_text())
                    self.assertIn('Reprise observée', detail.inner_text())
                    detail.locator('.sample-technical').first.evaluate('(node)=>node.open=true')
                    if url.startswith('http:'):
                        page.wait_for_function("!document.querySelector('[data-source-navigate]').disabled")
                        received = []
                        def receive():
                            target, done, result = bridge.commands.get(timeout=5)
                            received.append(target); result.update(ok=True, line=target['line']); done.set()
                        worker = threading.Thread(target=receive); worker.start()
                        detail.locator('.trace-line').first.click(); worker.join(5)
                        self.assertTrue(received[0]['source_line'])
                    page.set_viewport_size({'width':390, 'height':900})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    detail.screenshot(path=str(output/'c2-etroit.png'))
                    page.set_viewport_size({'width':1600, 'height':1000})
                    detail.screenshot(path=str(output/'c2-large.png'))
                    robot = page.locator('details[data-group^="DemVidageComplet:"]')
                    robot.locator('> summary').click()
                    self.assertIn('Info', robot.inner_text())
                    self.assertIn('Aucune demande', robot.inner_text())
                    with page.expect_download() as download:
                        page.locator('[data-pdf]').click()
                    pdf = output/'rapport.pdf'; download.value.save_as(pdf)
                    document = pdfium.PdfDocument(pdf)
                    text = '\n'.join(document[i].get_textpage().get_text_range() for i in range(len(document)))
                    self.assertIn('C2', text)
                    self.assertIn('10 bascule(s)', text)
                    self.assertIn('Synthèse terrain', text)
                    self.assertNotIn('Blocage confirmé', text)
                    self.assertNotIn('Aucune demande', text)
                    self.assertIn('2 demandes sur 2 jours de trace', text)
                    self.assertNotIn('Pic sur 24 h', text)
                    self.assertNotIn('Pic sur 1 h', text)
                    self.assertGreater(text.index('Vidage complet'), text.index('Lecture et exploitation'))
                    document.close()
                self.assertFalse(errors)
                browser.close()
        finally:
            bridge.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
