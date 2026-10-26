"""Valide les episodes C5, leurs attributions et la synthese robot compacte."""
from datetime import datetime
from pathlib import Path
import os
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.c5_analysis import analyze_c5
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Models.group_analysis import _combine_signal
from Models.robot_drain import drain_box_ratio, drain_compact_box_text, merge_robot_box_metrics
from Tools.validate_c2_signal import frames_for


def blinking(count=11, step=3):
    return [(i * step, f'tEA-T3: WAIT-COND C4:1 C5:{i%2} fgBfinT3:1 eT3:2') for i in range(count)]


def cycle(start=31, id_b=230, id_a=32481, measured=False, complete=True):
    rows = [(start, f'tT3/T4: transfert T3->T4 terminé, longueur=0 mm, attend transfert vers T5 (idB={id_b})'),
            (start+.1, f"tT3/T4: ***IL N'Y A PAS DE BOITE MESURE sur C6 et LongMesure incorrect *** (idB={id_b})"),
            (start+1, 'tT4*T5: WAIT-FIN-TRANSFERT-T4/T5 C6:1'),
            (start+2, f"BdD: Création de la boite 'CIP-COMMUN' -unknow x=5012 (0x0x20) IdA:{id_a}"),
            (start+2, f"photoCamT5 'AjoutBtT5.idA{id_a}.idB{id_b}'")]
    if measured:
        rows.append((start+3, f'MAJ (APRES-MESURE-LARG) bt IdA:{id_a} CIP-COMMUN'))
    if complete:
        rows += [(start+4, 'T5: Suppr. dern. boite chargée car largeur lue sur T5 < 2mm (et C9=0) ...'),
                 (start+4, f'Suppr. dernière boite transférer (IdBdD:{id_a} IdT5:{id_a} Ref:CIP-COMMUN)')]
    rows.append((start+5, 'tEA-T3: WAIT-COND C4:1 C5:0'))
    return rows


def signal(rows):
    frames = frames_for(rows)
    return next((row for row in build_diagnostics(frames, []) if row.code == 'C5_SIGNAL_ANOMALY'), None)


def fixture():
    return blinking() + [(30.5, 'tEA-T3: ajout boite virtuelle sur T3 ALPHA-INC-FICTIF 10,3g')] + cycle()


