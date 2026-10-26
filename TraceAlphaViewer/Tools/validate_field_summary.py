"""Verifie les cartes groupees et le PDF terrain sans avalanche de preuves."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'TraceAlphaViewer'))
from Models.diagnostic import DiagnosticIncident, build_diagnostics, _build_t4_diff_incidents
from Models.diagnostic_summary import normalize_summary_incidents
from Models.diagnostic_report import build_report_payload, build_diagnostic_report_html, write_diagnostic_report
from Models.state import MachineEvent
from Tools.validate_motor_dp import frames_for, RETRY, OK, FAULT, CONNECT, fixture
from Tools.validate_measurement_report import product_samples


def t4_incidents():
    result=[]
    for index in range(16):
        events=[MachineEvent(line_num=index*100+offset, timestamp=index*86400+offset,
            timestamp_str=f'{index+1:02d}|09:00:{offset:02d}', severity='warning', kind='T4',
            title=f'Controle longueur T4 diff {delta}mm', detail=f'BdD:100 T4C:{100+delta} T4T:100')
            for offset,delta in enumerate((10,11+index,-20-index),1)]
        row=_build_t4_diff_incidents(events)[0]
        row.metrics['source_segment']=index
        result.append(row)
    return result


def summary_payload():
    frames=product_samples([('DEMO-A',[-4]*12+[0]*28),('DEMO-B',[8]*15+[0]*25),('DEMO-C',[2]*40)])
    incidents=build_diagnostics(frames,[])+build_diagnostics(frames_for(fixture()),[])+t4_incidents()
    for index in range(5):
        incidents.append(DiagnosticIncident('warning',f'Contrôle complémentaire fictif {index}',
            'T5',f'FICTIF-{index}',count=index+1,summary='Événement observé, cause à confirmer.',
            symptom='Un cycle nécessite un contrôle terrain.',checks=['Vérifier le passage physique.']))
    payload=build_report_payload(normalize_summary_incidents(incidents,16),frames,source_name='DOSSIER FICTIF — 16 TRACES')
    payload['source'].update(identity={'pharmacy':'Démonstration','alpha_number':'031',
        'alpha_database':'BASEALPHA_#2026.031.MDB','pharmacy_database':'BASEFICDEMO.MDB'},
        files=[{'name':f'fictif-{index}.old'} for index in range(16)],
        dates_available=True,start='01/10/2026 à 09:00:00',end='16/10/2026 à 18:00:00',duration='144 h observées')
    return frames,payload


class FieldSummaryTests(unittest.TestCase):
    def test_available_lahlou_segments(self):
        from Models.folder_catalog import scan_source
        from Models.folder_report import _collect_events
        from Models.frame_store import FrameStore, write_frame_store_iter
        from Models.group_analysis import analyze_group
        from Parser.trace_parser import parse_file
        paths=[Path.home()/'Desktop/trace alpha'/f'TracAlpha1_{index:03d}.old' for index in range(16,20)]
        if not all(path.exists() for path in paths):
            self.skipTest('Les quatre traces Lahlou locales ne sont pas disponibles')
        expected=[]
        with tempfile.TemporaryDirectory(dir=ROOT/'build',prefix='lahlou-summary-') as temporary:
            sources=[]
            for index,path in enumerate(paths):
                source=scan_source(path)
                frames=parse_file(str(path),min_dt=0.0)
                expected.extend(_build_t4_diff_incidents(_collect_events(frames)))
                store=Path(temporary)/f'source-{index}'
                write_frame_store_iter(iter(frames),store)
                source['store']=str(store)
                sources.append(source)
                del frames
            grouped=analyze_group(sources,Path(temporary)/'group')
            rows=[row for row in grouped['diagnostics'] if row.code=='diffT4']
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0].count,sum(row.count for row in expected))
            self.assertEqual(rows[0].metrics['max_abs_diff_mm'],max(row.metrics['max_abs_diff_mm'] for row in expected))
            with FrameStore(grouped['store']) as store:
                payload=build_report_payload(grouped['diagnostics'],store)
                t4=next(row for row in payload['groups'] if row['code']=='diffT4')
                self.assertEqual(t4['metrics']['analyzed_files'],4)
                for sample in t4['examples']:
                    location=store.source_location(sample['line'])
                    self.assertIn(location['name'],sample['source_label'])
                output=ROOT/'build/lahlou-field-summary'
                write_diagnostic_report(grouped['diagnostics'],output,store)

    def test_t4_grouping_threshold_and_compatibility(self):
        originals=t4_incidents()
        before=deepcopy(originals)
        grouped=normalize_summary_incidents(originals,16)
        self.assertEqual(originals,before)
        self.assertEqual(len(grouped),1)
        row=grouped[0]
        self.assertEqual((row.count,row.metrics['max_abs_diff_mm']),(32,35))
        self.assertEqual((row.metrics['affected_files'],row.metrics['analyzed_files']),(16,16))
        self.assertEqual(len(row.metrics['segments']),16)
        self.assertEqual(normalize_summary_incidents(grouped),grouped)
        report=build_report_payload(grouped,[])
        self.assertEqual(len(report['groups']),1)
        self.assertLessEqual(len(report['groups'][0]['series']),10)
        self.assertEqual(report['groups'][0]['occurrence_count'],32)
        legacy=DiagnosticIncident('warning','T4 ancien max 59mm','T4','diffT4',count=12)
        self.assertIn('maximum indisponible',normalize_summary_incidents([legacy])[0].summary)

    def test_only_critical_motors_visible(self):
        info=build_diagnostics(frames_for([(0,RETRY),(1,OK),(2,RETRY)]),[])
        self.assertFalse(any(row.code=='MOTOR_COMM' for row in info))
        frames=frames_for([(0,RETRY),(1,OK),(10,FAULT),(11,CONNECT),(20,RETRY),(21,OK)])
        row=next(row for row in build_diagnostics(frames,[]) if row.code=='MOTOR_COMM')
        self.assertEqual((row.count,row.first_line,row.last_line),(1,3,4))
        self.assertEqual(row.metrics['recovered_episode_count'],0)
        self.assertEqual(row.metrics['reconnected_episode_count'],1)
        self.assertEqual(len(row.metrics['episodes']),1)
        self.assertFalse(row.metrics['episodes'][0]['belts'])
        self.assertEqual(row.metrics['episodes'][0]['common_commands'],['IX'])

    def test_viewer_t4_details_are_folded_and_navigable(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        app=ctk.CTk();app.withdraw()
        try:
            targets=[]
            panel=DiagnosticPanel(app,normalize_summary_incidents(t4_incidents(),16),[],
                                  on_measurement_click=targets.append)
            self.assertEqual(len(panel._incidents),1)
            panel._show_details(panel._incidents[0])
            self.assertIn('32 contrôles',panel._details.get('1.0','end'))
            self.assertTrue(int(panel._details.tag_cget('t4-segment-0','elide')))
            self.assertTrue(panel._details.tag_ranges('t4-source-2'))
            panel.destroy()
        finally:
            for job in app.tk.call('after','info'):app.tk.call('after','cancel',job)
            app.destroy()

    def test_web_and_pdf_are_concise(self):
        import pypdfium2 as pdfium
        from playwright.sync_api import sync_playwright
        frames,payload=summary_payload()
        output=ROOT/'build/field-summary-validation';output.mkdir(parents=True,exist_ok=True)
        with patch('Models.diagnostic_report.build_report_payload',return_value=payload):
            report=write_diagnostic_report([],output,frames)
            fallback=output/'fallback.html';fallback.write_text(build_diagnostic_report_html([],frames),encoding='utf-8')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            for path in (report,fallback):
                page.goto(path.as_uri())
                t4=page.locator('details[data-group^="diffT4:"]')
                self.assertEqual(t4.count(),1)
                self.assertIsNone(t4.get_attribute('open'))
                t4.locator('>summary').click()
                self.assertLessEqual(t4.locator('.incident-series').count(),10)
                self.assertIn('10 exemples présentés',t4.inner_text())
                self.assertEqual(t4.locator('.incident-series[open]').count(),0)
                for width in (1440,390):
                    page.set_viewport_size({'width':width,'height':1000})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                blocks=page.evaluate('TraceReport.pdfLines('+__import__('json').dumps(payload)+')')
                self.assertLessEqual(sum(len(row['rows']) for row in blocks if row['kind']=='examples'),3)
                with page.expect_download() as download:page.locator('[data-pdf]').click()
                target=output/'synthese.pdf';download.value.save_as(target)
                pdf=pdfium.PdfDocument(target)
                self.assertGreaterEqual(len(pdf),4)
                self.assertLessEqual(len(pdf),5)
                content='\n'.join(pdf[index].get_textpage().get_text_range() for index in range(len(pdf)))
                for expected in ('32 contrôles','35 mm','16 fichier','Communication moteurs','Mesures et présentation'):
                    self.assertIn(expected,content)
                self.assertNotIn('DEFAUT de Comm.',content)
                for group in payload['groups']:
                    if group['field_severity'] in {'warning','error'}:
                        self.assertIn(group['title'].replace('—','-'),content)
                for index in range(len(pdf)):
                    pdf[index].render(scale=1.4).to_pil().save(output/f'page-{index+1}.png')
                pdf.close()
            overloaded=deepcopy(payload)
            base=next(group for group in payload['groups'] if group['code']=='FICTIF-0')
            for index in range(24):
                overloaded['groups'].append(dict(base,id=f'charge-{index}',title=f'ALERTE CHARGE {index:02d}',
                    symptom='Observation longue pour vérifier les retours à la ligne et la pagination sans perdre un problème.'))
            raw=page.evaluate('(data)=>Array.from(TraceReport.buildPdf(data))',overloaded)
            target=output/'synthese-chargee.pdf';target.write_bytes(bytes(raw))
            pdf=pdfium.PdfDocument(target)
            try:
                content='\n'.join(pdf[index].get_textpage().get_text_range() for index in range(len(pdf)))
                for index in range(24):self.assertIn(f'ALERTE CHARGE {index:02d}',content)
                self.assertGreater(len(pdf),5)
                for index in range(len(pdf)):
                    textpage=pdf[index].get_textpage()
                    for char in range(textpage.count_chars()):
                        left,bottom,right,top=textpage.get_charbox(char)
                        if right>left and top>bottom:
                            self.assertGreaterEqual(left,35)
                            self.assertLessEqual(right,561)
                            self.assertGreaterEqual(bottom,20)
            finally:pdf.close()
            self.assertFalse(errors,errors)
            browser.close()


if __name__=='__main__':unittest.main(verbosity=2)
