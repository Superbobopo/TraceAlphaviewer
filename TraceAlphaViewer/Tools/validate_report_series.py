"""Verifie les series bornees, les UNKNOWN et les preuves navigables du rapport."""
from pathlib import Path
import json
import pickle
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.state import MachineState
from Models.diagnostic import DiagnosticIncident, build_diagnostics, camera_report_stats
from Models.diagnostic_report import build_report_payload, write_diagnostic_report
from Models.frame_store import FrameStore, write_frame_store
from Models.measurement_analysis import analyze_measurements
from Models.report_bridge import ReportBridge


def camera_frames(total=100, unknown=8):
    frames = []
    def add(text):
        line = len(frames) + 1
        frames.append(MachineState(line_num=line, timestamp=line, timestamp_str=f'00:00:{line}',
                                   raw_lines=[(line, text)]))
    for index in range(total):
        reference = f'ALPHA-INC-{index}' if index < unknown else f'340{index:010d}'
        for reader in (1, 2):
            add(f'CB{reader}: ajout Hist_LectCB boite n°{index} 0code(s) lu(s)')
            add(f'idCB{reader}: --> Réf:{reference}')
            if reader == 1:
                add(f"tEA-T3: demande le transfert de EA->T3 '{reference}'")
        add(f'idCB2: (Nboite= {index + 1})')
        add(f"tT3/T4: demande le transfert de T3->T4 '{reference}'")
        if index < unknown:
            add(f"Création de la boite 'ALPHA-INC-{index}' -unknow")
    return frames


def repeated_frames(count):
    frames = [MachineState(line_num=i, timestamp=i, timestamp_str=f'00:{i}',
                          raw_lines=[(i, 'InitMachine: demande initialisation de T4 ...')])
              for i in range(1, count + 1)]
    incident = DiagnosticIncident(severity='error', title='T4', code='INIT-C6', belt='T4',
        first_line=1, last_line=count, start_time=1, end_time=count, start_time_str='00:01',
        end_time_str=f'00:{count}', count=count, summary=f'{count} demandes',
        event_lines=list(range(1, count + 1)))
    return frames, incident


