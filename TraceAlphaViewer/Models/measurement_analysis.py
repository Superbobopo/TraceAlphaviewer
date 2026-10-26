"""Mesures par cycle boite et ecarts a la BdD, independants du rendu."""
from collections import Counter
from statistics import mean, median
from operator import attrgetter

from Models.dimension_check import (DIMENSION_TOLERANCE_MM, DIMENSION_TOLERANCES_MM,
    dimension_tolerance, dimension_finding_code, measurement_orientation, best_orientation_dimensions,
    orientation_category)
from Models.measurement_identity import measurement_exclusion, EXCLUSION_LABELS

AXES = (('length', 'Longueur T4/C6 (T4C)', 2), ('width', 'Largeur T5/C9', 0),
        ('height', 'Hauteur T5/LzB', 1))

_MEASUREMENT_FIELDS = (
    'id_alpha', 'id_b', 't5_transfer_id', 'barcode', 'source_ref', 'name',
    'identified_barcode', 'identified_name', 'identity_line', 'identity_source', 'identity_conflict',
    'camera_identity_line', 'camera_identity_source', 'bdd_reference', 'bdd_source_line',
    'bdd_width_mm', 'bdd_height_mm', 'bdd_length_mm', 'measurement_status',
    'measured_t5_width_mm', 'measured_t5_height_mm', 'measured_t4_length_mm',
    'measured_t4t_length_mm', 'measured_t4_diff_mm', 'measured_t4_line',
    'measured_t5_line', 'measured_height_line',
)
_measurement_values = attrgetter(*_MEASUREMENT_FIELDS)


def _stats(samples, index):
    values = [item['deltas'][index] for item in samples]
    errors = [abs(value) for value in values]
    return {'count': len(values), 'references': len({s['barcode'] for s in samples if s['barcode']}),
            'min_abs': min(errors) if errors else None, 'max_abs': max(errors) if errors else None,
            'mean_abs': mean(errors) if errors else None, 'mean_signed': mean(values) if values else None,
            'min_signed': min(values) if values else None, 'max_signed': max(values) if values else None,
            'under_count': sum(v < -dimension_tolerance(index) for v in values),
            'over_count': sum(v > dimension_tolerance(index) for v in values),
            'worst_under': min((v for v in values if v < -dimension_tolerance(index)), default=None),
            'worst_over': max((v for v in values if v > dimension_tolerance(index)), default=None)}


def _frequencies(samples, index):
    groups = {}
    for sample in samples:
        groups.setdefault(sample['deltas'][index], []).append(sample)
    rows = [{'delta': delta, 'count': len(items),
             'references': len({s['barcode'] for s in items}),
             'percent': 100 * len(items) / len(samples)} for delta, items in groups.items()]
    return sorted(rows, key=lambda row: (-row['count'], abs(row['delta']), row['delta']))


def _product_groups(samples):
    groups = {}
    for sample in samples:
        key = (sample['barcode'], tuple(sample['expected']))
        groups.setdefault(key, []).append(sample)
    return groups


def _product_rows(groups, index):
    rows = []
    for (barcode, expected), samples in groups.items():
        values = sorted(s['deltas'][index] for s in samples)
        # La fenêtre porte sur toutes les mesures du même produit et de la même BdD.
        best = (0, 0, 0)
        left = 0
        for right, value in enumerate(values):
            while value - values[left] > 2:
                left += 1
            candidate = (right - left + 1, values[left], value)
            if (-candidate[0], abs((candidate[1] + candidate[2]) / 2), candidate[1]) < \
                    (-best[0], abs((best[1] + best[2]) / 2), best[1]):
                best = candidate
        total = len(values)
        rows.append({'barcode': barcode, 'name': samples[-1].get('name', ''),
                     'expected': list(expected), 'total': total, 'limited': total < 10,
                     'min_signed': values[0], 'max_signed': values[-1],
                     'window_count': best[0], 'window_percent': 100 * best[0] / total,
                     'window_min': best[1], 'window_max': best[2],
                     'dispersed': best[0] / total < .8 and values[-1] - values[0] > 2,
                     'under_count': sum(v < -dimension_tolerance(index) for v in values),
                     'over_count': sum(v > dimension_tolerance(index) for v in values),
                     'samples': samples})
    return sorted(rows, key=lambda row: (-row['total'], row['barcode'], row['expected']))


