from __future__ import annotations

import re
from dataclasses import dataclass, field

from Models.diagnostic_knowledge import knowledge
from Models.state import MachineEvent, MachineState


@dataclass
class DiagnosticIncident:
    severity: str
    title: str
    belt: str = ""
    code: str = ""
    first_line: int = 0
    last_line: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    start_time_str: str = ""
    end_time_str: str = ""
    count: int = 0
    summary: str = ""
    symptom: str = ""
    probable_causes: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    confidence: str = ""
    event_lines: list[int] = field(default_factory=list)

    def duration_label(self) -> str:
        duration = max(0, int(self.end_time - self.start_time))
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h{minutes:02d}m{seconds:02d}s"
        if minutes:
            return f"{minutes}m{seconds:02d}s"
        return f"{seconds}s"


_MOTOR_ERROR = re.compile(r'^(T\d)\s+en erreur eT:(-?\d+)')
_T4_DIFF = re.compile(r'Controle longueur T4 diff\s+(-?\d+)mm')
_TRACE_T4_INIT_ERR = re.compile(r'Initialisation de T4 termin.ee sur ERREUR -18', re.IGNORECASE)
_TRACE_T5_DEM_VIDAGE = re.compile(r'OMEGA:T5-DemVidageComplet', re.IGNORECASE)
_TRACE_017 = re.compile(r'017-Avt:\s*boite coinc.ee sur C4 apr.s .* ejects', re.IGNORECASE)
_TRACE_028 = re.compile(r'028-Avt:\s*d.faut communication carte moteurs', re.IGNORECASE)
_TRACE_118 = re.compile(r'118-Vide T5 suite blocage poubelle', re.IGNORECASE)


def _frame_lines(frames: list[MachineState]) -> list[tuple[int, str, float, str]]:
    lines: list[tuple[int, str, float, str]] = []
    seen: set[int] = set()
    for frame in frames:
        for line_num, text, *_ in frame.raw_lines:
            if line_num in seen:
                continue
            seen.add(line_num)
            lines.append((line_num, text, frame.timestamp, frame.timestamp_str))
    return lines


def _event_group_incident(
    severity: str,
    title: str,
    belt: str,
    code: str,
    events: list[MachineEvent],
    summary: str,
    causes: list[str],
    symptom: str = "",
    checks: list[str] | None = None,
    confidence: str = "",
) -> DiagnosticIncident:
    first = events[0]
    last = events[-1]
    return DiagnosticIncident(
        severity=severity,
        title=title,
        belt=belt,
        code=code,
        first_line=first.line_num,
        last_line=last.line_num,
        start_time=first.timestamp,
        end_time=last.timestamp,
        start_time_str=first.timestamp_str,
        end_time_str=last.timestamp_str,
        count=len(events),
        summary=summary,
        symptom=symptom,
        probable_causes=causes,
        checks=list(checks or []),
        confidence=confidence,
        event_lines=[event.line_num for event in events],
    )


def _motor_error_title(belt: str, code: str) -> str:
    if belt == 'T4' and code == '-18':
        return 'T4 eT:-18 - Index T4 non trouve'
    return f'{belt} eT:{code} - Erreur moteur'


def _motor_error_causes(belt: str, code: str) -> list[str]:
    if belt == 'T4' and code == '-18':
        return list(knowledge('t4_error_minus_18').get('causes', []))
    return list(knowledge('motor_error_generic').get('causes', []))


