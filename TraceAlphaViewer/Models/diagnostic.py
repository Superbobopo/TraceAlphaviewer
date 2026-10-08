from __future__ import annotations

import re
from dataclasses import dataclass, field

from Models.dimension_check import (
    DIMENSION_TOLERANCE_MM,
    dimension_finding_code as _shared_dimension_finding_code,
    dimension_ok as _shared_dimension_ok,
    dimension_tuple_matches_unordered as _shared_dimension_tuple_matches_unordered,
)
from Models.et_codes import et_description
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
_TRACE_T4_INIT_REQUEST = re.compile(r'InitMachine:\s+demande initialisation de T4', re.IGNORECASE)
_TRACE_T5_DEM_VIDAGE = re.compile(r'OMEGA:T5-DemVidageComplet', re.IGNORECASE)
_TRACE_017 = re.compile(r'017-Avt:\s*boite coinc.ee sur C4 apr.s .* ejects', re.IGNORECASE)
_TRACE_C4_STUCK_AFTER_EJECTS = re.compile(
    r'boite\s+coinc\S*\s+sur\s+C4\s+apr\S*s.*ject',
    re.IGNORECASE,
)
_TRACE_028 = re.compile(r'028-Avt:\s*d.faut communication carte moteurs', re.IGNORECASE)
_TRACE_118 = re.compile(r'118-Vide T5 suite blocage poubelle', re.IGNORECASE)
_ALPHA_RESET_UPTIME = re.compile(
    r'Temps depuis RESET carte ALPHA\s*:\s*(\d+)\s*mn',
    re.IGNORECASE,
)
_ALPHA_RESET_MAX_RESTART_MINUTES = 10
_ALPHA_RESET_MIN_DROP_MINUTES = 5
_CUBESTOP_INFO = re.compile(r'\bCubeStop:([YN])\b', re.IGNORECASE)
_CUBESTOP_MOVE = re.compile(
    r'mvt\s+CubeStop\s+vers\s+le\s+(HAUT|BAS)(?:\s*\((.*?)\))?',
    re.IGNORECASE,
)
_CUBESTOP_TEA = re.compile(
    r'tEA-T3:\s+(\S+)\s+C4:(\d+)\s+C5:(\d+)\s+fgBfinT3:(\d+)'
    r'\s+eT3:(-?\d+)\s+pT3:(-?\d+)mm',
    re.IGNORECASE,
)
_CUBESTOP_TEA_ERROR = re.compile(r'tEA-T3:\s+ERREUR transfert EA->T3\s+(-?\d+)', re.IGNORECASE)
_CUBESTOP_TRANSFER_DONE = re.compile(r'le transfert \(EA->T3\) est termin', re.IGNORECASE)
_CAMERA_HIST = re.compile(
    r'\bCB([12]):\s+ajout Hist_LectCB .*?boite n\S*?(\d+)\s+(\d+)code\(s\) lu\(s\)',
    re.IGNORECASE,
)
_CAMERA_UNKNOWN_REF = re.compile(r'idCB([12]):\s+-->\s+R\S*f:(ALPHA-(?:INC|DET|DIF)\S*)', re.IGNORECASE)
_CAMERA_UNKNOWN_CREATE = re.compile(
    r"Cr\S*ation de la boite '([^']*ALPHA-(?:INC|DET|DIF)[^']*)'\s+-?unknow",
    re.IGNORECASE,
)
_CAMERA_SUCCESS_READER = re.compile(r'\bidCB([12]):', re.IGNORECASE)
_CAMERA_SUCCESS_TOKEN = re.compile(r'(?:/Soh/|<Soh>|\x01)(\d+)', re.IGNORECASE)
_CAMERA_UNKNOWN_THRESHOLD = 0.07
_CAMERA_MIN_BOXES_FOR_INACTIVE = 50
_CAMERA_EXPECTED = {
    'CB1': ('1', '2', '4', '5', '6'),
    'CB2': ('3',),
}
_DIMENSION_TOLERANCE_MM = DIMENSION_TOLERANCE_MM
_T5_WIDTH_C9_INVALID = re.compile(
    r'largeur lue sur T5\s*<\s*2mm\s+et\s+C9=1',
    re.IGNORECASE,
)
_T5_LIST_SEPARATORS = ("<Dc2>", chr(182))
_T5_BOX_CREATE = re.compile(
    r"Cr\S*ation de la boite '([^']*)'\s+(.+?)\s+x=(\d+)"
    r"\s+\((\d+)x(\d+)x(\d+)\)\s+IdA:(\d+)",
    re.IGNORECASE,
)
_T5_AJOUT = re.compile(r"AjoutBtT5\.idA(\d+)\.idB(-?\d+)", re.IGNORECASE)
_T5_BUTEE = re.compile(
    r"MAJ \(BUTEE-T5\) boite Id:(\d+) ref:(\S*).*?nvlle dim:\d+x(\d+)\s+X:(\d+)",
    re.IGNORECASE,
)
_T5_MESURE = re.compile(
    r"MAJ \(APRES-MESURE-LARG\) bt IdA:(\d+) '([^']*)'.*?"
    r"nvlle lxH:(\d+)x(\d+) \[x(\d+)\] X:(\d+)",
    re.IGNORECASE,
)
_T5_REMOVE = re.compile(r"supp\. de T5 la boite Id:(\d+)\s+ref:(\S+)", re.IGNORECASE)
_T5_REMOVE2 = re.compile(r"-suppression de la boite ID:(\d+)", re.IGNORECASE)
_T5_REMOVE3 = re.compile(r"Suppr\. la boite IdA:(\d+)", re.IGNORECASE)
_T5_NO_SPACE = re.compile(r"pas assez de place", re.IGNORECASE)
_T5_VIDAGE = re.compile(r"DEM-VIDAGE|demande de vidage complet|AvVideCompletDeT5", re.IGNORECASE)
_T5_STALE_MIN_SECONDS = 120
_T5_STALE_MIN_NO_SPACE = 5
_DIMENSION_CONTEXT_PATTERNS = (
    ('boite trop proche', re.compile(r'A DETRUIRE|trop pr', re.IGNORECASE)),
    ('vidage T5', re.compile(r'T5-DemVidageComplet|Une demande de vidage complet', re.IGNORECASE)),
    ('poubelle pleine longue', re.compile(r'FlagPoubellePleineLong', re.IGNORECASE)),
    ('suppression T5', re.compile(r'T5-DEL-PACK|supp\. de T5|Suppr\. la boite|suppression de la boite', re.IGNORECASE)),
)
_T4_INIT_MIN_REPEAT = 3
_T4_NORMAL_CYCLE_TITLES = (
    'T3 vers T4 demarre',
    'Mesure longueur T4 en cours',
    'C6 declenche longueur',
    'T3 vers T4 termine',
    'Transfert T4 vers T5 demarre',
    'Retour index T4 apres depot',
    'Cycle T4 termine',
    'T3->T4 en cours',
    'T3->T4 idB=',
    'T4 vers T5',
)


