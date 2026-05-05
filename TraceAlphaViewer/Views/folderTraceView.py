from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog

from Models.diagnostic import DiagnosticIncident
from Models.folder_report import FolderReport, TraceReportEntry, export_folder_report_csv
from Models.state import MachineEvent
from Views.BaseView import BaseView
from Widgets.folder_panels import GroupSection, GroupedItemPanel, TraceListPanel
from Widgets.trace_panel import TracePanel


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
        for widget in self.winfo_children():
            widget.destroy()

    def _build(self) -> None:
        self._build_title_bar()

        body = ctk.CTkFrame(self, fg_color='#12121f', corner_radius=0)
        body.pack(fill='both', expand=True)

        self._bottom = ctk.CTkFrame(body, fg_color='#0f0f1c', corner_radius=0, height=280)
        self._bottom.pack(fill='x', side='bottom')
        self._bottom.pack_propagate(False)
        self._build_bottom(self._bottom)

        top = ctk.CTkFrame(body, fg_color='#12121f', corner_radius=0)
        top.pack(fill='both', expand=True)

        self._trace_list = TraceListPanel(top, on_select=self._select_entry, width=360)
        self._trace_list.pack(side='left', fill='both', padx=(6, 3), pady=6)
        self._trace_list.set_entries(self._report.entries)

        analysis = ctk.CTkFrame(top, fg_color='#12121f', corner_radius=0)
        analysis.pack(side='right', fill='both', expand=True, padx=(3, 6), pady=6)
        self._build_analysis(analysis)

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
            )
            tabs.pack(fill='both', expand=True)
            summary_tab = tabs.add('Capteurs & Tapis')
            diag_tab = tabs.add('Diagnostic')
            error_tab = tabs.add('Erreur')
            event_tab = tabs.add('Evenements')
            tabs.set('Diagnostic')
        else:
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
            title='DIAGNOSTIC GLOBAL DOSSIER',
            item_label=self._diagnostic_item_label,
            detail_label=self._diagnostic_detail_label,
            on_item_click=self._on_diagnostic_click,
            empty_text='Aucun diagnostic detecte sur le dossier charge.',
        )
        self._diagnostic_panel.pack(fill='both', expand=True)

        self._error_panel = GroupedItemPanel(
            error_tab,
            title='ERREURS DOSSIER',
            item_label=self._event_item_label,
            detail_label=self._event_detail_label,
            on_item_click=self._on_event_click,
            empty_text='Aucune erreur detectee sur le dossier charge.',
        )
        self._error_panel.pack(fill='both', expand=True)

        self._event_panel = GroupedItemPanel(
            event_tab,
            title='EVENEMENTS DOSSIER',
            item_label=self._event_item_label,
            detail_label=self._event_detail_label,
            on_item_click=self._on_event_click,
            empty_text='Aucun evenement detecte sur le dossier charge.',
        )
        self._event_panel.pack(fill='both', expand=True)

        self._refresh_analysis_tabs()

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

        self._trace_placeholder = ctk.CTkLabel(
            parent,
            text='Choisis une trace dans la liste pour afficher la previsualisation brute.',
            font=('Consolas', 11),
            text_color='#556677',
        )
        self._trace_placeholder.pack(fill='both', expand=True)

        self._trace_panel = TracePanel(parent, on_line_click=None)

    def _refresh_analysis_tabs(self) -> None:
        self._diagnostic_panel.set_groups(
            self._build_diagnostic_sections(),
            summary=self._diagnostic_summary_text(),
        )
        self._error_panel.set_groups(
            self._build_error_sections(),
            summary=f'{self._report.total_errors} erreurs detectees sur {self._report.trace_count} trace(s).',
        )
        self._event_panel.set_groups(
            self._build_event_sections(),
            summary=f'{self._report.total_events} evenements detectes sur {self._report.trace_count} trace(s).',
        )

    def _build_diagnostic_sections(self) -> list[GroupSection[FolderDiagnosticRef]]:
        sections: list[GroupSection[FolderDiagnosticRef]] = []
        for entry in self._report.entries:
            items = [FolderDiagnosticRef(entry, incident) for incident in entry.diagnostics]
            if entry.parse_error:
                continue
            if not items:
                continue
            sections.append(GroupSection(
                title=f'{entry.name}  ({len(items)} diagnostics)',
                items=items,
            ))
        return sections

    def _build_error_sections(self) -> list[GroupSection[FolderEventRef]]:
        sections: list[GroupSection[FolderEventRef]] = []
        for entry in self._report.entries:
            items: list[FolderEventRef] = []
            if entry.parse_error:
                parse_event = MachineEvent(
                    line_num=0,
                    timestamp=0.0,
                    timestamp_str='--:--:--',
                    severity='error',
                    kind='PARSE',
                    title='Erreur lecture/parse de trace',
                    detail=entry.parse_error,
                )
                items.append(FolderEventRef(entry, parse_event))
            items.extend(FolderEventRef(entry, event) for event in entry.error_events)
            if not items:
                continue
            sections.append(GroupSection(
                title=f'{entry.name}  ({len(items)} erreurs)',
                items=items,
            ))
        return sections

    def _build_event_sections(self) -> list[GroupSection[FolderEventRef]]:
        sections: list[GroupSection[FolderEventRef]] = []
        for entry in self._report.entries:
            if entry.parse_error or not entry.events:
                continue
            sections.append(GroupSection(
                title=f'{entry.name}  ({len(entry.events)} evenements)',
                items=[FolderEventRef(entry, event) for event in entry.events],
            ))
        return sections

    def _diagnostic_summary_text(self) -> str:
        counter = Counter()
        for entry in self._report.entries:
            for incident in entry.diagnostics:
                counter[incident.title] += 1
        if not counter:
            return 'Aucun diagnostic global detecte sur le dossier charge.'
        top = ', '.join(f'{title}: {count}' for title, count in counter.most_common(4))
        return (
            f'{self._report.total_diagnostics} diagnostics sur {self._report.trace_count} trace(s). '
            f'Familles principales: {top}'
        )

    def _diagnostic_item_label(self, ref: FolderDiagnosticRef) -> str:
        incident = ref.incident
        return (
            f'{incident.start_time_str:<8} {incident.severity.upper():<8} '
            f'{incident.belt or "-":<4} L.{incident.first_line:<7} '
            f'{incident.count:>3}x  {incident.title}'
        )

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
        self._select_entry(ref.entry)

    def _on_event_click(self, ref: FolderEventRef) -> None:
        self._select_entry(ref.entry)

    def _select_entry(self, entry: TraceReportEntry) -> None:
        self._selected_entry = entry
        self._trace_list.highlight_entry(entry.filepath)
        self._update_summary(entry)
        self._update_preview(entry)

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

    def _update_preview(self, entry: TraceReportEntry) -> None:
        self._preview_label.configure(text=f'Previsualisation : {entry.name}')
        if entry.parse_error:
            self._trace_panel.pack_forget()
            if not self._trace_placeholder.winfo_manager():
                self._trace_placeholder.pack(fill='both', expand=True)
            self._trace_placeholder.configure(text=f'Impossible de charger la trace: {entry.parse_error}')
            self._trace_loaded_path = ''
            return

        if self._trace_placeholder.winfo_manager():
            self._trace_placeholder.pack_forget()
        if not self._trace_panel.winfo_manager():
            self._trace_panel.pack(fill='both', expand=True)
        if self._trace_loaded_path != entry.filepath:
            self._trace_panel.load_file(entry.filepath)
            self._trace_loaded_path = entry.filepath

    def _open_selected_trace(self) -> None:
        entry = self._selected_entry
        if entry is None or entry.parse_error:
            return
        from Views.traceView import TraceView
        self.master.switch_view(
            TraceView(self.master, filepath=entry.filepath, frames=entry.frames, return_view=self)
        )

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