def _compact_product(row):
    return {key: value for key, value in row.items() if key != 'samples'}


def _close_product(row, center, index):
    close = [s for s in row['samples'] if abs(s['deltas'][index] - center) <= 1]
    return dict(_compact_product(row), center=center, close_count=len(close),
                close_percent=100 * len(close) / row['total'],
                repeated=row['total'] >= 2 and len(close) / row['total'] >= .8)


def _repetition_advice(name, repeated_references):
    if not repeated_references:
        return ''
    if repeated_references == 1:
        return 'Vérifier en premier la fiche BdD et la présentation du produit qui présente une répétition ; piste à confirmer.'
    controls = {'length': 'de T4/C6', 'width': 'de T5/C9', 'height': 'de LzB'}[name]
    advice = (f'Une répétition est observée sur plusieurs produits : vérifier le paramétrage et le réglage/calibrage {controls}, '
              'mesurer physiquement quelques boîtes et contrôler leurs dimensions BdD. Piste à confirmer.')
    if name == 'length':
        advice += ' Vérifier aussi une éventuelle intervention mécanique sans nouveau paramétrage.'
    return advice


def _repeated_offsets(samples, anomalies, index, name, products):
    result = {}
    for side, sign in (('under', -1), ('over', 1)):
        selected = [s for s in anomalies if s['deltas'][index] * sign > 0]
        frequencies = _frequencies(selected, index)
        center = frequencies[0]['delta'] if frequencies else None
        close = [s for s in samples if abs(s['deltas'][index] - center) <= 1] if center is not None else []
        bad = [s for s in close if abs(s['deltas'][index]) > dimension_tolerance(index)]
        cluster = None
        if close:
            references = len({s['barcode'] for s in close})
            product_rows = [_close_product(row, center, index) for row in products]
            product_rows = [row for row in product_rows if row['close_count']]
            product_totals = Counter(s['barcode'] for s in samples)
            confirmed = {row['barcode'] for row in product_rows if row['repeated']}
            contributions = Counter(s['barcode'] for s in close)
            dominant_code, dominant_count = sorted(contributions.items(), key=lambda pair: (-pair[1], pair[0]))[0]
            dominant = next(s for s in close if s['barcode'] == dominant_code)
            product_rows.sort(key=lambda row: (not row['repeated'], -row['close_count'], row['barcode'], row['expected']))
            cluster = {'center': center, 'median': center, 'min_signed': min(s['deltas'][index] for s in close),
                       'max_signed': max(s['deltas'][index] for s in close), 'count': len(close),
                       'bad_count': len(bad), 'good_count': len(close) - len(bad),
                       'bad_references': len({s['barcode'] for s in bad}),
                       'bad_min_signed': min(s['deltas'][index] for s in bad),
                       'bad_max_signed': max(s['deltas'][index] for s in bad),
                       'references': references, 'similar': bool(confirmed), 'shared': len(confirmed) >= 2,
                       'limited': len(close) < 10, 'repeated_references': len(confirmed),
                       'singleton_references': len({row['barcode'] for row in product_rows if product_totals[row['barcode']] == 1}),
                       'products': product_rows[:3], 'advice': _repetition_advice(name, len(confirmed)),
                       'dominant': {'barcode': dominant_code, 'name': dominant.get('name', ''),
                                    'count': dominant_count, 'percent': 100 * dominant_count / len(close)},
                       'percent_side': 100 * len(bad) / len(selected),
                       'percent_bad': 100 * len(bad) / len(anomalies),
                       'bad_percent_all': 100 * len(bad) / len(samples),
                       'percent_all': 100 * len(close) / len(samples)}
        result[side] = {'count': len(selected), 'frequencies': frequencies, 'cluster': cluster}
    return result


