"""Frequences et priorites partagees des demandes de vidage T5 robot."""
from __future__ import annotations
from datetime import datetime, timedelta
from dataclasses import replace
import re

_ROBOT_REQUEST = re.compile(r'OMEGA:T5-DemVidageComplet\b', re.I)
_PICK_OK = re.compile(r'OMEGA:T5-DEL-PACK@Ok@(\d+)\b', re.I)
_REMOVE = re.compile(r'supp\. de T5 la boite Id:(\d+)\s+ref:(\S+)', re.I)
_DRAIN_START = re.compile(r'T5v:\s*Une demande de vidage complet', re.I)
_CLEAR = re.compile(r'Suppression de toutes les boites', re.I)
_LIST_END = re.compile(r'envoi en UDP la liste des boites valides sur T5\.\s*(\d+) boite', re.I)
_CREATION = re.compile(r"Cr\S*ation de la boite .*?\bIdA:(\d+)", re.I)
_BOX_RELEVANT = re.compile('|'.join(f'(?:{pattern.pattern})' for pattern in (
    _ROBOT_REQUEST, _PICK_OK, _REMOVE, _DRAIN_START, _CLEAR, _LIST_END, _CREATION))
    + r'|version logiciel VBalpha:', re.I)


def analyze_robot_boxes(line_states, trace_origin=None, absolute_origin=False):
    """Attribue uniquement les blocs complets dont l'origine robot est prouvee."""
    result = {'box_metrics_version': 1, 'rejected_boxes_count': 0, 'robot_picked_boxes_count': 0,
              'unattributed_removed_boxes_count': 0, 'drain_episodes': [], 'box_daily': {}, 'undated_requests': []}
    calendar = TraceCalendar(trace_origin) if trace_origin and not absolute_origin else None
    pending, active = [], None
    picked, versions, seen, requests = set(), {}, set(), set()

    def observation(line, state):
        moment = (trace_origin + timedelta(seconds=state.timestamp) if absolute_origin and trace_origin else
                  calendar.at(state.timestamp) if calendar else None)
        return {'line': line, 'time_str': state.timestamp_str, 'date': moment.date().isoformat() if moment else '',
                'display_time_str': moment.strftime('%d/%m/%Y à %H:%M:%S') if moment else state.timestamp_str}

    def daily(date):
        return result['box_daily'].setdefault(date, {'rejected_boxes_count': 0, 'robot_picked_boxes_count': 0,
                                                   'unattributed_removed_boxes_count': 0, 'pick_examples': []})

    def finish(complete=False):
        nonlocal active
        if active is None:
            return
        active['complete'] = complete
        active['attributed'] = bool(complete and active['request_lines'] and not active['ambiguous'])
        active['box_count'] = len(active['boxes']) if active['attributed'] else None
        key = 'rejected_boxes_count' if active['attributed'] else 'unattributed_removed_boxes_count'
        for box in active['boxes']:
            result[key] += 1
            daily(box['date'])[key] += 1
        result['drain_episodes'].append(active)
        active = None

    for line, text, state in line_states:
        if line in seen:
            continue
        seen.add(line)
        if calendar:
            calendar.observe(state.timestamp)
        clock = ((calendar.at(state.timestamp) - trace_origin).total_seconds() if calendar else state.timestamp)
        if 'version logiciel VBalpha:' in text:
            finish()
            pending, picked, versions = [], set(), {}
        # Une attente ancienne ne prouve pas l'origine d'un vidage ulterieur.
        if pending and not 0 <= clock - pending[0]['time'] <= 120:
            pending = []
        if active and not 0 <= clock - active['last_time'] <= 120:
            finish()
        if not _BOX_RELEVANT.search(text):
            continue
        if _ROBOT_REQUEST.search(text):
            requests.add(line)
            proof = observation(line, state)
            pending.append(dict(proof, time=clock))
            if not proof['date'] and len(result['undated_requests']) < 10:
                result['undated_requests'].append(proof)
        if _DRAIN_START.search(text):
            finish()
            active = dict(observation(line, state), request_lines=[row['line'] for row in pending],
                          boxes=[], block_line=0, end_line=0, last_time=clock, ambiguous=False)
            pending = []
        if _CLEAR.search(text):
            if active is None or active['block_line']:
                finish()
                active = dict(observation(line, state), request_lines=[row['line'] for row in pending], boxes=[], end_line=0,
                              last_time=clock, ambiguous=False)
                pending = []
            active['block_line'] = line
        removal = _REMOVE.search(text)
        if removal:
            box = dict(observation(line, state), id_alpha=int(removal[1]), barcode=removal[2])
            if active and active['block_line']:
                if not any(row['id_alpha'] == box['id_alpha'] for row in active['boxes']):
                    active['boxes'].append(box)
                active['last_time'] = clock
            else:
                result['unattributed_removed_boxes_count'] += 1
                daily(box['date'])['unattributed_removed_boxes_count'] += 1
        ending = _LIST_END.search(text)
        if ending and active and active['block_line']:
            active['end_line'] = line
            finish(complete=int(ending[1]) == 0)
        creation = _CREATION.search(text)
        if creation:
            identity = int(creation[1])
            versions[identity] = versions.get(identity, 0) + 1
        pick = _PICK_OK.search(text)
        if pick:
            identity = int(pick[1])
            key = (identity, versions.get(identity, 0))
            if key not in picked:
                picked.add(key)
                result['robot_picked_boxes_count'] += 1
                proof = dict(observation(line, state), id_alpha=identity)
                day = daily(proof['date'])
                day['robot_picked_boxes_count'] += 1
                if len(day['pick_examples']) < 10:
                    day['pick_examples'].append(proof)
            if active:
                active['ambiguous'] = True
    finish()
    attributed = {line for episode in result['drain_episodes'] if episode['attributed'] for line in episode['request_lines']}
    result['unattributed_request_count'] = len(requests - attributed)
    return result


