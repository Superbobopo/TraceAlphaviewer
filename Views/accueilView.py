"""
AccueilView - ecran de demarrage avec ouverture de fichier trace (.old/.txt).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

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

        q_frame = ctk.CTkFrame(center, fg_color='transparent')
        q_frame.pack(pady=(16, 0))
        ctk.CTkLabel(q_frame, text='Qualite :',
                     font=('Consolas', 11), text_color='#445566').pack(side='left', padx=(0, 8))
        self._quality_var = ctk.StringVar(value='normal')
        for lbl, val in [('Rapide (5s)', 'rapide'), ('Normal (2s)', 'normal'), ('Fin (0.5s)', 'fin')]:
            ctk.CTkRadioButton(q_frame, text=lbl, variable=self._quality_var, value=val,
                               font=('Consolas', 10), text_color='#667788').pack(side='left', padx=6)

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
            font=('Consolas', 10),
            text_color='#445566',
        )

        ctk.CTkLabel(
            self,
            text='v1.0',
            font=('Consolas', 9),
            text_color='#2a2a3a',
        ).place(relx=1.0, rely=1.0, anchor='se', x=-6, y=-4)

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

    def _load(self, path: str) -> None:
        """Lance le parsing dans un thread et affiche la progression."""
        self._show_progress(True)
        self._progress_bar.set(0)
        self._progress_lbl.configure(text=f'Chargement : {os.path.basename(path)}')

        quality_map = {'rapide': 5.0, 'normal': 2.0, 'fin': 0.5}
        min_dt = quality_map.get(self._quality_var.get(), 2.0)

        def worker():
            from Parser.trace_parser import parse_file

            def on_progress(done, total):
                ratio = done / max(total, 1)
                self.after(0, self._progress_bar.set, ratio)

            try:
                frames = parse_file(path, progress_cb=on_progress, min_dt=min_dt)
                self.after(0, self._on_loaded, path, frames)
            except Exception as e:
                self.after(0, self._on_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _show_progress(self, visible: bool) -> None:
        if visible:
            self._progress_bar.pack(pady=(4, 2))
            self._progress_lbl.pack()
        else:
            self._progress_bar.pack_forget()
            self._progress_lbl.pack_forget()

    def _on_loaded(self, path: str, frames) -> None:
        self._show_progress(False)
        from Views.traceView import TraceView
        view = TraceView(self.master, filepath=path, frames=frames)
        self.master.switch_view(view)

    def _on_error(self, msg: str) -> None:
        self._show_progress(False)
        self._progress_lbl.configure(
            text=f'Erreur : {msg}', text_color='#ff6666'
        )
        self._progress_lbl.pack()
