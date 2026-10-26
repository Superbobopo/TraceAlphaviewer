"""Instabilite C5 et cycles non mesures, sans modifier les populations camera."""
from __future__ import annotations

from collections import deque
import re

from Models.trace_calendar import trace_calendar, display_time, format_observed_time
from Models.robot_drain import TraceCalendar

_C5 = re.compile(r'\btEA-T3:.*?\bC5:([01])\b')
_PROGRESS = re.compile(r'le transfert \(EA->T3\) est termin', re.I)
_RESTART = re.compile(r'version logiciel VBalpha:', re.I)
_FINISH = re.compile(r'tT3/T4: transfert T3->T4 termin.*?longueur=([\d.,]+) mm.*?idB=(\d+)', re.I)
_NO_C6 = re.compile(r"PAS DE BOITE MESURE sur C6.*?idB=(\d+)", re.I)
_CREATE = re.compile(r"BdD: Cr\S*ation de la boite .*?IdA:(\d+)", re.I)
_ADD = re.compile(r'AjoutBtT5\.idA(\d+)\.idB(\d+)', re.I)
_MEASURE = re.compile(r'MAJ \(APRES-MESURE-LARG\).*?IdA:(\d+)', re.I)
_DELETE_REASON = re.compile(r'Suppr\. dern\. boite charg\S* car largeur lue sur T5 < 2\s*mm \(et C9=0\)', re.I)
_DELETE = re.compile(r'Suppr\. derni\S* boite transf\S*.*?IdBdD:(\d+) IdT5:(\d+)', re.I)
_VIRTUAL = re.compile(r'ajout boite virtuelle sur T3\s+(\S+)\s+(\S+)', re.I)
_C6 = re.compile(r'\bC6:1\b')
_TIME = re.compile(r'\d+\|\d{2}:\d{2}:\d{2}(?:\.\d+)?')
_CYCLE_RELEVANT = re.compile(
    r'version logiciel VBalpha:|T3->T4|C6|BdD:|AjoutBtT5|MAJ|Suppr\.|boite virtuelle sur T3', re.I)


def c5_metric_text(metrics):
    return (f"{metrics['episode_count']} épisode(s) · {metrics['transitions']} bascule(s) C5 · "
            f"{metrics['suspect_cycle_count']} boîte(s) fantôme(s) probable(s) · "
            f"{metrics['virtual_creation_count']} création(s) virtuelle(s) explicite(s) · "
            f"{metrics['incomplete_cycle_count']} association(s) incomplète(s)")


def merge_c5_metrics(rows):
    keys = ('episode_count', 'transitions', 'suspect_cycle_count',
            'virtual_creation_count', 'incomplete_cycle_count')
    return {'c5_metrics_version': 1, **{key: sum(row.get(key, 0) for row in rows) for key in keys},
            'episodes': [episode for row in rows for episode in row.get('episodes', [])]}