def repeated_offset_lines(axis, limit=5):
    lines = []
    signed = lambda value: f'{value:+.1f}'.replace('.', ',')
    percent = lambda value: f'{value:.1f}'.replace('.', ',')
    for side, label in (('under', 'En moins'), ('over', 'En trop')):
        item = axis.get('recurrence', {}).get(side, {})
        frequencies = item.get('frequencies', [])
        if not frequencies:
            continue
        frequent = '; '.join(f"{row['count']} {'boîte' if row['count'] == 1 else 'boîtes'} "
                             f"à {signed(row['delta'])} mm" for row in frequencies[:limit])
        lines.append(f'{label} — écarts les plus fréquents : {frequent}.')
        cluster = item['cluster']
        if cluster:
            lines.append(f"Autour de {signed(cluster['center'])} mm (±1 mm) : {cluster['bad_count']} défauts "
                         f"de {signed(cluster['bad_min_signed'])} à {signed(cluster['bad_max_signed'])} mm "
                         f"sur {cluster['bad_references']} références ({percent(cluster['percent_bad'])} % des mauvaises mesures ; "
                         f"{percent(cluster['bad_percent_all'])} % des comparables), "
                         f"et {cluster['good_count']} mesures conformes voisines. "
                         f"Ensemble : {cluster['count']} mesures de {signed(cluster['min_signed'])} "
                         f"à {signed(cluster['max_signed'])} mm, {cluster['references']} références, "
                         f"{percent(cluster['percent_all'])} % des comparables de la trace.")
            repeated = cluster['repeated_references']
            text = (f"Répétition étayée sur {repeated} produits, chacun mesuré plusieurs fois."
                    if repeated >= 2 else 'Répétition observée sur un seul produit.' if repeated == 1
                    else 'La concentration ne confirme pas une répétition au sein des produits.')
            if cluster['limited']:
                text += ' Effectif limité.'
            dominant = cluster['dominant']
            text += (f" Produit le plus représenté : {dominant['barcode']}, {dominant['count']}/{cluster['count']} "
                     f"mesures du groupe ({percent(dominant['percent'])} %).")
            lines.append(text)
            if repeated:
                details = '; '.join(f"{row['barcode']} : {row['close_count']}/{row['total']} "
                                    f"({percent(row['close_percent'])} %)" for row in cluster['products'] if row['repeated'])
                lines.append('Exemples de répétition, à dimensions BdD identiques : ' + details + '.')
                lines.append(cluster['advice'])
    return lines


def _interpretation(name, total, observations):
    if not total['count']:
        return ['Aucune mesure comparable pour proposer une piste.']
    lines = []
    if observations.get('opposed_groups'):
        lines.append('Deux groupes de sens opposés sont observés : aucun réglage unique ne peut être déduit de leur moyenne.')
    if observations['variant_references']:
        lines.append(f"{observations['variant_references']} référence(s) avec plusieurs dimensions BdD : "
                     'variantes analysées séparément, à vérifier dans la BdD.')
    if observations['opposite_references']:
        lines.append(f"{observations['opposite_references']} produit(s) présentent des groupes opposés : "
                     'examiner leur présentation, la chronologie et les lignes sources avant de proposer un réglage commun.')
    if observations['dispersed_references']:
        lines.append(f"Dispersion au sein de {observations['dispersed_references']} produit(s) à dimensions BdD identiques, "
                     f"sur {observations['dispersed_count']} mesures : aucune fenêtre de 2 mm n'en couvre 80 %.")
        for row in observations['dispersed_products']:
            lines.append(f"{row['barcode']} : {row['total']} mesures, plage {row['min_signed']:+.1f} "
                         f"à {row['max_signed']:+.1f} mm ; meilleure fenêtre : {row['window_count']}/{row['total']} "
                         f"({row['window_percent']:.1f} %)." + (' Effectif limité.' if row['limited'] else ''))
        if name == 'length':
            if observations['dispersed_under_count']:
                lines.append("Pour cette dispersion en moins : contrôler un possible patinage du moteur, "
                             "du rouleau moteur et l'entraînement T4. Hypothèse à vérifier.")
            if observations['dispersed_over_count']:
                lines.append('Pour cette dispersion en trop : contrôler le positionnement de C6 et les détections parasites. Hypothèse à vérifier.')
        elif observations['dispersed_under_count'] or observations['dispersed_over_count']:
            lines.append('Pour cette dispersion : contrôler C9, la présentation et le mouvement T5. Hypothèse à vérifier.'
                         if name == 'width' else 'Pour cette dispersion : contrôler LzB, la présentation et son paramétrage. Hypothèse à vérifier.')
    return lines


