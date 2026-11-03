"""Impact relatif observe ; les gravites des diagnostics restent independantes."""
import re
from math import isfinite


DOMAINS = (
    ('camera', 'Caméras', 'lectures caméra observées'),
    ('transfers', 'Transferts', 'confirmations de transfert'),
    ('measurements', 'Mesures', 'mesures finales complètes'),
    ('robot', 'Robot', 'échanges robot reçus'),
    ('motors', 'Communication moteurs', 'réponses moteurs observées'),
    ('alpha', 'Carte Alpha', 'relevés du compteur carte'),
)
LABELS = {'ok': 'Aucune alerte détectée', 'warning': 'Alerte',
          'critical': 'Critique', 'unavailable': 'Non évalué'}
CODE_DOMAINS = {
    'UNKNOWN': ('camera',), 'CAM-NO-READ': ('camera',),
    'DP_MISSING': ('camera',), 'CAMERA_CODE_MODE': ('camera',),
    'C2_SIGNAL_ANOMALY': ('transfers',), 'C3_SIGNAL_ANOMALY': ('transfers',),
    'C5_SIGNAL_ANOMALY': ('transfers',), 'T2-EA': ('transfers',),
    'CUBESTOP_C4_BLOCKED': ('transfers',), '017-Avt': ('transfers',),
    '118-Vide T5': ('transfers',), 'INIT-C6': ('transfers',),
    'INIT-INDEX': ('transfers',), 'CREATE': ('transfers',),
    'T5_STALE_UNMEASURED_BOX': ('transfers',),
    'T5_DRIVE_SUSPECTED': ('transfers', 'measurements'),
    'T4_LENGTH': ('measurements',), 'T5_WIDTH': ('measurements',),
    'T5_HEIGHT': ('measurements',), 'GLOBAL': ('measurements',),
    'ORIENTATION': ('measurements',), 'diffT4': ('measurements',),
    'C6': ('measurements',), 'C9_WIDTH_INVALID': ('measurements',),
    'DemVidageComplet': ('robot',), 'MOTOR_COMM': ('motors',),
    'ALPHA_CARD_RESET': ('alpha',),
}
EXCLUDED_CODES = {'REFERENCE_ABSENT', 'REFERENCE_NON_ALPHATISABLE'}
_TRANSFER = re.compile(r'transfert T3->T4 termin|le transfert \(EA->T3\) est termin|'
                       r'T2:.*transfert.*termin|la boite est rendu.*\(physiquement\) sur T5', re.I)
_MEASURE = re.compile(r'MAJ \(APRES-MESURE-LARG\).*?nvlle lxH:(-?\d+)x(-?\d+)\s*\[x(-?\d+)\]', re.I)
_MOTOR = re.compile(r'Comm\.\s*OK sur StepMotors|SendCde:.*?-->\s*(?:Ok\b|\d+\b)', re.I)