def _frame_line_states(frames: list[MachineState]) -> list[tuple[int, str, MachineState]]:
    lines: list[tuple[int, str, MachineState]] = []
    seen: set[int] = set()
    for frame in frames:
        for line_num, text, *_ in frame.raw_lines:
            if line_num in seen:
                continue
            seen.add(line_num)
            lines.append((line_num, text, frame))
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
    desc = et_description(belt, code)
    if desc:
        return f'{belt} eT:{code} - {desc}'
    return f'{belt} eT:{code} - Erreur moteur non documentee'


def _motor_error_causes(belt: str, code: str) -> list[str]:
    if belt == 'T2' and code == '-88':
        return list(knowledge('t2_error_minus_88_c4').get('causes', []))
    if belt == 'T3' and code == '-43':
        return list(knowledge('t3_error_minus_43_c4_stuck').get('causes', []))
    if belt == 'T3' and code == '-48':
        return list(knowledge('t3_error_minus_48_c4_missing').get('causes', []))
    if belt == 'T4' and code == '-18':
        return list(knowledge('t4_error_minus_18').get('causes', []))
    return list(knowledge('motor_error_generic').get('causes', []))


def _motor_error_rule_id(belt: str, code: str) -> str:
    if belt == 'T2' and code == '-88':
        return 't2_error_minus_88_c4'
    if belt == 'T3' and code == '-43':
        return 't3_error_minus_43_c4_stuck'
    if belt == 'T3' and code == '-48':
        return 't3_error_minus_48_c4_missing'
    if belt == 'T4' and code == '-18':
        return 't4_error_minus_18'
    return 'motor_error_generic'


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
        rule = knowledge(_motor_error_rule_id(belt, code))
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
        if event.kind == 'BOITE' and event.title.startswith('T4->T5')
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


def _build_cubestop_c4_blocked_incidents(
    line_states: list[tuple[int, str, MachineState]],
) -> list[DiagnosticIncident]:
    has_cubestop = False
    for _, text, _ in line_states:
        info = _CUBESTOP_INFO.search(text)
        if info and info.group(1).upper() == 'Y':
            has_cubestop = True
            break
        if _CUBESTOP_MOVE.search(text):
            has_cubestop = True
            break
    if not has_cubestop:
        return []

    attempts: list[dict[str, object]] = []
    last_haut: tuple[int, float, str, str] | None = None
    active: dict[str, object] | None = None

    def start_attempt(line_num: int, state: MachineState) -> dict[str, object]:
        haut_line, haut_ts, haut_ts_str, haut_reason = last_haut or (
            line_num,
            state.timestamp,
            state.timestamp_str,
            '',
        )
        return {
            'first_line': haut_line,
            'last_line': line_num,
            'start_time': haut_ts,
            'end_time': state.timestamp,
            'start_time_str': haut_ts_str,
            'end_time_str': state.timestamp_str,
            'reason': haut_reason,
            'lines': [haut_line, line_num] if haut_line != line_num else [line_num],
            'samples': 0,
            'near_end': False,
            'error_code': '',
            'explicit': False,
        }

    def remember_line(attempt: dict[str, object], line_num: int, state: MachineState) -> None:
        attempt['last_line'] = line_num
        attempt['end_time'] = state.timestamp
        attempt['end_time_str'] = state.timestamp_str
        lines = attempt.setdefault('lines', [])
        if isinstance(lines, list) and line_num not in lines and len(lines) < 16:
            lines.append(line_num)

    def close_attempt(force_issue: bool = False, success: bool = False) -> None:
        nonlocal active
        if not active:
            return
        issue = (
            force_issue
            or bool(active.get('explicit'))
            or bool(active.get('error_code'))
            or bool(active.get('near_end'))
        )
        if success or not issue or int(active.get('samples', 0)) < 2:
            active = None
            return
        attempts.append(active)
        active = None

    for line_num, text, state in line_states:
        move = _CUBESTOP_MOVE.search(text)
        if move:
            position = move.group(1).upper()
            reason = (move.group(2) or '').strip()
            if position == 'HAUT':
                close_attempt(force_issue=True)
                last_haut = (line_num, state.timestamp, state.timestamp_str, reason)
            elif active:
                close_attempt(force_issue=bool(active.get('near_end') or active.get('error_code')))

        explicit_stuck = _TRACE_C4_STUCK_AFTER_EJECTS.search(text) or _TRACE_017.search(text)
        if explicit_stuck:
            if active is None:
                active = start_attempt(line_num, state)
            active['explicit'] = True
            active['error_code'] = active.get('error_code') or '-43'
            remember_line(active, line_num, state)
            close_attempt(force_issue=True)
            continue

        error = _CUBESTOP_TEA_ERROR.search(text)
        if error and active is not None:
            active['error_code'] = error.group(1)
            remember_line(active, line_num, state)

        tea = _CUBESTOP_TEA.search(text)
        if tea:
            task = tea.group(1)
            c4 = int(tea.group(2))
            c5 = int(tea.group(3))
            e_t3 = int(tea.group(5))
            p_t3 = int(tea.group(6))
            if (
                task == 'DEM-TRSF'
                and c4 == 1
                and c5 == 0
                and last_haut is not None
                and state.timestamp - last_haut[1] <= 90
            ):
                active = start_attempt(line_num, state)

            if active is not None:
                remember_line(active, line_num, state)
                if c4 == 0 or c5 == 1 or _CUBESTOP_TRANSFER_DONE.search(text):
                    close_attempt(success=True)
                    continue
                if c4 == 1 and c5 == 0 and task in {'DEM-TRSF', 'WAIT-FIN-TRSF', 'ERREUR'}:
                    active['samples'] = int(active.get('samples', 0)) + 1
                    if p_t3 <= -430:
                        active['near_end'] = True
                    if e_t3 < 0 or task == 'ERREUR':
                        active['error_code'] = str(e_t3)

        elif active is not None and _CUBESTOP_TRANSFER_DONE.search(text):
            close_attempt(success=True)

    close_attempt(force_issue=True)
    if not attempts:
        return []

    attempts.sort(key=lambda item: int(item['first_line']))
    first = attempts[0]
    last = attempts[-1]
    explicit = any(bool(item.get('explicit')) for item in attempts)
    severity = 'error' if explicit or len(attempts) >= 2 else 'warning'
    examples = []
    event_lines: list[int] = []
    for item in attempts[:4]:
        error_code = f" eT3:{item['error_code']}" if item.get('error_code') else ""
        examples.append(
            f"L.{item['first_line']}->{item['last_line']} "
            f"C4 reste actif pendant transfert EA->T3{error_code}"
        )
        key_lines = [int(item['first_line']), int(item['last_line'])]
        key_lines.extend(line for line in item.get('lines', []) if isinstance(line, int))
        for line in key_lines:
            if isinstance(line, int) and line not in event_lines:
                event_lines.append(line)

    rule = knowledge('cubestop_c4_blocked')
    return [DiagnosticIncident(
        severity=severity,
        title='CubeStop / C4 - Passage vers T3 bloque',
        belt='EA',
        code='CUBESTOP_C4_BLOCKED',
        first_line=int(first['first_line']),
        last_line=int(last['last_line']),
        start_time=float(first['start_time']),
        end_time=float(last['end_time']),
        start_time_str=str(first['start_time_str']),
        end_time_str=str(last['end_time_str']),
        count=len(attempts),
        summary=(
            f"{len(attempts)} tentative(s) suspecte(s): le CubeStop est commande en haut, "
            "le transfert EA->T3 est demande, mais C4 reste actif et C5 ne voit pas la boite. "
            f"Exemples: {'; '.join(examples)}."
        ),
        symptom=str(rule.get('symptom', '')),
        probable_causes=list(rule.get('causes', [])),
        checks=list(rule.get('checks', [])),
        confidence=str(rule.get('confidence', '')),
        event_lines=event_lines[:12],
    )]