def analyze_c5(line_states, trace_origin=None):
    calendar = trace_calendar(line_states)

    def observations():
        dated = TraceCalendar(trace_origin) if trace_origin else None
        for line, text, state in line_states:
            match = _TIME.search(text)
            raw = match[0] if match else state.timestamp_str
            moment = dated.at(state.timestamp) if dated else None
            obs = {'line': line, 'time': (moment - trace_origin).total_seconds() if moment else state.timestamp,
                   'time_str': format_observed_time(moment) if moment else display_time(calendar, line, raw)}
            yield line, text, state, obs

    episodes, window = [], deque()
    current = previous = last_input = last_change = None
    context = 0

    def close(reason, boundary=None):
        nonlocal current, previous, last_change
        if current:
            current['end_reason'] = reason
            if boundary:
                current['boundary'] = boundary
            episodes.append(current)
        current = previous = last_change = None
        window.clear()

    for line, text, state, obs in observations():
        if last_input and obs['time'] - last_input['time'] > 120:
            close('Interruption des observations supérieure à deux minutes', last_input)
            context += 1
        last_input = obs
        if _RESTART.search(text):
            close('Redémarrage logiciel', obs)
            context += 1
            continue
        if _PROGRESS.search(text):
            close('Transfert EA→T3 confirmé ; état de C5 à contrôler', obs)
            continue
        match = _C5.search(text)
        if not match:
            continue
        if current and last_change and obs['time'] - last_change['time'] >= 300:
            close('Cinq minutes observées sans bascule ; réparation non attestée', obs)
        obs = dict(obs, value=int(match[1]))
        if previous and previous['value'] != obs['value']:
            window.append((previous, obs))
            last_change = obs
            while window and obs['time'] - window[0][1]['time'] > 300 + 1e-6:
                window.popleft()
            if current:
                current['transitions'] += 1
            elif len(window) >= 10:
                current = {'first': window[0][0], 'last': obs, 'context': context,
                           'transitions': len(window), 'alternations': list(window)[:2]}
        previous = obs
        if current:
            current['last'] = obs
    close('Fin de trace ; résolution non observée')
    if not episodes:
        return None

    # Les identites explicites lient les etapes ; le CIP ne sert jamais de cle.
    cycles, virtuals = [], []
    by_idb, by_ida = {}, {}
    last_input = creation = reason = t4_cycle = None
    last_created_id = 0
    context = 0
    for line, text, state, obs in observations():
        if last_input and obs['time'] - last_input['time'] > 120:
            by_idb.clear()
            by_ida.clear()
            creation = reason = t4_cycle = None
            last_created_id = 0
            context += 1
        last_input = obs
        if not _CYCLE_RELEVANT.search(text):
            continue
        if _RESTART.search(text):
            by_idb.clear()
            by_ida.clear()
            creation = reason = t4_cycle = None
            last_created_id = 0
            context += 1
        last_input = obs
        match = _VIRTUAL.search(text)
        if match:
            virtuals.append(dict(obs, reference=match[1], weight=match[2], context=context))
        match = _FINISH.search(text)
        if match:
            id_b = int(match[2])
            old_cycle = by_idb.get(id_b)
            reused_pending = bool(old_cycle and not old_cycle['id_alpha'] and not old_cycle.get('end_line'))
            if reused_pending:
                old_cycle['ambiguous'] = True
            t4_cycle = dict(obs, id_b=id_b, id_alpha=0, context=context,
                            length=float(match[1].replace(',', '.')), missing_c6=False,
                            ambiguous=reused_pending, measured=False, complete=False,
                            sources={'transfert T3→T4': line})
            by_idb[id_b] = t4_cycle
            cycles.append(t4_cycle)
        match = _NO_C6.search(text)
        if match:
            cycle = by_idb.get(int(match[1]))
            if cycle and obs['time'] - cycle['time'] <= 120:
                cycle['missing_c6'] = True
                cycle['sources']['absence signalée sur C6'] = line
        if t4_cycle and not t4_cycle['id_alpha'] and _C6.search(text):
            t4_cycle['sources'].setdefault('impulsion C6 observée', line)
        match = _CREATE.search(text)
        if match:
            id_a = int(match[1])
            old_cycle = by_ida.pop(id_a, None)
            if old_cycle:
                old_cycle['ambiguous'] = True
            creation = dict(obs, id_alpha=id_a)
            last_created_id = id_a
        match = _ADD.search(text)
        if match:
            id_a, id_b = map(int, match.groups())
            cycle = by_idb.get(id_b)
            if cycle and id_a in by_ida:
                cycle['ambiguous'] = True
                by_ida[id_a]['ambiguous'] = True
            if (cycle and creation and creation['id_alpha'] == id_a
                    and 0 <= obs['time'] - creation['time'] <= 2 and obs['time'] - cycle['time'] <= 120):
                if cycle['id_alpha'] or id_a in by_ida:
                    cycle['ambiguous'] = True
                else:
                    cycle['id_alpha'] = id_a
                    cycle['sources'].update({'création BdD': creation['line'], 'liaison IdA/IdB': line})
                    by_ida[id_a] = cycle
            creation = None
        match = _MEASURE.search(text)
        if match and int(match[1]) in by_ida:
            by_ida[int(match[1])]['measured'] = True
        if _DELETE_REASON.search(text):
            reason = dict(obs, id_alpha=creation['id_alpha'] if creation else last_created_id)
        match = _DELETE.search(text)
        if match:
            id_a, id_t5 = map(int, match.groups())
            cycle = by_ida.pop(id_a, None)
            if cycle:
                cycle['sources']['suppression IdA'] = line
                cycle['end_line'], cycle['end_time'] = line, obs['time']
                if (reason and reason['id_alpha'] == id_a and 0 <= line - reason['line'] <= 10
                        and 0 <= obs['time'] - reason['time'] <= 2):
                    cycle['sources']['largeur < 2 mm et C9=0'] = reason['line']
                    cycle['complete'] = bool(id_a == id_t5 and cycle['length'] == 0
                        and cycle['missing_c6'] and not cycle['ambiguous'] and not cycle['measured'])
            reason = None

    metrics = {'c5_metrics_version': 1, 'episode_count': len(episodes), 'transitions': 0,
               'suspect_cycle_count': 0, 'virtual_creation_count': 0, 'incomplete_cycle_count': 0,
               'episodes': []}
    examples = []
    for index, episode in enumerate(episodes, 1):
        first, last = episode['first'], episode['last']
        boundary = episode.get('boundary')
        # Une borne de contexte n'est pas une preuve de reprise ni une boite du nouvel episode.
        selected = [cycle for cycle in cycles if cycle['context'] == episode['context']
                    and first['line'] <= cycle['line'] <= last['line'] and cycle['length'] == 0]
        virtual = [item for item in virtuals if item['context'] == episode['context']
                   and first['line'] <= item['line'] <= last['line']]
        complete = sum(cycle['complete'] for cycle in selected)
        incomplete = len(selected) - complete
        sources = {'début': first['line'], 'dernière observation C5': last['line']}
        for number, (before, after) in enumerate(episode['alternations'], 1):
            sources[f'bascule {number} avant'] = before['line']
            sources[f'bascule {number} après'] = after['line']
        if boundary:
            sources['fin du contexte'] = boundary['line']
        detail = (f"Épisode {index} du {first['time_str']} au {last['time_str']} : "
                  f"{episode['transitions']} bascule(s) C5, {complete} boîte(s) fantôme(s) probable(s), "
                  f"{len(virtual)} création(s) virtuelle(s) explicite(s), {incomplete} association(s) incomplète(s). "
                  f"{episode['end_reason']}. L'absence physique et une panne de C5 ne sont pas prouvées seules.")
        item = {'first_line': first['line'], 'last_line': last['line'], 'start_time': first['time'],
                'end_time': last['time'], 'start_time_str': first['time_str'], 'end_time_str': last['time_str'],
                'duration_seconds': max(0, last['time'] - first['time']), 'transitions': episode['transitions'],
                'suspect_cycle_count': complete, 'virtual_creation_count': len(virtual),
                'incomplete_cycle_count': incomplete, 'cycles': selected, 'virtual_creations': virtual,
                'sources': sources, 'detail': detail, 'end_reason': episode['end_reason']}
        metrics['episodes'].append(item)
        for key in ('transitions', 'suspect_cycle_count', 'virtual_creation_count', 'incomplete_cycle_count'):
            metrics[key] += item[key]
        proofs = [{'line': first['line'], 'time_str': first['time_str'], 'box': '', 'barcode': '',
                   'detail': detail, 'sources': sources, 'episode': index}]
        for cycle in sorted(selected, key=lambda row: (not row['complete'], row['line'])):
            label = 'Boîte fantôme probable' if cycle['complete'] else 'Cycle non mesuré : association incomplète'
            proofs.append({'line': cycle['line'], 'time_str': cycle['time_str'],
                           'box': f"IdB:{cycle['id_b']} · IdA:{cycle['id_alpha'] or '?'}", 'barcode': '',
                           'detail': label + ' ; longueur nulle, voir les observations C6/T5.',
                           'sources': cycle['sources'], 'episode': index})
        for virtual_box in virtual:
            proofs.append({'line': virtual_box['line'], 'time_str': virtual_box['time_str'],
                           'box': '', 'barcode': virtual_box['reference'],
                           'detail': f"Création virtuelle explicite après pesée : {virtual_box['weight']}. Cause distincte à contrôler.",
                           'sources': {'création virtuelle': virtual_box['line']}, 'episode': index})
        for proof in proofs:
            proof['display_time_str'] = proof['time_str']
        # Les creations virtuelles restent accessibles meme si de nombreux cycles precedent.
        examples.extend((proofs[:1] + proofs[-len(virtual):] + proofs[1:-len(virtual)]
                         if virtual else proofs)[:10])
    return metrics, examples
