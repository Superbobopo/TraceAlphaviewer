"""Episodes C2/C3 etablis uniquement depuis les observations brutes de la trace."""
from __future__ import annotations

import re
from array import array
from functools import lru_cache
from Models.trace_calendar import trace_calendar, display_time, TraceLines

_TIME = re.compile(r'\d+\|\d{2}:\d{2}:\d{2}(?:\.\d+)?')
_SENSOR = re.compile(r'\b(C[234569]):([01])\b')
_T2 = re.compile(r'\bT2:\s', re.I)
_PROGRESS = re.compile(r'\bT2:\s*(?:BOITE-LOAD|TRANSFERT-TERMINE|Transfert de T2->EA termin)', re.I)
_RELAUNCH = re.compile(r'relance le vidage machine', re.I)
_INIT = re.compile(r'InitMachine:\s*demande initialisation de T2\b', re.I)
_RESTART = re.compile(r'version logiciel VBalpha:', re.I)
_DRAIN_END = re.compile(r'Vid:\s*Fin de vidage de la machine', re.I)
_SENSOR_BITS = {key: 1 << index for index, key in enumerate(('C2', 'C3', 'C4', 'C5', 'C6', 'C9'))}
_T2_FLAG, _PROGRESS_FLAG, _RELAUNCH_FLAG = 1 << 12, 1 << 13, 1 << 14
_INIT_FLAG, _DRAIN_FLAG, _RESTART_FLAG, _CAPTEURS_FLAG = 1 << 15, 1 << 16, 1 << 17, 1 << 18


def _parse_signal_facts(text):
    lower = text.lower()
    bits = 0
    if 'C2:' in text or 'C3:' in text or 'C4:' in text:
        for key, value in _SENSOR.findall(text):
            bit = _SENSOR_BITS[key]
            bits |= bit
            bits = bits | (bit << 6) if value == '1' else bits & ~(bit << 6)
    if 't2:' in lower:
        if _T2.search(text):
            bits |= _T2_FLAG
        if _PROGRESS.search(text):
            bits |= _PROGRESS_FLAG
    if 'vidage' in lower and _RELAUNCH.search(text):
        bits |= _RELAUNCH_FLAG
    if 'initmachine:' in lower and _INIT.search(text):
        bits |= _INIT_FLAG
    if 'vid:' in lower and _DRAIN_END.search(text):
        bits |= _DRAIN_FLAG
    if ('version logiciel' in lower or not text.isascii()) and _RESTART.search(text):
        bits |= _RESTART_FLAG
    if 'Capteurs ' in text:
        bits |= _CAPTEURS_FLAG
    return bits


def _signal_facts(line_states):
    cached = getattr(line_states, '_signal_facts', None)
    if cached is not None and len(cached) == len(line_states):
        return cached
    parse = lru_cache(maxsize=2048)(_parse_signal_facts)
    result = array('I', (parse(text) for _, text, _ in line_states))
    if isinstance(line_states, TraceLines):
        line_states._signal_facts = result
    return result


def c2_metric_text(metrics):
    return signal_metric_text(metrics, 'C2')


def signal_metric_text(metrics, sensor):
    return (f"{metrics['episode_count']} épisode(s) · {metrics['transitions']} bascule(s) {sensor} · "
            f"{metrics['drain_relaunches']} relance(s) de vidage avec {sensor} seul actif · "
            f"{metrics['initialization_requests']} demande(s) d'initialisation T2")


def analyze_c2(line_states):
    return _analyze_signal(line_states, 'C2')


def analyze_c3(line_states):
    return _analyze_signal(line_states, 'C3')


