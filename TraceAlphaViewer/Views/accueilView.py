"""
AccueilView - ecran de demarrage avec ouverture de fichier trace (.old/.txt).
"""
from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from queue import Empty
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from Models.folder_report import FolderReport, TraceReportEntry
from Models.loading_client import LoadingSession
from Models.loading_progress import PHASES, ProgressTracker, VIEW_SEGMENT
from Models.state import MachineEvent, MachineState
from Views.BaseView import BaseView
from Widgets.ui_theme import UI_COLORS


PROJECT_ROOT = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False)
                else Path(__file__).resolve().parents[1])
TRACE_EXTENSIONS = ('.old', '.txt')
_LANDING_SIGNAL_PATH = (
    0, 31, 80, 31, 89, 31, 96, 19, 106, 43, 116, 13, 128, 48,
    140, 31, 212, 31, 222, 31, 232, 21, 241, 39, 251, 31,
    355, 31, 365, 31, 374, 10, 388, 51, 401, 24, 410, 31, 600, 31,
)
TRACE_DIRS = (
    PROJECT_ROOT,
    PROJECT_ROOT.parent / 'donneesSource',
    PROJECT_ROOT.parent / 'donn\u00e9esSource',
)


def _find_trace_files() -> list[Path]:
    """Retourne les traces trouvees dans les dossiers connus."""
    traces: list[Path] = []
    seen: set[Path] = set()

    for directory in TRACE_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob('*'):
            if not path.is_file() or path.suffix.lower() not in TRACE_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            traces.append(resolved)
            seen.add(resolved)

    return sorted(traces, key=lambda p: p.stat().st_mtime, reverse=True)


def _collect_events(frames: list[MachineState]) -> list[MachineEvent]:
    events: list[MachineEvent] = []
    seen: set[tuple[int, str, str]] = set()
    for frame in frames:
        for event in frame.events:
            key = (event.line_num, event.kind, event.title)
            if key in seen:
                continue
            seen.add(key)
            events.append(event)
    return sorted(events, key=lambda event: (event.line_num, event.kind, event.title))


