"""Mesures par cycle boite et ecarts a la BdD, independants du rendu."""
from collections import Counter
from statistics import mean, median

from Models.dimension_check import DIMENSION_TOLERANCE_MM, dimension_finding_code

AXES = (('width', 'Largeur T5/C9', 0), ('height', 'Hauteur T5/LzB', 1),
        ('length', 'Longueur T4/C6', 2))


def _stats(samples, index):
    values = [item['deltas'][index] for item in samples]
    errors = [abs(value) for value in values]
    return {'count': len(values), 'references': len({s['barcode'] for s in samples if s['barcode']}),
            'min_abs': min(errors) if errors else None, 'max_abs': max(errors) if errors else None,
            'mean_abs': mean(errors) if errors else None, 'mean_signed': mean(values) if values else None}


def summarize(samples, excluded=None):
    axes = {}
    for name, label, index in AXES:
        anomalies = [s for s in samples if abs(s['deltas'][index]) > DIMENSION_TOLERANCE_MM]
        total = _stats(samples, index)
        total['outside_count'] = len(anomalies)
        total['outside_percent'] = 100 * len(anomalies) / len(samples) if samples else 0
        bias = None
        if len(samples) >= 10:
            center = median(s['deltas'][index] for s in samples)
            cluster = [s for s in samples if abs(s['deltas'][index] - center) <= 1]
            if center and len(cluster) / len(samples) >= .8:
                references = len({s['barcode'] for s in cluster if s['barcode']})
                if abs(center) <= DIMENSION_TOLERANCE_MM:
                    advice = 'Decalage regulier observe, restant dans la tolerance.'
                elif references < 2:
                    advice = 'Verifier en premier la fiche BdD et la presentation de cette reference.'
                else:
                    advice = 'Verifier le reglage/calibrage et les references BdD ; piste a confirmer sur le terrain.'
                bias = {'median': center, 'count': len(cluster), 'percent': 100 * len(cluster) / len(samples),
                        'references': references, 'advice': advice}
        axes[name] = {'label': label, 'all': total, 'anomalies': _stats(anomalies, index), 'bias': bias}
    return {'axes': axes, 'excluded': dict(excluded or {}), 'comparable_count': len(samples),
            'tolerance_mm': DIMENSION_TOLERANCE_MM}


def analyze_measurements(frames):
    """Conserve la derniere mesure complete et les preuves distinctes de chaque cycle T5."""
    active = {}
    cycles = {}
    samples = []
    serial = 0
    ambiguous_previous = Counter()
    ambiguous_count = 0
    for frame in frames:
        boxes = frame.boxes_on_T5
        barcode_counts = Counter(b.barcode or b.source_ref for b in boxes)
        counts = Counter(('A', b.id_alpha) if b.id_alpha else ('B', b.id_b) if b.id_b
                         else ('C', b.barcode or b.source_ref) for b in boxes)
        current = {}
        ambiguous_now = Counter()
        used = set()
        # Indexer les seuls cycles encore presents, sans parcours de l'historique.
        aliases = {}
        for key, item in active.items():
            for alias in item['aliases']:
                aliases.setdefault(alias, set()).add(key)
        for box in boxes:
            identity = ('A', box.id_alpha) if box.id_alpha else ('B', box.id_b) if box.id_b else ('C', box.barcode or box.source_ref)
            if not identity[1] or counts[identity] > 1:
                ambiguous_now[identity] += 1
                continue
            box_aliases = [('A', box.id_alpha), ('B', box.id_b), ('C', box.barcode or box.source_ref)]
            box_aliases = [a for a in box_aliases if a[1]]
            key = None
            for alias in box_aliases:
                if alias[0] == 'C' and barcode_counts[alias[1]] != 1:
                    continue
                candidates = aliases.get(alias, set()) - used
                candidates = {k for k in candidates if not (
                    box.id_alpha and active[k]['id_alpha'] and box.id_alpha != active[k]['id_alpha'])
                    and not (box.id_b and active[k]['id_b'] and box.id_b != active[k]['id_b']
                             and not (box.id_alpha and box.id_alpha == active[k]['id_alpha']))
                    and not (alias[0] == 'C' and not box.id_alpha and not box.id_b
                             and (active[k]['id_alpha'] or active[k]['id_b']))}
                if len(candidates) == 1:
                    key = next(iter(candidates))
                    break
            if key is None:
                serial += 1
                key = serial
                cycles[key] = {'last': None, 'signature': None, 'missing': 'incomplete', 'c9_error': False}
            item = cycles[key]
            item.update(aliases=list(dict.fromkeys(item.get('aliases', []) + box_aliases)),
                        id_alpha=box.id_alpha or item.get('id_alpha', 0),
                        id_b=box.id_b or item.get('id_b', 0))
            used.add(key)
            current[key] = item
            expected = [box.bdd_width_mm, box.bdd_height_mm, box.bdd_length_mm]
            measured = [box.measured_t5_width_mm, box.measured_t5_height_mm,
                        box.measured_t4_length_mm or box.measured_t5_length_mm]
            item['c9_error'] = box.measurement_status == 'c9_error'
            if any(v <= 0 for v in expected):
                item['missing'] = 'reference_absent'
                continue
            if any(v <= 0 for v in measured):
                item['missing'] = 'incomplete'
                continue
            signature = (tuple(expected), tuple(measured), item['c9_error'])
            if signature == item['signature']:
                item['last'].update(barcode=box.barcode or box.source_ref, source_ref=box.source_ref,
                    box=f'IdA:{box.id_alpha}' if box.id_alpha else f'idB:{box.id_b}' if box.id_b else box.barcode)
                continue
            item['signature'] = signature
            if item['last'] is not None:
                item['last']['final'] = False
            observation = {'cycle': key, 'line': frame.line_num, 'time': frame.timestamp,
                'time_str': frame.timestamp_str, 'box': f'IdA:{box.id_alpha}' if box.id_alpha else f'idB:{box.id_b}' if box.id_b else box.barcode,
                'barcode': box.barcode or box.source_ref, 'source_ref': box.source_ref,
                'expected': expected, 'measured': measured,
                'deltas': [m - e for m, e in zip(measured, expected)],
                'code': dimension_finding_code(tuple(measured), tuple(expected)),
                'invalid': item['c9_error'], 'final': True}
            item['last'] = observation
            samples.append(observation)
        ambiguous_count += sum((ambiguous_now - ambiguous_previous).values())
        ambiguous_previous = ambiguous_now
        active = current
    excluded = Counter({'ambiguous': ambiguous_count})
    comparable = []
    finals = []
    for item in cycles.values():
        last = item['last']
        if item['c9_error']:
            excluded['invalid'] += 1
        elif last is None:
            excluded[item['missing']] += 1
        elif last['code'] == 'ORIENTATION':
            excluded['orientation'] += 1
            finals.append(last)
        else:
            comparable.append(last)
            finals.append(last)
    summary = summarize(comparable, excluded)
    summary['cycle_count'] = serial + ambiguous_count
    return {'summary': summary, 'samples': samples, 'finals': finals}


