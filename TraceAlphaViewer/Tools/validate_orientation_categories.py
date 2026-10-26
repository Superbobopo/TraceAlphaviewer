"""Verifie la periode du rapport et les categories d'orientation sans doubles comptes."""
from pathlib import Path
from datetime import datetime, timedelta
import pickle
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.dimension_check import orientation_category, measurement_orientation
from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Models.frame_store import FrameStore, write_frame_store
from Models.measurement_analysis import analyze_measurements
from Models.robot_drain import trace_period
from Tools.validate_measurement_report import samples


def category_frames():
    values = [(100,30,60)]*3 + [(30,60,100)]*2 + [(30,100,60),(80,30,80)] + [(60,30,100)]*3
    values += [(100,30,60)]*26
    frames = samples(len(values),0)
    for i,(frame,measured) in enumerate(zip(frames,values)):
        box = frame.boxes_on_T5[0]
        box.barcode = box.identified_barcode = box.bdd_reference = 'PARTAGE-FICTIF' if i<10 else f'ROTATION-FICTIVE-{i-10:02d}'
        box.name = box.identified_name = 'PRODUIT FICTIF'
        box.measured_t5_width_mm,box.measured_t5_height_mm,box.measured_t4_length_mm = measured
        frame.timestamp = i*5400
    return frames


