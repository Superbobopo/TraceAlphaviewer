"""Analyse commune de segments d'un meme Alpha, sans prolonger leurs cycles."""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from bisect import bisect_left, bisect_right
from dataclasses import fields, replace
from datetime import datetime, timedelta
from pathlib import Path
import operator
import pickle
import time

from Models import diagnostic as diagnostic_model
from Models.folder_report import _collect_events
from Models.frame_store import FrameStore, write_frame_store_iter
from Models.measurement_analysis import (
    _analyze_comparable, analyze_measurements, build_orientation_lists, build_reference_lists, MeasurementCollector,
)
from Models.reference_index import build_reference_records, ReferenceCollector
from Models.robot_drain import (
    TraceCalendar, date_drain_metrics, drain_metric_text, drain_metrics, format_trace_duration,
    read_trace_origin, trace_period,
)
from Models.state import BoxInfo
from Models.robot_drain import analyze_robot_boxes, attach_robot_box_metrics, merge_robot_box_metrics
from Models.c5_analysis import merge_c5_metrics, c5_metric_text
from Models.trace_observations import OBSERVATION_CODES
from Models.diagnostic_summary import normalize_summary_incidents
from Models.trace_calendar import TraceLines


_BOX_LINES = tuple(item.name for item in fields(BoxInfo)
                   if item.name.endswith('_line') or item.name == 't5_transfer_id')
_CAMERA_CODES = {'UNKNOWN', 'CAM-NO-READ', 'REFERENCE_ABSENT', 'REFERENCE_NON_ALPHATISABLE'}
_DIMENSION_CODES = {'T4_LENGTH', 'T5_WIDTH', 'T5_HEIGHT', 'GLOBAL', 'ORIENTATION'}


class _SegmentFrames(Sequence):
    def __init__(self, frames, first, count):
        self.frames, self.first, self.count = frames, first, count

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self.count))]
        index = operator.index(index)
        if index < 0:
            index += self.count
        if not 0 <= index < self.count:
            raise IndexError(index)
        return self.frames[self.first + index]


def build_group_business_events(frames, events, belt):
    """Les details metier ne raccordent jamais deux segments de dossier."""
    from Models.event_cycles import build_business_events
    segments = getattr(frames, 'source_metadata', {}).get('segments', [])
    if len(segments) <= 1:
        return build_business_events(frames, events, belt)
    event_lines = [event.line_num for event in events]
    result = []
    for segment in segments:
        first = bisect_left(event_lines, segment['first_line'])
        last = bisect_right(event_lines, segment['last_line'])
        view = _SegmentFrames(frames, segment['first_frame'], segment['frame_count'])
        result.extend(build_business_events(view, events[first:last], belt))
    return result


