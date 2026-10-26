"""Mesure la preparation masquee d'un viewer depuis un bilan deja calcule."""
from pathlib import Path
import argparse
import json
import pickle
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('--legacy', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(args.results / 'sources' if args.legacy else ROOT / 'TraceAlphaViewer'))
    import customtkinter as ctk
    from Models.frame_store import FrameStore
    from Views.traceView import TraceView
    with (args.results / 'result.pkl').open('rb') as stream:
        data = pickle.load(stream)
    navigation_seconds = 0.0
    if not args.legacy and 'navigation' not in data:
        from Models.list_navigation import prepare_navigation
        tick = time.perf_counter()
        data['navigation'] = prepare_navigation(data['events'], data['diagnostics'], data['references'])
        navigation_seconds = time.perf_counter() - tick
    app = ctk.CTk()
    app.withdraw()
    app.geometry('1500x860')
    gaps, error = [], []
    previous = started = time.perf_counter()

    def beat():
        nonlocal previous
        now = time.perf_counter()
        gaps.append(now - previous)
        previous = now
        if now - started > 600:
            error.append('Preparation superieure a dix minutes')
            app.quit()
        else:
            app.after(10, beat)

    with FrameStore(data['store']) as frames:
        options = {} if args.legacy else {'navigation': data.get('navigation')}
        view = TraceView(app, data['filepath'], frames, events=data['events'],
                         diagnostics=data['diagnostics'], references=data['references'], **options)

        def ready():
            view.show()
            app.quit()

        def failed(message):
            error.append(message)
            app.quit()

        app.after(10, beat)
        view.prepare(ready, failed)
        app.mainloop()
        total = time.perf_counter() - started
        result = dict(seconds=total, p95_ms=sorted(gaps)[int((len(gaps) - 1) * .95)] * 1000,
                      max_ms=max(gaps) * 1000, panels=getattr(view, 'preparation_timings', {}),
                      navigation_seconds=navigation_seconds)
        view.destroy()
        for job in app.tk.call('after', 'info'):
            app.after_cancel(job)
        app.destroy()
    if error:
        raise RuntimeError(error[0])
    (args.results / ('viewer-legacy.json' if args.legacy else 'viewer.json')).write_text(
        json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
