"""Valide les frequences robot, leur priorite et les alertes viewer/web/PDF."""
from pathlib import Path
import sys
import threading
import tempfile
import unittest
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.state import MachineState
from Models.diagnostic import build_diagnostics, DiagnosticIncident, _build_text_pattern_incidents
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Models.robot_drain import drain_metrics, t5_priority_score, read_trace_origin, TraceCalendar

ORIGIN = datetime(2026, 2, 13)


def frames_for(times):
    return [MachineState(line_num=i, timestamp=t, timestamp_str=f'{int(t)//86400+1:02d}|{int(t)%86400//3600:02d}:{int(t)%3600//60:02d}:{int(t)%60:02d}',
            raw_lines=[(i, 'UDP trame recu du robot: @T1@OMEGA:T5-DemVidageComplet')])
            for i, t in enumerate(times, 1)]


def stale_incident():
    return DiagnosticIncident(severity='error', title='Boite non mesuree bloquante', belt='T5',
        code='T5_STALE_UNMEASURED_BOX', count=3, first_line=1, last_line=3, event_lines=[1, 2, 3])


class RobotDrainTests(unittest.TestCase):
    def test_calendar_rollovers_empty_days_and_daily_limits(self):
        for origin in (datetime(2026,1,31,23,30),datetime(2026,12,31,23,30),datetime(2024,2,28,23,30)):
            dates = [origin] + [origin + timedelta(minutes=15+i) for i in range(16)]
            dates += [origin+timedelta(days=2,hours=1),origin+timedelta(days=4)]
            frames = []
            for i,date in enumerate(dates):
                raw_delta = ((date.day-origin.day)*86400
                    +(date-date.replace(hour=0,minute=0,second=0,microsecond=0)).total_seconds()
                    -(origin-origin.replace(hour=0,minute=0,second=0,microsecond=0)).total_seconds())
                text = 'Fin' if i in (0,len(dates)-1) else 'OMEGA:T5-DemVidageComplet'
                frames.append(MachineState(line_num=i+1,timestamp=raw_delta,timestamp_str=date.strftime('%H:%M:%S'),raw_lines=[(i+1,text)]))
            robot = next(item for item in build_diagnostics(frames,[],trace_origin=origin) if item.code=='DemVidageComplet')
            metrics = robot.metrics
            self.assertEqual(metrics['trace']['days'],5)
            self.assertEqual(len(metrics['daily']),5)
            self.assertEqual(sum(row['count'] for row in metrics['daily']),17)
            self.assertEqual(metrics['trace']['end'],dates[-1].strftime('%d/%m/%Y à %H:%M:%S'))
            self.assertTrue(any(row['count']==0 for row in metrics['daily']))
            self.assertTrue(all(len(row['examples'])<=10 for row in metrics['daily']))
            expected = drain_metrics([(i,(date-origin).total_seconds(),'') for i,date in enumerate(dates[1:-1])])
            self.assertEqual((metrics['hour']['count'],metrics['day']['count'],metrics['reinforced']),
                             (expected['hour']['count'],expected['day']['count'],expected['reinforced']))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.old'
            path.write_text('creation de la trace à 23:30:00 le 31/12/2026\n* 31|23:30:00.7 OUVERTURE DE LA TRACE le 31/12/2026\n',encoding='latin-1')
            self.assertEqual(read_trace_origin(path),datetime(2026,12,31,23,30,0,700000))
            path.write_text('31|23:30:00.7 OMEGA:T5-DemVidageComplet\n',encoding='latin-1')
            self.assertIsNone(read_trace_origin(path))
        frames=frames_for([0,600])
        robot=next(item for item in build_diagnostics(frames,[]) if item.code=='DemVidageComplet')
        payload=build_report_payload([robot],frames)
        self.assertIn('Dates indisponibles',payload['groups'][0]['summary'])
        self.assertNotIn('Critique :',payload['groups'][0]['summary'])

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

    def test_worker_date_metadata_reaches_report(self):
        from Models.loading_worker import run
        from Models.frame_store import FrameStore
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fictive.old'
            path.write_text('creation de la trace le 13/02/2026\n'
                '* 13|09:00:00.2 OUVERTURE DE LA TRACE le 13/02/2026\n'
                '13|09:10:00.2 OMEGA:T5-DemVidageComplet\n'
                '13|09:20:00.2 OMEGA:T5-DemVidageComplet\n'
                '15|12:00:00.2 Fin\n',encoding='latin-1')
            messages=[]
            run({'mode':'file','path':str(path),'session':str(Path(directory)/'session')},
                lambda kind,data:messages.append((kind,data)))
            entry=next(data for kind,data in messages if kind=='entry')
            incidents=[item for kind,data in messages if kind=='diagnostics' for item in data]
            with FrameStore(entry['store']) as frames:
                group=next(row for row in build_report_payload(incidents,frames)['groups'] if row['code']=='DemVidageComplet')
            self.assertEqual(group['summary'],'2 demandes sur 3 jours de trace')
            self.assertIn('13/02/2026',group['trace_period'])
            self.assertIn('15/02/2026',group['trace_period'])
            self.assertEqual([day['count'] for day in group['daily']],[2,0,0])

    def test_detection_and_priority(self):
        for count in (1, 5, 6, 9, 10, 11, 15):
            frames = frames_for([i * 7200 for i in range(count)] if count < 15 else [i * 6000 for i in range(15)])
            frames[0].raw_lines += [(100, 'T5v: Une demande de vidage complet de T5 est demandee'),
                                    (101, '118-Vide T5 suite blocage poubelle'),
                                    (102, 'Robot prend IdA=1')]
            incidents = build_diagnostics(frames, [], trace_origin=ORIGIN)
            robot = next(item for item in incidents if item.code == 'DemVidageComplet')
            self.assertEqual(robot.count, count)
            self.assertEqual(robot.severity, 'info' if count < 10 else 'error')
            payload = build_report_payload(incidents + [stale_incident()], frames)
            group = next(item for item in payload['groups'] if item['code'] == robot.code)
            self.assertEqual(group['family'], 'robot')
            self.assertTrue(all(day['example_count'] <= 10 for day in group['daily']))
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
        origin = read_trace_origin(trace)
        self.assertEqual(origin, datetime(2026,10,11,22,51,0,600000))
        selected_frames = []
        first = last = None
        counts = {}
        with trace.open(encoding='latin-1') as source:
            for line, text in enumerate(source, 1):
                match = re.match(r'\s*\*?\s*(\d+)\|(\d+):(\d+):(\d+)\.(\d+)', text)
                if not match:
                    continue
                d, h, m, s, ds = map(int, match.groups())
                date = origin.replace(day=d, hour=h, minute=m, second=s, microsecond=ds*100000)
                state = MachineState(timestamp=(date-origin).total_seconds(),
                                     timestamp_str=match[0], line_num=line, raw_lines=[(line, text.rstrip())])
                if first is None:first = state
                last = state
                if 'OMEGA:T5-DemVidageComplet' in text:
                    selected_frames.append(state)
                    counts[date.date().isoformat()] = counts.get(date.date().isoformat(),0) + 1
        frames = [first] + selected_frames + [last]
        robot = next(item for item in build_diagnostics(frames, [], trace_origin=origin) if item.code == 'DemVidageComplet')
        self.assertEqual(robot.count, 58)
        self.assertEqual(robot.metrics['trace']['days'],5)
        self.assertEqual({day['date']:day['count'] for day in robot.metrics['daily'] if day['count']},counts)
        self.assertEqual(sum(day['count'] for day in robot.metrics['daily']),58)
        payload = build_report_payload([robot], frames)
        group = payload['groups'][0]
        self.assertEqual(group['occurrence_count'], 58)
        self.assertEqual(payload['source']['start'],'11/10/2026 à 22:51:00')
        self.assertEqual(payload['source']['end'],'15/10/2026 à 14:21:52')
        self.assertEqual(payload['source']['duration'],'87 h 30 min 51 s')
        self.assertEqual(len(group['examples']),min(10,sum(min(count,10) for count in counts.values())))
        from Parser.trace_parser import parse_file
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / 'commandes.old'
            selected.write_text('\n'.join(frame.raw_lines[0][1] for frame in frames), encoding='latin-1')
            parsed = parse_file(str(selected), min_dt=0.0)
            parsed_robot = next(item for item in build_diagnostics(parsed, [], trace_origin=read_trace_origin(selected)) if item.code == robot.code)
            self.assertEqual(parsed_robot.count, 58)
            for window in ('hour', 'day'):
                self.assertEqual(parsed_robot.metrics[window]['count'], robot.metrics[window]['count'])
        print(f"Loire : {robot.summary} ; {robot.metrics['trace']} ; repartition {counts}", flush=True)

    def test_viewer_alert_and_order(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        root = ctk.CTk(); root.withdraw()
        try:
            for count in (1, 5, 6, 9, 10):
                frames = frames_for([i * 7200 for i in range(count)])
                incidents = build_diagnostics(frames, [], trace_origin=ORIGIN) + [stale_incident()]
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
                self.assertIn('13 février 2026', panel._details.get('1.0', 'end'))
                self.assertEqual(panel._details.tag_cget('robot-day-0','elide'),'1')
                panel._details.tk.call(panel._measurement_bindings['robot-day-0-header'],
                                       *(['0'] * len(panel._details._subst_format)))
                self.assertEqual(panel._details.tag_cget('robot-day-0','elide'),'0')
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
        frames = frames_for([i * 5000 for i in range(16)]+[2*86400,2*86400+300,4*86400])
        frames[-1].raw_lines=[(frames[-1].line_num,'Fin de trace')]
        incidents = build_diagnostics(frames, [], trace_origin=ORIGIN) + [stale_incident()]
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
                    self.assertEqual(page.locator('.robot-drain-alert').count(),0)
                    alert = page.locator('.priority-grid [data-priority^="DemVidageComplet:"]')
                    self.assertTrue(alert.is_visible())
                    self.assertIn('critique', alert.inner_text().lower())
                    self.assertIn('18', alert.inner_text())
                    alert.focus(); page.keyboard.press('Enter')
                    detail = page.locator('details[data-group^="DemVidageComplet:"]')
                    self.assertTrue(detail.evaluate('(node)=>node.open'))
                    self.assertEqual(detail.locator(':scope > summary > div').count(), 1)
                    summary = detail.locator(':scope > summary')
                    title = summary.locator('h3').bounding_box()
                    badges = summary.locator('.badges').bounding_box()
                    total = summary.locator('.robot-total').bounding_box()
                    self.assertAlmostEqual(title['x'], badges['x'], delta=1)
                    self.assertGreaterEqual(total['y'], title['y'] + title['height'])
                    self.assertIn('18 demandes sur 5 jours',alert.inner_text())
                    self.assertNotIn('13/02/2026',alert.inner_text())
                    self.assertIn('13/02/2026',detail.inner_text())
                    self.assertNotIn('sur 24 h',alert.inner_text())
                    self.assertEqual(detail.locator('.robot-day').count(),2)
                    self.assertEqual(detail.locator('.robot-zero-day').count(),3)
                    self.assertEqual(detail.locator('.robot-day .sample').count(),10)
                    self.assertIn('13 février 2026', detail.locator('.robot-day > summary').first.inner_text())
                    detail.locator('.robot-day > summary').first.click()
                    self.assertIn('10 exemples présentés',detail.inner_text())
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
                    self.assertIn('T5 - Vidage complet demande', ' '.join(text.split()))
                    self.assertIn('13/02/2026',text)
                    self.assertIn('18 demandes sur 5 jours',text)
                    self.assertNotIn('13 février',text)
                    self.assertNotIn('Pic sur 24 h',text)
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