def _build_motor_error_incidents(events: list[MachineEvent]) -> list[DiagnosticIncident]:
    grouped: dict[tuple[str, str], list[MachineEvent]] = {}
    for event in events:
        if event.kind != 'ERREUR':
            continue
        match = _MOTOR_ERROR.search(event.title)
        if not match:
            continue
        belt, code = match.groups()
        if code == '-1':
            continue
        grouped.setdefault((belt, code), []).append(event)

    incidents: list[DiagnosticIncident] = []
    for (belt, code), group in grouped.items():
        group.sort(key=lambda event: event.line_num)
        title = _motor_error_title(belt, code)
        summary = (
            f"{len(group)} apparition(s), de L.{group[0].line_num} "
            f"a L.{group[-1].line_num}, entre {group[0].timestamp_str} "
            f"et {group[-1].timestamp_str}."
        )
        rule = knowledge('t4_error_minus_18' if belt == 'T4' and code == '-18' else 'motor_error_generic')
        incidents.append(_event_group_incident(
            'error',
            title,
            belt,
            code,
            group,
            summary,
            _motor_error_causes(belt, code),
            symptom=str(rule.get('symptom', '')),
            checks=list(rule.get('checks', [])),
            confidence=str(rule.get('confidence', '')),
        ))
    return incidents


def _build_t4_diff_incidents(events: list[MachineEvent]) -> list[DiagnosticIncident]:
    group: list[MachineEvent] = []
    max_diff = 0
    for event in events:
        if event.kind != 'T4':
            continue
        match = _T4_DIFF.search(event.title)
        if not match:
            continue
        diff = int(match.group(1))
        if abs(diff) <= 10:
            continue
        max_diff = max(max_diff, abs(diff))
        group.append(event)

    if not group:
        return []

    return [_event_group_incident(
        'warning',
        f'T4 - Ecart longueur mesuree > 10mm (max {max_diff}mm)',
        'T4',
        'diffT4',
        sorted(group, key=lambda event: event.line_num),
        "Une ou plusieurs mesures T4 different trop de la reference BdD/T4.",
        [
            "Boite mal tassee ou glissement pendant la mesure longueur.",
            "C6 declenche trop tot/trop tard.",
            "Mesure T4C/T4T incoherente ou reference BdD inadaptee.",
        ],
        symptom="La mesure de longueur T4 s'ecarte sensiblement de la reference attendue.",
        checks=[
            "Comparer les mesures T4C/T4T avec la reference BdD.",
            "Verifier le declenchement de C6 pendant la mesure.",
        ],
        confidence='possible',
    )]


def _build_missing_c6_incidents(events: list[MachineEvent]) -> list[DiagnosticIncident]:
    incidents: list[DiagnosticIncident] = []
    t4_events = [event for event in events if event.kind == 'T4']
    open_measure: MachineEvent | None = None
    saw_c6 = False

    for event in t4_events:
        if event.title.startswith('Mesure longueur T4 en cours'):
            if open_measure is not None and not saw_c6:
                incidents.append(_missing_c6_incident(open_measure, event))
            open_measure = event
            saw_c6 = False
            continue
        if open_measure is None:
            continue
        if event.title.startswith('C6 declenche longueur') or ('C6:1' in event.detail and 'Lg:' in event.detail):
            saw_c6 = True
        if event.title.startswith('T3 vers T4 termine') or event.title.startswith('Transfert T4 vers T5'):
            if not saw_c6:
                incidents.append(_missing_c6_incident(open_measure, event))
            open_measure = None
            saw_c6 = False

    if open_measure is not None and not saw_c6:
        incidents.append(_missing_c6_incident(open_measure, open_measure))
    return incidents


def _missing_c6_incident(start: MachineEvent, end: MachineEvent) -> DiagnosticIncident:
    return DiagnosticIncident(
        severity='warning',
        title='T4 - C6 non declenche pendant la mesure longueur',
        belt='T4',
        code='C6',
        first_line=start.line_num,
        last_line=end.line_num,
        start_time=start.timestamp,
        end_time=end.timestamp,
        start_time_str=start.timestamp_str,
        end_time_str=end.timestamp_str,
        count=1,
        summary="Une mesure longueur T4 commence sans evenement C6 associe avant la fin du cycle.",
        symptom="Une mesure T4 se lance mais aucun declenchement C6 n'est observe avant la fin du cycle.",
        probable_causes=[
            "Boite n'atteint pas le capteur C6.",
            "Capteur C6 absent, deregle ou cable.",
            "Mouvement T4 interrompu avant detection.",
        ],
        checks=[
            "Verifier le capteur C6 et son positionnement.",
            "Verifier si la boite atteint bien la zone C6.",
        ],
        confidence='probable',
        event_lines=[start.line_num, end.line_num],
    )