def attach_robot_box_metrics(metrics, analysis):
    metrics.update(analysis)
    if not metrics.get('daily') and analysis.get('undated_requests'):
        metrics['daily'] = [{'date': '', 'label': 'Dates indisponibles', 'count': metrics['total'],
                             'first_time': '', 'last_time': '', 'examples': [dict(row) for row in analysis['undated_requests']]}]
    by_request = {line: episode for episode in analysis['drain_episodes'] for line in episode['request_lines']}
    for day in metrics.get('daily', []):
        if day.get('observed') is False:
            continue
        counts = analysis['box_daily'].get(day['date'], {})
        for key in ('rejected_boxes_count', 'robot_picked_boxes_count', 'unattributed_removed_boxes_count'):
            day[key] = counts.get(key, 0)
        day['pick_examples'] = counts.get('pick_examples', [])[:10]
        for proof in day['examples']:
            episode = by_request.get(proof['line'])
            proof['box_count'] = episode['box_count'] if episode else None
            proof['box_ids'] = [box['id_alpha'] for box in episode['boxes']] if episode else []
            proof['sources'] = ({'commande robot': proof['line'], 'debut du bloc': episode['block_line'],
                                 **{f"boite IdA:{box['id_alpha']}": box['line'] for box in episode['boxes']},
                                 'fin du bloc': episode['end_line']} if episode else {'commande robot': proof['line']})
            proof['sources'] = {label: line for label, line in proof['sources'].items() if line}
            proof['detail'] = (f"{proof['box_count']} boîte(s) évacuée(s) : " + ', '.join(map(str, proof['box_ids']))
                               if proof['box_count'] is not None else 'Nombre de boîtes évacuées non attribuable.')


def drain_box_text(metrics):
    if not metrics.get('box_metrics_version'):
        return 'Données indisponibles — régénérer le rapport'
    text = (f"{metrics['rejected_boxes_count']} boîte(s) évacuée(s) lors des vidages robot · "
            f"{metrics['robot_picked_boxes_count']} prise(s) confirmée(s) par le robot")
    if metrics.get('unattributed_request_count'):
        text += f" · {metrics['unattributed_request_count']} demande(s) sans bilan complet"
    return text


def drain_box_ratio(metrics):
    if not metrics.get('box_metrics_version'):
        return None
    evacuated = metrics['rejected_boxes_count']
    total = evacuated + metrics['robot_picked_boxes_count']
    return evacuated / total if total else None


def drain_compact_box_text(metrics):
    if not metrics.get('box_metrics_version'):
        return 'Données indisponibles — régénérer le rapport'
    def number(value):
        return f'{value:,}'.replace(',', ' ')
    ratio = drain_box_ratio(metrics)
    ratio_text = f'{ratio:.2%}'.replace('.', ',') + ' évacuées' if ratio is not None else 'Ratio indisponible'
    return (f"{number(metrics['rejected_boxes_count'])} boîtes évacuées · "
            f"{number(metrics['robot_picked_boxes_count'])} prises confirmées · {ratio_text}")


def merge_robot_box_metrics(analyses):
    merged = {'box_metrics_version': 1, 'drain_episodes': [], 'box_daily': {},
              'undated_requests': [proof for row in analyses for proof in row.get('undated_requests', [])][:10]}
    keys = ('rejected_boxes_count', 'robot_picked_boxes_count', 'unattributed_removed_boxes_count')
    for key in keys:
        merged[key] = sum(row[key] for row in analyses)
    merged['unattributed_request_count'] = sum(row.get('unattributed_request_count', 0) for row in analyses)
    for row in analyses:
        merged['drain_episodes'].extend(row['drain_episodes'])
        for date, day in row['box_daily'].items():
            target = merged['box_daily'].setdefault(date, dict.fromkeys(keys, 0))
            for key in keys:
                target[key] += day[key]
            target['pick_examples'] = (target.get('pick_examples', []) + day['pick_examples'])[:10]
    return merged


