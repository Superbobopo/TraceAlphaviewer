"""Valide les domaines observés, les gravités partagées et le radar web/PDF."""
from dataclasses import asdict
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.diagnostic import DiagnosticIncident, build_diagnostics
from Models.diagnostic_report import build_report_payload, build_diagnostic_report_html, write_diagnostic_report, _field_severity_for
from Models.frame_store import FrameStore, write_frame_store_iter, update_store_metadata
from Models.health_radar import DOMAINS, HealthObservationCollector, build_health_radar, domains_for, merge_health_observations, impact_color, camera_impact_color, measurement_impact_color
from Models.segment_collector import SegmentCollector
from Tools.validate_c2_signal import frames_for


NORMAL = [
    'CB1: ajout Hist_LectCB (lecture n°1 boite n°1 1code(s) lu(s))',
    'tT3/T4: transfert T3->T4 terminé, longueur=100 mm, attend transfert vers T5 (idB=1)',
    "MAJ (APRES-MESURE-LARG) bt IdA:1 'FICTIF' (nvlle lxH:50x30 [x100] X:7800)(BdD:50x30x100)",
    'UDP trame recu du robot (127.0.0.1): @T1@OMEGA:T5-State=FREE',
    'SendCde: envoi cde machine(1): T5C,45 --> Ok',
    'Temps depuis RESET carte ALPHA: 300 mn',
]


class ObservedFrames(list):
    pass


def fixture(complete=True):
    frames = ObservedFrames(frames_for(list(enumerate(NORMAL if complete else NORMAL[:2]))))
    collector = SegmentCollector()
    for frame in frames:
        collector.consume(frame)
    frames.health_observations = collector.health.finish(line_states=collector.lines)
    return frames


def groups(code, severity='error', **extra):
    return dict(id=code+':1:T5', title='Constat fictif '+code, code=code, belt='T5',
                severity=severity, field_severity=severity, **extra)


