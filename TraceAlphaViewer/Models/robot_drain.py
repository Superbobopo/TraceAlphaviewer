"""Frequences et priorites partagees des demandes de vidage T5 robot."""
from __future__ import annotations
from datetime import date, timedelta
from dataclasses import replace

from Models.trace_calendar import date_label, display_time, source_datetime


def drain_metrics(occurrences, trace=None):
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
    result['critical'] = drain_is_critical(result)
    result['reinforced'] = False
    if trace:
        result['trace'] = trace
        result['daily'] = []
        if trace.get('available'):
            grouped = {}
            for line, _, time in ordered:
                moment = source_datetime(trace, line, time)
                if moment:
                    grouped.setdefault(moment.date(), []).append(
                        {'line': line, 'time_str': moment.strftime('%H:%M:%S'),
                         'display_time_str': display_time(trace, line, time)})
            day = date.fromisoformat(trace['first_date'])
            last = date.fromisoformat(trace['last_date'])
            while day <= last:
                examples = grouped.get(day, [])
                result['daily'].append({'date': day.isoformat(), 'label': date_label(day),
                    'count': len(examples), 'first_time': examples[0]['time_str'] if examples else '',
                    'last_time': examples[-1]['time_str'] if examples else '', 'examples': examples[:10]})
                day += timedelta(days=1)
        if ordered:
            result['requests_start'] = display_time(trace, ordered[0][0], ordered[0][2])
            result['requests_end'] = display_time(trace, ordered[-1][0], ordered[-1][2])
        for name in ('hour', 'day'):
            for key, line_key in (('start', 'first_line'), ('end', 'last_line')):
                result[name][key] = display_time(trace, result[name][line_key], result[name][key])
    return result


def drain_metric_text(metrics):
    return (f"{metrics['total']} demande(s) robot ; maximum "
            f"{metrics['day']['count']} sur 24 h glissantes")


def drain_is_critical(metrics):
    return int((metrics or {}).get('day', {}).get('count', 0)) >= 10


def drain_summary(metrics):
    return drain_metric_text(metrics) + ('. Critique : au moins 10 demandes sur 24 h glissantes.'
        if drain_is_critical(metrics) else '. Information : moins de 10 demandes sur 24 h glissantes.')


def normalize_robot_incidents(incidents):
    """Recalcule les anciens caches sans reutiliser leurs indicateurs de criticite."""
    result = []
    for incident in incidents:
        if incident.code == 'DemVidageComplet':
            metrics = dict(incident.metrics)
            critical = drain_is_critical(metrics)
            metrics.update(critical=critical, reinforced=False)
            incident = replace(incident, metrics=metrics, severity='error' if critical else 'info',
                               summary=drain_summary(metrics))
        result.append(incident)
    return result


def t5_priority_score(code, severity, count, metrics=None):
    base = {'error': 500, 'warning': 190, 'info': 80}.get(severity, 0)
    if code == 'T5_STALE_UNMEASURED_BOX':
        return base + 120 + min(count, 60)
    if code == 'DemVidageComplet':
        metrics = metrics or {}
        critical = drain_is_critical(metrics)
        return ((500 if critical else 80) + (140 if critical else 0)
                + min(int(metrics.get('day', {}).get('count', 0)), 60))
    return None