class C5Tests(unittest.TestCase):
    def test_inclusive_window_and_raw_values(self):
        rows = blinking(step=30)
        incident = signal(rows)
        self.assertEqual((incident.severity, incident.count, incident.metrics['transitions']), ('warning', 1, 10))
        self.assertIsNone(signal(blinking(10)))
        # Les dix horodatages de bascule couvrent exactement cinq minutes.
        rows = blinking(step=300/9)
        self.assertEqual(signal(rows).metrics['transitions'], 10)
        self.assertIsNone(signal(blinking(step=301/9)))
        frames = frames_for(blinking())
        for frame in frames:
            frame.C5 = 1
        self.assertEqual(analyze_c5([(n,t,f) for f in frames for n,t in f.raw_lines])[0]['transitions'], 10)
        self.assertIsNone(signal([(i, 'idCB2: WAIT-COND C5:'+str(i%2)) for i in range(50)]))
        self.assertIsNone(signal([(i, 'tEA-T3: WAIT-COND C5:1') for i in range(50)]))

    def test_boundaries_and_requests_are_not_confirmations(self):
        for boundary in ('tEA-T3: le transfert (EA->T3) est terminé', 'version logiciel VBalpha: 1.0'):
            rows = blinking(6) + [(16, boundary)] + [(20+s,t) for s,t in blinking(6)]
            self.assertIsNone(signal(rows))
        self.assertIsNotNone(signal(blinking(6) + [(16, 'tEA-T3: demande le transfert de EA->T3')]
                                    + [(20+s,t) for s,t in blinking(6)]))
        self.assertIsNone(signal(blinking(6) + [(136+s,t) for s,t in blinking(6)]))
        rows = blinking() + [(100, 'tEA-T3: WAIT-COND C5:0'),
                              (200, 'tEA-T3: WAIT-COND C5:0'),
                              (300, 'tEA-T3: WAIT-COND C5:0'),
                              (330, 'tEA-T3: WAIT-COND C5:0')]
        incident = signal(rows)
        self.assertIn('Cinq minutes', incident.metrics['episodes'][0]['end_reason'])
        self.assertNotIn('réparation confirmée', incident.examples[0]['detail'])

    def test_critical_cycle_virtual_and_c6_pulse(self):
        incident = signal(fixture())
        self.assertEqual((incident.severity, incident.metrics['suspect_cycle_count']), ('error', 1))
        self.assertEqual(incident.metrics['virtual_creation_count'], 1)
        self.assertEqual(incident.metrics['incomplete_cycle_count'], 0)
        suspect = incident.metrics['episodes'][0]['cycles'][0]
        self.assertEqual((suspect['id_b'], suspect['id_alpha']), (230,32481))
        self.assertIn('impulsion C6 observée', suspect['sources'])
        self.assertIn('largeur < 2 mm et C9=0', suspect['sources'])
        self.assertTrue(any('pesée' in example['detail'] for example in incident.examples))

    def test_incomplete_ambiguous_and_measured_cycles(self):
        for rows in (cycle(complete=False), cycle(measured=True),
                     [row for row in cycle() if 'PAS DE BOITE' not in row[1]],
                     [(s,t.replace('idB230','idB999')) for s,t in cycle()],
                     [(s,t.replace('IdT5:32481','IdT5:777')) for s,t in cycle()]):
            incident = signal(blinking()+rows)
            self.assertEqual((incident.severity,incident.metrics['suspect_cycle_count']), ('warning',0))
            self.assertEqual(incident.metrics['incomplete_cycle_count'],1)
        rows=cycle(); rows.insert(5,rows[4])
        self.assertEqual(signal(blinking()+rows).severity,'warning')
        rows=cycle()
        rows.insert(5,(34,"BdD: Création de la boite 'CIP-COMMUN' -unknow x=5012 (0x0x20) IdA:999"))
        self.assertEqual(signal(blinking()+rows).severity,'warning')

    def test_reused_identifiers_cip_and_segments(self):
        incident=signal(blinking()+cycle()+cycle(start=40))
        self.assertEqual(incident.metrics['suspect_cycle_count'],2)
        # IdB peut etre reutilise apres son attribution IdA, meme si l'ancienne boite est encore sur T5.
        incident=signal(blinking()+cycle(measured=True,complete=False)+cycle(start=40,id_a=999))
        self.assertEqual(incident.metrics['suspect_cycle_count'],1)
        self.assertEqual(incident.metrics['incomplete_cycle_count'],1)
        first=signal(blinking()+cycle(complete=False))
        second=signal(blinking()+cycle(start=40))
        combined=_combine_signal([first,second])[0]
        self.assertEqual(combined.metrics['episode_count'],2)
        self.assertEqual(combined.metrics['suspect_cycle_count'],1)
        self.assertEqual(combined.metrics['incomplete_cycle_count'],1)
        self.assertEqual({row['episode'] for row in combined.examples},{1,2})
        # Une fin dans un autre segment ne complete jamais la chaine precedente.
        self.assertIsNone(signal(cycle()[5:]))

    def test_report_episodes_bounded_proofs_and_unchanged_diagnostics(self):
        rows=fixture()+sum((cycle(start=40+i*10,id_b=300+i,id_a=400+i) for i in range(14)),[])
        frames=frames_for(rows)
        incidents=build_diagnostics(frames,[])
        with patch('Models.diagnostic._build_c5_incidents',return_value=[]):
            old=build_diagnostics(frames,[])
        self.assertEqual(old,[item for item in incidents if item.code!='C5_SIGNAL_ANOMALY'])
        group=next(row for row in build_report_payload(incidents,frames)['groups'] if row['code']=='C5_SIGNAL_ANOMALY')
        self.assertEqual((len(group['examples']),len(group['series'])),(10,1))
        self.assertEqual(group['metrics']['suspect_cycle_count'],15)
        self.assertEqual(group['field_priority'],501)
        self.assertEqual(group['belt'],'T3')
        self.assertNotIn('initialisation T2',group['metric'])
        for example in group['examples']:
            self.assertTrue(set(example['sources'].values()).issubset({row['line'] for row in example['context']}))

    def test_robot_ratio_totals_legacy_and_zero(self):
        from Tools.validate_robot_box_counts import fixture as robot_frames, ORIGIN
        from Models.robot_drain import analyze_robot_boxes
        frames=robot_frames()
        analysis=analyze_robot_boxes([(n,t,f) for f in frames for n,t in f.raw_lines],ORIGIN)
        analysis.update(rejected_boxes_count=60,robot_picked_boxes_count=2100)
        self.assertAlmostEqual(drain_box_ratio(analysis),60/2160)
        self.assertIn('2,78% évacuées',drain_compact_box_text(analysis))
        self.assertIn('2 100 prises confirmées',drain_compact_box_text(analysis))
        other=dict(analysis,rejected_boxes_count=1,robot_picked_boxes_count=1)
        self.assertAlmostEqual(drain_box_ratio(merge_robot_box_metrics([analysis,other])),61/2162)
        self.assertIn('Ratio indisponible',drain_compact_box_text(dict(analysis,rejected_boxes_count=0,robot_picked_boxes_count=0)))
        self.assertIn('régénérer',drain_compact_box_text({}))
        robot=next(row for row in build_diagnostics(frames,[],trace_origin=ORIGIN) if row.code=='DemVidageComplet')
        robot.metrics.update(analysis)
        group=build_report_payload([robot],frames)['groups'][0]
        self.assertEqual(len(group['priority_lines']),2)
        self.assertNotIn('sans bilan', ' '.join(group['priority_lines']))
        self.assertNotIn('Trace analysée', ' '.join(group['priority_lines']))

    def test_group_stores_and_source_provenance(self):
        from Tools.validate_folder_groups import FolderGroupsTests
        from Models.group_analysis import analyze_group
        from Models.frame_store import FrameStore
        helper=FolderGroupsTests(); helper.setUp()
        try:
            first_rows=blinking()+cycle(complete=False)
            second_rows=blinking()+cycle(start=40)
            sources=[helper.source(name,start,[text for _,text in rows],times=[s for s,_ in rows])
                     for name,start,rows in [('c5-a','2026-10-21T10:00:00',first_rows),
                                             ('c5-b','2026-10-22T10:00:00',second_rows)]]
            result=analyze_group(sources,helper.root/'combined')
            incidents=result['diagnostics']
            incident=next(row for row in incidents if row.code=='C5_SIGNAL_ANOMALY')
            self.assertEqual((incident.count,incident.metrics['suspect_cycle_count']), (2,1))
            self.assertEqual(incident.metrics['incomplete_cycle_count'],1)
            with FrameStore(result['store']) as frames:
                group=next(row for row in build_report_payload(incidents,frames)['groups'] if row['code']=='C5_SIGNAL_ANOMALY')
                self.assertEqual(len(group['series']),2)
                self.assertIn('21/10/2026',group['series'][0]['start_time_str'])
                self.assertIn('22/10/2026',group['series'][1]['start_time_str'])
                for sample in group['examples']:
                    expected='c5-a.old' if sample['episode']==1 else 'c5-b.old'
                    self.assertIn(expected,sample['source_label'])
                    self.assertIn('21/10/2026' if sample['episode']==1 else '22/10/2026',sample['display_time_str'])
                    self.assertTrue(all(expected in row['source_label'] for row in sample['context']))
        finally:helper.tearDown()

    def test_calendar_month_and_year_rollovers(self):
        for origin in (datetime(2026,10,31,23,59,40),datetime(2026,12,31,23,59,40)):
            frames=frames_for(blinking())
            for frame in frames:
                if frame.timestamp>=20:frame.timestamp-=31*86400
            result=analyze_c5([(n,t,f) for f in frames for n,t in f.raw_lines],origin)
            episode=result[0]['episodes'][0]
            self.assertEqual(episode['duration_seconds'],30)
            self.assertIn('01/11/2026' if origin.month==10 else '01/01/2027',episode['end_time_str'])

    def test_available_local_trace_on_parser_frames(self):
        from Parser.trace_parser import parse_file
        path=Path(os.environ.get('USERPROFILE',''))/'Desktop'/'trace alpha'/'tracalpha1.txt'
        if not path.is_file():self.skipTest('Trace terrain locale absente')
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            target=Path(directory)/'extrait-local.old'
            with path.open(encoding='latin-1') as source, target.open('w',encoding='latin-1') as output:
                for number,text in enumerate(source,1):
                    if number>651000:break
                    if number>=621200:output.write(text)
            frames=parse_file(str(target),min_dt=0.0)
            incidents=build_diagnostics(frames,[])
            with patch('Models.diagnostic._build_c5_incidents',return_value=[]):
                baseline=build_diagnostics(frames,[])
            self.assertEqual(baseline,[row for row in incidents if row.code!='C5_SIGNAL_ANOMALY'])
            c5=next(row for row in incidents if row.code=='C5_SIGNAL_ANOMALY')
            self.assertEqual(c5.metrics['suspect_cycle_count'],15)
            self.assertEqual(c5.metrics['virtual_creation_count'],2)
            self.assertEqual(c5.severity,'error')
            cycles=c5.metrics['episodes'][0]['cycles']
            self.assertEqual({row['id_b'] for row in cycles},set(range(223,238)))
            self.assertTrue(all(row['complete'] for row in cycles))
            print('Trace locale : 15 cycles IdB 223..237 attribues, 2 creations virtuelles ; autres diagnostics identiques.')

    def test_viewer_browser_pdf_navigation(self):
        import customtkinter as ctk
        import pypdfium2 as pdfium
        from playwright.sync_api import sync_playwright
        from Widgets.diagnostic_panel import DiagnosticPanel
        from Models.report_bridge import ReportBridge
        from Tools.validate_robot_box_counts import fixture as robot_frames, ORIGIN
        frames=frames_for(fixture()+[(1000+s,t) for s,t in fixture()])
        incidents=build_diagnostics(frames,[])
        incident=next(row for row in incidents if row.code=='C5_SIGNAL_ANOMALY')
        root=ctk.CTk(); root.withdraw()
        received=[]
        try:
            panel=DiagnosticPanel(root,incidents,frames,on_incident_click=received.append)
            panel._show_details(incident)
            line=incident.metrics['episodes'][0]['cycles'][0]['sources']['suppression IdA']
            script=panel._details.tk.call(panel._details._w,'tag','bind',f'c5-source-{line}','<Button-1>')
            command=re.search(r'\[([^\s]+)',script)[1]
            panel._details.tk.call(command,*(['0']*len(panel._details._subst_format)))
            self.assertEqual(received[0].first_line,line)
            panel.destroy()
        finally:
            for job in root.tk.call('after','info'):root.tk.call('after','cancel',job)
            root.destroy()
        robot=next(row for row in build_diagnostics(robot_frames(),[],trace_origin=ORIGIN) if row.code=='DemVidageComplet')
        robot.count=52
        robot.metrics.update(total=52,day={'count':52},rejected_boxes_count=60,robot_picked_boxes_count=2100)
        robot.metrics['trace']['days']=13
        incidents.append(robot)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            report=write_diagnostic_report(incidents,Path(directory),frames,source_name='DEMONSTRATION C5 ET ROBOT')
            fallback=Path(directory)/'fallback.html'
            fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
            bridge=ReportBridge()
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(channel='msedge',headless=True)
                    page=browser.new_page(viewport={'width':1600,'height':1000})
                    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    for url in (bridge.register(report),fallback.as_uri()):
                        page.goto(url)
                        card=page.locator('.priority-grid [data-priority^="DemVidageComplet:"]')
                        self.assertEqual(card.count(),1)
                        text=card.inner_text()
                        self.assertIn('2,78%',text)
                        self.assertNotIn('Trace analysée',text)
                        self.assertNotIn('bilan complet',text)
                        detail=page.locator('details[data-group^="C5_SIGNAL_ANOMALY:"]')
                        detail.locator('> summary').click()
                        for series in detail.locator('.incident-series').all():series.evaluate('(node)=>node.open=true')
                        self.assertIn('fantôme',detail.inner_text())
                        for node in detail.locator('.sample-technical').all():node.evaluate('(node)=>node.open=true')
                        link=detail.locator(f'[data-source-navigate="source:{line}"]').first
                        if url.startswith('http:'):
                            page.wait_for_function("!document.querySelector('[data-source-navigate]').disabled")
                            targets=[]
                            def receive():
                                target,done,result=bridge.commands.get(timeout=5)
                                targets.append(target);result.update(ok=True,line=target['line']);done.set()
                            worker=threading.Thread(target=receive);worker.start();link.click();worker.join(5)
                            self.assertEqual(targets[0]['line'],line)
                        else:self.assertTrue(link.is_disabled())
                        page.set_viewport_size({'width':390,'height':900})
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                        page.set_viewport_size({'width':1600,'height':1000})
                        with page.expect_download() as download:page.locator('[data-pdf]').click()
                        pdf=Path(directory)/'report.pdf';download.value.save_as(pdf)
                        document=pdfium.PdfDocument(pdf)
                        text='\n'.join(document[i].get_textpage().get_text_range() for i in range(len(document)))
                        for expected in ('Capteur C5','fantôme','2,78%','prises confirmées','évacuées /','Synthèse terrain'):
                            self.assertIn(expected,text)
                        self.assertNotIn('Épisode 2',text)
                        document.close()
                    self.assertFalse(errors)
                    browser.close()
            finally:bridge.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
