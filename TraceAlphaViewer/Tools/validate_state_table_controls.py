"""Verifie les libelles Unicode et les commandes Diagnostic a trois echelles."""
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
import sys
import tkinter.font as tkfont
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
import customtkinter as ctk
from Models.state import MachineState
from Widgets.state_table import StateTable, _SENS_COLORS, _OFF_COLOR
from Widgets.diagnostic_panel import DiagnosticPanel
from Widgets.ui_theme import UI_COLORS


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def show_without_activation(app):
    app.update_idletasks()
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        hwnd = user32.GetAncestor(app.winfo_id(), 2)
        style = user32.GetWindowLongPtrW(hwnd, -20)
        user32.SetWindowLongPtrW(hwnd, -20, (style | 0x08000080) & ~0x00040000)
    app.deiconify()
    app.update()


class StateTableControlTests(unittest.TestCase):
    def test_labels_states_and_rounded_controls_at_three_scales(self):
        for scale in (1., 1.25, 1.5):
            with self.subTest(scale=scale), patch('Widgets.diagnostic_panel._load_split_widths', return_value={'normal':0,'fullscreen':0}), patch('Widgets.diagnostic_panel._save_split_widths'):
                ctk.set_widget_scaling(scale)
                ctk.set_window_scaling(scale)
                app = ctk.CTk()
                app.withdraw()
                app.attributes('-alpha', 0.)
                app._ui_palette = UI_COLORS
                app.geometry('1400x900')
                table = StateTable(app)
                table.pack(side='right', fill='y')
                panel = DiagnosticPanel(app, [], [])
                panel.pack(side='left', fill='both', expand=True)
                errors = []
                app.report_callback_exception = lambda *args: errors.append(str(args[1]))
                try:
                    show_without_activation(app)
                    labels = [child.cget('text') for child in descendants(table) if isinstance(child, ctk.CTkLabel)]
                    for text in ('── Capteurs ──', '── Tapis ──', 'Début T1', 'T2 (chargé)', 'eT:—', '—'):
                        self.assertIn(text, labels)
                    self.assertEqual(labels.count('●'), 10)
                    self.assertFalse(any(marker in text for text in labels for marker in ('Ã', 'â€', 'â—', '\ufffd')))
                    table.update_state(MachineState())
                    self.assertTrue(all(dot.cget('text_color') == _OFF_COLOR for dot in table._sensor_rows.values()))
                    table.update_state(MachineState(C0=True,C1=True,C2=True,C3=True,C4=True,C5=True,C6=True,C9=True,
                                                   flag_poubelle_pleine=True,lzb=20,eT0=-999))
                    for name,dot in table._sensor_rows.items():
                        self.assertEqual(dot.cget('text_color'), _SENS_COLORS[name])
                        self.assertEqual(dot.cget('text'), '●')
                    self.assertEqual(table._belt_et_labels['EA'].cget('text'), 'tâche')
                    self.assertEqual(table._belt_desc_labels['T0'].cget('text'), 'Err: code eT non documenté')
                    for button,role in ((panel._global_btn,'surface'),(panel._report_btn,'accent')):
                        self.assertIsInstance(button, ctk.CTkButton)
                        self.assertEqual(button.cget('corner_radius'), 6)
                        self.assertEqual(button.cget('fg_color'), UI_COLORS[role])
                        button._on_enter()
                        self.assertEqual(button._text_label.cget('background'),button.cget('hover_color'))
                        button._on_leave()
                        self.assertEqual(button._text_label.cget('background'),button.cget('fg_color'))
                    panel._showing_global = False
                    panel._global_btn.invoke()
                    self.assertTrue(panel._showing_global)
                    with patch('Widgets.diagnostic_panel.write_diagnostic_report', return_value=ROOT/'build/fictif.html'), patch.object(panel,'_launch_report') as launch:
                        panel._report_btn.invoke()
                        launch.assert_called_once()
                        panel._set_report_button(preparing=True)
                        panel._report_btn.invoke()
                        launch.assert_called_once()
                    app.update_idletasks()
                    button = panel._report_btn
                    self.assertEqual(button.cget('state'),'disabled')
                    self.assertEqual(button.cget('text'),'Rapport en préparation…')
                    font = tkfont.Font(app, font=button._text_label.cget('font'))
                    self.assertGreaterEqual(button.winfo_width(),font.measure(button.cget('text'))+8)
                    self.assertGreaterEqual(button.winfo_height(),font.metrics('linespace'))
                    self.assertLessEqual(button.winfo_y()+button.winfo_height(),button.master.winfo_height())
                    panel._report_requested = False
                    panel._report_failed('Echec fictif')
                    self.assertEqual(button.cget('state'),'normal')
                    self.assertEqual(button.cget('text'),'Rapport web')
                    panel._report_task = SimpleNamespace(results=Queue())
                    panel._report_task.results.put(('done',{}))
                    panel._set_report_button(preparing=True)
                    panel._poll_report()
                    self.assertEqual(button.cget('state'),'normal')
                    self.assertEqual(button.cget('text'),'Rapport web')
                    self.assertFalse(errors,errors)
                finally:
                    panel.destroy()
                    table.destroy()
                    for job in app.tk.call('after','info'):
                        app.after_cancel(job)
                    app.destroy()
        ctk.set_widget_scaling(1.)
        ctk.set_window_scaling(1.)


if __name__ == '__main__':
    unittest.main(verbosity=2)
