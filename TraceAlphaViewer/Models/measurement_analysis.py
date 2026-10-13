"""Mesures par cycle boite et ecarts a la BdD, independants du rendu."""
from collections import Counter
from statistics import mean, median

from Models.dimension_check import DIMENSION_TOLERANCE_MM, dimension_finding_code
from Models.measurement_identity import measurement_exclusion, EXCLUSION_LABELS

AXES = (('length', 'Longueur T4/C6 (T4C)', 2), ('width', 'Largeur T5/C9', 0),
        ('height', 'Hauteur T5/LzB', 1))


def _stats(samples, index):
    values = [item['deltas'][index] for item in samples]
    errors = [abs(value) for value in values]
    return {'count': len(values), 'references': len({s['barcode'] for s in samples if s['barcode']}),
            'min_abs': min(errors) if errors else None, 'max_abs': max(errors) if errors else None,
            'mean_abs': mean(errors) if errors else None, 'mean_signed': mean(values) if values else None,
            'min_signed': min(values) if values else None, 'max_signed': max(values) if values else None,
            'under_count': sum(v < -DIMENSION_TOLERANCE_MM for v in values),
            'over_count': sum(v > DIMENSION_TOLERANCE_MM for v in values),
            'worst_under': min((v for v in values if v < -DIMENSION_TOLERANCE_MM), default=None),
            'worst_over': max((v for v in values if v > DIMENSION_TOLERANCE_MM), default=None)}


def _interpretation(name, total, bias):
    if not total['count']:
        return ['Aucune mesure comparable pour proposer une piste.']
    if bias:
        return [bias['advice']]
    if not total['under_count'] and not total['over_count']:
        return []
    lines = []
    if total['count'] < 10:
        lines.append('Moins de 10 boites comparables : echantillon insuffisant pour qualifier la tendance.')
    elif total['under_count'] or total['over_count']:
        lines.append('Les ecarts varient : aucun decalage regulier detecte avec le critere retenu.')
    if name == 'length':
        if total['under_count']:
            lines.append('Mesures trop courtes : verifier un possible patinage du moteur, du rouleau moteur et l\'entrainement T4.')
        if total['over_count']:
            lines.append('Mesures trop longues : verifier le positionnement de C6 et une detection parasite perturbant la mesure.')
    elif total['under_count'] or total['over_count']:
        lines.append('Verifier C9 et le mouvement T5.' if name == 'width' else 'Verifier LzB et son parametrage.')
    return lines


