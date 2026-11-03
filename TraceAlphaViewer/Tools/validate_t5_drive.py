"""Valide les chaînes T4/T5, leurs limites et les preuves des rapports."""
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Models.diagnostic import _build_t5_drive_incidents, _frame_line_states, build_diagnostics
from Models.diagnostic_report import build_report_payload, build_diagnostic_report_html
from Tools.validate_c2_signal import frames_for


def cycle(idb=1, ida=101, c9=1, t4t=115, collective=False):
    texts = [
        f'tT3/T4: transfert T3->T4 terminé, longueur=113 mm, attend transfert vers T5 (idB={idb})',
        "tT4*T5: Demande le transfert (physique) de la boite de T4 vers T5 'CIP-COMMUN' ...",
        'tT4*T5: la boite est rendu (physiquement) sur T5',
        f'tT4*T5: => longueur boite (BdD)=112 (T2T)=115 (T4C)=113 (T4T)={t4t} diffT4=0mm',
        f"BdD: Création de la boite 'CIP-COMMUN' PRODUIT FICTIF x=7930 (0x0x113) IdA:{ida}",
        f"photoCamT5 'AjoutBtT5.idA{ida}.idB{idb}'",
        f'MAJ (BUTEE-T5) boite Id:{ida} ref:CIP-COMMUN (nvlle dim:0x0 X:8207)',
        "T5: Il n'y a pas de boite sous le laser T5 !",
        'T5: Ph4-WAIT-POS-REPOS eT5=71 larg:164 C9:0 LzB:0 pT5:2984',
        f'T5: largeur lue sur T5 < 2mm et C9={c9} ...',
        (f' - supp. de T5 la boite Id:{ida} ref:ALPHA-DET-FICTIF[Lz]' if collective else
         f'Suppr. dernière boite transférer (IdBdD:{ida} IdT5:{ida} Ref:ALPHA-DET-FICTIF[Lz])'),
    ]
    return list(enumerate(texts))


def incidents(rows):
    return _build_t5_drive_incidents(_frame_line_states(frames_for(rows)))