class HealthObservationCollector:
    """Compteurs bornés alimentés par les lignes déjà dédoublonnées du segment."""
    def __init__(self):
        self.counts = dict.fromkeys((key for key, _, _ in DOMAINS), 0)
        self._context = 0
        self._previous_time = None
        self._line_cycles = {}
        self._transferred = set()
        self._unattributed = set()
        self._stage_signature = None
        self._stage_projection = {}

    def observe_frame(self, frame, references, seen_lines=()):
        previous = self._previous_time
        if previous is not None and (frame.timestamp < previous or frame.timestamp - previous > 120):
            self._context += 1
        self._previous_time = frame.timestamp
        for line, text, *_ in frame.raw_lines:
            if line in seen_lines or line in self._line_cycles:
                continue
            if 'version logiciel VBalpha:' in text:
                self._context += 1
            transfer = 'transfert' in text.lower() or 'physiquement' in text
            events = [event for event in frame.events if event.line_num == line and event.severity in {'error', 'warning'}]
            if not transfer and not events and 'Création de la boite' not in text and 'Creation de la boite' not in text:
                continue
            signature = (self._context, references.current_stage_keys)
            if signature != self._stage_signature:
                stages = {}
                for stage, key in references.current_stage_keys:
                    record = references.records[key]
                    cycle = (self._context, key, record.first_line)
                    stages.setdefault(stage, set()).add(cycle)
                # Les lignes partageant la meme situation gardent une projection immuable.
                self._stage_projection = {stage: frozenset(keys) for stage, keys in stages.items()}
                self._stage_signature = signature
            stages = self._stage_projection
            identity = re.search(r'\b(IdA|Id|idB|Nboite)\s*[:=]\s*(\d+)', text, re.I)
            if identity:
                attribute = 'id_b' if identity[1].lower() in {'idb', 'nboite'} else 'id_alpha'
                stages = {stage: frozenset(cycle for cycle in keys
                          if getattr(references.records[cycle[1]], attribute) == int(identity[2]))
                          for stage, keys in stages.items()}
            self._line_cycles[line] = stages
            if transfer:
                if 'T3->T4' in text:
                    target = stages.get('T4') or stages.get('T3', set())
                elif ('T4' in text and 'T5' in text) or 'physiquement' in text:
                    target = stages.get('T4') or stages.get('T5', set())
                elif 'EA->T3' in text:
                    target = stages.get('T3') or stages.get('EA', set())
                elif 'T2' in text:
                    target = stages.get('EA', set())
                else:
                    target = set()
                if len(target) == 1:
                    self._transferred.update(target)
                else:
                    self._unattributed.add(line)

    def consume(self, text):
        if 'Hist_LectCB' in text and ('CB1:' in text or 'CB2:' in text):
            self.counts['camera'] += 1
        if ('transfert' in text.lower() or 'physiquement' in text) and _TRANSFER.search(text):
            if 'erreur' not in text.lower():
                self.counts['transfers'] += 1
        if 'MAJ (APRES-MESURE-LARG)' in text:
            match = _MEASURE.search(text)
            if match and all(int(value) > 0 for value in match.groups()):
                self.counts['measurements'] += 1
        if 'UDP trame recu du robot' in text or 'UDP trame reçu du robot' in text:
            self.counts['robot'] += 1
        if ('SendCde:' in text or 'StepMotors' in text) and _MOTOR.search(text):
            self.counts['motors'] += 1
        if 'Temps depuis RESET carte ALPHA' in text:
            self.counts['alpha'] += 1

    def finish(self, diagnostics=(), line_states=(), origin=None, robot_analysis=None):
        affected, unresolved = set(), set()
        for incident in diagnostics:
            group = {'code': incident.code, 'belt': incident.belt}
            if 'transfers' not in domains_for(group) or incident.severity not in {'error', 'warning'}:
                continue
            metrics = incident.metrics
            episodes = metrics.get('episodes') or [None]
            for episode in episodes:
                lines = ([episode['first_line']] if episode else
                         (incident.event_lines or [incident.first_line]) if re.fullmatch(r'-\d+', incident.code) else [incident.first_line])
                found = set()
                for line in lines:
                    stages = self._line_cycles.get(line, {})
                    stage = 'EA' if (incident.belt, incident.code) in {('T2', '-88'), ('T3', '-43'), ('T3', '-48')} else incident.belt
                    keys = stages.get(stage, set())
                    if len(keys) == 1 and keys <= self._transferred:
                        found.update(keys)
                    else:
                        unresolved.add((line, incident.code))
                affected.update(found)
        duration = 0.0
        if line_states:
            from Models.trace_calendar import observation_clock
            previous = None
            for value in observation_clock(line_states, origin).values(line_states):
                if previous is not None and 0 <= value - previous <= 120:
                    duration += value - previous
                previous = value
        robot = next((item.metrics for item in diagnostics if item.code == 'DemVidageComplet'), None)
        if robot is None and line_states:
            if robot_analysis is None:
                from Models.robot_drain import analyze_robot_boxes
                robot_analysis = analyze_robot_boxes(line_states, origin)
            robot = robot_analysis
        robot = {key: robot[key] for key in ('box_metrics_version', 'rejected_boxes_count', 'robot_picked_boxes_count', 'unattributed_request_count') if key in robot} if robot else {}
        return {'version': 2, 'segments': 1, 'counts': dict(self.counts), 'robot': robot,
                'duration_seconds': duration,
                'transfers': {'affected': len(affected), 'total': len(self._transferred),
                              'unattributed_episodes': len(unresolved),
                              'unattributed_transfers': len(self._unattributed)}}


