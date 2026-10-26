"""Classement relatif C5/T5 depuis les cycles et intervalles observes."""
from collections import defaultdict
from math import isfinite

IMPACT_CODES = {'C5_SIGNAL_ANOMALY', 'T5_STALE_UNMEASURED_BOX'}
UNAVAILABLE = 'Impact indisponible — régénérer le rapport'


def _get(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def prepare_impact(incidents):
    intervals = defaultdict(list)
    cycles = set()
    c5_count = 0
    code = None
    for incident in incidents:
        current_code = _get(incident, 'code')
        if current_code not in IMPACT_CODES or code not in (None, current_code):
            return {'available': False, 'note': UNAVAILABLE}
        code = current_code
        metrics = _get(incident, 'metrics', {})
        segment = metrics.get('source_segment', 0)
        if code == 'C5_SIGNAL_ANOMALY':
            if not metrics.get('c5_metrics_version') or not metrics.get('episodes'):
                return {'available': False, 'note': UNAVAILABLE}
            records = metrics['episodes']
            c5_count += metrics['suspect_cycle_count']
        else:
            if not metrics.get('priority_impact_version') or not metrics.get('blocked_cycle'):
                return {'available': False, 'note': UNAVAILABLE}
            records = [metrics['blocked_cycle']]
        for record in records:
            source = record.get('source_segment', segment)
            start, end = record.get('start_time'), record.get('end_time')
            if not isinstance(start, (float, int)) or not isinstance(end, (float, int)) or not all(map(isfinite, (start, end))) or end < start:
                return {'available': False, 'note': UNAVAILABLE}
            intervals[source].append((start, end))
            if code == 'T5_STALE_UNMEASURED_BOX':
                cycles.add((source, record['first_line'], record['id_alpha']))
    duration = 0.0
    episodes = 0
    for spans in intervals.values():
        merged = []
        for start, end in sorted(spans):
            if merged and start < merged[-1][1]:
                merged[-1][1] = max(end, merged[-1][1])
            elif merged and (start, end) == tuple(merged[-1]):
                continue
            else:
                merged.append([start, end])
        duration += sum(end - start for start, end in merged)
        episodes += len(merged)
    return {'available': True, 'cycles': c5_count if code == 'C5_SIGNAL_ANOMALY' else len(cycles),
            'episodes': episodes, 'duration_seconds': duration}


def order_impact(groups):
    """Ne permute que les positions C5/T5 de meme criticite, avant toute limite."""
    result = list(groups)
    positions = defaultdict(list)
    for index, group in enumerate(result):
        if group['code'] not in IMPACT_CODES:
            continue
        group['priority_impact'] = prepare_impact(group['incidents'])
        positions[group.get('field_severity', group['severity'])].append(index)
    for slots in positions.values():
        selected = [result[index] for index in slots]
        if not all(group['priority_impact']['available'] for group in selected):
            continue
        selected.sort(key=lambda group: (-group['priority_impact']['cycles'],
            -group['priority_impact']['episodes'], -group['priority_impact']['duration_seconds'], group['first_line']))
        for index, group in zip(slots, selected):
            result[index] = group
    return result
