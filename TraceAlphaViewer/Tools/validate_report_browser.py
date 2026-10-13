"""Verifie le rapport React, le secours hors ligne et le PDF sur donnees fictives."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Tools.validate_measurement_report import samples, recurring_samples, product_samples
from Models.diagnostic import build_diagnostics, DiagnosticIncident
from Models.diagnostic_report import write_diagnostic_report, build_diagnostic_report_html
from Models.report_bridge import ReportBridge


class BrowserTests(unittest.TestCase):
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
                    text=page.locator('[data-axis=length] .recurrence').inner_text()
                    for expected in ('6 défauts','5 mesures conformes voisines','11 mesures','3 produits'):
                        self.assertIn(expected,text)
                    page.locator('[data-measure-axis=length][data-measure-side=under]').click()
                    panel=page.locator('.measurement-reference-list')
                    self.assertIn('Plusieurs variantes BdD',panel.inner_text())
                    panel.get_by_role('button',name='PRODUIT-A',exact=True).click()
                    observation=panel.locator('.product-observations')
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
                    contents=' '.join('\n'.join(p.get_textpage().get_text_range() for p in document).split())
                    for expected in ('5 mesures conformes voisines','Plusieurs variantes BdD','6/6','0/4'):
                        self.assertIn(expected,contents)
                    document.close()
                    page.locator('[data-measure-axis=length][data-measure-side=under_group]').click()
                    self.assertEqual(panel.locator('tbody > tr').count(),3)
                    panel.get_by_role('button',name='PRODUIT-C',exact=True).click()
                    self.assertIn('Toutes les mesures comparables de ce produit',panel.inner_text())
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
                text = axis.locator('.recurrence').inner_text()
                for expected in ('12 boîtes à -4,0 mm','6 boîtes à -5,0 mm','18','90,0 %','18,0 %'):
                    self.assertIn(expected,text)
                self.assertNotIn('réglage/calibrage',text)
                self.assertFalse(axis.locator('.measure-details').evaluate('(node) => node.open'))
                axis.locator('.measure-details > summary').click()
                distribution = axis.locator('.measurement-distribution')
                self.assertEqual(distribution.locator('tbody tr').count(),4)
                self.assertIn('80',distribution.inner_text())
                self.assertIn('0,0 mm',distribution.inner_text())
                card = page.locator('details[data-group]').first
                self.assertFalse(card.evaluate('(node) => node.open'))
                self.assertTrue(card.locator('summary .recurrence').is_visible())
                self.assertIn('Bilan des mesures de la trace',card.locator(':scope > summary').inner_text())
                self.assertIn('18',card.locator(':scope > summary .recurrence').inner_text())
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
                    panel.get_by_role('button',name='REF-MULTI',exact=True).click()
                    proofs=panel.locator('.reference-proofs > .sample')
                    self.assertEqual(proofs.count(),25)
                    self.assertIn('T4T (complément)',proofs.first.inner_text())
                    self.assertIn('Mesures de ce produit dans la trace',panel.locator('.product-observations').inner_text())
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
        for frame,delta in zip(frames,(6,-4,9,3,-3)):
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
                text = axis.inner_text()
                for expected in ('2/5','3/5','-4,0 à +9,0 mm','+3,7','6,3'):
                    self.assertIn(expected,text)
                self.assertFalse(axis.locator('.measure-details').evaluate('(node) => node.open'))
                self.assertIn('Aucune mauvaise mesure',page.locator('[data-open=measurements] [data-axis=width]').inner_text())
                card = page.locator('details[data-group]').filter(has_text='T2 eT:-88').first
                self.assertFalse(card.evaluate('(node) => node.open'))
                self.assertTrue(card.locator('summary .plain-explanation').is_visible())
                self.assertIn('capteur C4',card.locator('summary .plain-explanation').inner_text())
                self.assertIn('Points à vérifier en premier',page.locator('main').inner_text())
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
                page.get_by_role('heading', name='Comprendre cette trace').wait_for()
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
                page.locator('[data-open=measurements] > summary').click()
                page.screenshot(path=str(output / 'rapport-react.png'), full_page=True)
                for width in (1920, 1280, 850):
                    page.set_viewport_size({'width':width,'height':1080})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                bridge.close()
                page.locator('details[data-group]').first.evaluate('(node) => node.open = true')
                page.locator('[data-navigate]').first.click()
                page.get_by_role('status').filter(has_text='fermée').wait_for()
                page.goto(report.as_uri())
                page.get_by_role('heading',name='Comprendre cette trace').wait_for()
                page.goto(fallback.as_uri())
                page.get_by_role('heading', name='Comprendre cette trace').wait_for()
                page.locator('details[data-group] > summary').first.click()
                self.assertTrue(page.locator('[data-navigate]').first.is_disabled())
                page.locator('[data-open=measurements] > summary').click()
                self.assertIn('35', page.locator('[data-open=measurements]').inner_text())
                self.assertFalse(errors, errors)
                browser.close()
        finally:
            bridge.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