def merge_health_observations(items):
    valid = [item for item in items if item.get('version') in {1, 2}]
    complete = bool(valid) and all(item.get('version') == 2 for item in items)
    return {'version': 2 if complete else 1, 'segments': sum(item.get('segments', 1) for item in valid),
            'robot': dict(box_metrics_version=1, **{key: sum(item.get('robot', {}).get(key, 0) for item in valid)
                         for key in ('rejected_boxes_count', 'robot_picked_boxes_count', 'unattributed_request_count')}) if complete and all(item.get('robot', {}).get('box_metrics_version') for item in valid) else {},
            'duration_seconds': sum(item.get('duration_seconds', 0) for item in valid) if complete else None,
            'transfers': {key: sum(item.get('transfers', {}).get(key, 0) for item in valid)
                          for key in ('affected', 'total', 'unattributed_episodes', 'unattributed_transfers')} if complete else {},
            'counts': {key: sum(item.get('counts', {}).get(key, 0) for item in valid)
                       for key, _, _ in DOMAINS}}


def domains_for(group):
    code = str(group.get('code', ''))
    if code in EXCLUDED_CODES:
        return ()
    if code in CODE_DOMAINS:
        return CODE_DOMAINS[code]
    if group.get('belt') in {'T0', 'T1', 'T2', 'T3', 'T4', 'T5', 'EA'}:
        if re.fullmatch(r'-\d+', code) or code.startswith('WAIT-'):
            return ('transfers',)
    return ()


def impact_color(value):
    if value is None:
        return '#929ca7'
    low, high, fraction = ((191, 52, 68), (181, 121, 18), value * 2) if value <= .5 else ((181, 121, 18), (40, 124, 80), (value - .5) * 2)
    return '#' + ''.join(f'{round(a + (b - a) * fraction):02x}' for a, b in zip(low, high))


def camera_impact_color(rate):
    if rate is None:
        return impact_color(None)
    value = 1 - rate / .16 if rate <= .08 else max(0, (.12 - rate) / .08)
    return impact_color(value)


def measurement_impact_color(affected, total):
    if total is None or affected is None or total <= 0 or not 0 <= affected <= total:
        return impact_color(None)
    if affected * 100 > total * 15:
        return '#bf3444'
    if affected * 100 > total * 8:
        return '#b57912'
    return impact_color(1 - affected / total)


def repeated_transfer_problems(groups):
    reasons = []
    for group in groups:
        code, belt = group['code'], group.get('belt')
        count = group.get('occurrence_count', 0)
        if code == 'C5_SIGNAL_ANOMALY':
            count = group.get('metrics', {}).get('blocked_transfer_count', 0)
        elif not (code in {'CUBESTOP_C4_BLOCKED', 'T2-EA', 'INIT-C6', 'INIT-INDEX'}
                  or (belt == 'T2' and code in {'-87', '-88', '-89'})
                  or (belt == 'T3' and code in {'-43', '-46', '-48', '-49'})
                  or (belt == 'T4' and code in {'-17', '-18', '-19'})):
            continue
        if count >= 2 and group.get('field_severity', group.get('severity')) in {'error', 'warning'}:
            reasons.append({'id': group['id'], 'title': group['title'], 'count': count})
    return reasons


