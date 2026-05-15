from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog

from Models.diagnostic import DiagnosticIncident
from Models.folder_report import FolderReport, TraceReportEntry, export_folder_report_csv
from Models.state import MachineEvent
from Views.BaseView import BaseView
from Widgets.folder_panels import GroupSection, GroupedItemPanel, TraceListPanel
from Widgets.trace_panel import TracePanel


PREVIEW_BAR_H = 36
RESIZE_HANDLE_H = 7


@dataclass
class FolderDiagnosticRef:
    entry: TraceReportEntry
    incident: DiagnosticIncident


@dataclass
class FolderEventRef:
    entry: TraceReportEntry
    event: MachineEvent


class FolderTraceView(BaseView):
    def __init__(self, master, report: FolderReport, **kwargs):
        super().__init__(master, fg_color='#12121f', **kwargs)
        self._report = report
        self._selected_entry: TraceReportEntry | None = None
        self._trace_loaded_path: str = ''
        self._details_height = 280
        self._resize_job: str | None = None
        self._drag_start_y = 0
        self._drag_start_details_height = self._details_height
        self._active_focus_line: int | None = None
        self._active_focus_start: int | None = None
        self._active_focus_end: int | None = None
        self._active_tab = 'Diagnostic'
        self._viewer_window: ctk.CTkToplevel | None = None
        self._viewer_view: BaseView | None = None

    def show(self) -> None:
        super().show()
        self._build()
        if self._selected_entry is not None:
            selected = next(
                (entry for entry in self._report.entries if entry.filepath == self._selected_entry.filepath),
                None,
            )
            if selected is not None:
                self._select_entry(selected)
                return
        if self._report.entries:
            first_ok = next((entry for entry in self._report.entries if entry.has_data), self._report.entries[0])
            self._select_entry(first_ok)

    def hide(self) -> None:
        super().hide()
        self._close_viewer_window()
        for widget in self.winfo_children():
            widget.destroy()

    def _build(self) -> None:
        self._build_title_bar()

        body = ctk.CTkFrame(self, fg_color='#12121f', corner_radius=0)
        body.pack(fill='both', expand=True)

        self._bottom = ctk.CTkFrame(
            body,
            fg_color='#0f0f1c',
            corner_radius=0,
            height=self._bottom_total_height(),
        )
        self._bottom.pack(fill='x', side='bottom')
        self._bottom.pack_propagate(False)
        self._build_bottom(self._bottom)
        self.after(80, lambda: self._set_bottom_height(self._details_height))

        top = ctk.CTkFrame(body, fg_color='#12121f', corner_radius=0)
        top.pack(fill='both', expand=True)

        self._trace_list = TraceListPanel(top, on_select=self._select_entry, width=360)
        self._trace_list.pack(side='left', fill='both', padx=(6, 3), pady=6)
        self._trace_list.set_entries(self._report.entries)

        analysis = ctk.CTkFrame(top, fg_color='#12121f', corner_radius=0)
        analysis.pack(side='right', fill='both', expand=True, padx=(3, 6), pady=6)
        self._build_analysis(analysis)

    def _bottom_total_height(self) -> int:
        return PREVIEW_BAR_H + RESIZE_HANDLE_H + self._details_height

    def _current_bottom_height(self) -> int:
        if not hasattr(self, '_details_frame'):
            return self._details_height
        height = self._details_frame.winfo_height()
        return max(160, height if height > 1 else self._details_height)

    def _set_bottom_height(self, bottom_height: int) -> None:
        if not hasattr(self, '_bottom'):
            return
        self._details_height = max(160, int(bottom_height))
        self._details_frame.configure(height=self._details_height)
        self._bottom.configure(height=self._bottom_total_height())

    def _start_details_resize(self, event) -> None:
        self._drag_start_y = event.y_root
        self._drag_start_details_height = self._current_bottom_height()

    def _drag_details_resize(self, event) -> None:
        delta = event.y_root - self._drag_start_y
        self._queue_bottom_height(self._drag_start_details_height - delta)

    def _queue_bottom_height(self, bottom_height: int) -> None:
        self._pending_details_height = max(160, int(bottom_height))
        if self._resize_job is None:
            self._resize_job = self.after_idle(self._apply_pending_bottom_height)

    def _apply_pending_bottom_height(self) -> None:
        self._resize_job = None
        self._set_bottom_height(getattr(self, '_pending_details_height', self._details_height))

    def _build_title_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color='#1e1e30', height=38, corner_radius=0)
        bar.pack(fill='x', side='top')
        bar.pack_propagate(False)

        dirname = Path(self._report.directory).name or self._report.directory
        ctk.CTkLabel(
            bar,
            text=f'  Dossier : {dirname}',
            font=('Consolas', 12, 'bold'),
            text_color='#88aacc',
        ).pack(side='left', padx=12)

        ctk.CTkLabel(
            bar,
            text=(
                f'{self._report.trace_count} traces | '
                f'{self._report.total_diagnostics} diagnostics | '
                f'{self._report.total_errors} erreurs | '
                f'{self._report.total_events} evenements'
            ),
            font=('Consolas', 11),
            text_color='#556677',
        ).pack(side='left', padx=8)

        ctk.CTkButton(
            bar,
            text='Exporter CSV',
            width=110,
            height=28,
            fg_color='#1e3a5f',
            hover_color='#2a4a7f',
            font=('Consolas', 10, 'bold'),
            command=self._export_csv,
        ).pack(side='right', padx=(0, 8), pady=4)

        ctk.CTkButton(
            bar,
            text='✕ Fermer',
            width=80,
            height=28,
            fg_color='#2a2a3e',
            hover_color='#aa2233',
            text_color='#cc8888',
            font=('Consolas', 11),
            command=self._close,
        ).pack(side='right', padx=8, pady=4)

    def _build_analysis(self, parent) -> None:
        if hasattr(ctk, 'CTkTabview'):
            tabs = ctk.CTkTabview(
                parent,
                fg_color='#12121f',
                segmented_button_fg_color='#1e1e30',
                segmented_button_selected_color='#1e3a5f',
                segmented_button_selected_hover_color='#2a4a7f',
                segmented_button_unselected_color='#252538',
                segmented_button_unselected_hover_color='#353555',
                text_color='#aabbcc',
                command=self._on_tab_change,
            )
            self._tabs = tabs
            tabs.pack(fill='both', expand=True)
            summary_tab = tabs.add('Capteurs & Tapis')
            diag_tab = tabs.add('Diagnostic')
            error_tab = tabs.add('Erreur')
            event_tab = tabs.add('Evenements')
        else:
            self._tabs = None
            summary_tab = ctk.CTkFrame(parent, fg_color='#12121f')
            diag_tab = ctk.CTkFrame(parent, fg_color='#12121f')
            error_tab = ctk.CTkFrame(parent, fg_color='#12121f')
            event_tab = ctk.CTkFrame(parent, fg_color='#12121f')
            summary_tab.pack(fill='both', expand=True)
            diag_tab.pack_forget()
            error_tab.pack_forget()
            event_tab.pack_forget()

        self._summary_panel = self._build_summary_panel(summary_tab)
        self._diagnostic_panel = GroupedItemPanel(
            diag_tab,
            title='DIAGNOSTIC TRACE',
            item_label=self._diagnostic_item_label,
            detail_label=self._diagnostic_detail_label,
            item_tags=self._diagnostic_item_tags,
            on_item_click=self._on_diagnostic_click,
            empty_text='Aucun diagnostic detecte sur la trace selectionnee.',
        )
        self._diagnostic_panel.pack(fill='both', expand=True)

        self._error_panel = GroupedItemPanel(
            error_tab,
            title='ERREURS TRACE',
            item_label=self._event_item_label,
            detail_label=self._event_detail_label,
            item_tags=self._event_item_tags,
            on_item_click=self._on_event_click,
            empty_text='Aucune erreur pour cette trace.',
        )
        self._error_panel.pack(fill='both', expand=True)

        self._event_panel = GroupedItemPanel(
            event_tab,
            title='EVENEMENTS TRACE',
            item_label=self._event_item_label,
            detail_label=self._event_detail_label,
            item_tags=self._event_item_tags,
            on_item_click=self._on_event_click,
            empty_text='Aucun evenement detecte sur la trace selectionnee.',
        )
        self._event_panel.pack(fill='both', expand=True)

        self._refresh_analysis_tabs()
        if self._tabs is not None:
            self._tabs.set('Diagnostic')

    def _build_summary_panel(self, parent):
        frame = ctk.CTkFrame(parent, fg_color='#12121f', corner_radius=0)
        frame.pack(fill='both', expand=True)

        header = ctk.CTkFrame(frame, fg_color='#1e1e30', height=28, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)
        ctk.CTkLabel(
            header,
            text='SYNTHESE TRACE SELECTIONNEE',
            font=('Consolas', 10, 'bold'),
            text_color='#88aacc',
        ).pack(side='left', padx=8)

        self._summary_text = ctk.CTkTextbox(
            frame,
            fg_color='#0f0f1c',
            text_color='#aabbcc',
            font=('Consolas', 10),
            corner_radius=0,
        )
        self._summary_text.pack(fill='both', expand=True, pady=(0, 8))
        self._summary_text.configure(state='disabled')

        action_bar = ctk.CTkFrame(frame, fg_color='transparent')
        action_bar.pack(fill='x', pady=(0, 8))

        self._btn_open_trace = ctk.CTkButton(
            action_bar,
            text='Ouvrir cette trace',
            width=160,
            height=30,
            fg_color='#1e3a5f',
            hover_color='#2a4a7f',
            font=('Consolas', 10, 'bold'),
            command=self._open_selected_trace,
        )
        self._btn_open_trace.pack(side='left', padx=8)
        return frame

    def _build_bottom(self, parent) -> None:
        bar = ctk.CTkFrame(parent, fg_color='#1a1a2e', height=36, corner_radius=0)
        bar.pack(fill='x', side='top')
        bar.pack_propagate(False)

        self._preview_label = ctk.CTkLabel(
            bar,
            text='Aucune trace selectionnee',
            font=('Consolas', 10),
            text_color='#778899',
        )
        self._preview_label.pack(side='left', padx=10)

        ctk.CTkButton(
            bar,
            text='Ouvrir la trace',
            width=120,
            height=26,
            fg_color='#252538',
            hover_color='#353555',
            font=('Consolas', 10),
            command=self._open_selected_trace,
        ).pack(side='right', padx=8, pady=5)

        self._resize_handle = tk.Frame(parent, bg='#263142', height=RESIZE_HANDLE_H, cursor='sb_v_double_arrow')
        self._resize_handle.pack(fill='x', side='top')
        self._resize_handle.bind('<ButtonPress-1>', self._start_details_resize)
        self._resize_handle.bind('<B1-Motion>', self._drag_details_resize)

        self._details_frame = ctk.CTkFrame(parent, fg_color='#12121f', corner_radius=0)
        self._details_frame.pack(fill='both', expand=True, side='top')
        self._details_frame.pack_propagate(False)

        self._trace_placeholder = ctk.CTkLabel(
            self._details_frame,
            text='Choisis une trace dans la liste pour afficher la previsualisation brute.',
            font=('Consolas', 11),
            text_color='#556677',
        )
        self._trace_placeholder.pack(fill='both', expand=True)

        self._trace_panel = TracePanel(self._details_frame, on_line_click=self._on_trace_line_click)

    def _refresh_analysis_tabs(self) -> None:
        self._diagnostic_panel.set_groups(
            self._build_diagnostic_sections(self._selected_entry),
            summary=self._diagnostic_summary_text(),
        )
        self._error_panel.set_groups(
            self._build_error_sections(self._selected_entry),
            summary=self._selected_error_summary_text(),
        )
        self._event_panel.set_groups(
            self._build_event_sections(self._selected_entry),
            summary=self._selected_event_summary_text(),
        )
        self._sync_active_tab_to_focus(trigger_callback=False)

    def _on_tab_change(self, *_args) -> None:
        if self._tabs is None:
            return
        self._active_tab = self._tabs.get()
        self._sync_active_tab_to_focus(trigger_callback=True)

    def _build_diagnostic_sections(self, selected_entry: TraceReportEntry | None) -> list[GroupSection[FolderDiagnosticRef]]:
        sections: list[GroupSection[FolderDiagnosticRef]] = []
        if selected_entry is None or selected_entry.parse_error:
            return sections
        items = [FolderDiagnosticRef(selected_entry, incident) for incident in selected_entry.diagnostics]
        if items:
            sections.append(GroupSection(
                title=f'{selected_entry.name}  ({len(items)} diagnostics)',
                items=items,
            ))
        return sections

    def _build_error_sections(self, selected_entry: TraceReportEntry | None) -> list[GroupSection[FolderEventRef]]:
        sections: list[GroupSection[FolderEventRef]] = []
        if selected_entry is None:
            return sections

        items: list[FolderEventRef] = []
        if selected_entry.parse_error:
            parse_event = MachineEvent(
                line_num=0,
                timestamp=0.0,
                timestamp_str='--:--:--',
                severity='error',
                kind='PARSE',
                title='Erreur lecture/parse de trace',
                detail=selected_entry.parse_error,
            )
            items.append(FolderEventRef(selected_entry, parse_event))
        items.extend(FolderEventRef(selected_entry, event) for event in selected_entry.error_events)
        if items:
            sections.append(GroupSection(
                title=f'{selected_entry.name}  ({len(items)} erreurs)',
                items=items,
            ))
        return sections

    def _build_event_sections(self, selected_entry: TraceReportEntry | None) -> list[GroupSection[FolderEventRef]]:
        sections: list[GroupSection[FolderEventRef]] = []
        if selected_entry is None or selected_entry.parse_error or not selected_entry.events:
            return sections
        sections.append(GroupSection(
            title=f'{selected_entry.name}  ({len(selected_entry.events)} evenements)',
            items=[FolderEventRef(selected_entry, event) for event in selected_entry.events],
        ))
        return sections

    def _diagnostic_summary_text(self) -> str:
        entry = self._selected_entry
        if entry is None:
            return 'Choisis une trace a gauche pour afficher ses diagnostics.'
        if entry.parse_error:
            return f'{entry.name}: erreur de lecture/parse.'
        return f'{entry.name}: {entry.diagnostic_count} diagnostic(s) detecte(s).'

    def _selected_event_summary_text(self) -> str:
        entry = self._selected_entry
        if entry is None:
            return 'Choisis une trace a gauche pour afficher ses evenements.'
        if entry.parse_error:
            return f'{entry.name}: erreur de lecture/parse.'
        return f'{entry.name}: {entry.event_count} evenement(s) detecte(s).'

    def _selected_error_summary_text(self) -> str:
        entry = self._selected_entry
        if entry is None:
            return 'Choisis une trace a gauche pour afficher ses erreurs.'
        if entry.parse_error:
            return f'{entry.name}: erreur de lecture/parse.'
        return f'{entry.name}: {entry.error_count} erreur(s) detectee(s).'

    def _diagnostic_item_label(self, ref: FolderDiagnosticRef) -> str:
        incident = ref.incident
        return (
            f'{incident.start_time_str:<8} {incident.severity.upper():<8} '
            f'{incident.belt or "-":<4} L.{incident.first_line:<7} '
            f'{incident.count:>3}x  {incident.title}'
        )

    def _diagnostic_item_tags(self, ref: FolderDiagnosticRef) -> tuple[str, ...]:
        severity = ref.incident.severity.lower()
        if severity == 'error':
            return ('error',)
        if severity == 'warning':
            return ('warning',)
        return ('info',)

    def _diagnostic_detail_label(self, ref: FolderDiagnosticRef) -> str:
        incident = ref.incident
        return (
            f'Fichier   : {ref.entry.name}\n'
            f'Incident  : {incident.title}\n'
            f'Zone      : {incident.belt or "-"}\n'
            f'Code      : {incident.code or "-"}\n'
            f'Periode   : {incident.start_time_str} -> {incident.end_time_str}\n'
            f'Lignes    : L.{incident.first_line} -> L.{incident.last_line}\n'
            f'Occurrences : {incident.count}\n\n'
            f'Symptome:\n{incident.symptom or "-"}\n\n'
            f'Resume:\n{incident.summary}\n\n'
            f'Causes probables:\n' + '\n'.join(f'- {cause}' for cause in incident.probable_causes or ['-']) + '\n\n'
            f'Verifications:\n' + '\n'.join(f'- {check}' for check in incident.checks or ['-'])
        )

    def _event_item_label(self, ref: FolderEventRef) -> str:
        event = ref.event
        return f'{event.timestamp_str:<8} {event.kind:<9} L.{event.line_num:<7} {event.title}'

    def _event_item_tags(self, ref: FolderEventRef) -> tuple[str, ...]:
        severity = ref.event.severity.lower()
        if severity == 'error':
            return ('error',)
        if severity == 'warning':
            return ('warning',)
        return ('info',)

    def _event_detail_label(self, ref: FolderEventRef) -> str:
        event = ref.event
        return (
            f'Fichier   : {ref.entry.name}\n'
            f'Type      : {event.kind}\n'
            f'Severite  : {event.severity}\n'
            f'Heure     : {event.timestamp_str}\n'
            f'Ligne     : {event.line_num or "-"}\n'
            f'Titre     : {event.title}\n\n'
            f'Detail:\n{event.detail or "-"}'
        )

    def _on_diagnostic_click(self, ref: FolderDiagnosticRef) -> None:
        self._set_active_focus(ref.entry, ref.incident.first_line, ref.incident.first_line, ref.incident.last_line)
        self._update_preview(ref.entry, focus_line=ref.incident.first_line)
        self._focus_viewer_on_line(ref.entry, ref.incident.first_line)

    def _on_event_click(self, ref: FolderEventRef) -> None:
        self._set_active_focus(ref.entry, ref.event.line_num, ref.event.line_num, ref.event.line_num)
        self._update_preview(ref.entry, focus_line=ref.event.line_num)
        self._focus_viewer_on_line(ref.entry, ref.event.line_num)

    def _on_trace_line_click(self, file_line: int) -> None:
        entry = self._selected_entry
        if entry is None or entry.parse_error:
            return
        self._set_active_focus(entry, file_line, file_line, file_line)
        self._trace_panel.highlight_lines(file_line, file_line)
        self._sync_active_tab_to_focus(trigger_callback=False)
        self._focus_viewer_on_line(entry, file_line)

    def _select_entry(self, entry: TraceReportEntry, focus_line: int | None = None) -> None:
        previous_path = self._selected_entry.filepath if self._selected_entry is not None else ''
        self._selected_entry = entry
        self._trace_list.highlight_entry(entry.filepath)
        self._update_summary(entry)
        if focus_line is None:
            self._set_active_focus(entry, None, None, None)
        else:
            self._set_active_focus(entry, focus_line, focus_line, focus_line)
        if previous_path != entry.filepath or focus_line is None:
            self._refresh_selected_tabs()
        self._update_preview(entry, focus_line=focus_line)

    def _set_active_focus(
        self,
        entry: TraceReportEntry,
        line: int | None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> None:
        self._selected_entry = entry
        self._active_focus_line = line if line and line > 0 else None
        self._active_focus_start = start_line if start_line and start_line > 0 else self._active_focus_line
        self._active_focus_end = end_line if end_line and end_line > 0 else self._active_focus_line
        if (
            self._active_focus_start is not None
            and self._active_focus_end is not None
            and self._active_focus_start > self._active_focus_end
        ):
            self._active_focus_start, self._active_focus_end = self._active_focus_end, self._active_focus_start

    def _refresh_selected_tabs(self) -> None:
        self._diagnostic_panel.set_groups(
            self._build_diagnostic_sections(self._selected_entry),
            summary=self._diagnostic_summary_text(),
        )
        self._error_panel.set_groups(
            self._build_error_sections(self._selected_entry),
            summary=self._selected_error_summary_text(),
        )
        self._event_panel.set_groups(
            self._build_event_sections(self._selected_entry),
            summary=self._selected_event_summary_text(),
        )
        self._sync_active_tab_to_focus(trigger_callback=False)

    def _sync_active_tab_to_focus(self, trigger_callback: bool = False) -> None:
        if self._selected_entry is None or self._active_tab == 'Capteurs & Tapis':
            return
        if self._active_focus_line is None:
            self._diagnostic_panel.clear_selection()
            self._error_panel.clear_selection()
            self._event_panel.clear_selection()
            return

        if self._active_tab == 'Diagnostic':
            self._diagnostic_panel.select_item(
                self._best_diagnostic_for_focus(),
                trigger_callback=trigger_callback,
            )
        elif self._active_tab == 'Erreur':
            self._error_panel.select_item(
                self._best_event_for_focus(self._selected_entry.error_events),
                trigger_callback=trigger_callback,
            )
        elif self._active_tab == 'Evenements':
            self._event_panel.select_item(
                self._best_event_for_focus(self._selected_entry.events),
                trigger_callback=trigger_callback,
            )

    def _best_diagnostic_for_focus(self) -> FolderDiagnosticRef | None:
        entry = self._selected_entry
        if entry is None or not entry.diagnostics or self._active_focus_line is None:
            return None
        incident = min(
            entry.diagnostics,
            key=lambda item: self._range_distance(item.first_line, item.last_line),
        )
        return FolderDiagnosticRef(entry, incident)

    def _best_event_for_focus(self, events: list[MachineEvent]) -> FolderEventRef | None:
        entry = self._selected_entry
        candidates = [event for event in events if event.line_num > 0]
        if entry is None or not candidates or self._active_focus_line is None:
            return None
        event = min(
            candidates,
            key=lambda item: self._range_distance(item.line_num, item.line_num),
        )
        return FolderEventRef(entry, event)

    def _range_distance(self, start_line: int, end_line: int) -> int:
        focus = self._active_focus_line or 0
        active_start = self._active_focus_start or focus
        active_end = self._active_focus_end or focus
        start = min(start_line, end_line)
        end = max(start_line, end_line)
        if start <= active_end and end >= active_start:
            return 0
        if end < active_start:
            return active_start - end
        return start - active_end

    def _update_summary(self, entry: TraceReportEntry) -> None:
        self._summary_text.configure(state='normal')
        self._summary_text.delete('1.0', 'end')
        if entry.parse_error:
            text = (
                f'Fichier : {entry.name}\n'
                f'Statut  : Erreur parse\n\n'
                f'Detail:\n{entry.parse_error}'
            )
            self._btn_open_trace.configure(state='disabled')
        else:
            text = (
                f'Fichier     : {entry.name}\n'
                f'Plage horaire : {entry.start_time_str} -> {entry.end_time_str}\n'
                f'Frames      : {entry.frame_count}\n'
                f'Diagnostics : {entry.diagnostic_count}\n'
                f'Erreurs     : {entry.error_count}\n'
                f'Evenements  : {entry.event_count}\n'
                f'Statut      : {entry.status_label}\n'
            )
            self._btn_open_trace.configure(state='normal')
        self._summary_text.insert('end', text)
        self._summary_text.configure(state='disabled')

    def _update_preview(self, entry: TraceReportEntry, focus_line: int | None = None) -> None:
        self._preview_label.configure(text=f'Previsualisation : {entry.name}')
        if entry.parse_error:
            self._trace_panel.pack_forget()
            if not self._trace_placeholder.winfo_manager():
                self._trace_placeholder.pack(fill='both', expand=True)
            self._trace_placeholder.configure(text=f'Impossible de charger la trace: {entry.parse_error}')
            self._trace_loaded_path = ''
            self._trace_panel.clear_highlight()
            return

        if self._trace_placeholder.winfo_manager():
            self._trace_placeholder.pack_forget()
        if not self._trace_panel.winfo_manager():
            self._trace_panel.pack(fill='both', expand=True)
        if self._trace_loaded_path != entry.filepath:
            self._trace_panel.load_file(entry.filepath)
            self._trace_loaded_path = entry.filepath
        if focus_line and focus_line > 0:
            self._trace_panel.highlight_lines(focus_line, focus_line)
        else:
            self._trace_panel.clear_highlight()

    def _open_selected_trace(self) -> None:
        entry = self._selected_entry
        if entry is None or entry.parse_error:
            return
        self._open_selected_trace_in_window(entry)

    def _open_selected_trace_in_window(self, entry: TraceReportEntry) -> None:
        from Views.folderPlaybackView import FolderPlaybackView

        window = self._ensure_viewer_window(entry)
        if self._viewer_view is not None:
            self._viewer_view.hide()
            self._viewer_view.destroy()

        self._viewer_view = FolderPlaybackView(
            window,
            entry=entry,
            on_frame=self._on_viewer_frame,
            on_close=self._close_viewer_window,
        )
        self._viewer_view.show()
        window.title(f'TraceAlpha Viewer - {entry.name}')
        window.deiconify()
        window.lift()
        window.focus_force()

    def _focus_viewer_on_line(self, entry: TraceReportEntry, file_line: int) -> None:
        if file_line <= 0:
            return
        if self._viewer_window is None or not self._viewer_window.winfo_exists() or self._viewer_view is None:
            return
        if not hasattr(self._viewer_view, 'is_entry') or not hasattr(self._viewer_view, 'go_to_file_line'):
            return
        if not self._viewer_view.is_entry(entry):
            self._open_selected_trace_in_window(entry)
        if self._viewer_view is not None and hasattr(self._viewer_view, 'go_to_file_line'):
            self._viewer_view.go_to_file_line(file_line, stop=True)
            if self._viewer_window is not None and self._viewer_window.winfo_exists():
                self._viewer_window.lift()

    def _ensure_viewer_window(self, entry: TraceReportEntry) -> ctk.CTkToplevel:
        if self._viewer_window is not None and self._viewer_window.winfo_exists():
            return self._viewer_window

        window = ctk.CTkToplevel(self.master)
        window.title(f'TraceAlpha Viewer - {entry.name}')
        window.geometry('980x650')
        window.minsize(960, 640)
        window.configure(fg_color='#12121f')
        window.protocol('WM_DELETE_WINDOW', self._close_viewer_window)
        self._viewer_window = window
        return window

    def _on_viewer_frame(self, entry: TraceReportEntry, frame) -> None:
        if self._selected_entry is None or self._selected_entry.filepath != entry.filepath:
            self._select_entry(entry)
        elif self._trace_loaded_path != entry.filepath:
            self._update_preview(entry)
        self._highlight_preview_frame(entry, frame)

    def _highlight_preview_frame(self, entry: TraceReportEntry, frame) -> None:
        self._preview_label.configure(text=f'Previsualisation : {entry.name}')
        if self._trace_placeholder.winfo_manager():
            self._trace_placeholder.pack_forget()
        if not self._trace_panel.winfo_manager():
            self._trace_panel.pack(fill='both', expand=True)
        if self._trace_loaded_path != entry.filepath:
            self._trace_panel.load_file(entry.filepath)
            self._trace_loaded_path = entry.filepath

        start_line = frame.line_num
        end_line = frame.raw_lines[-1][0] if frame.raw_lines else start_line
        self._trace_panel.highlight_lines(start_line, end_line)

    def _close_viewer_window(self) -> None:
        view = self._viewer_view
        window = self._viewer_window
        self._viewer_view = None
        self._viewer_window = None

        if view is not None:
            try:
                view.hide()
                view.destroy()
            except tk.TclError:
                pass
        if window is not None:
            try:
                if window.winfo_exists():
                    window.destroy()
            except tk.TclError:
                pass

    def _export_csv(self) -> None:
        default_name = f"{Path(self._report.directory).name or 'rapport_traces'}.csv"
        path = filedialog.asksaveasfilename(
            title='Exporter le rapport CSV',
            defaultextension='.csv',
            initialfile=default_name,
            filetypes=[('CSV', '*.csv')],
        )
        if not path:
            return
        export_folder_report_csv(self._report, path)

    def _close(self) -> None:
        from Views.accueilView import AccueilView
        self.master.switch_view(AccueilView(self.master))
