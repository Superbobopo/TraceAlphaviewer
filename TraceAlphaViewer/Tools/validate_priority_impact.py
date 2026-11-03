"""Verifie le classement commun selon les blocages observes."""
from dataclasses import replace
from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'TraceAlphaViewer'))
from Models.diagnostic import DiagnosticIncident, build_diagnostics
from Models.diagnostic_report import build_report_payload, _group_incidents, write_diagnostic_report
from Models.priority_impact import prepare_impact, order_impact
from Tools.validate_c5_signal import fixture, frames_for, cycle


def stale(line=100, start=0, end=250, identity=32094, count=21, segment=0):
    return DiagnosticIncident('error', 'T5 - Boite non mesuree bloquante', 'T5', 'T5_STALE_UNMEASURED_BOX',
        first_line=line, last_line=line+10, start_time=start, end_time=end, count=count,
        metrics={'priority_impact_version':1,'source_segment':segment,'blocked_cycle':{
            'id_alpha':identity,'first_line':line,'start_time':start,'end_time':end}})


def c5(count=15, episodes=1, duration=600):
    return DiagnosticIncident('error','Capteur C5 — signal anormal','T3','C5_SIGNAL_ANOMALY',first_line=300,
        metrics={'c5_metrics_version':2,'blocked_transfer_count':episodes,'blocked_duration_seconds':duration*episodes,'suspect_cycle_count':count,'episode_count':episodes,
                 'transitions':3476,'virtual_creation_count':2,'incomplete_cycle_count':0,
                 'episodes':[{'kind':'blocked_transfer','first_line':300+i,'start_time':i*(duration+1),'end_time':i*(duration+1)+duration}
                             for i in range(episodes)]})


