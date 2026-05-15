"""
TracePanel – affiche la trace complète du fichier .old.

• Chargement asynchrone du fichier (chunks de 3000 lignes)
• Chaque ligne = "L.XXXXXX  texte"
• Lignes du frame courant surlignées en bleu
• Clic sur une ligne → callback(file_line_num: int)
• Lignes inconnues (hors keywords) affichées en gris atténué
"""
from __future__ import annotations

import threading
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
        self._build()

    # ── Construction ─────────────────────────────────────────────────────────
    def _build(self) -> None:
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

        # Clic
        self._text.bind('<Button-1>', self._on_click)

    # ── Chargement du fichier ─────────────────────────────────────────────────
    def load_file(self, filepath: str) -> None:
        """Charge le fichier en arrière-plan et insère les lignes dans le widget."""
        self._text.configure(state='normal')
        self._text.delete('1.0', 'end')
        self._text.insert('end', 'Chargement de la trace…\n',
                           ('known',))
        self._text.configure(state='disabled')

        def _worker():
            lines: List[Tuple[int, str]] = []
            try:
                with open(filepath, encoding='latin-1', errors='replace') as fh:
                    for i, raw in enumerate(fh, 1):
                        lines.append((i, raw.rstrip('\r\n')))
            except Exception as exc:
                lines = [(1, f'Erreur lecture : {exc}')]
            self.after(0, lambda: self._start_insert(lines))

        threading.Thread(target=_worker, daemon=True).start()

    def _start_insert(self, lines: List[Tuple[int, str]]) -> None:
        self._total_lines = len(lines)
        self._text.configure(state='normal')
        self._text.delete('1.0', 'end')
        self._text.configure(state='disabled')
        self._insert_chunk(lines, 0)

    def _insert_chunk(self, lines: List[Tuple[int, str]], start: int,
                      chunk: int = 3000) -> None:
        if start >= len(lines):
            return
        self._text.configure(state='normal')
        end = min(start + chunk, len(lines))
        for (num, text) in lines[start:end]:
            prefix = f'L.{num:<7} '
            self._text.insert('end', prefix, ('linenum',))
            self._text.insert('end', text + '\n', ('known',))
        self._text.configure(state='disabled')
        if end < len(lines):
            self.after(5, lambda: self._insert_chunk(lines, end, chunk))
        else:
            # Restaure le highlight si on était déjà sur un frame
            if self._hi_start > 0:
                self.highlight_lines(self._hi_start, self._hi_end)

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