def build_health_radar(observations, groups, *, camera=None, measurements=None):
    if not observations or observations.get('version') not in {1, 2}:
        return None
    camera, measurements = camera or {}, measurements or {}
    unknown = camera.get('unknown', {})
    robot = observations.get('robot') or next((group.get('metrics', {}) for group in groups if group['code'] == 'DemVidageComplet'), {})
    duration = observations.get('duration_seconds')
    hours = duration / 3600 if isinstance(duration, (int, float)) and duration > 0 else None
    transfers = observations.get('transfers', {}) if observations.get('version') == 2 else {}
    def count(code):
        return sum(group.get('occurrence_count', 0) for group in groups if group['code'] == code)
    populations = {
        'camera': (unknown.get('count'), unknown.get('total'), 'boîtes finales UNKNOWN', 'passages analysés'),
        'transfers': (transfers.get('affected'), transfers.get('total'), 'cycles avec anomalie de transfert', 'cycles avec transfert observé'),
        'measurements': (measurements.get('global', {}).get('outside_count'), measurements.get('global', {}).get('count'), 'boîtes hors tolérance', 'boîtes comparables'),
        'robot': (robot.get('rejected_boxes_count'), (robot.get('rejected_boxes_count', 0) + robot.get('robot_picked_boxes_count', 0)) if robot.get('box_metrics_version') else None, 'boîtes évacuées', 'sorties comptabilisées'),
        'motors': (count('MOTOR_COMM'), hours, 'épisodes avec défaut explicite', 'heures couvertes'),
        'alpha': (count('ALPHA_CARD_RESET'), hours, 'resets détectés', 'heures couvertes'),
    }
    axes = []
    for key, label, observation_label in DOMAINS:
        related = [group for group in groups if key in domains_for(group)]
        related.sort(key=lambda group: {'error': 0, 'warning': 1, 'info': 2}.get(
            group.get('field_severity', group.get('severity')), 3))
        numerator, denominator, unit, population = populations[key]
        frequency = key in {'motors', 'alpha'}
        valid = all(isinstance(x, (int, float)) and isfinite(x) for x in (numerator, denominator)) and numerator >= 0 and denominator > 0
        valid = valid and (frequency or numerator <= denominator)
        rate = numerator / denominator if valid else None
        value = (1 / (1 + rate) if frequency else 1 - rate) if valid else None
        partial = key == 'transfers' and bool(transfers.get('unattributed_episodes') or transfers.get('unattributed_transfers'))
        limits = []
        if not valid:
            limits.append('Données insuffisantes : recharger la trace et régénérer le rapport si nécessaire.')
        if partial:
            limits.append(f"Couverture partielle : {transfers.get('unattributed_episodes', 0)} épisode(s) et {transfers.get('unattributed_transfers', 0)} observation(s) de transfert sans cycle attribuable restent hors du ratio.")
        if frequency:
            limits.append('Durée des intervalles horodatés continus (120 s maximum) ; interruptions exclues. Un incident/heure correspond au milieu du rayon, sans changer les seuils des cartes.')
        if key == 'alpha':
            limits.append('Aucun reset détecté ne garantit pas l’absence de reset hors observation.')
        if key == 'robot':
            limits.append('Part évacuée parmi les sorties comptabilisées ; ce ratio ne mesure pas le taux d’échec des tentatives de prise.')
            if robot.get('unattributed_request_count'):
                limits.append(f"{robot['unattributed_request_count']} demande(s) sans bilan complet.")
        if key == 'measurements' and measurements.get('excluded_count'):
            limits.append(f"{measurements['excluded_count']} cycle(s) exclus de la comparaison dimensionnelle.")
        if key == 'camera':
            limits.append('La position conserve la proportion des passages sans UNKNOWN final. La couleur souligne le taux de non-identification : vert à 0 %, orange à 8 %, rouge dès 12 %.')
        color = camera_impact_color(rate) if key == 'camera' else impact_color(value)
        repeated = repeated_transfer_problems(related) if key == 'transfers' else []
        if repeated:
            limits.append('Alerte de répétition : pour un ratio calculable, dès deux occurrences d’un même diagnostic de blocage ou d’initialisation T4, la couleur est au moins orange, même si la proportion de cycles concernés est faible. Les diagnostics peuvent concerner les mêmes cycles ; leurs effectifs ne sont pas additionnés au ratio.')
            limits.extend(f"{item['title']} : {item['count']} occurrence(s)." for item in repeated)
            if valid and value > .5:
                color = '#b57912'
        if key == 'measurements':
            color = measurement_impact_color(numerator, denominator) if valid else impact_color(None)
            limits.append('Couleur Mesures : alerte au-delà de 8 % de boîtes hors tolérance, critique au-delà de 15 %. Longueur, largeur et hauteur partagent cette règle ; une boîte multiaxes compte une seule fois. À 8 % exactement : pas d’alerte ; à 15 % exactement : alerte.')
        axes.append({'id': key, 'label': label, 'value': value, 'rate': rate,
                     'color': color, 'metric_kind': 'frequency' if frequency else 'proportion',
                     'numerator': numerator, 'denominator': denominator, 'unit': unit, 'population': population,
                     'coverage': 'unavailable' if not valid else 'partial' if partial else 'observed',
                     'unattributed_episodes': transfers.get('unattributed_episodes', 0) if key == 'transfers' else 0,
                     'unattributed_transfers': transfers.get('unattributed_transfers', 0) if key == 'transfers' else 0,
                     'limits': limits,
                     'repeated_problems': repeated,
                     'groups': [{'id': group['id'], 'title': group['title'],
                                 'severity': group.get('field_severity', group.get('severity'))}
                                for group in related],
                     'explanation': 'Impact relatif sur l’activité observée. La gravité des diagnostics associés reste indépendante.'})
    return {'version': 2, 'title': 'Bilan de l’Alpha', 'axes': axes,
            'segments': observations.get('segments', 1)}