class AccueilView(BaseView):

    def show(self) -> None:
        super().show()
        self._build()

    def hide(self) -> None:
        super().hide()
        for w in self.winfo_children():
            w.destroy()

    def _build(self) -> None:
        from Models.system_usage import SystemUsage
        self.configure(fg_color=UI_COLORS['background'])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color='transparent')
        header.grid(row=0, column=0, sticky='ew', padx=32, pady=(24, 0))
        self._usage_probe = SystemUsage()
        corner = self._resource_corner = ctk.CTkFrame(header, fg_color='transparent')
        corner.pack(side='right')
        meters = ctk.CTkFrame(corner, fg_color='transparent')
        meters.pack(side='left')
        self._usage_widgets = []
        for title in ('CPU', 'RAM'):
            label = ctk.CTkLabel(meters, text=title + ' : Indisponible',
                                 font=('Consolas', 10), height=18,
                                 text_color='#92a6bb', anchor='w')
            label.pack(fill='x')
            bar = ctk.CTkProgressBar(meters, width=160, height=4,
                                    fg_color='#213043', progress_color=UI_COLORS['accent'])
            bar.set(0)
            bar.pack(pady=(0, 4))
            self._usage_widgets.append((label, bar))
        self._ram_quantity = ctk.CTkLabel(meters, text='', font=('Consolas', 10), height=16,
                                         text_color='#73899f', anchor='w')
        self._ram_quantity.pack(fill='x')
        self._update_usage()
        body = ctk.CTkFrame(self, fg_color='transparent')
        body.grid(row=1, column=0, sticky='nsew', padx=32, pady=4)
        center = self._landing_content = ctk.CTkFrame(body, fg_color='transparent')
        center.place(relx=0.5, rely=0.5, anchor='center')
        ctk.CTkLabel(center, text='LECTURE   /   ANALYSE   /   DIAGNOSTIC',
                     font=('Consolas', 10), text_color=UI_COLORS['accent'], height=18).pack()
        ctk.CTkLabel(
            center,
            text='TraceAlpha Viewer',
            font=('Segoe UI', 38, 'bold'),
            text_color='#f1f6fc',
        ).pack(pady=(8, 0))
        ctk.CTkLabel(center, text='Comprendre chaque mouvement.',
                     font=('Segoe UI', 20), text_color='#a9bed1').pack(pady=(0, 6))
        self._landing_intro = ctk.CTkLabel(center,
            text='Rejouez vos traces, suivez les boîtes et retrouvez les événements clés.',
            font=('Segoe UI', 12), text_color=UI_COLORS['dim'], height=22)
        self._landing_intro.pack()
        self._signal_frame = ctk.CTkFrame(center, width=600, height=62, fg_color='transparent')
        self._signal_frame.pack(fill='x', pady=(16, 22))
        self._signal_frame.pack_propagate(False)
        signal = tk.Canvas(self._signal_frame, background=UI_COLORS['background'], highlightthickness=0, bd=0)
        signal.pack(fill='both', expand=True)
        signal.bind('<Configure>', self._draw_landing_signal)
        actions = self._landing_actions = ctk.CTkFrame(center, fg_color='transparent')
        actions.pack(fill='x')
        self._open_buttons = []
        for number, title, detail, button_text, command, primary in (
            ('01', 'Une trace', 'Un fichier, toute sa chronologie.',
             'Ouvrir une trace (.old/.txt)', self._open_file, True),
            ('02', 'Un dossier', 'Vos traces, regroupées par machine.',
             'Ouvrir un dossier de traces', self._open_folder, False),
        ):
            card = ctk.CTkFrame(actions, fg_color='#122533' if primary else UI_COLORS['panel'],
                               border_color='#294b54' if primary else '#283649',
                               border_width=1, corner_radius=14)
            card.pack(side='left', padx=(0, 12) if primary else 0)
            caption = ctk.CTkFrame(card, fg_color='transparent')
            caption.pack(fill='x', padx=14, pady=(14, 2))
            ctk.CTkLabel(caption, text=number, width=24, height=24, corner_radius=6,
                         fg_color=UI_COLORS['selected'] if primary else '#263347',
                         text_color='#76e4cb' if primary else '#a3bbd3',
                         font=('Consolas', 10)).pack(side='left', padx=(0, 9))
            ctk.CTkLabel(caption, text=title, font=('Segoe UI', 15, 'bold'),
                         text_color=UI_COLORS['text']).pack(side='left')
            ctk.CTkLabel(card, text=detail, font=('Segoe UI', 11), text_color=UI_COLORS['muted'],
                         anchor='w').pack(fill='x', padx=14, pady=(0, 8))
            button = ctk.CTkButton(card, text=button_text, width=270, height=44,
                font=('Segoe UI', 13, 'bold' if primary else 'normal'),
                fg_color=UI_COLORS['accent'] if primary else UI_COLORS['control'],
                hover_color=UI_COLORS['accent_hover'] if primary else UI_COLORS['hover'],
                text_color=UI_COLORS['accent_text'] if primary else '#e1ecf7',
                corner_radius=9, command=command)
            button.pack(padx=9, pady=(0, 12))
            self._open_buttons.append(button)
        self._landing_hint = ctk.CTkLabel(center,
            text='ÉTATS MACHINE     ·     PARCOURS DES BOÎTES     ·     RAPPORTS',
            font=('Consolas', 10), text_color='#71879d', height=22)
        self._landing_hint.pack(pady=(18, 0))

        self._progress_frame = ctk.CTkFrame(center, fg_color='#111f2f', corner_radius=12,
                                           border_width=1, border_color='#2a3c51')

        self._progress_bar = ctk.CTkProgressBar(
            self._progress_frame, width=558, height=6,
            fg_color='#23384b', progress_color=UI_COLORS['accent'],
        )
        self._progress_bar.set(0)

        self._progress_lbl = ctk.CTkLabel(
            self._progress_frame,
            height=18,
            text='',
            font=('Segoe UI', 11, 'bold'), wraplength=540,
            text_color='#b8ccdf',
        )
        self._progress_step_lbl = ctk.CTkLabel(
            self._progress_frame,
            height=18,
            text='',
            font=('Segoe UI', 11), wraplength=540,
            text_color='#96b4ca',
        )
        self._progress_estimate_lbl = ctk.CTkLabel(
            self._progress_frame, text='', height=18, font=('Consolas', 10), text_color=UI_COLORS['accent'])
        self._progress_steps = PHASES
        self._progress_step_rows: dict[str, ctk.CTkLabel] = {}
        self._progress_steps_frame = ctk.CTkFrame(
            self._progress_frame,
            fg_color='transparent',
            corner_radius=8,
            border_width=0,
        )
        for key, label in self._progress_steps:
            row = ctk.CTkLabel(
                self._progress_steps_frame,
                text=f'[ ] {label}',
                font=('Segoe UI', 11),
                text_color='#8ca5bc',
                anchor='w',
                width=0,
                height=18,
            )
            row.pack(anchor='w', padx=10, pady=1)
            self._progress_step_rows[key] = row

        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.grid(row=2, column=0, sticky='ew', padx=32, pady=(0, 22))
        ctk.CTkFrame(footer, height=1, fg_color='#233144').pack(fill='x', pady=(0, 12))
        footline = ctk.CTkFrame(footer, fg_color='transparent')
        footline.pack(fill='x')
        ctk.CTkLabel(footline, text='●  Analyse locale', font=('Segoe UI', 11),
                     text_color='#7f9caa', height=18).pack(side='left')

        ctk.CTkLabel(
            footline, text='Nitr0r & Superbobopo   /   v1.0',
            font=('Segoe UI', 10), text_color='#7f93a9', height=18,
        ).pack(side='right')

    def _draw_landing_signal(self, event):
        """Frise decorative : aucun etat ni aucune mesure de la trace."""
        canvas = event.widget
        size = (event.width, event.height)
        if min(size) < 2 or getattr(canvas, '_signal_size', None) == size:
            return
        try:
            from PIL import Image, ImageDraw, ImageTk
        except ImportError:
            self._draw_landing_signal_native(canvas, *size)
            canvas._signal_size = size
            return
        # Suréchantillonner à la taille affichée pour lisser les diagonales, même en haute résolution.
        quality = 4
        picture = Image.new('RGB', (event.width * quality, event.height * quality), UI_COLORS['background'])
        draw = ImageDraw.Draw(picture)
        sx, sy = event.width / 600, event.height / 62
        def line(points, color, width=1):
            coordinates = [(x * sx * quality, y * sy * quality)
                           for x, y in zip(points[::2], points[1::2])]
            draw.line(coordinates, fill=color, width=max(1, round(width * sx * quality)), joint='curve')
        for y in (12, 31, 50):
            line((0, y, 600, y), '#192b3b')
        for x in range(0, 601, 30):
            line((x, 6, x, 56), '#142333')
        path = _LANDING_SIGNAL_PATH
        line(path, '#153c3d', 7)
        line(path, '#287567', 3)
        line(path, UI_COLORS['accent'], 1.5)
        for x in (80, 212, 355, 500):
            draw.ellipse(((x-3)*sx*quality, 28*sy*quality, (x+3)*sx*quality, 34*sy*quality),
                         fill=UI_COLORS['selected_text'], outline=UI_COLORS['background'],
                         width=max(1, round(sx * quality)))
        photo = ImageTk.PhotoImage(picture.resize(size, Image.Resampling.LANCZOS), master=canvas)
        if getattr(canvas, '_signal_item', None) is not None:
            canvas.itemconfigure(canvas._signal_item, image=photo)
        else:
            canvas.delete('all')
            canvas._signal_item = canvas.create_image(0, 0, anchor='nw', image=photo)
        canvas._signal_photo = photo
        canvas._signal_size = size

    def _draw_landing_signal_native(self, canvas, width, height):
        """Pillow est optionnel : garder un accueil utilisable sans ce module."""
        canvas.delete('all')
        canvas._signal_item = None
        canvas._signal_photo = None
        sx, sy = width / 600, height / 62
        def line(points, color, thickness=1):
            coordinates = [value * (sx if index % 2 == 0 else sy)
                           for index, value in enumerate(points)]
            canvas.create_line(*coordinates, fill=color, width=thickness * sx)
        for y in (12, 31, 50):
            line((0, y, 600, y), '#192b3b')
        for x in range(0, 601, 30):
            line((x, 6, x, 56), '#142333')
        for color, thickness in (('#153c3d', 7), ('#287567', 3), (UI_COLORS['accent'], 1.5)):
            line(_LANDING_SIGNAL_PATH, color, thickness)
        for x in (80, 212, 355, 500):
            canvas.create_oval((x-3)*sx, 28*sy, (x+3)*sx, 34*sy,
                fill=UI_COLORS['selected_text'], outline=UI_COLORS['background'], width=1)

    def _update_usage(self):
        cpu, memory = self._usage_probe.sample()
        label, bar = self._usage_widgets[0]
        label.configure(text='CPU : Indisponible' if cpu is None else f'CPU : {cpu:.0%}')
        bar.set(cpu or 0)
        label, bar = self._usage_widgets[1]
        if memory.reliable:
            used = memory.total - memory.available
            ratio = used / memory.total
            label.configure(text=f'RAM : {ratio:.0%}')
            self._ram_quantity.configure(text=f'{used / 1024**3:.1f}/{memory.total / 1024**3:.1f} Gio')
            bar.set(ratio)
        else:
            label.configure(text='RAM : Indisponible')
            self._ram_quantity.configure(text='')
            bar.set(0)
        self.after(1000, self._update_usage)

    def _open_file(self) -> None:
        initial_dir = str(getattr(self.master, '_trace_dialog_directory', PROJECT_ROOT))
        path = filedialog.askopenfilename(
            title='Ouvrir une trace AlphaV2',
            initialdir=initial_dir,
            filetypes=[
                ('Traces AlphaV2', '*.old *.txt'),
                ('Trace .old', '*.old'),
                ('Trace .txt', '*.txt'),
                ('Tous les fichiers', '*.*'),
            ],
        )
        if path:
            self.master._trace_dialog_directory = Path(path).parent
            self._load(path)

    def _open_folder(self) -> None:
        initial_dir = str(getattr(self.master, '_trace_dialog_directory', PROJECT_ROOT))
        path = filedialog.askdirectory(
            title='Ouvrir un dossier de traces AlphaV2',
            initialdir=initial_dir,
        )
        if path:
            self.master._trace_dialog_directory = Path(path)
            self._load_folder(path)

    def _load(self, path: str) -> None:
        self._start_loading('file', path)

    def _load_folder(self, path: str) -> None:
        self._start_loading('folder_catalog', path)

    def _start_loading(self, mode: str, path: str) -> None:
        if getattr(self, '_load_busy', False):
            return
        path = str(Path(path).resolve())
        self._load_busy = True
        self._progress_tracker = ProgressTracker(mode)
        self._progress_rendered_at = -float('inf')
        self._progress_render_job = None
        self._show_progress(True)
        self._progress_bar.set(0)
        self._set_progress_text(
            f'Analyse de la trace : {os.path.basename(path)}',
            'Lecture du fichier trace...',
            current_step='read',
        )
        self._render_progress(force=True)

        self._load_mode = mode
        self._load_path = path
        self._loaded_entries = []
        self._load_data = None
        self._folder_catalog = None
        self._prepared_view = None
        self._preloaded_trace = None
        self._prepare_when_raw_ready = False
        try:
            self._load_session = LoadingSession()
            self._load_task = self._load_session.start(mode, path=path)
            if mode == 'file' and Path(path).is_file():
                from Models.resource_policy import detect_resources, budget_for, worker_estimate
                resources = detect_resources()
                if resources.reliable and resources.cpus >= 4 and budget_for(resources) >= 4 * worker_estimate(Path(path).stat().st_size):
                    from Widgets.trace_panel import TracePanel
                    self._preloaded_trace = TracePanel(self)
                    self._raw_preload_started = time.perf_counter()
                    self._preloaded_trace.load_file(path, on_ready=self._raw_prepared,
                        on_error=self._on_error, on_progress=self._accept_progress)
            self.after(10, self._poll_loading)
        except Exception as exc:
            self._on_error(str(exc))

    def _poll_loading(self) -> None:
        if not self._load_busy:
            return
        deadline = time.perf_counter() + 0.008
        try:
            while time.perf_counter() < deadline:
                kind, payload = self._load_task.results.get_nowait()
                if kind == 'progress':
                    self._accept_progress(payload)
                elif kind == 'step':
                    self._set_progress_text(*payload)
                elif kind == 'entry':
                    self._load_data = dict(payload, events=[], diagnostics=[], references=[])
                    self._load_data['frames'] = (
                        self._load_session.open_store(payload['store']) if payload['store'] else []
                    )
                elif kind == 'catalog':
                    self._folder_catalog = payload
                elif kind in ('events', 'diagnostics', 'references'):
                    self._load_data[kind].extend(payload)
                elif kind == 'entry_done':
                    data = self._load_data
                    for key, expected in payload.items():
                        if len(data[key]) != expected:
                            raise OSError('Resultats de chargement incomplets')
                    self._loaded_entries.append(data)
                elif kind == 'done':
                    self._load_timings = payload['timings']
                    self._prepare_loaded_view()
                    return
                elif kind == 'error':
                    self._on_error(payload)
                    return
        except Empty:
            pass
        except Exception as exc:
            self._on_error(str(exc))
            return
        self.after(10, self._poll_loading)

    def _prepare_loaded_view(self) -> None:
        if self._preloaded_trace is not None and self._preloaded_trace._loading:
            self._prepare_when_raw_ready = True
            return
        self._set_progress_text('Preparation du viewer', "Preparation de l'affichage...", 'display')
        self._accept_progress(dict(phase='display', segment=VIEW_SEGMENT, task='Preparation du viewer'))
        if self._load_mode == 'folder_catalog':
            from Views.alphaFolderView import AlphaFolderView
            view = AlphaFolderView(self.master, self._load_path, self._folder_catalog,
                                   load_session=self._load_session)
        elif self._load_mode == 'file':
            data = self._loaded_entries[0]
            from Views.traceView import TraceView
            view = TraceView(self.master, data['filepath'], data['frames'],
                             events=data['events'], diagnostics=data['diagnostics'],
                             references=data['references'], load_session=self._load_session,
                             navigation=data.get('navigation'), preloaded_trace=self._preloaded_trace)
            if self._preloaded_trace is not None:
                view.preparation_timings['prechargement_trace'] = self._raw_preload_seconds
                self._preloaded_trace = None
        else:
            from Views.folderTraceView import FolderTraceView
            entries = [TraceReportEntry(
                filepath=data['filepath'], name=data['name'], modified_ts=data['modified_ts'],
                frames=data['frames'], events=data['events'], diagnostics=data['diagnostics'],
                error_events=[event for event in data['events'] if event.severity == 'error'],
                parse_error=data['parse_error'],
            ) for data in self._loaded_entries]
            view = FolderTraceView(self.master, FolderReport(self._load_path, entries),
                                   load_session=self._load_session)
        self._prepared_view = view
        if self._load_mode in ('file', 'folder_catalog'):
            view.prepare(lambda: self._finish_loading(view), on_error=self._on_error,
                         on_progress=self._accept_progress)
        else:
            view.prepare(lambda: self._finish_loading(view), on_error=self._on_error)

    def _raw_prepared(self):
        self._raw_preload_seconds = time.perf_counter() - self._raw_preload_started
        if self._prepare_when_raw_ready and self._load_busy:
            self._prepare_when_raw_ready = False
            self.after(0, self.preparation_step, self._prepare_loaded_view, self._on_error)

    def _discard_preloaded_trace(self):
        source = getattr(self, '_preloaded_trace', None)
        if source is not None:
            source.destroy()
            self._preloaded_trace = None

    def _finish_loading(self, view) -> None:
        self._progress_tracker.ready()
        self._render_progress(force=True)
        self._load_busy = False
        self._load_session = None
        self._prepared_view = None
        self._loaded_entries = []
        self._load_data = None
        self._load_task = None
        self.master.switch_view(view)

    def destroy(self) -> None:
        self._discard_preloaded_trace()
        session = getattr(self, '_load_session', None)
        if session is not None:
            session.close()
        prepared = getattr(self, '_prepared_view', None)
        if prepared is not None:
            prepared.destroy()
        super().destroy()

    def _show_progress(self, visible: bool) -> None:
        if visible:
            self._landing_intro.pack_forget()
            self._signal_frame.pack_forget()
            self._landing_hint.pack_forget()
            self._landing_actions.pack_configure(pady=(18, 0))
            self._progress_frame.pack(pady=(12, 0), fill='x')
            self._progress_bar.pack(padx=18, pady=(16, 8))
            self._progress_lbl.pack(padx=18)
            self._progress_step_lbl.pack(padx=18)
            self._progress_estimate_lbl.pack()
            self._progress_steps_frame.pack(padx=18, pady=(6, 12))
        else:
            self._progress_frame.pack_forget()
            self._progress_bar.pack_forget()
            self._progress_lbl.pack_forget()
            self._progress_step_lbl.pack_forget()
            self._progress_estimate_lbl.pack_forget()
            self._progress_steps_frame.pack_forget()
            self._landing_actions.pack_configure(pady=0)
            self._landing_intro.pack(before=self._landing_actions)
            self._signal_frame.pack(fill='x', pady=(16, 22), before=self._landing_actions)
            self._landing_hint.pack(pady=(18, 0))

    def _set_progress_text(self, title: str, step: str, current_step: str | None = None) -> None:
        self._progress_lbl.configure(text=title, text_color='#b8ccdf')
        self._progress_step_lbl.configure(text=step, text_color='#96b4ca')
        self._update_progress_steps(current_step)

    def _update_progress_steps(self, current_step: str | None) -> None:
        tracker = getattr(self, '_progress_tracker', None)
        if tracker is None:
            return
        for key, label in self._progress_steps:
            row = self._progress_step_rows.get(key)
            if row is None:
                continue
            state = tracker.phase_state(key)
            if state == 'unused':
                row.pack_forget()
                continue
            if not row.winfo_manager():
                row.pack(anchor='w', padx=10, pady=1)
            if state == 'done':
                row.configure(text=f'[OK] {label}', text_color='#7ccda9')
            elif state == 'running':
                row.configure(text=f'[..] {label}', text_color=UI_COLORS['accent'])
            else:
                row.configure(text=f'[ ] {label}', text_color=UI_COLORS['dim'])

    def _accept_progress(self, payload):
        self._progress_tracker.update(payload)
        self._render_progress()

    def _render_progress(self, force=False):
        if self._progress_render_job is not None:
            if not force:
                return
            self.after_cancel(self._progress_render_job)
            self._progress_render_job = None
        remaining = .1 - (time.perf_counter() - self._progress_rendered_at)
        if remaining > 0 and not force:
            self._progress_render_job = self.after(max(1, int(remaining * 1000)), self._flush_progress)
            return
        self._progress_rendered_at = time.perf_counter()
        tracker = self._progress_tracker
        self._progress_bar.set(tracker.fraction)
        self._progress_estimate_lbl.configure(text=f'Progression estimee : {int(tracker.fraction * 100)} %')
        if tracker.task:
            self._progress_step_lbl.configure(text=tracker.task)
        self._update_progress_steps(tracker.phase)

    def _flush_progress(self):
        self._progress_render_job = None
        self._render_progress()

    def _on_loaded(self, path: str, frames, events, diagnostics, references) -> None:
        self._load_busy = False
        self._show_progress(False)
        from Views.traceView import TraceView
        view = TraceView(
            self.master,
            filepath=path,
            frames=frames,
            events=events,
            diagnostics=diagnostics,
            references=references,
        )
        self.master.switch_view(view)

    def _on_folder_loaded(self, report) -> None:
        self._load_busy = False
        self._show_progress(False)
        from Views.folderTraceView import FolderTraceView
        view = FolderTraceView(self.master, report=report)
        self.master.switch_view(view)

    def _on_error(self, msg: str) -> None:
        self._discard_preloaded_trace()
        job = getattr(self, '_progress_render_job', None)
        if job is not None:
            self.after_cancel(job)
            self._progress_render_job = None
        session = getattr(self, '_load_session', None)
        if session is not None:
            session.close()
            self._load_session = None
        prepared = getattr(self, '_prepared_view', None)
        if prepared is not None:
            prepared.destroy()
            self._prepared_view = None
        self._load_task = None
        self._load_data = None
        self._loaded_entries = []
        self._load_busy = False
        self._show_progress(True)
        for widget in (self._progress_bar, self._progress_step_lbl,
                       self._progress_estimate_lbl, self._progress_steps_frame):
            widget.pack_forget()
        self._progress_lbl.configure(
            text=f'Erreur : {msg}', text_color='#ff6666'
        )
        self._progress_lbl.pack(padx=18, pady=14)
        self._progress_step_lbl.configure(text='')
