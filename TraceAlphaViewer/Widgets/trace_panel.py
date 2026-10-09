"""
TracePanel – affiche la trace complète du fichier .old.

• Chargement asynchrone du fichier (blocs de 500 lignes)
• Chaque ligne = "L.XXXXXX  texte"
• Lignes du frame courant surlignées en bleu
• Clic sur une ligne → callback(file_line_num: int)
• Lignes inconnues (hors keywords) affichées en gris atténué
"""
from __future__ import annotations

import threading
from queue import Empty, Queue, Full
import time
from typing import Callable, List, Optional, Tuple

import customtkinter as ctk
import tkinter as tk


class TracePanel(ctk.CTkFrame):
    """Panneau trace complète avec navigation par clic."""

    def __init__(self, master,
                 on_line_click: Optional[Callable[[int], None]] = None,
                 **kwargs):
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self._on_line_click = on_line_click
        self._total_lines = 0
        self._hi_start: int = 0
        self._hi_end:   int = 0
        self._load_generation = 0
        self._load_cancel = threading.Event()
        self._load_results = Queue(maxsize=4)
        self._stream_started = False
        self._poll_job = None
        self._insert_job = None
        self._search_job = None
        self._loading = False
        self._search_var = tk.StringVar()
        self._search_matches = []
        self._search_index = -1
        self._search_pending_direction = None
        self._build()
        self._poll_job = self.after(30, self._poll_results)

    # ── Construction ─────────────────────────────────────────────────────────
    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color='#1e1e30', corner_radius=0)
        header.pack(fill='x')
        ctk.CTkLabel(header, text='CIP / texte', font=('Consolas', 10)).pack(side='left', padx=8)
        search = ctk.CTkEntry(header, textvariable=self._search_var, height=26)
        search.pack(side='left', fill='x', expand=True, padx=4, pady=4)
        search.bind('<Return>', lambda e: self._navigate_search(1))
        search.bind('<F3>', lambda e: self._navigate_search(1))
        search.bind('<Shift-F3>', lambda e: self._navigate_search(-1))
        for label, direction in (('<', -1), ('>', 1)):
            ctk.CTkButton(header, text=label, width=30, height=26,
                          command=lambda d=direction: self._navigate_search(d)).pack(side='left', padx=2)
        self._search_label = ctk.CTkLabel(header, text='', width=120, font=('Consolas', 10))
        self._search_label.pack(side='left', padx=8)
        self._search_var.trace_add('write', lambda *_: self._queue_search())
        # Scrollbars
        vscroll = tk.Scrollbar(self, orient='vertical',
                                bg='#1a1a2e', troughcolor='#12121f',
                                activebackground='#334455')
        vscroll.pack(side='right', fill='y')

        hscroll = tk.Scrollbar(self, orient='horizontal',
                                bg='#1a1a2e', troughcolor='#12121f',
                                activebackground='#334455')
        hscroll.pack(side='bottom', fill='x')

        # Widget texte
        self._text = tk.Text(
            self,
            bg='#12121f', fg='#aabbcc',
            font=('Consolas', 10),
            wrap='none',
            cursor='arrow',
            state='disabled',
            selectbackground='#1e2d44',
            insertbackground='#4FC3F7',
            yscrollcommand=vscroll.set,
            xscrollcommand=hscroll.set,
            relief='flat', borderwidth=0,
        )
        self._text.pack(fill='both', expand=True)
        vscroll.config(command=self._text.yview)
        hscroll.config(command=self._text.xview)

        # Tags de mise en forme
        self._text.tag_configure(
            'linenum', foreground='#334455', font=('Consolas', 9))
        self._text.tag_configure(
            'unknown', foreground='#3a4a55',
            font=('Consolas', 9, 'italic'))
        self._text.tag_configure(
            'known', foreground='#aabbcc')
        self._text.tag_configure(
            'hi', background='#1a2d45', foreground='#ddeeff')
        self._text.tag_configure(
            'hi_linenum', background='#1a2d45', foreground='#4477aa',
            font=('Consolas', 9))
        self._text.tag_configure('search', background='#62501e', foreground='#fff0b0')
        self._text.tag_configure('search_current', background='#aa731a', foreground='#ffffff')

        # Clic
        self._text.bind('<Button-1>', self._on_click)

    # ── Chargement du fichier ─────────────────────────────────────────────────
    def load_file(self, filepath: str) -> None:
        """Charge le fichier en arrière-plan et insère les lignes dans le widget."""
        self._load_cancel.set()
        self._load_cancel = threading.Event()
        cancel = self._load_cancel
        self._load_generation += 1
        generation = self._load_generation
        self._load_results = Queue(maxsize=4)
        results = self._load_results
        self._stream_started = False
        self._loading = True
        self._total_lines = 0
        self._hi_start = self._hi_end = 0
        if self._insert_job:
            self.after_cancel(self._insert_job)
            self._insert_job = None
        self._queue_search()
        self._text.configure(state='normal')
        self._text.delete('1.0', 'end')
        self._text.insert('end', 'Chargement de la trace…\n',
                           ('known',))
        self._text.configure(state='disabled')

        def _worker():
            def put(kind, value):
                while not cancel.is_set():
                    try:
                        results.put((generation, kind, value), timeout=0.05)
                        return True
                    except Full:
                        pass
                return False
            try:
                lines = []
                total_lines = 0
                with open(filepath, encoding='latin-1', errors='replace') as fh:
                    for i, raw in enumerate(fh, 1):
                        if cancel.is_set():
                            return
                        lines.append((i, raw.rstrip('\r\n')))
                        total_lines = i
                        if len(lines) == 500:
                            if not put('lines', lines):
                                return
                            lines = []
                if lines and not put('lines', lines):
                    return
                put('done', total_lines)
            except Exception as exc:
                put('error', f'Erreur lecture : {exc}')

        threading.Thread(target=_worker, daemon=True).start()

    def _poll_results(self) -> None:
        self._poll_job = None
        deadline = time.perf_counter() + 0.008
        try:
            while time.perf_counter() < deadline:
                generation, kind, value = self._load_results.get_nowait()
                if generation == self._load_generation:
                    if not self._stream_started:
                        self._text.configure(state='normal')
                        self._text.delete('1.0', 'end')
                        self._text.configure(state='disabled')
                        self._stream_started = True
                    if kind == 'lines':
                        self._append_lines(value)
                        self._total_lines = value[-1][0]
                    else:
                        if kind == 'error':
                            self._append_lines([(self._total_lines + 1, value)])
                            self._total_lines += 1
                        else:
                            self._total_lines = value
                        self._finish_insert()
        except Empty:
            pass
        self._poll_job = self.after(1 if self._loading else 30, self._poll_results)

    def _append_lines(self, lines):
        segments = []
        for num, text in lines:
            segments.extend((f'L.{num:<7} ', ('linenum',), text + '\n', ('known',)))
        if segments:
            self._text.configure(state='normal')
            self._text.insert('end', *segments)
            self._text.configure(state='disabled')

    def _finish_insert(self):
        self._loading = False
        self._queue_search()
        if self._hi_start > 0:
            self.highlight_lines(self._hi_start, self._hi_end)

    def _start_insert(self, lines: List[Tuple[int, str]]) -> None:
        self._total_lines = len(lines)
        self._text.configure(state='normal')
        self._text.delete('1.0', 'end')
        self._text.configure(state='disabled')
        self._insert_chunk(lines, 0)

    def _insert_chunk(self, lines: List[Tuple[int, str]], start: int,
                      chunk: int = 500) -> None:
        self._insert_job = None
        if start >= len(lines):
            self._finish_insert()
            return
        end = min(start + chunk, len(lines))
        self._append_lines(lines[start:end])
        if end < len(lines):
            self._insert_job = self.after(1, lambda: self._insert_chunk(lines, end, chunk))
        else:
            self._finish_insert()

    def _queue_search(self) -> None:
        if self._search_job:
            self.after_cancel(self._search_job)
            self._search_job = None
        self._search_matches = []
        self._search_index = -1
        self._search_pending_direction = None
        self._text.tag_remove('search', '1.0', 'end')
        self._text.tag_remove('search_current', '1.0', 'end')
        query = self._search_var.get().strip()
        self._search_label.configure(text='Chargement...' if query and self._loading else '')
        if query and not self._loading:
            self._search_job = self.after(180, lambda: self._search_chunk(query, '1.10'))

    def _search_chunk(self, query: str, start: str) -> None:
        self._search_job = None
        count = tk.IntVar()
        for _ in range(200):
            found = self._text.search(query, start, stopindex='end', nocase=True, count=count)
            if not found:
                self._search_label.configure(text=f'{len(self._search_matches)} occurrence(s)')
                direction = self._search_pending_direction
                self._search_pending_direction = None
                if direction is not None:
                    self._navigate_search(direction)
                return
            end = self._text.index(f'{found}+{count.get()}c')
            # Exclut les numeros de ligne ajoutes par le viewer.
            if int(found.split('.')[1]) >= 10:
                self._search_matches.append((found, end))
                self._text.tag_add('search', found, end)
            start = end
        self._search_label.configure(text=f'{len(self._search_matches)}...')
        self._search_job = self.after(1, lambda: self._search_chunk(query, start))

    def _navigate_search(self, direction: int) -> str:
        if self._search_job:
            self._search_pending_direction = direction
            return 'break'
        if not self._search_matches:
            return 'break'
        if self._search_index < 0:
            self._search_index = 0 if direction > 0 else len(self._search_matches) - 1
        else:
            self._search_index = (self._search_index + direction) % len(self._search_matches)
        start, end = self._search_matches[self._search_index]
        if self._on_line_click:
            self._on_line_click(int(start.split('.')[0]))
        self._text.tag_remove('search_current', '1.0', 'end')
        self._text.tag_add('search_current', start, end)
        self._text.tag_raise('search')
        self._text.tag_raise('search_current')
        self._text.see(start)
        self._search_label.configure(text=f'{self._search_index + 1}/{len(self._search_matches)}')
        return 'break'

    def destroy(self) -> None:
        self._load_cancel.set()
        for job in (self._poll_job, self._insert_job, self._search_job):
            if job:
                self.after_cancel(job)
        super().destroy()

    # ── Highlight ─────────────────────────────────────────────────────────────
    def highlight_lines(self, start: int, end: int) -> None:
        """Surligne les lignes fichier [start, end] (1-based)."""
        self._hi_start = start
        self._hi_end   = end
        self._text.tag_remove('hi',       '1.0', 'end')
        self._text.tag_remove('hi_linenum', '1.0', 'end')
        s = f'{start}.0'
        e = f'{end + 1}.0'
        self._text.tag_add('hi',        s, e)
        # Le préfixe "L.XXXXXX " a un tag séparé pour garder la couleur atténuée
        for ln in range(start, end + 1):
            # Colonne 0 à 9 = préfixe "L.NNNNNNN "
            self._text.tag_add('hi_linenum', f'{ln}.0', f'{ln}.9')
        self._text.see(s)

    def clear_highlight(self) -> None:
        """Retire le surlignage courant de la trace."""
        self._hi_start = 0
        self._hi_end = 0
        self._text.tag_remove('hi', '1.0', 'end')
        self._text.tag_remove('hi_linenum', '1.0', 'end')

    def mark_unknown_lines(self, file_lines: List[int]) -> None:
        """Colore en gris les lignes non reconnues par le parser."""
        for ln in file_lines:
            self._text.tag_add('unknown', f'{ln}.9', f'{ln}.end')
            self._text.tag_remove('known', f'{ln}.9', f'{ln}.end')

    # ── Clic ─────────────────────────────────────────────────────────────────
    def _on_click(self, event) -> None:
        if not self._on_line_click:
            return
        idx = self._text.index(f'@{event.x},{event.y}')
        line_num = int(idx.split('.')[0])
        if 1 <= line_num <= self._total_lines:
            self._on_line_click(line_num)