class OrientationCategoryTests(unittest.TestCase):
    def test_simple_compound_equal_and_tied_dimensions(self):
        expected = (60,30,100)
        for measured,category in (((100,30,60),'flat_rotation'),((30,60,100),'on_edge'),
                                  ((30,100,60),'other'),((60,100,30),'other'),((30,40,30),'other')):
            self.assertEqual(measurement_orientation(measured,expected),'orientation')
            self.assertEqual(orientation_category(measured,expected),category)
        self.assertEqual(orientation_category((30,60,60),(60,30,60)),'other')
        self.assertEqual(measurement_orientation((80,30,80),expected),'orientation_uncertain')

    def test_categories_keep_denominators_exclusions_and_variants(self):
        result = analyze_measurements(category_frames())
        refs = result['orientation_references']
        count = lambda kind:sum(row['count'] for row in refs[kind])
        self.assertEqual([count(kind) for kind in ('flat_rotation','on_edge','other','uncertain')],[29,2,1,1])
        self.assertEqual(count('probable'),32)
        self.assertEqual(result['summary']['comparable_count'],3)
        self.assertEqual(result['summary']['excluded']['orientation'],32)
        self.assertEqual(result['summary']['excluded']['orientation_uncertain'],1)
        cycles=[]
        for kind,expected_count in (('flat_rotation',3),('on_edge',2),('other',1),('uncertain',1)):
            row=next(row for row in refs[kind] if row['barcode']=='PARTAGE-FICTIF')
            self.assertEqual((row['count'],row['total'],row['percent']),(expected_count,10,expected_count*10))
            for sample in row['samples']:
                self.assertEqual(sample['orientation_category'],kind)
                cycles.append(sample['cycle'])
        self.assertEqual(len(cycles),len(set(cycles)))
        frames=category_frames()
        box=frames[1].boxes_on_T5[0]
        box.bdd_width_mm=61
        variants=analyze_measurements(frames)['orientation_references']
        self.assertEqual(variants['flat_rotation'][0]['variant_count'],2)
        self.assertEqual(variants['flat_rotation'][0]['total'],10)

    def test_worker_period_without_robot_and_calendar_rollovers(self):
        from Models.loading_worker import run
        cases = [('13/02/2026','13|09:00:00.2','15|12:00:00.2','51 h 00 min 00 s','15/02/2026'),
                 ('31/12/2026','31|23:30:00.2','01|00:30:00.2','1 h 00 min 00 s','01/01/2027'),
                 ('28/02/2024','28|23:30:00.2','01|00:30:00.2','25 h 00 min 00 s','01/03/2024')]
        for date,first,last,duration,end in cases:
            with self.subTest(date=date),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'fictive.old'
                path.write_text(f'creation de la trace le {date}\n* {first} OUVERTURE DE LA TRACE le {date}\n{last} Fin\n',encoding='latin-1')
                messages=[]
                run({'mode':'file','path':str(path),'session':str(Path(directory)/'session')},
                    lambda kind,value:messages.append((kind,value)))
                entry=next(value for kind,value in messages if kind=='entry')
                incidents=[item for kind,batch in messages if kind=='diagnostics' for item in batch]
                self.assertFalse(any(item.code=='DemVidageComplet' for item in incidents))
                with FrameStore(entry['store']) as store:
                    self.assertFalse(store._cache)
                    payload=build_report_payload(incidents,store)
                    self.assertFalse(store._cache)
                    self.assertTrue(payload['source']['dates_available'])
                    self.assertTrue(payload['source']['start'].startswith(date))
                    self.assertTrue(payload['source']['end'].startswith(end))
                    self.assertEqual(payload['source']['duration'],duration)

    def test_old_session_without_period(self):
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory)
            write_frame_store(samples(2,0),directory)
            path=directory/'index.pkl'
            metadata=pickle.loads(path.read_bytes());metadata.pop('trace_period')
            path.write_bytes(pickle.dumps(metadata))
            with FrameStore(directory) as store:
                source=build_report_payload([],store)['source']
                self.assertFalse(source['dates_available'])
                self.assertEqual(source['start'],'Dates indisponibles')

    def test_browser_category_preview_navigation_and_pdf(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        from Models.report_bridge import ReportBridge
        from Models.measurement_navigation import measurement_box_in_frame
        frames=category_frames();incidents=build_diagnostics(frames,[])
        period=trace_period(datetime(2026,2,13,9),datetime(2026,2,13,9)+timedelta(seconds=frames[-1].timestamp))
        output=ROOT/'build'/'orientation-category-validation';output.mkdir(parents=True,exist_ok=True)
        report=write_diagnostic_report(incidents,output,frames,source_name='DONNEES FICTIVES',trace_period=period)
        fallback=output/'fallback.html'
        fallback.write_text(build_diagnostic_report_html(incidents,frames,trace_period=period),encoding='utf-8')
        bridge=ReportBridge()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1100})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                for url in (bridge.register(report),fallback.as_uri()):
                    page.goto(url)
                    local=url.startswith('http:')
                    if local:page.get_by_role('status').filter(has_text='Liaison avec').wait_for()
                    self.assertIn('13/02/2026',page.locator('.hero-period').inner_text())
                    self.assertIn('15/02/2026',page.locator('.hero-period').inner_text())
                    self.assertIn('52 h 30 min 00 s',page.locator('.hero-duration').inner_text())
                    preview=page.locator('.orientation-preview')
                    self.assertEqual(preview.locator('tbody tr').count(),4)
                    self.assertEqual(preview.locator('.orientation-tag').count(),4)
                    self.assertEqual(page.locator('.orientation-category').count(),3)
                    flat=page.locator('[data-orientation-category=flat_rotation]')
                    received=[]
                    def receive():
                        target,done,result=bridge.commands.get(timeout=5)
                        received.append(target);result.update(ok=True,line=target['line']);done.set()
                    thread=threading.Thread(target=receive) if local else None
                    if thread:thread.start()
                    preview.get_by_role('button',name='PARTAGE-FICTIF',exact=True).first.click()
                    if thread:thread.join(5)
                    self.assertTrue(flat.evaluate('node=>node.open'))
                    self.assertIn('3/10',flat.inner_text())
                    self.assertEqual(flat.locator('.orientation-proofs>.sample').count(),3)
                    if local:self.assertEqual(measurement_box_in_frame(frames[0],received[0]['sample']).id_alpha,100)
                    flat.get_by_role('button',name='Retour aux références').click()
                    self.assertEqual(flat.locator('tbody tr').count(),25)
                    flat.get_by_role('button',name='Suivants',exact=True).click()
                    self.assertEqual(flat.locator('tbody tr').count(),2)
                    edge=page.locator('[data-orientation-category=on_edge]')
                    edge.locator('summary').first.click()
                    self.assertIn('bien à plat',edge.inner_text())
                    self.assertIn('restitution du robot',edge.inner_text())
                    self.assertIn('rebond',edge.inner_text())
                    received.clear()
                    thread=threading.Thread(target=receive) if local else None
                    if thread:thread.start()
                    edge.get_by_role('button',name='PARTAGE-FICTIF',exact=True).click()
                    if thread:thread.join(5)
                    self.assertIn('2/10',edge.inner_text())
                    if local:self.assertEqual(measurement_box_in_frame(frames[3],received[0]['sample']).id_alpha,103)
                    page.locator('.orientations').screenshot(path=str(output/'categories.png'))
                    page.set_viewport_size({'width':390,'height':1000})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    page.set_viewport_size({'width':1440,'height':1100})
                    with page.expect_download() as download:page.locator('[data-pdf]').click()
                    pdf=output/'rapport.pdf';download.value.save_as(pdf)
                    document=pdfium.PdfDocument(pdf)
                    text=' '.join(' '.join(page.get_textpage().get_text_range() for page in document).split())
                    for expected in ('13/02/2026','Longueur / largeur','Largeur / hauteur','Autres permutations','Orientations indécidables','restitution du robot','3/10','2/10'):
                        self.assertIn(expected,text)
                    document.close()
                self.assertFalse(errors,errors)
                browser.close()
        finally:bridge.close()


if __name__=='__main__':
    unittest.main()
