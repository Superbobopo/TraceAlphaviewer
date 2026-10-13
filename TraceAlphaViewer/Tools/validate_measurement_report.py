"""Regressions des mesures, de la legende et de la liaison locale du rapport."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch, Mock
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.state import BoxInfo, MachineState
from Models.dimension_check import MEASUREMENT_STYLES, measurement_status_from_code
from Models.measurement_analysis import analyze_measurements, representative_samples, summary_text, reference_page
from Models.diagnostic import build_diagnostics, DiagnosticIncident
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Models.report_bridge import ReportBridge
from Parser.trace_parser import _classify_alpha_measurement, _update


def samples(count=35, delta=5):
    frames = []
    for i in range(count):
        line = i * 3 + 1
        box = BoxInfo(id_alpha=100 + i, barcode=f'DEMO-{i % 2}', name='PRODUIT FICTIF',
            identified_barcode=f'DEMO-{i % 2}', identified_name='PRODUIT FICTIF',
            identity_line=line, identity_source='CB2', bdd_reference=f'DEMO-{i % 2}', bdd_source_line=line,
            measured_t4_line=line, measured_t5_line=line, measured_height_line=line,
            bdd_length_mm=100, bdd_width_mm=60, bdd_height_mm=30,
            measured_t4_length_mm=100 + delta, measured_t5_width_mm=60, measured_t5_height_mm=30,
            length_mm=100, width_mm=60, height_mm=30, x_pos=942)
        _classify_alpha_measurement(box)
        line = i * 3 + 1
        frames.append(MachineState(line_num=line, timestamp=i, timestamp_str=f'09:00:{i:02d}',
            boxes_on_T5=[box], raw_lines=[(line, f'DONNEES FICTIVES boite {i} longueur {100+delta} BdD 100')]))
    return frames


def recurring_samples():
    frames = samples(100, 0)
    for i, (frame, delta) in enumerate(zip(frames, [-4] * 12 + [-5] * 6 + [-20] * 2 + [0] * 80)):
        frame.boxes_on_T5[0].measured_t4_length_mm += delta
        frame.timestamp_str = f'09:{i // 60:02d}:{i % 60:02d}'
        frame.raw_lines = [(frame.line_num,f'DONNEES FICTIVES boite {i} T4C={100+delta} mm BdD=100 mm')]
    return frames


def product_samples(groups):
    """Construit des cycles fictifs par produit et variante BdD."""
    frames = samples(sum(len(group[1]) for group in groups), 0)
    position = 0
    for group in groups:
        barcode, deltas = group[:2]
        expected = group[2] if len(group) > 2 else (60, 30, 100)
        for delta in deltas:
            frame = frames[position]
            box = frame.boxes_on_T5[0]
            box.barcode = box.identified_barcode = box.bdd_reference = barcode
            box.name = box.identified_name = f'PRODUIT FICTIF {barcode}'
            box.bdd_width_mm, box.bdd_height_mm, box.bdd_length_mm = expected
            box.measured_t5_width_mm, box.measured_t5_height_mm = expected[:2]
            box.measured_t4_length_mm = expected[2] + delta
            frame.timestamp_str = f'09:{position // 60:02d}:{position % 60:02d}'
            frame.raw_lines = [(frame.line_num,
                f'DONNEES FICTIVES {barcode} T4C={expected[2]+delta} BdD={expected[2]}')]
            _classify_alpha_measurement(box)
            position += 1
    return frames


class MeasurementTests(unittest.TestCase):
    def test_repeated_offsets_with_good_measures_extremes_and_worker_payload(self):
        frames = recurring_samples()
        analysis = analyze_measurements(frames)
        axis = analysis['summary']['axes']['length']
        self.assertIsNone(axis['bias'])
        below = axis['recurrence']['under']
        self.assertEqual([(v['delta'],v['count']) for v in below['frequencies']], [(-4,12),(-5,6),(-20,2)])
        group = below['cluster']
        self.assertEqual((group['center'],group['min_signed'],group['max_signed'],group['count']),(-4,-5,-4,18))
        self.assertEqual((group['bad_count'],group['good_count']),(18,0))
        self.assertEqual((group['percent_side'],group['percent_bad'],group['percent_all']),(90,90,18))
        self.assertEqual(group['references'],2)
        self.assertFalse(group['similar'])
        self.assertFalse(group['shared'])
        self.assertEqual(group['repeated_references'],0)
        self.assertEqual(axis['product_observations']['dispersed_references'],0)
        self.assertNotIn('calibrage',group['advice'])
        self.assertNotIn('patinage',' '.join(axis['interpretation']))
        self.assertNotIn('parasite',' '.join(axis['interpretation']))
        text = summary_text(analysis['summary'])
        for expected in ('12 boîtes à -4,0 mm','6 boîtes à -5,0 mm','90,0 %','18,0 %'):
            self.assertIn(expected,text)
        self.assertNotIn('aucun decalage regulier',text)
        payload = build_report_payload(build_diagnostics(frames,[]),frames)
        self.assertEqual(payload['measurements'],analysis['summary'])
        self.assertEqual(payload['groups'][0]['measurement_stats'],analysis['summary'])
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        root = ctk.CTk()
        root.withdraw()
        try:
            panel = DiagnosticPanel(root,build_diagnostics(frames,[]),frames)
            self.assertIn('12 boîtes à -4,0 mm',panel._details.get('1.0','end'))
            panel._show_details(build_diagnostics(frames,[])[0])
            self.assertIn('12 boîtes à -4,0 mm',panel._details.get('1.0','end'))
            panel.destroy()
        finally:
            for job in root.tk.call('after','info'):
                root.tk.call('after','cancel',job)
            root.destroy()

    def test_repeated_offsets_both_signs_one_reference_and_small_sides(self):
        frames = product_samples([('EN-MOINS',[-4]*12),('EN-TROP',[5]*12),('CONFORME',[0]*16)])
        axis = analyze_measurements(frames)['summary']['axes']['length']
        self.assertIsNone(axis['bias'])
        for side,center in (('under',-4),('over',5)):
            group = axis['recurrence'][side]['cluster']
            self.assertTrue(group['similar'])
            self.assertEqual((group['center'],group['count'],group['percent_bad'],group['percent_all']),(center,12,50,30))
            self.assertEqual(group['repeated_references'],1)
            self.assertFalse(group['shared'])
            self.assertIn('fiche BdD',group['advice'])
        self.assertEqual(axis['all']['mean_signed'],.3)
        frames = product_samples([('UNE-REFERENCE',[-4]*12+[-5]*6+[-20]*2)])
        advice = analyze_measurements(frames)['summary']['axes']['length']['recurrence']['under']['cluster']['advice']
        self.assertIn('fiche BdD',advice)
        for negative,near,similar in ((9,9,True),(10,8,True),(10,7,False)):
            frames = product_samples([('UNE-REFERENCE',[-4]*near+[-10]*(negative-near))])
            axis = analyze_measurements(frames)['summary']['axes']['length']
            self.assertEqual(axis['recurrence']['under']['cluster']['similar'],similar)
            if negative < 10:
                self.assertTrue(axis['recurrence']['under']['cluster']['limited'])
                self.assertIn('effectif limité',' '.join(axis['recurrence_lines']).lower())
        for field,name in (('measured_t5_width_mm','width'),('measured_t5_height_mm','height')):
            frames = samples(15,0)
            for frame in frames:
                setattr(frame.boxes_on_T5[0],field,getattr(frame.boxes_on_T5[0],field)+5)
            axis = analyze_measurements(frames)['summary']['axes'][name]
            self.assertTrue(axis['recurrence']['over']['cluster']['similar'])
            self.assertNotIn('T4/C6',axis['recurrence']['over']['cluster']['advice'])

    def test_neighbouring_good_measures_mode_tie_and_complete_distribution(self):
        frames = product_samples([('PRODUIT-A',[-4]*6+[-5]*4+[-3]*3),
                                  ('PRODUIT-B',[-4]*6+[-5]*4+[-3]*3),
                                  ('AUTRE',[0]*8+[-20])])
        axis = analyze_measurements(frames)['summary']['axes']['length']
        group = axis['recurrence']['under']['cluster']
        self.assertEqual((group['center'],group['count'],group['bad_count'],group['good_count']),(-4,26,20,6))
        self.assertEqual((group['min_signed'],group['max_signed']),(-5,-3))
        self.assertAlmostEqual(group['percent_all'],100*26/35)
        self.assertAlmostEqual(group['percent_bad'],100*20/21)
        self.assertTrue(group['shared'])
        self.assertEqual(group['repeated_references'],2)
        self.assertIn('calibrage',group['advice'])
        self.assertEqual({row['delta']:row['count'] for row in axis['frequencies']},
                         {-4:12,-5:8,-3:6,0:8,-20:1})
        tie = analyze_measurements(product_samples([('EGALITE',[-4]*2+[-5]*2+[4]*2+[5]*2)]))['summary']['axes']['length']
        self.assertEqual(tie['recurrence']['under']['cluster']['center'],-4)
        self.assertEqual(tie['recurrence']['over']['cluster']['center'],4)
        mode = analyze_measurements(product_samples([('MODE',[-4]*4+[-8]*3+[-9]*3)]))['summary']['axes']['length']
        self.assertEqual(mode['recurrence']['under']['cluster']['center'],-4)

    def test_good_only_product_is_accessible_in_neighbouring_group(self):
        frames = product_samples([('DEFAUT',[-4]*3),('CONFORME-PROCHE',[-3]*3),('AUTRE',[0]*2)])
        analysis = analyze_measurements(frames)
        group = analysis['summary']['axes']['length']['recurrence']['under']['cluster']
        self.assertEqual((group['count'],group['bad_count'],group['good_count']),(6,3,3))
        self.assertEqual((group['percent_all'],group['bad_percent_all']),(75,37.5))
        self.assertEqual((group['references'],group['bad_references']),(2,1))
        self.assertNotIn('CONFORME-PROCHE',[row['barcode'] for row in analysis['references']['length']['under']])
        rows = reference_page(analysis,'length','under_group')['rows']
        nearby = next(row for row in rows if row['barcode']=='CONFORME-PROCHE')
        self.assertEqual((nearby['count'],nearby['total']),(3,3))
        self.assertEqual(nearby['observations'][0]['close_percent'],100)
        page = reference_page(analysis,'length','under_group',barcode='CONFORME-PROCHE')
        self.assertEqual(page['total'],3)
        self.assertEqual([sample['deltas'][2] for sample in page['samples']],[-3]*3)
        payload = build_report_payload(build_diagnostics(frames,[]),frames)
        exported = next(row for row in payload['measurement_references']['length']['under_group']
                        if row['barcode']=='CONFORME-PROCHE')
        by_id = {sample['id']:sample for sample in payload['measurement_examples']}
        self.assertEqual([by_id[key]['deltas'][2] for key in exported['sample_ids']],[-3]*3)

    def test_nine_and_ten_identical_measures_keep_the_same_observation(self):
        groups = []
        for count in (9,10):
            axis = analyze_measurements(samples(count,-4))['summary']['axes']['length']
            group = axis['recurrence']['under']['cluster']
            groups.append(group)
            self.assertTrue(group['similar'])
            self.assertTrue(group['shared'])
            self.assertEqual(group['repeated_references'],2)
            self.assertEqual(group['limited'],count<10)
            self.assertIn('calibrage',group['advice'])
            self.assertNotIn('patinage',' '.join(axis['interpretation']))
        self.assertEqual(groups[0]['advice'],groups[1]['advice'])

    def test_dominant_product_and_singletons_do_not_confirm_multiple_products(self):
        frames = product_samples([('DOMINANT',[-4]*20),('ISOLE-A',[-4]),('ISOLE-B',[-4]),
                                  ('AUTRE',[-10]*3)])
        axis = analyze_measurements(frames)['summary']['axes']['length']
        group = axis['recurrence']['under']['cluster']
        self.assertTrue(group['similar'])
        self.assertFalse(group['shared'])
        self.assertEqual(group['repeated_references'],1)
        self.assertEqual((group['dominant']['barcode'],group['dominant']['count']),('DOMINANT',20))
        self.assertAlmostEqual(group['dominant']['percent'],100*20/22)
        self.assertIn('fiche BdD',group['advice'])
        self.assertNotIn('calibrage',group['advice'])
        self.assertNotIn('calibrage',axis['bias']['advice'])
        singles = product_samples([(f'ISOLE-{i}',[-4]) for i in range(12)])
        cluster = analyze_measurements(singles)['summary']['axes']['length']['recurrence']['under']['cluster']
        self.assertFalse(cluster['similar'])
        self.assertFalse(cluster['shared'])
        self.assertEqual(cluster['repeated_references'],0)

    def test_product_variations_are_separate_from_cross_product_differences(self):
        between = product_samples([('PRODUIT-A',[-4]*6),('PRODUIT-B',[-10]*6)])
        axis = analyze_measurements(between)['summary']['axes']['length']
        self.assertEqual(axis['product_observations']['dispersed_references'],0)
        self.assertNotIn('patinage',' '.join(axis['interpretation']))
        within = product_samples([('PRODUIT-A',[-4,-4,-8,-8,-12,-12]),
                                  ('PRODUIT-B',[4,4,8,8,12,12])])
        axis = analyze_measurements(within)['summary']['axes']['length']
        observations = axis['product_observations']
        self.assertEqual((observations['dispersed_references'],observations['dispersed_count']),(2,12))
        self.assertEqual({row['barcode']:row['window_count'] for row in observations['dispersed_products']},
                         {'PRODUIT-A':2,'PRODUIT-B':2})
        self.assertTrue(all(row['limited'] for row in observations['dispersed_products']))
        advice = ' '.join(axis['interpretation'])
        self.assertIn('patinage',advice)
        self.assertIn('C6',advice)
        self.assertIn('parasite',advice)
        boundary = product_samples([('PRODUIT-A',[-4]*8+[-12]*2)])
        axis = analyze_measurements(boundary)['summary']['axes']['length']
        self.assertEqual(axis['product_observations']['dispersed_references'],0)
        self.assertNotIn('patinage',' '.join(axis['interpretation']))

    def test_width_and_height_dispersion_keep_their_own_controls(self):
        for name, field, control in (('width','measured_t5_width_mm','C9'),
                                     ('height','measured_t5_height_mm','LzB')):
            frames = product_samples([('DISPERSION',[0]*6)])
            for frame, delta in zip(frames,[4,4,8,8,12,12]):
                box = frame.boxes_on_T5[0]
                setattr(box,field,getattr(box,field)+delta)
            axis = analyze_measurements(frames)['summary']['axes'][name]
            self.assertEqual(axis['product_observations']['dispersed_references'],1)
            advice = ' '.join(axis['interpretation'])
            self.assertIn(control,advice)
            self.assertNotIn('T4',advice)
            self.assertNotIn('C6',advice)
            self.assertNotIn('patinage',advice)

    def test_incident_and_report_controls_follow_product_evidence(self):
        cases = [('conformes majoritaires',recurring_samples(),False,False),
                 ('répétition commune',samples(12,-4),True,False),
                 ('dispersion interne',product_samples([('DISPERSE',[-4,-4,-8,-8,-12,-12])]),False,True)]
        for name, frames, calibration, slipping in cases:
            with self.subTest(name=name):
                incidents = build_diagnostics(frames,[])
                incident = next(item for item in incidents if item.code=='T4_LENGTH')
                causes = ' '.join(incident.probable_causes)
                checks = ' '.join(incident.checks)
                self.assertEqual('calibrage' in causes or 'calibrage' in checks,calibration)
                self.assertEqual('patinage' in causes or 'patinage' in checks,slipping)
                payload = build_report_payload(incidents,frames)
                group = next(item for item in payload['groups'] if item['code']=='T4_LENGTH')
                report_text = ' '.join(group['probable_causes']+group['checks']+
                    [group['field_action'],group['field_impact'],group['impact']])
                self.assertEqual('calibrage' in report_text,calibration)
                self.assertEqual('patinage' in report_text,slipping)
                self.assertIn('physiquement',checks)
                self.assertIn('BdD',checks)
                if calibration:
                    self.assertIn('calibrage',group['field_action'])
                if not calibration and not slipping:
                    for hypothesis in ('moteur','rouleau','entraînement','entrainement'):
                        self.assertNotIn(hypothesis,report_text)

    def test_opposed_products_and_variants_do_not_create_false_dispersion(self):
        cases = [('produits différents',product_samples([('NEGATIF',[-4]*4),('POSITIF',[5]*4)]),0,0),
                 ('variantes opposées',product_samples([('VARIANT',[-4]*4,(60,30,100)),
                                                        ('VARIANT',[5]*4,(62,31,110))]),1,1)]
        for name, frames, variants, opposite in cases:
            with self.subTest(name=name):
                axis = analyze_measurements(frames)['summary']['axes']['length']
                observations = axis['product_observations']
                self.assertTrue(observations['opposed_groups'])
                self.assertEqual(observations['variant_references'],variants)
                self.assertEqual(observations['opposite_references'],opposite)
                self.assertEqual(observations['dispersed_references'],0)
                explanation = ' '.join(axis['interpretation'])
                self.assertIn('réglage unique',explanation)
                self.assertNotIn('patinage',explanation)
                self.assertNotIn('parasite',explanation)
                incident = next(item for item in build_diagnostics(frames,[]) if item.code=='T4_LENGTH')
                self.assertIn('réglage unique',' '.join(incident.checks))
                if opposite:
                    self.assertIn('chronologie',' '.join(incident.checks))
                payload = build_report_payload([incident],frames)
                self.assertIn('réglage unique',' '.join(payload['groups'][0]['checks']))

    def test_multiple_axes_without_product_repetition_keep_neutral_hypotheses(self):
        frames = recurring_samples()
        for frame in frames:
            box = frame.boxes_on_T5[0]
            delta = box.measured_t4_length_mm - box.bdd_length_mm
            box.measured_t5_width_mm += delta
            box.measured_t5_height_mm += delta
        incidents = build_diagnostics(frames,[])
        incident = next(item for item in incidents if item.code=='GLOBAL')
        payload = build_report_payload(incidents,frames)
        group = next(item for item in payload['groups'] if item['code']=='GLOBAL')
        text = ' '.join(incident.probable_causes+incident.checks+group['probable_causes']+
                       group['checks']+[group['impact'],group['field_impact'],group['field_action']])
        for hypothesis in ('patinage','calibrage','suspicion','blocage','tassement','tassage','moteur','rouleau'):
            self.assertNotIn(hypothesis,text.lower())

    def test_opposite_groups_on_same_product_and_bdd_variants(self):
        opposite = product_samples([('DEUX-COMPORTEMENTS',[-4]*5+[5]*5)])
        analysis = analyze_measurements(opposite)
        axis = analysis['summary']['axes']['length']
        self.assertEqual(axis['product_observations']['opposite_references'],1)
        self.assertFalse(axis['recurrence']['under']['cluster']['similar'])
        self.assertFalse(axis['recurrence']['over']['cluster']['similar'])
        lines = ' '.join(axis['interpretation'])
        self.assertIn('présentation',lines)
        self.assertIn('chronologie',lines)
        frames = product_samples([('VARIANT',[-4]*4,(60,30,100)),
                                  ('VARIANT',[-10]*4,(60,30,110)),
                                  ('AUTRE',[-4]*4)])
        analysis = analyze_measurements(frames)
        axis = analysis['summary']['axes']['length']
        observations = axis['product_observations']
        self.assertEqual(observations['variant_references'],1)
        self.assertEqual(observations['dispersed_references'],0)
        self.assertEqual({tuple(v) for v in observations['variants'][0]['expected']},
                         {(60,30,100),(60,30,110)})
        variant = next(row for row in analysis['references']['length']['under'] if row['barcode']=='VARIANT')
        self.assertEqual(variant['variant_count'],2)
        self.assertEqual({(tuple(row['expected']),row['total'],row['close_count']) for row in variant['observations']},
                         {((60,30,100),4,4),((60,30,110),4,0)})
        self.assertTrue(all(not row['dispersed'] for row in variant['observations']))
        page = reference_page(analysis,'length','under',barcode='VARIANT')
        self.assertEqual(page['total'],8)
        same_product = product_samples([('VARIANT',[-4]*3,(60,30,100)),
                                        ('VARIANT',[-4]*3,(62,31,110))])
        group = analyze_measurements(same_product)['summary']['axes']['length']['recurrence']['under']['cluster']
        self.assertTrue(group['similar'])
        self.assertEqual(group['repeated_references'],1)
        self.assertFalse(group['shared'])
        isolated_variants = product_samples([('VARIANT',[-4],(60,30,100)),
                                            ('VARIANT',[-4],(62,31,110)),
                                            ('AUTRE',[-4,-4])])
        group = analyze_measurements(isolated_variants)['summary']['axes']['length']['recurrence']['under']['cluster']
        self.assertEqual(group['repeated_references'],1)
        self.assertFalse(group['shared'])

    def test_unknown_reidentification_dinh_conflicts_and_missing_t4c(self):
        frames = samples(6,-5)
        boxes = [f.boxes_on_T5[0] for f in frames]
        boxes[0].barcode = 'ALPHA-INC-UNKNOWN'
        boxes[0].identified_barcode = ''
        boxes[1].source_ref = 'ALPHA-INC-RELUE-CB2'
        boxes[2].barcode = 'ALPHA-INC-REJET[DINH]'
        boxes[3].bdd_reference = 'AUTRE-PRODUIT'
        boxes[4].identity_line = 0
        boxes[5].measured_t4_line = 0
        for box in boxes:
            _classify_alpha_measurement(box)
        analysis = analyze_measurements(frames)
        self.assertEqual(analysis['summary']['comparable_count'],2)
        self.assertEqual(analysis['summary']['excluded'],{'ambiguous':0,'unknown':1,'reference_conflict':1,'identity_unconfirmed':1,'t4c_absent':1})
        self.assertEqual(boxes[0].measurement_status,'')
        self.assertEqual(boxes[2].measurement_status,'length')
        self.assertEqual(analysis['finals'][1]['barcode'],'DEMO-0')
        self.assertTrue(analysis['finals'][1]['rejected_dimensions'])
        self.assertEqual(analysis['summary']['cycle_count'],6)

    def test_parser_t4c_sources_and_dinh_keep_product_across_snapshots(self):
        state,ctx = MachineState(C5=1),{}
        lines = [
            "idCB2: Identif. sur le lecteur1 Ok 'DEMO', (Nboite= 32)",
            'Rech. infos dans la BdD pour DEMO',
            '--> PRODUIT FICTIF 64x33x163 94,3g',
            'transfert T3->T4 termine longueur=161 mm idB=32',
            'la boite est rendu (physiquement) sur T5',
            'tT4*T5: => longueur boite (BdD)=163 (T2T)=180 (T4C)=161 (T4T)=134 diffT4=27mm',
            "BdD: Creation de la boite 'DEMO' PRODUIT FICTIF x=4360 (0x0x161) IdA:201",
            "MAJ (APRES-MESURE-LARG) bt IdA:201 'DEMO' (nvlle lxH:64x33 [x161] X:4476)(BdD:64x33x163)",
            'UDP @ALPHA:T5-LIST-PACK@<Dc2>201<Dc2>Y<Dc2>ALPHA-INC-001[Dinh]<Dc2>PRODUIT FICTIF[Dinh]<Dc2>64<Dc2>33<Dc2>161<Dc2>94,3<Dc2>LOT<Dc2>SN<Dc2>0<Dc2>DATE<Dc2>DAY<Dc2>4476@FP',
        ]
        frames = []
        for number,text in enumerate(lines,1):
            state.line_num=number
            state.timestamp=number
            state.timestamp_str=f'09:00:{number:02d}'
            state.raw_lines=[(number,text)]
            state.events=[]
            _update(state,text,ctx,number)
            frames.append(state.deep_copy())
        box=state.boxes_on_T5[0]
        self.assertEqual(box.identified_barcode,'DEMO')
        self.assertEqual(box.bdd_reference,'DEMO')
        self.assertEqual(box.identified_name,'PRODUIT FICTIF')
        self.assertEqual((box.measured_t4_length_mm,box.measured_t4t_length_mm),(161,134))
        self.assertEqual(box.measured_t4_line,6)
        self.assertEqual(box.measurement_status,'ok')
        self.assertEqual(box.clone(),box)
        analysis=analyze_measurements(frames)
        self.assertEqual(analysis['summary']['axes']['length']['all']['mean_signed'],-2)
        self.assertEqual(analysis['summary']['axes']['length']['all']['outside_count'],0)
        sample=analysis['finals'][0]
        self.assertEqual(sample['sources'],{'length':6,'width':8,'height':8,'bdd':8,'identity':1})
        self.assertEqual(sample['line'],8)
        self.assertEqual(sample['t4t'],134)
        self.assertEqual(sample['diff_t4'],27)
        self.assertTrue(sample['rejected_dimensions'])

        # Un resume consomme ne doit pas contaminer la boite suivante.
        state.box_on_T3=BoxInfo(id_b=33,barcode='DEMO')
        _update(state,'tT4*T5: => longueur boite (BdD)=163 (T2T)=180 (T4C)=99 (T4T)=90 diffT4=8mm',ctx,10)
        self.assertEqual(state.boxes_on_T5[0].measured_t4_length_mm,161)
        self.assertEqual(state.box_on_T3.measured_t4_length_mm,0)

    def test_reference_order_denominators_both_sides_and_pages(self):
        frames=samples(4,0)
        for frame,delta in zip(frames,(-5,9,0,-8)):
            box=frame.boxes_on_T5[0]
            box.barcode=box.identified_barcode=box.bdd_reference='DEMO'
            box.measured_t4_length_mm+=delta
        analysis=analyze_measurements(frames)
        below=analysis['references']['length']['under'][0]
        above=analysis['references']['length']['over'][0]
        self.assertEqual((below['count'],below['total'],below['percent'],below['worst']),(2,4,50,-8))
        self.assertEqual((above['count'],above['total'],above['percent'],above['worst']),(1,4,25,9))
        self.assertEqual([s['deltas'][2] for s in below['samples']],[-8,-5])
        frames=samples(60)
        for i,frame in enumerate(frames):
            box=frame.boxes_on_T5[0]
            box.barcode=box.identified_barcode=box.bdd_reference=f'DEMO-{i:03d}'
            box.measured_t4_length_mm+=i
        analysis=analyze_measurements(frames)
        self.assertEqual(reference_page(analysis,'length','over',0)['rows'][0]['barcode'],'DEMO-059')
        self.assertEqual([len(reference_page(analysis,'length','over',p)['rows']) for p in (0,1,2)],[25,25,10])

    def test_signed_range_counts_two_means_and_extreme_proofs(self):
        frames = samples(3)
        for frame, expected, measured in zip(frames, (20,20,30), (26,16,39)):
            box = frame.boxes_on_T5[0]
            box.bdd_length_mm, box.measured_t4_length_mm = expected, measured
        analysis = analyze_measurements(frames)
        result = analysis['summary']
        bad = result['axes']['length']['anomalies']
        self.assertEqual((bad['min_signed'],bad['max_signed']),(-4,9))
        self.assertEqual((bad['worst_under'],bad['worst_over']),(-4,9))
        self.assertEqual((bad['under_count'],bad['over_count']),(1,2))
        self.assertAlmostEqual(bad['mean_signed'],11/3)
        self.assertAlmostEqual(bad['mean_abs'],19/3)
        self.assertEqual((result['global']['within_count'],result['global']['outside_count']),(0,3))
        self.assertEqual(result['axes']['width']['all']['within_count'],3)
        self.assertIn('-4.0 a +9.0 mm',summary_text(result))
        selected = representative_samples(analysis['samples'],code='T4_LENGTH')
        self.assertEqual({s['deltas'][2] for s in selected},{6,-4,9})
        self.assertEqual(result['cycle_count'],3)
        for delta in (-5,5,0):
            axis = analyze_measurements(samples(3,delta))['summary']['axes']['length']
            self.assertEqual(axis['anomalies']['worst_under'],-5 if delta < 0 else None)
            self.assertEqual(axis['anomalies']['worst_over'],5 if delta > 0 else None)

    def test_tolerance_boundaries_global_union_and_direction_pistes(self):
        frames = samples(12,0)
        for i,frame in enumerate(frames):
            box = frame.boxes_on_T5[0]
            box.measured_t4_length_mm += [-3,3,-4,4,0,0,0,0,0,0,0,0][i]
            if i == 2:
                box.measured_t5_width_mm += 5
        result = analyze_measurements(frames)['summary']
        self.assertEqual(result['global']['outside_count'],2)
        self.assertEqual(result['global']['within_count'],10)
        self.assertEqual(result['axes']['length']['all']['within_count'],10)
        self.assertEqual(result['axes']['width']['all']['outside_count'],1)
        pistes = ' '.join(result['axes']['length']['interpretation'])
        self.assertEqual(result['axes']['length']['product_observations']['dispersed_references'],2)
        self.assertIn('patinage',pistes)
        self.assertIn('parasite',pistes)
        self.assertNotIn('patinage',' '.join(result['axes']['width']['interpretation']))
        biased = analyze_measurements(samples(12,-4))['summary']['axes']['length']
        self.assertIn('calibrage',biased['recurrence']['under']['cluster']['advice'])
        for frame in frames:
            frame.boxes_on_T5[0].measured_t4_length_mm = 106
            frame.boxes_on_T5[0].barcode = 'UNE-REFERENCE'
            frame.boxes_on_T5[0].identified_barcode = 'UNE-REFERENCE'
            frame.boxes_on_T5[0].bdd_reference = 'UNE-REFERENCE'
        biased = analyze_measurements(frames)['summary']['axes']['length']
        self.assertIn('fiche BdD',biased['bias']['advice'])

    def test_colors_and_c9_priority(self):
        self.assertEqual(len(MEASUREMENT_STYLES), 8)
        self.assertEqual([measurement_status_from_code(c) for c in ('', 'ORIENTATION', 'T4_LENGTH', 'T5_WIDTH', 'T5_HEIGHT', 'GLOBAL')],
                         ['ok', 'orientation', 'length', 'width', 'height', 'multiple'])
        box = samples(1)[0].boxes_on_T5[0]
        box.measurement_status = 'c9_error'
        _classify_alpha_measurement(box)
        self.assertEqual(box.measurement_status, 'c9_error')
        cases = [('ok',(60,30,100)),('orientation',(100,30,60)),('length',(60,30,105)),
                 ('width',(65,30,100)),('height',(60,35,100)),('multiple',(65,35,105)),('',(0,30,100))]
        for status, values in cases:
            box.measurement_status = ''
            box.measured_t5_width_mm,box.measured_t5_height_mm,box.measured_t4_length_mm = values
            _classify_alpha_measurement(box)
            self.assertEqual(box.measurement_status,status)

    def test_bias_signed_abs_populations_and_references(self):
        for delta in (-5, 5):
            result = analyze_measurements(samples(12, delta))['summary']['axes']['length']
            self.assertEqual(result['all']['count'], 12)
            self.assertEqual(result['all']['mean_signed'], delta)
            self.assertEqual(result['anomalies']['min_abs'], 5)
            self.assertEqual(result['anomalies']['max_abs'], 5)
            self.assertEqual(result['all']['references'], 2)
            self.assertEqual(result['bias']['percent'], 100)
            self.assertIn('calibrage', result['bias']['advice'])
        within = analyze_measurements(samples(12, 2))['summary']['axes']['length']
        self.assertEqual(within['anomalies']['count'], 0)
        self.assertIn('tolerance', within['bias']['advice'])
        frames = samples(12)
        for i, frame in enumerate(frames):
            frame.boxes_on_T5[0].barcode = 'UNIQUE'
            frame.boxes_on_T5[0].identified_barcode = 'UNIQUE'
            frame.boxes_on_T5[0].bdd_reference = 'UNIQUE'
            frame.boxes_on_T5[0].measured_t4_length_mm = 95 if i % 2 else 105
        result = analyze_measurements(frames)['summary']['axes']['length']
        self.assertEqual(result['all']['mean_signed'], 0)
        self.assertEqual(result['all']['mean_abs'], 5)
        self.assertIsNone(result['bias'])
        frames[-1].boxes_on_T5[0].measured_t4_length_mm = 1000
        self.assertEqual(analyze_measurements(frames)['summary']['axes']['length']['all']['max_abs'], 900)

    def test_final_cycle_dedup_and_same_barcode(self):
        first = samples(1)[0]
        repeated = deepcopy(first)
        repeated.line_num = 2
        corrected = deepcopy(first)
        corrected.line_num = 3
        corrected.boxes_on_T5[0].measured_t4_length_mm = 101
        second = deepcopy(first)
        second.line_num = 5
        result = analyze_measurements([first, repeated, corrected, MachineState(line_num=4), second])
        self.assertEqual(len(result['samples']), 3)
        self.assertEqual(result['summary']['axes']['length']['all']['count'], 2)
        self.assertEqual(result['summary']['axes']['length']['anomalies']['count'], 1)
        self.assertFalse(result['samples'][0]['final'])
        together = samples(2)
        together[0].boxes_on_T5 += together[1].boxes_on_T5
        together[0].boxes_on_T5[1].barcode = together[0].boxes_on_T5[0].barcode
        together[0].boxes_on_T5[1].identified_barcode = together[0].boxes_on_T5[0].barcode
        together[0].boxes_on_T5[1].bdd_reference = together[0].boxes_on_T5[0].barcode
        self.assertEqual(analyze_measurements(together[:1])['summary']['comparable_count'], 2)

    def test_exclusions_and_axes(self):
        frames = samples(5)
        frames[0].boxes_on_T5[0].measured_t4_length_mm = 60
        frames[0].boxes_on_T5[0].measured_t5_width_mm = 100
        frames[1].boxes_on_T5[0].measurement_status = 'c9_error'
        frames[2].boxes_on_T5[0].bdd_width_mm = 0
        frames[3].boxes_on_T5[0].measured_t5_height_mm = 0
        frames[4].boxes_on_T5[0].id_alpha = 0
        frames[4].boxes_on_T5.append(deepcopy(frames[4].boxes_on_T5[0]))
        result = analyze_measurements(frames)['summary']
        self.assertEqual(result['comparable_count'], 0)
        self.assertEqual(result['excluded'], {'orientation':1,'invalid':1,'reference_absent':1,'incomplete':1,'ambiguous':2})
        self.assertEqual(result['cycle_count'],result['comparable_count']+result['excluded_count'])
        self.assertEqual(result['global']['outside_count'],0)
        for field, axis in (('measured_t5_width_mm', 'width'), ('measured_t5_height_mm', 'height')):
            frames = samples(12, 0)
            for frame in frames:
                box = frame.boxes_on_T5[0]
                setattr(box, field, getattr(box, field) + 5)
            self.assertEqual(analyze_measurements(frames)['summary']['axes'][axis]['bias']['median'], 5)

    def test_payload_examples_escape_and_full_stats(self):
        frames = samples()
        frames[0].raw_lines[0] = (1, '</script><script>alert("TEST")</script>')
        incidents = build_diagnostics(frames, [])
        payload = build_report_payload(incidents, frames, source_name='DEMONSTRATION')
        group = next(g for g in payload['groups'] if g['code'] == 'T4_LENGTH')
        self.assertEqual(len(group['examples']), 35)
        self.assertEqual(len(group['representative_ids']), 3)
        self.assertEqual(group['measurement_stats'], payload['measurements'])
        self.assertEqual(incidents[0].measurement_stats, payload['measurements'])
        self.assertEqual(group['examples'][0]['context'][0]['line'], 1)
        fallback = build_diagnostic_report_html(incidents, frames)
        self.assertNotIn('</script><script>alert(', fallback)
        self.assertIn('Voir dans AlphaViewer', fallback)

    def test_firmware_proofs_keep_box_and_values_without_bdd_statistics(self):
        frames = samples(1)
        box = frames[0].boxes_on_T5[0]
        box.measurement_status = 'c9_error'
        frames[0].raw_lines = [(1,'IdA:100 largeur invalide C9 actif')]
        incident = DiagnosticIncident(severity='warning',title='C9 invalide',belt='T5',code='C9_WIDTH_INVALID',
            first_line=1,last_line=1,start_time=0,end_time=0,start_time_str='09:00:00',end_time_str='09:00:00',count=1,
            summary='Largeur invalide',event_lines=[1])
        payload = build_report_payload([incident],frames)
        sample = payload['groups'][0]['examples'][0]
        self.assertEqual(sample['box'],'IdA:100')
        self.assertEqual(sample['barcode'],'DEMO-0')
        self.assertEqual(sample['measured'],[60,30,105])
        self.assertTrue(sample['invalid'])
        self.assertEqual(payload['measurements']['comparable_count'],0)

    def test_metrics_do_not_depend_on_formatted_summary(self):
        incidents = [DiagnosticIncident(title='UNKNOWN',code='UNKNOWN',count=5,metrics={'total_boxes':20},severity='warning',
            summary='Texte modifie sans chiffres'),
            DiagnosticIncident(title='Reset',code='ALPHA_CARD_RESET',count=2,metrics={'trace_duration':'1h00m00s'},severity='error'),
            DiagnosticIncident(title='Camera',code='CAM-NO-READ',count=1,metrics={'missing_cameras':['CB2 camera 3']},severity='warning')]
        payload = build_report_payload(incidents,samples(1))
        groups = {g['code']:g for g in payload['groups']}
        self.assertIn('5 unknown / 20',groups['UNKNOWN']['metric'])
        self.assertIn('25.0%',groups['UNKNOWN']['metric'])
        self.assertEqual(groups['ALPHA_CARD_RESET']['affected_label'],'2 reset(s) sur 1h00m00s de trace')
        self.assertIn('CB2 camera 3',groups['CAM-NO-READ']['affected_label'])


class ReportReuseTests(unittest.TestCase):
    def test_reference_worker_pages_navigation_cancel_and_no_ui_frame_scan(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        from Models.frame_store import FrameStore,write_frame_store
        from Models.loading_client import LoadingSession
        import pickle
        session=LoadingSession()
        frames=samples(60)
        analysis=analyze_measurements(frames)
        store_path=session.directory/'entry'
        write_frame_store(frames,store_path,measurement_summary=analysis['summary'])
        with (store_path/'measurements.pkl').open('wb') as output:
            pickle.dump(analysis,output,pickle.HIGHEST_PROTOCOL)
        store=FrameStore(store_path)
        app=ctk.CTk();app.withdraw()
        errors=[]
        app.report_callback_exception=lambda *args:errors.append(str(args[1]))
        try:
            with patch.object(FrameStore,'__iter__',side_effect=AssertionError('Parcours frames dans Tk')):
                visited=[]
                panel=DiagnosticPanel(app,build_diagnostics(frames,[]),store,load_session=session,
                                      on_measurement_click=visited.append)
                self.assertTrue(panel._details.tag_ranges('measurement-length-over'))
                before=len(panel._details._tclCommands)
                for _ in range(12):panel._show_global_summary()
                self.assertLessEqual(len(panel._details._tclCommands),before+2)
                def wait():
                    deadline=time.monotonic()+8
                    while panel._measurement_task is not None and time.monotonic()<deadline:
                        app.update();time.sleep(.005)
                    self.assertIsNone(panel._measurement_task)
                    self.assertFalse(errors,errors)
                panel._open_measurement_references('length','over')
                wait()
                self.assertIn('30/30',panel._details.get('1.0','end'))
                panel._open_measurement_references('length','over',barcode='DEMO-0')
                wait()
                self.assertIn('Page 1/2',panel._details.get('1.0','end'))
                panel._open_measurement_references('length','over',1,'DEMO-0')
                wait()
                self.assertIn('Page 2/2',panel._details.get('1.0','end'))
                sample=analysis['references']['length']['over'][0]['samples'][0]
                panel._navigate_measurement_sample(sample,'length')
                self.assertEqual(visited,[sample['sources']['length']])
                self.assertIn('Identification L.',panel._details.get('1.0','end'))
                panel._open_measurement_references('width','under')
                panel._show_global_summary()
                self.assertIsNone(panel._measurement_task)
                app.update()
                self.assertIn('DIAGNOSTIC GLOBAL',panel._details.get('1.0','end'))
        finally:
            for job in app.tk.call('after','info'):app.tk.call('after','cancel',job)
            app.destroy();store.close();session.close()
            self.assertTrue(session.cleaned.wait(15))

    def test_two_views_reopen_without_worker_and_regenerate_missing_files(self):
        import customtkinter as ctk
        from Widgets.diagnostic_panel import DiagnosticPanel
        from Models.frame_store import FrameStore
        app = ctk.CTk()
        app.withdraw()
        frames = samples(3)
        incidents = build_diagnostics(frames,[])
        try:
            with tempfile.TemporaryDirectory(dir=ROOT / 'TraceAlphaViewer' / '.trace_work') as temp:
                opened = []
                panels = [DiagnosticPanel(app,incidents,frames,on_report_open=opened.append) for _ in range(2)]
                writer = lambda *args,**kwargs: write_diagnostic_report(*args,output_dir=Path(temp),**kwargs)
                with patch('Widgets.diagnostic_panel.write_diagnostic_report',side_effect=writer) as generated, \
                     patch('Widgets.diagnostic_panel.messagebox.showerror',side_effect=lambda *args: self.fail(str(args))):
                    panels[0]._open_web_report()
                    panels[1]._open_web_report()
                    self.assertNotEqual(opened[0],opened[1])
                    read_text = Path.read_text
                    def read_manifest_only(path,*args,**kwargs):
                        self.assertEqual(path.suffixes[-2:],['.manifest','.json'])
                        return read_text(path,*args,**kwargs)
                    with patch.object(Path,'read_text',autospec=True,side_effect=read_manifest_only):
                        panels[0]._open_web_report()
                    self.assertEqual(opened[0],opened[2])
                    self.assertEqual(generated.call_count,2)
                    data = opened[0].with_name(opened[0].name.replace('diagnostic_report_','report_data_')).with_suffix('.json')
                    data.unlink()
                    panels[0]._open_web_report()
                    self.assertEqual(generated.call_count,3)
                    self.assertNotEqual(opened[0],opened[-1])
                    cached = opened[-1]
                    assets = json.loads(cached.with_suffix('.manifest.json').read_text(encoding='utf-8'))
                    script = next((name for name in assets if name.endswith('.js')),None)
                    if script:
                        (cached.parent / script).unlink()
                        panels[0]._open_web_report()
                        self.assertEqual(generated.call_count,4)
                    generated_count = generated.call_count
                    store,session = Mock(spec=FrameStore),Mock()
                    store.directory = Path(temp)
                    panels[0]._frames,panels[0]._load_session = store,session
                    panels[0]._open_web_report()
                    session.start.assert_not_called()
                    self.assertEqual(generated.call_count,generated_count)
                    panels[0]._report_path.unlink()
                    panels[0]._open_web_report()
                    session.start.assert_called_once()
                panel = panels[1]
                self.assertIsInstance(panel._detail_scroll,ctk.CTkScrollbar)
                panel._details.configure(state='normal')
                panel._details.insert('end','\n'.join(f'Ligne {i}' for i in range(100)))
                panel._details.configure(state='disabled')
                panel._detail_scroll.cget('command')('moveto',1)
                self.assertGreater(panel._details.yview()[0],0)
                self.assertIsInstance(panel._list_scroll,ctk.CTkScrollbar)
        finally:
            for job in app.tk.call('after','info'):
                app.tk.call('after','cancel',job)
            app.destroy()


class BridgeTests(unittest.TestCase):
    def test_registered_example_origin_paths_and_shutdown(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'TraceAlphaViewer' / '.trace_work') as temp:
            frames = samples(2)
            report = write_diagnostic_report(build_diagnostics(frames, []), Path(temp), frames)
            bridge = ReportBridge()
            try:
                url = bridge.register(report)
                with patch('Models.report_bridge.json.loads',side_effect=AssertionError('Preuves relues')):
                    self.assertEqual(bridge.register(report),url)
                self.assertEqual(len(bridge.reports),1)
                base = url.rsplit('/', 1)[0]
                self.assertIn(b'html', urlopen(url).read()[:100].lower())
                sample = next(iter(next(iter(bridge.reports.values()))['examples']))
                result = {}
                def request():
                    req = Request(base + '/navigate', data=json.dumps({'sample_id':sample}).encode(),
                                  headers={'Content-Type':'application/json','Origin':'http://' + bridge.address})
                    result.update(json.load(urlopen(req)))
                thread = threading.Thread(target=request)
                thread.start()
                target, done, reply = bridge.commands.get(timeout=3)
                self.assertEqual(target['line'], 1)
                reply.update(ok=True, line=target['line'])
                done.set()
                thread.join(5)
                self.assertTrue(result['ok'])
                for route in ('../../Main.py', '_next/../../Main.py'):
                    with self.assertRaises(HTTPError):
                        urlopen(base + '/' + route)
                with self.assertRaises(HTTPError):
                    urlopen(Request(base + '/navigate', data=b'{"sample_id":"unknown"}',
                        headers={'Origin':'http://example.invalid','Content-Type':'application/json'}))
                for body in (b'[]',b'{"sample_id":"unknown"}'):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base+'/navigate',data=body,
                            headers={'Origin':'http://'+bridge.address,'Content-Type':'application/json'}))
                    self.assertEqual(error.exception.code,400)
                other = ReportBridge()
                try:
                    other_url = other.register(report)
                    self.assertNotEqual(bridge.token,other.token)
                    self.assertNotEqual(bridge.address,other.address)
                    bridge.close()
                    self.assertTrue(json.load(urlopen(other_url.rsplit('/',1)[0]+'/status'))['connected'])
                finally:
                    other.close()
            finally:
                bridge.close()
                bridge.thread.join(3)
            self.assertTrue(bridge.closed.is_set())

    def test_view_navigation_and_invalidation(self):
        from Main import TraceAlphaViewer
        from Views.traceView import TraceView
        from Models.loading_client import LoadingSession
        session = LoadingSession()
        frames = samples(4)
        path = session.directory / 'demonstration.old'
        path.write_text('\n'.join(f.raw_lines[0][1] for f in frames), encoding='utf-8')
        app = TraceAlphaViewer()
        app.withdraw()
        view = TraceView(app, str(path), frames, events=[], diagnostics=build_diagnostics(frames, []))
        try:
            app.switch_view(view)
            view._report_bridge = ReportBridge()
            result, done = {}, threading.Event()
            view._report_bridge.commands.put(({'line':7,'code':'T4_LENGTH','first_line':1}, done, result))
            with patch.object(app,'deiconify'), patch.object(app,'lift'):
                view._poll_report_bridge()
            self.assertTrue(done.is_set())
            self.assertTrue(result.get('ok'), result)
            self.assertEqual(view._idx, 2)
            self.assertFalse(view._playing)
            self.assertEqual(view._analysis_tabs.get(), 'Diagnostic')
            stale = threading.Event()
            stale.set()
            expired_result = {}
            view._report_bridge.commands.put(({'line':1,'code':'T4_LENGTH','first_line':1},stale,expired_result))
            view._poll_report_bridge()
            self.assertEqual(view._idx,2)
            self.assertFalse(expired_result)
            bridge = view._report_bridge
            view.hide()
            self.assertTrue(bridge.closed.is_set())
        finally:
            for job in app.tk.call('after','info'):
                app.tk.call('after','cancel',job)
            app.destroy()
            session.close()
            self.assertTrue(session.cleaned.wait(15))


if __name__ == '__main__':
    (ROOT / 'TraceAlphaViewer' / '.trace_work').mkdir(exist_ok=True)
    unittest.main(verbosity=2)
