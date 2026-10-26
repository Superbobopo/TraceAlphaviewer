"""Valide les communications moteurs, modes camera et rejets de peremption."""
from pathlib import Path
from datetime import datetime
import os
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'TraceAlphaViewer'))
from Models.diagnostic import build_diagnostics, _camera_stats, _frame_line_states
from Models.identification_analysis import identification_cycles
from Models.trace_observations import analyze_motor_communication, analyze_code_modes, OBSERVATION_CODES
from Models.diagnostic_report import build_report_payload,write_diagnostic_report,build_diagnostic_report_html
from Tools.validate_c2_signal import frames_for

RETRY="envoi cde vers StepMotors pour le 2ème essai. cde:'IX'"
OK="Comm. OK sur StepMotors après le 2ème essai. cde:'IX'"
FAULT="DEFAUT de Comm. StepMotors sur cde:'IX'"
CONNECT='Connexion socket DEMO port 9762 StepMotors... .Ok'
MODE123='idCB1: demande prise photos puis décodages (codes autorisés:123 arrêt sur:1)'


def dp_rows(start=0,id_b=8,id_a=31191,recover=False,final=True,placeholder=False):
    rows=[(start,"CB1: ajout Hist_LectCB (lecture n°1 boite n°1 1code(s) lu(s))"),
          (start+1,'idCB1: --> Réf:3400927406980 lot: SN: DP:'),
          (start+2,"tEA-T3: demande le transfert de EA->T3 '3400927406980' FICTIF ..."),
          (start+3,'tEA-T3: le transfert (EA->T3) est terminé'),
          (start+4,'idCB2: Lance identification (car idCB1.Ref:3400927406980 [manque DP]) ...'),
          (start+4.5,'idCB2: demande prise photos puis décodages (codes autorisés:1)'),
          (start+5,'idCB2: on a recu PR<Soh>3<Dc2>3400927406980<Dc2>2<Dc2>0<Dc2>'),
          (start+6,'CB2: ajout Hist_LectCB (lecture n°1 boite n°1 1code(s) lu(s))'),
          (start+7,'idCB2: --> Réf:3400927406980 lot: SN: DP:'+('12/2099' if placeholder else '08/2027' if recover else '')),
          (start+8,f'idCB2: (Nboite= {id_b})'),
          (start+9,f'tT3/T4: transfert T3->T4 terminé, longueur=100 mm (idB={id_b})'),
          (start+10,"tT4*T5: Demande le transfert (physique) de la boite de T4 vers T5 '3400927406980' ..."),
          (start+11,f"BdD: Création de la boite 'ALPHA-INC-001' -unknow x=5012 (40x20x100) IdA:{id_a}"),
          (start+12,f"photoCamT5 'AjoutBtT5.idA{id_a}.idB{id_b}'")]
    if final:
        rows += [(start+13,f'boite n°{id_b} manque la DP 3400927406980 FICTIF'),
                 (start+14,f'Change réf dernière boite transférer (IdBdD:{id_a} IdT5:{id_a}) 3400927406980 -> ALPHA-INC-001[MqDP]')]
    return rows


def fixture():
    return ([(0,MODE123),(1,RETRY),(2,FAULT),(3,'Erreur winsock (StepMotors) n°10053 interruption'),
             (4,'-> port WINSOCK non ouvert (StepMotors), demande sa réouverture ...'),(5,CONNECT),
             (5.1,'InitMachine: demande initialisation de T0 ...'),(5.2,'InitMachine: demande initialisation de T5 ...')]
            +dp_rows(start=10)+[(40,MODE123.replace('CB1','CB2')),(41,MODE123.replace(':123',':1')),
                               (42,MODE123.replace('CB1','CB2').replace(':123',':1'))])