def _analyze_comparable(samples, excluded=None):
    axes = {}
    groups = _product_groups(samples)
    products_by_axis = {}
    for name, label, index in AXES:
        anomalies = [s for s in samples if abs(s['deltas'][index]) > dimension_tolerance(index)]
        total = _stats(samples, index)
        total['outside_count'] = len(anomalies)
        total['outside_percent'] = 100 * len(anomalies) / len(samples) if samples else 0
        total['within_count'] = len(samples) - len(anomalies)
        total['within_percent'] = 100 - total['outside_percent'] if samples else 0
        products = _product_rows(groups, index)
        products_by_axis[name] = products
        recurrence = _repeated_offsets(samples, anomalies, index, name, products)
        by_barcode = {}
        for row in products:
            by_barcode.setdefault(row['barcode'], []).append(row)
        variants = [{'barcode': barcode, 'name': rows[0]['name'], 'expected': [r['expected'] for r in rows]}
                    for barcode, rows in by_barcode.items() if len(rows) > 1]
        dispersed = [row for row in products if row['dispersed']]
        opposite = []
        centers = [recurrence[s]['cluster']['center'] if recurrence[s]['cluster'] else None for s in ('under', 'over')]
        if all(c is not None for c in centers):
            opposite_codes = {barcode for barcode, rows in by_barcode.items() if all(
                sum(abs(s['deltas'][index] - center) <= 1 for row in rows for s in row['samples']) >= 2
                for center in centers)}
            opposite = [row for row in products if row['barcode'] in opposite_codes]
        observations = {'variant_references': len(variants), 'variants': variants,
                        'opposed_groups': all(recurrence[s]['cluster'] is not None for s in ('under', 'over')),
                        'dispersed_references': len({r['barcode'] for r in dispersed}),
                        'dispersed_count': sum(r['total'] for r in dispersed),
                        'dispersed_under_count': sum(r['under_count'] for r in dispersed),
                        'dispersed_over_count': sum(r['over_count'] for r in dispersed),
                        'dispersed_products': [_compact_product(r) for r in dispersed[:3]],
                        'opposite_references': len({r['barcode'] for r in opposite}),
                        'opposite_products': [_compact_product(r) for r in opposite[:3]]}
        bias = None
        if len(samples) >= 10:
            center = median(s['deltas'][index] for s in samples)
            cluster = [s for s in samples if abs(s['deltas'][index] - center) <= 1]
            if center and len(cluster) / len(samples) >= .8:
                references = len({s['barcode'] for s in cluster if s['barcode']})
                if abs(center) <= dimension_tolerance(index):
                    advice = 'Decalage regulier observe, restant dans la tolerance.'
                else:
                    confirmed = {r['barcode'] for r in products if _close_product(r, center, index)['repeated']}
                    advice = _repetition_advice(name, len(confirmed)) or 'Concentration observée sur la trace ; répétition par produit non confirmée.'
                bias = {'median': center, 'count': len(cluster), 'percent': 100 * len(cluster) / len(samples),
                        'references': references, 'advice': advice}
        axes[name] = {'label': label, 'tolerance_mm': dimension_tolerance(name),
                      'all': total, 'anomalies': _stats(anomalies, index), 'bias': bias,
                      'recurrence': recurrence, 'recurrence_lines': [], 'frequencies': _frequencies(samples, index),
                      'product_observations': observations,
                      'interpretation': _interpretation(name, total, observations)}
        axes[name]['recurrence_lines'] = repeated_offset_lines(axes[name])
    outside = sum(any(abs(v) > dimension_tolerance(i) for i, v in enumerate(s['deltas'])) for s in samples)
    summary = {'axes': axes, 'excluded': dict(excluded or {}), 'comparable_count': len(samples),
            'cycle_count': len(samples) + sum((excluded or {}).values()),
            'excluded_count': sum((excluded or {}).values()),
            'global': {'within_count': len(samples) - outside, 'outside_count': outside,
                       'count': len(samples), 'references': len({s['barcode'] for s in samples if s['barcode']}),
                       'within_percent': 100 * (len(samples) - outside) / len(samples) if samples else 0,
                       'outside_percent': 100 * outside / len(samples) if samples else 0},
            'tolerance_mm': DIMENSION_TOLERANCE_MM, 'tolerances_mm': dict(DIMENSION_TOLERANCES_MM)}
    return summary, products_by_axis


