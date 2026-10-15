"""Frequences et priorites partagees des demandes de vidage T5 robot."""
from __future__ import annotations


def drain_metrics(occurrences):
    ordered = sorted(occurrences, key=lambda item: (item[1], item[0]))
    result = {'total': len(ordered)}
    for name, seconds in (('hour', 3600), ('day', 86400)):
        left = 0
        best_left, best_right = 0, -1
        for right, item in enumerate(ordered):
            while item[1] - ordered[left][1] > seconds:
                left += 1
            if right - left > best_right - best_left:
                best_left, best_right = left, right
        result[name] = {'count': best_right - best_left + 1,
                        'first_line': ordered[best_left][0] if ordered else 0,
                        'last_line': ordered[best_right][0] if ordered else 0,
                        'start': ordered[best_left][2] if ordered else '',
                        'end': ordered[best_right][2] if ordered else ''}
    result['critical'] = result['hour']['count'] >= 2 or result['day']['count'] >= 5
    result['reinforced'] = result['day']['count'] >= 15
    return result


def drain_metric_text(metrics):
    return (f"{metrics['total']} demande(s) robot ; maximum "
            f"{metrics['hour']['count']} sur 1 h et {metrics['day']['count']} sur 24 h")


def t5_priority_score(code, severity, count, metrics=None):
    base = {'error': 500, 'warning': 190, 'info': 80}.get(severity, 0)
    if code == 'T5_STALE_UNMEASURED_BOX':
        return base + 120 + min(count, 60)
    if code == 'DemVidageComplet':
        metrics = metrics or {}
        critical = metrics.get('critical', severity == 'error')
        return (base + (140 if critical else 0)
                + min(int(metrics.get('day', {}).get('count', count)), 60)
                + (100 if metrics.get('reinforced') else 0))
    return None
