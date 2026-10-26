"""Valide l'identite pharmacie/Alpha et sa presentation web/PDF."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'TraceAlphaViewer'))
from Models.folder_catalog import read_source_identity
from Models.frame_store import FrameStore
from Models.loading_worker import run
from Models.diagnostic_report import write_diagnostic_report, build_diagnostic_report_html, build_report_payload


class IdentityTests(unittest.TestCase):
    def test_identification_and_worker_metadata(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            path=Path(directory)/'fictif.old'
            def trace(alpha='BASEALPHA_#2025.031.MDB', pharmacy='BASEFIC1560LAHLOU.MDB'):
                return ('22|09:00:00.0 OUVERTURE DE LA TRACE le 22/10/2026\n'
                        f'22|09:00:00.1 C:\\APOTEKA\\{alpha}\n'
                        f'22|09:00:00.2 C:\\APOTEKA\\{pharmacy}\n'
                        '22|09:00:01.0 T5: WAIT-COND\n')
            path.write_text(trace(),encoding='latin-1')
            identity=read_source_identity(path)
            self.assertEqual((identity['pharmacy'],identity['alpha_number']),('Lahlou','031'))
            messages=[]
            run({'mode':'file','path':str(path),'session':directory},lambda key,value:messages.append((key,value)))
            entry=next(value for key,value in messages if key=='entry')
            with FrameStore(entry['store']) as frames:
                self.assertEqual(frames.source_metadata['identity'],identity)
                self.assertEqual(build_report_payload([],frames)['source']['identity'],identity)
            path.write_text(trace('basealpha2_#2025.009.mdb','baseficmotte.mdb'),encoding='latin-1')
            self.assertEqual(read_source_identity(path)['alpha_number'],'009')
            path.write_text(trace('BASEALPHA2_LOCALE.MDB'),encoding='latin-1')
            self.assertIsNone(read_source_identity(path)['alpha_number'])
            path.write_text(trace()+'22|09:02:00.0 BASEALPHA_#2025.009.MDB\n',encoding='latin-1')
            self.assertIsNone(read_source_identity(path))
            path.write_text(trace(pharmacy='inconnue'),encoding='latin-1')
            self.assertIsNone(read_source_identity(path))

    def test_browser_pdf_legacy_and_long_names(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        from Tools.validate_c5_signal import frames_for,fixture
        from Models.diagnostic import build_diagnostics
        class Frames(list):pass
        frames=Frames(frames_for(fixture()))
        frames.source_metadata={'identity':{'alpha_database':'BASEALPHA_#2025.031.MDB',
            'pharmacy_database':'BASEFIC1560LAHLOU.MDB','pharmacy':'Lahlou','alpha_number':'031'}}
        incidents=build_diagnostics(frames,[])
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory, sync_playwright() as pw:
            report=write_diagnostic_report(incidents,Path(directory),frames,source_name='DEMONSTRATION FICTIVE')
            fallback=Path(directory)/'fallback.html'
            fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
            browser=pw.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':900})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            for url in (report.as_uri(),fallback.as_uri()):
                page.goto(url)
                header=page.locator('.hero')
                self.assertIn('Pharmacie Lahlou',header.inner_text())
                self.assertIn('Alpha 031',header.inner_text())
                self.assertEqual(page.locator('h1').inner_text(),'Rapport d’analyse Alpha')
                page.locator('.hero').screenshot(path=str(ROOT/'build/report-identity-header.png'))
                for width in (1440,850,390):
                    page.set_viewport_size({'width':width,'height':900})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                with page.expect_download() as download:page.locator('[data-pdf]').click()
                path=Path(directory)/'rapport.pdf';download.value.save_as(path)
                pdf=pdfium.PdfDocument(path)
                text='\n'.join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
                self.assertIn('Pharmacie Lahlou',text);self.assertIn('Alpha 031',text)
                pdf.close()
            frames.source_metadata['identity']['pharmacy']='Pharmacie avec un nom particulièrement long et plusieurs communes associées'
            frames.source_metadata['identity']['alpha_number']=None
            frames.source_metadata['identity']['alpha_database']='BASEALPHA2_LOCALE_TRES_LONGUE.MDB'
            fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
            page.goto(fallback.as_uri())
            self.assertIn('BASEALPHA2_LOCALE_TRES_LONGUE.MDB',page.locator('.hero').inner_text())
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            frames.source_metadata={}
            fallback.write_text(build_diagnostic_report_html(incidents,frames),encoding='utf-8')
            page.goto(fallback.as_uri())
            self.assertEqual(page.locator('.hero-identity').count(),0)
            self.assertFalse(errors)
            browser.close()


if __name__=='__main__':unittest.main(verbosity=2)