def summarize(samples, excluded=None):
    return _analyze_comparable(samples, excluded)[0]


class MeasurementCollector:
    """Accumule les mesures d'un segment sans relire ses frames."""

    def __init__(self):
        self.active, self.cycles, self.samples = {}, {}, []
        self.serial = self.ambiguous_count = 0
        self.ambiguous_previous = Counter()
        self._previous_values = None
        self._repeat_safe = False

    def consume(self, frame_index, frame):
        values = tuple(_measurement_values(box) for box in frame.boxes_on_T5)
        if self._repeat_safe and values == self._previous_values:
            return
        active, cycles, samples = self.active, self.cycles, self.samples
        serial, ambiguous_count = self.serial, self.ambiguous_count
        ambiguous_previous = self.ambiguous_previous
        boxes = frame.boxes_on_T5
        barcode_counts = Counter(b.barcode or b.source_ref for b in boxes)
        counts = Counter(('A', b.id_alpha) if b.id_alpha else ('B', b.id_b) if b.id_b
                         else ('P', b.t5_transfer_id) if b.t5_transfer_id
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
            identity = (('A', box.id_alpha) if box.id_alpha else ('B', box.id_b) if box.id_b
                        else ('P', box.t5_transfer_id) if box.t5_transfer_id
                        else ('C', box.barcode or box.source_ref))
            if not identity[1] or counts[identity] > 1:
                ambiguous_now[identity] += 1
                continue
            box_aliases = [('A', box.id_alpha), ('B', box.id_b), ('P', box.t5_transfer_id),
                           ('C', box.barcode or box.source_ref)]
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
                         box.measured_t5_line, box.measured_height_line, box.bdd_source_line,
                         box.camera_identity_line, box.camera_identity_source)
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
                'display_frame_index': frame_index, 'display_line': frame.line_num,
                'display_time_str': frame.timestamp_str,
                'time_str': frame.timestamp_str, 'box': f'IdA:{box.id_alpha}' if box.id_alpha else f'idB:{box.id_b}' if box.id_b else box.barcode,
                'barcode': box.identified_barcode, 'name': box.identified_name or box.name,
                'id_alpha': box.id_alpha, 'id_b': box.id_b,
                'identity_source': box.identity_source,
                'camera_identity_source': box.camera_identity_source,
                'current_reference': box.barcode, 'source_ref': box.source_ref,
                'rejected_dimensions': '[DINH]' in box.barcode.upper(),
                't4c': box.measured_t4_length_mm, 't4t': box.measured_t4t_length_mm,
                'diff_t4': box.measured_t4_diff_mm,
                'sources': {'length': box.measured_t4_line, 'width': box.measured_t5_line,
                            'height': box.measured_height_line, 'bdd': box.bdd_source_line,
                            'identity': box.camera_identity_line},
                'expected': expected, 'measured': measured, 'tolerances_mm': dict(DIMENSION_TOLERANCES_MM),
                'deltas': [m - e for m, e in zip(measured, expected)],
                'code': dimension_finding_code(tuple(measured), tuple(expected)),
                'orientation_state': measurement_orientation(tuple(measured), tuple(expected)),
                'invalid': item['c9_error'], 'final': True}
            item['last'] = observation
            samples.append(observation)
        ambiguous_count += sum((ambiguous_now - ambiguous_previous).values())
        ambiguous_previous = ambiguous_now
        active = current
        self.active, self.serial = active, serial
        self.ambiguous_previous, self.ambiguous_count = ambiguous_previous, ambiguous_count
        self._previous_values = values
        primary = [('A', box.id_alpha) if box.id_alpha else ('B', box.id_b) if box.id_b
                   else ('P', box.t5_transfer_id) for box in boxes]
        strong_counts = Counter(alias for item in active.values() for alias in item['aliases']
                                if alias[0] in ('A', 'B', 'P'))
        self._repeat_safe = (all(key[1] for key in primary) and len(set(primary)) == len(primary)
            and all(strong_counts[key] == 1 for key in primary))

    def finish(self):
        cycles, samples = self.cycles, self.samples
        serial, ambiguous_count = self.serial, self.ambiguous_count
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
                excluded[last['orientation_state']] += 1
                finals.append(last)
            else:
                comparable.append(last)
                finals.append(last)
        summary, products = _analyze_comparable(comparable, excluded)
        summary['cycle_count'] = serial + ambiguous_count
        return {'summary': summary, 'samples': samples, 'finals': finals,
                'references': build_reference_lists(comparable, products, summary),
                'orientation_references': build_orientation_lists(finals)}



