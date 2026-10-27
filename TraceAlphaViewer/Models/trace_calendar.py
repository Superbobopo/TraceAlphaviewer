"""Calendrier observe dans les entetes de trace, sans supposer la date du PC."""
from bisect import bisect_right
from datetime import datetime, timedelta
from functools import lru_cache
from array import array
from collections.abc import Mapping
import re


_OPEN_DATE = re.compile(r'OUVERTURE DE LA TRACE.*?\ble\s+(\d{2}/\d{2}/\d{4})', re.I)
_CLOCK = re.compile(r'(\d{2}):(\d{2}):(\d{2})')
_MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
           'août', 'septembre', 'octobre', 'novembre', 'décembre')


def date_label(day):
    return f'{day.day} {_MONTHS[day.month - 1]} {day.year}'


@lru_cache(maxsize=8192)
def clock_seconds(time_str):
    clock = _CLOCK.search(time_str)
    return sum(int(value) * factor for value, factor in zip(clock.groups(), (3600, 60, 1))) if clock else None


class TraceLines(list):
    """Lignes d'un seul segment avec calendrier partage entre analyses."""

    calendar = None


class ObservationClock:
    """Temps numeriques partages ; seules les preuves demandent une date formatee."""

    def __init__(self, line_states, origin):
        self.origin = origin
        self.length = len(line_states)
        self.calendar = trace_calendar(line_states) if origin is None else None
        self.times = None
        if origin is not None:
            from Models.robot_drain import TraceCalendar
            dated = TraceCalendar(origin)
            self.times = array('d')
            previous = None
            value = 0.0
            for _, _, state in line_states:
                if state.timestamp != previous:
                    value = (dated.at(state.timestamp) - origin).total_seconds()
                    previous = state.timestamp
                self.times.append(value)

    def values(self, line_states):
        return iter(self.times) if self.times is not None else (row[2].timestamp for row in line_states)

    def label(self, line, seconds, timestamp_str, raw=None):
        if self.origin is not None:
            return format_observed_time(self.origin + timedelta(seconds=seconds))
        return display_time(self.calendar, line, raw if raw is not None else timestamp_str)


def observation_clock(line_states, origin=None):
    # Les lignes d'un segment restent immuables pendant ses analyses.
    cached = getattr(line_states, '_observation_clock', None)
    if cached is not None and cached.origin == origin and cached.length == len(line_states):
        return cached
    clock = ObservationClock(line_states, origin)
    if isinstance(line_states, TraceLines):
        line_states._observation_clock = clock
    return clock


_RAW_TIME = re.compile(r'\d+\|\d{2}:\d{2}:\d{2}(?:\.\d+)?')


class TimedObservation(Mapping):
    """Observation C5 interne, sans chaine de date sur les lignes ignorees."""
    __slots__ = ('line', 'time', 'clock', 'timestamp_str', 'text', 'label', 'value', 'previous', 'lower')

    def __init__(self, clock, line, seconds, timestamp_str, text):
        self.clock, self.line, self.time = clock, line, seconds
        self.timestamp_str, self.text = timestamp_str, text
        self.label = self.value = None
        self.previous = None
        self.lower = None

    def __iter__(self):
        return iter(('line', 'time', 'time_str', 'value') if self.value is not None else ('line', 'time', 'time_str'))

    def __len__(self):
        return 4 if self.value is not None else 3

    def __getitem__(self, key):
        if key == 'line':
            return self.line
        if key == 'time':
            return self.time
        if key == 'value' and self.value is not None:
            return self.value
        if key == 'time_str':
            if self.label is None:
                match = _RAW_TIME.search(self.text) if self.clock.origin is None else None
                raw = match[0] if match else self.timestamp_str
                self.label = self.clock.label(self.line, self.time, self.timestamp_str, raw)
            return self.label
        raise KeyError(key)


class _Calendar(dict):
    def compile_segments(self):
        self.starts = tuple(item['line'] for item in self['segments'])
        self.dates = tuple(item['date'] for item in self['segments'])


@lru_cache(maxsize=8192)
def _format_clock(date, hour, minute, second):
    return datetime.fromisoformat(date).replace(hour=hour, minute=minute, second=second).strftime('%d/%m/%Y à %H:%M:%S')


def format_observed_time(moment):
    return _format_clock(moment.date().isoformat(), moment.hour, moment.minute, moment.second)


def trace_calendar(line_states):
    if isinstance(line_states, TraceLines) and line_states.calendar is not None:
        return line_states.calendar
    result = _Calendar(_build_calendar(line_states))
    result.compile_segments()
    if isinstance(line_states, TraceLines):
        line_states.calendar = result
    return result


def _build_calendar(line_states):
    observations = []
    anchor = None
    previous = None
    elapsed = 0.0
    for line, text, state in line_states:
        seconds = clock_seconds(state.timestamp_str)
        if seconds is None:
            continue
        current = (state.timestamp, seconds)
        if previous is not None and current != previous:
            delta = current[0] - previous[0]
            # Le compteur jour du firmware peut revenir a 1 au changement de mois.
            elapsed += delta if delta > -86400 else (seconds - previous[1]) % 86400
        if previous != current or not observations:
            observations.append((line, elapsed, state.timestamp_str, seconds))
        previous = current
        match = _OPEN_DATE.search(text)
        if match and anchor is None:
            try:
                anchor = (elapsed, datetime.strptime(match[1], '%d/%m/%Y') + timedelta(seconds=seconds))
            except ValueError:
                pass
    if not observations:
        return {'available': False, 'start': '', 'end': '', 'days': 0, 'segments': []}
    duration = max(0, observations[-1][1] - observations[0][1])
    hours, remainder = divmod(int(duration), 3600)
    minutes, seconds = divmod(remainder, 60)
    result = {'available': anchor is not None, 'start': observations[0][2], 'end': observations[-1][2],
              'days': 0, 'duration_seconds': duration,
              'duration': f'{hours} h {minutes:02d} min {seconds:02d} s', 'segments': []}
    if anchor is not None:
        moments = [(line, anchor[1] + timedelta(seconds=offset - anchor[0]))
                   for line, offset, _, _ in observations]
        result.update(start=moments[0][1].strftime('%d/%m/%Y à %H:%M:%S'),
                      end=moments[-1][1].strftime('%d/%m/%Y à %H:%M:%S'),
                      first_date=moments[0][1].date().isoformat(),
                      last_date=moments[-1][1].date().isoformat(),
                      days=(moments[-1][1].date() - moments[0][1].date()).days + 1)
        for line, moment in moments:
            day = moment.date().isoformat()
            if not result['segments'] or result['segments'][-1]['date'] != day:
                result['segments'].append({'line': line, 'date': day})
    return result


def source_datetime(period, line, time_str):
    segments = period.get('segments', [])
    clock = _CLOCK.search(time_str)
    if not segments or not clock:
        return None
    starts = period.starts if isinstance(period, _Calendar) else [item['line'] for item in segments]
    index = max(0, bisect_right(starts, line) - 1)
    return datetime.fromisoformat(segments[index]['date']).replace(
        hour=int(clock[1]), minute=int(clock[2]), second=int(clock[3]))


def display_time(period, line, time_str):
    segments = period.get('segments', [])
    if not segments:
        return time_str
    clock = _CLOCK.search(time_str)
    if not clock:
        return time_str
    starts = period.starts if isinstance(period, _Calendar) else [item['line'] for item in segments]
    index = max(0, bisect_right(starts, line) - 1)
    return _format_clock(segments[index]['date'], int(clock[1]), int(clock[2]), int(clock[3]))