def _is_t4_normal_cycle_event(event: MachineEvent) -> bool:
    if event.kind not in {'T4', 'TRANSFERT'}:
        return False
    return any(event.title.startswith(title) for title in _T4_NORMAL_CYCLE_TITLES)


def _c6_stats_for_lines(
    line_states: list[tuple[int, str, MachineState]],
    first_line: int,
    last_line: int,
) -> tuple[int, int]:
    samples = [
        state.C6
        for line_num, _, state in line_states
        if first_line <= line_num <= last_line
    ]
    if not samples:
        return 0, 0
    active_count = sum(1 for value in samples if value == 1)
    return active_count, len(samples)


def _t4_repeated_init_incident(
    sequence: list[tuple[int, MachineState]],
    line_states: list[tuple[int, str, MachineState]],
    events: list[MachineEvent],
) -> DiagnosticIncident:
    first_line, first_state = sequence[0]
    last_line, last_state = sequence[-1]
    active_count, sample_count = _c6_stats_for_lines(line_states, first_line, last_line)
    c6_stuck_active = sample_count > 0 and active_count == sample_count
    rule_id = 't4_init_repeated_c6_active' if c6_stuck_active else 't4_init_repeated_index_missing'
    rule = knowledge(rule_id)
    minus_18 = [
        event for event in events
        if first_line <= event.line_num <= last_line
        and event.kind == 'ERREUR'
        and event.title.startswith('T4 en erreur eT:-18')
    ]
    summary = (
        f"{len(sequence)} demande(s) d'initialisation T4 d'affilee, "
        f"de L.{first_line} a L.{last_line}."
    )
    if sample_count:
        summary += f" C6 actif sur {active_count}/{sample_count} etat(s) observes."
    if minus_18:
        summary += f" Erreur eT:-18 observee {len(minus_18)} fois dans la sequence."

    return DiagnosticIncident(
        severity='error',
        title=(
            'T4 - Initialisations repetees avec C6 toujours actif'
            if c6_stuck_active
            else 'T4 - Initialisations repetees, index C6 non retrouve'
        ),
        belt='T4',
        code='INIT-C6' if c6_stuck_active else 'INIT-INDEX',
        first_line=first_line,
        last_line=last_line,
        start_time=first_state.timestamp,
        end_time=last_state.timestamp,
        start_time_str=first_state.timestamp_str,
        end_time_str=last_state.timestamp_str,
        count=len(sequence),
        summary=summary,
        symptom=str(rule.get('symptom', '')),
        probable_causes=list(rule.get('causes', [])),
        checks=list(rule.get('checks', [])),
        confidence=str(rule.get('confidence', '')),
        event_lines=[line_num for line_num, _ in sequence[:12]],
    )


def _build_t4_init_loop_incidents(
    line_states: list[tuple[int, str, MachineState]],
    events: list[MachineEvent],
) -> list[DiagnosticIncident]:
    incidents: list[DiagnosticIncident] = []
    markers: list[tuple[int, str, MachineState | MachineEvent]] = []
    for line_num, text, state in line_states:
        if _TRACE_T4_INIT_REQUEST.search(text):
            markers.append((line_num, 'init', state))
    for event in events:
        if _is_t4_normal_cycle_event(event):
            markers.append((event.line_num, 'reset', event))

    sequence: list[tuple[int, MachineState]] = []
    for line_num, marker, payload in sorted(markers, key=lambda item: (item[0], 0 if item[1] == 'reset' else 1)):
        if marker == 'reset':
            if len(sequence) >= _T4_INIT_MIN_REPEAT:
                incidents.append(_t4_repeated_init_incident(sequence, line_states, events))
            sequence = []
            continue
        if isinstance(payload, MachineState):
            sequence.append((line_num, payload))

    if len(sequence) >= _T4_INIT_MIN_REPEAT:
        incidents.append(_t4_repeated_init_incident(sequence, line_states, events))
    return incidents


def _build_text_pattern_incidents(
    line_states: list[tuple[int, str, MachineState]],
) -> list[DiagnosticIncident]:
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
    ]

    for title, belt, code, pattern, rule_id, severity, summary, minimum_count in patterns:
        matched = [
            (line_num, state.timestamp, state.timestamp_str)
            for line_num, text, state in line_states
            if pattern.search(text)
        ]
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


