"""Instabilite C5 et cycles non mesures, sans modifier les populations camera."""
from __future__ import annotations

from collections import deque
from functools import lru_cache
import re

from Models.trace_calendar import observation_clock, TimedObservation

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
_CYCLE_RELEVANT = re.compile(
    r'version logiciel VBalpha:|T3->T4|C6|BdD:|AjoutBtT5|MAJ|Suppr\.|boite virtuelle sur T3', re.I)
_TRANSFER_STATE = re.compile(r'tT3/T4:\s+(\S+)\s+eT4:(-?\d+)')
_TRANSFER_REQUEST = re.compile(r"tT3/T4: demande le transfert de T3->T4.*?'([^']*)'", re.I)
_TRANSFER_DONE = re.compile(r'tT3/T4: transfert T3->T4 termin', re.I)
_REFUSED = re.compile(r'tT3/T4:.*?\beT4:-47\b', re.I)
_IDENTITY = re.compile(r'idCB2:.*?Nboite\s*=\s*(\d+)', re.I)
_PRODUCT = re.compile(r'idCB2:.*?R.f:([^ ]+)')
_INITIALIZE = re.compile(r'InitMachine: demande initialisation de (T[34])\b|SendCde:.*?\b(T[34])I\b', re.I)
_EJECTION = re.compile(r'tEA-T3: Demande .jection', re.I)
_LOOKUP = re.compile(r'Rech\. infos existantes BdD pour (\S+)', re.I)
_PRODUCT_INFO = re.compile(r'^\s*(?:\d+\|\d{2}:\d{2}:\d{2}\.\d+\s+)?-->\s+(.+?)\s+\d+x\d+x\d+\b')
_SIGNAL_TOKENS = ('version logiciel', 'ea->t3', 'tea-t3:')
_BLOCKED_TOKENS = ('version logiciel', 'tea-t3:', 'ea->t3', 'tt3/t4:', 't3->t4', 'idcb2:',
                   'initmachine:', 'sendcde:', 'rech. infos existantes bdd pour', '-->')
_CYCLE_TOKENS = ('version logiciel', 't3->t4', 'c6', 'bdd:', 'ajoutbtt5', 'maj', 'suppr.', 'boite virtuelle sur t3')


def c5_is_critical(metrics):
    return bool(metrics.get('suspect_cycle_count') or metrics.get('blocked_transfer_count'))


