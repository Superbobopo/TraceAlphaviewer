"""
EventPanel - liste cliquable des evenements importants extraits de la trace.
"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
import tkinter as tk

from Models.state import MachineEvent


_SEVERITY_TAGS = {
    'error': ('#ff7777', '#3a1820'),
    'warning': ('#ffbb55', '#2e2512'),
    'info': ('#aabbcc', '#12121f'),
}


class EventPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        events: list[MachineEvent],
        on_event_click: Optional[Callable[[MachineEvent], None]] = None,
        **kwargs,
    ):
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self._events = events
        self._on_event_click = on_event_click
        self._line_to_event: dict[int, MachineEvent] = {}
        self._build()
        self.set_events(events)

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color='#1e1e30', height=26, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)

        self._title = ctk.CTkLabel(
            header,
            text='EVENEMENTS',
            font=('Consolas', 10, 'bold'),
            text_color='#88aacc',
        )
        self._title.pack(side='left', padx=8)

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
            width=52,
        )
        self._text.pack(fill='both', expand=True)
        vscroll.config(command=self._text.yview)

        self._text.tag_configure('line', foreground='#445566')
        self._text.tag_configure('current', background='#1a2d45')
        for severity, (fg, bg) in _SEVERITY_TAGS.items():
            self._text.tag_configure(severity, foreground=fg)
            self._text.tag_configure(f'{severity}_current', foreground=fg, background=bg)

        self._text.bind('<Button-1>', self._on_click)

    def set_events(self, events: list[MachineEvent]) -> None:
        self._events = events
        self._line_to_event = {}
        self._title.configure(text=f'EVENEMENTS ({len(events)})')

        self._text.configure(state='normal')
        self._text.delete('1.0', 'end')

        if not events:
            self._text.insert('end', 'Aucun evenement detecte\n', ('line',))
        else:
            for idx, event in enumerate(events, 1):
                display_line = int(self._text.index('end-1c').split('.')[0])
                self._line_to_event[display_line] = event
                severity = event.severity if event.severity in _SEVERITY_TAGS else 'info'
                text = (
                    f'{event.timestamp_str:<8} '
                    f'{event.kind:<9} '
                    f'L.{event.line_num:<7} '
                    f'{event.title}\n'
                )
                self._text.insert('end', text, (severity,))

        self._text.configure(state='disabled')

    def highlight_for_line(self, file_line: int) -> None:
        self._text.tag_remove('current', '1.0', 'end')
        for severity in _SEVERITY_TAGS:
            self._text.tag_remove(f'{severity}_current', '1.0', 'end')

        best_line = None
        best_event = None
        for display_line, event in self._line_to_event.items():
            if event.line_num <= file_line and (
                best_event is None or event.line_num > best_event.line_num
            ):
                best_line = display_line
                best_event = event

        if best_line is None or best_event is None:
            return

        severity = best_event.severity if best_event.severity in _SEVERITY_TAGS else 'info'
        self._text.tag_add('current', f'{best_line}.0', f'{best_line}.end')
        self._text.tag_add(f'{severity}_current', f'{best_line}.0', f'{best_line}.end')
        self._text.see(f'{best_line}.0')

    def _on_click(self, event) -> None:
        if not self._on_event_click:
            return
        idx = self._text.index(f'@{event.x},{event.y}')
        display_line = int(idx.split('.')[0])
        selected = self._line_to_event.get(display_line)
        if selected:
            self._on_event_click(selected)