class T5DriveTests(unittest.TestCase):
    def test_complete_variants(self):
        for c9 in (0, 1):
            for t4t in (0, 115):
                for collective in (False, True):
                    with self.subTest(c9=c9, t4t=t4t, collective=collective):
                        found = incidents(cycle(c9=c9, t4t=t4t, collective=collective))
                        self.assertEqual(len(found), 1)
                        self.assertEqual((found[0].severity, found[0].count), ('error', 1))
                        self.assertEqual(found[0].metrics['cycle']['width']['c9'], c9)
                        json.dumps(found[0].metrics)

    def test_each_required_link(self):
        for index in (0, 2, 4, 5, 7, 9, 10):
            with self.subTest(index=index):
                rows = cycle()
                del rows[index]
                self.assertEqual(incidents(rows), [])
        self.assertEqual(incidents([(t, text.replace('longueur=113', 'longueur=0')) for t, text in cycle()]), [])
        self.assertEqual(len(incidents([row for i, row in enumerate(cycle()) if i != 3])), 1)

    def test_recovery_and_provisional_dimensions(self):
        rows = cycle()
        rows.insert(-1, (9.5, 'MAJ (APRES-MESURE-LARG) bt IdA:101 CIP-COMMUN (nvlle lxH:40x20 [x113] X:7800)'))
        self.assertEqual(incidents(rows), [])
        self.assertEqual(incidents([row for row in cycle() if 'largeur lue' not in row[1]]), [])
        for separator in ('<Dc2>', chr(182)):
            fields = ['101', 'Y', 'CIP-COMMUN', 'PRODUIT FICTIF', '40', '20'] + ['0'] * 17
            rows = cycle()
            rows.insert(-1, (9.5, 'ALPHA:T5-LIST-PACK@' + separator + separator.join(fields) + '@FP'))
            self.assertEqual(incidents(rows), [])

    def test_boundaries(self):
        for boundary in ('version logiciel VBalpha: v1.0', 'ligne sans motif T5'):
            rows = cycle()
            if boundary.startswith('version'):
                rows.insert(9, (8.5, boundary))
            else:
                rows = rows[:9] + [(200, boundary)] + [(201+t, text) for t, text in rows[9:]]
            self.assertEqual(incidents(rows), [])
        rows = cycle()
        self.assertEqual(incidents(rows[:9]) + incidents(rows[9:]), [])
        rows = cycle()[:-1] + [(t, 'attente continue sans motif T5') for t in (60, 120, 180)] + [(200, cycle()[-1][1])]
        self.assertEqual(len(incidents(rows)), 1)

    def test_identities_and_same_barcode(self):
        rows = cycle() + [(t+20, text) for t, text in cycle(idb=2, ida=102)]
        self.assertEqual([item.metrics['cycle']['id_b'] for item in incidents(rows)], [1, 2])
        wrong = [(t, text.replace('AjoutBtT5.idA101.idB1', 'AjoutBtT5.idA101.idB2')) for t, text in cycle()]
        self.assertEqual(incidents(wrong), [])
        wrong = [(t, text.replace('IdBdD:101', 'IdBdD:999')) for t, text in cycle()]
        self.assertEqual(incidents(wrong), [])
        wrong = [(t, text.replace('IdT5:101', 'IdT5:999')) for t, text in cycle()]
        self.assertEqual(incidents(wrong), [])

    def test_report_and_full_entrypoint(self):
        rows = cycle() + [(t+20, text) for t, text in cycle(idb=2, ida=102)]
        frames = frames_for(rows)
        found = build_diagnostics(frames, [])
        drive = [item for item in found if item.code == 'T5_DRIVE_SUSPECTED']
        self.assertEqual(len(drive), 2)
        payload = build_report_payload(found, frames)
        group = next(item for item in payload['groups'] if item['code'] == 'T5_DRIVE_SUSPECTED')
        self.assertEqual((group['occurrence_count'], group['field_severity']), (2, 'error'))
        self.assertEqual(group['metrics']['cycle_count'], 2)
        self.assertLessEqual(len(group['examples']), 10)
        self.assertTrue(all(item['detail'] and item['line'] for item in group['examples']))
        self.assertIn('T5_DRIVE_SUSPECTED', build_diagnostic_report_html(found, frames))
        json.dumps(payload)

    def test_folder_segments_and_reused_ids(self):
        from Tools.validate_folder_groups import FolderGroupsTests
        from Models.group_analysis import analyze_group
        fixture = FolderGroupsTests()
        fixture.setUp()
        try:
            texts = [text for _, text in cycle()]
            first = fixture.source('jour1', '2026-10-28T10:00:00', texts)
            second = fixture.source('jour2', '2026-10-29T10:00:00', texts)
            result = analyze_group([first, second], fixture.root / 'complet')
            found = [row for row in result['diagnostics'] if row.code == 'T5_DRIVE_SUSPECTED']
            self.assertEqual(len(found), 2)
            self.assertEqual({row.metrics['source_segment'] for row in found}, {0, 1})
            self.assertGreater(found[1].first_line, found[0].last_line)
            first = fixture.source('debut', '2026-10-28T10:00:00', texts[:9])
            second = fixture.source('fin', '2026-10-28T10:01:00', texts[9:])
            result = analyze_group([first, second], fixture.root / 'incomplet')
            self.assertFalse(any(row.code == 'T5_DRIVE_SUSPECTED' for row in result['diagnostics']))
        finally:
            fixture.tearDown()

    def test_viewer_summary_without_window(self):
        from types import SimpleNamespace
        from Widgets.diagnostic_panel import DiagnosticPanel
        class Text:
            def __init__(self):
                self.value = ''
            def configure(self, **kwargs):
                pass
            def delete(self, *args):
                self.value = ''
            def insert(self, position, value, *args):
                self.value += value
        frames = frames_for(cycle() + [(t+20, text) for t, text in cycle(idb=2, ida=102)])
        details = Text()
        panel = SimpleNamespace(_incidents=build_diagnostics(frames, []), _frames=frames,
                                _details=details, _measurement_summary={},
                                _cancel_measurement_task=lambda: None,
                                _clear_current_selection=lambda: None,
                                _line_label=lambda line: f'L.{line}')
        DiagnosticPanel._show_global_summary(panel)
        self.assertIn('2 boîte(s) sans mesures T5', details.value)
        self.assertIn('[CRITIQUE] T5 T5_DRIVE_SUSPECTED', details.value)
        self.assertIn('Vérifier le mouvement réel de T5', details.value)

    def test_browser_navigation_and_pdf(self):
        from playwright.sync_api import sync_playwright
        import pypdfium2 as pdfium
        from Models.diagnostic_report import write_diagnostic_report
        from Models.report_bridge import ReportBridge
        frames = frames_for(cycle())
        found = build_diagnostics(frames, [])
        bridge = ReportBridge()
        root = Path(__file__).resolve().parents[2]
        (root / 'build').mkdir(exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=root / 'build') as directory, sync_playwright() as pw:
                output = Path(directory)
                report = write_diagnostic_report(found, output, frames, source_name='DONNEES FICTIVES')
                fallback = output / 'secours.html'
                fallback.write_text(build_diagnostic_report_html(found, frames), encoding='utf-8')
                browser = pw.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1080})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for index, url in enumerate((bridge.register(report), fallback.as_uri())):
                    page.goto(url)
                    group = page.locator('details[data-group^="T5_DRIVE_SUSPECTED:"]')
                    self.assertIn('Critique', group.locator(':scope > summary').inner_text())
                    group.locator(':scope > summary').click()
                    group.locator('.incident-series > summary').first.click()
                    self.assertIn('Absence sous le laser hauteur', group.inner_text())
                    self.assertIn('Suppression informatique', group.inner_text())
                    button = group.locator('[data-navigate]').first
                    if index == 0:
                        received = []
                        def respond():
                            target, done, result = bridge.commands.get(timeout=10)
                            received.append(target)
                            result.update(ok=True, line=target['line'])
                            done.set()
                        thread = threading.Thread(target=respond)
                        thread.start()
                        button.click()
                        thread.join(10)
                        self.assertEqual(received[0]['code'], 'T5_DRIVE_SUSPECTED')
                    else:
                        self.assertTrue(button.is_disabled())
                    with page.expect_download() as download:
                        page.get_by_role('button', name='Exporter PDF').click()
                    pdf = output / f'rapport-{index}.pdf'
                    download.value.save_as(pdf)
                    document = pdfium.PdfDocument(pdf)
                    content = '\n'.join(document[i].get_textpage().get_text_range() for i in range(len(document)))
                    document.close()
                    self.assertIn('entraînement', content)
                    self.assertIn('CRITIQUE', content.upper())
                    self.assertFalse(errors, errors)
                browser.close()
        finally:
            bridge.close()


if __name__ == '__main__':
    unittest.main()