def analyze_measurements(frames):
    """Conserve la derniere mesure complete et les preuves de chaque cycle T5."""
    collector = MeasurementCollector()
    for index, frame in enumerate(frames):
        collector.consume(index, frame)
    return collector.finish()


def build_orientation_lists(finals):
    """Denominateurs par produit avant exclusion des orientations, une mesure par cycle."""
    eligible = [sample for sample in finals if sample.get('final', True) and not sample.get('invalid')
                and all(sample.get('sources', {}).get(axis, 0) > 0 for axis, _, _ in AXES)]
    totals = Counter(sample['barcode'] for sample in eligible)
    variants = {}
    for sample in eligible:
        variants.setdefault(sample['barcode'], set()).add(tuple(sample['expected']))
    result = {}
    proofs_by_kind = {kind: [] for kind in ('probable', 'uncertain', 'flat_rotation', 'on_edge', 'other')}
    for sample in eligible:
        state = sample.get('orientation_state')
        if state not in ('orientation', 'orientation_uncertain'):
            continue
        matches = best_orientation_dimensions(sample['measured'], sample['expected'])
        category = orientation_category(sample['measured'], sample['expected'], matches) if state == 'orientation' else 'uncertain'
        proof = dict(sample, orientation_matches=matches, orientation_category=category)
        proofs_by_kind['probable' if state == 'orientation' else 'uncertain'].append(proof)
        if state == 'orientation':
            proofs_by_kind[category].append(proof)
    for kind, proofs_in_kind in proofs_by_kind.items():
        groups = {}
        for proof in proofs_in_kind:
            groups.setdefault(proof['barcode'], []).append(proof)
        rows = []
        for barcode, proofs in groups.items():
            proofs.sort(key=lambda sample: (sample['display_frame_index'], sample['display_line'], sample['cycle']))
            count, total = len(proofs), totals[barcode]
            rows.append({'barcode': barcode, 'name': proofs[0].get('name', ''), 'count': count,
                         'total': total, 'percent': 100 * count / total, 'samples': proofs,
                         'orientation_category': kind,
                         'variant_count': len(variants[barcode])})
        result[kind] = sorted(rows, key=lambda row: (-row['count'], -row['percent'], row['barcode']))
    return result


