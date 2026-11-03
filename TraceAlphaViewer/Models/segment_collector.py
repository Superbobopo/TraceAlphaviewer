"""Collecte commune pendant le parcours des snapshots d'un seul fichier."""
from Models.diagnostic import DiagnosticState, StateIncidentCollector
from Models.measurement_analysis import MeasurementCollector
from Models.reference_index import ReferenceCollector
from Models.trace_calendar import TraceLines
from Models.health_radar import HealthObservationCollector


class SegmentCollector:
    def __init__(self):
        self.measures = MeasurementCollector()
        self.references = ReferenceCollector()
        self.states = StateIncidentCollector()
        self.events = []
        self.lines = TraceLines()
        self.health = HealthObservationCollector()
        self.count = 0
        self._seen_events = set()
        self._seen_lines = set()

    def consume(self, frame):
        self.measures.consume(self.count, frame)
        self.references.consume(frame)
        self.health.observe_frame(frame, self.references, self._seen_lines)
        self.states.consume(frame)
        for event in frame.events:
            key = (event.line_num, event.kind, event.title)
            if key not in self._seen_events:
                self.events.append(event)
                self._seen_events.add(key)
        state = DiagnosticState(frame.timestamp, frame.timestamp_str, frame.C6)
        for line, text, *_ in frame.raw_lines:
            if line not in self._seen_lines:
                self.health.consume(text)
                self.lines.append((line, text, state))
                self._seen_lines.add(line)
        self.count += 1

    def finish(self):
        self.events.sort(key=lambda event: (event.line_num, event.kind, event.title))
        self._seen_events.clear()
        self._seen_lines.clear()
        return self.measures.finish()