def _analyze_signal(line_states, sensor):
    idle_sensors = ('C3', 'C4') if sensor == 'C2' else ('C2', 'C4')
    complete_state = ' '.join(f'{key}:{int(key == sensor)}' for key in ('C2', 'C3', 'C4', 'C5', 'C6', 'C9'))
    calendar = trace_calendar(line_states)
    episodes = []
    current = None
    pending = None

    def observation(line, text, state):
        match = _TIME.search(text)
        raw_time = match[0] if match else state.timestamp_str
        dated = display_time(calendar, line, raw_time)
        if dated != raw_time and '.' in raw_time:
            dated += '.' + raw_time.rsplit('.', 1)[1]
        return {'line': line, 'time': state.timestamp, 'raw_time': raw_time, 'display_time': dated}

    def open_episode(obs):
        return {'first': obs, 'last': obs, 'last_t2': None, 'first_t2': None,
                'transitions': 0, 'alternations': [], 'blocks': [], 'initializations': [],
                'drain_end': None, 'recovery': None, 'end_reason': ''}

    def close_episode(reason, recovery=None, boundary=None):
        nonlocal current
        if current is None:
            return
        current['end_reason'] = reason
        current['recovery'] = recovery
        if boundary:
            current['boundary'] = boundary
        first, last = current['first_t2'], current['last_t2']
        unstable = bool(first and last and current['transitions'] >= 10
                        and last['time'] - first['time'] >= 300)
        current['unstable'] = unstable
        if unstable or current['blocks']:
            episodes.append(current)
        current = None

    idle_mask = sum(_SENSOR_BITS[key] << 6 for key in idle_sensors)
    for (line, text, state), facts in zip(line_states, _signal_facts(line_states)):
        if current and state.timestamp - current['last']['time'] > 120:
            close_episode('Interruption des observations supérieure à deux minutes')
        if pending and (line - pending['line'] > 3 or state.timestamp - pending['time'] > 2):
            pending = None
        if facts & _RESTART_FLAG:
            close_episode('Redémarrage logiciel')
            pending = None
            continue
        idle_active = bool(facts & idle_mask)
        progress = bool(facts & _PROGRESS_FLAG)
        t2 = bool(facts & _T2_FLAG)
        relaunch = bool(facts & _RELAUNCH_FLAG)
        initialization = bool(facts & _INIT_FLAG)
        drain_end = bool(facts & _DRAIN_FLAG)
        complete = facts & 7 == 7
        if not (idle_active or progress or relaunch or (facts & _CAPTEURS_FLAG and pending)
                or (t2 and complete) or (current and (initialization or drain_end))):
            continue
        sensors = {key: int(bool(facts & (bit << 6))) for key, bit in _SENSOR_BITS.items() if facts & bit}
        obs = observation(line, text, state)
        if idle_active:
            if sensor == 'C3' and sensors.get('C4') != 1 and not progress:
                close_episode(f"Activation de C2 à {obs['display_time']} : contexte de surveillance terminé, "
                              "reprise T2 non attestée", boundary=obs)
            else:
                close_episode(f"Activation {'/'.join(idle_sensors)} : progression observée", obs)
        elif progress:
            close_episode('Progression T2 confirmée', obs)
        if relaunch:
            pending = obs
        if 'Capteurs ' in text and pending and 0 < line - pending['line'] <= 3:
            if set(sensors) == {'C2', 'C3', 'C4', 'C5', 'C6', 'C9'}:
                if sensors[sensor] == 1 and not any(sensors[key] for key in sensors if key != sensor):
                    if current is None:
                        current = open_episode(pending)
                    current['blocks'].append({'request': pending, 'state': obs})
                    current['last'] = obs
                pending = None
        if t2 and complete:
            if idle_active or progress:
                continue
            if current is None:
                current = open_episode(obs)
            obs = dict(obs, value=sensors[sensor])
            previous = current['last_t2']
            if previous and previous['value'] != obs['value']:
                current['transitions'] += 1
                if len(current['alternations']) < 2:
                    current['alternations'].append((previous, obs))
            current['first_t2'] = current['first_t2'] or obs
            current['last_t2'] = obs
            current['last'] = obs
        if current and initialization:
            current['initializations'].append(obs)
        if current and drain_end:
            current['drain_end'] = obs
    close_episode('Fin de trace : résolution non observée')
    if not episodes:
        return None

    metrics = {'episode_count': len(episodes), 'transitions': sum(e['transitions'] for e in episodes),
               'drain_relaunches': sum(len(e['blocks']) for e in episodes),
               'initialization_requests': sum(len(e['initializations']) for e in episodes),
               'unstable_episodes': sum(e['unstable'] for e in episodes),
               'blocked_episodes': sum(bool(e['blocks']) for e in episodes), 'episodes': []}
    examples = []
    for index, episode in enumerate(episodes, 1):
        first, last = episode['first'], episode['last']
        duration = round(last['time'] - first['time'], 3)
        blocks = episode['blocks']
        recovery = episode['recovery']
        sources = {'début': first['line'], 'dernière_observation': last['line']}
        for number, (before, after) in enumerate(episode['alternations'], 1):
            sources[f'bascule_{number}_avant'] = before['line']
            sources[f'bascule_{number}_après'] = after['line']
        if blocks:
            sources.update(relance=blocks[0]['request']['line'], état_capteurs=blocks[0]['state']['line'],
                           dernière_relance=blocks[-1]['request']['line'])
        if episode['initializations']:
            sources['initialisation_T2'] = episode['initializations'][0]['line']
        if episode['drain_end']:
            sources['fin_vidage'] = episode['drain_end']['line']
        if recovery:
            sources['reprise'] = recovery['line']
        if episode.get('boundary'):
            sources['fin_contexte'] = episode['boundary']['line']
        detail = (f"Épisode {index} du {first['display_time']} au {last['display_time']} "
                  f"({duration:g} s) : {episode['transitions']} bascule(s) {sensor}, "
                  f"{len(blocks)} relance(s) de vidage, {len(episode['initializations'])} "
                  "demande(s) d'initialisation T2. ")
        if episode['unstable']:
            detail += f"Instabilité sans progression T2 attestée, {' et '.join(idle_sensors)} à zéro. "
        if blocks:
            detail += f"Blocage confirmé : relance explicite suivie de {complete_state}. "
        if episode['drain_end']:
            detail += f"Fin de vidage observée à {episode['drain_end']['display_time']}. "
        detail += (f"Reprise observée à {recovery['display_time']} ; état du capteur à contrôler."
                   if recovery else episode['end_reason'] + '.')
        item = {'first_line': first['line'], 'last_line': last['line'],
                'start_time': first['time'], 'end_time': last['time'],
                'start_time_str': first['display_time'], 'end_time_str': last['display_time'],
                'duration_seconds': duration, 'transitions': episode['transitions'],
                'drain_relaunches': len(blocks), 'initialization_requests': len(episode['initializations']),
                'unstable': episode['unstable'], 'blocked': bool(blocks),
                'end_reason': episode['end_reason'], 'recovery': recovery,
                'blocks': blocks, 'sources': sources, 'detail': detail}
        if episode.get('boundary'):
            item['boundary'] = episode['boundary']
        metrics['episodes'].append(item)
        target = blocks[0]['request'] if blocks else first
        examples.append({'line': target['line'], 'time_str': target['display_time'],
                         'display_time_str': target['display_time'], 'box': '', 'barcode': '',
                         'detail': detail, 'sources': sources, 'episode': index})
    # Les preuves bloquantes et les longues sequences restent visibles dans la limite d'export.
    selected = sorted(range(len(episodes)), key=lambda i: (
        not bool(episodes[i]['blocks']), -(episodes[i]['last']['time'] - episodes[i]['first']['time'])))[:10]
    return metrics, [examples[i] for i in sorted(selected)]
