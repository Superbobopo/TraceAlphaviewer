"""
ReferencePanel - liste cliquable des boites/reference vues dans la trace.
"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
import tkinter as tk

from Models.reference_index import ReferenceRecord
from Widgets.text_renderer import TextRenderer


class ReferencePanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        records: list[ReferenceRecord],
        on_reference_click: Optional[Callable[[ReferenceRecord], None]] = None,
        **kwargs,
    ):
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self._records = records
        self._visible_records: list[ReferenceRecord] = []
        self._on_reference_click = on_reference_click
        self._line_to_record: dict[int, ReferenceRecord] = {}
        self._search_var = tk.StringVar()
        self._unknown_only = False
        self._build()
        self._highlight_line = None
        self._renderer = TextRenderer(self, self._text,
            on_row=lambda line, item: self._line_to_record.__setitem__(line, item),
            on_done=self._restore_highlight)
        self.set_records(records)

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color='#1e1e30', height=34, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)

        self._title = ctk.CTkLabel(
            header,
            text='REFERENCES',
            font=('Consolas', 10, 'bold'),
            text_color='#88aacc',
        )
        self._title.pack(side='left', padx=(8, 12))
        ctk.CTkLabel(header, text='CIP / filtre', font=('Consolas', 10),
                     text_color='#88aacc').pack(side='left', padx=(0, 6))

        search = ctk.CTkEntry(
            header,
            textvariable=self._search_var,
            placeholder_text='CIP, barcode, nom, IdA, idB...',
            height=24,
            fg_color='#151525',
            text_color='#ddeeff',
            border_color='#334455',
            font=('Consolas', 10),
        )
        search.pack(side='left', fill='x', expand=True, padx=(0, 8), pady=5)
        search.bind('<Return>', lambda e: self._open_first_result())
        self._search_var.trace_add('write', lambda *_: self._render())

        self._btn_unknown = ctk.CTkButton(
            header,
            text='Unknown',
            width=72,
            height=22,
            corner_radius=4,
            font=('Consolas', 9),
            fg_color='#252538',
            hover_color='#353555',
            text_color='#aabbcc',
            command=self._toggle_unknown_filter,
        )
        self._btn_unknown.pack(side='right', padx=(0, 6), pady=5)

        vscroll = tk.Scrollbar(self, orient='vertical')
        vscroll.pack(side='right', fill='y')

        self._text = tk.Text(
            self,
            bg='#12121f',
            fg='#aabbcc',
            font=('Consolas', 9),
            wrap='none',
            cursor='arrow',
            state='disabled',
            yscrollcommand=vscroll.set,
            relief='flat',
            borderwidth=0,
            width=70,
        )
        self._text.pack(fill='both', expand=True)
        vscroll.config(command=self._text.yview)

        self._text.tag_configure('header', foreground='#6688aa')
        self._text.tag_configure('normal', foreground='#aabbcc')
        self._text.tag_configure('taken', foreground='#88ddaa')
        self._text.tag_configure('unknown', foreground='#ffbb55')
        self._text.tag_configure('current', background='#1a2d45', foreground='#ddeeff')
        self._text.bind('<Button-1>', self._on_click)

    def set_records(self, records: list[ReferenceRecord]) -> None:
        self._records = records
        self._render()

    def _record_matches(self, record: ReferenceRecord, query: str) -> bool:
        if not query:
            return True
        text = ' '.join([
            record.barcode,
            record.source_ref,
            record.name,
            str(record.id_b or ''),
            str(record.id_alpha or ''),
            f'idB:{record.id_b}' if record.id_b else '',
            f'IdA:{record.id_alpha}' if record.id_alpha else '',
            record.stages_label(),
        ]).lower()
        return query in text

    def _open_first_result(self) -> str:
        if self._visible_records and self._on_reference_click:
            self._on_reference_click(self._visible_records[0])
        return 'break'

    def _filtered_records(self) -> list[ReferenceRecord]:
        query = self._search_var.get().strip().lower()
        records = [record for record in self._records if self._record_matches(record, query)]
        if self._unknown_only:
            records = [record for record in records if record.is_unknown()]
        return records

    def _toggle_unknown_filter(self) -> None:
        self._unknown_only = not self._unknown_only
        self._btn_unknown.configure(
            fg_color='#7a5520' if self._unknown_only else '#252538',
            hover_color='#8a6530' if self._unknown_only else '#353555',
            text_color='#ffe0aa' if self._unknown_only else '#aabbcc',
        )
        self._render()

    def _render(self) -> None:
        records = self._filtered_records()
        self._visible_records = records
        self._line_to_record = {}
        self._title.configure(text=f'REFERENCES ({len(records)}/{len(self._records)})')

        def rows():
            yield f'{"Heure":<8} {"Ligne":<9} {"Parcours":<13} {"Ids":<20} Reference / nom\n', ('header',), None
            if not records:
                yield 'Aucune reference trouvee.\n', ('normal',), None
            for record in records:
                ids = ' '.join(
                    part for part in (
                        f'idB:{record.id_b}' if record.id_b else '',
                        f'IdA:{record.id_alpha}' if record.id_alpha else '',
                    )
                    if part
                )
                text = (
                    f'{record.first_time_str:<8} '
                    f'L.{record.first_line:<7} '
                    f'{record.stages_label():<13} '
                    f'{ids:<20} '
                    f'{record.main_ref()} {record.name}\n'
                )
                if record.is_unknown():
                    tag = 'unknown'
                elif record.taken_by_robot:
                    tag = 'taken'
                else:
                    tag = 'normal'
                yield text, (tag,), record
        self._renderer.start(rows())

    @property
    def loading(self):
        return self._renderer.loading

    def _restore_highlight(self):
        if self._highlight_line is not None:
            self.highlight_for_line(self._highlight_line)

    def destroy(self):
        self._renderer.cancel()
        super().destroy()

    def highlight_for_line(self, file_line: int) -> None:
        self._highlight_line = file_line
        self._text.tag_remove('current', '1.0', 'end')
        best_line = None
        best_record = None
        for display_line, record in self._line_to_record.items():
            if record.first_line <= file_line and (
                best_record is None or record.first_line > best_record.first_line
            ):
                best_line = display_line
                best_record = record
        if best_line is None:
            return
        self._text.tag_add('current', f'{best_line}.0', f'{best_line}.end')
        self._text.see(f'{best_line}.0')

    def _on_click(self, event) -> None:
        if not self._on_reference_click:
            return
        idx = self._text.index(f'@{event.x},{event.y}')
        display_line = int(idx.split('.')[0])
        selected = self._line_to_record.get(display_line)
        if selected:
            self._on_reference_click(selected)
