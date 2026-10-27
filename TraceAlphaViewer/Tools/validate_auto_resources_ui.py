"""Controle les indicateurs de ressources et la geometrie de l\'accueil."""
from pathlib import Path
import sys
import unittest
import time
import os
import subprocess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import customtkinter as ctk
from Views.accueilView import AccueilView
from Models.resource_policy import Resources


class PerformancePanelTests(unittest.TestCase):
    def test_signal_without_pillow_and_after_resize(self):
        from types import SimpleNamespace
        try:
            from PIL import ImageTk
            pillow_available = True
        except ImportError:
            pillow_available = False
        app = ctk.CTk()
        app.withdraw()
        home = AccueilView(app)
        try:
            home.show()
            canvas = home._signal_frame.winfo_children()[0]
            event = SimpleNamespace(widget=canvas, width=600, height=62)
            home._draw_landing_signal(event)
            self.assertEqual(canvas.type(canvas.find_all()[0]), 'image' if pillow_available else 'line')
            with patch.dict(sys.modules, {'PIL': None}):
                for width in (642, 900, 600):
                    event.width = width
                    home._draw_landing_signal(event)
                    self.assertTrue(canvas.find_all())
                    self.assertTrue(all(canvas.type(item) in ('line', 'oval') for item in canvas.find_all()))
                    self.assertEqual(canvas._signal_size, (width, 62))
            event.width = 601
            home._draw_landing_signal(event)
            if pillow_available:
                self.assertEqual(len(canvas.find_all()), 1)
                self.assertEqual(canvas.type(canvas.find_all()[0]), 'image')
            else:
                self.assertTrue(all(canvas.type(item) in ('line', 'oval') for item in canvas.find_all()))
        finally:
            home.destroy()
            for job in app.tk.call('after', 'info'):
                app.after_cancel(job)
            app.destroy()

    def test_compact_home_geometry_and_scaling(self):
        from Main import TraceAlphaViewer
        from Views.BaseView import BaseView
        requested_scale = os.environ.get('TRACE_ALPHA_TEST_UI_SCALE')
        if requested_scale is None:
            for scale in (1., 1.25, 1.5):
                result = subprocess.run([sys.executable, __file__,
                    'PerformancePanelTests.test_compact_home_geometry_and_scaling'],
                    env=dict(os.environ, TRACE_ALPHA_TEST_UI_SCALE=str(scale)),
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        ctk.set_window_scaling(float(requested_scale))
        ctk.set_widget_scaling(float(requested_scale))
        app = TraceAlphaViewer()
        app.withdraw()
        try:
            for scale in (float(requested_scale),):
                app._apply_view_geometry()
                app.update()
                home = app.main_view
                available_height = int((app.winfo_screenheight() - 100) / app._get_window_scaling())
                self.assertEqual((app._current_width, app._current_height), (900, min(860, available_height)))
                self.assertEqual((app._min_width, app._min_height), (820, min(750, available_height)))
                center = home._progress_frame.master
                buttons = home._open_buttons
                self.assertEqual(len(buttons), 2)
                self.assertEqual(home._progress_bar.cget('width'), 558)
                for button in buttons:
                    self.assertEqual((button.cget('width'), button.cget('height')), (270, 44))
                    self.assertLessEqual(button._text_label.winfo_reqwidth(), button.winfo_width())
                self.assertFalse(home._progress_frame.winfo_manager())
                self.assertGreaterEqual(home._landing_content.winfo_rooty(),
                                        home._landing_content.master.winfo_rooty())
                for label, bar in home._usage_widgets:
                    self.assertEqual(bar.cget('width'), 160)
                home._show_progress(True)
                for phase, _ in home._progress_steps:
                    home._set_progress_text('Chargement fictif', phase, phase)
                    app.update()
                    last = home._progress_step_rows['raw']
                    self.assertLessEqual(last.winfo_rooty() + last.winfo_height(),
                                         home.winfo_rooty() + home.winfo_height())
                    self.assertGreaterEqual(home._progress_bar.winfo_rooty(),
                                            home._resource_corner.winfo_rooty() + home._resource_corner.winfo_height())
                app.geometry(f'820x{min(750, available_height)}')
                app.update()
                self.assertLessEqual(home._progress_step_rows['raw'].winfo_rooty() + home._progress_step_rows['raw'].winfo_height(),
                                     home.winfo_rooty() + home.winfo_height())
                self.assertGreaterEqual(home._landing_content.winfo_rooty(),
                                        home._landing_content.master.winfo_rooty())
                home._on_error('Fichier fictif indisponible')
                app.update()
                self.assertEqual(home._progress_frame.winfo_manager(), 'pack')
                self.assertIn('Fichier fictif indisponible', home._progress_lbl.cget('text'))
                home._show_progress(False)
                self.assertTrue(home._signal_frame.winfo_manager())
                app.switch_view(BaseView(app))
                app.update()
                expected_width = min(1500, int((app.winfo_screenwidth() - 40) / app._get_window_scaling()))
                actual_width = int(app.geometry().split('x')[0])
                self.assertLessEqual(abs(actual_width - expected_width), 1, app.geometry())
                app.switch_view(AccueilView(app))
                app.update()
                self.assertEqual((app._current_width, app._current_height), (900, min(860, available_height)))
        finally:
            app.main_view.destroy()
            for job in app.tk.call('after', 'info'):
                app.after_cancel(job)
            app.destroy()

    def test_report_destroy_during_and_after_preparation(self):
        from Models.loading_client import LoadingSession
        from Models.frame_store import write_frame_store
        from Models.state import MachineState
        from Widgets.diagnostic_panel import DiagnosticPanel
        app = ctk.CTk()
        app.withdraw()
        errors = []
        app.report_callback_exception = lambda *args: errors.append(str(args[1]))
        try:
            for wait_for_report in (False, True):
                session = LoadingSession()
                try:
                    write_frame_store([MachineState(line_num=1)], session.directory/'store')
                    store = session.open_store(session.directory/'store')
                    panel = DiagnosticPanel(app, [], frames=store, load_session=session)
                    panel.pack()
                    panel._start_report()
                    directory = panel._report_directory
                    task = panel._report_task
                    if wait_for_report:
                        deadline = time.monotonic() + 20
                        while panel._report_task is not None and time.monotonic() < deadline:
                            app.update()
                            time.sleep(.005)
                        self.assertIsNone(panel._report_task)
                        self.assertTrue(panel._report_path.is_file())
                        self.assertFalse(panel._report_retained)
                    panel.destroy()
                    self.assertTrue(task.finished.wait(10))
                    deadline = time.monotonic() + 5
                    while directory.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertFalse(directory.exists())
                finally:
                    session.close()
                    self.assertTrue(session.cleaned.wait(10))
            self.assertEqual(errors, [])
        finally:
            for job in app.tk.call('after', 'info'):
                app.after_cancel(job)
            app.destroy()

    def test_resources_without_manual_controls(self):
        app = ctk.CTk()
        app.geometry('900x860')
        home = AccueilView(app)
        try:
            home.show()
            app.update()
            self.assertEqual(home._resource_corner.pack_info()['side'], 'right')
            self.assertGreater(home._resource_corner.winfo_rootx(),
                               home.winfo_rootx() + home.winfo_width() / 2)
            for name in ('_performance_button', '_performance_frame', '_memory_limit'):
                self.assertFalse(hasattr(home, name))
            self.assertEqual(len(home._usage_widgets), 2)
            home._show_progress(True)
            with patch.object(home._usage_probe, 'sample',
                              return_value=(.25, Resources(16 * 1024**3, 8 * 1024**3, 8, True))):
                home._update_usage()
            self.assertEqual(home._usage_widgets[0][0].cget('text'), 'CPU : 25%')
            self.assertEqual(home._usage_widgets[1][0].cget('text'), 'RAM : 50%')
            self.assertEqual(home._ram_quantity.cget('text'), '8.0/16.0 Gio')
            home.hide()
            self.assertFalse(home._pending_jobs)
            home.show()
            self.assertEqual(len(home._usage_widgets), 2)
        finally:
            home.destroy()
            for job in app.tk.call('after', 'info'):
                app.after_cancel(job)
            app.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
