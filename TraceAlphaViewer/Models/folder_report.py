from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from Models.diagnostic import DiagnosticIncident, build_diagnostics
from Models.state import MachineEvent, MachineState
from Parser.trace_parser import parse_file


TRACE_EXTENSIONS = {'.old', '.txt'}


@dataclass
class TraceReportEntry:
    filepath: str
    name: str
    modified_ts: float = 0.0
    frames: list[MachineState] = field(default_factory=list)
    events: list[MachineEvent] = field(default_factory=list)
    diagnostics: list[DiagnosticIncident] = field(default_factory=list)
    error_events: list[MachineEvent] = field(default_factory=list)
    parse_error: str = ""

    @property
    def has_data(self) -> bool:
        return bool(self.frames) and not self.parse_error

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def error_count(self) -> int:
        return len(self.error_events)

    @property
    def diagnostic_count(self) -> int:
        return len(self.diagnostics)

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def start_time_str(self) -> str:
        if not self.frames:
            return '--:--:--'
        return self.frames[0].timestamp_str

    @property
    def end_time_str(self) -> str:
        if not self.frames:
            return '--:--:--'
        return self.frames[-1].timestamp_str

    @property
    def status_label(self) -> str:
        if self.parse_error:
            return 'Erreur parse'
        if not self.frames:
            return 'Trace vide'
        return 'OK'


@dataclass
class FolderReport:
    directory: str
    entries: list[TraceReportEntry] = field(default_factory=list)

    @property
    def trace_count(self) -> int:
        return len(self.entries)

    @property
    def parsed_entries(self) -> list[TraceReportEntry]:
        return [entry for entry in self.entries if entry.has_data]

    @property
    def total_frames(self) -> int:
        return sum(entry.frame_count for entry in self.entries)

    @property
    def total_diagnostics(self) -> int:
        return sum(entry.diagnostic_count for entry in self.entries)

    @property
    def total_errors(self) -> int:
        return sum(entry.error_count for entry in self.entries)

    @property
    def total_events(self) -> int:
        return sum(entry.event_count for entry in self.entries)

    @property
    def failed_entries(self) -> list[TraceReportEntry]:
        return [entry for entry in self.entries if entry.parse_error]


def find_trace_files(directory: str | Path) -> list[Path]:
    root = Path(directory)
    traces: list[Path] = []
    for path in root.rglob('*'):
        if not path.is_file() or path.suffix.lower() not in TRACE_EXTENSIONS:
            continue
        traces.append(path.resolve())
    return sorted(traces, key=lambda p: p.stat().st_mtime, reverse=True)


def _collect_events(frames: list[MachineState]) -> list[MachineEvent]:
    events: list[MachineEvent] = []
    seen: set[tuple[int, str, str]] = set()
    for frame in frames:
        for event in frame.events:
            key = (event.line_num, event.kind, event.title)
            if key in seen:
                continue
            seen.add(key)
            events.append(event)
    return sorted(events, key=lambda event: (event.line_num, event.kind, event.title))


def build_trace_report_entry(path: str | Path, min_dt: float = 0.0) -> TraceReportEntry:
    filepath = str(Path(path).resolve())
    entry = TraceReportEntry(
        filepath=filepath,
        name=Path(filepath).name,
        modified_ts=Path(filepath).stat().st_mtime,
    )
    try:
        frames = parse_file(filepath, min_dt=min_dt)
    except Exception as exc:
        entry.parse_error = str(exc)
        return entry

    events = _collect_events(frames)
    entry.frames = frames
    entry.events = events
    entry.diagnostics = build_diagnostics(frames, events)
    entry.error_events = [event for event in events if event.severity == 'error']
    return entry


def build_folder_report(
    directory: str | Path,
    progress_cb: Callable[[int, int, str], None] | None = None,
    min_dt: float = 0.0,
) -> FolderReport:
    files = find_trace_files(directory)
    entries: list[TraceReportEntry] = []
    total = len(files)
    for index, path in enumerate(files, 1):
        if progress_cb:
            progress_cb(index - 1, total, path.name)
        entries.append(build_trace_report_entry(path, min_dt=min_dt))
        if progress_cb:
            progress_cb(index, total, path.name)
    return FolderReport(directory=str(Path(directory).resolve()), entries=entries)


def export_folder_report_csv(report: FolderReport, output_path: str | Path) -> None:
    fieldnames = [
        'fichier', 'statut', 'type', 'severite', 'zone', 'code', 'titre',
        'premiere_ligne', 'derniere_ligne', 'heure_debut', 'heure_fin',
        'occurrences', 'resume',
    ]
    with open(output_path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for entry in report.entries:
            if entry.parse_error:
                writer.writerow({
                    'fichier': entry.name,
                    'statut': 'Erreur parse',
                    'type': 'erreur',
                    'severite': 'error',
                    'zone': '',
                    'code': 'PARSE',
                    'titre': 'Erreur lecture/parse de trace',
                    'premiere_ligne': '',
                    'derniere_ligne': '',
                    'heure_debut': '',
                    'heure_fin': '',
                    'occurrences': 1,
                    'resume': entry.parse_error,
                })
                continue

            for incident in entry.diagnostics:
                writer.writerow({
                    'fichier': entry.name,
                    'statut': entry.status_label,
                    'type': 'diagnostic',
                    'severite': incident.severity,
                    'zone': incident.belt,
                    'code': incident.code,
                    'titre': incident.title,
                    'premiere_ligne': incident.first_line,
                    'derniere_ligne': incident.last_line,
                    'heure_debut': incident.start_time_str,
                    'heure_fin': incident.end_time_str,
                    'occurrences': incident.count,
                    'resume': incident.summary,
                })

            for event in entry.events:
                writer.writerow({
                    'fichier': entry.name,
                    'statut': entry.status_label,
                    'type': 'erreur' if event.severity == 'error' else 'evenement',
                    'severite': event.severity,
                    'zone': event.kind,
                    'code': '',
                    'titre': event.title,
                    'premiere_ligne': event.line_num,
                    'derniere_ligne': event.line_num,
                    'heure_debut': event.timestamp_str,
                    'heure_fin': event.timestamp_str,
                    'occurrences': 1,
                    'resume': event.detail,
                })
