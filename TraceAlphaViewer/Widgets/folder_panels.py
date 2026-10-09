from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

import customtkinter as ctk
import tkinter as tk

from Models.folder_report import TraceReportEntry
from Widgets.text_renderer import TextRenderer


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
        self._renderer = TextRenderer(self, self._text,
            on_row=lambda line, item: self._line_to_entry.__setitem__(line, item),
            on_done=self._restore_highlight)

    def _restore_highlight(self):
        if self._selected_path:
            self.highlight_entry(self._selected_path)

    @property
    def loading(self):
        return self._renderer.loading

    def destroy(self):
        self._renderer.cancel()
        super().destroy()

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
        self._text.tag_configure('selected', background='#23496d', foreground='#ffffff')
        self._text.tag_configure('error', foreground='#ff8888')
        self._text.bind('<Button-1>', self._on_click)

    def set_entries(self, entries: list[TraceReportEntry]) -> None:
        self._entries = entries
        self._line_to_entry = {}
        def rows():
            if not entries:
                yield 'Aucune trace trouvee.\n', ('meta',), None
            for entry in entries:
                tags = ('error',) if entry.parse_error else ('title',)
                yield f'{entry.name}\n', tags, entry
                yield (f'  {entry.status_label} | {entry.frame_count} frames | '
                       f'{entry.diagnostic_count} diag | {entry.error_count} err\n'), ('meta',), None
        self._renderer.start(rows())

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
        item_tags: Callable[[T], tuple[str, ...]] | None = None,
        on_item_click: Callable[[T], None] | None = None,
        empty_text: str = 'Aucun element',
        **kwargs,
    ):
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self._item_label = item_label
        self._detail_label = detail_label
        self._item_tags = item_tags
        self._on_item_click = on_item_click
        self._empty_text = empty_text
        self._line_to_item: dict[int, T] = {}
        self._item_id_to_line: dict[int, int] = {}
        self._pending_selection = None
        self._build(title)
        self._renderer = TextRenderer(self, self._list, on_row=self._map_row,
                                      on_done=self._restore_selection)

    def _restore_selection(self):
        if self._pending_selection is not None:
            item, trigger = self._pending_selection
            self._pending_selection = None
            self.select_item(item, trigger_callback=trigger)

    def _map_row(self, line, item):
        self._line_to_item[line] = item
        self._item_id_to_line[id(item)] = line

    @property
    def loading(self):
        return self._renderer.loading

    def destroy(self):
        self._renderer.cancel()
        super().destroy()

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

        self._list.tag_configure('group', foreground='#9cc7ff', font=('Consolas', 10, 'bold'))
        self._list.tag_configure('meta', foreground='#7c8a99')
        self._list.tag_configure('selected', background='#23496d', foreground='#ffffff')
        self._list.tag_configure('error', foreground='#ff8f8f')
        self._list.tag_configure('warning', foreground='#ffc46b')
        self._list.tag_configure('info', foreground='#9ecbff')
        self._list.bind('<Button-1>', self._on_click)

    def set_groups(self, groups: list[GroupSection[T]], summary: str = '') -> None:
        self._pending_selection = None
        self._line_to_item = {}
        self._item_id_to_line = {}
        self._summary.configure(text=summary)
        first_item = next((section.items[0] for section in groups if section.items), None)
        def rows():
            if not groups:
                yield f'{self._empty_text}\n', ('meta',), None
            for section in groups:
                yield f'{section.title}\n', ('group',), None
                if not section.items:
                    yield '  Aucun element\n', ('meta',), None
                for item in section.items:
                    tags = self._item_tags(item) if self._item_tags else ()
                    yield f'  {self._item_label(item)}\n', tags, item
                yield '\n', ('meta',), None
        self._renderer.start(rows())
        self._show_details(first_item)

    def select_item(self, item: T | None, trigger_callback: bool = False) -> bool:
        if item is None:
            return False
        display_line = self._item_id_to_line.get(id(item))
        if display_line is None:
            for line, candidate in self._line_to_item.items():
                if candidate == item:
                    display_line = line
                    break
        if display_line is None:
            if self.loading:
                self._pending_selection = (item, trigger_callback)
            return False
        self._select_display_line(display_line, trigger_callback=trigger_callback)
        return True

    def select_first(self, predicate: Callable[[T], bool], trigger_callback: bool = False) -> T | None:
        for display_line, item in self._line_to_item.items():
            if predicate(item):
                self._select_display_line(display_line, trigger_callback=trigger_callback)
                return item
        return None

    def clear_selection(self) -> None:
        self._pending_selection = None
        self._list.tag_remove('selected', '1.0', 'end')

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
        self._select_display_line(display_line, trigger_callback=True)

    def _select_display_line(self, display_line: int, trigger_callback: bool = False) -> None:
        selected = self._line_to_item.get(display_line)
        if selected is None:
            return
        self._list.tag_remove('selected', '1.0', 'end')
        self._list.tag_add('selected', f'{display_line}.0', f'{display_line}.end')
        self._list.see(f'{display_line}.0')
        self._show_details(selected)
        if trigger_callback and self._on_item_click:
            self._on_item_click(selected)
