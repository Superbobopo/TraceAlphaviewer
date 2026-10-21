"""
DiagnosticPanel - synthese cliquable des incidents detectes dans une trace.
"""
from __future__ import annotations

import json
import os
import re
import webbrowser
import time
from queue import Empty
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

from Models.diagnostic import DiagnosticIncident
from Models.robot_drain import t5_priority_score
from Models.diagnostic_report import write_diagnostic_report, report_files_available
from Models.diagnostic_report import _metric_from_summary as _structured_metric
from Models.state import MachineState
from Models.frame_store import FrameStore
from Models.loading_client import LoadingSession
from Models.measurement_analysis import analyze_measurements, summary_text, reference_page, AXES
from Widgets.text_renderer import TextRenderer


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

_SEVERITY_ORDER = {'error': 0, 'warning': 1, 'info': 2}

_DETAILS_DEFAULT_WIDTH = 0
_DETAILS_FULLSCREEN_DEFAULT_WIDTH = 0
_DETAILS_MIN_WIDTH = 240
_INCIDENTS_MIN_WIDTH = 280
_SPLIT_PREF_KEY = 'diagnostic_split_left_width'
_SPLIT_NORMAL_PREF_KEY = 'diagnostic_split_left_width_normal'
_SPLIT_FULLSCREEN_PREF_KEY = 'diagnostic_split_left_width_fullscreen'


def _prefs_path() -> Path:
    base_dir = Path(os.environ.get('LOCALAPPDATA', Path.home()))
    return base_dir / 'TraceAlphaViewer' / 'ui_prefs.json'