def _iso_date(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def _source_origin(source):
    calendar = source.get('calendar') or {}
    origin = _iso_date(source.get('start') or calendar.get('start'))
    if origin is not None:
        with FrameStore(source['store']) as frames:
            return origin - timedelta(seconds=frames[0].timestamp if frames else 0)
    return read_trace_origin(source['filepath'])


def _dump(path, value):
    with Path(path).open('wb') as output:
        pickle.dump(value, output, protocol=pickle.HIGHEST_PROTOCOL)


def _copy_sources(sources, raw_path):
    metadata = []
    line_offset = 0
    with raw_path.open('wb') as output:
        for index, source in enumerate(sources):
            line_count = 0
            with open(source['filepath'], 'rb') as raw:
                for text in raw:
                    # Une fin de fichier sans retour ne doit pas fusionner deux lignes.
                    output.write(text if text.endswith(b'\n') else text.rstrip(b'\r') + b'\n')
                    line_count += 1
            metadata.append({'filepath': str(Path(source['filepath']).resolve()),
                             'name': source.get('name') or Path(source['filepath']).name,
                             'segment': index, 'first_line': line_offset + 1,
                             'last_line': line_offset + line_count, 'line_offset': line_offset,
                             'raw_line_count': line_count, 'identity': source.get('identity', {})})
            line_offset += line_count
    return metadata


def _group_frames(sources, metadata, origin, progress):
    segments = metadata['segments']
    date_segments = metadata['date_segments']
    frame_index = 0
    for index, source in enumerate(sources):
        location = metadata['sources'][index]
        offset = location['line_offset']
        source_origin = source['_origin']
        calendar = TraceCalendar(source_origin) if source_origin else None
        first_frame = frame_index
        start = end = None
        with FrameStore(source['store']) as frames:
            duplicate_ranges = frames.source_metadata.get('duplicate_ranges', [])
            metadata['duplicate_ranges'].extend({
                'first_line': row['first_line'] + offset,
                'last_line': row['last_line'] + offset,
                'source_first_line': row['source_first_line'] + offset,
            } for row in duplicate_ranges)
            for local_index, original in enumerate(frames):
                frame = original.deep_copy()
                frame.line_num += offset
                if frame.line_num > location['last_line']:
                    raise ValueError('Le stockage ne correspond plus aux lignes du fichier source')
                moment = calendar.at(original.timestamp) if calendar else None
                if moment is not None:
                    start = start or moment
                    end = moment
                    # Corriger le retour du jour firmware sans changer les flottants du parser.
                    rollover = round((moment - source_origin).total_seconds() - original.timestamp)
                    frame.timestamp = original.timestamp + rollover + (source_origin - origin).total_seconds()
                    date = moment.date().isoformat()
                    if not date_segments or date_segments[-1]['date'] != date:
                        date_segments.append({'line': frame.line_num, 'date': date})
                frame.raw_lines = [(number + offset, text, *extra)
                                   for number, text, *extra in frame.raw_lines]
                for box in (frame.box_in_EA, frame.box_on_T3, frame.box_on_T4, *frame.boxes_on_T5):
                    if box is not None:
                        for field in _BOX_LINES:
                            number = getattr(box, field)
                            if number:
                                setattr(box, field, number + offset)
                frame.events = [replace(event, line_num=event.line_num + offset,
                                        timestamp=event.timestamp + (frame.timestamp - original.timestamp))
                                for event in frame.events]
                frame_index += 1
                yield frame
                if progress and local_index % 500 == 0:
                    progress('merge', index, len(sources), location['name'])
            segments.append({'source': index, 'first_frame': first_frame,
                             'frame_count': frame_index - first_frame,
                             'last_frame': frame_index - 1,
                             'first_line': location['first_line'], 'last_line': location['last_line'],
                             'start': start.isoformat() if start else '',
                             'end': end.isoformat() if end else ''})
            location.update(start=start.isoformat() if start else '',
                            end=end.isoformat() if end else '')


def _group_period(metadata):
    intervals = [(datetime.fromisoformat(row['start']), datetime.fromisoformat(row['end']))
                 for row in metadata['segments'] if row['start'] and row['end']]
    if not intervals or len(intervals) != len(metadata['segments']):
        return {'available': False, 'segments': [], 'gaps': [], 'observed_duration_seconds': 0}
    intervals.sort()
    result = trace_period(intervals[0][0], max(end for _, end in intervals))
    observed = 0.0
    gaps = []
    left, right = intervals[0]
    for start, end in intervals[1:]:
        if start > right:
            observed += (right - left).total_seconds()
            gaps.append({'start': right.isoformat(), 'end': start.isoformat(),
                         'duration_seconds': (start - right).total_seconds()})
            left, right = start, end
        else:
            right = max(right, end)
    observed += (right - left).total_seconds()
    result.update(first_date=intervals[0][0].date().isoformat(),
                  last_date=max(end for _, end in intervals).date().isoformat(),
                  observed_duration_seconds=observed, observed_duration=format_trace_duration(observed),
                  gaps=gaps, segments=list(metadata['date_segments']))
    return result


def _measurement_union(analyses):
    samples, finals = [], []
    excluded = Counter()
    cycles = serial = 0
    for analysis in analyses:
        sample_ids = set()
        for sample in analysis['samples'] + analysis['finals']:
            if id(sample) not in sample_ids:
                sample_ids.add(id(sample))
                sample['cycle'] += serial
        serial = max((row['cycle'] for row in analysis['samples']), default=serial)
        samples.extend(analysis['samples'])
        finals.extend(analysis['finals'])
        excluded.update(analysis['summary']['excluded'])
        cycles += analysis['summary']['cycle_count']
    comparable = [row for row in finals if row['code'] != 'ORIENTATION']
    summary, products = _analyze_comparable(comparable, excluded)
    summary['cycle_count'] = cycles
    return {'summary': summary, 'samples': samples, 'finals': finals,
            'references': build_reference_lists(comparable, products, summary),
            'orientation_references': build_orientation_lists(finals)}


def _merge_camera(target, source):
    for key in ('all_hist_boxes',):
        target[key].update(source[key])
    for key in ('reader_boxes', 'reader_zero_boxes'):
        for reader in ('CB1', 'CB2'):
            target[key][reader].update(source[key][reader])
    for reader in ('CB1', 'CB2'):
        counts = Counter(target['success_by_reader'][reader])
        counts.update(source['success_by_reader'][reader])
        target['success_by_reader'][reader] = dict(counts)
    for key in ('created_unknown', 'hist_samples', 'cycles'):
        target[key].extend(source[key])


def _reset_observations(line_states, origin):
    previous = None
    result = []
    for line, text, frame in line_states:
        match = diagnostic_model._ALPHA_RESET_UPTIME.search(text)
        if match:
            minutes = int(match[1])
            if (previous is not None and minutes <= diagnostic_model._ALPHA_RESET_MAX_RESTART_MINUTES
                    and previous - minutes >= diagnostic_model._ALPHA_RESET_MIN_DROP_MINUTES):
                result.append((line, origin + timedelta(seconds=frame.timestamp) if origin else None))
            previous = minutes
    return result


def _combine_resets(incidents, observations, period):
    if not incidents:
        return []
    dated = Counter(moment.date().isoformat() for _, moment in observations if moment is not None)
    count = len(observations)
    selected = [row for row in incidents if row.count] or incidents
    first, last = selected[0], selected[-1]
    duration = period.get('observed_duration', period.get('duration', ''))
    metrics = {'trace_duration': duration,
               'max_daily_count': max(dated.values(), default=0),
               'daily': [{'date': day, 'count': amount} for day, amount in sorted(dated.items())],
               'observed_duration_seconds': period.get('observed_duration_seconds', 0)}
    return [replace(first, count=count, last_line=last.last_line, end_time=last.end_time,
                    end_time_str=last.end_time_str, metrics=metrics,
                    severity=diagnostic_model.alpha_reset_severity(count, metrics),
                    summary=f"{count} reset(s) carte Alpha detecte(s) sur {duration or 'la periode observee'} observee.",
                    event_lines=list(dict.fromkeys(line for row in incidents for line in row.event_lines)))]


def _daily_coverage(metrics, metadata):
    intervals = [(datetime.fromisoformat(row['start']), datetime.fromisoformat(row['end']))
                 for row in metadata['segments'] if row['start'] and row['end']]
    for day in metrics.get('daily', []):
        start = datetime.fromisoformat(day['date'])
        end = start + timedelta(days=1)
        touched = [(max(start, left), min(end, right)) for left, right in intervals
                   if left < end and right >= start]
        duration = sum(max(0, (right - left).total_seconds()) for left, right in touched)
        day.update(observed=bool(touched), observed_duration_seconds=duration,
                   partial=bool(touched) and duration < 86400,
                   status='observed' if touched else 'not_observed')
        if not touched:
            day['count'] = None


def _combine_signal(incidents):
    if not incidents:
        return []
    first, last = incidents[0], incidents[-1]
    if first.code == 'C5_SIGNAL_ANOMALY':
        metrics = merge_c5_metrics([row.metrics for row in incidents])
        metrics['episodes'] = [dict(episode, source_segment=row.metrics.get('source_segment', 0))
                               for row in incidents for episode in row.metrics['episodes']]
        examples, offset = [], 0
        for incident in incidents:
            examples.extend(dict(row, episode=row.get('episode', 0) + offset) for row in incident.examples)
            offset += incident.count
        return [replace(first, last_line=last.last_line, end_time=last.end_time,
                        end_time_str=last.end_time_str, count=metrics['episode_count'],
                        metrics=metrics, examples=examples, summary=c5_metric_text(metrics),
                        severity='error' if metrics['suspect_cycle_count'] else 'warning',
                        event_lines=[line for row in incidents for line in row.event_lines])]
    metrics = {key: sum(row.metrics.get(key, 0) for row in incidents)
               for key in ('episode_count', 'transitions', 'drain_relaunches', 'initialization_requests',
                           'unstable_episodes', 'blocked_episodes')}
    metrics['episodes'] = [episode for row in incidents for episode in row.metrics.get('episodes', [])]
    examples = []
    offset = 0
    for incident in incidents:
        examples.extend(dict(row, episode=row.get('episode', 0) + offset) for row in incident.examples)
        offset += incident.count
    sensor = 'C2' if first.code == 'C2_SIGNAL_ANOMALY' else 'C3'
    return [replace(first, last_line=last.last_line, end_time=last.end_time,
                    end_time_str=last.end_time_str, count=offset, metrics=metrics, examples=examples,
                    severity='error' if metrics['drain_relaunches'] else 'warning',
                    summary=diagnostic_model.signal_metric_text(metrics, sensor),
                    event_lines=[line for row in incidents for line in row.event_lines])]


def _combine_observations(incidents):
    if not incidents:return []
    first=min(incidents,key=lambda row:row.first_line)
    metrics={'observation_metrics_version':1,'episodes':[]}
    for incident in incidents:
        for key,value in incident.metrics.items():
            if key not in {'observation_metrics_version','source_segment','episodes'} and isinstance(value,int):
                metrics[key]=metrics.get(key,0)+value
        metrics['episodes'].extend(dict(episode,source_segment=incident.metrics.get('source_segment',0))
                                   for episode in incident.metrics['episodes'])
    code=first.code
    if code=='MOTOR_COMM':
        severity='error' if metrics['critical_episode_count'] else 'info'
        count=metrics['critical_episode_count'] or metrics['episode_count']
        rule='motor_comm'
    elif code=='DP_MISSING':
        severity='warning' if metrics['confirmed_count'] else 'info'
        count=metrics['confirmed_count'] or metrics['recovered_count']
        rule='dp_missing'
    else:
        severity,count,rule='warning',metrics['episode_count'],'camera_code_mode'
    return diagnostic_model._observation_incident(code,first.title,first.belt,severity,count,metrics,rule)


def analyze_segment(store_dir, segment, origin, index, total, name='', progress_cb=None):
    """Analyse un seul fichier, avec son lecteur et ses accumulateurs independants."""
    timings = {}
    with FrameStore(store_dir) as frames:
        tick = time.perf_counter()
        view = _SegmentFrames(frames, segment['first_frame'], segment['frame_count'])
        if progress_cb:
            progress_cb('analysis', index, total, name)
        measures, reference_index = MeasurementCollector(), ReferenceCollector()
        state_index = diagnostic_model.StateIncidentCollector()
        events, seen_events, line_states, seen_lines = [], set(), TraceLines(), set()
        for local_index, frame in enumerate(view):
            measures.consume(local_index, frame)
            reference_index.consume(frame)
            state_index.consume(frame)
            for event in frame.events:
                key = (event.line_num, event.kind, event.title)
                if key not in seen_events:
                    events.append(event)
                    seen_events.add(key)
            state = diagnostic_model.DiagnosticState(frame.timestamp, frame.timestamp_str, frame.C6)
            for line, text, *_ in frame.raw_lines:
                if line not in seen_lines:
                    line_states.append((line, text, state))
                    seen_lines.add(line)
            if progress_cb and local_index % 500 == 0:
                progress_cb('analysis', index, total, name)
        events.sort(key=lambda event: (event.line_num, event.kind, event.title))
        analysis = measures.finish()
        timings[f'segment_{index + 1}_collecte'] = time.perf_counter() - tick
        # L'index de preuve appartient au viewer commun, pas a la vue du segment.
        for sample in analysis['samples']:
            sample['display_frame_index'] += segment['first_frame']
        stats = {}
        if progress_cb:
            progress_cb('diagnostic', index, total, name)
        tick = time.perf_counter()
        robot_analysis = analyze_robot_boxes(line_states, origin, absolute_origin=total > 1)
        analyses = diagnostic_model.build_diagnostics(view, events, analysis, trace_origin=origin,
            line_states=line_states, camera_stats_output=stats, state_incidents=state_index.finish(),
            robot_box_analysis=robot_analysis)
        timings[f'segment_{index + 1}_diagnostic'] = time.perf_counter() - tick
        if total > 1:
            for incident in analyses:
                incident.metrics = dict(incident.metrics, source_segment=index)
        if progress_cb:
            progress_cb('references', index, total, name)
        tick = time.perf_counter()
        rows = reference_index.finish(events)
        timings[f'segment_{index + 1}_references'] = time.perf_counter() - tick
        if total > 1:
            for row in rows:
                row.key = f'S{index + 1}:{row.key}'
        resets = _reset_observations(line_states, origin)
        drains = [(line, frame.timestamp, frame.timestamp_str) for line, text, frame in line_states
                  if diagnostic_model._TRACE_T5_DEM_VIDAGE.search(text)]
        return dict(events=events, incidents=analyses, references=rows, analysis=analysis,
                    camera=stats, resets=resets, drains=drains, boxes=robot_analysis, timings=timings)


def _segment_results(store_dir, metadata, origin, progress_cb, parallel):
    segments = metadata['segments']
    if not parallel or len(segments) < 2:
        for index, segment in enumerate(segments):
            yield analyze_segment(store_dir, segment, origin, index, len(segments),
                                  metadata['sources'][index]['name'], progress_cb)
        return
    from Models.loading_client import WorkerTask
    from Models.worker_process_tree import own_process_tree
    from queue import Empty
    import uuid
    own_process_tree()
    child_root = Path(store_dir).parent / 'analysis-workers'
    for first in range(0, len(segments), 2):
        tasks = []
        try:
            for index in range(first, min(first + 2, len(segments))):
                tasks.append(WorkerTask(child_root / uuid.uuid4().hex, dict(
                    mode='segment_analysis', session=str(child_root), store=str(store_dir),
                    segment=segments[index], origin=origin, index=index, total=len(segments),
                    name=metadata['sources'][index]['name'])))
            for task in tasks:
                result = None
                while True:
                    try:
                        kind, payload = task.results.get(timeout=0.1)
                    except Empty:
                        if task.finished.is_set():
                            raise OSError('Sous-worker termine sans resultat de segment')
                        continue
                    if kind == 'segment_progress' and progress_cb:
                        progress_cb(*payload)
                    elif kind == 'segment_result':
                        result = payload
                    elif kind == 'error':
                        raise OSError(payload)
                    elif kind == 'done':
                        if result is None:
                            raise OSError('Analyse de segment incomplete')
                        if not task.finished.wait(10):
                            raise OSError('Le sous-worker ne se ferme pas')
                        yield result
                        break
        finally:
            for task in tasks:
                if not task.finished.is_set():
                    task.cancel()
            for task in tasks:
                task.finished.wait(10)


def analyze_group(sources, session_dir, progress_cb=None, *, timings=None, parallel=False):
    """Prepare le viewer d'un groupe dans le worker, sans liste globale de frames."""
    if not sources:
        raise ValueError('Le groupe ne contient aucun fichier')
    sources = [dict(source) for source in sources]
    for source in sources:
        source['_origin'] = _source_origin(source)
    if len(sources) > 1 and any(source['_origin'] is None for source in sources):
        raise ValueError('Les traces sans calendrier fiable doivent rester separees')
    sources.sort(key=lambda source: source['_origin'] or datetime.min)
    origin = sources[0]['_origin']
    directory = Path(session_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = directory / 'group.old'
    metadata = {'version': 1, 'group_name': sources[0].get('group_name', ''),
                'identity': sources[0].get('identity', {}),
                'sources': _copy_sources(sources, raw_path), 'segments': [],
                'date_segments': [], 'duplicate_ranges': []}
    store_dir = directory / 'frames'
    timings = timings if timings is not None else {}
    tick = time.perf_counter()
    count = write_frame_store_iter(_group_frames(sources, metadata, origin, progress_cb),
                                   store_dir, source_metadata=metadata)
    timings['regroupement'] = time.perf_counter() - tick
    period = _group_period(metadata)
    all_events, incidents, references, measurements, resets = [], [], [], [], []
    camera = None
    drains = []
    box_analyses = []
    with FrameStore(store_dir) as frames:
        for result in _segment_results(store_dir, metadata, origin, progress_cb, parallel):
            timings.update(result['timings'])
            incidents.extend(result['incidents'])
            references.extend(result['references'])
            measurements.append(result['analysis'])
            all_events.extend(result['events'])
            if camera is None:
                camera = result['camera']
            else:
                _merge_camera(camera, result['camera'])
            resets.extend(result['resets'])
            drains.extend(result['drains'])
            box_analyses.append(result['boxes'])
        analysis = _measurement_union(measurements)
        camera = camera or diagnostic_model._camera_stats([])
        camera['trace'] = period
        report = diagnostic_model.camera_report_stats(frames, stats=camera)
        if len(sources) > 1:
            motors = diagnostic_model._build_motor_error_incidents(all_events)
            motor_keys = {(row.belt, row.code) for row in motors}
            retained = [row for row in incidents if row.code not in _CAMERA_CODES | _DIMENSION_CODES | OBSERVATION_CODES |
                        {'ALPHA_CARD_RESET', 'DemVidageComplet', 'C2_SIGNAL_ANOMALY', 'C3_SIGNAL_ANOMALY', 'C5_SIGNAL_ANOMALY'}
                        and (row.belt, row.code) not in motor_keys]
            retained.extend(motors)
            for code in OBSERVATION_CODES:
                retained.extend(_combine_observations([row for row in incidents if row.code==code]))
            retained.extend(diagnostic_model._build_dimension_incidents(frames, [], analysis))
            retained.extend(diagnostic_model._build_unknown_camera_incident(camera))
            retained.extend(diagnostic_model._build_inactive_camera_incident(camera))
            retained.extend(diagnostic_model._build_reference_absent_incident(camera))
            retained.extend(diagnostic_model._build_reference_rejection_incident(camera, 'non_alphatisable'))
            retained.extend(_combine_resets([row for row in incidents if row.code == 'ALPHA_CARD_RESET'],
                                             resets, period))
            for code in ('C2_SIGNAL_ANOMALY', 'C3_SIGNAL_ANOMALY', 'C5_SIGNAL_ANOMALY'):
                retained.extend(_combine_signal([row for row in incidents if row.code == code]))
            drain_incidents = [row for row in incidents if row.code == 'DemVidageComplet']
            if drain_incidents:
                metrics = drain_metrics(drains)
                if origin is not None:
                    dated = [(line, origin + timedelta(seconds=time)) for line, time, _ in drains]
                    start = origin + timedelta(seconds=frames[0].timestamp)
                    end = origin + timedelta(seconds=frames[-1].timestamp)
                    date_drain_metrics(metrics, dated, start, end)
                    _daily_coverage(metrics, metadata)
                metrics['trace'] = period
                attach_robot_box_metrics(metrics, merge_robot_box_metrics(box_analyses))
                first, last = drain_incidents[0], drain_incidents[-1]
                retained.append(replace(first, count=len(drains), last_line=last.last_line,
                    end_time=last.end_time, end_time_str=last.end_time_str, metrics=metrics,
                    severity='error' if metrics['critical'] else 'info', summary=drain_metric_text(metrics),
                    event_lines=[line for line, _, _ in drains]))
            incidents = retained
    incidents = normalize_summary_incidents(incidents, len(sources))
    incidents.sort(key=lambda row: ({'error': 0, 'warning': 1, 'info': 2}.get(row.severity, 9),
                                   row.first_line, row.title))
    with (store_dir / 'index.pkl').open('rb') as source:
        index = pickle.load(source)
    index.update(measurement_summary=analysis['summary'], trace_period=period)
    _dump(store_dir / 'index.tmp', index)
    (store_dir / 'index.tmp').replace(store_dir / 'index.pkl')
    _dump(store_dir / 'events.pkl', all_events)
    _dump(store_dir / 'measurements.pkl', analysis)
    _dump(store_dir / 'camera_report.pkl', report)
    _dump(directory / 'manifest.pkl', metadata)
    name = metadata['group_name'] or sources[0].get('name') or 'Groupe Alpha'
    return {'filepath': str(raw_path), 'store': str(store_dir), 'name': name,
            'modified_ts': 0.0, 'parse_error': '', 'events': all_events,
            'diagnostics': incidents, 'references': references,
            'metadata': metadata, 'frame_count': count}