def _build_missing_t5_creation_incidents(events: list[MachineEvent]) -> list[DiagnosticIncident]:
    incidents: list[DiagnosticIncident] = []
    creation_lines = [
        event.line_num for event in events
        if event.kind == 'BOITE' and event.title.startswith('Creation T5')
    ]
    for event in events:
        if event.kind != 'TRANSFERT' or not event.title.startswith('T4 vers T5'):
            continue
        has_creation = any(0 <= line - event.line_num <= 20 for line in creation_lines)
        if has_creation:
            continue
        incidents.append(DiagnosticIncident(
            severity='warning',
            title='T5 - Boite rendue sans creation BdD proche',
            belt='T5',
            code='CREATE',
            first_line=event.line_num,
            last_line=event.line_num,
            start_time=event.timestamp,
            end_time=event.timestamp,
            start_time_str=event.timestamp_str,
            end_time_str=event.timestamp_str,
            count=1,
            summary="Une boite arrive physiquement sur T5, mais aucune creation BdD n'est detectee dans les 20 lignes suivantes.",
            symptom="Une boite est rendue sur T5 sans creation BdD detectee juste apres.",
            probable_causes=[
                "Creation BdD absente, retardee ou format de trace non reconnu.",
                "Probleme dans la transition T4->T5 ou l'ajout de boite T5.",
            ],
            checks=[
                "Verifier les lignes proches de l'arrivee physique sur T5.",
                "Verifier la creation/ajout de boite cote BdD.",
            ],
            confidence='possible',
            event_lines=[event.line_num],
        ))
    return incidents


def _build_wait_incidents(frames: list[MachineState]) -> list[DiagnosticIncident]:
    incidents: list[DiagnosticIncident] = []
    checks = [
        ('T4', lambda st: st.state_tT3_T4, lambda st: st.C6),
        ('T5', lambda st: st.state_T5, lambda st: st.C9),
    ]
    threshold = 120.0

    for belt, state_getter, sensor_getter in checks:
        start: MachineState | None = None
        last: MachineState | None = None
        state_name = ''
        for frame in frames:
            current = state_getter(frame)
            is_suspicious = current.startswith('WAIT-') and current != 'WAIT-COND' and sensor_getter(frame) == 0
            if not is_suspicious:
                if start and last and last.timestamp - start.timestamp >= threshold:
                    incidents.append(_wait_incident(belt, state_name, start, last))
                start = None
                last = None
                state_name = ''
                continue
            if start is None or current != state_name:
                if start and last and last.timestamp - start.timestamp >= threshold:
                    incidents.append(_wait_incident(belt, state_name, start, last))
                start = frame
                state_name = current
            last = frame

        if start and last and last.timestamp - start.timestamp >= threshold:
            incidents.append(_wait_incident(belt, state_name, start, last))
    return incidents


def _wait_incident(belt: str, state_name: str, start: MachineState, end: MachineState) -> DiagnosticIncident:
    return DiagnosticIncident(
        severity='warning',
        title=f'{belt} - Attente longue {state_name}',
        belt=belt,
        code=state_name,
        first_line=start.line_num,
        last_line=end.line_num,
        start_time=start.timestamp,
        end_time=end.timestamp,
        start_time_str=start.timestamp_str,
        end_time_str=end.timestamp_str,
        count=1,
        summary=f"Etat {state_name} maintenu pendant environ {int(end.timestamp - start.timestamp)}s.",
        symptom=f"L'etat {state_name} reste actif anormalement longtemps sur {belt}.",
        probable_causes=[
            "Capteur attendu absent ou non stable.",
            "Mouvement non termine ou commande non acquittee.",
            "Verifier les lignes de trace autour du debut de l'attente.",
        ],
        checks=[
            "Ouvrir les lignes au debut de l'attente longue.",
            "Verifier le capteur associe et la commande attendue.",
        ],
        confidence='possible',
        event_lines=[start.line_num, end.line_num],
    )


