"""Controle la disposition du diagnostic aux echelles UI 100, 125 et 150 %."""
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
import customtkinter as ctk
from PIL import ImageGrab
from Main import TraceAlphaViewer
from Views.traceView import TraceView
from Tools.validate_measurement_report import samples
from Models.diagnostic import build_diagnostics


def main():
    output = ROOT / 'build' / 'layout-validation'
    output.mkdir(parents=True, exist_ok=True)
    frames = samples(4)
    incidents = build_diagnostics(frames, [])
    incidents[0].title += ' — ' + 'Intitule long de demonstration sans troncature. ' * 12
    path = output / 'demonstration.txt'
    path.write_text('\n'.join(f.raw_lines[0][1] for f in frames), encoding='utf-8')
    with patch('Widgets.diagnostic_panel._load_split_widths', return_value={'normal':0,'fullscreen':0}), \
         patch('Widgets.diagnostic_panel._save_split_widths'):
        app = TraceAlphaViewer()
        errors = []
        app.report_callback_exception = lambda *args: errors.append(str(args[1]))
        try:
            view = TraceView(app, str(path), frames, events=[], diagnostics=incidents)
            app.switch_view(view)
            app.update()
            def pump():
                until = time.monotonic() + .4
                while time.monotonic() < until:
                    app.update()
                    time.sleep(.005)
            for scale in (1,1.25,1.5):
                ctk.set_widget_scaling(scale)
                ctk.set_window_scaling(scale)
                for maximized in (False,True):
                    app.state('normal')
                    app.geometry(f'{int(1800/scale)}x{int(950/scale)}+10+10')
                    if maximized:
                        app.state('zoomed')
                    view._analysis_tabs.set('Diagnostic')
                    pump()
                    panel = view._diagnostic_panel
                    canvas = view._machine_canvas
                    assert view._canvas is not canvas, 'Le canvas interne CTk doit rester distinct'
                    assert (canvas.winfo_width(),canvas.winfo_height()) == (920,540), (scale,maximized,canvas.winfo_width(),canvas.winfo_height())
                    assert app.winfo_width() <= app.winfo_screenwidth(), 'La fenetre depasse la largeur de l ecran'
                    self_list = panel._list
                    assert self_list.cget('wrap') == 'word'
                    assert incidents[0].title in self_list.get('1.0','end')
                    for position in (0, panel._paned.winfo_width()):
                        panel._set_sash_pos(0,position)
                        panel._clamp_split_width()
                        pump()
                        assert self_list.winfo_width() >= 150, (scale,maximized,position,panel._paned.winfo_width(),self_list.winfo_width(),panel._get_sash_pos(0))
                        assert panel._details.winfo_width() >= 150
                    title_line = max(panel._line_to_incident)
                    self_list.see(f'{title_line}.0')
                    pump()
                    coords = self_list.bbox(f'{title_line}.0')
                    assert coords, 'Le debut du titre doit etre accessible'
                    panel._on_click(SimpleNamespace(x=coords[0]+1,y=coords[1]+1))
                    assert incidents[0].title in panel._details.get('1.0','end')
                    self_list.see(f'{title_line}.end')
                    pump()
                    assert self_list.bbox(f'{title_line}.end'), 'La fin du titre doit etre accessible'
                    panel._set_sash_pos(0,int(panel._paned.winfo_width()*.4))
                    panel._show_global_summary()
                    pump()
                    ImageGrab.grab(window=app.winfo_id()).save(output / f'ui-{int(scale*100)}-{maximized}.png')
                    print(f'Disposition validee : echelle {scale:.0%}, maximise={maximized}',flush=True)
            assert not errors, errors
        finally:
            app.destroy()
            ctk.set_widget_scaling(1)
            ctk.set_window_scaling(1)


if __name__ == '__main__':
    main()
