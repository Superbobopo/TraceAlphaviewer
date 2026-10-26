"""Verifie les informations restaurees, leurs preuves et les anciens rapports."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import os
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.state import MachineState
from Models.trace_calendar import trace_calendar
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Models.measurement_analysis import analyze_measurements
from Models.dimension_check import orientation_category
from Models.robot_drain import read_trace_origin
from Models.report_bridge import ReportBridge
from Tools.validate_measurement_report import orientation_samples


def dated_frames():
    frames = []
    for index, (seconds, clock, text) in enumerate([
        (0, '23:00:00', 'OUVERTURE DE LA TRACE le 31/12/2025'),
        (10, '23:00:10', 'OMEGA:T5-DemVidageComplet'),
        (20, '23:00:20', 'OMEGA:T5-DemVidageComplet'),
        (93600, '01:00:00', 'Fin de la trace'),
    ], 1):
        frames.append(MachineState(line_num=index, timestamp=seconds, timestamp_str=clock,
                                   raw_lines=[(index, text)]))
    return frames


class RestorationTests(unittest.TestCase):
    def test_legacy_frames_without_raw_lines_keep_observed_times(self):
        frames = [MachineState(timestamp=0, timestamp_str='09:00:00'),
                  MachineState(timestamp=60, timestamp_str='09:01:00')]
        source = build_report_payload([], frames)['source']
        self.assertEqual((source['start'], source['end']), ('Dates indisponibles', 'Rechargez la trace'))
        self.assertFalse(source['dates_available'])

    def test_calendar_rollovers_and_no_invented_date(self):
        frames = dated_frames()
        calendar = trace_calendar([(f.line_num, f.raw_lines[0][1], f) for f in frames])
        self.assertEqual((calendar['start'], calendar['end'], calendar['days']),
                         ('31/12/2025 à 23:00:00', '02/01/2026 à 01:00:00', 3))
        frames[0].raw_lines = [(1, 'Version logiciel du 12/04/2024')]
        self.assertFalse(trace_calendar([(f.line_num, f.raw_lines[0][1], f) for f in frames])['available'])
        frames[0].raw_lines = [(1, 'OUVERTURE DE LA TRACE le 31/01/2026')]
        frames[-1].timestamp = -30 * 86400 + 7200
        calendar = trace_calendar([(f.line_num, f.raw_lines[0][1], f) for f in frames])
        self.assertEqual(calendar['end'], '01/02/2026 à 01:00:00')

    def test_daily_zero_days_proofs_and_cached_metrics(self):
        frames = dated_frames()
        incidents = build_diagnostics(frames, [], trace_origin=datetime(2025, 12, 31, 23))
        payload = build_report_payload(incidents, frames)
        robot = next(group for group in payload['groups'] if group['code'] == 'DemVidageComplet')
        self.assertEqual([day['count'] for day in robot['daily']], [2, 0, 0])
        self.assertEqual([sample['line'] for sample in robot['examples']], [2, 3])
        self.assertEqual(robot['examples'][1]['display_time_str'], '31/12/2025 à 23:00:20')
        old = deepcopy(incidents)
        for incident in old:
            if incident.code == 'DemVidageComplet':
                for key in ('trace', 'daily', 'requests_start', 'requests_end'):
                    incident.metrics.pop(key, None)
        restored = next(group for group in build_report_payload(old, frames)['groups'] if group['code'] == 'DemVidageComplet')
        self.assertNotIn('daily', restored)
        self.assertIn('Dates indisponibles', restored['trace_period'])
        self.assertEqual(restored['metrics']['critical'], robot['metrics']['critical'])

    def test_orientation_partition_keeps_denominators_and_cached_analyses(self):
        analysis = analyze_measurements(orientation_samples())
        lists = analysis['orientation_references']
        self.assertEqual(sum(row['count'] for kind in ('flat_rotation', 'on_edge', 'other') for row in lists[kind]),
                         sum(row['count'] for row in lists['probable']))
        self.assertEqual(lists['flat_rotation'][0]['total'], 7)
        self.assertEqual(lists['flat_rotation'][0]['count'], 2)
        self.assertEqual(orientation_category([40, 50, 100], [50, 40, 100]), 'on_edge')
        self.assertEqual(orientation_category([100, 50, 50], [50, 50, 100]), 'other')
        self.assertEqual(orientation_category([100, 75, 75], [50, 100, 100]), 'other')

    def test_ten_proofs_over_period_keep_complete_counts_and_later_days(self):
        frames = dated_frames()[:1]
        for day in range(2):
            for index in range(12):
                line = len(frames) + 1
                frames.append(MachineState(line_num=line, timestamp=day*86400 + index + 1,
                    timestamp_str=f'23:00:{index+1:02d}', raw_lines=[(line, 'OMEGA:T5-DemVidageComplet')]))
        robot = next(group for group in build_report_payload(build_diagnostics(frames, [], trace_origin=datetime(2025, 12, 31, 23)), frames)['groups']
                     if group['code'] == 'DemVidageComplet')
        self.assertEqual(robot['occurrence_count'], 24)
        self.assertEqual([day['count'] for day in robot['daily']], [12, 12])
        self.assertEqual([day['example_count'] for day in robot['daily']], [5, 5])
        self.assertEqual(robot['examples'][5]['line'], 15)
        self.assertEqual(len(robot['examples']),10)

    def test_browser_sidebar_categories_days_navigation_pdf_and_legacy(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        frames = orientation_samples()
        payload = build_report_payload(build_diagnostics(frames, []), frames, 'DEMONSTRATION FICTIVE')
        dated = dated_frames()
        robot_payload = build_report_payload(build_diagnostics(dated, [], trace_origin=datetime(2025, 12, 31, 23)), dated)
        payload['source'] = robot_payload['source']
        robot = next(group for group in robot_payload['groups'] if group['code'] == 'DemVidageComplet')
        payload['groups'].append(robot)
        bridge = ReportBridge()
        output = ROOT / 'build' / 'report-restoration'
        output.mkdir(parents=True, exist_ok=True)
        try:
            with patch('Models.diagnostic_report.build_report_payload', return_value=payload):
                report = write_diagnostic_report([], output, frames)
                fallback = output / 'secours.html'
                fallback.write_text(build_diagnostic_report_html([], frames), encoding='utf-8')
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
                    for width in (1920, 1440, 1280, 850, 390):
                        page.set_viewport_size({'width': width, 'height': 1080})
                        sidebar = page.locator('.camera-sidebar')
                        self.assertTrue(sidebar.is_visible())
                        self.assertTrue(page.locator('.camera-panel').evaluate('(node)=>node.open'))
                        self.assertEqual(sidebar.locator('.camera-row').count(), 6)
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        if width >= 1360:
                            self.assertGreater(sidebar.bounding_box()['x'], page.locator('.priorities').bounding_box()['x'] + page.locator('.priorities').bounding_box()['width'])
                        else:
                            self.assertLess(sidebar.bounding_box()['y'], page.locator('[data-open=measurements]').bounding_box()['y'])
                    page.set_viewport_size({'width': 1920, 'height': 1080})
                    page.screenshot(path=str(output / ('react-large.png' if local else 'secours-large.png')))
                    self.assertEqual(page.locator('.orientation-category').count(), 3)
                    if local:
                        def open_preview():
                            command, done, result = bridge.commands.get(timeout=10)
                            result.update(ok=True, line=command['line'])
                            done.set()
                        preview_thread = threading.Thread(target=open_preview)
                        preview_thread.start()
                    page.locator('.orientation-preview [data-orientation-barcode]').first.click()
                    if local:
                        preview_thread.join(10)
                        page.get_by_role('status').filter(has_text='positionné').wait_for()
                    self.assertTrue(page.locator('[data-orientation-category=flat_rotation]').evaluate('(node)=>node.open'))
                    self.assertEqual(page.locator('[data-orientation-list=flat_rotation] .orientation-proofs > .sample').count(), 2)
                    card = page.locator(f'[data-group="{robot["id"]}"]')
                    card.locator(':scope > summary').click()
                    self.assertEqual(card.locator('.robot-zero-day').count(), 2)
                    card.locator('.robot-day > summary').click()
                    button = card.locator('.robot-day [data-navigate]').nth(1)
                    if local:
                        received = []
                        def navigate():
                            command, done, result = bridge.commands.get(timeout=10)
                            received.append(command)
                            result.update(ok=True, line=command['line'])
                            done.set()
                        thread = threading.Thread(target=navigate)
                        thread.start()
                        button.click()
                        page.get_by_role('status').filter(has_text='positionné').wait_for()
                        thread.join(10)
                        self.assertEqual(received[0]['line'], 3)
                    else:
                        self.assertTrue(button.is_disabled())
                    page.locator('[data-family]').select_option('robot')
                    self.assertTrue(page.locator('.robot-day').evaluate('(node)=>node.open'))
                    self.assertTrue(page.locator('.camera-panel').evaluate('(node)=>node.open'))
                    with page.expect_download() as download:
                        page.get_by_role('button', name='Exporter PDF').click()
                    pdf = output / 'restauration.pdf'
                    download.value.save_as(pdf)
                    document = pdfium.PdfDocument(pdf)
                    content = ' '.join(' '.join(p.get_textpage().get_text_range() for p in document).split())
                    for text in ('31/12/2025', '02/01/2026', '3 jours de trace', 'Synthèse terrain',
                                 'Longueur / largeur inversées', 'Orientations indécidables',
                                 'Cycles', 'Lecture des caméras'):
                        self.assertIn(text, content)
                    document.close()
                legacy = deepcopy(payload)
                legacy.pop('orientation_categories')
                legacy['orientation_references'] = {key: legacy['orientation_references'][key] for key in ('probable', 'uncertain')}
                old_robot = next(group for group in legacy['groups'] if group['code'] == 'DemVidageComplet')
                old_robot.pop('daily')
                old_robot.pop('trace_period')
                for key in ('daily', 'trace', 'requests_start', 'requests_end'):
                    old_robot['metrics'].pop(key, None)
                page.evaluate('(payload)=>{document.body.innerHTML="<div id=legacy></div>";TraceReport.mount(document.querySelector("#legacy"),payload)}', legacy)
                self.assertEqual(page.locator('[data-orientation-list=probable]').count(), 1)
                page.locator(f'[data-group="{robot["id"]}"] > summary').click()
                self.assertIn('Dates indisponibles', page.locator('.robot-days').inner_text())
                for ratio, band in ((0.07, 'is-good'), (0.075, 'is-good'), (0.08, 'is-warning'), (0.12, 'is-warning'), (0.121, 'is-bad')):
                    legacy['unknown'] = dict(legacy['unknown'], total=1000, count=int(ratio*1000), ratio=ratio, alert=ratio>0.07)
                    page.evaluate('(payload)=>TraceReport.mount(document.querySelector("#legacy"),payload)', legacy)
                    self.assertIn(band, page.locator('.unknown-counter').get_attribute('class'))
                    self.assertEqual(page.locator('.unknown-counter').bounding_box()['height'], 60)
                    self.assertEqual(page.locator('.unknown-alert').count(), 0)
                    self.assertEqual(page.locator('button.unknown-counter').count(), 0)
                self.assertFalse(errors, errors)
                browser.close()
        finally:
            bridge.close()

    @unittest.skipUnless(os.environ.get('TRACE_ALPHA_REFERENCE_TRACE'), 'Trace terrain facultative non fournie')
    def test_real_trace_invariants(self):
        from Parser.trace_parser import parse_file
        from Models.folder_report import _collect_events
        trace = os.environ['TRACE_ALPHA_REFERENCE_TRACE']
        frames = parse_file(trace, min_dt=0)
        payload = build_report_payload(build_diagnostics(frames, _collect_events(frames), trace_origin=read_trace_origin(trace)), frames)
        self.assertEqual(payload['source']['end'], '21/10/2026 à 08:57:35')
        self.assertEqual(payload['source']['duration'], '16 h 37 min 14 s')
        self.assertEqual((payload['unknown']['count'], payload['unknown']['total']), (80, 161))
        groups = {group['code']: group for group in payload['groups']}
        self.assertEqual(groups['REFERENCE_ABSENT']['occurrence_count'], 17)
        self.assertEqual([day['count'] for day in groups['DemVidageComplet']['daily']], [2, 0])
        self.assertEqual([sum(row['count'] for row in payload['orientation_references'][key])
                          for key in ('flat_rotation', 'on_edge', 'other', 'uncertain')], [0, 2, 0, 1])
        self.assertEqual([(row['camera'], row['success_count']) for row in payload['camera']['chart'][:2]], [('3', 51), ('6', 30)])


if __name__ == '__main__':
    unittest.main(verbosity=2)
