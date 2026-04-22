"""
DiagnosticPanel - synthese cliquable des incidents detectes dans une trace.
"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
import tkinter as tk

from Models.diagnostic import DiagnosticIncident


_SEVERITY_STYLES = {
    'error': ('#ff7777', '#3a1820'),
    'warning': ('#ffbb55', '#2e2512'),
    'info': ('#aabbcc', '#12121f'),
}

_SEVERITY_LABELS = {
    'error': 'CRITIQUE',
    'warning': 'ALERTE',
    'info': 'INFO',
}


class DiagnosticPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        incidents: list[DiagnosticIncident],
        on_incident_click: Optional[Callable[[DiagnosticIncident], None]] = None,
        **kwargs,
    ):
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self._incidents = incidents
        self._on_incident_click = on_incident_click
        self._line_to_incident: dict[int, DiagnosticIncident] = {}
        self._build()
        self.set_incidents(incidents)

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color='#1e1e30', height=58, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)

        self._title = ctk.CTkLabel(
            header,
            text='DIAGNOSTIC GLOBAL DE LA TRACE',
            font=('Consolas', 10, 'bold'),
            text_color='#88aacc',
        )
        self._title.pack(anchor='w', padx=8, pady=(5, 0))

        self._summary = ctk.CTkLabel(
            header,
            text='Analyse de toute la trace chargee.',
            font=('Consolas', 9),
            text_color='#778899',
        )
        self._summary.pack(anchor='w', padx=8, pady=(0, 4))

        body = ctk.CTkFrame(self, fg_color='#12121f', corner_radius=0)
        body.pack(fill='both', expand=True)

        left = ctk.CTkFrame(body, fg_color='#12121f', corner_radius=0)
        left.pack(side='left', fill='both', expand=True)

        right = ctk.CTkFrame(body, fg_color='#0f0f1c', corner_radius=0, width=420)
        right.pack(side='right', fill='both', padx=(1, 0))
        right.pack_propagate(False)

        vscroll = tk.Scrollbar(left, orient='vertical')
        vscroll.pack(side='right', fill='y')

        self._list = tk.Text(
            left,
            bg='#12121f',
            fg='#aabbcc',
            font=('Consolas', 10),
            wrap='none',
            cursor='arrow',
            state='disabled',
            yscrollcommand=vscroll.set,
            relief='flat',
            borderwidth=0,
            height=10,
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

        self._list.tag_configure('current', background='#1a2d45')
        self._list.tag_configure('header', foreground='#778899')
        for severity, (fg, bg) in _SEVERITY_STYLES.items():
            self._list.tag_configure(severity, foreground=fg)
            self._list.tag_configure(f'{severity}_current', foreground=fg, background=bg)

        self._list.bind('<Button-1>', self._on_click)

    def set_incidents(self, incidents: list[DiagnosticIncident]) -> None:
        self._incidents = incidents
        self._line_to_incident = {}
        errors = sum(1 for incident in incidents if incident.severity == 'error')
        warnings = sum(1 for incident in incidents if incident.severity == 'warning')
        first_error = next((incident for incident in incidents if incident.severity == 'error'), None)
        if first_error:
            focus = f'Premier critique: L.{first_error.first_line} - {first_error.title}'
        elif incidents:
            focus = f'Premier incident: L.{incidents[0].first_line} - {incidents[0].title}'
        else:
            focus = 'Aucun incident detecte sur la trace complete.'
        self._summary.configure(
            text=f'Trace complete: {errors} critiques, {warnings} alertes, {len(incidents)} incidents. {focus}'
        )

        self._list.configure(state='normal')
        self._list.delete('1.0', 'end')

        if not incidents:
            self._list.insert('end', 'Aucun incident detecte sur l ensemble de la trace.\n', ('info',))
        else:
            self._list.insert(
                'end',
                'Heure    Niveau    Zone Ligne    Occ.  Incident\n',
                ('header',),
            )
            for incident in incidents:
                display_line = int(self._list.index('end-1c').split('.')[0])
                self._line_to_incident[display_line] = incident
                severity = incident.severity if incident.severity in _SEVERITY_STYLES else 'info'
                severity_label = _SEVERITY_LABELS.get(severity, severity.upper())
                zone = incident.belt or '-'
                text = (
                    f'{incident.start_time_str:<8} '
                    f'{severity_label:<9} '
                    f'{zone:<4} '
                    f'L.{incident.first_line:<7} '
                    f'{incident.count:>3}x  '
                    f'{incident.title} ({incident.duration_label()})\n'
                )
                self._list.insert('end', text, (severity,))

        self._list.configure(state='disabled')
        self._show_details(incidents[0] if incidents else None)

    def highlight_for_line(self, file_line: int) -> None:
        self._list.tag_remove('current', '1.0', 'end')
        for severity in _SEVERITY_STYLES:
            self._list.tag_remove(f'{severity}_current', '1.0', 'end')

        best_line = None
        best_incident = None
        for display_line, incident in self._line_to_incident.items():
            if incident.first_line <= file_line and (
                best_incident is None or incident.first_line > best_incident.first_line
            ):
                best_line = display_line
                best_incident = incident

        if best_line is None or best_incident is None:
            return

        severity = best_incident.severity if best_incident.severity in _SEVERITY_STYLES else 'info'
        self._list.tag_add('current', f'{best_line}.0', f'{best_line}.end')
        self._list.tag_add(f'{severity}_current', f'{best_line}.0', f'{best_line}.end')
        self._list.see(f'{best_line}.0')
        self._show_details(best_incident)

    def _show_details(self, incident: DiagnosticIncident | None) -> None:
        self._details.configure(state='normal')
        self._details.delete('1.0', 'end')
        if incident is None:
            self._details.insert(
                'end',
                'Diagnostic global de la trace\n\n'
                'Aucun incident detecte sur l ensemble de la trace chargee.'
            )
        else:
            causes = '\n'.join(f'- {cause}' for cause in incident.probable_causes)
            lines = ', '.join(f'L.{line}' for line in incident.event_lines[:12])
            if len(incident.event_lines) > 12:
                lines += ', ...'
            severity = _SEVERITY_LABELS.get(incident.severity, incident.severity.upper())
            text = (
                f'Diagnostic global de la trace\n\n'
                f'Incident : {incident.title}\n'
                f'Niveau   : {severity}\n'
                f'Zone     : {incident.belt or "-"}\n'
                f'Code     : {incident.code or "-"}\n'
                f'Lignes   : L.{incident.first_line} -> L.{incident.last_line}\n'
                f'Periode  : {incident.start_time_str} -> {incident.end_time_str} '
                f'({incident.duration_label()})\n'
                f'Occurrences : {incident.count}\n\n'
                f'Resume:\n{incident.summary}\n\n'
                f'Causes probables:\n{causes or "-"}\n\n'
                f'Lignes utiles a ouvrir:\n{lines or "-"}'
            )
            self._details.insert('end', text)
        self._details.configure(state='disabled')

    def _on_click(self, event) -> None:
        idx = self._list.index(f'@{event.x},{event.y}')
        display_line = int(idx.split('.')[0])
        selected = self._line_to_incident.get(display_line)
        if not selected:
            return
        self._show_details(selected)
        if self._on_incident_click:
            self._on_incident_click(selected)
