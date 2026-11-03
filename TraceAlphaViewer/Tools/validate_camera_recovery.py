"""Valide les recuperations CB2 par cycle et leurs denominations web/PDF."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.diagnostic import _camera_stats, _frame_line_states, camera_report_stats
from Models.diagnostic_report import build_report_payload, write_diagnostic_report, build_diagnostic_report_html
from Models.group_analysis import _merge_camera
from Models.identification_analysis import IdentificationCycle
from Tools.validate_reference_absent import cycle_lines, frames_for


def fixture():
    rows = cycle_lines(1, recovered=True) + cycle_lines(2)
    rows += cycle_lines(3, known=True, direct=True) + cycle_lines(4, direct=True)
    rows += cycle_lines(5, missing=(2,))
    return frames_for(rows)


class RecoveryTests(unittest.TestCase):
    def test_first_success_distribution_and_retries(self):
        rows = cycle_lines(1, known=True)
        frames = frames_for(rows[:3] * 4 + rows)
        stats = _camera_stats(_frame_line_states(frames))
        self.assertEqual(len(stats['cycles']), 1)
        cycle = stats['cycles'][0]
        self.assertLess(cycle.reader_first_success_lines['CB1'], cycle.reader_success_lines['CB1'])
        self.assertEqual(stats['decoding_distribution'],
                         {'version': 1, 'available': True, 'total': 1, 'CB1': 1, 'CB2': 0})
        for first in ('CB1', 'CB2'):
            other = 'CB2' if first == 'CB1' else 'CB1'
            cycle = IdentificationCycle(first_line=1, codes={'CB1': [1, 1], 'CB2': [1]},
                reader_first_success_lines={first: 2, other: 3},
                reader_success_lines={first: 9, other: 3})
            with patch('Models.diagnostic.identification_cycles', return_value=[cycle]):
                distribution = _camera_stats([])['decoding_distribution']
            self.assertEqual(distribution[first], 1)
            self.assertEqual(distribution[other], 0)
        self.assertEqual(camera_report_stats(frames_for(cycle_lines(1)))['decoding_distribution']['total'], 0)

    def test_recoveries_and_unknown_use_different_populations(self):
        stats = camera_report_stats(fixture())
        flow = stats['recovery']
        self.assertEqual(stats['total_boxes'], 5)
        self.assertEqual(flow['cb1_zero_count'], 4)
        self.assertEqual(flow['cb2_recovered_count'], 2)
        self.assertEqual(flow['cb2_zero_count'], 1)
        self.assertEqual(flow['cb2_not_observed_count'], 1)
        self.assertEqual(stats['unknown']['count'], 1)
        self.assertEqual(stats['decoding_distribution'],
                         {'version': 1, 'available': True, 'total': 3, 'CB1': 1, 'CB2': 2})
        readers = {row['reader']: row for row in stats['reader_stats']}
        self.assertEqual((readers['CB1']['boxes'], readers['CB2']['boxes']), (5, 3))
        self.assertEqual(sum(flow[key] for key in ('cb2_recovered_count', 'cb2_zero_count',
            'cb2_not_observed_count', 'chronology_unconfirmed_count')), flow['cb1_zero_count'])

    def test_repeated_attempts_do_not_inflate_recovery(self):
        rows = cycle_lines(1, recovered=True)
        position = next(i for i, text in enumerate(rows) if 'CB2: ajout' in text)
        rows[position:position] = [rows[position].replace('1code(s)', '0code(s)')] * 8
        stats = camera_report_stats(frames_for(rows))
        self.assertEqual(stats['recovery']['cb2_recovered_count'], 1)
        rows = cycle_lines(1, known=True)
        rows.insert(0, rows[0].replace('1code(s)', '0code(s)'))
        self.assertEqual(camera_report_stats(frames_for(rows))['recovery']['cb1_zero_count'], 0)

    def test_chronology_is_required_and_legacy_stays_unavailable(self):
        cycle = IdentificationCycle(first_line=1, codes={'CB1': [0], 'CB2': [1]},
            reader_last_lines={'CB1': 10, 'CB2': 5}, reader_success_lines={'CB2': 5})
        with patch('Models.diagnostic.identification_cycles', return_value=[cycle]):
            flow = _camera_stats([])['recovery']
        self.assertEqual(flow['cb2_recovered_count'], 0)
        self.assertEqual(flow['chronology_unconfirmed_count'], 1)
        stats = _camera_stats(_frame_line_states(fixture()))
        stats.pop('recovery')
        self.assertFalse(camera_report_stats(fixture(), stats=stats)['recovery']['available'])

    def test_folder_sums_independent_segments(self):
        one = _camera_stats(_frame_line_states(fixture()))
        frames = fixture()
        for frame in frames:
            frame.line_num += 1000
            frame.raw_lines = [(line+1000, text) for line, text, *_ in frame.raw_lines]
        two = _camera_stats(_frame_line_states(frames))
        _merge_camera(one, two)
        self.assertEqual(one['recovery']['cb2_recovered_count'], 4)
        self.assertEqual(one['recovery']['cb1_zero_count'], 8)
        self.assertEqual(len(one['all_hist_boxes']), 10)
        self.assertEqual(one['decoding_distribution'],
                         {'version': 1, 'available': True, 'total': 6, 'CB1': 2, 'CB2': 4})
        old = deepcopy(one)
        old.pop('decoding_distribution')
        _merge_camera(one, old)
        self.assertFalse(one['decoding_distribution']['available'])

    def test_both_renderers_pdf_mobile_and_old_reports(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        frames = fixture()
        payload = build_report_payload([], frames)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as temporary, sync_playwright() as pw:
            output = Path(temporary)
            report = write_diagnostic_report([], output, frames, source_name='LECTURES FICTIVES')
            fallback = output/'secours.html'
            fallback.write_text(build_diagnostic_report_html([], frames), encoding='utf-8')
            browser = pw.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1080})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            for index, path in enumerate((report, fallback)):
                page.goto(path.as_uri())
                self.assertIn('UNKNOWN finaux', page.locator('.unknown-counter').inner_text())
                self.assertIn('passages', page.locator('.unknown-counter').get_attribute('aria-label'))
                cards = page.locator('.camera-readers section')
                self.assertEqual(cards.count(), 2)
                self.assertIn('1 / 3 · 33,3 %', cards.nth(0).inner_text())
                self.assertIn('2 / 3 · 66,7 %', cards.nth(1).inner_text())
                self.assertEqual(page.locator('.camera-recovery').count(), 0)
                self.assertNotIn('Sans code', page.locator('.camera-readers').inner_text())
                for width in (1440, 1360, 390):
                    page.set_viewport_size({'width':width, 'height':1080})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    self.assertLessEqual(page.locator('.unknown-counter').bounding_box()['height'], 61)
                with page.expect_download() as downloaded:
                    page.get_by_role('button', name='Exporter PDF').click()
                pdf = output/f'lecture-{index}.pdf'
                downloaded.value.save_as(pdf)
                document = pdfium.PdfDocument(pdf)
                text = '\n'.join(p.get_textpage().get_text_range() for p in document)
                document.close()
                self.assertIn('33,3 %', text)
                self.assertIn('66,7 %', text)
                self.assertNotIn('Récupérations CB1', text)
                legacy = deepcopy(payload)
                legacy['camera'].pop('decoding_distribution')
                page.evaluate('data=>TraceReport.mount(document.querySelector(".report").parentElement,data)', legacy)
                self.assertIn('Régénérer le rapport', page.locator('.camera-readers').inner_text())
                empty = deepcopy(payload)
                empty['camera']['decoding_distribution'] = {'version': 1, 'available': True, 'total': 0, 'CB1': 0, 'CB2': 0}
                page.evaluate('data=>TraceReport.mount(document.querySelector(".report").parentElement,data)', empty)
                self.assertIn('Aucune boîte décodée', page.locator('.camera-readers').inner_text())
                self.assertNotIn('NaN', page.locator('.camera-readers').inner_text())
                for name, data, expected in (('ancien', legacy, 'Régénérer le rapport'),
                                             ('vide', empty, 'Aucune boîte décodée')):
                    page.evaluate('data=>{const old=document.querySelector(".report").parentElement;'
                                  'const root=old.cloneNode(false);old.replaceWith(root);TraceReport.mount(root,data)}', data)
                    with page.expect_download() as downloaded:
                        page.get_by_role('button', name='Exporter PDF').click()
                    path = output/f'{name}-{index}.pdf'
                    downloaded.value.save_as(path)
                    document = pdfium.PdfDocument(path)
                    text = '\n'.join(p.get_textpage().get_text_range() for p in document)
                    document.close()
                    self.assertIn(expected, text)
                large = deepcopy(payload)
                large['camera']['decoding_distribution'] = {'version': 1, 'available': True, 'total': 3096, 'CB1': 2212, 'CB2': 884}
                page.evaluate('data=>TraceReport.mount(document.querySelector(".report").parentElement,data)', large)
                text = page.locator('.camera-readers').inner_text().replace('\u202f', ' ').replace('\u00a0', ' ')
                self.assertIn('2 212 / 3 096 · 71,4 %', text)
                self.assertIn('884 / 3 096 · 28,6 %', text)
            self.assertFalse(errors, errors)
            browser.close()


if __name__ == '__main__':
    unittest.main()
