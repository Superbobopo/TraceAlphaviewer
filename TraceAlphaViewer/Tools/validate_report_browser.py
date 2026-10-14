"""Verifie le rapport React, le secours hors ligne et le PDF sur donnees fictives."""
from pathlib import Path
import tempfile
import threading
import shutil
from copy import deepcopy
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Tools.validate_measurement_report import samples, recurring_samples, product_samples, phased_samples, orientation_samples
from Models.diagnostic import build_diagnostics, DiagnosticIncident
from Models.diagnostic_report import write_diagnostic_report, build_diagnostic_report_html, build_report_payload
from Models.measurement_analysis import analyze_measurements
from Models.report_bridge import ReportBridge


class BrowserTests(unittest.TestCase):
    def test_header_priority_alignment_and_progressive_distributions(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        fields={'length':'measured_t4_length_mm','width':'measured_t5_width_mm','height':'measured_t5_height_mm'}
        distributions={
            'length':[(1,398),(2,315),(3,149),(0,147),(-1,33),(-2,25),(4,14),(-3,8),(5,8),(-11,2),(77,2)]+[(delta,1) for delta in (-4,6,-9,-10,-12,-14,-21,78,79,111,136)],
            'width':[(-3,368),(-4,305),(-2,215),(-5,155),(-1,44),(-6,14),(0,5),(1,4),(-7,1),(16,1)],
            'height':[(0,622),(1,248),(-1,195),(3,30),(2,11),(-2,6)]}
        frames=samples(1112,0)
        for axis,values in distributions.items():
            deltas=[delta for delta,count in values for _ in range(count)]
            self.assertEqual(len(deltas),1112)
            for frame,delta in zip(frames,deltas):
                box=frame.boxes_on_T5[0]
                setattr(box,fields[axis],getattr(box,fields[axis])+delta)
        incidents=build_diagnostics(frames,[])
        incidents.append(DiagnosticIncident(title='Carte Alpha - Reset fictif',code='ALPHA_CARD_RESET',belt='ALPHA',severity='error',count=1))
        payload=build_report_payload(incidents,frames,source_name='PRESENTATION FICTIVE')
        self.assertGreaterEqual(len(payload['priority']),3)
        for group,text in zip(payload['priority'][:3],('Vérifier quelques boîtes et comparer leurs dimensions physiques. '*3,'Contrôle court.','Contrôle détaillé avec une explication plus longue pour vérifier le début du bloc. '*5)):
            group['field_action']=text
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        with patch('Models.diagnostic_report.build_report_payload',return_value=payload):
            report=write_diagnostic_report(incidents,output,frames)
            fallback=output/'secours-presentation.html'
            fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1600})
            for path in (report,fallback):
                page.goto(path.as_uri())
                self.assertEqual(page.locator('.hero-title').evaluate('(node)=>getComputedStyle(node).textAlign'),'center')
                self.assertEqual(page.locator('.hero-meta .meta-item').count(),3)
                for width in (1920,1440,1280):
                    page.set_viewport_size({'width':width,'height':1600})
                    positions=page.locator('.priority-grid .priority-action').evaluate_all('(nodes)=>nodes.map(node=>node.getBoundingClientRect().top)')
                    self.assertLess(max(positions)-min(positions),1)
                page.set_viewport_size({'width':1440,'height':1600})
                for axis,values in distributions.items():
                    table=page.locator(f'[data-axis={axis}] .measurement-distribution')
                    self.assertEqual(table.locator('tbody tr').count(),5)
                    button=page.locator(f'[data-distribution-axis={axis}]')
                    self.assertEqual(button.get_attribute('aria-expanded'),'false')
                    button.focus()
                    page.keyboard.press('Enter')
                    self.assertEqual(table.locator('tbody tr').count(),len(values))
                    self.assertEqual(button.get_attribute('aria-expanded'),'true')
                    self.assertTrue(button.evaluate('(node)=>document.activeElement===node'))
                page.locator('[data-measure-axis=length][data-measure-side=over]').click()
                self.assertEqual(page.locator('[data-axis=length] .measurement-distribution tbody tr').count(),22)
                page.locator('[data-measure-close]').click()
                for axis in fields:
                    page.locator(f'[data-distribution-axis={axis}]').click()
                    self.assertEqual(page.locator(f'[data-axis={axis}] .measurement-distribution tbody tr').count(),5)
                for width in (850,390):
                    page.set_viewport_size({'width':width,'height':1600})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.screenshot(path=str(output/'rapport-presentation-mobile.png'))
                page.set_viewport_size({'width':1440,'height':1600})
                page.screenshot(path=str(output/'rapport-presentation-ensemble.png'))
                page.locator('.hero').screenshot(path=str(output/'rapport-presentation-entete.png'))
                page.locator('.priority-grid').screenshot(path=str(output/'rapport-presentation-priorites.png'))
                with page.expect_download() as download:page.get_by_role('button',name='Exporter PDF').click()
                pdf=output/'rapport-presentation.pdf'
                download.value.save_as(pdf)
                document=pdfium.PdfDocument(pdf)
                content=' '.join(' '.join(p.get_textpage().get_text_range() for p in document).split())
                for text in ('+136,0 mm','+16,0 mm','0,1 %','0,7 %'):
                    self.assertIn(text,content)
                document.close()
            browser.close()

    def test_orientation_products_pagination_full_frame_and_offline_details(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        from Models.measurement_navigation import measurement_box_in_frame
        frames=orientation_samples()
        extra=samples(26*20,0)
        for i,frame in enumerate(extra):
            box=frame.boxes_on_T5[0]
            box.barcode=box.identified_barcode=box.bdd_reference=f'RARE-ORIENTATION-{i//20:02d}'
            box.name=box.identified_name='PRODUIT FICTIF RARE'
            box.bdd_width_mm,box.bdd_height_mm,box.bdd_length_mm=50,40,100
            box.measured_t5_width_mm,box.measured_t5_height_mm,box.measured_t4_length_mm=(100,40,50) if i%20==0 else (50,40,100)
            frame.line_num+=30
            box.measured_t4_line=box.measured_t5_line=box.measured_height_line=frame.line_num
            box.camera_identity_line=box.bdd_source_line=frame.line_num
            frame.timestamp=i+7
            frame.timestamp_str=f'09:{(i+7)//60:02d}:{(i+7)%60:02d}'
            frame.raw_lines=[(frame.line_num,'ROTATION FICTIVE OU PRESENTATION NORMALE')]
        frames+=extra
        incidents=build_diagnostics(frames,[])
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        report=write_diagnostic_report(incidents,output,frames,source_name='ORIENTATIONS FICTIVES')
        fallback=output/'secours-orientations.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        bridge=ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1080})
                for url in (bridge.register(report),fallback.as_uri()):
                    local=url.startswith('http:')
                    page.goto(url)
                    if local:page.get_by_role('status').filter(has_text='Liaison avec').wait_for()
                    section=page.locator('.orientations')
                    self.assertIn('Orientation probable d’après les dimensions',section.inner_text())
                    self.assertEqual(page.locator('details[data-group]').filter(has_text='ORIENTATION').count(),0)
                    panel=section.locator('[data-orientation-list=probable]')
                    self.assertEqual(panel.locator('tbody tr').count(),25)
                    self.assertIn('5,0 %',panel.inner_text())
                    panel.get_by_role('button',name='Suivants',exact=True).click()
                    self.assertEqual(panel.locator('tbody tr').count(),2)
                    panel.get_by_role('button',name='Précédents',exact=True).click()
                    target=self._open_reference(page,panel,'ORIENTATION-FICTIVE',bridge if local else None,keyboard=True)
                    self.assertEqual(panel.locator('.orientation-proofs > .sample').count(),3)
                    self.assertIn('3/7',panel.inner_text())
                    self.assertEqual(panel.locator('.box-measurements').first.locator('thead th').count(),3)
                    self.assertIn('Écart cumulé',panel.inner_text())
                    self.assertIn('50 mm',panel.locator('.orientation-matches').first.inner_text())
                    self.assertEqual(panel.locator('.measure-bad').count(),0)
                    if local:
                        self.assertEqual(target['frame_index'],1)
                        self.assertEqual(measurement_box_in_frame(frames[1],target['sample']).id_alpha,101)
                        received=[]
                        def navigate_box():
                            command,done,result=bridge.commands.get(timeout=10)
                            received.append(command)
                            result.update(ok=True,line=command['line'])
                            done.set()
                        thread=threading.Thread(target=navigate_box)
                        thread.start()
                        panel.locator('.orientation-proofs > .sample').nth(1).locator('[data-navigate]').click()
                        page.get_by_role('status').filter(has_text='positionné').wait_for()
                        thread.join(5)
                        self.assertEqual(received[0]['frame_index'],2)
                        self.assertEqual(measurement_box_in_frame(frames[2],received[0]['sample']).id_alpha,102)
                    section.locator('.orientation-uncertain > summary').click()
                    unsure=section.locator('[data-orientation-list=uncertain]')
                    self._open_reference(page,unsure,'ORIENTATION-FICTIVE',bridge if local else None)
                    self.assertIn('Orientation indécidable',unsure.inner_text())
                    self.assertEqual(unsure.locator('.orientation-matches tbody tr').count(),2)
                    page.set_viewport_size({'width':390,'height':1080})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    page.set_viewport_size({'width':1440,'height':1080})
                    with page.expect_download() as download:page.get_by_role('button',name='Exporter PDF').click()
                    pdf=output/'rapport-orientations.pdf'
                    download.value.save_as(pdf)
                    document=pdfium.PdfDocument(pdf)
                    content=' '.join(' '.join(p.get_textpage().get_text_range() for p in document).split())
                    for text in ('Boîtes dans le mauvais sens','Orientations indécidables','3/7','5,0 %','RARE-ORIENTATION-25','Écart cumulé'):
                        self.assertIn(text,content)
                    document.close()
                page.goto(bridge.register(report))
                page.get_by_role('status').filter(has_text='Liaison avec').wait_for()
                bridge.close()
                self._open_reference(page,page.locator('[data-orientation-list=probable]'),'ORIENTATION-FICTIVE')
                page.get_by_role('status').filter(has_text='fermée').wait_for()
                self.assertEqual(page.locator('.orientation-proofs > .sample').count(),3)
                browser.close()
        finally:bridge.close()

    def test_frequent_products_rare_pagination_navigation_and_pdf(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        groups=[('RARE',[136]*2+[0]*251),('JUSTE-SOUS',[4]*25+[0]*228),
                ('RETENU',[4]*26+[0]*227),('LIMITE',[4]*10+[0]*90)]
        groups += [(f'RARE-PAGE-{i:02d}',[136]+[0]*10) for i in range(26)]
        frames=product_samples(groups)
        incidents=build_diagnostics(frames,[])
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        report=write_diagnostic_report(incidents,output,frames,source_name='PRODUITS FREQUENTS FICTIFS')
        fallback=output/'secours-cas-rares.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        bridge=ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1080})
                for url in (bridge.register(report),fallback.as_uri()):
                    local=url.startswith('http:')
                    page.goto(url)
                    if local:page.get_by_role('status').filter(has_text='Liaison avec').wait_for()
                    button=page.locator('[data-measure-axis=length][data-measure-side=over]')
                    self.assertIn('+4,0 mm',button.inner_text())
                    self.assertNotIn('136',button.inner_text())
                    axis=page.locator('[data-axis=length]')
                    self.assertTrue(axis.locator('.measurement-distribution').is_visible())
                    self.assertEqual(axis.locator('.measurement-distribution').count(),1)
                    self.assertEqual(axis.locator('.measure-details .measurement-distribution').count(),0)
                    self.assertIn('+136,0 mm',axis.locator('.measurement-distribution').inner_text())
                    self.assertFalse(axis.locator('.measure-details').evaluate('(node)=>node.open'))
                    button.click()
                    panel=page.locator('.measurement-reference-list')
                    main=panel.locator(':scope > .table-wrap')
                    self.assertEqual(main.locator('tbody tr').count(),2)
                    self.assertNotIn('RARE',main.inner_text())
                    rare=panel.locator('.rare-products')
                    self.assertFalse(rare.evaluate('(node)=>node.open'))
                    rare.locator(':scope > summary').focus()
                    page.keyboard.press('Enter')
                    self.assertEqual(rare.locator('tbody tr').count(),25)
                    self.assertIn('2 sur 253',rare.inner_text())
                    target=self._open_reference(page,panel,'RARE',bridge if local else None,keyboard=True)
                    self.assertEqual(panel.locator('.reference-proofs > .sample').count(),2)
                    self.assertIn('+136,0 mm',panel.inner_text())
                    if local:self.assertEqual(target['frame_index'],0)
                    panel.get_by_role('button',name='Retour aux références').click()
                    rare=panel.locator('.rare-products')
                    self.assertTrue(rare.evaluate('(node)=>node.open'))
                    rare.get_by_role('button',name='Suivants',exact=True).click()
                    self.assertEqual(rare.locator('tbody tr').count(),3)
                    self.assertIn('Page 2/2',rare.inner_text())
                    page.set_viewport_size({'width':390,'height':1080})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    page.set_viewport_size({'width':1440,'height':1080})
                    with page.expect_download() as download:page.get_by_role('button',name='Exporter PDF').click()
                    pdf=output/'rapport-cas-rares.pdf'
                    download.value.save_as(pdf)
                    document=pdfium.PdfDocument(pdf)
                    content=' '.join(' '.join(p.get_textpage().get_text_range() for p in document).split())
                    self.assertIn('cas rares (< 10 %)',content)
                    self.assertIn('Répartition de toutes les mesures comparables',content)
                    self.assertIn('max 136,0 mm',content)
                    document[0].render(scale=1.2).to_pil().save(output/'pdf-cas-rares-page-1.png')
                    document.close()
                browser.close()
        finally:bridge.close()

    def test_dimension_priority_and_recurrences_sorted_by_affected_boxes(self):
        from playwright.sync_api import sync_playwright
        frames=samples(1112,0)
        changes=[('measured_t5_width_mm',-4)]*460+[('measured_t5_width_mm',16)]+[('measured_t4_length_mm',-11)]*4+[('measured_t4_length_mm',4)]*22+[('measured_t5_height_mm',3)]*30
        for frame,(field,delta) in zip(frames,changes):
            box=frame.boxes_on_T5[0]
            setattr(box,field,getattr(box,field)+delta)
        incidents=build_diagnostics(frames,[])
        incidents.extend([DiagnosticIncident(title='Reset fictif',code='ALPHA_CARD_RESET',belt='ALPHA',severity='error',count=1),
                          DiagnosticIncident(title='Dimensions globales fictives',code='GLOBAL',belt='T5',severity='warning',count=1)])
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        report=write_diagnostic_report(incidents,output,frames,source_name='PRIORITES MESURE FICTIVES')
        fallback=output/'secours-priorites.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1080})
            for path in (report,fallback):
                page.goto(path.as_uri())
                self.assertIn('T5_WIDTH',page.locator('[data-priority]').first.get_attribute('data-priority'))
                self.assertIn('T5_WIDTH',page.locator('details[data-group]').first.get_attribute('data-group'))
                self.assertIn('Critique',page.locator('details[data-group]').first.locator(':scope > summary').inner_text())
                rows=page.locator('details[data-group]').filter(has=page.locator('h3',has_text='Dimensions globales fictives')).locator('.group-recurrence')
                self.assertEqual(rows.count(),5)
                for i,count in enumerate((460,30,22,4,1)):self.assertIn(f'{count} boîtes',rows.nth(i).inner_text())
                self.assertTrue(page.locator('.hero').evaluate("(node)=>getComputedStyle(node).backgroundImage.includes('linear-gradient')"))
                page.screenshot(path=str(output/'rapport-priorites-distribution.png'),full_page=True)
            browser.close()

    def test_height_threshold_colors_exports_and_legacy_report(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        frames=samples(8,0)
        deltas=(-4,-3,-2,-1,1,2,3,4)
        for frame,delta in zip(frames,deltas):
            box=frame.boxes_on_T5[0]
            box.barcode=box.identified_barcode=box.bdd_reference='HAUTEUR'
            box.measured_t5_height_mm+=delta
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        incidents=build_diagnostics(frames,[])
        report=write_diagnostic_report(incidents,output,frames,source_name='SEUIL HAUTEUR FICTIF')
        fallback=output/'secours-hauteur.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        with patch.dict('Models.dimension_check.DIMENSION_TOLERANCES_MM',{'height':3}):
            old=analyze_measurements(frames)
            old_incidents=build_diagnostics(frames,[])
        old['summary'].pop('tolerances_mm')
        for axis in old['summary']['axes'].values():axis.pop('tolerance_mm')
        for sample in old['samples']:sample.pop('tolerances_mm')
        legacy=output/'ancien-seuil-hauteur.html'
        with patch('Models.diagnostic_report.analyze_measurements',return_value=old):
            legacy.write_text(build_diagnostic_report_html(old_incidents,frames),encoding='utf-8')
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1080})
            for path,tolerance in ((report,2),(fallback,2),(legacy,3)):
                page.goto(path.as_uri())
                height=page.locator('[data-axis=height]')
                self.assertIn(f'À vérifier : écart > {tolerance} mm',height.inner_text())
                self.assertIn(f'{4 if tolerance==2 else 2} boîtes hors tolérance',height.inner_text())
                self.assertIn('longueur > 3 mm',page.locator('.measurement-intro').inner_text())
                self.assertIn('largeur > 3 mm',page.locator('.measurement-intro').inner_text())
                height.locator('.measure-details > summary').click()
                height.locator('.recurrence-details > summary').click()
                height.locator('[data-measure-side=under_group]').click()
                panel=page.locator('.measurement-reference-list')
                panel.get_by_role('button',name='HAUTEUR',exact=True).click()
                tables=panel.locator('.reference-proofs .box-measurements')
                self.assertEqual(tables.count(),8)
                for index,delta in enumerate(deltas):
                    cell=tables.nth(index).locator('tbody tr').nth(2).locator('td').nth(3)
                    self.assertEqual(cell.get_attribute('class'),'measure-bad' if abs(delta)>tolerance else 'measure-good')
                page.set_viewport_size({'width':390,'height':1080})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.set_viewport_size({'width':1440,'height':1080})
                with page.expect_download() as download:
                    page.get_by_role('button',name='Exporter PDF').click()
                pdf=output/f'rapport-hauteur-{path.stem}.pdf'
                download.value.save_as(pdf)
                document=pdfium.PdfDocument(pdf)
                content=' '.join(' '.join(p.get_textpage().get_text_range() for p in document).split())
                self.assertIn(f'hauteur > {tolerance} mm',content)
                self.assertIn(f'écart > {tolerance} mm',content)
                document.close()
            browser.close()

    def test_no_comparables_explain_exclusions_without_zero_over_zero(self):
        from playwright.sync_api import sync_playwright
        frames=samples(2)
        for frame in frames:frame.boxes_on_T5[0].camera_identity_line=0
        incidents=build_diagnostics(frames,[])
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        report=write_diagnostic_report(incidents,output,frames,source_name='CAMERA NON CONFIRMEE FICTIVE')
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page()
            page.goto(report.as_uri())
            content=page.locator('[data-open=measurements]').inner_text()
            self.assertIn('Aucune boîte ne réunit',content)
            self.assertIn('Comparaison indisponible',content)
            self.assertNotIn('0/0',content)
            page.locator('.measurement-exclusions > summary').click()
            self.assertIn('identifications caméra non confirmées',page.locator('.measurement-exclusions').inner_text())
            self.assertTrue(page.locator('[data-measure-axis=length][data-measure-side=under]').is_disabled())
            browser.close()

    def test_legacy_measurement_report_keeps_details_and_requires_regeneration(self):
        from playwright.sync_api import sync_playwright
        frames=phased_samples()
        analysis=deepcopy(analyze_measurements(frames))
        for sample in analysis['samples']:
            sample.pop('display_frame_index',None)
            sample.pop('display_line',None)
        incidents=build_diagnostics(frames,[])
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        with patch('Models.diagnostic_report.analyze_measurements',return_value=analysis):
            report=write_diagnostic_report(incidents,output,frames,source_name='ANCIEN RAPPORT FICTIF')
        bridge=ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page()
                page.goto(bridge.register(report))
                page.get_by_role('status').filter(has_text='Liaison avec').wait_for()
                page.locator('[data-measure-axis=length][data-measure-side=under]').click()
                panel=page.locator('.measurement-reference-list')
                panel.get_by_role('button',name='DEMO-0',exact=True).click()
                self.assertIn('régénérer',page.get_by_role('status').inner_text())
                self.assertIn('93 mm',panel.inner_text())
                self.assertTrue(panel.locator('.reference-proofs [data-navigate]').is_disabled())
                self.assertTrue(bridge.commands.empty())
                browser.close()
        finally:
            bridge.close()

    def _open_reference(self,page,panel,barcode,bridge=None,keyboard=False):
        received=[]
        if bridge:
            def navigate():
                target,done,result=bridge.commands.get(timeout=10)
                received.append(target)
                result.update(ok=True,line=target['line'])
                done.set()
            thread=threading.Thread(target=navigate)
            thread.start()
        button=panel.get_by_role('button',name=barcode,exact=True)
        if keyboard:
            button.focus()
            page.keyboard.press('Enter')
        else:
            button.click()
        if bridge:
            page.get_by_role('status').filter(has_text='positionné').wait_for()
            thread.join(5)
            self.assertEqual(len(received),1)
            return received[0]

    def test_guided_report_hierarchy_keyboard_and_complete_box_details(self):
        from playwright.sync_api import sync_playwright
        frames=phased_samples()
        incidents=build_diagnostics(frames,[])
        incidents.extend(DiagnosticIncident(title=f'PROBLEME FICTIF {i}',code=f'FICTIF-{i}',belt='T2',
            severity='error',count=1,first_line=1,last_line=1,event_lines=[1]) for i in range(5))
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        report=write_diagnostic_report(incidents,output,frames,source_name='LECTURE GUIDEE FICTIVE')
        fallback=output/'secours-guide.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        bridge=ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1080})
                for url in (bridge.register(report),fallback.as_uri()):
                    local=url.startswith('http:')
                    page.goto(url)
                    if local:page.get_by_role('status').filter(has_text='Liaison avec').wait_for()
                    self.assertEqual(page.locator('[data-priority]').count(),3)
                    self.assertEqual(page.locator('.axis-grid > .axis').count(),3)
                    self.assertNotIn('Décalage moyen',page.locator('.axis-grid').inner_text())
                    self.assertFalse(page.locator('.measurement-exclusions').evaluate('(node)=>node.open'))
                    page.get_by_role('button',name='Exporter PDF').focus()
                    page.keyboard.press('Tab')
                    self.assertTrue(page.evaluate('document.activeElement.hasAttribute("data-priority")'))
                    page.keyboard.press('Enter')
                    self.assertTrue(page.locator('details[data-group][open]').count())
                    page.locator('[data-axis=length] .measure-details > summary').click()
                    statistics=page.locator('[data-axis=length] .measure-details').inner_text()
                    self.assertIn('Erreur absolue minimum',statistics)
                    self.assertIn('Erreur absolue maximum',statistics)
                    page.locator('[data-measure-axis=length][data-measure-side=under]').click()
                    panel=page.locator('.measurement-reference-list')
                    target=self._open_reference(page,panel,'DEMO-0',bridge if local else None,keyboard=True)
                    self.assertTrue(page.locator('[data-axis=length] .measure-details').evaluate('(node)=>node.open'))
                    self.assertEqual(panel.locator('.reference-proofs .box-measurements tbody > tr').count(),3)
                    for value in ('93 mm','102 mm','64 mm','60 mm','30 mm','09:00:04'):
                        self.assertIn(value,panel.inner_text())
                    self.assertNotIn('ETAPE FICTIVE',panel.inner_text())
                    if local:self.assertEqual((target['frame_index'],target['line']),(3,4))
                    for width in (1920,1280,850,390):
                        page.set_viewport_size({'width':width,'height':1080})
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    page.screenshot(path=str(output/'rapport-guide-mobile.png'),full_page=True)
                    page.set_viewport_size({'width':1440,'height':1080})
                    page.screenshot(path=str(output/'rapport-guide-detail.png'),full_page=True)
                browser.close()
        finally:
            bridge.close()

    def test_reference_clicks_all_axes_sides_missing_sources_and_closed_viewer(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        frames=samples(13,0)
        fields={'length':'measured_t4_length_mm','width':'measured_t5_width_mm','height':'measured_t5_height_mm'}
        expected_lines={}
        for i,(axis,side,delta) in enumerate((axis,side,delta*sign)
                for axis in fields for side,sign in (('under',-1),('over',1)) for delta in (4,5)):
            frame=frames[i]
            box=frame.boxes_on_T5[0]
            barcode=f'{axis}-{side}'
            box.barcode=box.identified_barcode=box.bdd_reference=barcode
            setattr(box,fields[axis],getattr(box,fields[axis])+delta)
            line=frame.line_num
            box.measured_t4_line=line
            box.measured_t5_line=line+1
            box.measured_height_line=line+2
            frame.line_num=line+2
            frame.raw_lines=[(line,'T4C FICTIF'),(line+1,'C9 FICTIF'),(line+2,'HAUTEUR FICTIVE')]
            if abs(delta)==5:expected_lines[barcode]=line+2
        missing=frames[-1].boxes_on_T5[0]
        missing.barcode=missing.identified_barcode=missing.bdd_reference='SOURCE-ABSENTE'
        missing.measured_t5_width_mm+=6
        missing.measured_t5_line=0
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        incidents=build_diagnostics(frames,[])
        report=write_diagnostic_report(incidents,output,frames,source_name='NAVIGATION FICTIVE')
        fallback=output/'secours-navigation.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        data=report.with_name(report.name.replace('diagnostic_report_','report_data_')).with_suffix('.json')
        shutil.copyfile(data,fallback.with_suffix('.json'))
        bridge=ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1080})
                for url in (bridge.register(report),bridge.register(fallback),fallback.as_uri()):
                    local=url.startswith('http:')
                    page.goto(url)
                    if local:page.get_by_role('status').filter(has_text='Liaison avec').wait_for()
                    for axis in fields:
                        for side in ('under','over'):
                            page.locator(f'[data-measure-axis={axis}][data-measure-side={side}]').click()
                            panel=page.locator('.measurement-reference-list')
                            barcode=f'{axis}-{side}'
                            target=self._open_reference(page,panel,barcode,bridge if local else None)
                            self.assertEqual(panel.locator('.reference-proofs > .sample').count(),2)
                            self.assertIn('4,0 mm',panel.inner_text())
                            if local:
                                self.assertEqual((target['axis'],target['line']),(axis,expected_lines[barcode]))
                            else:
                                self.assertTrue(panel.locator('[data-navigate]').first.is_disabled())
                                self.assertIn('détail reste consultable',page.get_by_role('status').inner_text())
                    page.locator('[data-measure-axis=width][data-measure-side=over]').click()
                    panel.get_by_role('button',name='SOURCE-ABSENTE',exact=True).click()
                    self.assertIn('État complet indisponible',page.get_by_role('status').inner_text())
                    self.assertTrue(panel.locator('.reference-proofs [data-navigate]').is_disabled())
                    self.assertTrue(bridge.commands.empty())
                    page.evaluate('document.querySelector(".measure-details").open=true')
                    self.assertIn('Produits distincts',page.locator('[data-axis=length]').inner_text())
                    with page.expect_download() as download:
                        page.get_by_role('button',name='Exporter PDF').click()
                    pdf=output/'rapport-navigation.pdf'
                    download.value.save_as(pdf)
                    document=pdfium.PdfDocument(pdf)
                    pages=[p.get_textpage().get_text_range() for p in document]
                    contents=' '.join('\n'.join(pages).split())
                    for page_text in pages:
                        lines=[line.strip() for line in page_text.splitlines() if line.strip() and not line.startswith('TraceAlphaViewer')]
                        if lines:
                            self.assertNotIn('les 3 plus grands',lines[-1])
                    for text in ('> 3 mm','produits distincts','se compensent','CB1/CB2'):
                        self.assertIn(text,contents)
                    document.close()
                page.goto(bridge.register(report))
                page.get_by_role('status').filter(has_text='Liaison avec').wait_for()
                page.locator('[data-measure-axis=length][data-measure-side=under]').click()
                bridge.close()
                page.locator('.measurement-reference-list').get_by_role('button',name='length-under',exact=True).click()
                page.get_by_role('status').filter(has_text='fermée').wait_for()
                self.assertEqual(page.locator('.reference-proofs > .sample').count(),2)
                self.assertTrue(page.locator('.reference-proofs [data-navigate]').first.is_disabled())
                browser.close()
        finally:
            bridge.close()

    def test_neighboring_good_measurements_and_bdd_variants_remain_visible(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        frames=product_samples([
            ('PRODUIT-A',[-4,-4,-4,-4,-3,-3]),
            ('PRODUIT-A',[4,4,5,5],(60,30,120)),
            ('PRODUIT-B',[-4,-4,-3]),
            ('PRODUIT-C',[-3,-3]),
        ])
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        incidents=build_diagnostics(frames,[])
        report=write_diagnostic_report(incidents,output,frames,source_name='VARIANTES FICTIVES')
        fallback=output/'secours-variantes.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        bridge=ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1080})
                for url in (bridge.register(report),fallback.as_uri()):
                    local=url.startswith('http:')
                    page.goto(url)
                    page.locator('[data-axis=length] .measure-details > summary').click()
                    page.locator('[data-axis=length] .recurrence-details > summary').click()
                    text=page.locator('[data-axis=length] .recurrence-details').inner_text()
                    for expected in ('6 mesures dépassent','5 restent conformes','11 mesures','3 produit'):
                        self.assertIn(expected,text)
                    page.locator('[data-measure-axis=length][data-measure-side=under]').click()
                    panel=page.locator('.measurement-reference-list')
                    self.assertIn('Plusieurs variantes BdD',panel.inner_text())
                    self._open_reference(page,panel,'PRODUIT-A',bridge if local else None)
                    observation=panel.locator('.product-observations')
                    observation.locator(':scope > summary').click()
                    for expected in ('variantes sont analysées séparément','100 × 60 × 30','120 × 60 × 30','6/6','0/4'):
                        self.assertIn(expected,observation.inner_text())
                    self.assertEqual(panel.locator('.reference-proofs > .sample').count(),4)
                    observation.locator('.comparison-examples > summary').click()
                    example=observation.locator('.sample').filter(has_text='-3,0 mm').first
                    self.assertTrue(example.is_visible())
                    if local:
                        received=[]
                        def navigate():
                            target,done,result=bridge.commands.get(timeout=10)
                            received.append(target)
                            result.update(ok=True,line=target['line'])
                            done.set()
                        thread=threading.Thread(target=navigate)
                        thread.start()
                        page.wait_for_function("!document.querySelector('.comparison-examples [data-navigate]').disabled")
                        example.locator('[data-navigate]').click()
                        page.get_by_role('status').filter(has_text='positionné').wait_for()
                        thread.join(5)
                        self.assertIn(received[0]['line'],(13,16))
                        self.assertEqual(received[0]['axis'],'length')
                    else:
                        self.assertTrue(example.locator('[data-navigate]').is_disabled())
                    with page.expect_download() as download:
                        page.get_by_role('button',name='Exporter PDF').click()
                    pdf_path=output/'rapport-variantes.pdf'
                    download.value.save_as(pdf_path)
                    document=pdfium.PdfDocument(pdf_path)
                    pages=[p.get_textpage().get_text_range() for p in document]
                    contents=' '.join('\n'.join(pages).split())
                    for page_text in pages:
                        lines=[line.strip() for line in page_text.splitlines() if line.strip() and not line.startswith('TraceAlphaViewer')]
                        if lines:
                            self.assertNotIn('les 3 plus grands',lines[-1])
                    for expected in ('5 mesures conformes voisines','Plusieurs variantes BdD','6/6','0/4'):
                        self.assertIn(expected,contents)
                    document.close()
                    page.locator('[data-measure-axis=length][data-measure-side=under_group]').click()
                    self.assertEqual(panel.locator('tbody > tr').count(),3)
                    panel.get_by_role('button',name='PRODUIT-C',exact=True).click()
                    self.assertIn('Toutes les mesures comparables de ce produit',panel.inner_text())
                    panel.locator('.product-observations > summary').click()
                    self.assertIn('2/2',panel.locator('.product-observations').inner_text())
                    self.assertEqual(panel.locator('.reference-proofs > .sample').count(),2)
                    self.assertIn('-3,0 mm',panel.locator('.reference-proofs').inner_text())
                browser.close()
        finally:
            bridge.close()

    def test_repeated_offsets_visible_in_closed_cards_fallback_and_pdf(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        output = ROOT / 'build' / 'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        frames = recurring_samples()
        incidents = build_diagnostics(frames,[])
        report = write_diagnostic_report(incidents,output,frames,source_name='DECALAGES FICTIFS')
        fallback = output / 'secours-decalages.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge',headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1080})
            for path in (report,fallback):
                page.goto(path.as_uri())
                axis = page.locator('[data-axis=length]')
                self.assertFalse(axis.locator('.measure-details').evaluate('(node) => node.open'))
                self.assertTrue(axis.locator('.measurement-distribution').is_visible())
                axis.locator('.measure-details > summary').click()
                axis.locator('.recurrence-details > summary').click()
                text = axis.locator('.recurrence-details').inner_text()
                for expected in ('12 boîtes à -4,0 mm','6 boîtes à -5,0 mm','18','90,0 %','18,0 %'):
                    self.assertIn(expected,text)
                self.assertNotIn('réglage/calibrage',text)
                self.assertTrue(axis.locator('.measure-details').evaluate('(node) => node.open'))
                distribution = axis.locator('.measurement-distribution')
                self.assertEqual(distribution.locator('tbody tr').count(),4)
                self.assertIn('80',distribution.inner_text())
                self.assertIn('0,0 mm',distribution.inner_text())
                card = page.locator('details[data-group]').first
                self.assertFalse(card.evaluate('(node) => node.open'))
                self.assertTrue(card.locator('summary .group-recurrence').is_visible())
                self.assertIn('boîtes en défaut',card.locator(':scope > summary').inner_text())
                self.assertIn('18',card.locator(':scope > summary .group-recurrence').inner_text())
                self.assertNotIn('aucun decalage regulier',page.locator('main').inner_text())
                with page.expect_download() as download:
                    page.get_by_role('button',name='Exporter PDF').click()
                pdf_path = output / 'rapport-decalages.pdf'
                download.value.save_as(pdf_path)
                document = pdfium.PdfDocument(pdf_path)
                contents = ' '.join('\n'.join(p.get_textpage().get_text_range() for p in document).split())
                for expected in ('Bilan des mesures de la trace','12 boîtes à -4,0 mm','6 boîtes à -5,0 mm','90,0 %','18,0 %'):
                    self.assertIn(expected,contents)
                document[0].render(scale=1.2).to_pil().save(output/'pdf-decalages-page-1.png')
                document.close()
            page.screenshot(path=str(output/'rapport-decalages.png'),full_page=True)
            browser.close()

    def test_reference_lists_sort_paging_details_and_axis_navigation(self):
        from playwright.sync_api import sync_playwright
        frames=samples(90)
        for i,frame in enumerate(frames):
            box=frame.boxes_on_T5[0]
            barcode='REF-MULTI' if i < 60 else f'REF-{i:03d}'
            box.barcode=box.identified_barcode=box.bdd_reference=barcode
            box.measured_t4_length_mm=95 if i==59 else 105 if i<60 else 106+i-60
            box.measured_t4t_length_mm=box.measured_t4_length_mm+2
            box.measured_t4_diff_mm=-2
        frames[0].boxes_on_T5[0].measured_t5_line=2
        frames[0].raw_lines.append((2,'MAJ FICTIVE largeur et hauteur'))
        output=ROOT/'build'/'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        incidents=build_diagnostics(frames,[])
        report=write_diagnostic_report(incidents,output,frames,source_name='LISTES FICTIVES')
        fallback=output/'secours-listes.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        bridge=ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1080})
                for url in (bridge.register(report),fallback.as_uri()):
                    local=url.startswith('http:')
                    page.goto(url)
                    page.locator('[data-measure-axis=length][data-measure-side=over]').click()
                    panel=page.locator('.measurement-reference-list')
                    self.assertEqual(panel.locator('tbody tr').count(),25)
                    self.assertIn('REF-089',panel.locator('tbody tr').first.inner_text())
                    panel.get_by_role('button',name='Suivants').click()
                    self.assertEqual(panel.locator('tbody tr').count(),6)
                    self._open_reference(page,panel,'REF-MULTI',bridge if local else None)
                    proofs=panel.locator('.reference-proofs > .sample')
                    self.assertEqual(proofs.count(),25)
                    proofs.first.locator('.sample-technical > summary').click()
                    self.assertIn('T4T (complément)',proofs.first.inner_text())
                    self.assertIn('Répétitions et variantes de ce produit',panel.locator('.product-observations').inner_text())
                    panel.get_by_role('button',name='Suivants').click()
                    self.assertEqual(proofs.count(),25)
                    panel.get_by_role('button',name='Suivants').click()
                    self.assertEqual(proofs.count(),9)
                    if local:
                        panel.get_by_role('button',name='Précédents').click()
                        panel.get_by_role('button',name='Précédents').click()
                        received=[]
                        def navigate():
                            target,done,result=bridge.commands.get(timeout=10)
                            received.append(target)
                            result.update(ok=True,line=target['line'])
                            done.set()
                        thread=threading.Thread(target=navigate)
                        thread.start()
                        page.wait_for_function("!document.querySelector('.reference-proofs [data-navigate]').disabled")
                        proofs.locator('[data-navigate]').first.click()
                        page.get_by_role('status').filter(has_text='positionné').wait_for()
                        thread.join(5)
                        self.assertEqual(received[0]['line'],1)
                        self.assertEqual(received[0]['axis'],'length')
                    else:
                        self.assertTrue(proofs.locator('[data-navigate]').first.is_disabled())
                    page.locator('[data-measure-axis=length][data-measure-side=under]').click()
                    self.assertEqual(panel.locator('tbody tr').count(),1)
                    panel.locator('.rare-products > summary').click()
                    self.assertIn('REF-MULTI',panel.inner_text())
                    if not local:
                        import pypdfium2 as pdfium
                        with page.expect_download() as download:
                            page.get_by_role('button',name='Exporter PDF').click()
                        pdf_path=output/'rapport-listes.pdf'
                        download.value.save_as(pdf_path)
                        document=pdfium.PdfDocument(pdf_path)
                        contents='\n'.join(p.get_textpage().get_text_range() for p in document)
                        for expected in ('REF-089','REF-088','REF-087','REF-MULTI','T4C','T4T','diffT4'):
                            self.assertIn(expected,contents)
                        document[0].render(scale=1.2).to_pil().save(output/'pdf-listes-page-1.png')
                        document.close()
                    for width in (1920,1280,850):
                        page.set_viewport_size({'width':width,'height':1080})
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    page.screenshot(path=str(output/'rapport-listes.png'),full_page=True)
                browser.close()
        finally:
            bridge.close()

    def test_signed_ranges_counts_and_plain_explanations_visible(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        output = ROOT / 'build' / 'report-validation'
        output.mkdir(parents=True,exist_ok=True)
        frames = samples(5,0)
        for frame,delta in zip(frames,(6,-4,9,2,-2)):
            frame.boxes_on_T5[0].measured_t4_length_mm += delta
        incidents = build_diagnostics(frames,[])
        incidents.append(DiagnosticIncident(title='T2 eT:-88 - Err: boite deja C4',code='-88',belt='T2',
            severity='warning',count=1,first_line=1,last_line=1,event_lines=[1]))
        report = write_diagnostic_report(incidents,output,frames,source_name='ECARTS FICTIFS')
        fallback = output / 'secours-ecarts.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge',headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1080})
            for path in (report,fallback):
                page.goto(path.as_uri())
                axis = page.locator('[data-open=measurements] [data-axis=length]')
                axis.wait_for(state='visible')
                axis.locator('.measure-details > summary').click()
                text = axis.inner_text()
                for expected in ('2/5','3/5','-4,0','+9,0','+3,7','6,3'):
                    self.assertIn(expected,text)
                self.assertTrue(axis.locator('.measure-details').evaluate('(node) => node.open'))
                self.assertIn('0 boîtes hors tolérance',page.locator('[data-open=measurements] [data-axis=width]').inner_text())
                card = page.locator('details[data-group]').filter(has_text='T2 eT:-88').first
                self.assertFalse(card.evaluate('(node) => node.open'))
                self.assertTrue(card.locator('summary .plain-explanation').is_visible())
                self.assertIn('capteur C4',card.locator('summary .plain-explanation').inner_text())
                self.assertIn('À vérifier en premier',page.locator('main').inner_text())
                pdf_path = output / 'rapport-ecarts.pdf'
                with page.expect_download() as download:
                    page.get_by_role('button',name='Exporter PDF').click()
                download.value.save_as(pdf_path)
                document = pdfium.PdfDocument(pdf_path)
                contents = '\n'.join(p.get_textpage().get_text_range() for p in document)
                for expected in ('-4,0 à +9,0','+3,7','6,3','2/5','3/5','capteur C4'):
                    self.assertIn(expected,contents)
                document[0].render(scale=1.4).to_pil().save(output / 'pdf-ecarts-page-1.png')
                document.close()
            page.screenshot(path=str(output / 'rapport-ecarts.png'),full_page=True)
            browser.close()

    def test_react_fallback_navigation_pagination_and_pdf(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        output = ROOT / 'build' / 'report-validation'
        output.mkdir(parents=True, exist_ok=True)
        frames = samples()
        incidents = build_diagnostics(frames, [])
        report = write_diagnostic_report(incidents, output, frames, source_name='DEMONSTRATION FICTIVE')
        fallback = output / 'secours.html'
        fallback.write_text(build_diagnostic_report_html(incidents, frames), encoding='utf-8')
        bridge = ReportBridge()
        try:
            url = bridge.register(report)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1080})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url)
                page.get_by_role('heading', name='Rapport d’analyse Alpha').wait_for()
                page.locator('details[data-group] > summary').first.click()
                button = page.locator('[data-navigate]').first
                page.wait_for_function("!document.querySelector('[data-navigate]').disabled")
                received = []
                def navigate():
                    target, done, result = bridge.commands.get(timeout=10)
                    received.append(target)
                    result.update(ok=True, line=target['line'])
                    done.set()
                thread = threading.Thread(target=navigate)
                thread.start()
                button.click()
                page.get_by_role('status').filter(has_text='positionné').wait_for()
                thread.join(5)
                self.assertEqual(received[0]['line'], 1)
                self.assertEqual(page.locator('.evidence .sample').count(), 3)
                page.get_by_role('button', name='Voir les 35 exemples').click()
                self.assertEqual(page.locator('.evidence .sample').count(), 25)
                page.get_by_role('button', name='Suivants').click()
                self.assertEqual(page.locator('.evidence .sample').count(), 10)
                page.get_by_role('searchbox').fill('INTROUVABLE')
                page.wait_for_timeout(300)
                self.assertEqual(page.locator('details[data-group]').count(), 0)
                page.get_by_role('searchbox').fill('DEMO-1')
                page.wait_for_timeout(300)
                self.assertEqual(page.locator('details[data-group]').count(), 1)
                with page.expect_download() as download:
                    page.get_by_role('button', name='Exporter PDF').click()
                pdf_path = output / 'rapport.pdf'
                download.value.save_as(pdf_path)
                document = pdfium.PdfDocument(pdf_path)
                contents = '\n'.join(p.get_textpage().get_text_range() for p in document)
                self.assertIn('35', contents)
                self.assertIn('5,0', contents)
                self.assertIn('calibrage', contents)
                document[0].render(scale=1.4).to_pil().save(output / 'pdf-page-1.png')
                document[len(document)-1].render(scale=1.4).to_pil().save(output / 'pdf-derniere-page.png')
                document.close()
                page.locator('[data-open=measurements]').evaluate('(node) => node.open = true')
                page.screenshot(path=str(output / 'rapport-react.png'), full_page=True)
                for width in (1920, 1280, 850):
                    page.set_viewport_size({'width':width,'height':1080})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                bridge.close()
                page.locator('details[data-group]').first.evaluate('(node) => node.open = true')
                page.locator('[data-navigate]').first.click()
                page.get_by_role('status').filter(has_text='fermée').wait_for()
                page.goto(report.as_uri())
                page.get_by_role('heading',name='Rapport d’analyse Alpha').wait_for()
                page.goto(fallback.as_uri())
                page.get_by_role('heading', name='Rapport d’analyse Alpha').wait_for()
                page.locator('details[data-group] > summary').first.click()
                self.assertTrue(page.locator('[data-navigate]').first.is_disabled())
                page.locator('[data-open=measurements]').evaluate('(node) => node.open = true')
                self.assertIn('35', page.locator('[data-open=measurements]').inner_text())
                self.assertFalse(errors, errors)
                browser.close()
        finally:
            bridge.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