def _build_t2_blocked_before_ea_incidents(frames: list[MachineState]) -> list[DiagnosticIncident]:
    incidents: list[DiagnosticIncident] = []
    rule = knowledge('t2_block_before_ea')
    start: MachineState | None = None
    last: MachineState | None = None
    threshold = 8.0

    for frame in frames:
        suspicious = (
            frame.state_T2 in ('WAIT-COND-TRSF', 'WAIT-FIN-TRSF')
            and frame.C2 == 1
            and frame.C3 == 1
            and frame.C4 == 0
        )
        if suspicious:
            if start is None:
                start = frame
            last = frame
            continue
        if start and last and last.timestamp - start.timestamp >= threshold:
            incidents.append(DiagnosticIncident(
                severity='warning',
                title='T2 -> EA - Boite probablement bloquee avant C4',
                belt='T2',
                code='T2-EA',
                first_line=start.line_num,
                last_line=last.line_num,
                start_time=start.timestamp,
                end_time=last.timestamp,
                start_time_str=start.timestamp_str,
                end_time_str=last.timestamp_str,
                count=1,
                summary=(
                    "C2 et C3 restent actifs pendant une demande de transfert vers EA "
                    f"sans allumage de C4 pendant environ {int(last.timestamp - start.timestamp)}s."
                ),
                symptom=str(rule.get('symptom', '')),
                probable_causes=list(rule.get('causes', [])),
                checks=list(rule.get('checks', [])),
                confidence=str(rule.get('confidence', '')),
                event_lines=[start.line_num, last.line_num],
            ))
        start = None
        last = None

    if start and last and last.timestamp - start.timestamp >= threshold:
        incidents.append(DiagnosticIncident(
            severity='warning',
            title='T2 -> EA - Boite probablement bloquee avant C4',
            belt='T2',
            code='T2-EA',
            first_line=start.line_num,
            last_line=last.line_num,
            start_time=start.timestamp,
            end_time=last.timestamp,
            start_time_str=start.timestamp_str,
            end_time_str=last.timestamp_str,
            count=1,
            summary=(
                "C2 et C3 restent actifs pendant une demande de transfert vers EA "
                f"sans allumage de C4 pendant environ {int(last.timestamp - start.timestamp)}s."
            ),
            symptom=str(rule.get('symptom', '')),
            probable_causes=list(rule.get('causes', [])),
            checks=list(rule.get('checks', [])),
            confidence=str(rule.get('confidence', '')),
            event_lines=[start.line_num, last.line_num],
        ))
    return incidents


def _build_t4_init_loop_incidents(frames: list[MachineState], events: list[MachineEvent]) -> list[DiagnosticIncident]:
    incidents: list[DiagnosticIncident] = []
    rule = knowledge('t4_init_loop')

    init_frames = [frame for frame in frames if frame.eT4 in {1, 11, 12, 13, 14, 15, 16}]
    t4_minus_18 = [
        event for event in events
        if event.kind == 'ERREUR' and event.title.startswith('T4 en erreur eT:-18')
    ]
    if len(init_frames) >= 12 and len(t4_minus_18) >= 3:
        first = t4_minus_18[0]
        last = t4_minus_18[-1]
        incidents.append(DiagnosticIncident(
            severity='error',
            title='T4 - Boucle d initialisation probable',
            belt='T4',
            code='INIT-LOOP',
            first_line=first.line_num,
            last_line=last.line_num,
            start_time=first.timestamp,
            end_time=last.timestamp,
            start_time_str=first.timestamp_str,
            end_time_str=last.timestamp_str,
            count=len(t4_minus_18),
            summary=(
                f"T4 repete des erreurs d'initialisation (-18) {len(t4_minus_18)} fois "
                "sans stabilisation visible."
            ),
            symptom=str(rule.get('symptom', '')),
            probable_causes=list(rule.get('causes', [])),
            checks=list(rule.get('checks', [])),
            confidence=str(rule.get('confidence', '')),
            event_lines=[event.line_num for event in t4_minus_18[:12]],
        ))
    return incidents