def _duration_text(seconds: float) -> str:
    duration = max(0, int(seconds))
    minutes, seconds = divmod(duration, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _build_alpha_card_reset_incident(
    line_states: list[tuple[int, str, MachineState]],
) -> list[DiagnosticIncident]:
    readings: list[tuple[int, int, MachineState]] = []
    for line_num, text, state in line_states:
        match = _ALPHA_RESET_UPTIME.search(text)
        if match:
            readings.append((line_num, int(match.group(1)), state))
    if not readings:
        return []

    resets: list[tuple[tuple[int, int, MachineState], tuple[int, int, MachineState], int]] = []
    for index in range(1, len(readings)):
        previous = readings[index - 1]
        current = readings[index]
        drop = previous[1] - current[1]
        if current[1] <= _ALPHA_RESET_MAX_RESTART_MINUTES and drop >= _ALPHA_RESET_MIN_DROP_MINUTES:
            resets.append((previous, current, index))

    trace_duration = _duration_text(line_states[-1][2].timestamp - line_states[0][2].timestamp)
    rule = knowledge('alpha_card_reset')
    if not resets:
        first_line, first_uptime, first_state = readings[0]
        last_line, last_uptime, last_state = readings[-1]
        summary = (
            f"0 reset carte Alpha detecte sur {trace_duration} de trace. "
            f"Compteur observe de {first_uptime} a {last_uptime} mn "
            f"({len(readings)} releve(s))."
        )
        return [DiagnosticIncident(
            severity='info',
            title='Carte Alpha - Aucun reset detecte',
            belt='ALPHA',
            code='ALPHA_CARD_RESET',
            first_line=first_line,
            last_line=last_line,
            start_time=first_state.timestamp,
            end_time=last_state.timestamp,
            start_time_str=first_state.timestamp_str,
            end_time_str=last_state.timestamp_str,
            count=0,
            summary=summary,
            symptom="Le compteur d'uptime de la carte Alpha ne redescend pas dans la trace.",
            probable_causes=[],
            checks=["Aucune action requise sur la base de ce compteur."],
            confidence='forte',
            event_lines=[first_line, last_line] if first_line != last_line else [first_line],
        )]

    event_lines: list[int] = []
    evidence: list[str] = []
    for previous, current, index in resets:
        event_lines.extend([previous[0], current[0]])
        event_lines.extend(item[0] for item in readings[index + 1:index + 4])
        evidence.append(
            f"{previous[1]} -> {current[1]} mn a {current[2].timestamp_str} (L.{current[0]})"
        )
    first_reset = resets[0][1]
    last_reset = resets[-1][1]
    summary = (
        f"{len(resets)} reset(s) carte Alpha detecte(s) sur {trace_duration} de trace. "
        + " ; ".join(evidence[:4])
        + "."
    )
    return [DiagnosticIncident(
        severity='error',
        title='Carte Alpha - Reset inattendu detecte',
        belt='ALPHA',
        code='ALPHA_CARD_RESET',
        first_line=first_reset[0],
        last_line=last_reset[0],
        start_time=first_reset[2].timestamp,
        end_time=last_reset[2].timestamp,
        start_time_str=first_reset[2].timestamp_str,
        end_time_str=last_reset[2].timestamp_str,
        count=len(resets),
        summary=summary,
        symptom=str(rule.get('symptom', '')),
        probable_causes=list(rule.get('causes', [])),
        checks=list(rule.get('checks', [])),
        confidence=str(rule.get('confidence', 'forte')),
        event_lines=list(dict.fromkeys(event_lines)),
    )]


def _dimension_ok(measured: int, expected: int) -> bool:
    return _shared_dimension_ok(measured, expected)


def _dimension_tuple_matches_unordered(
    measured: tuple[int, int, int],
    expected: tuple[int, int, int],
) -> bool:
    return _shared_dimension_tuple_matches_unordered(measured, expected)


def _dimension_context_labels(
    line_states: list[tuple[int, str, MachineState]],
    line_num: int,
    margin: int = 30,
) -> list[str]:
    labels: list[str] = []
    for current_line, text, _ in line_states:
        if current_line < line_num - margin or current_line > line_num + margin:
            continue
        for label, pattern in _DIMENSION_CONTEXT_PATTERNS:
            if label not in labels and pattern.search(text):
                labels.append(label)
    return labels


def _dimension_box_label(box) -> str:
    if box.id_alpha:
        return f'IdA:{box.id_alpha}'
    if box.id_b:
        return f'idB:{box.id_b}'
    return box.barcode or box.source_ref or 'boite'


def _dimension_finding_code(
    measured: tuple[int, int, int],
    expected: tuple[int, int, int],
) -> str:
    return _shared_dimension_finding_code(measured, expected)


def _dimension_title(code: str) -> str:
    titles = {
        'ORIENTATION': 'Dimensions - Boite dans une orientation differente',
        'T4_LENGTH': 'Dimensions - Longueur T4/C6 incoherente',
        'T5_HEIGHT': 'Dimensions - Hauteur T5/LzB incoherente',
        'T5_WIDTH': 'Dimensions - Largeur T5/C9 incoherente',
        'GLOBAL': 'Dimensions - Mesures incoherentes avec la BdD',
    }
    return titles.get(code, 'Dimensions - Mesures incoherentes')


def _dimension_causes_checks(code: str) -> tuple[list[str], list[str], str]:
    if code == 'ORIENTATION':
        return (
            ["Boite presentee dans un autre sens ou sur la tranche."],
            ["Verifier l'orientation physique avant de conclure a un capteur defaillant."],
            'probable',
        )
    if code == 'T4_LENGTH':
        return (
            ["Mesure C6/T4 decalee.", "Moteur ou rouleau T4 qui patine.", "Boite mal entrainee sur T4."],
            ["Comparer T4C/T4T a la longueur BdD.", "Verifier C6, moteur et rouleau T4."],
            'probable',
        )
    if code == 'T5_HEIGHT':
        return (
            ["Capteur hauteur T5 mal calibre, desserre ou perturbe."],
            ["Verifier LzB et la fixation/calibration du capteur hauteur."],
            'probable',
        )
    if code == 'T5_WIDTH':
        return (
            ["Mesure C9/T5 decalee.", "Boite pas correctement posee ou mouvement T5 perturbe."],
            ["Verifier C9, la mecanique T5 et la trajectoire de retour position repos."],
            'probable',
        )
    return (
        [
            "Boite bloquee avant la butee T5 ou mauvais tassement.",
            "Mesures perturbees par une boite deja presente.",
            "Probleme mecanique T4/T5 ou capteur C6/C9/hauteur.",
        ],
        [
            "Chercher les lignes 'A DETRUIRE car trop proche' et les vidages T5 proches.",
            "Verifier que la boite atteint bien la butee avant la mesure largeur.",
            "Comparer C6, LzB et C9 sur la meme boite.",
        ],
        'probable',
    )


def _build_dimension_incidents(
    frames: list[MachineState],
    line_states: list[tuple[int, str, MachineState]],
) -> list[DiagnosticIncident]:
    findings_by_code: dict[str, list[dict[str, object]]] = {}
    seen: set[tuple[object, tuple[int, int, int], tuple[int, int, int]]] = set()

    for frame in frames:
        for box in frame.boxes_on_T5:
            expected = (box.bdd_width_mm, box.bdd_height_mm, box.bdd_length_mm)
            if any(value <= 0 for value in expected):
                continue
            measured_length = box.measured_t4_length_mm or box.measured_t5_length_mm
            if box.measured_t5_width_mm <= 0 or measured_length <= 0:
                continue
            measured = (box.measured_t5_width_mm, box.measured_t5_height_mm, measured_length)
            code = _dimension_finding_code(measured, expected)
            if not code:
                continue
            key_id = box.id_alpha or box.id_b or box.barcode or box.source_ref
            key = (key_id, expected, measured)
            if key in seen:
                continue
            seen.add(key)
            findings_by_code.setdefault(code, []).append({
                'line': frame.line_num,
                'time': frame.timestamp,
                'time_str': frame.timestamp_str,
                'box': _dimension_box_label(box),
                'barcode': box.barcode or box.source_ref,
                'expected': expected,
                'measured': measured,
                'context': _dimension_context_labels(line_states, frame.line_num),
            })

    incidents: list[DiagnosticIncident] = []
    for code, findings in findings_by_code.items():
        findings.sort(key=lambda item: int(item['line']))
        first = findings[0]
        last = findings[-1]
        examples = []
        context_labels: list[str] = []
        for item in findings:
            for label in item['context']:
                if label not in context_labels:
                    context_labels.append(label)
            if len(examples) >= 4:
                continue
            expected = item['expected']
            measured = item['measured']
            examples.append(
                f"{item['box']} {item['barcode']} mesure "
                f"{measured[0]}x{measured[1]}x{measured[2]} "
                f"pour BdD {expected[0]}x{expected[1]}x{expected[2]}"
            )
        context = f" Contexte proche: {', '.join(context_labels)}." if context_labels else ""
        summary = (
            f"{len(findings)} boite(s) avec dimensions hors tolerance "
            f"(>{_DIMENSION_TOLERANCE_MM}mm). "
            f"Exemples: {'; '.join(examples)}.{context}"
        )
        causes, checks, confidence = _dimension_causes_checks(code)
        incidents.append(DiagnosticIncident(
            severity='warning',
            title=_dimension_title(code),
            belt='T5' if code != 'T4_LENGTH' else 'T4',
            code=code,
            first_line=int(first['line']),
            last_line=int(last['line']),
            start_time=float(first['time']),
            end_time=float(last['time']),
            start_time_str=str(first['time_str']),
            end_time_str=str(last['time_str']),
            count=len(findings),
            summary=summary,
            symptom="Les dimensions mesurees ne correspondent pas aux dimensions BdD attendues.",
            probable_causes=causes,
            checks=checks,
            confidence=confidence,
            event_lines=[int(item['line']) for item in findings[:12]],
        ))
    return incidents


def _iter_t5_list_records(text: str) -> list[list[str]]:
    if 'ALPHA:T5-LIST-PACK' not in text:
        return []
    records: list[list[str]] = []
    for separator in _T5_LIST_SEPARATORS:
        if separator not in text:
            continue
        for part in text.split('@'):
            if separator not in part:
                continue
            fields = part.split(separator)
            if fields and fields[0] == '':
                fields = fields[1:]
            if len(fields) >= 23 and fields[0].isdigit():
                records.append(fields)
        if records:
            break
    return records


def _t5_box_label(info: dict[str, object]) -> str:
    parts: list[str] = []
    if info.get('id'):
        parts.append(f"IdA:{info['id']}")
    if info.get('id_b'):
        parts.append(f"idB:{info['id_b']}")
    if info.get('name'):
        parts.append(str(info['name']))
    elif info.get('barcode'):
        parts.append(str(info['barcode']))
    return ' | '.join(parts) if parts else 'boite T5'


def _build_stale_unmeasured_t5_incidents(
    line_states: list[tuple[int, str, MachineState]],
) -> list[DiagnosticIncident]:
    boxes: dict[int, dict[str, object]] = {}
    no_space_lines: list[tuple[int, float, str]] = []
    recent_vidage_line = 0

    def ensure_box(id_a: int, line_num: int, state: MachineState) -> dict[str, object]:
        info = boxes.get(id_a)
        if info is None:
            info = {
                'id': id_a,
                'first_line': line_num,
                'last_line': line_num,
                'first_time': state.timestamp,
                'last_time': state.timestamp,
                'first_time_str': state.timestamp_str,
                'last_time_str': state.timestamp_str,
                'event_lines': [],
                'id_b': 0,
                'barcode': '',
                'name': '',
                'created_line': 0,
                'butee_line': 0,
                'measured_line': 0,
                'removed_line': 0,
                'removed_by_vidage': False,
                'width_zero_seen': False,
                'status_n_seen': False,
                'last_x': '',
            }
            boxes[id_a] = info
        info['last_line'] = max(int(info['last_line']), line_num)
        info['last_time'] = max(float(info['last_time']), state.timestamp)
        info['last_time_str'] = state.timestamp_str
        if line_num not in info['event_lines']:
            info['event_lines'].append(line_num)
        return info

    for line_num, text, state in line_states:
        if _T5_NO_SPACE.search(text):
            no_space_lines.append((line_num, state.timestamp, state.timestamp_str))
        if _T5_VIDAGE.search(text):
            recent_vidage_line = line_num

        mo = _T5_BOX_CREATE.search(text)
        if mo:
            id_a = int(mo.group(7))
            info = ensure_box(id_a, line_num, state)
            info['created_line'] = line_num
            info['barcode'] = mo.group(1)
            info['name'] = mo.group(2).strip()
            info['width_zero_seen'] = info['width_zero_seen'] or int(mo.group(4)) <= 0
            info['first_line'] = min(int(info['first_line']), line_num)
            info['first_time'] = min(float(info['first_time']), state.timestamp)
            info['first_time_str'] = state.timestamp_str

        mo = _T5_AJOUT.search(text)
        if mo:
            info = ensure_box(int(mo.group(1)), line_num, state)
            info['id_b'] = int(mo.group(2))

        mo = _T5_BUTEE.search(text)
        if mo:
            info = ensure_box(int(mo.group(1)), line_num, state)
            info['butee_line'] = line_num
            info['barcode'] = info.get('barcode') or mo.group(2)
            info['width_zero_seen'] = True
            info['last_x'] = mo.group(4)

        mo = _T5_MESURE.search(text)
        if mo:
            info = ensure_box(int(mo.group(1)), line_num, state)
            info['measured_line'] = line_num
            info['barcode'] = info.get('barcode') or mo.group(2)

        for record in _iter_t5_list_records(text):
            id_a = int(record[0])
            info = ensure_box(id_a, line_num, state)
            info['barcode'] = info.get('barcode') or record[2]
            info['name'] = info.get('name') or record[3]
            info['status_n_seen'] = info['status_n_seen'] or record[1] == 'N'
            info['width_zero_seen'] = info['width_zero_seen'] or int(record[4] or 0) <= 0
            info['last_x'] = record[13]

        remove_match = _T5_REMOVE.search(text) or _T5_REMOVE2.search(text) or _T5_REMOVE3.search(text)
        if remove_match:
            id_a = int(remove_match.group(1))
            info = ensure_box(id_a, line_num, state)
            info['removed_line'] = line_num
            info['removed_by_vidage'] = recent_vidage_line and line_num - recent_vidage_line <= 20

    incidents: list[DiagnosticIncident] = []
    for id_a, info in sorted(boxes.items()):
        if info.get('measured_line'):
            continue
        if not info.get('width_zero_seen'):
            continue
        if not info.get('status_n_seen') and not info.get('butee_line'):
            continue

        first_line = int(info['first_line'])
        last_line = int(info.get('removed_line') or info['last_line'])
        first_time = float(info['first_time'])
        last_time = float(info['last_time'])
        duration = max(0, int(last_time - first_time))
        no_space = [
            item for item in no_space_lines
            if first_line <= item[0] <= last_line
        ]
        following = [
            other for other_id, other in boxes.items()
            if other_id != id_a
            and int(other['first_line']) > first_line
            and int(other['first_line']) <= last_line
            and not other.get('measured_line')
            and other.get('width_zero_seen')
        ]
        if (
            duration < _T5_STALE_MIN_SECONDS
            and len(no_space) < _T5_STALE_MIN_NO_SPACE
            and not following
        ):
            continue

        following_labels = '; '.join(_t5_box_label(other) for other in following[:4])
        no_space_text = f"{len(no_space)} message(s) 'pas assez de place'"
        removal = "suppression pendant vidage T5" if info.get('removed_by_vidage') else "suppression/fin de presence T5"
        summary = (
            f"{_t5_box_label(info)} reste sur T5 sans MAJ (APRES-MESURE-LARG), "
            f"avec largeur 0/statut non valide. Duree observee {duration}s, {no_space_text}. "
            f"Derniere position X connue: {info.get('last_x') or '-'}. {removal}."
        )
        if following_labels:
            summary += f" Boite(s) suivante(s) egalement bloquees ou non mesurees: {following_labels}."

        useful_lines = [
            int(value) for value in [
                info.get('created_line'),
                info.get('butee_line'),
                no_space[0][0] if no_space else 0,
                following[0]['first_line'] if following else 0,
                info.get('removed_line'),
            ]
            if value
        ]
        for line in list(info.get('event_lines', []))[:6]:
            if line not in useful_lines:
                useful_lines.append(int(line))

        incidents.append(DiagnosticIncident(
            severity='error',
            title='T5 - Boite non mesuree bloquante',
            belt='T5',
            code='T5_STALE_UNMEASURED_BOX',
            first_line=first_line,
            last_line=last_line,
            start_time=first_time,
            end_time=last_time,
            start_time_str=str(info['first_time_str']),
            end_time_str=str(info['last_time_str']),
            count=max(1, len(no_space)),
            summary=summary,
            symptom=(
                "Une boite reste dans la base T5 en statut non valide, sans mesure largeur complete, "
                "pendant que T5 signale un manque de place."
            ),
            probable_causes=[
                "Boite physiquement bloquee ou mal positionnee sur T5.",
                "Boite conservee informatiquement alors qu'elle aurait du etre mesuree, prise, detruite ou videe.",
                "Tassage/retour repos impossible sans pousser une boite deja trop loin sur T5.",
            ],
            checks=[
                "Verifier la boite indiquee par IdA et sa goulotte dans les lignes ALPHA:T5-LIST-PACK.",
                "Controler les messages 'pas assez de place' avant de chercher un defaut C9 seul.",
                "Verifier si une vidange T5 tardive supprime plusieurs boites non mesurees.",
            ],
            confidence='forte',
            event_lines=useful_lines[:12],
        ))

    return incidents


def _build_c9_invalid_width_incidents(
    line_states: list[tuple[int, str, MachineState]],
) -> list[DiagnosticIncident]:
    matches = [
        (line_num, state.timestamp, state.timestamp_str)
        for line_num, text, state in line_states
        if _T5_WIDTH_C9_INVALID.search(text)
    ]
    if not matches:
        return []

    first_line, first_ts, first_ts_str = matches[0]
    last_line, last_ts, last_ts_str = matches[-1]
    return [DiagnosticIncident(
        severity='warning',
        title='T5 - Largeur C9 invalide',
        belt='T5',
        code='C9_WIDTH_INVALID',
        first_line=first_line,
        last_line=last_line,
        start_time=first_ts,
        end_time=last_ts,
        start_time_str=first_ts_str,
        end_time_str=last_ts_str,
        count=len(matches),
        summary=(
            f"{len(matches)} lecture(s) indiquent une largeur T5 <2 mm avec C9 actif. "
            "C'est une suspicion forte C9/T5, differente d'une simple largeur hors tolerance."
        ),
        symptom="Largeur lue sur T5 invalide alors que C9 detecte une presence.",
        probable_causes=[
            "C9 perturbe ou mal positionne.",
            "Boite non passee correctement devant C9.",
            "Blocage ou mauvais tassement sur T5 avant la mesure largeur.",
        ],
        checks=[
            "Verifier C9 et son alignement.",
            "Controler qu'aucune boite ne bloque avant la butee T5.",
            "Comparer avec les lignes de vidage T5 et de boites trop proches autour de l'heure.",
        ],
        confidence='forte',
        event_lines=[line_num for line_num, _, _ in matches[:12]],
    )]


def _reader_rate_label(count: int, total: int) -> str:
    if total <= 0:
        return f'{count}/0'
    return f'{count}/{total} ({count / total:.1%})'


def _camera_success_label(success_by_camera: dict[str, int], expected: tuple[str, ...]) -> str:
    parts = [f'{camera}:{success_by_camera.get(camera, 0)}' for camera in expected]
    extra = sorted(camera for camera in success_by_camera if camera not in expected)
    parts.extend(f'{camera}:{success_by_camera[camera]}' for camera in extra)
    return ', '.join(parts) if parts else '-'


def _camera_unknown_bucket(readers: set[str] | frozenset[str]) -> str:
    if 'CB1' in readers and 'CB2' in readers:
        return 'CB1+CB2'
    if 'CB1' in readers:
        return 'CB1 seul'
    if 'CB2' in readers:
        return 'CB2 seul'
    return 'non attribue'


def _camera_stats(
    line_states: list[tuple[int, str, MachineState]],
) -> dict[str, object]:
    all_hist_boxes: set[str] = set()
    reader_boxes = {'CB1': set(), 'CB2': set()}
    reader_zero_boxes = {'CB1': set(), 'CB2': set()}
    reader_unknown_refs: dict[str, set[str]] = {}
    success_by_reader = {'CB1': {}, 'CB2': {}}
    created_unknown: list[tuple[int, str, float, str, frozenset[str]]] = []
    hist_samples: list[tuple[int, float, str]] = []

    for line_num, text, state in line_states:
        match = _CAMERA_HIST.search(text)
        if match:
            reader = f'CB{match.group(1)}'
            box_id = match.group(2)
            code_count = int(match.group(3))
            all_hist_boxes.add(box_id)
            reader_boxes[reader].add(box_id)
            hist_samples.append((line_num, state.timestamp, state.timestamp_str))
            if code_count == 0:
                reader_zero_boxes[reader].add(box_id)

        match = _CAMERA_UNKNOWN_REF.search(text)
        if match:
            reader = f'CB{match.group(1)}'
            reader_unknown_refs.setdefault(match.group(2), set()).add(reader)

        match = _CAMERA_SUCCESS_READER.search(text)
        if match and 'PR' in text:
            reader = f'CB{match.group(1)}'
            expected = set(_CAMERA_EXPECTED.get(reader, ()))
            for token in _CAMERA_SUCCESS_TOKEN.finditer(text):
                camera = token.group(1)
                if camera not in expected:
                    continue
                success_by_reader[reader][camera] = success_by_reader[reader].get(camera, 0) + 1

        match = _CAMERA_UNKNOWN_CREATE.search(text)
        if match:
            ref = match.group(1)
            readers = frozenset(reader_unknown_refs.get(ref, set()))
            created_unknown.append((line_num, ref, state.timestamp, state.timestamp_str, readers))

    return {
        'all_hist_boxes': all_hist_boxes,
        'reader_boxes': reader_boxes,
        'reader_zero_boxes': reader_zero_boxes,
        'success_by_reader': success_by_reader,
        'created_unknown': created_unknown,
        'hist_samples': hist_samples,
    }


def _build_unknown_camera_incident(stats: dict[str, object]) -> list[DiagnosticIncident]:
    all_hist_boxes = stats['all_hist_boxes']
    reader_boxes = stats['reader_boxes']
    reader_zero_boxes = stats['reader_zero_boxes']
    success_by_reader = stats['success_by_reader']
    created_unknown = stats['created_unknown']

    total_boxes = len(all_hist_boxes)
    if total_boxes <= 0 or not created_unknown:
        return []

    by_bucket = {
        'CB1 seul': 0,
        'CB2 seul': 0,
        'CB1+CB2': 0,
        'non attribue': 0,
    }
    confirmed_unknown: list[tuple[int, str, float, str, frozenset[str]]] = []
    for item in created_unknown:
        *_, readers = item
        bucket = _camera_unknown_bucket(readers)
        by_bucket[bucket] += 1
        if bucket == 'CB1+CB2':
            confirmed_unknown.append(item)

    confirmed_count = len(confirmed_unknown)
    ratio = confirmed_count / total_boxes
    if confirmed_count <= 0 or ratio <= _CAMERA_UNKNOWN_THRESHOLD:
        return []

    first_line, _, first_ts, first_ts_str, _ = confirmed_unknown[0]
    last_line, _, last_ts, last_ts_str, _ = confirmed_unknown[-1]

    camera_labels = [
        f"{reader} cameras reussies: {_camera_success_label(success_by_reader[reader], _CAMERA_EXPECTED[reader])}"
        for reader in ('CB1', 'CB2')
    ]
    zero_labels = [
        f"{reader} 0 code: {_reader_rate_label(len(reader_zero_boxes[reader]), len(reader_boxes[reader]))}"
        for reader in ('CB1', 'CB2')
    ]
    attribution = (
        "Attribution unknown finales: "
        f"CB1 seul={by_bucket['CB1 seul']}, "
        f"CB2 seul={by_bucket['CB2 seul']}, "
        f"CB1+CB2={by_bucket['CB1+CB2']}, "
        f"non attribue={by_bucket['non attribue']}"
    )

    rule = knowledge('camera_unknown_rate')
    checks = list(rule.get('checks', []))
    for reader, expected in _CAMERA_EXPECTED.items():
        missing = [camera for camera in expected if success_by_reader[reader].get(camera, 0) == 0]
        if missing:
            checks.append(
                f"{reader}: camera(s) {', '.join(missing)} sans reussite observee, "
                "potentiellement deconnectee(s) ou non contributive(s)."
            )
        else:
            checks.append(f"{reader}: toutes les cameras attendues ont au moins une reussite observee.")

    return [DiagnosticIncident(
        severity='warning',
        title='Camera - Trop de boites finales unknown',
        belt='IDENTIF',
        code='UNKNOWN',
        first_line=first_line,
        last_line=last_line,
        start_time=first_ts,
        end_time=last_ts,
        start_time_str=first_ts_str,
        end_time_str=last_ts_str,
        count=confirmed_count,
        summary=(
            f'{confirmed_count} boite(s) unknown confirmee(s) CB1+CB2 sur {total_boxes} boite(s) passees '
            f'({ratio:.1%}, seuil > {_CAMERA_UNKNOWN_THRESHOLD:.0%}). '
            f'{attribution}. {"; ".join(zero_labels)}. {"; ".join(camera_labels)}.'
        ),
        symptom=str(rule.get('symptom', '')),
        probable_causes=list(rule.get('causes', [])),
        checks=checks,
        confidence=str(rule.get('confidence', '')),
        event_lines=[line_num for line_num, *_ in confirmed_unknown[:12]],
    )]


def _build_inactive_camera_incident(stats: dict[str, object]) -> list[DiagnosticIncident]:
    all_hist_boxes = stats['all_hist_boxes']
    success_by_reader = stats['success_by_reader']
    hist_samples = stats['hist_samples']
    total_boxes = len(all_hist_boxes)
    if total_boxes < _CAMERA_MIN_BOXES_FOR_INACTIVE:
        return []

    missing_labels: list[str] = []
    for reader, expected in _CAMERA_EXPECTED.items():
        successes = success_by_reader[reader]
        for camera in expected:
            if successes.get(camera, 0) == 0:
                missing_labels.append(f'{reader} camera {camera}')

    if not missing_labels:
        return []

    first_line, first_ts, first_ts_str = hist_samples[0] if hist_samples else (0, 0.0, '-')
    last_line, last_ts, last_ts_str = hist_samples[-1] if hist_samples else (0, 0.0, '-')
    rule = knowledge('camera_no_success')
    summary = (
        f"Camera(s) sans reussite observee sur {total_boxes} boite(s) passees: "
        f"{', '.join(missing_labels)}."
    )
    return [DiagnosticIncident(
        severity='warning',
        title='Camera - Camera attendue sans aucune lecture',
        belt='IDENTIF',
        code='CAM-NO-READ',
        first_line=first_line,
        last_line=last_line,
        start_time=first_ts,
        end_time=last_ts,
        start_time_str=first_ts_str,
        end_time_str=last_ts_str,
        count=len(missing_labels),
        summary=summary,
        symptom=str(rule.get('symptom', '')),
        probable_causes=list(rule.get('causes', [])),
        checks=list(rule.get('checks', [])),
        confidence=str(rule.get('confidence', '')),
        event_lines=[line_num for line_num, _, _ in hist_samples[:12]],
    )]


def camera_report_stats(frames: list[MachineState]) -> dict[str, object]:
    """Statistiques de lecture camera pour le rapport terrain."""
    stats = _camera_stats(_frame_line_states(frames))
    success_by_reader = stats['success_by_reader']
    reader_boxes = stats['reader_boxes']
    reader_zero_boxes = stats['reader_zero_boxes']

    chart: list[dict[str, object]] = []
    for reader, expected in _CAMERA_EXPECTED.items():
        successes = success_by_reader.get(reader, {})
        reader_max = max([int(successes.get(camera, 0)) for camera in expected] or [0])
        for camera in expected:
            count = int(successes.get(camera, 0))
            if count == 0:
                status = 'zero'
                status_label = 'aucune reussite'
            elif reader_max >= 4 and count <= reader_max * 0.5:
                status = 'weak'
                status_label = 'faible dans son groupe'
            else:
                status = 'ok'
                status_label = 'contributive'
            chart.append({
                'reader': reader,
                'camera': camera,
                'label': f'Camera {camera} / {reader}',
                'success_count': count,
                'expected': True,
                'status': status,
                'status_label': status_label,
            })
    chart.sort(key=lambda item: (-int(item['success_count']), str(item['reader']), str(item['camera'])))

    reader_stats: list[dict[str, object]] = []
    for reader in ('CB1', 'CB2'):
        boxes = len(reader_boxes.get(reader, set()))
        zero_boxes = len(reader_zero_boxes.get(reader, set()))
        rate = zero_boxes / boxes if boxes else 0.0
        reader_stats.append({
            'reader': reader,
            'expected_cameras': ', '.join(_CAMERA_EXPECTED.get(reader, ())),
            'boxes': boxes,
            'zero_code_boxes': zero_boxes,
            'zero_code_rate': rate,
            'zero_code_label': _reader_rate_label(zero_boxes, boxes),
        })

    alerts = [
        item for item in chart
        if str(item['status']) in {'zero', 'weak'}
    ]
    return {
        'available': bool(frames),
        'total_boxes': len(stats['all_hist_boxes']),
        'chart': chart,
        'reader_stats': reader_stats,
        'alerts': alerts,
        'note': 'CB1 = cameras 1, 2, 4, 5, 6. CB2 = camera 3.',
    }


def build_diagnostics(
    frames: list[MachineState],
    events: list[MachineEvent],
) -> list[DiagnosticIncident]:
    incidents: list[DiagnosticIncident] = []
    line_states = _frame_line_states(frames)
    incidents.extend(_build_motor_error_incidents(events))
    incidents.extend(_build_t4_diff_incidents(events))
    incidents.extend(_build_missing_c6_incidents(events))
    incidents.extend(_build_missing_t5_creation_incidents(events))
    incidents.extend(_build_wait_incidents(frames))
    incidents.extend(_build_t2_blocked_before_ea_incidents(frames))
    incidents.extend(_build_cubestop_c4_blocked_incidents(line_states))
    incidents.extend(_build_t4_init_loop_incidents(line_states, events))
    incidents.extend(_build_text_pattern_incidents(line_states))
    incidents.extend(_build_alpha_card_reset_incident(line_states))
    incidents.extend(_build_stale_unmeasured_t5_incidents(line_states))
    incidents.extend(_build_c9_invalid_width_incidents(line_states))
    incidents.extend(_build_dimension_incidents(frames, line_states))
    camera_stats = _camera_stats(line_states)
    incidents.extend(_build_unknown_camera_incident(camera_stats))
    incidents.extend(_build_inactive_camera_incident(camera_stats))

    severity_order = {'error': 0, 'warning': 1, 'info': 2}
    return sorted(
        incidents,
        key=lambda incident: (
            severity_order.get(incident.severity, 9),
            incident.first_line,
            incident.title,
        ),
    )
