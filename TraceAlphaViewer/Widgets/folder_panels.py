from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

import customtkinter as ctk
import tkinter as tk

from Models.folder_report import TraceReportEntry


T = TypeVar('T')


@dataclass
class GroupSection(Generic[T]):
    title: str
    items: list[T]


class TraceListPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_select: Callable[[TraceReportEntry], None] | None = None,
        **kwargs,
    ):
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self._entries: list[TraceReportEntry] = []
        self._line_to_entry: dict[int, TraceReportEntry] = {}
        self._selected_path: str = ''
        self._on_select = on_select
        self._build()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color='#1e1e30', height=28, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)
        ctk.CTkLabel(
            header,
            text='TRACES DU DOSSIER',
            font=('Consolas', 10, 'bold'),
            text_color='#88aacc',
        ).pack(side='left', padx=8)

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
            width=42,
        )
        self._text.pack(fill='both', expand=True)
        vscroll.config(command=self._text.yview)

        self._text.tag_configure('title', foreground='#ddeeff')
        self._text.tag_configure('meta', foreground='#667788')
        self._text.tag_configure('selected', background='#1a2d45')
        self._text.tag_configure('error', foreground='#ff8888')
        self._text.bind('<Button-1>', self._on_click)

    def set_entries(self, entries: list[TraceReportEntry]) -> None:
        self._entries = entries
        self._line_to_entry = {}
        self._text.configure(state='normal')
        self._text.delete('1.0', 'end')
        if not entries:
            self._text.insert('end', 'Aucune trace trouvee.\n', ('meta',))
        for entry in entries:
            line_title = int(self._text.index('end-1c').split('.')[0])
            self._line_to_entry[line_title] = entry
            tags = ('title',)
            if entry.parse_error:
                tags = ('error',)
            self._text.insert('end', f'{entry.name}\n', tags)
            meta = (
                f'  {entry.status_label} | {entry.frame_count} frames | '
                f'{entry.diagnostic_count} diag | {entry.error_count} err\n'
            )
            self._text.insert('end', meta, ('meta',))
        self._text.configure(state='disabled')
        if self._selected_path:
            self.highlight_entry(self._selected_path)

    def highlight_entry(self, filepath: str) -> None:
        self._selected_path = filepath
        self._text.tag_remove('selected', '1.0', 'end')
        for display_line, entry in self._line_to_entry.items():
            if entry.filepath == filepath:
                self._text.tag_add('selected', f'{display_line}.0', f'{display_line + 1}.0')
                self._text.see(f'{display_line}.0')
                break

    def _on_click(self, event) -> None:
        idx = self._text.index(f'@{event.x},{event.y}')
        display_line = int(idx.split('.')[0])
        selected = self._line_to_entry.get(display_line)
        if selected and self._on_select:
            self._on_select(selected)


class GroupedItemPanel(ctk.CTkFrame, Generic[T]):
    def __init__(
        self,
        master,
        title: str,
        item_label: Callable[[T], str],
        detail_label: Callable[[T], str],
        on_item_click: Callable[[T], None] | None = None,
        empty_text: str = 'Aucun element',
        **kwargs,
    ):
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self._item_label = item_label
        self._detail_label = detail_label
        self._on_item_click = on_item_click
        self._empty_text = empty_text
        self._line_to_item: dict[int, T] = {}
        self._build(title)

    def _build(self, title: str) -> None:
        header = ctk.CTkFrame(self, fg_color='#1e1e30', height=50, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)
        self._title = ctk.CTkLabel(
            header,
            text=title,
            font=('Consolas', 10, 'bold'),
            text_color='#88aacc',
        )
        self._title.pack(anchor='w', padx=8, pady=(5, 0))
        self._summary = ctk.CTkLabel(
            header,
            text='',
            font=('Consolas', 9),
            text_color='#778899',
        )
        self._summary.pack(anchor='w', padx=8, pady=(0, 4))

        body = tk.PanedWindow(
            self,
            orient='horizontal',
            sashwidth=6,
            bg='#263142',
            bd=0,
            showhandle=False,
        )
        body.pack(fill='both', expand=True)

        left = tk.Frame(body, bg='#12121f')
        right = tk.Frame(body, bg='#0f0f1c')
        body.add(left, minsize=360, stretch='always')
        body.add(right, minsize=320, stretch='never')

        vscroll = tk.Scrollbar(left, orient='vertical')
        vscroll.pack(side='right', fill='y')
        self._list = tk.Text(
            left,
            bg='#12121f',
            fg='#aabbcc',
            font=('Consolas', 9),
            wrap='none',
            cursor='arrow',
            state='disabled',
            yscrollcommand=vscroll.set,
            relief='flat',
            borderwidth=0,
        )
        self._list.pack(fill='both', expand=True)
        vscroll.config(command=self._list.yview)

        self._details = tk.Text(
            right,
            bg='#0f0f1c',
            fg='#aabbcc',
            font=('Consolas', 9),
            wrap='word',
            cursor='arrow',
            state='disabled',
            relief='flat',
            borderwidth=0,
        )
        self._details.pack(fill='both', expand=True, padx=8, pady=8)

        self._list.tag_configure('group', foreground='#88aacc', font=('Consolas', 10, 'bold'))
        self._list.tag_configure('meta', foreground='#667788')
        self._list.tag_configure('selected', background='#1a2d45')
        self._list.bind('<Button-1>', self._on_click)

    def set_groups(self, groups: list[GroupSection[T]], summary: str = '') -> None:
        self._line_to_item = {}
        self._summary.configure(text=summary)
        self._list.configure(state='normal')
        self._list.delete('1.0', 'end')
        if not groups:
            self._list.insert('end', f'{self._empty_text}\n', ('meta',))
            self._list.configure(state='disabled')
            self._show_details(None)
            return

        first_item: T | None = None
        for section in groups:
            self._list.insert('end', f'{section.title}\n', ('group',))
            if not section.items:
                self._list.insert('end', '  Aucun element\n', ('meta',))
                continue
            for item in section.items:
                display_line = int(self._list.index('end-1c').split('.')[0])
                self._line_to_item[display_line] = item
                self._list.insert('end', f'  {self._item_label(item)}\n')
                if first_item is None:
                    first_item = item
            self._list.insert('end', '\n', ('meta',))
        self._list.configure(state='disabled')
        self._show_details(first_item)

    def _show_details(self, item: T | None) -> None:
        self._details.configure(state='normal')
        self._details.delete('1.0', 'end')
        if item is None:
            self._details.insert('end', self._empty_text)
        else:
            self._details.insert('end', self._detail_label(item))
        self._details.configure(state='disabled')

    def _on_click(self, event) -> None:
        idx = self._list.index(f'@{event.x},{event.y}')
        display_line = int(idx.split('.')[0])
        selected = self._line_to_item.get(display_line)
        if selected is None:
            return
        self._list.tag_remove('selected', '1.0', 'end')
        self._list.tag_add('selected', f'{display_line}.0', f'{display_line}.end')
        self._show_details(selected)
        if self._on_item_click:
            self._on_item_click(selected)