class ImpactTests(unittest.TestCase):
    def test_duration_precedes_punctual_counts_and_cycles(self):
        punctual=replace(stale(),belt='T3',code='-43',metrics={},count=100000)
        for incidents,expected in (([punctual,c5()], 'C5_SIGNAL_ANOMALY'),
                ([stale(),c5(duration=121)],'T5_STALE_UNMEASURED_BOX'),
                ([stale(),c5(duration=251)],'C5_SIGNAL_ANOMALY'),
                ([punctual,replace(c5(),severity='warning')],'-43')):
            self.assertEqual(order_impact(_group_incidents(incidents))[0]['code'],expected)
        signal=replace(c5(),metrics=dict(c5().metrics,blocked_transfer_count=0,
            episodes=[{'kind':'signal','start_time':0,'end_time':999999}]))
        self.assertEqual(prepare_impact([signal])['duration_seconds'],0)
        self.assertFalse(prepare_impact([signal])['blocking'])
        self.assertFalse(prepare_impact([c5(episodes=2,duration=60)])['blocking'])
        self.assertTrue(prepare_impact([c5(duration=120)])['blocking'])
        legacy=replace(c5(),metrics=dict(c5().metrics,c5_metrics_version=1))
        self.assertFalse(prepare_impact([legacy])['available'])
        tied=order_impact(_group_incidents([stale(),c5(episodes=2,duration=125)]))
        self.assertEqual(tied[0]['code'],'C5_SIGNAL_ANOMALY')

    def test_overlaps_reused_ids_segments_and_legacy(self):
        result=prepare_impact([stale(),stale(line=120,start=100,end=300),stale()])
        self.assertEqual((result['cycles'],result['episodes'],result['duration_seconds']),(2,1,300))
        result=prepare_impact([stale(),stale(line=120,start=250,end=300)])
        self.assertEqual((result['cycles'],result['episodes'],result['duration_seconds']),(2,2,300))
        result=prepare_impact([stale(),stale(segment=1)])
        self.assertEqual((result['cycles'],result['episodes'],result['duration_seconds']),(2,2,500))
        separated=replace(c5(episodes=2),metrics=dict(c5(episodes=2).metrics,episodes=[
            {'kind':'blocked_transfer','first_line':10,'context':0,'start_time':0,'end_time':250},
            {'kind':'blocked_transfer','first_line':20,'context':1,'start_time':100,'end_time':300}]))
        self.assertEqual(prepare_impact([separated])['duration_seconds'],450)
        legacy=replace(stale(),metrics={})
        groups=_group_incidents([legacy,c5()])
        self.assertEqual(order_impact(groups)[0]['code'],'C5_SIGNAL_ANOMALY')
        self.assertFalse(groups[0]['priority_impact']['available'])
        payload=build_report_payload([legacy,replace(c5(),metrics={})],[])
        self.assertTrue(all(not row['priority_impact']['available'] for row in payload['groups']))
        self.assertTrue(all('régénérer' in row['field_explanation'] for row in payload['groups']))

    def test_t5_reused_creation_is_a_distinct_cycle(self):
        from Models.diagnostic import _build_stale_unmeasured_t5_incidents, _frame_line_states
        rows=[]
        for start in (0,300):
            rows += [(start,"BdD: Création de la boite 'CIP' FICTIF x=5012 (0x0x20) IdA:42"),
                     (start+1,'MAJ (BUTEE-T5) boite Id:42 ref:CIP (nvlle dim:0x0 X:5289)'),
                     (start+125,'T5: pas assez de place'),
                     (start+126,'- supp. de T5 la boite Id:42 ref:CIP')]
        incidents=_build_stale_unmeasured_t5_incidents(_frame_line_states(frames_for(rows)))
        self.assertEqual(len(incidents),2)
        impact=prepare_impact(incidents)
        self.assertEqual((impact['cycles'],impact['episodes']),(2,2))

    def test_actual_trace(self):
        from Parser.trace_parser import parse_file
        path=Path(os.environ.get('USERPROFILE',''))/'Desktop/trace alpha/tracalpha1.txt'
        if not path.is_file():self.skipTest('Trace terrain absente')
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            paths=[Path(directory)/'t5.old',Path(directory)/'c5.old']
            with path.open(encoding='latin-1') as source, paths[0].open('w',encoding='latin-1') as a, paths[1].open('w',encoding='latin-1') as b:
                for line,text in enumerate(source,1):
                    if 515700<=line<=516250:a.write(text)
                    if 621200<=line<=651000:b.write(text)
                    if line>651000:break
            selected=[]
            for source,code in zip(paths,('T5_STALE_UNMEASURED_BOX','C5_SIGNAL_ANOMALY')):
                frames=parse_file(str(source),min_dt=0.0)
                selected.extend(row for row in build_diagnostics(frames,[]) if row.code==code)
            groups=order_impact(_group_incidents(selected))
            self.assertEqual(groups[0]['code'],'C5_SIGNAL_ANOMALY')
            self.assertEqual(groups[0]['metrics']['suspect_cycle_count'],15)
            self.assertEqual(groups[0]['metrics']['blocked_transfer_count'],2)
            self.assertEqual(groups[0]['priority_impact']['cycles'],2)
            t5=next(row for row in groups if row['code']=='T5_STALE_UNMEASURED_BOX')
            self.assertEqual(t5['priority_impact']['cycles'],1)
            self.assertEqual(t5['occurrence_count'],21)

    def test_viewer_web_pdf(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        frames=frames_for(fixture()+sum((cycle(start=40+i*10,id_b=300+i,id_a=400+i) for i in range(14)),[]))
        blocked=c5(duration=154373)
        import json
        local=ROOT/'TraceAlphaViewer/.trace_work/astier-validation-changes.json'
        if local.is_file():
            actual=json.loads(local.read_text(encoding='utf-8'))
            blocked=replace(blocked,metrics=dict(actual['c5_metrics'],episodes=actual['blocks']))
        punctual=replace(stale(),belt='T3',code='-43',title='T3 eT:-43 - Err: boite coincee',
                         metrics={},count=2,first_line=46525,last_line=439107,end_time=35108)
        incidents=build_diagnostics(frames,[])+[stale(),blocked,punctual]
        payload=build_report_payload(incidents,frames)
        codes=[row['code'] for row in payload['priority']]
        self.assertLess(codes.index('C5_SIGNAL_ANOMALY'),codes.index('T5_STALE_UNMEASURED_BOX'))
        self.assertLess(codes.index('C5_SIGNAL_ANOMALY'),codes.index('-43'))
        self.assertEqual(payload['groups'][0]['code'],'C5_SIGNAL_ANOMALY')
        root=ctk.CTk();root.withdraw()
        try:
            panel=DiagnosticPanel(root,incidents,frames)
            text=panel._details.get('1.0','end')
            self.assertLess(text.index('C5_SIGNAL_ANOMALY'),text.index('T5_STALE_UNMEASURED_BOX'))
            complete=text.split('TOUS LES TYPES DE PROBLEMES',1)[1]
            self.assertLess(complete.index('C5_SIGNAL_ANOMALY'),complete.index('-43'))
            panel._show_details(replace(stale(),metrics={}))
            self.assertIn('régénérer',panel._details.get('1.0','end'))
            panel.destroy()
        finally:
            for job in root.tk.call('after','info'):root.tk.call('after','cancel',job)
            root.destroy()
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            report=write_diagnostic_report(incidents,Path(directory),frames)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page();page.goto(report.as_uri())
                text=page.locator('.priority-grid').inner_text()
                self.assertIn('Capteur C5',text)
                # Un cycle T5 rare reste en alerte et quitte les trois priorites.
                self.assertNotIn('T5 - Boite',text)
                self.assertIn('Alerte',page.locator('details.group[data-group^="T5_STALE_UNMEASURED_BOX:"] > summary').inner_text())
                summary=page.locator('details.group[data-group^="C5_SIGNAL_ANOMALY:"] > summary').first
                self.assertEqual(summary.inner_text().count('transfert T3→T4 bloqué'),1)
                self.assertIn('42 h 52 observées · reprise non confirmée',summary.inner_text())
                self.assertNotIn('184053',summary.inner_text())
                self.assertEqual(page.locator('details.group').first.get_attribute('data-group').split(':')[0],'C5_SIGNAL_ANOMALY')
                with page.expect_download() as download:page.locator('[data-pdf]').click()
                path=Path(directory)/'rapport.pdf';download.value.save_as(path)
                pdf=pdfium.PdfDocument(path)
                text='\n'.join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
                self.assertLess(text.index('Capteur C5'),text.index('T5 - Boite'))
                self.assertLess(text.index('Capteur C5'),text.index('T3 eT:-43'))
                pdf.close();browser.close()


if __name__=='__main__':unittest.main(verbosity=2)
