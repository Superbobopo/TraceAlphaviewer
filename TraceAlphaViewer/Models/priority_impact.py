"""Classement commun selon les blocages effectivement observes."""
from collections import defaultdict
from math import isfinite

IMPACT_CODES = {'C5_SIGNAL_ANOMALY', 'T5_STALE_UNMEASURED_BOX'}
UNAVAILABLE = 'Impact indisponible — régénérer le rapport'


def _get(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def prepare_impact(incidents):
    intervals = defaultdict(list)
    cycles = set()
    code = None
    for incident in incidents:
        current_code = _get(incident, 'code')
        if current_code not in IMPACT_CODES or code not in (None, current_code):
            return {'available': False, 'note': UNAVAILABLE}
        code = current_code
        metrics = _get(incident, 'metrics', {})
        segment = metrics.get('source_segment', 0)
        if code == 'C5_SIGNAL_ANOMALY':
            if metrics.get('c5_metrics_version', 0) < 2:
                return {'available': False, 'note': UNAVAILABLE}
            records = [record for record in metrics.get('episodes', []) if record.get('kind') == 'blocked_transfer']
            if metrics.get('blocked_transfer_count') and not records:
                return {'available': False, 'note': UNAVAILABLE}
        else:
            if not metrics.get('priority_impact_version') or not metrics.get('blocked_cycle'):
                return {'available': False, 'note': UNAVAILABLE}
            records = [metrics['blocked_cycle']]
        for record in records:
            source = record.get('source_segment', segment)
            start, end = record.get('start_time'), record.get('end_time')
            if not isinstance(start, (float, int)) or not isinstance(end, (float, int)) or not all(map(isfinite, (start, end))) or end < start:
                return {'available': False, 'note': UNAVAILABLE}
            intervals[(source, record.get('context', 0))].append((start, end))
            if code == 'T5_STALE_UNMEASURED_BOX':
                cycles.add((source, record['first_line'], record['id_alpha']))
            else:
                cycles.add((source, record.get('first_line'), record.get('id_b')))
    duration = 0.0
    episodes = 0
    blocking = False
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
        blocking |= any(end - start >= 120 for start, end in merged)
        episodes += len(merged)
    return {'available': True, 'cycles': len(cycles), 'blocking': blocking,
            'episodes': episodes, 'duration_seconds': duration}


def order_impact(groups):
    """La gravite precede le blocage confirme, puis le classement habituel."""
    result = list(groups)
    for group in result:
        if group['code'] not in IMPACT_CODES:
            continue
        if 'priority_impact' not in group:
            group['priority_impact'] = prepare_impact(group.get('incidents', []))
    def key(group):
        impact = group.get('priority_impact', {})
        blocked = impact.get('available') and impact.get('blocking')
        severity = {'error': 0, 'warning': 1, 'info': 2}.get(group.get('field_severity', group['severity']), 9)
        if blocked:
            return (severity, 0, -impact['duration_seconds'], -impact['cycles'], -impact['episodes'], group['first_line'])
        return (severity, 1, -group.get('field_priority', group.get('priority_score', 0)), 0, 0, group['first_line'])
    return sorted(result, key=key)