class ReportSeriesTests(unittest.TestCase):
    def test_browser_counter_series_sources_and_pdf(self):
        from playwright.sync_api import sync_playwright
        from Models.diagnostic_report import build_diagnostic_report_html
        import pypdfium2 as pdfium
        frames = camera_frames(100,8)
        diagnostics = build_diagnostics(frames,[])
        series_frames, incident = repeated_frames(6188)
        # Les deux series fictives conservent des bornes distinctes.
        second = DiagnosticIncident(severity='error',title='T4',code='INIT-C6',belt='T4',
            first_line=6200,last_line=6201,count=2,event_lines=[6200,6201])
        diagnostics += [incident,second]
        output=ROOT/'build'/'report-series-validation'
        output.mkdir(parents=True,exist_ok=True)
        report=write_diagnostic_report(diagnostics,output,frames,source_name='DONNEES FICTIVES')
        fallback=output/'fallback.html'
        fallback.write_text(build_diagnostic_report_html(diagnostics,frames),encoding='utf-8')
        bridge=ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1100})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                for url in (bridge.register(report),fallback.as_uri()):
                    page.goto(url)
                    self.assertEqual(page.locator('[data-priority]').count(),3)
                    self.assertIn('8 / 100',page.locator('.unknown-counter').inner_text())
                    self.assertIn('8,0 %',page.locator('.unknown-counter').inner_text())
                    self.assertEqual(page.locator('.unknown-alert,#unknown-details,[data-unknown]').count(),0)
                    self.assertEqual(page.locator('.unknown-counter').get_attribute('role'),'group')
                    self.assertTrue(page.locator('.unknown-counter').evaluate("node=>node.classList.contains('is-warning')"))
                    group=page.locator('details[data-group]').filter(has=page.locator('.incident-series')).filter(has_text='6188 demandes').first
                    group.evaluate('(node)=>node.open=true')
                    series=group.locator('.incident-series')
                    self.assertEqual(series.count(),2)
                    self.assertEqual(group.locator('.incident-series .sample').count(),10)
                    self.assertEqual(series.nth(1).locator('.sample').count(),1)
                    self.assertIn('10 exemples présentés',group.inner_text())
                    if url.startswith('http:'):
                        series.first.evaluate('(node)=>node.open=true')
                        series.first.locator('.sample-technical').first.evaluate('(node)=>node.open=true')
                        link=series.first.locator('.trace-line').first
                        page.wait_for_function("!document.querySelector('.incident-series .trace-line').disabled")
                        received=[]
                        def receive():
                            target,done,result=bridge.commands.get(timeout=5)
                            received.append(target);result.update(ok=True,line=target['line']);done.set()
                        worker=threading.Thread(target=receive);worker.start()
                        link.focus();page.keyboard.press('Enter');worker.join(5)
                        self.assertEqual(len(received),1)
                        self.assertTrue(received[0]['source_line'])
                    else:
                        self.assertTrue(page.locator('.trace-line').first.is_disabled())
                    page.locator('.priorities').screenshot(path=str(output/'priorites.png'))
                    page.set_viewport_size({'width':390,'height':900})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    page.locator('.priorities').screenshot(path=str(output/'priorites-mobile.png'))
                    page.set_viewport_size({'width':1440,'height':1100})
                    with page.expect_download() as download:page.locator('[data-pdf]').click()
                    pdf=output/'report.pdf';download.value.save_as(pdf)
                    document=pdfium.PdfDocument(pdf)
                    content=' '.join(p.get_textpage().get_text_range() for p in document)
                    self.assertIn('UNKNOWN CB1+CB2',content)
                    self.assertIn('8 / 100',content)
                    document.close()
                self.assertFalse(errors,errors)
                browser.close()
        finally:bridge.close()

    def test_compact_unknown_counter_colors(self):
        from playwright.sync_api import sync_playwright
        payload = build_report_payload([], None)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge',headless=True)
            page = browser.new_page()
            page.set_content('<div id="preview"></div>')
            page.add_style_tag(path=str(ROOT/'TraceAlphaViewer/report_app/public/report-ui.css'))
            page.add_script_tag(path=str(ROOT/'TraceAlphaViewer/report_app/public/report-ui.js'))
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':1000})
                for count,total,tone in ((0,100,'good'),(799,10000,'good'),(8,100,'warning'),
                                         (12,100,'warning'),(1201,10000,'bad'),(0,0,'neutral')):
                    payload['unknown'].update(count=count,total=total,ratio=count/total if total else None)
                    page.evaluate('(data)=>TraceReport.mount(document.querySelector("#preview"),data)',payload)
                    counter=page.locator('.unknown-counter')
                    self.assertIn('is-'+tone,counter.get_attribute('class'))
                    self.assertEqual(counter.evaluate('node=>node.tagName'),'DIV')
                    self.assertIsNone(counter.get_attribute('tabindex'))
                    self.assertEqual(round(counter.bounding_box()['height']),60)
                    self.assertEqual(page.locator('.unknown-alert,#unknown-details,[data-unknown]').count(),0)
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    if not total:self.assertIn('Indisponible',counter.inner_text())
            browser.close()

    def test_series_counts_and_boundaries(self):
        for count in (2, 10, 11, 6188):
            with self.subTest(count=count):
                frames, incident = repeated_frames(count)
                payload = build_report_payload([incident], frames)
                group = payload['groups'][0]
                self.assertEqual(group['occurrence_count'], count)
                self.assertEqual(len(group['examples']), min(10, count))
                self.assertEqual(group['series'][0]['evidence_count'], count)
                self.assertEqual(len(incident.event_lines), count)
                expected = (list(range(1, count + 1)) if count <= 10
                            else [1 + round(i * (count - 1) / 9) for i in range(10)])
                self.assertEqual([s['line'] for s in group['examples']], expected)
        frames, incident = repeated_frames(20)
        second = DiagnosticIncident(severity='error', title='T4', code='INIT-C6', belt='T4',
            first_line=15, last_line=20, count=6, event_lines=list(range(15, 21)))
        incident.last_line=10; incident.count=10; incident.event_lines=list(range(1,11))
        group = build_report_payload([second, incident], frames)['groups'][0]
        self.assertEqual(len(group['series']), 2)
        self.assertEqual([s['first_line'] for s in group['series']], [1,15])
        self.assertEqual(group['occurrence_count'], 16)
        self.assertEqual(len(group['examples']),10)

    def test_unknown_thresholds_and_temporary_reads(self):
        self.assertIsNone(build_report_payload([], None)['unknown']['ratio'])
        for total,count,alert in ((0,0,False),(100,0,False),(100,7,False),(100,8,True),(100,11,True)):
            frames = camera_frames(total, count)
            output = {}
            diagnostics = build_diagnostics(frames, [], camera_report_output=output)
            direct = camera_report_stats(frames)
            self.assertEqual(output, direct)
            unknown = build_report_payload(diagnostics, frames)['unknown']
            self.assertEqual((unknown['count'],unknown['total'],unknown['alert']), (count,total,alert))
            self.assertEqual(len(unknown['examples']), min(count,10))
            self.assertEqual(unknown['ratio'], count/total if total else None)
        frames = camera_frames(2, 1)
        frames.append(MachineState(line_num=100, raw_lines=[(100,'idCB1: --> Réf:ALPHA-INC-temporary')]))
        stats = camera_report_stats(frames)
        self.assertEqual(stats['unknown']['count'],1)
        self.assertEqual(stats['unknown']['buckets']['CB1+CB2'],1)

    def test_indexed_context_equals_scan_and_old_session_fallback(self):
        frames, _ = repeated_frames(1500)
        frames[-1].raw_lines.append((1501,'derniere ligne du groupe'))
        incident = DiagnosticIncident(severity='error', title='T4', code='INIT-C6', belt='T4',
            first_line=1001,last_line=1501,count=2,event_lines=[1001,1501])
        expected = build_report_payload([incident], frames)
        expected.pop('generated_at')
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            directory = Path(directory)
            write_frame_store(frames,directory)
            with (directory/'measurements.pkl').open('wb') as output:
                pickle.dump(analyze_measurements(frames),output)
            with FrameStore(directory) as stored:
                actual = build_report_payload([incident],stored);actual.pop('generated_at')
                self.assertEqual(expected,actual)
            with (directory/'camera_report.pkl').open('wb') as output:
                pickle.dump(camera_report_stats(frames),output)
            class IndexedOnly(FrameStore):
                def __iter__(self):
                    raise AssertionError('Parcours integral interdit pour le rapport prepare')
            with IndexedOnly(directory) as stored:
                actual = build_report_payload([incident],stored);actual.pop('generated_at')
                self.assertEqual(expected,actual)
                targets = {row['navigation_id'] for group in actual['groups']
                           for sample in group['examples'] for row in sample['context']}
                self.assertIn('source:1501',targets)

    def test_registered_source_navigation_and_arbitrary_line_rejected(self):
        frames, incident = repeated_frames(11)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            path = write_diagnostic_report([incident],Path(directory),frames)
            bridge=ReportBridge()
            try:
                url=bridge.register(path)
                request_url=url.replace('view.html','navigate')
                received=[]
                def receive():
                    target,complete,result=bridge.commands.get(timeout=5)
                    received.append(target);result.update(ok=True,line=target['line']);complete.set()
                worker=threading.Thread(target=receive);worker.start()
                request=Request(request_url,data=json.dumps({'sample_id':'source:2'}).encode(),
                                headers={'Content-Type':'application/json','Origin':'http://'+bridge.address})
                with urlopen(request) as response:self.assertEqual(json.load(response)['line'],2)
                worker.join(5)
                self.assertTrue(received[0]['source_line'])
                self.assertNotIn('sample',received[0])
                for sample_id in ('source:99999','arbitrary'):
                    request=Request(request_url,data=json.dumps({'sample_id':sample_id,'line':2}).encode(),
                                    headers={'Content-Type':'application/json','Origin':'http://'+bridge.address})
                    with self.assertRaises(HTTPError) as failure:urlopen(request)
                    self.assertEqual(failure.exception.code,400)
                self.assertTrue(bridge.commands.empty())
            finally:bridge.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
