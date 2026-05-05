"""
EventPanel - liste cliquable des evenements importants extraits de la trace.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

import customtkinter as ctk
import tkinter as tk

from Models.state import MachineEvent


_SEVERITY_TAGS = {
    'error': ('#ff7777', '#3a1820'),
    'warning': ('#ffbb55', '#2e2512'),
    'info': ('#aabbcc', '#12121f'),
}
_BELT_FILTERS = ('Tous', 'T0', 'T1', 'T2', 'T3', 'T4', 'T5')
_BELT_RE = re.compile(r'\bT[0-5]\b', re.IGNORECASE)
_TOKEN_BELTS = {
    'C0': 'T1',
    'C1': 'T1',
    'C2': 'T2',
    'C3': 'T2',
    'C4': 'T2',
    'CB1': 'T2',
    'EA': 'T2',
    'C5': 'T3',
    'CB2': 'T3',
    'C6': 'T4',
    'LG': 'T4',
    'PT4': 'T4',
    'C9': 'T5',
    'LZB': 'T5',
    'PT5': 'T5',
    'IDA': 'T5',
    'BUTEE': 'T5',
    'POUBELLE': 'T5',
}


def _event_belts(event: MachineEvent) -> set[str]:
    text = f'{event.kind} {event.title} {event.detail}'.upper()
    motor_error = re.match(r'(T[0-5])\s+EN ERREUR', event.title.upper())
    if event.kind.upper() == 'ERREUR' and motor_error:
        return {motor_error.group(1)}
    belts = {match.group(0).upper() for match in _BELT_RE.finditer(text)}
    for token, belt in _TOKEN_BELTS.items():
        if token in text:
            belts.add(belt)
    if event.kind.upper() == 'BOITE' and (
        'ROBOT SUPPRIME' in text or 'SUPPRESSION BOITE IDA' in text
    ):
        belts.add('T5')
    return belts


class EventPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        events: list[MachineEvent],
        on_event_click: Optional[Callable[[MachineEvent], None]] = None,
        title: str = 'EVENEMENTS',
        empty_text: str = 'Aucun evenement detecte',
        show_belt_filters: bool = False,
        **kwargs,
    ):
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self._events = events
        self._visible_events: list[MachineEvent] = []
        self._on_event_click = on_event_click
        self._panel_title = title
        self._empty_text = empty_text
        self._show_belt_filters = show_belt_filters
        self._active_belt_filter = 'Tous'
        self._filter_buttons: dict[str, ctk.CTkButton] = {}
        self._line_to_event: dict[int, MachineEvent] = {}
        self._build()
        self.set_events(events)

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color='#1e1e30', height=26, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)

        self._title = ctk.CTkLabel(
            header,
            text=self._panel_title,
            font=('Consolas', 10, 'bold'),
            text_color='#88aacc',
        )
        self._title.pack(side='left', padx=8)
        if self._show_belt_filters:
            filters = ctk.CTkFrame(header, fg_color='transparent')
            filters.pack(side='right', padx=6)
            for belt in _BELT_FILTERS:
                btn = ctk.CTkButton(
                    filters,
                    text=belt,
                    width=42 if belt == 'Tous' else 30,
                    height=20,
                    corner_radius=4,
                    font=('Consolas', 9),
                    command=lambda b=belt: self._set_belt_filter(b),
                )
                btn.pack(side='left', padx=1)
                self._filter_buttons[belt] = btn
            self._refresh_filter_buttons()

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
        self._render_events()

    def _set_belt_filter(self, belt: str) -> None:
        self._active_belt_filter = belt if belt in _BELT_FILTERS else 'Tous'
        self._refresh_filter_buttons()
        self._render_events()

    def _refresh_filter_buttons(self) -> None:
        for belt, button in self._filter_buttons.items():
            if belt == self._active_belt_filter:
                button.configure(fg_color='#2a4a7f', hover_color='#345a96', text_color='#ddeeff')
            else:
                button.configure(fg_color='#252538', hover_color='#353555', text_color='#aabbcc')

    def _filtered_events(self) -> list[MachineEvent]:
        if self._active_belt_filter == 'Tous':
            return self._events
        return [
            event for event in self._events
            if self._active_belt_filter in _event_belts(event)
        ]

    def _render_events(self) -> None:
        events = self._filtered_events()
        self._visible_events = events
        self._line_to_event = {}
        if self._active_belt_filter == 'Tous':
            self._title.configure(text=f'{self._panel_title} ({len(events)})')
        else:
            self._title.configure(text=f'{self._panel_title} - {self._active_belt_filter} ({len(events)})')

        self._text.configure(state='normal')
        self._text.delete('1.0', 'end')

        if not events:
            self._text.insert('end', f'{self._empty_text}\n', ('line',))
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