def _blocked_transfers(observations, signal_episodes):
    """L'etat logiciel porte le blocage, independamment du retour d'un eT positif."""
    blocks, active = [], None
    request = identity = product = arrival = ejection = lookup = None
    context = 0
    previous_line = -1
    last_initialization = None

    def close(reason, boundary=None, recovered=False):
        nonlocal active, last_initialization
        if active is None:
            return
        duration = max(0, active['end_time'] - active['start_time'])
        unstable = any(episode['context'] == active['context'] and any(
            start <= active['refusal_time'] <= end for start, end in episode.get('instability_windows', []))
            for episode in signal_episodes) if active['refusal_time'] is not None else False
        if duration >= 120 or unstable:
            active.update(duration_seconds=duration, instability_confirmed=unstable,
                          end_reason=reason, recovered=recovered)
            if boundary:
                active['sources']['reprise confirmee' if recovered else 'fin du contexte'] = boundary['line']
            active['sources']['derniere erreur observee'] = active['last_line']
            blocks.append(active)
        active = None
        last_initialization = None

    for line, text, state, obs in observations():
        if line <= previous_line:
            continue
        previous_line = line
        lower = obs.lower
        unicode_case = not text.isascii()
        if obs.previous is not None:
            close('Interruption des observations ; reprise non confirmée', obs.previous)
            context += 1
            request = identity = product = arrival = ejection = lookup = None
        if ('version logiciel' in lower or unicode_case) and _RESTART.search(text):
            close('Redémarrage logiciel ; reprise non confirmée', obs)
            context += 1
            request = identity = product = arrival = ejection = lookup = None
            continue
        if ('tea-t3:' in lower or unicode_case) and _EJECTION.search(text):
            ejection = obs
        match = _LOOKUP.search(text) if 'rech.' in lower or unicode_case else None
        if match:
            lookup = dict(obs, barcode=match[1], name='')
        match = _PRODUCT_INFO.search(text) if '-->' in text else None
        if match and lookup and 0 <= obs['time'] - lookup['time'] <= 2:
            lookup.update(name=match[1], source_line=line)
        if ('ea->t3' in lower or unicode_case) and _PROGRESS.search(text):
            # Un nouvel arrivant ne remplace pas l'identite du transfert deja bloque.
            arrival = dict(obs, ejection_line=ejection['line'] if ejection and
                           0 <= obs['time'] - ejection['time'] <= 120 else 0)
            identity = product = ejection = None
        match = _PRODUCT.search(text) if 'idcb2:' in lower or unicode_case else None
        if match:
            name = lookup.get('name', '') if lookup and lookup['barcode'] == match[1] and \
                0 <= obs['time'] - lookup['time'] <= 2 else ''
            product = dict(obs, barcode=match[1], name=name)
        match = _IDENTITY.search(text) if 'idcb2:' in lower or unicode_case else None
        if match:
            identity = dict(obs, id_b=int(match[1]), product=product)
        transfer_line = 'tt3/t4:' in lower or unicode_case
        match = _TRANSFER_REQUEST.search(text) if transfer_line else None
        if match:
            request = dict(obs, reference=match[1], identity=identity, arrival=arrival)
            if active is not None:
                active['sources'].setdefault('nouvelle demande sans reprise prouvee', line)
        if transfer_line and _TRANSFER_DONE.search(text):
            close('Transfert T3→T4 explicitement terminé', obs, recovered=True)
            request = identity = product = arrival = None
            continue
        snapshot = _TRANSFER_STATE.search(text) if transfer_line else None
        refused = _REFUSED.search(text) if transfer_line else None
        in_error = bool(snapshot and snapshot[1].rstrip(',') == 'ERREUR-TRSF-T3-T4')
        if in_error or refused:
            if active is None:
                sources = {'premiere erreur T3 vers T4': line}
                candidate = request if request and 0 <= obs['time'] - request['time'] <= 120 else None
                linked = candidate.get('identity') if candidate else None
                linked_product = linked.get('product') if linked else None
                if (linked and not (0 <= candidate['time'] - linked['time'] <= 120 and
                        linked_product and linked['time'] - linked_product['time'] <= 120 and
                        linked_product['barcode'] == candidate['reference'])):
                    linked = None
                if candidate:
                    sources['demande T3 vers T4'] = candidate['line']
                    if candidate['arrival'] and 0 <= candidate['time'] - candidate['arrival']['time'] <= 120:
                        sources['arrivee EA vers T3'] = candidate['arrival']['line']
                        if candidate['arrival']['ejection_line']:
                            sources['demande ejection EA'] = candidate['arrival']['ejection_line']
                if linked:
                    sources.update(identification_CB2=linked_product['line'], identite_IdB=linked['line'])
                active = dict(first_line=line, last_line=line, start_time=obs['time'], end_time=obs['time'],
                    start_time_str=obs['time_str'], end_time_str=obs['time_str'], context=context,
                    refusal_time=None, refusal_count=0, initialization_count=0, sources=sources,
                    id_b=linked['id_b'] if linked else 0,
                    barcode=linked_product['barcode'] if linked else '', name=linked_product['name'] if linked else '',
                    kind='blocked_transfer',
                    transitions=0, suspect_cycle_count=0, virtual_creation_count=0, incomplete_cycle_count=0,
                    cycles=[], virtual_creations=[])
            active.update(last_line=line, end_time=obs['time'], end_time_str=obs['time_str'])
            if refused and active['refusal_time'] is None:
                active['refusal_time'] = obs['time']
                active['refusal_count'] = 1
                active['sources']['refus eT4 moins 47'] = line
            if snapshot and int(snapshot[2]) >= 0:
                active['sources'].setdefault('code moteur positif sans reprise', line)
        elif snapshot and active:
            close("Sortie de l'état d'erreur ; reprise non confirmée", obs)
        initialization = (_INITIALIZE.search(text) if active and (
            'initmachine:' in lower or 'sendcde:' in lower or unicode_case) else None)
        if initialization:
            belt = initialization[1] or initialization[2]
            command = bool(initialization[2])
            paired_request = (command and last_initialization and last_initialization[0] == belt
                              and not last_initialization[1] and 0 <= obs['time'] - last_initialization[2] <= 2)
            if not paired_request:
                active['initialization_count'] += 1
            last_initialization = (belt, command, obs['time'])
            active['sources'].setdefault('initialisation sans reprise prouvee', line)
    close('Fin de fichier ; reprise non confirmée')
    for block in blocks:
        block['detail'] = (
            f"Transfert T3→T4 bloqué du {block['start_time_str']} au {block['end_time_str']} : "
            f"{block['duration_seconds']:g} s observées, {block['refusal_count']} refus -47, "
            f"{block['initialization_count']} initialisation(s). "
            + ('Instabilité C5 associée. ' if block['instability_confirmed'] else 'Instabilité C5 non établie. ')
            + (f"Produit identifié CB2 : {block['name']} (IdB:{block['id_b']}). " if block['name'] else '')
            + block['end_reason'] + '. La présence prolongée de la même boîte reste une hypothèse.')
    return blocks