class HealthRadarTests(unittest.TestCase):
    def test_positive_observations_and_old_data(self):
        observed = fixture().health_observations
        self.assertEqual(observed['counts'], dict.fromkeys((key for key, _, _ in DOMAINS), 1))
        self.assertEqual(build_health_radar(observed, [])['version'], 2)
        self.assertIsNone(build_health_radar({}, []))
        empty = HealthObservationCollector().finish()
        self.assertTrue(all(axis['value'] is None for axis in build_health_radar(empty, [])['axes']))
        self.assertNotIn('health_radar', build_report_payload([], frames_for([])))

    def test_proportions_are_continuous_and_independent_of_severity(self):
        observed = fixture().health_observations
        colors = []
        for ratio in (0, .0129, .1, .5, 1):
            found = build_health_radar(observed, [groups('CAM-NO-READ')],
                                       camera={'unknown':dict(count=ratio*10000,total=10000)},
                                       measurements={'global':dict(outside_count=ratio*10000,count=10000)})
            for index in (0, 2):
                self.assertAlmostEqual(found['axes'][index]['value'], 1-ratio)
            colors.append(found['axes'][0]['color'])
        self.assertEqual(len(set(colors)),4)
        self.assertEqual(impact_color(None),'#929ca7')
        self.assertEqual(domains_for(groups('-18')), ('transfers',))
        self.assertEqual(domains_for(groups('WAIT-INDEX')), ('transfers',))
        json.dumps(found)

    def test_camera_colors_use_unknown_anchors_without_changing_radius(self):
        observed=dict(version=2,duration_seconds=3600)
        for rate in (0,.0129,.08,.1,.12,.194):
            axes=build_health_radar(observed,[],camera={'unknown':dict(count=rate*10000,total=10000)},
                measurements={'global':dict(outside_count=rate*10000,count=10000)})['axes']
            self.assertAlmostEqual(axes[0]['value'],1-rate)
            self.assertEqual(axes[0]['color'],camera_impact_color(rate))
            self.assertEqual(axes[2]['color'],measurement_impact_color(rate*10000,10000))
        self.assertEqual(camera_impact_color(0),'#287c50')
        self.assertEqual(camera_impact_color(.08),'#b57912')
        self.assertEqual(camera_impact_color(.12),'#bf3444')
        self.assertEqual(camera_impact_color(.194),'#bf3444')
        self.assertEqual(camera_impact_color(None),'#929ca7')
        axis=build_health_radar(observed,[],camera={'unknown':dict(count=1194,total=6160)})['axes'][0]
        self.assertAlmostEqual(axis['value'],1-1194/6160)
        self.assertEqual(axis['color'],'#bf3444')

    def test_measurement_alert_and_critical_boundaries_are_strict(self):
        for count,expected in ((0,'#287c50'),(79,None),(80,None),(81,'#b57912'),(150,'#b57912'),(151,'#bf3444')):
            color=measurement_impact_color(count,1000)
            self.assertEqual(color,impact_color(1-count/1000) if expected is None else expected)
            axis=build_health_radar(dict(version=2),[],measurements={'global':dict(outside_count=count,count=1000)})['axes'][2]
            self.assertEqual(axis['color'],color)
            self.assertAlmostEqual(axis['value'],1-count/1000)
        self.assertEqual(measurement_impact_color(0,0),'#929ca7')
        for axis_name in ('length','width','height'):
            summary={'global':dict(outside_count=81,count=1000),'axes':{axis_name:dict(outside_count=81)}}
            self.assertEqual(build_health_radar(dict(version=2),[],measurements=summary)['axes'][2]['color'],'#b57912')

    def test_repeated_transfer_problems_override_small_ratio_only(self):
        observed=dict(version=2,transfers=dict(affected=42,total=1435))
        related=[dict(groups('-88',occurrence_count=38),belt='T2'),
                 dict(groups('-43',occurrence_count=7),belt='T3'),
                 dict(groups('INIT-INDEX',occurrence_count=18),belt='T4')]
        axis=build_health_radar(observed,related)['axes'][1]
        self.assertEqual(axis['color'],'#b57912')
        self.assertAlmostEqual(axis['value'],1-42/1435)
        self.assertEqual((axis['numerator'],axis['denominator']),(42,1435))
        self.assertEqual([item['count'] for item in axis['repeated_problems']],[38,7,18])
        self.assertIn('pas additionnés',' '.join(axis['limits']))
        single=[dict(related[0],occurrence_count=1)]
        self.assertEqual(build_health_radar(observed,single)['axes'][1]['color'],impact_color(1-42/1435))
        for group in related:
            self.assertEqual(build_health_radar(observed,[group])['axes'][1]['color'],'#b57912')
        high=dict(observed,transfers=dict(affected=80,total=100))
        self.assertEqual(build_health_radar(high,related)['axes'][1]['color'],impact_color(.2))
        missing=build_health_radar(dict(version=2),related)['axes'][1]
        self.assertIsNone(missing['value'])
        self.assertEqual(missing['color'],'#929ca7')
        signals=[dict(groups('C5_SIGNAL_ANOMALY',occurrence_count=10000),metrics=dict(blocked_transfer_count=0))]
        self.assertEqual(build_health_radar(observed,signals)['axes'][1]['color'],impact_color(1-42/1435))

    def test_robot_ratio_and_hourly_frequency(self):
        observed = dict(version=2,duration_seconds=3600,robot=dict(box_metrics_version=1,rejected_boxes_count=25,robot_picked_boxes_count=1920))
        for count in (0, 1, 4):
            found = build_health_radar(observed,[groups('MOTOR_COMM',occurrence_count=count),groups('ALPHA_CARD_RESET',occurrence_count=count),groups('DemVidageComplet')])
            self.assertAlmostEqual(found['axes'][3]['rate'],25/1945)
            self.assertEqual(found['axes'][3]['groups'][0]['severity'],'error')
            for axis in found['axes'][4:]:self.assertAlmostEqual(axis['value'],1/(1+count))
        zero = dict(observed,duration_seconds=0,robot={})
        self.assertTrue(all(axis['value'] is None for axis in build_health_radar(zero,[])['axes']))

    def test_transfers_count_cycles_not_messages_and_respect_reuse(self):
        from Models.state import BoxInfo, MachineState, MachineEvent
        collector=SegmentCollector()
        for line in (1,2,3,5):
            if line==5:
                collector.consume(MachineState(line_num=4,timestamp=4,timestamp_str='09:00:04',raw_lines=[(4,'version logiciel VBalpha: FICTIF')]))
            event=MachineEvent(line,float(line),'09:00:00','error','T3','T3 en erreur eT:-49')
            collector.consume(MachineState(line_num=line,timestamp=float(line),timestamp_str='09:00:00',box_on_T3=BoxInfo(id_b=42),
                raw_lines=[(line,'transfert (EA->T3) termine')],events=[event]))
        incident=DiagnosticIncident('error','T3 bloque','T3','-49',first_line=1,event_lines=[1,2,3,5])
        result=collector.health.finish([incident],collector.lines)
        self.assertEqual(result['transfers']['affected'],2)
        self.assertEqual(result['transfers']['total'],2)
        combined=merge_health_observations([result,result])
        self.assertEqual(combined['transfers']['affected'],4)
        self.assertEqual(combined['transfers']['total'],4)

    def test_coverage_excludes_gaps_and_partial_results_remain_explicit(self):
        from Models.state import MachineState
        collector=SegmentCollector()
        for line,stamp in enumerate((0,60,1000,1060),1):
            collector.consume(MachineState(line_num=line,timestamp=stamp,timestamp_str='09:00:00',raw_lines=[(line,'transfert T3->T4 termine')]))
        incident=DiagnosticIncident('error','T3 bloque','T3','-49',first_line=1,event_lines=[1])
        result=collector.health.finish([incident],collector.lines)
        self.assertEqual(result['duration_seconds'],120)
        axis=build_health_radar(result,[])['axes'][1]
        self.assertIsNone(axis['value'])
        self.assertEqual(axis['unattributed_episodes'],1)
        self.assertGreater(axis['unattributed_transfers'],0)
        self.assertTrue(any('partielle' in item for item in axis['limits']))
        self.assertIsNone(build_health_radar({'version':1,'counts':{}},[])['axes'][1]['value'])

    def test_initialization_does_not_invent_transfer_exposure(self):
        from Models.state import BoxInfo, MachineState, MachineEvent
        collector=SegmentCollector()
        event=MachineEvent(1,0,'09:00:00','error','T4','T4 en erreur eT:-17')
        collector.consume(MachineState(line_num=1,box_on_T4=BoxInfo(id_b=1),raw_lines=[(1,event.title)],events=[event]))
        incident=DiagnosticIncident('error',event.title,'T4','-17',first_line=1,event_lines=[1])
        transfers=collector.health.finish([incident],collector.lines)['transfers']
        self.assertEqual(transfers['total'],0)
        self.assertEqual(transfers['affected'],0)
        self.assertEqual(transfers['unattributed_episodes'],1)
        banner=MachineState(line_num=2,raw_lines=[(2,'version logiciel VBalpha: FICTIF')])
        collector.consume(banner)
        context=collector.health._context
        collector.consume(banner)
        self.assertEqual(collector.health._context,context)

    def test_unequal_segments_are_weighted_before_division(self):
        first=dict(version=2,duration_seconds=3600,counts={},transfers=dict(affected=1,total=10),
                   robot=dict(box_metrics_version=1,rejected_boxes_count=1,robot_picked_boxes_count=9))
        second=dict(version=2,duration_seconds=7200,counts={},transfers=dict(affected=3,total=100),
                    robot=dict(box_metrics_version=1,rejected_boxes_count=3,robot_picked_boxes_count=97))
        merged=merge_health_observations([first,second])
        axes=build_health_radar(merged,[groups('MOTOR_COMM',occurrence_count=3)],
            measurements={'global':dict(outside_count=1,count=10),
                          'axes':{'length':dict(outside_count=1),'width':dict(outside_count=1)}})['axes']
        self.assertAlmostEqual(axes[1]['rate'],4/110)
        self.assertAlmostEqual(axes[3]['rate'],4/110)
        self.assertAlmostEqual(axes[4]['value'],.5)
        self.assertAlmostEqual(axes[2]['rate'],.1)
        self.assertIsNone(build_health_radar(merged,[],camera={'unknown':dict(count=11,total=10)})['axes'][0]['value'])

    def test_collector_deduplicates_and_store_is_optional(self):
        frames = fixture()
        collector = SegmentCollector()
        for frame in frames:
            collector.consume(frame)
            collector.consume(frame)
        self.assertEqual(collector.health.finish()['counts'], frames.health_observations['counts'])
        with tempfile.TemporaryDirectory() as directory:
            write_frame_store_iter(iter(frames), directory)
            with FrameStore(directory) as store:
                self.assertEqual(store.health_observations, {})
            update_store_metadata(directory, health_observations=frames.health_observations)
            with FrameStore(directory) as store:
                self.assertEqual(store.health_observations, frames.health_observations)

    def test_group_and_single_have_identical_domains(self):
        from Tools.validate_folder_groups import FolderGroupsTests
        from Models.group_analysis import analyze_group
        helper = FolderGroupsTests()
        helper.setUp()
        try:
            first = helper.source('jour1','2026-10-28T09:00:00',NORMAL)
            second = helper.source('jour2','2026-10-29T09:00:00',NORMAL)
            single = analyze_group([first], helper.root/'single')
            combined = analyze_group([first,second], helper.root/'group')
            with FrameStore(single['store']) as store:
                one = store.health_observations
                axes = build_report_payload(single['diagnostics'], store)['health_radar']['axes']
            with FrameStore(combined['store']) as store:
                two = store.health_observations
                merged = build_report_payload(combined['diagnostics'], store)['health_radar']['axes']
            self.assertEqual(two, merge_health_observations([one,one]))
            self.assertEqual([a['value'] for a in axes], [a['value'] for a in merged])
        finally:
            helper.tearDown()

    def test_browser_fallback_react_pdf_and_legacy(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        frames = fixture()
        incident = DiagnosticIncident('error','T5 en défaut fictif','T5','T5_DRIVE_SUSPECTED',
            first_line=2,last_line=3,count=1,summary='Transfert et mesures impossibles',
            metrics={'t5_drive_metrics_version':1,'cycle_count':1,'cycle':{}})
        payload = build_report_payload([incident], frames)
        expected = {a['id']:a['color'] for a in payload['health_radar']['axes']}
        partial = build_report_payload([incident], fixture(False))
        empty = dict(payload, health_radar=build_health_radar(HealthObservationCollector().finish(), []))
        legacy = dict(payload)
        legacy.pop('health_radar')
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory, sync_playwright() as pw:
            out = Path(directory)
            report = write_diagnostic_report([incident],out,frames,source_name='RADAR FICTIF')
            paths = [report]
            for name,data in [('complete',payload),('partial',partial),('empty',empty),('legacy',legacy),('v1',dict(payload,health_radar={'version':1}))]:
                path = out/(name+'.html')
                path.write_text(build_diagnostic_report_html([],payload=data),encoding='utf-8')
                paths.append(path)
            browser = pw.chromium.launch(channel='msedge',headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1080},reduced_motion='reduce')
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            for index,path in enumerate(paths):
                page.goto(path.as_uri())
                if path.name=='legacy.html':
                    self.assertEqual(page.locator('.health-overview').count(),0)
                    continue
                if path.name=='v1.html':
                    self.assertIn('régénérer',page.locator('.health-legacy').inner_text())
                    self.assertEqual(page.locator('.health-overview').count(),0)
                    self.assertNotIn('has-health',page.locator('.priorities').get_attribute('class'))
                    continue
                self.assertEqual(page.locator('.priorities .health-label').count(),6)
                self.assertEqual(page.locator('.health-detail').count(),0)
                if index<2:
                    for axis,color in expected.items():
                        self.assertEqual(color,page.locator(f'.health-label[data-health-axis="{axis}"]').get_attribute('fill'))
                    page.locator('.health-label[data-health-axis="transfers"]').click()
                    page.locator('.health-links button').first.click()
                    self.assertTrue(page.locator('details[data-group^="T5_DRIVE_SUSPECTED:"]').evaluate('e=>e.open'))
                else:
                    self.assertEqual(page.locator('.health-shape').count(),0)
                if index==0:
                    with page.expect_download() as downloaded:
                        page.get_by_role('button',name='Exporter PDF').click()
                    pdf=out/'radar.pdf'
                    downloaded.value.save_as(pdf)
                    document=pdfium.PdfDocument(pdf)
                    content='\n'.join(document[i].get_textpage().get_text_range() for i in range(len(document)))
                    self.assertIn('Bilan de l',content)
                    self.assertIn('CRITIQUE',content)
                    self.assertLessEqual(len(document),6)
                    document.close()
                page.set_viewport_size({'width':480,'height':900})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                page.set_viewport_size({'width':1440,'height':1080})
            self.assertFalse(errors,errors)
            browser.close()

    def test_compact_layout_and_robot_example_at_four_widths(self):
        from playwright.sync_api import sync_playwright
        observed = dict(version=2,duration_seconds=3600,
                        transfers=dict(affected=1,total=100),
                        robot=dict(box_metrics_version=1,rejected_boxes_count=25,robot_picked_boxes_count=1920))
        frames=fixture()
        incident=DiagnosticIncident('error','Incident critique fictif','T5','T5_DRIVE_SUSPECTED',first_line=2,count=1,
                                    metrics=dict(t5_drive_metrics_version=1,cycle_count=1,cycle={}))
        payload=build_report_payload([incident],frames)
        before=[(row['code'],row['field_severity'],row['field_priority']) for row in payload['priority']]
        payload['unknown']=dict(count=33,total=1996)
        payload['health_radar']=build_health_radar(observed,[groups('DemVidageComplet')],
            camera={'unknown':payload['unknown']},measurements={'global':dict(outside_count=10,count=100)})
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory, sync_playwright() as pw:
            browser=pw.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page()
            for card_count in range(4):
                variant=dict(payload,priority=[dict(payload['priority'][0],id=f'fictif-{i}',title=f'Priorité fictive {i+1}') for i in range(card_count)])
                path=Path(directory)/f'impact-{card_count}.html'
                path.write_text(build_diagnostic_report_html([],payload=variant),encoding='utf8')
                page.goto(path.as_uri())
                self.assertFalse(page.locator('.status').is_visible())
                self.assertEqual(page.locator('.health-overview .priority-number').count(),0)
                self.assertEqual(page.locator('.priority-grid > button').count(),card_count)
                self.assertEqual(page.locator('.priority-grid > :last-child').get_attribute('class'),'health-overview')
                for width in (1440,1200,900,480):
                    page.set_viewport_size(dict(width=width,height=1080))
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    badge=page.locator('.unknown-counter')
                    self.assertIn('33 / 1\u202f996',badge.inner_text())
                    self.assertLessEqual(badge.bounding_box()['height'],32)
                    self.assertTrue(badge.evaluate("e=>e.scrollWidth<=e.clientWidth"))
                    cards=page.locator('.priority-grid > *')
                    columns=min(card_count+1,4 if width>=1100 else 2 if width>=700 else 1)
                    rectangles=[cards.nth(i).bounding_box() for i in range(cards.count())]
                    radar_box=page.locator('.health-overview').bounding_box()
                    self.assertGreaterEqual(page.locator('.health-svg').bounding_box()['height'],120)
                    for label in page.locator('.health-label').all():
                        bounds=label.bounding_box()
                        self.assertGreaterEqual(bounds['x'],radar_box['x'])
                        self.assertLessEqual(bounds['x']+bounds['width'],radar_box['x']+radar_box['width'])
                    for i,rect in enumerate(rectangles):
                        self.assertAlmostEqual(rect['y'],rectangles[i-i%columns]['y'],delta=2)
                        if i%columns:self.assertGreaterEqual(rect['x'],rectangles[i-1]['x']+rectangles[i-1]['width'])
                    for card in page.locator('.priority-grid > button').all():
                        badge_box=card.locator('.badge').bounding_box()
                        title_box=card.locator(':scope > strong').bounding_box()
                        self.assertLess(title_box['y']-badge_box['y']-badge_box['height'],40,
                            (card_count,width,page.locator('.priority-grid').evaluate('e=>getComputedStyle(e).gridTemplateRows')))
                    if card_count==3 and width>=1100:
                        self.assertAlmostEqual(rectangles[-1]['height'],rectangles[0]['height'],delta=2)
                    if width>=1100:
                        title=page.locator('.priority-heading .section-heading').bounding_box()
                        self.assertGreaterEqual(badge.bounding_box()['x'],title['x']+title['width'])
            point=page.locator('.health-point[data-health-axis="robot"]')
            self.assertAlmostEqual(float(point.get_attribute('data-value')),1-25/1945)
            point.click()
            self.assertIn('1,29 %',page.locator('.health-detail h3').inner_text())
            self.assertIn('Critique',page.locator('.health-detail').inner_text())
            page.locator('[data-health-close]').click()
            self.assertEqual(page.locator('.health-detail').count(),0)
            self.assertEqual(before,[(row['code'],row['field_severity'],row['field_priority']) for row in payload['priority']])
            browser.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