def _load_split_widths() -> dict[str, int]:
    try:
        data = json.loads(_prefs_path().read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        data = {}

    legacy_width = data.get(_SPLIT_PREF_KEY)
    try:
        normal_width = int(data.get(_SPLIT_NORMAL_PREF_KEY, legacy_width or _DETAILS_DEFAULT_WIDTH))
    except (ValueError, TypeError):
        normal_width = _DETAILS_DEFAULT_WIDTH
    try:
        fullscreen_width = int(data.get(_SPLIT_FULLSCREEN_PREF_KEY, _DETAILS_FULLSCREEN_DEFAULT_WIDTH))
    except (ValueError, TypeError):
        fullscreen_width = _DETAILS_FULLSCREEN_DEFAULT_WIDTH

    return {
        'normal': max(0, normal_width),
        'fullscreen': max(0, fullscreen_width),
    }


def _save_split_widths(widths: dict[str, int]) -> None:
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            data = {}
    data.pop(_SPLIT_PREF_KEY, None)
    data[_SPLIT_NORMAL_PREF_KEY] = max(_DETAILS_MIN_WIDTH, int(widths.get('normal', _DETAILS_DEFAULT_WIDTH)))
    data[_SPLIT_FULLSCREEN_PREF_KEY] = max(
        _DETAILS_MIN_WIDTH,
        int(widths.get('fullscreen', _DETAILS_FULLSCREEN_DEFAULT_WIDTH)),
    )
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def _duration_label(start: float, end: float) -> str:
    duration = max(0, int(end - start))
    minutes, seconds = divmod(duration, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _shorten(text: str, max_len: int = 170) -> str:
    text = ' '.join((text or '-').split())
    if len(text) <= max_len:
        return text
    return text[:max_len - 3].rstrip() + '...'


def _metric_from_summary(summary: str, code: str, occurrence_count: int, metrics=None) -> str:
    if metrics:
        return _structured_metric(summary, code, occurrence_count, metrics)
    if code == 'ALPHA_CARD_RESET':
        match = re.search(
            r'(\d+) reset(?:\(s\))? carte Alpha .*? sur ([^.]+?) de trace',
            summary,
        )
        if match:
            return f'{match.group(1)} reset(s) sur {match.group(2)} de trace'
        return f'{occurrence_count} reset(s) carte Alpha'
    if code == 'UNKNOWN':
        match = re.search(
            r'(\d+) boite\(s\) unknown confirmee\(s\) CB1\+CB2 sur (\d+) boite\(s\) passees \(([^)]+)\)',
            summary,
        )
        if match:
            return f'{match.group(1)} unknown confirmees / {match.group(2)} boites ({match.group(3)})'
    if code == 'CAM-NO-READ':
        match = re.search(r'Camera\(s\) sans reussite observee .*?: (.+?)\.', summary)
        if match:
            return f'cameras sans lecture: {match.group(1)}'
    return f'{occurrence_count} occurrence(s)'


def _business_lines(summary: str, code: str) -> list[str]:
    if code == 'UNKNOWN':
        lines: list[str] = []
        attribution = re.search(
            r'Attribution unknown finales: ([^.]+)\.',
            summary,
        )
        if attribution:
            lines.append(attribution.group(1))
        cameras = re.search(
            r'(CB1 cameras reussies: [^.]+; CB2 cameras reussies: [^.]+)\.',
            summary,
        )
        if cameras:
            lines.append(cameras.group(1))
        return lines
    if code == 'CAM-NO-READ':
        match = re.search(r'Camera\(s\) sans reussite observee .*?: (.+?)\.', summary)
        return [f'Camera(s) a verifier: {match.group(1)}'] if match else [_shorten(summary)]
    return [_shorten(summary)]


class DiagnosticPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        incidents: list[DiagnosticIncident],
        frames: list[MachineState] | None = None,
        on_incident_click: Optional[Callable[[DiagnosticIncident], None]] = None,
        load_session=None,
        on_report_open=None,
        on_measurement_click=None,
        source_name='',
        on_measurement_sample=None,
        **kwargs,
    ):
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self._incidents = incidents
        self._frames = frames
        self._measurement_analysis = None if isinstance(frames, FrameStore) else analyze_measurements(frames or [])
        self._measurement_summary = (frames.measurement_summary if isinstance(frames, FrameStore)
                                     else self._measurement_analysis['summary'])
        self._on_measurement_click = on_measurement_click
        self._on_measurement_sample = on_measurement_sample
        self._measurement_task = None
        self._measurement_job = None
        self._measurement_request = None
        self._measurement_bindings = {}
        self._on_report_open = on_report_open
        self._source_name = source_name
        self._on_incident_click = on_incident_click
        self._line_to_incident: dict[int, DiagnosticIncident] = {}
        self._split_widths = _load_split_widths()
        self._split_ready = False
        self._split_job = None
        self._mode_job = None
        self._window_mode = 'normal'
        self._showing_global = True
        self._load_session = load_session
        self._own_session = None
        self._report_task = None
        self._report_job = None
        self._report_path = None
        self._highlight_line = None
        self._build()
        self._renderer = TextRenderer(self, self._list,
            on_row=lambda line, item: self._line_to_incident.__setitem__(line, item),
            on_done=self._restore_highlight)
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
        self._title.bind('<Button-1>', lambda _event: self._show_global_summary())
        self._summary.bind('<Button-1>', lambda _event: self._show_global_summary())

        body = ctk.CTkFrame(self, fg_color='#12121f', corner_radius=0)
        body.pack(fill='both', expand=True)

        self._paned = tk.PanedWindow(
            body,
            orient='horizontal',
            sashrelief='raised',
            sashwidth=8,
            bd=0,
            opaqueresize=True,
            bg='#263142',
            showhandle=False,
        )
        self._paned.pack(fill='both', expand=True)

        left = tk.Frame(self._paned, bg='#0f0f1c', width=self._current_split_width())
        right = tk.Frame(self._paned, bg='#12121f', width=_INCIDENTS_MIN_WIDTH + 60)
        left.pack_propagate(False)
        right.pack_propagate(False)
        self._paned.add(left, minsize=_DETAILS_MIN_WIDTH, stretch='always')
        self._paned.add(right, minsize=_INCIDENTS_MIN_WIDTH, stretch='never')
        self._split_panes = (left, right)
        self._paned.bind('<Configure>', self._on_paned_configure)
        self._paned.bind('<ButtonRelease-1>', self._on_split_release)
        self._host = self.winfo_toplevel()
        self._host_binding = self._host.bind('<Configure>', self._on_host_configure, add='+')

        detail_bar = tk.Frame(left, bg='#0f0f1c', height=34)
        detail_bar.pack(fill='x')
        detail_bar.pack_propagate(False)
        self._global_btn = tk.Button(
            detail_bar,
            text='Vue globale',
            command=self._show_global_summary,
            bg='#1e1e30',
            fg='#aabbcc',
            activebackground='#263142',
            activeforeground='#ffffff',
            relief='flat',
            borderwidth=0,
            font=('Consolas', 9, 'bold'),
            padx=10,
            pady=3,
            cursor='hand2',
        )
        self._global_btn.pack(side='left', padx=8, pady=6)
        self._report_btn = tk.Button(
            detail_bar,
            text='Rapport web',
            command=self._open_web_report,
            bg='#1e1e30',
            fg='#aabbcc',
            activebackground='#263142',
            activeforeground='#ffffff',
            relief='flat',
            borderwidth=0,
            font=('Consolas', 9, 'bold'),
            padx=10,
            pady=3,
            cursor='hand2',
        )
        self._report_btn.pack(side='left', padx=(0, 8), pady=6)

        detail_body = tk.Frame(left, bg='#0f0f1c')
        detail_body.pack(fill='both', expand=True)
        detail_scroll = ctk.CTkScrollbar(detail_body, orientation='vertical', width=12,
            fg_color='#0f0f1c', button_color='#3c4358', button_hover_color='#65728d', corner_radius=6)
        self._detail_scroll = detail_scroll
        detail_scroll.pack(side='right', fill='y')
        self._details = tk.Text(
            detail_body,
            bg='#0f0f1c',
            fg='#aabbcc',
            font=('Consolas', 9),
            wrap='word',
            yscrollcommand=detail_scroll.set,
            cursor='arrow',
            state='disabled',
            relief='flat',
            borderwidth=0,
        )
        self._details.pack(fill='both', expand=True, padx=8, pady=8)
        detail_scroll.configure(command=self._details.yview)

        vscroll = ctk.CTkScrollbar(right, orientation='vertical', width=12,
            fg_color='#12121f', button_color='#3c4358', button_hover_color='#65728d', corner_radius=6)
        self._list_scroll = vscroll
        vscroll.pack(side='right', fill='y')

        self._list = tk.Text(
            right,
            bg='#12121f',
            fg='#aabbcc',
            font=('Consolas', 10),
            wrap='none',
            padx=8,
            spacing3=5,
            cursor='arrow',
            state='disabled',
            yscrollcommand=vscroll.set,
            relief='flat',
            borderwidth=0,
            height=10,
        )
        self._list.pack(fill='both', expand=True)
        vscroll.configure(command=self._list.yview)

        self._list.tag_configure('current', background='#1a2d45')
        self._list.tag_configure('header', foreground='#778899')
        for severity, (fg, bg) in _SEVERITY_STYLES.items():
            self._list.tag_configure(severity, foreground=fg)
            self._list.tag_configure(f'{severity}_current', foreground=fg, background=bg)

        self._list.bind('<Button-1>', self._on_click)
        self._list.bind('<Map>', lambda _event: self._list.configure(wrap='word'))

    def _on_paned_configure(self, _event) -> None:
        if not self._split_ready:
            if self._split_job is None:
                self._split_job = self.after_idle(self._apply_split_width)
            return
        self._clamp_split_width()

    def _host_mode(self) -> str:
        try:
            state = str(self.winfo_toplevel().state()).lower()
        except tk.TclError:
            return 'normal'
        return 'fullscreen' if state in ('zoomed', 'fullscreen') else 'normal'

    def _current_split_width(self) -> int:
        stored = self._split_widths.get(self._window_mode, 0)
        total = self._paned.winfo_width() if hasattr(self, '_paned') else 800
        return stored or int(max(total, 1) * .4)

    def _split_limits(self):
        total = max(1, self._paned.winfo_width() - 8)
        left = min(_DETAILS_MIN_WIDTH, int(total * .4))
        right = min(_INCIDENTS_MIN_WIDTH, int(total * .5))
        for pane, width in zip(self._split_panes, (left, right)):
            self._paned.paneconfigure(pane, minsize=width)
        return left, max(left, total - right)

    def _remember_current_width(self, width: int) -> None:
        self._split_widths[self._window_mode] = max(_DETAILS_MIN_WIDTH, int(width))

    def _set_sash_pos(self, index: int, x: int) -> None:
        if hasattr(self._paned, 'sashpos'):
            self._paned.sashpos(index, x)
        else:
            self._paned.sash_place(index, x, 0)

    def _get_sash_pos(self, index: int) -> int:
        if hasattr(self._paned, 'sashpos'):
            return int(self._paned.sashpos(index))
        return int(self._paned.sash_coord(index)[0])

    def _apply_mode_width(self) -> None:
        self._mode_job = None
        if not self._split_ready:
            return
        try:
            total_width = self._paned.winfo_width()
            if total_width <= 1:
                return
            min_left, max_left = self._split_limits()
            target = min(max(self._current_split_width(), min_left), max_left)
            self._set_sash_pos(0, target)
            self._remember_current_width(target)
        except (tk.TclError, AttributeError):
            return

    def _on_host_configure(self, _event) -> None:
        mode = self._host_mode()
        if mode == self._window_mode:
            return
        self._window_mode = mode
        if self._mode_job is not None:
            self.after_cancel(self._mode_job)
        self._mode_job = self.after_idle(self._apply_mode_width)

    def _apply_split_width(self) -> None:
        self._split_job = None
        try:
            self._window_mode = self._host_mode()
            total_width = self._paned.winfo_width()
            if total_width <= 1:
                self._split_job = self.after(30, self._apply_split_width)
                return
            min_left, max_left = self._split_limits()
            target = min(max(self._current_split_width(), min_left), max_left)
            self._set_sash_pos(0, target)
            self._remember_current_width(target)
            self._split_ready = True
        except (tk.TclError, AttributeError):
            return

    def _clamp_split_width(self) -> None:
        if not self._split_ready:
            return
        try:
            total_width = self._paned.winfo_width()
            if total_width <= 1:
                return
            min_left, max_left = self._split_limits()
            current = self._get_sash_pos(0)
            target = min(max(current, min_left), max_left)
            if target != current:
                self._set_sash_pos(0, target)
            self._remember_current_width(target)
        except (tk.TclError, AttributeError):
            return

    def _on_split_release(self, _event) -> None:
        if not self._split_ready:
            return
        self._clamp_split_width()
        try:
            self._remember_current_width(self._get_sash_pos(0))
            _save_split_widths(self._split_widths)
        except (tk.TclError, AttributeError):
            return

    def set_incidents(self, incidents: list[DiagnosticIncident]) -> None:
        self._incidents = incidents
        self._line_to_incident = {}
        errors = sum(1 for incident in incidents if incident.severity == 'error')
        warnings = sum(1 for incident in incidents if incident.severity == 'warning')
        self._summary.configure(
            text=f'Trace complete: {errors} critiques, {warnings} alertes, {len(incidents)} incidents.'
        )

        def rows():
            if not incidents:
                yield 'Aucun incident detecte sur l ensemble de la trace.\n', ('info',), None
            else:
                yield 'Heure | Niveau | Zone | Ligne | Occurrences\n', ('header',), None
            for incident in incidents:
                severity = incident.severity if incident.severity in _SEVERITY_STYLES else 'info'
                severity_label = _SEVERITY_LABELS.get(severity, severity.upper())
                zone = incident.belt or '-'
                yield (f'{incident.start_time_str} | {severity_label} | {zone} | '
                       f'L.{incident.first_line} | {incident.count}x\n'), (severity,), incident
                yield f'{incident.title} ({incident.duration_label()})\n', (severity,), incident
        self._renderer.start(rows())
        self._show_global_summary()

    @property
    def loading(self):
        return self._renderer.loading

    def _restore_highlight(self):
        if self._highlight_line is not None:
            self.highlight_for_line(self._highlight_line)

    def highlight_for_line(self, file_line: int) -> None:
        self._highlight_line = file_line
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
        self._list.tag_add('current', f'{best_line}.0', f'{best_line + 1}.end')
        self._list.tag_add(f'{severity}_current', f'{best_line}.0', f'{best_line + 1}.end')
        self._list.see(f'{best_line}.0')
        if not self._showing_global:
            self._show_details(best_incident)

    def _clear_current_selection(self) -> None:
        self._list.tag_remove('current', '1.0', 'end')
        for severity in _SEVERITY_STYLES:
            self._list.tag_remove(f'{severity}_current', '1.0', 'end')

    def _show_global_summary(self) -> None:
        self._cancel_measurement_task()
        self._showing_global = True
        self._clear_current_selection()
        self._details.configure(state='normal')
        self._details.delete('1.0', 'end')
        if not self._incidents:
            self._details.insert(
                'end',
                'Diagnostic global de la trace\n\n'
                'Aucun incident detecte sur l ensemble de la trace chargee.'
            )
            self._details.insert('end', '\n\nBILAN DES MESURES\n')
            self._insert_measurement_summary(self._measurement_summary)
            self._details.configure(state='disabled')
            return

        errors = sum(1 for incident in self._incidents if incident.severity == 'error')
        warnings = sum(1 for incident in self._incidents if incident.severity == 'warning')
        infos = sum(1 for incident in self._incidents if incident.severity == 'info')
        groups: dict[tuple[str, str, str, str], dict[str, object]] = {}
        for incident in self._incidents:
            key = (incident.severity, incident.belt, incident.code, incident.title)
            group = groups.get(key)
            if group is None:
                groups[key] = {
                    'severity': incident.severity,
                    'belt': incident.belt,
                    'code': incident.code,
                    'title': incident.title,
                    'first_line': incident.first_line,
                    'last_line': incident.last_line,
                    'start_time': incident.start_time,
                    'end_time': incident.end_time,
                    'start_time_str': incident.start_time_str,
                    'end_time_str': incident.end_time_str,
                    'incident_count': 1,
                    'occurrence_count': incident.count,
                    'summary': incident.summary,
                    'metrics': incident.metrics,
                }
                continue
            group['incident_count'] = int(group['incident_count']) + 1
            group['occurrence_count'] = int(group['occurrence_count']) + incident.count
            if incident.first_line < int(group['first_line']):
                group['first_line'] = incident.first_line
                group['start_time'] = incident.start_time
                group['start_time_str'] = incident.start_time_str
            if incident.last_line > int(group['last_line']):
                group['last_line'] = incident.last_line
                group['end_time'] = incident.end_time
                group['end_time_str'] = incident.end_time_str

        grouped = sorted(
            groups.values(),
            key=lambda group: (
                _SEVERITY_ORDER.get(str(group['severity']), 9),
                int(group['first_line']),
                str(group['title']),
            ),
        )

        self._details.insert(
            'end',
            'DIAGNOSTIC GLOBAL\n\n'
            f'Critiques : {errors} | Alertes : {warnings} | Infos : {infos} | '
            f'Types : {len(grouped)}\n\n'
        )
        for incident in self._incidents:
            if incident.code == 'DemVidageComplet':
                self._details.insert('end',
                    f'VIDAGE COMPLET T5 DEMANDE PAR LE ROBOT — {_SEVERITY_LABELS[incident.severity]}\n'
                    f'{incident.summary}\n')
                self._measurement_link('Voir les demandes et les controles',
                                       lambda item=incident: self._show_details(item), 'robot-drain-details')
                self._details.insert('end', '\n\n')
        self._details.insert('end', 'A TRAITER EN PRIORITE\n')

        priority_groups = sorted(
            grouped,
            key=lambda group: (
                _SEVERITY_ORDER.get(str(group['severity']), 9),
                -(t5_priority_score(str(group['code']), str(group['severity']),
                                    int(group['occurrence_count']), group.get('metrics'))
                  if group['code'] in {'DemVidageComplet', 'T5_STALE_UNMEASURED_BOX'}
                  else {'error': 500, 'warning': 190, 'info': 80}.get(str(group['severity']), 0)
                  + int(group['occurrence_count'])),
                int(group['first_line']),
            ),
        )[:5]
        priority_keys = {
            (str(group['severity']), str(group['belt']), str(group['code']), str(group['title']))
            for group in priority_groups
        }
        for group in grouped:
            key = (str(group['severity']), str(group['belt']), str(group['code']), str(group['title']))
            if str(group['code']) in {'UNKNOWN', 'CAM-NO-READ', 'REFERENCE_ABSENT'} and key not in priority_keys:
                priority_groups.append(group)
                priority_keys.add(key)
        for idx, group in enumerate(priority_groups, 1):
            severity_key = str(group['severity'])
            severity = _SEVERITY_LABELS.get(severity_key, severity_key.upper())
            zone = str(group['belt'] or '-')
            code = str(group['code'] or '-')
            occurrence_count = int(group['occurrence_count'])
            metric = _metric_from_summary(str(group['summary']), code, occurrence_count, group['metrics'])
            self._details.insert(
                'end',
                f'{idx}. [{severity}] {zone} {code} - {metric}\n'
                f'   {group["title"]}\n'
                f'   L.{group["first_line"]} -> L.{group["last_line"]} | '
                f'{group["start_time_str"]} -> {group["end_time_str"]}\n'
            )
            for line in _business_lines(str(group['summary']), code)[:2]:
                self._details.insert('end', f'   {line}\n')
            self._details.insert('end', '\n')

        self._details.insert('end', 'TOUS LES TYPES DE PROBLEMES\n')
        self._details.insert('end', '------------------------------------------------------------\n')

        for idx, group in enumerate(grouped, 1):
            severity_key = str(group['severity'])
            severity = _SEVERITY_LABELS.get(severity_key, severity_key.upper())
            zone = str(group['belt'] or '-')
            code = str(group['code'] or '-')
            duration = _duration_label(float(group['start_time']), float(group['end_time']))
            incident_count = int(group['incident_count'])
            occurrence_count = int(group['occurrence_count'])
            metric = _metric_from_summary(str(group['summary']), code, occurrence_count, group['metrics'])
            count_label = f'{incident_count} type(s)' if incident_count == 1 else f'{incident_count} sequences'
            self._details.insert(
                'end',
                f'{idx}. [{severity}] {zone} | {code} | {count_label} | {metric}\n'
                f'   {group["title"]}\n'
                f'   Lignes : L.{group["first_line"]} -> L.{group["last_line"]} | '
                f'Periode : {group["start_time_str"]} -> {group["end_time_str"]} ({duration})\n'
            )
            for line in _business_lines(str(group['summary']), code)[:2]:
                self._details.insert('end', f'   {line}\n')
            self._details.insert('end', '------------------------------------------------------------\n')
        self._details.insert('end', '\nBILAN DES MESURES\n')
        self._insert_measurement_summary(self._measurement_summary)
        self._details.configure(state='disabled')

    def _show_details(self, incident: DiagnosticIncident | None) -> None:
        self._cancel_measurement_task()
        self._showing_global = False
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
            checks = '\n'.join(f'- {check}' for check in incident.checks)
            lines = ', '.join(f'L.{line}' for line in incident.event_lines[:12])
            if len(incident.event_lines) > 12:
                lines += ', ...'
            severity = _SEVERITY_LABELS.get(incident.severity, incident.severity.upper())
            confidence = incident.confidence or '-'
            text = (
                f'Diagnostic global de la trace\n\n'
                f'Incident : {incident.title}\n'
                f'Niveau   : {severity}\n'
                f'Zone     : {incident.belt or "-"}\n'
                f'Code     : {incident.code or "-"}\n'
                f'Confiance: {confidence}\n'
                f'Lignes   : L.{incident.first_line} -> L.{incident.last_line}\n'
                f'Periode  : {incident.start_time_str} -> {incident.end_time_str} '
                f'({incident.duration_label()})\n'
                f'Occurrences : {incident.count}\n\n'
                f'Symptome detecte:\n{incident.symptom or "-"}\n\n'
                f'Resume:\n{incident.summary}\n\n'
                f'Causes probables:\n{causes or "-"}\n\n'
                f'Verifications conseillees:\n{checks or "-"}\n\n'
                f'Lignes utiles a ouvrir:\n{lines or "-"}'
            )
            self._details.insert('end', text)
            if incident.code == 'DemVidageComplet':
                for name, label in (('hour', '1 h'), ('day', '24 h')):
                    period = incident.metrics.get(name)
                    if period:
                        self._details.insert('end', f"\nPic sur {label} : {period['count']} — "
                                             f"{period['start']} -> {period['end']}")
                self._details.insert('end', f'\n\n{min(10, incident.count)} premieres demandes sur {incident.count} :\n')
                for line in incident.event_lines[:10]:
                    if self._on_measurement_click:
                        self._measurement_link(f'L.{line}\n',
                            lambda target=line: self._on_measurement_click(target), f'robot-drain-line-{line}')
                    else:
                        self._details.insert('end', f'L.{line}\n')
            if incident.measurement_stats:
                names = {'T4_LENGTH': ('length',), 'T5_WIDTH': ('width',), 'T5_HEIGHT': ('height',)}.get(incident.code)
                self._details.insert('end', '\n\nBILAN DES MESURES DE LA TRACE\n')
                self._insert_measurement_summary(incident.measurement_stats, names)
            for sample in incident.examples:
                self._details.insert('end', f"\n\nExemple L.{sample['line']} - {sample['time_str']} - {sample['box']} {sample['barcode']}\n")
                if 'measured' in sample:
                    self._details.insert('end', f"Largeur / hauteur / longueur : {sample['measured']} mm ; BdD {sample['expected']} mm ; ecarts {sample['deltas']} mm.")
                else:
                    self._details.insert('end', sample['detail'])
                    tag = f"reference-example-{sample['line']}"
                    self._details.insert('end', '\nVoir dans la trace', (tag,))
                    self._details.tag_configure(tag, foreground='#75bfff', underline=True)
                    self._details.tag_bind(tag, '<Button-1>',
                        lambda event, line=sample['line'], item=incident: self._open_reference_example(item, line))
        self._details.configure(state='disabled')

    def _open_reference_example(self, incident, line):
        from dataclasses import replace
        if self._on_incident_click:
            self._on_incident_click(replace(incident, first_line=line))

    def _insert_measurement_summary(self, summary, names=None):
        cursor = self._details.index('end-1c')
        self._details.insert('end', summary_text(summary, names))
        for axis, values in summary.get('axes', {}).items():
            if names is not None and axis not in names:
                continue
            start = self._details.search(values['label'], cursor, stopindex='end')
            if not start:
                continue
            for side, label, key in (('under', 'Trop petites', 'under_count'), ('over', 'trop grandes', 'over_count')):
                text = f"{label} : {values['all'][key]}"
                index = self._details.search(text, start, stopindex='end')
                tag = f'measurement-{axis}-{side}'
                self._details.tag_configure(tag, foreground='#75bfff', underline=True)
                self._details.tag_add(tag, index, f'{index}+{len(text)}c')
                self._bind_measurement_tag(tag, lambda a=axis, s=side: self._open_measurement_references(a, s))
            cursor = start
        for axis, values in summary.get('axes', {}).items():
            if names is not None and axis not in names:
                continue
            for side, item in values.get('recurrence', {}).items():
                cluster = item.get('cluster')
                if cluster:
                    self._measurement_link(f"\nProduits autour de {cluster['center']:+.1f} mm — {values['label']}\n",
                        lambda a=axis, s=side: self._open_measurement_references(a, s + '_group'),
                        f'measurement-group-{axis}-{side}')
            if values.get('frequencies'):
                self._measurement_link(f"\nRepartition de toutes les mesures — {values['label']}\n",
                    lambda a=axis, s=summary: self._show_measurement_distribution(s, a),
                    f'measurement-distribution-{axis}')

    def _show_measurement_distribution(self, summary, axis):
        self._cancel_measurement_task()
        self._showing_global = True
        values = summary['axes'][axis]
        self._details.configure(state='normal')
        self._details.delete('1.0', 'end')
        self._details.insert('end', f"BILAN DES MESURES DE LA TRACE\n{values['label']}\n\n"
            "Repartition de toutes les mesures comparables, conformes incluses.\n"
            "Une boite compte une fois ; ecart = mesure moins BdD.\n\n")
        for row in values.get('frequencies', []):
            self._details.insert('end', f"{row['delta']:+.1f} mm : {row['count']} boite(s) "
                f"({row['percent']:.1f} % des comparables), {row['references']} reference(s).\n")
        self._measurement_link('\nRetour au bilan', self._show_global_summary, 'measurement-back')
        self._details.configure(state='disabled')
        self._details.yview_moveto(0)

    def _cancel_measurement_task(self):
        if self._measurement_job is not None:
            self.after_cancel(self._measurement_job)
            self._measurement_job = None
        if self._measurement_task is not None:
            self._measurement_task.cancel()
            self._measurement_task = None

    def _bind_measurement_tag(self, tag, callback):
        previous = self._measurement_bindings.get(tag)
        if previous:
            self._details.tag_unbind(tag, '<Button-1>', previous)
        self._measurement_bindings[tag] = self._details.tag_bind(tag, '<Button-1>', lambda _event: callback())

    def _measurement_link(self, text, callback, tag):
        start = self._details.index('end-1c')
        self._details.insert('end', text)
        self._details.tag_add(tag, start, self._details.index('end-1c'))
        self._details.tag_configure(tag, foreground='#75bfff', underline=True)
        self._bind_measurement_tag(tag, callback)

    def _open_measurement_references(self, axis, side, page=0, barcode=''):
        self._cancel_measurement_task()
        self._showing_global = True
        self._measurement_request = (axis, side, page, barcode)
        self._details.configure(state='normal')
        self._details.delete('1.0', 'end')
        label = next(label for name,label,_ in AXES if name == axis)
        kind = 'Mesures proches du centre' if side.endswith('_group') else 'Trop petites' if side == 'under' else 'Trop grandes'
        self._details.insert('end', f"{label} — {kind}\n{barcode}\nPreparation de la liste...\n")
        self._details.configure(state='disabled')
        if isinstance(self._frames, FrameStore):
            self._own_session = self._own_session or (LoadingSession() if self._load_session is None else None)
            self._load_session = self._load_session or self._own_session
            try:
                self._measurement_task = self._load_session.start('measurement_references', store=str(self._frames.directory),
                    axis=axis, side=side, page=page, barcode=barcode)
            except Exception as exc:
                self._details.configure(state='normal')
                self._details.insert('end', '\nListe indisponible : ' + str(exc))
                self._details.configure(state='disabled')
                return
            self._measurement_job = self.after(10, self._poll_measurement_references)
        else:
            self._render_measurement_references(reference_page(self._measurement_analysis, axis, side, page, barcode))

    def _poll_measurement_references(self):
        self._measurement_job = None
        deadline = time.perf_counter() + .008
        while time.perf_counter() < deadline:
            try:
                kind, data = self._measurement_task.results.get_nowait()
            except Empty:
                break
            if kind == 'result':
                self._render_measurement_references(data)
            elif kind in ('done', 'error'):
                self._measurement_task = None
                if kind == 'error':
                    self._details.configure(state='normal')
                    self._details.insert('end', '\nListe indisponible : ' + str(data))
                    self._details.configure(state='disabled')
                return
        self._measurement_job = self.after(10, self._poll_measurement_references)

    def _render_measurement_references(self, data):
        axis,side,page,barcode = self._measurement_request
        label = next(label for name,label,_ in AXES if name == axis)
        grouped = side.endswith('_group')
        kind = 'Mesures proches du centre' if grouped else 'Trop petites' if side == 'under' else 'Trop grandes'
        self._details.configure(state='normal')
        self._details.delete('1.0', 'end')
        self._details.insert('end', f"{label} — {kind}\n")
        self._details.insert('end', 'Conformes voisines incluses ; detail de toutes les comparables du produit.\n\n'
            if grouped else 'Tri : pire ecart, puis nombre de boites.\n\n')
        self._measurement_link('Retour au bilan\n\n', self._show_global_summary, 'measurement-back')
        if barcode:
            self._details.insert('end', barcode + '\n\n')
            self._insert_product_observations(data, axis)
            if page == 0:
                representatives = data.get('representatives', [])
                if representatives:
                    self._details.insert('end', 'Exemples representatifs, conformes voisins inclus :\n')
                index = next(index for name,_,index in AXES if name == axis)
                for i,sample in enumerate(representatives):
                    self._details.insert('end', f"{sample['box']} — {sample['time_str']} — "
                        f"ecart {sample['deltas'][index]:+.1f} mm\n")
                    self._measurement_link('Voir dans AlphaViewer\n',
                        lambda s=sample: self._navigate_measurement_sample(s,axis), f'measurement-representative-{i}')
                self._details.insert('end', '\n')
            self._details.insert('end', 'Toutes les mesures comparables de ce produit :\n\n'
                if grouped else 'Boites hors tolerance de ce cote :\n\n')
            for i,sample in enumerate(data['samples']):
                index = next(index for name,_,index in AXES if name == axis)
                self._details.insert('end', f"{sample['box']} — {sample['time_str']} — {sample.get('name', '')}\n"
                    f"Attendu {sample['expected'][index]} mm ; mesure {sample['measured'][index]} mm ; ecart {sample['deltas'][index]:+.1f} mm.\n")
                self._measurement_link('Voir dans AlphaViewer\n\n', lambda s=sample: self._navigate_measurement_sample(s,axis), f'measurement-sample-{i}')
        else:
            for i,row in enumerate(data['rows']):
                self._measurement_link(f"{page*25+i+1}. {row['barcode']} — {row['name']}\n",
                    lambda b=row['barcode']: self._open_measurement_references(axis,side,0,b), f'measurement-ref-{i}')
                self._details.insert('end', f"   {row['count']}/{row['total']} boites ({row['percent']:.1f} %) ; "
                    f"plage {row['min_signed']:+.1f} a {row['max_signed']:+.1f} mm ; pire {row['worst']:+.1f} mm.\n\n")
                if row.get('variant_count', 0) > 1:
                    self._details.insert('end', '   Plusieurs variantes BdD : bilans separes dans le detail.\n\n')
        if not data['total']:
            self._details.insert('end', 'Aucune boite pour ce cote.\n')
        self._details.insert('end', f"Page {page+1}/{max(1,(data['total']+24)//25)} — {data['total']} {'boites' if barcode else 'references'}\n")
        if page:
            self._measurement_link('Precedents   ', lambda: self._open_measurement_references(axis,side,page-1,barcode), 'measurement-prev')
        if (page+1)*25 < data['total']:
            self._measurement_link('Suivants', lambda: self._open_measurement_references(axis,side,page+1,barcode), 'measurement-next')
        self._details.configure(state='disabled')
        self._details.yview_moveto(0)

    def _insert_product_observations(self, data, axis):
        observations = data.get('observations', [])
        if not observations:
            return
        self._details.insert('end', 'Toutes les mesures de ce produit dans la trace :\n')
        if data.get('variant_count', 0) > 1:
            self._details.insert('end', 'Plusieurs dimensions BdD : variantes analysees separement.\n')
        for row in observations:
            expected = row['expected']
            self._details.insert('end', f"\nBdD {expected[2]} x {expected[0]} x {expected[1]} mm "
                '(longueur x largeur x hauteur)\n'
                f"{row['total']} mesures ; plage {row['min_signed']:+.1f} a {row['max_signed']:+.1f} mm.\n")
            if row.get('center') is not None:
                self._details.insert('end', f"{row['close_count']}/{row['total']} mesures ({row['close_percent']:.1f} %) "
                    f"a +/-1 mm autour de {row['center']:+.1f} mm.\n")
            if row.get('repeated'):
                self._details.insert('end', 'Ecarts proches sur ce produit.\n')
            elif row['total'] == 1:
                self._details.insert('end', 'Une seule mesure : repetition non confirmee.\n')
            if row.get('dispersed'):
                self._details.insert('end', 'Dispersion observee sur ce produit : la fenetre de 2 mm la plus fournie '
                    f"contient {row['window_count']}/{row['total']} mesures ({row['window_percent']:.1f} %).\n")
            if row.get('limited'):
                self._details.insert('end', 'Effectif limite.\n')
        self._details.insert('end', '\n')

    def _navigate_measurement_sample(self, sample, axis):
        from Models.measurement_navigation import measurement_display_target
        try:
            _, line = measurement_display_target(sample)
            if self._on_measurement_sample is not None:
                self._on_measurement_sample(sample, axis)
            elif self._on_measurement_click is not None:
                self._on_measurement_click(line)
        except ValueError as exc:
            messagebox.showerror('Mesure', str(exc))
            return
        self._show_measurement_sample(sample, axis)

    def _show_measurement_sample(self, sample, axis='length'):
        self._cancel_measurement_task()
        self._showing_global = False
        self._details.configure(state='normal')
        self._details.delete('1.0', 'end')
        self._details.insert('end', f"{sample['barcode']} — {sample.get('name', '')}\n"
                             f"{sample['box']} — {sample.get('display_time_str', sample['time_str'])}\n")
        if sample.get('rejected_dimensions'):
            self._details.insert('end', f"Produit identifie puis rejete pour dimensions : {sample['current_reference']}\n")
        for name,label,index in AXES:
            self._details.insert('end', f"\n{label} : {sample['measured'][index]} / BdD {sample['expected'][index]} mm "
                f"({sample['deltas'][index]:+.1f} mm) ; mesure L.{sample['sources'][name]}.\n")
        if sample.get('t4t'):
            diff = f" ; diffT4 : {sample['diff_t4']:+.1f} mm" if sample.get('diff_t4') is not None else ''
            self._details.insert('end', f"\nT4T (complement) : {sample['t4t']} mm{diff}.\n")
        self._details.insert('end', f"\nIdentification L.{sample['sources']['identity']} ; BdD L.{sample['sources']['bdd']}.\n")
        for row in sample.get('context', []):
            self._details.insert('end', f"L.{row['line']} {row['text']}\n")
        self._measurement_link('\nRetour au bilan', self._show_global_summary, 'measurement-back')
        self._details.configure(state='disabled')

    def _open_web_report(self) -> None:
        if self._report_path is not None and report_files_available(self._report_path):
            self._launch_report(self._report_path)
            return
        if isinstance(self._frames, FrameStore):
            if self._report_task is not None:
                return
            try:
                if self._load_session is None:
                    self._own_session = self._own_session or LoadingSession()
                    self._load_session = self._own_session
                self._report_task = self._load_session.start(
                    'report', store=str(self._frames.directory), incidents=self._incidents,
                    source_name=self._source_name)
            except Exception as exc:
                messagebox.showerror('Rapport web', str(exc))
                return
            self._report_path = None
            self._report_btn.configure(text='Rapport en preparation...', state='disabled')
            self._report_job = self.after(10, self._poll_report)
            return
        try:
            report_path = write_diagnostic_report(self._incidents, frames=self._frames, source_name=self._source_name)
            self._report_path = Path(report_path)
            self._launch_report(report_path)
        except Exception as exc:
            messagebox.showerror(
                'Rapport web',
                f"Impossible de generer ou ouvrir le rapport diagnostic.\n\n{exc}",
            )

    def _poll_report(self):
        self._report_job = None
        deadline = time.perf_counter() + 0.008
        try:
            while time.perf_counter() < deadline:
                kind, payload = self._report_task.results.get_nowait()
                if kind == 'result':
                    self._report_path = Path(payload)
                elif kind in ('done', 'error'):
                    self._report_task = None
                    self._report_btn.configure(text='Rapport web', state='normal')
                    if kind == 'error':
                        messagebox.showerror('Rapport web', payload)
                    elif self._report_path is not None:
                        self._launch_report(self._report_path)
                    return
        except Empty:
            pass
        self._report_job = self.after(10, self._poll_report)

    def _launch_report(self, path):
        if self._on_report_open is not None:
            self._on_report_open(path)
        else:
            webbrowser.open(path.resolve().as_uri(), new=2)

    def destroy(self):
        self._cancel_measurement_task()
        self._host.unbind('<Configure>', self._host_binding)
        for job in (self._split_job, self._mode_job):
            if job is not None:
                self.after_cancel(job)
        self._renderer.cancel()
        if self._report_job is not None:
            self.after_cancel(self._report_job)
        if self._report_task is not None:
            self._report_task.cancel()
        if self._own_session is not None:
            self._own_session.close()
        super().destroy()

    def _on_click(self, event) -> None:
        idx = self._list.index(f'@{event.x},{event.y}')
        display_line = int(idx.split('.')[0])
        selected = self._line_to_incident.get(display_line)
        if not selected:
            return
        self._show_details(selected)
        if self._on_incident_click:
            self._on_incident_click(selected)