def representative_samples(samples, limit=3):
    if not samples:
        return []
    ordered = sorted(samples, key=lambda s: s['line'])
    score = lambda s: max((abs(v) for v in s.get('deltas', [])), default=0)
    center = median(score(s) for s in ordered)
    candidates = [ordered[0], max(ordered, key=score), min(ordered, key=lambda s: abs(score(s) - center))]
    result = []
    for item in candidates + ordered:
        if item not in result:
            result.append(item)
        if len(result) == limit:
            break
    return result


def summary_text(summary, names=None):
    lines = []
    for name, axis in summary.get('axes', {}).items():
        if names is not None and name not in names:
            continue
        lines.append(axis['label'])
        for key, title in (('anomalies', 'Anomalies'), ('all', 'Toutes les mesures comparables')):
            stats = axis[key]
            if not stats['count']:
                lines.append(f'  {title} : aucune mesure comparable.')
                continue
            lines.append(f"  {title} : {stats['count']} boite(s), {stats['references']} reference(s). "
                f"Erreur absolue min {stats['min_abs']:.1f}, max {stats['max_abs']:.1f}, moyenne {stats['mean_abs']:.1f} mm.")
            direction = {'length': ('trop court', 'trop long'), 'width': ('trop etroit', 'trop large'),
                         'height': ('trop bas', 'trop haut')}[name]
            signed = stats['mean_signed']
            lines.append(f"  Decalage moyen : {signed:+.1f} mm" +
                         (f" ({abs(signed):.1f} mm {direction[signed > 0]})" if signed else ' (sans biais moyen)'))
        lines.append(f"  Hors tolerance : {axis['all']['outside_count']} ({axis['all']['outside_percent']:.1f} %).")
        if axis['bias']:
            bias = axis['bias']
            lines.append(f"  Decalage regulier autour de {bias['median']:+.1f} mm : {bias['percent']:.1f} %, "
                         f"{bias['count']} boites / {bias['references']} references. {bias['advice']}")
    labels = {'orientation': 'orientations differentes', 'invalid': 'mesures invalides',
              'incomplete': 'mesures incompletes', 'reference_absent': 'references absentes', 'ambiguous': 'identites ambigues'}
    exclusions = [f'{labels[k]} : {v}' for k, v in summary.get('excluded', {}).items() if v]
    if exclusions:
        lines.append('Exclus du bilan de reglage : ' + ', '.join(exclusions) + '.')
    return '\n'.join(lines)
