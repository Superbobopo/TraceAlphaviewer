"""Progression estimee du chargement, sans dependance a Tk."""
from __future__ import annotations

import math
import time


PHASES = (
    ('read', 'Lecture et construction'),
    ('diagnostic', 'Diagnostics'),
    ('references', 'Finalisation des references'),
    ('display', 'Preparation du viewer'),
    ('raw', 'Chargement de la trace brute'),
)
# Mediane des parts observees sur les trois ouvertures locales du 26/10/2026.
PHASE_WEIGHTS = {'read': .540, 'diagnostic': .337, 'references': .001, 'display': .054, 'raw': .068}
CATALOG_WEIGHTS = {'read': .95, 'display': .05}
VIEW_SEGMENT = '__view__'


class ProgressTracker:
    def __init__(self, mode='file'):
        self.weights = dict(CATALOG_WEIGHTS if mode == 'folder_catalog' else PHASE_WEIGHTS)
        self._segments = {}
        self._values = {}
        self._states = {}
        self._fraction = 0.
        self._ready = False
        self.phase = 'read'
        self.task = ''

    def register_segments(self, segments):
        for segment in segments or ():
            weight = float(segment.get('weight', 1))
            self._segments[str(segment['id'])] = weight if math.isfinite(weight) and weight > 0 else 1.

    def update(self, payload):
        if not isinstance(payload, dict):
            # Les anciens workers ne savent mesurer que la lecture.
            payload = {'phase': 'read', 'done': payload, 'total': 1, 'segment': ''}
        self.register_segments(payload.get('segments'))
        phase = payload.get('phase', 'read')
        if phase not in self.weights:
            return self.fraction
        self.phase = phase
        self.task = str(payload.get('task', ''))
        segment = VIEW_SEGMENT if phase in ('display', 'raw') else str(payload.get('segment', ''))
        if segment != VIEW_SEGMENT and segment not in self._segments:
            self.register_segments([{'id': segment, 'weight': payload.get('segment_weight', 1)}])
        key = phase, segment
        state = payload.get('state', 'running')
        total = payload.get('total')
        if state == 'done':
            value = 1.
        elif total is not None and float(total) > 0:
            value = min(1., max(0., float(payload.get('done', 0)) / float(total)))
        else:
            value = self._values.get(key, 0.)
        if math.isfinite(value):
            self._values[key] = max(self._values.get(key, 0.), value)
        if self._states.get(key) != 'done':
            self._states[key] = state
        self._fraction = max(self._fraction, min(.999, self._estimate()))
        return self.fraction

    def _estimate(self):
        total_weight = sum(self._segments.values()) or 1.
        result = 0.
        for phase, weight in self.weights.items():
            if phase in ('display', 'raw'):
                value = self._values.get((phase, VIEW_SEGMENT), 0.)
            else:
                value = sum(self._values.get((phase, segment), 0.) * size
                            for segment, size in self._segments.items()) / total_weight
            result += weight * value
        return result

    @property
    def fraction(self):
        return 1. if self._ready else self._fraction

    def phase_state(self, phase):
        if phase not in self.weights:
            return 'unused'
        keys = ([(phase, VIEW_SEGMENT)] if phase in ('display', 'raw') else
                [(phase, segment) for segment in self._segments])
        states = [self._states.get(key) for key in keys]
        if states and all(state == 'done' for state in states):
            return 'done'
        return 'running' if any(state is not None for state in states) else 'pending'

    def complete_phase(self, phase):
        segments = ([VIEW_SEGMENT] if phase in ('display', 'raw') else list(self._segments) or [''])
        for segment in segments:
            self.update({'phase': phase, 'segment': segment, 'state': 'done'})

    def ready(self):
        for phase in self.weights:
            self.complete_phase(phase)
        self._ready = True
        return self.fraction


class ProgressEmitter:
    """Borne les messages intermediaires ; les fins restent explicites."""
    def __init__(self, send, segment='', segment_weight=1, clock=time.perf_counter):
        self.send = send
        self.segment = str(segment)
        self.segment_weight = segment_weight
        self.clock = clock
        self._last = -float('inf')

    def emit(self, phase, task='', done=0, total=None, unit='', state='running', force=False, segments=None):
        now = self.clock()
        if not force and state != 'done' and now - self._last < .1:
            return
        self._last = now
        payload = dict(version=1, phase=phase, task=task, done=done, total=total, unit=unit,
                       segment=self.segment, segment_weight=self.segment_weight, state=state)
        if segments is not None:
            payload['segments'] = segments
        self.send('progress', payload)