def c5_metric_text(metrics):
    if metrics.get('blocked_transfer_count'):
        count = metrics['blocked_transfer_count']
        minutes = int(metrics.get('blocked_duration_seconds', 0) // 60)
        blocks = [row for row in metrics.get('episodes', []) if row.get('kind') == 'blocked_transfer']
        recovered = blocks and all(row.get('recovered') for row in blocks)
        return (f"{count} transfert{'s' if count > 1 else ''} T3→T4 bloqué{'s' if count > 1 else ''} · "
                f"{minutes // 60} h {minutes % 60:02d} observées · "
                + ('reprise confirmée' if recovered else 'reprise non confirmée'))
    legacy = (' · Blocages T3→T4 non évalués : rechargez la trace et régénérez le rapport'
              if metrics.get('c5_metrics_version', 1) < 2 else '')
    return (f"{metrics.get('signal_episode_count', metrics['episode_count'])} épisode(s) de signal · {metrics['transitions']} bascule(s) C5 · "
            f"{metrics['suspect_cycle_count']} boîte(s) fantôme(s) probable(s) · "
            f"{metrics['virtual_creation_count']} création(s) virtuelle(s) explicite(s) · "
            f"{metrics['incomplete_cycle_count']} association(s) incomplète(s)") + legacy


def merge_c5_metrics(rows):
    keys = ('episode_count', 'transitions', 'suspect_cycle_count',
            'virtual_creation_count', 'incomplete_cycle_count', 'blocked_transfer_count',
            'blocked_duration_seconds', 'refusal_count', 'initialization_count', 'affected_cycle_count')
    return {'c5_metrics_version': min(row.get('c5_metrics_version', 1) for row in rows),
            'signal_episode_count': sum(row.get('signal_episode_count', row['episode_count']) for row in rows),
            **{key: sum(row.get(key, 0) for row in rows) for key in keys},
            'episodes': [episode for row in rows for episode in row.get('episodes', [])]}


def analyze_c5(line_states, trace_origin=None):
    clock = observation_clock(line_states, trace_origin)

    @lru_cache(maxsize=2048)
    def candidates(text):
        lower = text.lower()
        unicode_case = not text.isascii()
        flags = tuple(unicode_case or any(token in lower for token in tokens)
                      for tokens in (_SIGNAL_TOKENS, _BLOCKED_TOKENS, _CYCLE_TOKENS))
        return lower, flags

    def observations(tokens, ordered=False):
        kind = (_SIGNAL_TOKENS, _BLOCKED_TOKENS, _CYCLE_TOKENS).index(tokens)
        previous_index = previous_time = previous_line = None
        for index, ((line, text, state), seconds) in enumerate(zip(line_states, clock.values(line_states))):
            if ordered and previous_line is not None and line <= previous_line:
                continue
            gap = previous_time is not None and seconds - previous_time > 120
            lower, flags = candidates(text)
            candidate = flags[kind]
            boundary_index, boundary_time = previous_index, previous_time
            previous_index, previous_time, previous_line = index, seconds, line
            if not gap and not candidate:
                continue
            obs = TimedObservation(clock, line, seconds, state.timestamp_str, text)
            obs.lower = lower
            if gap:
                old_line, old_text, old_state = line_states[boundary_index]
                obs.previous = TimedObservation(clock, old_line, boundary_time, old_state.timestamp_str, old_text)
            yield line, text, state, obs

    episodes, window = [], deque()
    current = previous = last_change = None
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

    for line, text, state, obs in observations(_SIGNAL_TOKENS):
        if obs.previous is not None:
            close('Interruption des observations supérieure à deux minutes', obs.previous)
            context += 1
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
        obs.value = int(match[1])
        if previous and previous['value'] != obs['value']:
            window.append((previous, obs))
            last_change = obs
            while window and obs['time'] - window[0][1]['time'] > 300 + 1e-6:
                window.popleft()
            if current:
                current['transitions'] += 1
            elif len(window) >= 10:
                current = {'first': window[0][0], 'last': obs, 'context': context,
                           'transitions': len(window), 'alternations': list(window)[:2], 'instability_windows': []}
            if current and len(window) >= 10:
                spans = current['instability_windows']
                start, end = obs['time'] - 120, obs['time'] + 120
                if spans and start <= spans[-1][1]:
                    spans[-1][1] = end
                else:
                    spans.append([start, end])
        previous = obs
        if current:
            current['last'] = obs
    close('Fin de trace ; résolution non observée')
    blocked = _blocked_transfers(lambda: observations(_BLOCKED_TOKENS, ordered=True), episodes)
    if not episodes and not blocked:
        return None

    # Les identites explicites lient les etapes ; le CIP ne sert jamais de cle.
    cycles, virtuals = [], []
    by_idb, by_ida = {}, {}
    creation = reason = t4_cycle = None
    last_created_id = 0
    context = 0
    for line, text, state, obs in observations(_CYCLE_TOKENS):
        if obs.previous is not None:
            by_idb.clear()
            by_ida.clear()
            creation = reason = t4_cycle = None
            last_created_id = 0
            context += 1
        if not _CYCLE_RELEVANT.search(text):
            continue
        if _RESTART.search(text):
            by_idb.clear()
            by_ida.clear()
            creation = reason = t4_cycle = None
            last_created_id = 0
            context += 1
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

    metrics = {'c5_metrics_version': 2, 'episode_count': len(episodes) + len(blocked),
               'signal_episode_count': len(episodes), 'transitions': 0,
               'blocked_transfer_count': len(blocked),
               'blocked_duration_seconds': sum(item['duration_seconds'] for item in blocked),
               'refusal_count': sum(item['refusal_count'] for item in blocked),
               'initialization_count': sum(item['initialization_count'] for item in blocked),
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
    offset = len(metrics['episodes'])
    for index, block in enumerate(blocked, offset + 1):
        metrics['episodes'].append(block)
        examples.append(dict(line=block['first_line'], time_str=block['start_time_str'],
            display_time_str=block['start_time_str'], box=f"IdB:{block['id_b']}" if block['id_b'] else '',
            barcode=block['barcode'], detail=block['detail'], sources=block['sources'], episode=index))
    selected_cycles = [cycle for episode in metrics['episodes'] for cycle in episode['cycles'] if cycle['complete']]
    affected = {(cycle['context'], 'C', cycle['line']) for cycle in selected_cycles}
    for block in blocked:
        resumed = next((cycle for cycle in selected_cycles if cycle['context'] == block['context']
                        and cycle['id_b'] == block['id_b'] and cycle['line'] ==
                        block['sources'].get('reprise confirmee')), None)
        affected.add((block['context'], 'C', resumed['line']) if resumed else
                     (block['context'], 'L', block['first_line']))
    metrics['affected_cycle_count'] = len(affected)
    ordered = sorted(enumerate(metrics['episodes'], 1), key=lambda item: item[1]['first_line'])
    numbers = {old: new for new, (old, _) in enumerate(ordered, 1)}
    metrics['episodes'] = [item for _, item in ordered]
    for sample in examples:
        sample['episode'] = numbers[sample['episode']]
    return metrics, examples
