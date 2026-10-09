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
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.state import BoxInfo, MachineState
from Models.dimension_check import MEASUREMENT_STYLES, measurement_status_from_code
from Models.measurement_analysis import analyze_measurements
from Models.diagnostic import build_diagnostics, DiagnosticIncident
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Models.report_bridge import ReportBridge
from Parser.trace_parser import _classify_alpha_measurement


def samples(count=35, delta=5):
    frames = []
    for i in range(count):
        box = BoxInfo(id_alpha=100 + i, barcode=f'DEMO-{i % 2}', name='PRODUIT FICTIF',
            bdd_length_mm=100, bdd_width_mm=60, bdd_height_mm=30,
            measured_t4_length_mm=100 + delta, measured_t5_width_mm=60, measured_t5_height_mm=30,
            length_mm=100, width_mm=60, height_mm=30, x_pos=942)
        _classify_alpha_measurement(box)
        line = i * 3 + 1
        frames.append(MachineState(line_num=line, timestamp=i, timestamp_str=f'09:00:{i:02d}',
            boxes_on_T5=[box], raw_lines=[(line, f'DONNEES FICTIVES boite {i} longueur {100+delta} BdD 100')]))
    return frames


class MeasurementTests(unittest.TestCase):
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


class BridgeTests(unittest.TestCase):
    def test_registered_example_origin_paths_and_shutdown(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'TraceAlphaViewer' / '.trace_work') as temp:
            frames = samples(2)
            report = write_diagnostic_report(build_diagnostics(frames, []), Path(temp), frames)
            bridge = ReportBridge()
            try:
                url = bridge.register(report)
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
            app.destroy()
            session.close()
            self.assertTrue(session.cleaned.wait(15))


if __name__ == '__main__':
    (ROOT / 'TraceAlphaViewer' / '.trace_work').mkdir(exist_ok=True)
    unittest.main(verbosity=2)