def build_reference_lists(samples, products=None, summary=None):
    if products is None:
        summary, products = _analyze_comparable(samples)
    totals = Counter(s['barcode'] for s in samples)
    result = {}
    for name, _, index in AXES:
        by_barcode = {}
        for product in products[name]:
            by_barcode.setdefault(product['barcode'], []).append(product)
        sides = {'under': {}, 'over': {}}
        for sample in samples:
            delta = sample['deltas'][index]
            side = 'under' if delta < -dimension_tolerance(index) else 'over' if delta > dimension_tolerance(index) else ''
            if side:
                sides[side].setdefault(sample['barcode'], []).append(sample)
        result[name] = {}
        for side, groups in sides.items():
            rows = []
            for barcode, proofs in groups.items():
                stats = _stats(proofs, index)
                worst = stats['min_signed'] if side == 'under' else stats['max_signed']
                proofs = sorted(proofs, key=lambda s: (-abs(s['deltas'][index]),
                                s['sources'].get(name) or float('inf'), s['cycle']))
                product_rows = by_barcode[barcode]
                center = summary['axes'][name]['recurrence'][side]['cluster']['center']
                observations = [_close_product(row, center, index) for row in product_rows]
                representatives = []
                for row in product_rows:
                    close = [s for s in row['samples'] if abs(s['deltas'][index] - center) <= 1]
                    candidates = ([min(close, key=lambda s: abs(s['deltas'][index]) )] if close else [])
                    candidates += representative_samples(row['samples'], code={'length':'T4_LENGTH', 'width':'T5_WIDTH', 'height':'T5_HEIGHT'}[name])
                    representatives.extend(s for s in candidates[:3] if s not in representatives)
                rows.append(dict(stats, barcode=barcode, name=proofs[0].get('name', ''),
                                 total=totals[barcode], percent=100 * len(proofs) / totals[barcode],
                                 worst=worst, samples=proofs, observations=observations,
                                 variant_count=len(product_rows), representatives=representatives))
            result[name][side] = sorted(rows, key=lambda r: (-abs(r['worst']), -r['count'], r['barcode']))
        for side in ('under', 'over'):
            cluster = summary['axes'][name]['recurrence'][side]['cluster']
            rows = []
            if cluster:
                center = cluster['center']
                for barcode, product_rows in by_barcode.items():
                    comparable = [s for product in product_rows for s in product['samples']]
                    close = [s for s in comparable if abs(s['deltas'][index] - center) <= 1]
                    if not close:
                        continue
                    observations = [_close_product(row, center, index) for row in product_rows]
                    stats = _stats(close, index)
                    representatives = []
                    for product in product_rows:
                        representative = min(product['samples'], key=lambda s: abs(s['deltas'][index] - center))
                        representatives.append(representative)
                    worst = max((s['deltas'][index] for s in close), key=abs)
                    rows.append(dict(stats, barcode=barcode, name=comparable[0].get('name', ''),
                                     total=len(comparable), percent=100 * len(close) / len(comparable),
                                     worst=worst, samples=sorted(comparable, key=lambda s: s['line']),
                                     observations=observations, variant_count=len(product_rows), representatives=representatives))
            result[name][side + '_group'] = sorted(rows, key=lambda r: (-r['count'], r['barcode']))
    return result


def reference_page(analysis, axis, side, page=0, barcode=''):
    rows = analysis['references'][axis][side]
    if barcode:
        row = next(r for r in rows if r['barcode'] == barcode)
        samples = row['samples']
        return {'total': len(samples), 'samples': samples[page * 25:(page + 1) * 25],
                'observations': row.get('observations', []), 'variant_count': row.get('variant_count', 1),
                'representatives': row.get('representatives', [])}
    return {'total': len(rows), 'rows': [{k:v for k,v in row.items() if k not in ('samples', 'representatives')}
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
    below = [s for s in ordered if any(s['deltas'][i] < -dimension_tolerance(i) for i in indexes if i < len(s.get('deltas', [])))]
    above = [s for s in ordered if any(s['deltas'][i] > dimension_tolerance(i) for i in indexes if i < len(s.get('deltas', [])))]
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
        lines.append(axis['label'] + f" — A verifier : ecart absolu > {axis.get('tolerance_mm', summary.get('tolerance_mm', 3))} mm.")
        all_stats = axis['all']
        lines.append(f"  Bonnes mesures : {all_stats['within_count']}/{all_stats['count']} ({all_stats['within_percent']:.1f} %) ; "
                     f"mauvaises mesures : {all_stats['outside_count']}/{all_stats['count']} ({all_stats['outside_percent']:.1f} %). "
                     f"{all_stats['references']} reference(s).")
        lines.append(f"  Trop petites : {all_stats['under_count']} ; trop grandes : {all_stats['over_count']}.")
        lines.extend('  ' + text for text in axis.get('recurrence_lines', []))
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
        similar = any(item.get('cluster') and item['cluster']['similar'] for item in axis.get('recurrence', {}).values())
        if axis['bias'] and not similar:
            bias = axis['bias']
            lines.append(f"  Decalage regulier autour de {bias['median']:+.1f} mm : {bias['percent']:.1f} %, "
                         f"{bias['count']} boites / {bias['references']} references. {bias['advice']}")
        for explanation in axis.get('interpretation', []):
            lines.append('  Piste a verifier : ' + explanation)
    exclusions = [f'{EXCLUSION_LABELS[k]} : {v}' for k, v in summary.get('excluded', {}).items() if v]
    if exclusions:
        lines.append('Exclus du bilan de reglage : ' + ', '.join(exclusions) + '.')
    return '\n'.join(lines)
