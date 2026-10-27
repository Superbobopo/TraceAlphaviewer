"""Compare la geometrie et les couleurs metier du viewer sur donnees fictives."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def snapshot(view):
    import tkinter.font as tkfont
    from Widgets.machine_canvas import MachineCanvas
    widgets = {}

    def visit(widget, key):
        if not widget.winfo_ismapped():
            return
        row = {'class': type(widget).__name__, 'rect': [widget.winfo_rootx() - view.winfo_rootx(),
            widget.winfo_rooty() - view.winfo_rooty(), widget.winfo_width(), widget.winfo_height()]}
        try:
            font = widget.cget('font')
            row['font'] = font.actual() if hasattr(font, 'actual') else tkfont.Font(widget, font=font).actual()
        except (tk.TclError, ValueError, TypeError, AttributeError):
            # Certains widgets ne portent pas de police.
            pass
        for option in ('border_width', 'corner_radius', 'padx', 'pady', 'sashwidth'):
            try:
                row[option] = widget.cget(option)
            except (tk.TclError, ValueError, AttributeError):
                pass
        if isinstance(widget, MachineCanvas):
            row['primitives'] = [{'type': widget.type(item), 'coords': widget.coords(item),
                'options': {name: widget.itemcget(item, name) for name in widget.itemconfigure(item)}}
                for item in widget.find_all()]
        widgets[key] = row
        for index, child in enumerate(widget.winfo_children()):
            visit(child, key + '/' + str(index))

    visit(view, 'viewer')
    for tag in ('search', 'search_current', 'hi', 'hi_linenum'):
        widgets['trace-tag:' + tag] = {name: view._trace_panel._text.tag_cget(tag, name)
            for name in ('foreground', 'background', 'font')}
    return widgets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scale', type=float, default=1.)
    parser.add_argument('--record', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    import customtkinter as ctk
    from Main import TraceAlphaViewer
    from Models.loading_client import LoadingSession
    from Tools.generate_user_manual import demonstration
    from Views.traceView import TraceView
    from Widgets.machine_canvas import C
    from Widgets.state_table import _SENS_COLORS, _OFF_COLOR, _et_color
    from Widgets.diagnostic_panel import _SEVERITY_STYLES
    ctk.set_window_scaling(args.scale)
    ctk.set_widget_scaling(args.scale)
    session = LoadingSession()
    app = TraceAlphaViewer()
    app.attributes('-alpha', 0.)
    errors = []
    app.report_callback_exception = lambda *items: errors.append(str(items[1]))
    result = {'scenarios': {}, 'semantic': {'machine': C, 'sensors': _SENS_COLORS,
        'sensor_off': _OFF_COLOR, 'severity': _SEVERITY_STYLES,
        'et': {str(n): _et_color(n) for n in (-49, -1, 0, 1, 2, 43, 89)}}}

    def pump():
        deadline = time.monotonic() + .3
        while time.monotonic() < deadline:
            app.update()
            time.sleep(.005)
        if errors:
            raise AssertionError(errors)

    def record(name):
        pump()
        result['scenarios'][name] = snapshot(view)

    try:
        with ExitStack() as stack:
            stack.enter_context(patch('Widgets.diagnostic_panel._load_split_widths',
                return_value={'normal': 0, 'fullscreen': 0}))
            stack.enter_context(patch('Widgets.diagnostic_panel._save_split_widths'))
            path, frames, events, diagnostics, records = demonstration(session.directory)
            view = TraceView(app, str(path), frames, events=events, diagnostics=diagnostics,
                             references=records, source_name='DEMONSTRATION')
            app.switch_view(view)
            pump()
            view._go_to(24)
            for tab in ('Diagnostic', 'Capteurs & Tapis', 'References', 'Erreur', 'Evenements'):
                view._analysis_tabs.set(tab)
                record(tab)
            view._event_panel._set_belt_filter('T5')
            record('filtre-T5')
            view._analysis_tabs.set('Diagnostic')
            incident = next(item for item in diagnostics if item.code == 'INIT-C6')
            view._diagnostic_panel._show_details(incident)
            record('incident')
            view._btn_search.invoke()
            view._trace_panel._search_var.set('3400000000001')
            pump()
            view._trace_panel._navigate_search(1)
            record('recherche')
            view._toggle_trace_search()
            view._toggle_details()
            record('details-masques')
            view._toggle_details()
            view._set_speed(.5)
            record('details-visibles')
            view._start_playback()
            view._stop_playback()
            record('player-arrete')
            from Widgets.event_panel import EventPanel
            from Widgets.state_table import StateTable
            from Widgets.ui_theme import UI_COLORS, palette
            outside = EventPanel(app, [])
            table = StateTable(app)
            try:
                if outside.cget('fg_color') != '#12121f' or table.cget('fg_color') != '#161625':
                    raise AssertionError('Le theme deborde du viewer')
                if palette(outside) is not None or palette(view._event_panel) is not UI_COLORS:
                    raise AssertionError('Portee du theme incorrecte')
            finally:
                outside.destroy()
                table.destroy()
        result['semantic']['machine'] = {k: v for k, v in C.items() if k != 'bg'}
        result = json.loads(json.dumps(result))
        if args.record:
            args.record.parent.mkdir(parents=True, exist_ok=True)
            args.record.write_text(json.dumps(result), encoding='utf-8')
        if args.compare:
            expected = json.loads(args.compare.read_text(encoding='utf-8'))
            differences = []
            def compare(a, b, key):
                if isinstance(a, dict) and isinstance(b, dict):
                    for name in a.keys() | b.keys():
                        if name not in a or name not in b:
                            differences.append(key + '/' + name + ': absent')
                        else:
                            compare(a[name], b[name], key + '/' + name)
                elif a != b:
                    differences.append(f'{key}: {str(a)[:90]} -> {str(b)[:90]}')
            compare(expected, result, '')
            if differences:
                raise AssertionError('\n'.join(differences[:30]))
        print(f'Echelle {args.scale}: {len(result["scenarios"])} scenarios, geometrie et couleurs metier OK')
    finally:
        app.main_view.destroy()
        for job in app.tk.call('after', 'info'):
            app.after_cancel(job)
        app.destroy()
        session.close()
        if not session.cleaned.wait(10) or session.cleanup_error:
            raise AssertionError(session.cleanup_error or 'Session non nettoyee')


if __name__ == '__main__':
    main()