def read_trace_origin(path):
    date = None
    first = None
    with open(path, encoding='latin-1', errors='replace') as source:
        for index, text in enumerate(source):
            if index >= 256:
                break
            if 'OUVERTURE DE LA TRACE' in text or re.search(r'cr\S*ation de la trace', text, re.I):
                match = re.search(r'\ble\s+(\d{2}/\d{2}/\d{4})', text)
                if match:
                    try:
                        date = datetime.strptime(match[1], '%d/%m/%Y')
                    except ValueError:
                        pass
            match = re.match(r'\s*\*?\s*(\d+)\|(\d{2}):(\d{2}):(\d{2})\.(\d+)', text)
            if match and first is None:
                first = tuple(map(int, match.groups()))
            if date is not None and first is not None:
                day, hour, minute, second, fraction = first
                if date.day != day:
                    return None
                return date + timedelta(hours=hour, minutes=minute, seconds=second, milliseconds=fraction * 100)
    return None


class TraceCalendar:
    """Reconstitue les mois perdus dans les timestamps relatifs du parser."""
    def __init__(self, origin):
        self.origin = origin
        self.month = origin.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        self.base = origin.day * 86400 + (origin - origin.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
        self.previous_day = origin.day
        self.previous_timestamp = None
        self._moment = None

    def observe(self, timestamp):
        if timestamp == self.previous_timestamp:
            return
        day, _ = divmod(round((self.base + timestamp) * 10), 864000)
        if day < self.previous_day:
            self.month = (self.month.replace(day=28) + timedelta(days=4)).replace(day=1)
        self.previous_day = day
        self.previous_timestamp = timestamp
        self._moment = None

    def at(self, timestamp):
        self.observe(timestamp)
        if self._moment is None:
            day, ticks = divmod(round((self.base + timestamp) * 10), 864000)
            self._moment = self.month + timedelta(days=day - 1, milliseconds=ticks * 100)
        return self._moment


def format_trace_duration(seconds):
    hours, seconds = divmod(max(0, int(seconds)), 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours} h {minutes:02d} min {seconds:02d} s'


def trace_period(start, end):
    seconds = (end - start).total_seconds()
    return {'available': True, 'start': start.strftime('%d/%m/%Y à %H:%M:%S'),
            'end': end.strftime('%d/%m/%Y à %H:%M:%S'),
            'days': (end.date() - start.date()).days + 1,
            'duration_seconds': seconds, 'duration': format_trace_duration(seconds)}


def date_drain_metrics(metrics, dated, start, end):
    metrics['trace'] = trace_period(start, end)
    months = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
              'août', 'septembre', 'octobre', 'novembre', 'décembre')
    days = {}
    date = start.date()
    while date <= end.date():
        key = date.isoformat()
        days[key] = {'date': key, 'label': f'{date.day} {months[date.month - 1]} {date.year}',
                     'count': 0, 'first_time': '', 'last_time': '', 'examples': []}
        date += timedelta(days=1)
    for line, date in dated:
        row = days[date.date().isoformat()]
        time = date.strftime('%H:%M:%S')
        if not row['count']:
            row['first_time'] = time
        row['last_time'] = time
        row['count'] += 1
        if len(row['examples']) < 10:
            row['examples'].append({'line': line, 'time_str': time,
                                    'display_time_str': date.strftime('%d/%m/%Y à %H:%M:%S')})
    metrics['daily'] = list(days.values())
    metrics['requests_start'] = dated[0][1].strftime('%d/%m/%Y à %H:%M:%S')
    metrics['requests_end'] = dated[-1][1].strftime('%d/%m/%Y à %H:%M:%S')


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
    result['critical'] = drain_is_critical(result)
    result['reinforced'] = False
    return result


def drain_metric_text(metrics):
    total = metrics.get('total', 0)
    days = metrics.get('trace', {}).get('days')
    return (f"{total} demande{'s' if total != 1 else ''} sur {days} jour{'s' if days != 1 else ''} de trace"
            if days else f"{total} demande{'s' if total != 1 else ''} · Dates indisponibles")


def drain_period_text(metrics):
    period = metrics.get('trace', {})
    return (f"Trace analysée du {period['start']} au {period['end']}" if period.get('available') else
            'Dates indisponibles ; rechargez la trace pour retrouver le calendrier.')


def drain_is_critical(metrics):
    return int((metrics or {}).get('day', {}).get('count', 0)) >= 10


def normalize_robot_incidents(incidents):
    """Recalcule les anciens caches sans reutiliser leurs indicateurs de criticite."""
    result = []
    for incident in incidents:
        if incident.code == 'DemVidageComplet':
            metrics = dict(incident.metrics)
            critical = drain_is_critical(metrics)
            metrics.update(critical=critical, reinforced=False)
            incident = replace(incident, metrics=metrics, severity='error' if critical else 'info',
                               summary=drain_metric_text(metrics))
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