class ObservationTests(unittest.TestCase):
    def test_motor_retries_failures_reconnection_and_shutdown(self):
        def analyze(rows):return analyze_motor_communication(_frame_line_states(frames_for(rows)))
        self.assertEqual(analyze([(0,CONNECT),(1,'ferme TCPIP(0) StepMotors')]),[])
        episode=analyze([(0,RETRY),(120,OK)])[0]
        self.assertEqual((episode['severity'],episode['status'],episode['retry_count']),('info','recovered',1))
        episode=analyze([(0,RETRY),(121,OK)])[0]
        self.assertEqual(episode['status'],'unknown')
        self.assertEqual(episode['end_time'],0)
        episode=analyze([(0,RETRY),(1,OK.replace('IX','T5L'))])[0]
        self.assertEqual(episode['status'],'unknown')
        episodes=analyze(fixture())
        self.assertEqual(len(episodes),1)
        self.assertEqual((episodes[0]['severity'],episodes[0]['status'],episodes[0]['fault_count']),('error','reconnected',3))
        self.assertEqual(len(episodes[0]['initializations']),2)
        self.assertIn('à confirmer',episodes[0]['end_reason'])
        self.assertEqual(analyze([(0,'028-Avt: défaut communication carte moteurs')])[0]['severity'],'error')
        self.assertEqual(len(analyze([(0,FAULT),(121,FAULT)])),2)
        self.assertEqual(len(analyze([(0,FAULT),(1,'version logiciel VBalpha: 1'),(2,FAULT)])),2)

    def test_modes_periods_independent_readers_and_gaps(self):
        rows=[(0,MODE123),(1,MODE123),(2,MODE123.replace('CB1','CB2')),
              (3,MODE123.replace(':123',':1')),(4,MODE123.replace('CB1','CB2').replace(':123',':12'))]
        periods=analyze_code_modes(_frame_line_states(frames_for(rows)))
        self.assertEqual([(row['reader'],row['request_count']) for row in periods],[('CB1',2),('CB2',1)])
        for marker in ('version logiciel VBalpha: 1','ferme TCPIP(0) StepMotors'):
            periods=analyze_code_modes(_frame_line_states(frames_for([(0,MODE123),(1,marker),(2,MODE123)])))
            self.assertEqual(len(periods),2)
        self.assertEqual(len(analyze_code_modes(_frame_line_states(frames_for([(0,MODE123),(121,MODE123)])))),2)
        self.assertFalse(analyze_code_modes(_frame_line_states(frames_for([(0,MODE123.replace(':123',':1'))]))))

    def test_dp_confirmed_recovered_placeholder_and_unknown(self):
        for recover,final,placeholder,expected in ((False,True,False,(1,0)),(True,False,False,(0,1)),(False,False,True,(0,0))):
            frames=frames_for(dp_rows(recover=recover,final=final,placeholder=placeholder))
            stats=_camera_stats(_frame_line_states(frames))
            incidents=build_diagnostics(frames,[])
            dp=next((row for row in incidents if row.code=='DP_MISSING'),None)
            self.assertEqual((dp.metrics['confirmed_count'],dp.metrics['recovered_count']) if dp else (0,0),expected)
            self.assertEqual(len(stats['all_hist_boxes']),1)
            self.assertEqual(len(stats['created_unknown']),0 if final else 1)
            if final:
                self.assertEqual(dp.severity,'warning')
                self.assertIn('code brut limité au CIP',dp.examples[0]['sources'])
            if recover:
                payload=build_report_payload(incidents,frames)
                self.assertFalse(any(row['code']=='DP_MISSING' for row in payload['priority']))

    def test_reused_ids_ambiguity_and_merge(self):
        frames=frames_for(dp_rows()+dp_rows(start=30))
        cycles=identification_cycles(_frame_line_states(frames))
        self.assertEqual(len(cycles),2)
        dp=next(row for row in build_diagnostics(frames,[]) if row.code=='DP_MISSING')
        self.assertEqual(dp.metrics['confirmed_count'],2)
        frames=frames_for([(0,'boite n°8 manque la DP 3400927406980 FICTIF')])
        dp=next(row for row in build_diagnostics(frames,[]) if row.code=='DP_MISSING')
        self.assertEqual((dp.metrics['confirmed_count'],dp.metrics['unattributed_signal_count']),(0,1))
        self.assertEqual(dp.severity,'info')

    def test_group_boundaries_counts_and_provenance(self):
        from Tools.validate_folder_groups import FolderGroupsTests
        from Models.group_analysis import analyze_group
        from Models.frame_store import FrameStore
        helper=FolderGroupsTests();helper.setUp()
        try:
            sources=[]
            for index,rows in enumerate((fixture(),[(0,OK)]+dp_rows(start=5,final=False,recover=True))):
                sources.append(helper.source(f'observation-{index}',f'2026-10-{21+index}T09:00:00',
                    [text for _,text in rows],times=[seconds for seconds,_ in rows]))
            result=analyze_group(sources,helper.root/'combined')
            dp=next(row for row in result['diagnostics'] if row.code=='DP_MISSING')
            self.assertEqual((dp.metrics['confirmed_count'],dp.metrics['recovered_count']),(1,1))
            motor=next(row for row in result['diagnostics'] if row.code=='MOTOR_COMM')
            self.assertEqual(motor.metrics['recovered_episode_count'],0)
            with FrameStore(result['store']) as frames:
                groups=build_report_payload(result['diagnostics'],frames)['groups']
                for group in groups:
                    if group['code'] not in OBSERVATION_CODES:continue
                    for sample in group['examples']:
                        self.assertTrue(all(row['source_label'].split(' · ')[0]==sample['source_label'].split(' · ')[0] for row in sample['context']))
        finally:helper.tearDown()

    def test_available_local_sequences(self):
        from Parser.trace_parser import parse_file
        cases=[(ROOT/'TraceAlphaViewer/TracAlpha1_005.old',3735,3815,'motor'),
               (ROOT/'TraceAlphaViewer/TracAlpha1 - Domineuc.txt',47700,48280,'final'),
               (Path(os.environ.get('USERPROFILE',''))/'Desktop/trace alpha/TracAlpha1.txt',6200,6505,'recovery')]
        for source,first,last,kind in cases:
            if not source.is_file():continue
            with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
                target=Path(directory)/'extrait.old'
                with source.open(encoding='latin-1') as incoming,target.open('w',encoding='latin-1') as output:
                    for line,text in enumerate(incoming,1):
                        if line>last:break
                        if line>=first:output.write(text)
                frames=parse_file(str(target),min_dt=0.0)
                incidents=build_diagnostics(frames,[])
                if kind=='motor':
                    motor=next(row for row in incidents if row.code=='MOTOR_COMM')
                    self.assertEqual((motor.count,motor.severity),(1,'error'))
                    self.assertEqual(motor.metrics['reconnect_count'],1)
                    self.assertEqual({row['belt'] for row in motor.metrics['episodes'][0]['initializations']},set(('T0','T1','T2','T3','T4','T5')))
                else:
                    dp=next(row for row in incidents if row.code=='DP_MISSING')
                    self.assertEqual((dp.metrics['confirmed_count'],dp.metrics['recovered_count']),(1,0) if kind=='final' else (0,1))
                    if kind=='final':self.assertEqual(dp.examples[0]['barcode'],'3400927406980')

    def test_viewer_web_pdf_and_proofs(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        from Models.report_bridge import ReportBridge
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        frames=frames_for(fixture())
        incidents=build_diagnostics(frames,[])
        self.assertFalse(any(row.code=='028-Avt' for row in incidents))
        selected={row.code:row for row in incidents if row.code in OBSERVATION_CODES}
        self.assertEqual(set(selected),OBSERVATION_CODES)
        root=ctk.CTk();root.withdraw()
        try:
            panel=DiagnosticPanel(root,incidents,frames)
            for incident in selected.values():
                panel._show_details(incident)
                self.assertIn(incident.summary,panel._details.get('1.0','end'))
                line=next(iter(incident.examples[0]['sources'].values()))
                self.assertTrue(panel._details.tag_ranges(f'{incident.code.split("_",1)[0].lower()}-source-{line}'))
            panel.destroy()
        finally:
            for job in root.tk.call('after','info'):root.tk.call('after','cancel',job)
            root.destroy()
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            report=write_diagnostic_report(incidents,Path(directory),frames,source_name='DONNEES FICTIVES')
            fallback=Path(directory)/'fallback.html';fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
            bridge=ReportBridge()
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(channel='msedge',headless=True)
                    page=browser.new_page(viewport={'width':1440,'height':1000})
                    for url in (bridge.register(report),fallback.as_uri()):
                        page.goto(url)
                        badge=page.locator('.camera-panel > summary .camera-mode-alert')
                        self.assertEqual(badge.inner_text(),'⚠')
                        self.assertIn('123',badge.get_attribute('title'))
                        self.assertLess(page.locator('.camera-panel > summary').bounding_box()['height'],30)
                        for code in OBSERVATION_CODES:
                            detail=page.locator(f'details[data-group^="{code}:"]')
                            detail.locator('> summary').click()
                            for series in detail.locator('.incident-series').all():series.evaluate('(node)=>node.open=true')
                            self.assertTrue(detail.locator('.sample').count())
                        technical=page.locator('details[data-group^="DP_MISSING:"] .sample-technical').first
                        technical.evaluate('(node)=>node.open=true')
                        link=technical.locator('[data-source-navigate]').first
                        if url.startswith('http:'):
                            page.wait_for_function("!document.querySelector('[data-source-navigate]').disabled")
                            targets=[]
                            def receive():
                                target,done,result=bridge.commands.get(timeout=5)
                                targets.append(target);result.update(ok=True,line=target['line']);done.set()
                            worker=threading.Thread(target=receive);worker.start();link.click();worker.join(5)
                            self.assertTrue(targets[0]['source_line'])
                        else:self.assertTrue(link.is_disabled())
                        page.set_viewport_size({'width':390,'height':900})
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                        with page.expect_download() as download:page.locator('[data-pdf]').click()
                        path=Path(directory)/'rapport.pdf';download.value.save_as(path)
                        pdf=pdfium.PdfDocument(path)
                        text='\n'.join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
                        for expected in ('Communication moteurs','Péremption absente','mode 123','reconnecté','CIP'):
                            self.assertIn(expected,text)
                        pdf.close()
                        page.set_viewport_size({'width':1440,'height':1000})
                    clean=Path(directory)/'sans-mode-123.html'
                    clean.write_text(build_diagnostic_report_html(
                        [row for row in incidents if row.code!='CAMERA_CODE_MODE'],frames),encoding='utf-8')
                    page.goto(clean.as_uri())
                    self.assertEqual(page.locator('.camera-mode-alert').count(),0)
                    browser.close()
            finally:bridge.close()


if __name__=='__main__':unittest.main(verbosity=2)