def _build_text_pattern_incidents(frames: list[MachineState]) -> list[DiagnosticIncident]:
    incidents: list[DiagnosticIncident] = []
    patterns = [
        (
            'T5 - Vidage complet demande par le robot',
            'T5',
            'DemVidageComplet',
            _TRACE_T5_DEM_VIDAGE,
            't5_dem_vidage_complet',
            'warning',
            "Le robot demande plusieurs vidages complets de T5 apres perturbation de prise.",
            2,
        ),
        (
            'C4 - Boite coincee apres ejects',
            'EA',
            '017-Avt',
            _TRACE_017,
            'code_017_c4_eject',
            'warning',
            "La trace signale une boite coincee sur C4 apres plusieurs ejects.",
            1,
        ),
        (
            'Carte moteurs - Defaut communication',
            'MOTOR',
            '028-Avt',
            _TRACE_028,
            'code_028_motor_comm',
            'error',
            "La trace remonte un defaut de communication carte moteurs.",
            1,
        ),
        (
            'T5 - Vidage suite blocage poubelle',
            'T5',
            '118-Vide T5',
            _TRACE_118,
            'code_118_t5_bin_block',
            'warning',
            "Le T5 est vide suite a un blocage poubelle.",
            1,
        ),
        (
            'T4 - Initialisation terminee sur erreur -18',
            'T4',
            'INIT-18',
            _TRACE_T4_INIT_ERR,
            't4_error_minus_18',
            'error',
            "La trace textuelle confirme une fin d'initialisation T4 sur ERREUR -18.",
            1,
        ),
    ]

    lines = _frame_lines(frames)
    for title, belt, code, pattern, rule_id, severity, summary, minimum_count in patterns:
        matched = [(line_num, ts, ts_str) for line_num, text, ts, ts_str in lines if pattern.search(text)]
        if len(matched) < minimum_count:
            continue
        rule = knowledge(rule_id)
        first_line, first_ts, first_ts_str = matched[0]
        last_line, last_ts, last_ts_str = matched[-1]
        incidents.append(DiagnosticIncident(
            severity=severity,
            title=title,
            belt=belt,
            code=code,
            first_line=first_line,
            last_line=last_line,
            start_time=first_ts,
            end_time=last_ts,
            start_time_str=first_ts_str,
            end_time_str=last_ts_str,
            count=len(matched),
            summary=summary,
            symptom=str(rule.get('symptom', '')),
            probable_causes=list(rule.get('causes', [])),
            checks=list(rule.get('checks', [])),
            confidence=str(rule.get('confidence', '')),
            event_lines=[line_num for line_num, _, _ in matched[:12]],
        ))
    return incidents


def build_diagnostics(
    frames: list[MachineState],
    events: list[MachineEvent],
) -> list[DiagnosticIncident]:
    incidents: list[DiagnosticIncident] = []
    incidents.extend(_build_motor_error_incidents(events))
    incidents.extend(_build_t4_diff_incidents(events))
    incidents.extend(_build_missing_c6_incidents(events))
    incidents.extend(_build_missing_t5_creation_incidents(events))
    incidents.extend(_build_wait_incidents(frames))
    incidents.extend(_build_t2_blocked_before_ea_incidents(frames))
    incidents.extend(_build_t4_init_loop_incidents(frames, events))
    incidents.extend(_build_text_pattern_incidents(frames))

    severity_order = {'error': 0, 'warning': 1, 'info': 2}
    return sorted(
        incidents,
        key=lambda incident: (
            severity_order.get(incident.severity, 9),
            incident.first_line,
            incident.title,
        ),
    )
