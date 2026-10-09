"""
AccueilView - ecran de demarrage avec ouverture de fichier trace (.old/.txt).
"""
from __future__ import annotations

import os
import time
from queue import Empty
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from Models.folder_report import FolderReport, TraceReportEntry
from Models.loading_client import LoadingSession
from Models.state import MachineEvent, MachineState
from Views.BaseView import BaseView


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRACE_EXTENSIONS = ('.old', '.txt')
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
        center = ctk.CTkFrame(self, fg_color='transparent')
        center.place(relx=0.5, rely=0.5, anchor='center')

        ctk.CTkLabel(
            center,
            text='TraceAlpha Viewer',
            font=('Consolas', 32, 'bold'),
            text_color='#4FC3F7',
        ).pack(pady=(0, 4))

        ctk.CTkLabel(
            center,
            text='Visualiseur de traces AlphaV2',
            font=('Consolas', 13),
            text_color='#445566',
        ).pack(pady=(0, 40))

        ctk.CTkButton(
            center,
            text='Ouvrir une trace (.old/.txt)',
            font=('Consolas', 15, 'bold'),
            width=300, height=52,
            fg_color='#1e3a5f',
            hover_color='#2a4a7f',
            text_color='#aaccff',
            corner_radius=10,
            command=self._open_file,
        ).pack(pady=8)

        ctk.CTkButton(
            center,
            text='Ouvrir un dossier de traces',
            font=('Consolas', 14),
            width=300, height=44,
            fg_color='#252538',
            hover_color='#353555',
            text_color='#aaccff',
            corner_radius=10,
            command=self._open_folder,
        ).pack(pady=(4, 8))

        self._progress_frame = ctk.CTkFrame(center, fg_color='transparent')
        self._progress_frame.pack(pady=(20, 0), fill='x')

        self._progress_bar = ctk.CTkProgressBar(
            self._progress_frame, width=300, height=12,
            fg_color='#1a1a2e', progress_color='#4FC3F7',
        )
        self._progress_bar.set(0)

        self._progress_lbl = ctk.CTkLabel(
            self._progress_frame,
            text='',
            font=('Consolas', 10, 'bold'),
            text_color='#667788',
        )
        self._progress_step_lbl = ctk.CTkLabel(
            self._progress_frame,
            text='',
            font=('Consolas', 10),
            text_color='#445566',
        )
        self._progress_steps = [
            ('read', 'Lecture du fichier'),
            ('events', 'Construction des evenements'),
            ('diagnostic', 'Analyse diagnostic'),
            ('references', 'Index references'),
            ('display', 'Preparation affichage'),
        ]
        self._progress_step_rows: dict[str, ctk.CTkLabel] = {}
        self._progress_steps_frame = ctk.CTkFrame(
            self._progress_frame,
            fg_color='#171b25',
            corner_radius=8,
            border_width=1,
            border_color='#263142',
        )
        for key, label in self._progress_steps:
            row = ctk.CTkLabel(
                self._progress_steps_frame,
                text=f'[ ] {label}',
                font=('Consolas', 9),
                text_color='#4c5d70',
                anchor='w',
                width=300,
            )
            row.pack(anchor='w', padx=10, pady=1)
            self._progress_step_rows[key] = row

        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.place(relx=1.0, rely=1.0, anchor='se', x=-8, y=-6)

        ctk.CTkLabel(
            footer,
            text='by Nitr0r & Superbobopo',
            font=('Consolas', 10),
            text_color='#3c4d62',
        ).pack(anchor='e')

        ctk.CTkLabel(
            footer,
            text='v1.0',
            font=('Consolas', 9),
            text_color='#2a2a3a',
        ).pack(anchor='e', pady=(1, 0))

    def _open_file(self) -> None:
        trace_files = _find_trace_files()
        initial_dir = str(trace_files[0].parent if trace_files else PROJECT_ROOT)
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
            self._load(path)

    def _open_folder(self) -> None:
        trace_files = _find_trace_files()
        initial_dir = str(trace_files[0].parent if trace_files else PROJECT_ROOT)
        path = filedialog.askdirectory(
            title='Ouvrir un dossier de traces AlphaV2',
            initialdir=initial_dir,
        )
        if path:
            self._load_folder(path)

    def _load(self, path: str) -> None:
        self._start_loading('file', path)

    def _load_folder(self, path: str) -> None:
        self._start_loading('folder', path)

    def _start_loading(self, mode: str, path: str) -> None:
        if getattr(self, '_load_busy', False):
            return
        path = str(Path(path).resolve())
        self._load_busy = True
        self._show_progress(True)
        self._progress_bar.set(0)
        self._set_progress_text(
            f'Analyse de la trace : {os.path.basename(path)}',
            'Lecture du fichier trace...',
            current_step='read',
        )

        self._load_mode = mode
        self._load_path = path
        self._loaded_entries = []
        self._load_data = None
        self._prepared_view = None
        try:
            self._load_session = LoadingSession()
            self._load_task = self._load_session.start(mode, path=path)
            self.after(10, self._poll_loading)
        except Exception as exc:
            self._on_error(str(exc))

    def _poll_loading(self) -> None:
        deadline = time.perf_counter() + 0.008
        progress = None
        try:
            while time.perf_counter() < deadline:
                kind, payload = self._load_task.results.get_nowait()
                if kind == 'progress':
                    progress = payload
                elif kind == 'step':
                    if progress is not None:
                        self._progress_bar.set(progress)
                        progress = None
                    self._set_progress_text(*payload)
                elif kind == 'entry':
                    self._load_data = dict(payload, events=[], diagnostics=[], references=[])
                    self._load_data['frames'] = (
                        self._load_session.open_store(payload['store']) if payload['store'] else []
                    )
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
        if progress is not None:
            self._progress_bar.set(progress)
        self.after(10, self._poll_loading)

    def _prepare_loaded_view(self) -> None:
        self._progress_bar.set(1.0)
        self._set_progress_text('Preparation du viewer', "Preparation de l'affichage...", 'display')
        if self._load_mode == 'file':
            data = self._loaded_entries[0]
            from Views.traceView import TraceView
            view = TraceView(self.master, data['filepath'], data['frames'],
                             events=data['events'], diagnostics=data['diagnostics'],
                             references=data['references'], load_session=self._load_session)
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
        view.prepare(lambda: self._finish_loading(view), on_error=self._on_error)

    def _finish_loading(self, view) -> None:
        self._load_busy = False
        self._load_session = None
        self._prepared_view = None
        self._loaded_entries = []
        self._load_data = None
        self._load_task = None
        self.master.switch_view(view)

    def destroy(self) -> None:
        session = getattr(self, '_load_session', None)
        if session is not None:
            session.close()
        prepared = getattr(self, '_prepared_view', None)
        if prepared is not None:
            prepared.destroy()
        super().destroy()

    def _show_progress(self, visible: bool) -> None:
        if visible:
            self._progress_bar.pack(pady=(4, 2))
            self._progress_lbl.pack()
            self._progress_step_lbl.pack()
            self._progress_steps_frame.pack(pady=(8, 0), fill='x')
        else:
            self._progress_bar.pack_forget()
            self._progress_lbl.pack_forget()
            self._progress_step_lbl.pack_forget()
            self._progress_steps_frame.pack_forget()

    def _set_progress_text(self, title: str, step: str, current_step: str | None = None) -> None:
        self._progress_lbl.configure(text=title, text_color='#667788')
        self._progress_step_lbl.configure(text=step, text_color='#445566')
        self._update_progress_steps(current_step)

    def _update_progress_steps(self, current_step: str | None) -> None:
        if current_step is None:
            return
        keys = [key for key, _ in self._progress_steps]
        current_index = keys.index(current_step) if current_step in keys else -1
        for index, (key, label) in enumerate(self._progress_steps):
            row = self._progress_step_rows.get(key)
            if row is None:
                continue
            if index < current_index:
                row.configure(text=f'[OK] {label}', text_color='#5aa469')
            elif index == current_index:
                row.configure(text=f'[..] {label}', text_color='#4FC3F7')
            else:
                row.configure(text=f'[ ] {label}', text_color='#4c5d70')

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
        self._show_progress(False)
        self._progress_lbl.configure(
            text=f'Erreur : {msg}', text_color='#ff6666'
        )
        self._progress_lbl.pack()
        self._progress_step_lbl.configure(text='')