def summarize(samples, excluded=None):
    axes = {}
    for name, label, index in AXES:
        anomalies = [s for s in samples if abs(s['deltas'][index]) > DIMENSION_TOLERANCE_MM]
        total = _stats(samples, index)
        total['outside_count'] = len(anomalies)
        total['outside_percent'] = 100 * len(anomalies) / len(samples) if samples else 0
        total['within_count'] = len(samples) - len(anomalies)
        total['within_percent'] = 100 - total['outside_percent'] if samples else 0
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
                    advice = ('Verifier le reglage/calibrage du tapis, les references BdD et une eventuelle intervention '
                              'mecanique sans nouveau parametrage ; piste a confirmer sur le terrain.' if name == 'length'
                              else 'Verifier le reglage/calibrage et les references BdD ; piste a confirmer sur le terrain.')
                bias = {'median': center, 'count': len(cluster), 'percent': 100 * len(cluster) / len(samples),
                        'references': references, 'advice': advice}
        axes[name] = {'label': label, 'all': total, 'anomalies': _stats(anomalies, index), 'bias': bias,
                      'interpretation': _interpretation(name, total, bias)}
    outside = sum(any(abs(v) > DIMENSION_TOLERANCE_MM for v in s['deltas']) for s in samples)
    return {'axes': axes, 'excluded': dict(excluded or {}), 'comparable_count': len(samples),
            'cycle_count': len(samples) + sum((excluded or {}).values()),
            'excluded_count': sum((excluded or {}).values()),
            'global': {'within_count': len(samples) - outside, 'outside_count': outside,
                       'count': len(samples), 'references': len({s['barcode'] for s in samples if s['barcode']}),
                       'within_percent': 100 * (len(samples) - outside) / len(samples) if samples else 0,
                       'outside_percent': 100 * outside / len(samples) if samples else 0},
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
                cycles[key] = {'last': None, 'signature': None, 'missing': 'incomplete', 'c9_error': False,
                               'exclusion': ''}
            item = cycles[key]
            item.update(aliases=list(dict.fromkeys(item.get('aliases', []) + box_aliases)),
                        id_alpha=box.id_alpha or item.get('id_alpha', 0),
                        id_b=box.id_b or item.get('id_b', 0))
            used.add(key)
            current[key] = item
            item['exclusion'] = measurement_exclusion(box)
            if item['exclusion']:
                if item['last'] is not None:
                    item['last']['final'] = False
                continue
            expected = [box.bdd_width_mm, box.bdd_height_mm, box.bdd_length_mm]
            measured = [box.measured_t5_width_mm, box.measured_t5_height_mm,
                        box.measured_t4_length_mm if box.measured_t4_line else 0]
            item['c9_error'] = box.measurement_status == 'c9_error'
            if any(v <= 0 for v in expected):
                item['missing'] = 'reference_absent'
                continue
            if any(v <= 0 for v in measured):
                item['missing'] = 't4c_absent' if measured[2] <= 0 else 'incomplete'
                continue
            signature = (tuple(expected), tuple(measured), item['c9_error'], box.identified_barcode,
                         box.measured_t4t_length_mm, box.measured_t4_diff_mm, box.measured_t4_line,
                         box.measured_t5_line, box.bdd_source_line)
            if signature == item['signature']:
                item['last'].update(current_reference=box.barcode, source_ref=box.source_ref,
                    name=box.identified_name or box.name, rejected_dimensions='[DINH]' in box.barcode.upper(),
                    box=f'IdA:{box.id_alpha}' if box.id_alpha else f'idB:{box.id_b}' if box.id_b else box.barcode,
                    final=True)
                continue
            item['signature'] = signature
            if item['last'] is not None:
                item['last']['final'] = False
            observation = {'cycle': key, 'line': max(box.measured_t5_line, box.measured_t4_line, box.measured_height_line), 'time': frame.timestamp,
                'time_str': frame.timestamp_str, 'box': f'IdA:{box.id_alpha}' if box.id_alpha else f'idB:{box.id_b}' if box.id_b else box.barcode,
                'barcode': box.identified_barcode, 'name': box.identified_name or box.name,
                'id_alpha': box.id_alpha, 'id_b': box.id_b,
                'identity_source': box.identity_source,
                'current_reference': box.barcode, 'source_ref': box.source_ref,
                'rejected_dimensions': '[DINH]' in box.barcode.upper(),
                't4c': box.measured_t4_length_mm, 't4t': box.measured_t4t_length_mm,
                'diff_t4': box.measured_t4_diff_mm,
                'sources': {'length': box.measured_t4_line, 'width': box.measured_t5_line,
                            'height': box.measured_height_line, 'bdd': box.bdd_source_line,
                            'identity': box.identity_line},
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
        if item['exclusion']:
            excluded[item['exclusion']] += 1
        elif item['c9_error']:
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
    return {'summary': summary, 'samples': samples, 'finals': finals,
            'references': build_reference_lists(comparable)}


def build_reference_lists(samples):
    totals = Counter(s['barcode'] for s in samples)
    result = {}
    for name, _, index in AXES:
        sides = {'under': {}, 'over': {}}
        for sample in samples:
            delta = sample['deltas'][index]
            side = 'under' if delta < -DIMENSION_TOLERANCE_MM else 'over' if delta > DIMENSION_TOLERANCE_MM else ''
            if side:
                sides[side].setdefault(sample['barcode'], []).append(sample)
        result[name] = {}
        for side, groups in sides.items():
            rows = []
            for barcode, proofs in groups.items():
                stats = _stats(proofs, index)
                worst = stats['min_signed'] if side == 'under' else stats['max_signed']
                proofs = sorted(proofs, key=lambda s: (-abs(s['deltas'][index]), s['line']))
                rows.append(dict(stats, barcode=barcode, name=proofs[0].get('name', ''),
                                 total=totals[barcode], percent=100 * len(proofs) / totals[barcode],
                                 worst=worst, samples=proofs))
            result[name][side] = sorted(rows, key=lambda r: (-abs(r['worst']), -r['count'], r['barcode']))
    return result


def reference_page(analysis, axis, side, page=0, barcode=''):
    rows = analysis['references'][axis][side]
    if barcode:
        row = next(r for r in rows if r['barcode'] == barcode)
        samples = row['samples']
        return {'total': len(samples), 'samples': samples[page * 25:(page + 1) * 25]}
    return {'total': len(rows), 'rows': [{k:v for k,v in row.items() if k != 'samples'}
                                        for row in rows[page * 25:(page + 1) * 25]]}


def representative_samples(samples, limit=3, code=None):
    if not samples:
        return []
    # Les preuves finales portent les effectifs et les extremes du bilan.
    final = [s for s in samples if s.get('final', True)]
    ordered = sorted(final or samples, key=lambda s: s['line'])
    indexes = {'T4_LENGTH': (2,), 'T5_WIDTH': (0,), 'T5_HEIGHT': (1,)}.get(code, (0, 1, 2))
    values = lambda s: [s['deltas'][i] for i in indexes if i < len(s.get('deltas', []))]
    score = lambda s: max((abs(v) for v in values(s)), default=0)
    center = median(score(s) for s in ordered)
    below = [s for s in ordered if any(v < -DIMENSION_TOLERANCE_MM for v in values(s))]
    above = [s for s in ordered if any(v > DIMENSION_TOLERANCE_MM for v in values(s))]
    candidates = []
    if below:
        candidates.append(min(below, key=lambda s: min(values(s))))
    if above:
        candidates.append(max(above, key=lambda s: max(values(s))))
    candidates += [ordered[0], min(ordered, key=lambda s: abs(score(s) - center))]
    result = []
    for item in candidates + ordered:
        if item not in result:
            result.append(item)
        if len(result) == limit:
            break
    return result


def summary_text(summary, names=None):
    total = summary.get('global', {})
    lines = [f"Cycles de boites analyses sur T5 : {summary.get('cycle_count', 0)} ; "
             f"comparables : {summary.get('comparable_count', 0)} ; exclus : {summary.get('excluded_count', 0)}."]
    if total:
        lines.append(f"Toutes dimensions : {total['within_count']}/{total['count']} boites conformes "
                     f"({total['within_percent']:.1f} %) ; {total['outside_count']}/{total['count']} "
                     f"hors tolerance ({total['outside_percent']:.1f} %).")
    for name, axis in summary.get('axes', {}).items():
        if names is not None and name not in names:
            continue
        lines.append(axis['label'])
        all_stats = axis['all']
        lines.append(f"  Bonnes mesures : {all_stats['within_count']}/{all_stats['count']} ({all_stats['within_percent']:.1f} %) ; "
                     f"mauvaises mesures : {all_stats['outside_count']}/{all_stats['count']} ({all_stats['outside_percent']:.1f} %). "
                     f"{all_stats['references']} reference(s).")
        lines.append(f"  Trop petites : {all_stats['under_count']} ; trop grandes : {all_stats['over_count']}.")
        for key, title in (('anomalies', 'Mauvaises mesures'), ('all', 'Toutes les mesures comparables')):
            stats = axis[key]
            if not stats['count']:
                lines.append(f'  {title} : aucune.')
                continue
            lines.append(f"  {title} : {stats['count']} boite(s), {stats['references']} reference(s). "
                f"Plage {stats['min_signed']:+.1f} a {stats['max_signed']:+.1f} mm ; "
                f"erreur moyenne (sans tenir compte du sens) {stats['mean_abs']:.1f} mm.")
            below = f"{stats['worst_under']:+.1f} mm" if stats['worst_under'] is not None else 'aucune'
            above = f"{stats['worst_over']:+.1f} mm" if stats['worst_over'] is not None else 'aucune'
            lines.append(f"  Pire mauvaise mesure en moins : {below} ; en trop : {above}.")
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
        for explanation in axis.get('interpretation', []):
            if not axis['bias']:
                lines.append('  Piste a verifier : ' + explanation)
    exclusions = [f'{EXCLUSION_LABELS[k]} : {v}' for k, v in summary.get('excluded', {}).items() if v]
    if exclusions:
        lines.append('Exclus du bilan de reglage : ' + ', '.join(exclusions) + '.')
    return '\n'.join(lines)
