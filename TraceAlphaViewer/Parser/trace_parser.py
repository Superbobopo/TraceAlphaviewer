"""
Parser pour les fichiers de trace AlphaV2 (.old).

Format d'une ligne :
    [* |L |  ] DD|HH:MM:SS.t  texte…

Le parser construit une liste de MachineState : un état complet de la machine
par timestamp unique (granularité 0,1 s). Chaque état est obtenu en appliquant
les mises à jour successives sur le précédent (état incrémental).
"""
from __future__ import annotations

import os
import re
from typing import Callable, List, Optional

from Models.state import BoxInfo, MachineEvent, MachineState, box_color

# ── Regex d'en-tête de ligne ─────────────────────────────────────────────────
_HDR = re.compile(
    r'[*L ]?\s*(\d{1,2})\|(\d{2}):(\d{2}):(\d{2})\.(\d+)\s+(.*)'
)

# ── Regex d'état des convoyeurs ───────────────────────────────────────────────
_T0 = re.compile(r'\bT0:\s+(\S+)\s+eT0:(-?\d+)\s+C0:(\d+)')
_T1 = re.compile(r'\bT1:\s+(\S+)\s+eT1:(-?\d+)')
_T2 = re.compile(
    r'\bT2:\s+(\S+)\s+eT2:(-?\d+)(?:\s+eT3:(-?\d+))?\s+C2:(\d+)\s+C3:(\d+)\s+C4:(\d+)'
)
_TEA = re.compile(
    r'tEA-T3:\s+(\S+)\s+C4:(\d+)\s+C5:(\d+)\s+fgBfinT3:(\d+)'
    r'\s+eT3:(-?\d+)\s+pT3:(-?\d+)mm\s+IdCB1:(\S+)'
)
_TT3T4 = re.compile(
    r'tT3/T4:\s+(\S+)\s+eT4:(-?\d+)\s+C5:(\d+)\s+C6:(\d+)'
    r'\s+pT3:(-?\d+)mm\s+pT4:(-?\d+)mm\s+LgBtT4:(-?[\d,]+)mm'
)
_TT4T5 = re.compile(
    r'tT4\*T5:\s+(\S+)\s+C6:(\d+)\s+fgBfinT4:(\d+)\s+pT4:(-?\d+)mm'
)
_T5 = re.compile(
    r'\bT5:\s+(\S+)\s+eT5=(-?\d+).*?larg:(-?\d+).*?C9:(\d+)'
    r'.*?pT5:(-?\d+).*?eT5useO:(\d+).*?eT5useA:(\d+)'
)
T4_DIRECTION_MIN_DELTA_MM = 2

# ── Regex d'événements boîtes ─────────────────────────────────────────────────
_BOX_INIT_T5 = re.compile(
    r'sur T5:\s+(\S+)\s+(\S+)\s+lot:(\S+)\s+\S+\s+x=(\d+)'
)
_BOX_CREATE = re.compile(
    r"Cr[eé]ation de la boite '([^']+)'\s+(.+?)\s+x=(\d+)"
    r'\s+\((\d+)x(\d+)x(\d+)\)\s+IdA:(\d+)'
)
_BOX_REMOVE = re.compile(
    r'supp\. de T5 la boite Id:(\d+)\s+ref:(\S+)'
)
_BOX_REMOVE2 = re.compile(
    r'-suppression de la boite ID:(\d+)'
)
_BOX_REMOVE3 = re.compile(
    r"Suppr\. la boite IdA:(\d+)"
)
_CB_HIST = re.compile(
    r"\bCB([12]):\s+ajout Hist_LectCB .*?(\d+)code\(s\) lu\(s\)",
    re.IGNORECASE,
)
_CB_IDENTIF = re.compile(
    r"idCB([12]):\s*-->\s*R\S*f:(\S+)\s+lot:\s*(\S*)", re.IGNORECASE
)
_CB2_NBOITE = re.compile(
    r"idCB2:\s*\(Nboite=\s*(\d+)\)", re.IGNORECASE
)
_CB2_DIRECT_IDENTIF = re.compile(
    r"idCB2:.*?Ok '([^']+)'.*?\(Nboite=\s*(\d+)\)", re.IGNORECASE
)
_T3_T4_FIN_IDB = re.compile(
    r"transfert T3->T4 termin.*?longueur=([\d,]+) mm.*?idB=(\d+)",
    re.IGNORECASE,
)
_AJOUT_T5_ID = re.compile(
    r"AjoutBtT5\.idA(\d+)\.idB(-?\d+)", re.IGNORECASE
)
_DB_INFO = re.compile(
    r'-->\s+(.+?)\s+(\d+)x(\d+)x(\d+)\s+[\d,]+g'
)
_RECH_INFOS = re.compile(
    r'Rech\. infos.*?pour (\S+)'
)
_MAJ_T5_POS = re.compile(
    r'MAJ \(BUTEE-T5\) boite Id:(\d+) ref:(\S+).*?nvlle dim:\d+x(\d+)\s+X:(\d+)'
)
_MAJ_T5_MESURE = re.compile(
    r"MAJ \(APRES-MESURE-LARG\) bt IdA:(\d+) '([^']+)'.*?"
    r"nvlle lxH:(\d+)x(\d+) \[x(\d+)\] X:(\d+)"
)
_ERROR_WORD = re.compile(r'\b(err|erreur|timeout|alarme|defaut|défaut)\b', re.IGNORECASE)
_ERROR_REPEAT_DELAY = 300.0
# Position approximative d'arrivée depuis T4 (mm, coord machine) — lue dans les traces
_T5_ENTRY_X = 1060
_T5_LIST_SEP = chr(182)
_DEPL_T5 = re.compile(
    r'D[eé]place toutes les boites.*?sur (-?\d+) mm'
)
_DEPL_T5_ACTIVE = re.compile(
    r'DeplBtSurT5\.(-?\d+)mm\.Ref\S+\.idA(\d+)', re.IGNORECASE
)
_C1_SENSOR = re.compile(r'capteurC1=(\d+)')
_POUBELLE  = re.compile(r'FlagPoubellePleine\s*=\s*(\w+)', re.IGNORECASE)
_LZB       = re.compile(r'\bLzB[:\s=]+(-?\d+)')
_T4_LENGTH_SUMMARY = re.compile(
    r'longueur boite .*?\(BdD\)=(-?\d+).*?\(T2T\)=(-?\d+)'
    r'.*?\(T4C\)=(-?\d+).*?\(T4T\)=(-?\d+).*?diffT4=(-?\d+)mm',
    re.IGNORECASE,
)


def _ts(day: str, h: str, m: str, s: str, ds: str) -> float:
    return int(day) * 86400 + int(h) * 3600 + int(m) * 60 + int(s) + int(ds) * 0.1


def _add_event(
    state: MachineState,
    line_num: int,
    severity: str,
    kind: str,
    title: str,
    detail: str = "",
) -> None:
    state.events.append(MachineEvent(
        line_num=line_num,
        timestamp=state.timestamp,
        timestamp_str=state.timestamp_str,
        severity=severity,
        kind=kind,
        title=title,
        detail=detail,
    ))


def _is_unknown_ref(ref: str) -> bool:
    return ref.upper().startswith('ALPHA-INC') if ref else False


def _apply_identity(
    box: BoxInfo,
    barcode: str,
    lot: str = "",
    name: str = "",
    dims: Optional[tuple[int, int, int]] = None,
) -> None:
    if box.barcode and _is_unknown_ref(box.barcode) and barcode != box.barcode:
        box.source_ref = box.barcode
    elif barcode and _is_unknown_ref(barcode) and not box.source_ref:
        box.source_ref = barcode
    if barcode:
        box.barcode = barcode
        box.color = box_color(barcode)
    if lot:
        box.lot = lot
    if name:
        box.name = name
    if dims:
        box.width_mm, box.height_mm, box.length_mm = dims


def _find_unique_barcode(boxes: list[BoxInfo], barcode: str) -> Optional[BoxInfo]:
    if not barcode:
        return None
    matches = [b for b in boxes if b.barcode == barcode]
    return matches[0] if len(matches) == 1 else None


def _find_t5_box(
    state: MachineState,
    id_alpha: int = 0,
    id_b: int = 0,
    barcode: str = "",
) -> Optional[BoxInfo]:
    if id_alpha:
        for box in state.boxes_on_T5:
            if box.id_alpha == id_alpha:
                return box
    if id_b:
        for box in state.boxes_on_T5:
            if box.id_b == id_b:
                return box
    return _find_unique_barcode(state.boxes_on_T5, barcode)


def _clear_missing_active_t5(state: MachineState) -> None:
    if not state.t5_active_id_alpha:
        return
    if any(b.id_alpha == state.t5_active_id_alpha for b in state.boxes_on_T5):
        return
    state.t5_active_id_alpha = 0
    _commit_t5_visual_motion(state)


def _set_t5_after_c9(state: MachineState, id_alpha: int) -> None:
    box = _find_t5_box(state, id_alpha=id_alpha)
    if box:
        box.t5_after_c9 = True


def _box_label(box: Optional[BoxInfo]) -> str:
    if not box:
        return "boite"
    if box.id_b:
        return f'idB={box.id_b}'
    return box.barcode or box.source_ref or "boite"


def _ensure_reader_box(state: MachineState, reader: str, barcode: str = "") -> Optional[BoxInfo]:
    if reader == 'CB1':
        if state.box_in_EA is None:
            state.box_in_EA = BoxInfo(color=box_color(barcode or '0'))
        return state.box_in_EA
    if reader == 'CB2':
        if state.box_on_T3 is None and state.C5 == 1:
            state.box_on_T3 = BoxInfo(color=box_color(barcode or '0'))
        return state.box_on_T3
    return None


def _track_motor_error(
    state: MachineState,
    line_num: int,
    ctx: dict,
    belt: str,
    et: int,
    detail: str,
) -> None:
    active_errors = ctx.setdefault('active_errors', {})
    previous = active_errors.get(belt)
    if et < 0 and et != -1:
        if previous != et:
            active_errors[belt] = et
            last_error_ts = ctx.setdefault('last_error_ts', {})
            error_key = (belt, et)
            previous_ts = last_error_ts.get(error_key)
            if previous_ts is not None and state.timestamp - previous_ts < _ERROR_REPEAT_DELAY:
                return
            last_error_ts[error_key] = state.timestamp
            _add_event(
                state, line_num, 'error', 'ERREUR',
                f'{belt} en erreur eT:{et}', detail.strip()
            )
    else:
        active_errors.pop(belt, None)


def _track_signal_edges(state: MachineState, line_num: int, ctx: dict) -> None:
    sensors = {
        'C0': state.C0,
        'C2': state.C2,
        'C3': state.C3,
        'C4': state.C4,
        'C5': state.C5,
        'C6': state.C6,
        'C9': state.C9,
        'Poubelle': state.flag_poubelle_pleine,
    }
    labels = {
        'C0': 'Presence T1 entree detectee',
        'C2': 'Presence T2 sortie detectee',
        'C3': 'Presence T2 chargee detectee',
        'C4': 'Presence EA detectee',
        'C5': 'Presence T3 detectee',
        'C6': 'Presence T4 detectee',
        'C9': 'Laser T5 actif',
        'Poubelle': 'Poubelle pleine',
    }
    last = ctx.setdefault('last_sensors', {})
    for name, value in sensors.items():
        previous = last.get(name)
        last[name] = value
        if previous is None:
            continue
        if previous == 0 and value == 1:
            severity = 'warning' if name == 'Poubelle' else 'info'
            _add_event(state, line_num, severity, 'CAPTEUR', labels[name])


def _track_belt_task_edge(
    state: MachineState,
    line_num: int,
    ctx: dict,
    belt: str,
    et: int,
    state_name: str,
) -> None:
    key = f'last_{belt}_et'
    previous = ctx.get(key)
    ctx[key] = et
    if previous is None or previous == et:
        return
    if abs(et) <= 2:
        return
    severity = 'error' if et < 0 else 'info'
    _add_event(
        state, line_num, severity, belt,
        f'{belt} eT:{et} {state_name}'
    )


def _track_t4_cycle(state: MachineState, line_num: int, ctx: dict) -> None:
    last_et = ctx.get('last_t4_et')
    current_box = 'boite T4'

    if last_et != state.eT4:
        ctx['last_t4_et'] = state.eT4
        if state.eT4 == 41:
            ctx['t4_cycle_id'] = ctx.get('t4_cycle_id', 0) + 1
            _add_event(
                state, line_num, 'info', 'T4',
                'T3 vers T4 demarre', f'{current_box} pT4:{state.pT4}mm'
            )
        elif state.eT4 == 42:
            _add_event(
                state, line_num, 'info', 'T4',
                'Mesure longueur T4 en cours', f'{current_box} pT4:{state.pT4}mm'
            )
        elif state.eT4 == 43 and state.LgBtT4 > 0:
            _add_event(
                state, line_num, 'info', 'T4',
                f'Longueur T4 mesuree {state.LgBtT4:.0f}mm',
                f'{current_box} C6:{state.C6} pT4:{state.pT4}mm'
            )
        elif state.eT4 == 46:
            detail = f'{current_box} C6:{state.C6} pT4:{state.pT4}mm'
            if state.LgBtT4 > 0:
                detail += f' Lg:{state.LgBtT4:.0f}mm'
            _add_event(
                state, line_num, 'info', 'T4',
                'T3 vers T4 termine', detail
            )
        elif state.eT4 == 81:
            _add_event(
                state, line_num, 'info', 'T4',
                'Transfert T4 vers T5 demarre', f'{current_box} pT4:{state.pT4}mm'
            )
        elif state.eT4 == 83:
            _add_event(
                state, line_num, 'info', 'T4',
                'Retour index T4 apres depot', f'{current_box} pT4:{state.pT4}mm'
            )
        elif state.eT4 == 85:
            _add_event(
                state, line_num, 'info', 'T4',
                'Cycle T4 termine', f'{current_box} pT4:{state.pT4}mm'
            )

    cycle_id = ctx.get('t4_cycle_id', 0)
    if (
        state.C6 == 1
        and state.LgBtT4 > 0
        and ctx.get('last_t4_c6_measure_cycle') != cycle_id
    ):
        ctx['last_t4_c6_measure_cycle'] = cycle_id
        _add_event(
            state, line_num, 'info', 'T4',
            f'C6 declenche longueur {state.LgBtT4:.0f}mm',
            f'{current_box} pT4:{state.pT4}mm'
        )


def _update_t4_direction(state: MachineState, new_pT4: int, ctx: dict) -> None:
    previous_pT4 = ctx.get('last_pT4')
    if abs(state.eT4) <= 2 or state.eT4 in (5, 51, 85):
        state.t4_direction = 0
    elif previous_pT4 is not None and new_pT4 != previous_pT4:
        delta = new_pT4 - previous_pT4
        if abs(delta) >= T4_DIRECTION_MIN_DELTA_MM:
            state.t4_direction = 1 if delta < 0 else -1
            ctx['last_t4_direction'] = state.t4_direction
        else:
            state.t4_direction = int(ctx.get('last_t4_direction') or 0)
    else:
        state.t4_direction = int(ctx.get('last_t4_direction') or 0)
    ctx['last_pT4'] = new_pT4


def _t5_visual_base(box: BoxInfo) -> int:
    return int(box.t5_visual_x_pos or box.x_pos or 0)


def _commit_t5_visual_motion(state: MachineState) -> None:
    offset = int(state.t5_visual_offset_mm or 0)
    if offset:
        for box in state.boxes_on_T5:
            if not box.t5_entry_aligned:
                box.t5_visual_x_pos = _t5_visual_base(box) + offset
    state.t5_visual_offset_mm = 0


def _reset_t5_visual_offset(
    state: MachineState,
    ctx: Optional[dict],
    commit: bool = True,
) -> None:
    if commit:
        _commit_t5_visual_motion(state)
    else:
        state.t5_visual_offset_mm = 0
    if ctx is None:
        return
    ctx['t5_visual_anchor_pT5'] = state.pT5
    ctx['t5_visual_anchor_pending'] = True


def _update_t5_visual_offset(state: MachineState, new_pT5: int, ctx: dict) -> None:
    if ctx.pop('t5_visual_anchor_pending', False):
        ctx['t5_visual_anchor_pT5'] = new_pT5
        state.t5_visual_offset_mm = 0
        return

    has_positioned_box = any(not b.t5_entry_aligned for b in state.boxes_on_T5)
    anchor = ctx.get('t5_visual_anchor_pT5')
    if anchor is None or not has_positioned_box:
        ctx['t5_visual_anchor_pT5'] = new_pT5
        state.t5_visual_offset_mm = 0
        return

    state.t5_visual_offset_mm = new_pT5 - int(anchor)


def _t5_list_values(chunk: str) -> list[str]:
    if chunk.startswith('<Dc2>'):
        return chunk.split('<Dc2>')[1:]
    if chunk.startswith(_T5_LIST_SEP):
        return chunk.split(_T5_LIST_SEP)[1:]
    return []


def _apply_t5_list_pack(state: MachineState, text: str, ctx: Optional[dict] = None) -> bool:
    """Met a jour T5 avec la liste robot, qui contient les positions X exactes."""
    if 'ALPHA:T5-LIST-PACK' not in text:
        return False

    parsed: list[BoxInfo] = []
    for chunk in text.split('@'):
        values = _t5_list_values(chunk)
        if not values:
            continue
        if len(values) < 14:
            continue
        try:
            id_a = int(values[0])
            bc = values[2]
            width = int(values[4])
            height = int(values[5])
            length = int(values[6])
            x_pos = int(values[13])
        except (ValueError, IndexError):
            continue
        id_b = 0
        if ctx:
            id_b = ctx.get('ida_to_idb', {}).get(id_a, 0)
        t5_footprint = 0
        for idx, value in enumerate(values):
            if value.startswith('X990') and idx + 2 < len(values):
                try:
                    t5_footprint = int(values[idx + 1])
                except ValueError:
                    t5_footprint = 0
                break
        parsed.append(BoxInfo(
            barcode=bc,
            name=values[3],
            lot=values[8] if len(values) > 8 else '',
            width_mm=width,
            height_mm=height,
            length_mm=length,
            t5_footprint_mm=t5_footprint,
            id_b=id_b,
            id_alpha=id_a,
            x_pos=x_pos,
            t5_visual_x_pos=x_pos,
            t5_entry_aligned=False,
            t5_after_c9=True,
            color=box_color(bc),
        ))

    if parsed or text.rstrip().endswith('@FP'):
        state.boxes_on_T5 = parsed
        if (
            state.t5_active_id_alpha
            and not any(b.id_alpha == state.t5_active_id_alpha for b in state.boxes_on_T5)
        ):
            state.t5_active_id_alpha = 0
        _reset_t5_visual_offset(state, ctx, commit=False)
        return True
    return False


def _update(state: MachineState, text: str, ctx: dict, line_num: int) -> None:
    """Applique une ligne de texte sur l'état courant (in-place)."""

    if 'idCB2:' in text or 'CB2:' in text:
        ctx['last_reader'] = 'CB2'
    elif 'idCB1:' in text or 'CB1:' in text:
        ctx['last_reader'] = 'CB1'

    mo = _CB_HIST.search(text)
    if mo:
        reader = f'CB{mo.group(1)}'
        code_count = int(mo.group(2))
        ctx['last_reader'] = reader
        ctx['last_hist_reader'] = reader
        ctx['pending_reader'] = reader
        ctx['last_hist_code_count'] = code_count
        if reader == 'CB1':
            _ensure_reader_box(state, 'CB1')
            _add_event(state, line_num, 'info', 'IDENTIF', f'Lecture CB1 sur EA ({code_count} code)')
        else:
            target = _ensure_reader_box(state, 'CB2')
            if target:
                _add_event(state, line_num, 'info', 'IDENTIF', f'Lecture CB2 sur T3 ({code_count} code)')
            else:
                _add_event(
                    state, line_num, 'warning', 'IDENTIF',
                    f'Lecture CB2 sans boite T3 ({code_count} code)', f'C5:{state.C5}'
                )

    _apply_t5_list_pack(state, text, ctx)

    # T0
    mo = _T0.search(text)
    if mo:
        state.state_T0 = mo.group(1)
        state.eT0 = int(mo.group(2))
        state.C0 = int(mo.group(3))
        _track_motor_error(state, line_num, ctx, 'T0', state.eT0, text)
        _track_belt_task_edge(state, line_num, ctx, 'T0', state.eT0, state.state_T0)

    # T1
    mo = _T1.search(text)
    if mo:
        state.state_T1 = mo.group(1)
        state.eT1 = int(mo.group(2))
        _track_motor_error(state, line_num, ctx, 'T1', state.eT1, text)
        _track_belt_task_edge(state, line_num, ctx, 'T1', state.eT1, state.state_T1)

    # T2
    mo = _T2.search(text)
    if mo:
        state.state_T2 = mo.group(1)
        state.eT2 = int(mo.group(2))
        if mo.group(3) is not None:
            state.eT3 = int(mo.group(3))
        state.C2 = int(mo.group(4))
        state.C3 = int(mo.group(5))
        state.C4 = int(mo.group(6))
        _track_motor_error(state, line_num, ctx, 'T2', state.eT2, text)
        if mo.group(3) is not None:
            _track_motor_error(state, line_num, ctx, 'T3', state.eT3, text)
        _track_belt_task_edge(state, line_num, ctx, 'T2', state.eT2, state.state_T2)

    # tEA-T3
    mo = _TEA.search(text)
    if mo:
        state.state_tEA_T3 = mo.group(1)
        state.C4 = int(mo.group(2))
        state.C5 = int(mo.group(3))
        state.fgBfinT3 = int(mo.group(4))
        state.eT3 = int(mo.group(5))
        state.pT3 = int(mo.group(6))
        _track_motor_error(state, line_num, ctx, 'T3', state.eT3, text)

    # tT3/T4
    mo = _TT3T4.search(text)
    if mo:
        state.state_tT3_T4 = mo.group(1)
        state.eT4 = int(mo.group(2))
        state.C5 = int(mo.group(3))
        state.C6 = int(mo.group(4))
        state.pT3 = int(mo.group(5))
        new_pT4 = int(mo.group(6))
        _update_t4_direction(state, new_pT4, ctx)
        state.pT4 = new_pT4
        state.LgBtT4 = float(mo.group(7).replace(',', '.'))
        _track_motor_error(state, line_num, ctx, 'T4', state.eT4, text)
        _track_t4_cycle(state, line_num, ctx)

    # tT4*T5
    mo = _TT4T5.search(text)
    if mo:
        state.state_tT4_T5 = mo.group(1)
        state.C6 = int(mo.group(2))
        state.fgBfinT4 = int(mo.group(3))
        new_pT4 = int(mo.group(4))
        _update_t4_direction(state, new_pT4, ctx)
        state.pT4 = new_pT4

    # T5
    mo = _T5.search(text)
    if mo:
        state.state_T5 = mo.group(1)
        state.eT5 = int(mo.group(2))
        state.larg_T5 = int(mo.group(3))
        state.C9 = int(mo.group(4))
        if state.C9 and state.t5_active_id_alpha:
            _set_t5_after_c9(state, state.t5_active_id_alpha)
        new_pT5 = int(mo.group(5))
        previous_pT5 = ctx.get('last_pT5')
        if abs(state.eT5) <= 2 or state.eT5 in (5, 51):
            state.t5_direction = 0
        elif previous_pT5 is not None and new_pT5 != previous_pT5:
            delta = new_pT5 - previous_pT5
            state.t5_direction = -1 if delta > 0 else 1
            ctx['last_t5_direction'] = state.t5_direction
        else:
            state.t5_direction = int(ctx.get('last_t5_direction') or 0)
        state.pT5 = new_pT5
        _update_t5_visual_offset(state, new_pT5, ctx)
        ctx['last_pT5'] = new_pT5
        state.eT5useO = int(mo.group(6))
        state.eT5useA = int(mo.group(7))
        _track_motor_error(state, line_num, ctx, 'T5', state.eT5, text)

    # ── Boîte initiale sur T5 ────────────────────────────────────────────────
    mo = _BOX_INIT_T5.search(text)
    if mo:
        bc, name, lot, x = mo.group(1), mo.group(2), mo.group(3), int(mo.group(4))
        if not any(b.barcode == bc for b in state.boxes_on_T5):
            state.boxes_on_T5.append(
                BoxInfo(
                    barcode=bc, name=name, lot=lot, x_pos=x,
                    t5_visual_x_pos=x, color=box_color(bc)
                )
            )
        _add_event(state, line_num, 'info', 'BOITE', f'Boite deja sur T5 {bc}', text.strip())

    # ── Création boîte sur T5 ────────────────────────────────────────────────
    mo = _BOX_CREATE.search(text)
    if mo:
        bc   = mo.group(1)
        name = mo.group(2).strip()
        x    = int(mo.group(3))
        w, hh, lg = int(mo.group(4)), int(mo.group(5)), int(mo.group(6))
        id_a = int(mo.group(7))
        id_b = int(ctx.get('last_t5_transfer_idb') or 0)
        box = _find_t5_box(state, id_alpha=id_a, id_b=id_b)
        if box is None and id_b:
            box = _find_unique_barcode(state.boxes_on_T5, bc)
        if box is None:
            box = BoxInfo()
            state.boxes_on_T5.append(box)
        _apply_identity(box, bc, name=name, dims=(w, hh, lg))
        if not box.t5_entry_aligned:
            box.x_pos = x
            box.t5_visual_x_pos = x
            box.t5_after_c9 = False
        box.id_alpha = id_a
        if id_b:
            box.id_b = id_b
            ctx.setdefault('idb_to_ida', {})[id_b] = id_a
            ctx.setdefault('ida_to_idb', {})[id_a] = id_b
        _add_event(
            state, line_num, 'info', 'BOITE',
            f'T4->T5 {_box_label(box)} -> IdA={id_a}', f'{bc} {name} x={x}'
        )
        # La boîte n'est plus en EA ni sur T4 dès qu'elle est créée sur T5
        if state.box_on_T4 and (
            (id_b and state.box_on_T4.id_b == id_b)
            or (not id_b and state.box_on_T4.barcode == bc)
        ):
            state.box_on_T4 = None
        ctx['last_t5_transfer_idb'] = 0

    # ── Suppression boîte de T5 ──────────────────────────────────────────────
    mo = _BOX_REMOVE.search(text)
    if mo:
        id_a = int(mo.group(1))   # Id: (id_alpha)
        bc   = mo.group(2)        # ref: (barcode)
        if id_a:
            state.boxes_on_T5 = [b for b in state.boxes_on_T5 if b.id_alpha != id_a]
            if state.t5_active_id_alpha == id_a:
                state.t5_active_id_alpha = 0
                _reset_t5_visual_offset(state, ctx)
        else:
            victim = _find_unique_barcode(state.boxes_on_T5, bc)
            if victim:
                state.boxes_on_T5 = [b for b in state.boxes_on_T5 if b is not victim]
        _add_event(state, line_num, 'warning', 'BOITE', f'Robot supprime IdA={id_a}', bc)

    # ── Suppression boîte de T5 (format long) ──────────────────────────────
    mo = _BOX_REMOVE2.search(text)
    if mo:
        id_a = int(mo.group(1))
        state.boxes_on_T5 = [
            b for b in state.boxes_on_T5
            if b.id_alpha != id_a
        ]
        if state.t5_active_id_alpha == id_a:
            state.t5_active_id_alpha = 0
            _reset_t5_visual_offset(state, ctx)
        _add_event(state, line_num, 'warning', 'BOITE', f'Robot supprime IdA={id_a}')

    # ── Suppression boîte (format "Suppr. la boite IdA:X") ─────────────────
    mo = _BOX_REMOVE3.search(text)
    if mo:
        id_a = int(mo.group(1))
        state.boxes_on_T5 = [
            b for b in state.boxes_on_T5
            if b.id_alpha != id_a
        ]
        if state.t5_active_id_alpha == id_a:
            state.t5_active_id_alpha = 0
            _reset_t5_visual_offset(state, ctx)
        _add_event(state, line_num, 'warning', 'BOITE', f'Suppression boite IdA:{id_a}')

    # ── Mise à jour position X sur T5 (après tassement) ────────────────────
    mo = _MAJ_T5_POS.search(text)
    if mo:
        id_a = int(mo.group(1))
        bc   = mo.group(2)
        h    = int(mo.group(3))   # nvlle dim: WxH -> H = hauteur mesuree (mm)
        x    = int(mo.group(4))
        state.t5_active_id_alpha = id_a
        state.t5_x_butee = x
        _reset_t5_visual_offset(state, ctx)
        b = _find_t5_box(state, id_alpha=id_a, barcode=bc)
        id_b = ctx.get('ida_to_idb', {}).get(id_a, 0)
        if b:
            b.x_pos = x
            b.t5_visual_x_pos = x
            b.t5_entry_aligned = False
            b.t5_after_c9 = False
            b.id_alpha = id_a
            if id_b:
                b.id_b = id_b
            if h > 0:
                b.height_mm = h
        else:
            # Boîte pas encore suivie (ex: arrivée non capturée) — on la crée
            state.boxes_on_T5.append(BoxInfo(
                barcode=bc, id_alpha=id_a, x_pos=x,
                t5_visual_x_pos=x,
                id_b=id_b, height_mm=h, t5_entry_aligned=False,
                t5_after_c9=False, color=box_color(bc)
            ))
        _add_event(state, line_num, 'info', 'BOITE', f'MAJ butee T5 {bc}', f'IdA:{id_a} X:{x} haut:{h}')

    # ── Déplacement global des boîtes sur T5 (tassement) ────────────────────
    mo = _MAJ_T5_MESURE.search(text)
    if mo:
        id_a = int(mo.group(1))
        bc = mo.group(2)
        width = int(mo.group(3))
        height = int(mo.group(4))
        length = int(mo.group(5))
        x = int(mo.group(6))
        state.t5_active_id_alpha = id_a
        _reset_t5_visual_offset(state, ctx)
        b = _find_t5_box(state, id_alpha=id_a, barcode=bc)
        id_b = ctx.get('ida_to_idb', {}).get(id_a, 0)
        if b:
            b.x_pos = x
            b.t5_visual_x_pos = x
            b.t5_entry_aligned = False
            b.t5_after_c9 = True
            b.id_alpha = id_a
            if id_b:
                b.id_b = id_b
            b.width_mm = width
            b.height_mm = height
            b.length_mm = length
        else:
            state.boxes_on_T5.append(BoxInfo(
                barcode=bc, id_alpha=id_a, x_pos=x,
                id_b=id_b,
                width_mm=width, height_mm=height, length_mm=length,
                t5_footprint_mm=width,
                t5_visual_x_pos=x,
                t5_entry_aligned=False,
                t5_after_c9=True,
                color=box_color(bc),
            ))
        _add_event(state, line_num, 'info', 'BOITE', f'MAJ mesure T5 {bc}', f'IdA:{id_a} X:{x} {width}x{height}x{length}')

    mo = _DEPL_T5.search(text)
    if mo:
        delta = int(mo.group(1))
        for b in state.boxes_on_T5:
            b.x_pos += delta
            if not b.t5_entry_aligned:
                b.t5_visual_x_pos = b.x_pos
        _reset_t5_visual_offset(state, ctx, commit=False)

    # ── Mémorisation du code-barres cherché en BdD ──────────────────────────
    mo = _DEPL_T5_ACTIVE.search(text)
    if mo:
        delta = int(mo.group(1))
        id_a = int(mo.group(2))
        state.t5_active_id_alpha = id_a

    mo = _RECH_INFOS.search(text)
    if mo:
        ctx['pending_bc'] = mo.group(1)
        ctx['pending_name'] = ''
        ctx['pending_dims'] = None
        ctx['pending_reader'] = ctx.pop('last_hist_reader', ctx.get('last_reader', ''))

    # ── Infos BdD (nom + dimensions) ────────────────────────────────────────
    mo = _DB_INFO.search(text)
    if mo and 'pending_bc' in ctx:
        ctx['pending_name'] = mo.group(1).strip()
        ctx['pending_dims'] = (int(mo.group(2)), int(mo.group(3)), int(mo.group(4)))
        bc = ctx['pending_bc']
        target = None
        if ctx.get('pending_reader') == 'CB2':
            target = _ensure_reader_box(state, 'CB2', bc)
        elif ctx.get('pending_reader') == 'CB1':
            target = _ensure_reader_box(state, 'CB1', bc)
        elif state.box_in_EA and (state.box_in_EA.barcode == bc or _is_unknown_ref(bc)):
            target = state.box_in_EA
        if target:
            _apply_identity(target, bc, name=ctx['pending_name'], dims=ctx['pending_dims'])

    # ── Identification CB1 terminée ──────────────────────────────────────────
    mo = _CB_IDENTIF.search(text)
    if mo:
        reader = int(mo.group(1))
        bc = mo.group(2)
        lot = mo.group(3)
        name = ctx.get('pending_name', '')
        dims = ctx.get('pending_dims')
        if reader == 1:
            state.idCB1_barcode = bc
            state.idCB1_state = 'IDENTIFIED'
            target = _ensure_reader_box(state, 'CB1', bc)
            _apply_identity(target, bc, lot=lot, name=name, dims=dims)
            title = f'CB1 inconnu {bc}' if _is_unknown_ref(bc) else f'Identification CB1 {bc}'
            _add_event(state, line_num, 'info', 'IDENTIF', title, f'lot:{lot}')
        else:
            target = _ensure_reader_box(state, 'CB2', bc)
            if target:
                previous = target.source_ref or target.barcode
                _apply_identity(target, bc, lot=lot, name=name, dims=dims)
                ctx['last_cb2_box'] = target
                detail = f'{previous} -> {bc}' if previous and previous != bc else bc
                _add_event(state, line_num, 'info', 'IDENTIF', f'CB2 identifie {detail}', f'lot:{lot}')
            else:
                _add_event(
                    state, line_num, 'warning', 'IDENTIF',
                    f'CB2 identifie {bc} sans boite T3', f'C5:{state.C5}'
                )

    mo = _CB2_NBOITE.search(text)
    if mo:
        id_b = int(mo.group(1))
        target = state.box_on_T3
        if target is None and state.C5 == 1:
            target = _ensure_reader_box(state, 'CB2')
        if target:
            target.id_b = id_b
            ctx.setdefault('idb_to_box', {})[id_b] = target
            _add_event(
                state, line_num, 'info', 'IDENTIF',
                f'CB2 identifie idB={id_b} -> {target.barcode or target.source_ref}'
            )
        else:
            _add_event(
                state, line_num, 'warning', 'IDENTIF',
                f'Nboite={id_b} sans boite T3', f'C5:{state.C5}'
            )

    mo = _CB2_DIRECT_IDENTIF.search(text)
    if mo:
        bc = mo.group(1)
        id_b = int(mo.group(2))
        target = state.box_on_T3
        if target is None and state.C5 == 1:
            target = _ensure_reader_box(state, 'CB2', bc)
        if target:
            _apply_identity(target, bc)
            target.id_b = id_b
            ctx.setdefault('idb_to_box', {})[id_b] = target
            _add_event(state, line_num, 'info', 'IDENTIF', f'CB2 identifie idB={id_b} -> {bc}')
        else:
            _add_event(
                state, line_num, 'warning', 'IDENTIF',
                f'Identification CB2 directe sans boite T3 {bc}', f'Nboite:{id_b} C5:{state.C5}'
            )

    # ── Boîte chargée sur T2 ─────────────────────────────────────────────────
    if 'T2: une boite est charg' in text or 'BOITE-LOAD' in text:
        if state.box_in_EA is None:
            state.box_in_EA = BoxInfo(color=box_color('0'))

    # ── Transfert EA → T3 terminé : boîte passe de EA vers T3/T4 ───────────
    if 'le transfert (EA->T3) est termin' in text:
        if state.box_in_EA:
            state.box_on_T3 = state.box_in_EA
            _add_event(
                state, line_num, 'info', 'TRANSFERT',
                f'EA vers T3 {state.box_on_T3.barcode or "boite"}'
            )
        state.box_in_EA = None

    mo = _T3_T4_FIN_IDB.search(text)
    if mo:
        length = float(mo.group(1).replace(',', '.'))
        id_b = int(mo.group(2))
        if state.box_on_T3 is None:
            state.box_on_T3 = ctx.get('idb_to_box', {}).get(id_b)
        if state.box_on_T3:
            state.box_on_T3.id_b = id_b
            if length > 0:
                state.box_on_T3.length_mm = int(round(length))
            state.box_on_T4 = state.box_on_T3
            state.box_on_T3 = None
            ctx.setdefault('idb_to_box', {})[id_b] = state.box_on_T4
            _add_event(
                state, line_num, 'info', 'TRANSFERT',
                f'T3->T4 idB={id_b}', state.box_on_T4.barcode or state.box_on_T4.source_ref
            )

    # ── Fin de transfert T4 → T5 : box_on_T4 est ajoutée à boxes_on_T5 ──────
    if 'la boite est rendu (physiquement) sur T5' in text:
        bc = state.box_on_T4.barcode if state.box_on_T4 else ''
        id_b = state.box_on_T4.id_b if state.box_on_T4 else 0
        ctx['last_t5_transfer_idb'] = id_b
        if state.box_on_T4 is not None:
            b = state.box_on_T4
            # Évite le doublon si la boîte est déjà dans la liste
            box = _find_t5_box(state, id_b=b.id_b)
            if box is None:
                box = BoxInfo(
                    barcode=b.barcode, source_ref=b.source_ref, name=b.name, lot=b.lot,
                    length_mm=b.length_mm, width_mm=b.width_mm, height_mm=b.height_mm,
                    t5_footprint_mm=b.t5_footprint_mm,
                    id_b=b.id_b, id_alpha=b.id_alpha,
                    x_pos=_T5_ENTRY_X,
                    t5_visual_x_pos=0,
                    t5_entry_aligned=True,
                    t5_after_c9=False,
                    color=b.color,
                )
                state.boxes_on_T5.append(box)
            else:
                box.x_pos = _T5_ENTRY_X
                box.t5_visual_x_pos = 0
                box.t5_entry_aligned = True
                box.t5_after_c9 = False
        _add_event(state, line_num, 'info', 'TRANSFERT', f'T4 vers T5 {_box_label(state.box_on_T4)}')
        state.box_on_T4 = None

    mo = _AJOUT_T5_ID.search(text)
    if mo:
        id_a = int(mo.group(1))
        id_b = int(mo.group(2))
        ctx.setdefault('idb_to_ida', {})[id_b] = id_a
        ctx.setdefault('ida_to_idb', {})[id_a] = id_b
        box = _find_t5_box(state, id_alpha=id_a, id_b=id_b)
        if box:
            box.id_alpha = id_a
            box.id_b = id_b
            _add_event(
                state, line_num, 'info', 'TRANSFERT',
                f'T4->T5 idB={id_b} -> IdA={id_a}', box.barcode or box.source_ref
            )

    mo = _T4_LENGTH_SUMMARY.search(text)
    if mo:
        bdd, t2t, t4c, t4t, diff = (int(v) for v in mo.groups())
        severity = 'warning' if abs(diff) > 10 else 'info'
        _add_event(
            state, line_num, severity, 'T4',
            f'Controle longueur T4 diff {diff}mm',
            f'BdD:{bdd} T2T:{t2t} T4C:{t4c} T4T:{t4t}'
        )

    # ── Boîte sur C4 / pas de boite sur C4 ──────────────────────────────────
    if state.C4 == 0 and state.box_in_EA is not None:
        pass

    # ── C1 (fin T1) ──────────────────────────────────────────────────────────
    mo = _C1_SENSOR.search(text)
    if mo:
        state.C1 = int(mo.group(1))

    # ── FlagPoubellePleine ────────────────────────────────────────────────────
    mo = _POUBELLE.search(text)
    if mo:
        val = mo.group(1).lower()
        state.flag_poubelle_pleine = 0 if val in ('faux', '0', 'false', 'non') else 1

    # ── LzB (mesure hauteur T5, tentative) ────────────────────────────────────
    mo = _LZB.search(text)
    if mo:
        state.lzb = int(mo.group(1))

    if _ERROR_WORD.search(text):
        seen_error_lines = ctx.setdefault('seen_error_lines', set())
        if line_num not in seen_error_lines:
            seen_error_lines.add(line_num)
            _add_event(state, line_num, 'warning', 'TRACE', 'Message erreur trace', text.strip())

    _clear_missing_active_t5(state)
    _track_signal_edges(state, line_num, ctx)


# ── Détection de changements significatifs ────────────────────────────────────
def _is_significant(prev: MachineState, curr: MachineState) -> bool:
    """Retourne True si l'état a changé de façon notable (événement clé)."""
    if curr.events:
        return True
    # Changement de capteur (transition d'état front montant/descendant)
    if (prev.C0 != curr.C0 or prev.C1 != curr.C1 or
            prev.C2 != curr.C2 or prev.C3 != curr.C3 or
            prev.C4 != curr.C4 or prev.C5 != curr.C5 or
            prev.C6 != curr.C6 or prev.C9 != curr.C9 or
            prev.flag_poubelle_pleine != curr.flag_poubelle_pleine):
        return True
    # Changement de nombre de boîtes T5 (création / suppression)
    if len(prev.boxes_on_T5) != len(curr.boxes_on_T5):
        return True
    if [
        (b.id_alpha, b.id_b, b.x_pos, b.t5_visual_x_pos, b.t5_after_c9)
        for b in prev.boxes_on_T5
    ] != [
        (b.id_alpha, b.id_b, b.x_pos, b.t5_visual_x_pos, b.t5_after_c9)
        for b in curr.boxes_on_T5
    ]:
        return True
    # Transition d'état important d'un convoyeur
    for a, b in (
        (prev.state_tEA_T3, curr.state_tEA_T3),
        (prev.state_tT3_T4, curr.state_tT3_T4),
        (prev.state_tT4_T5, curr.state_tT4_T5),
        (prev.state_T5,     curr.state_T5),
    ):
        if a != b:
            return True
    if prev.t4_direction != curr.t4_direction:
        return True
    if prev.t5_direction != curr.t5_direction:
        return True
    if (
        prev.t5_active_id_alpha != curr.t5_active_id_alpha
        or prev.t5_x_butee != curr.t5_x_butee
        or prev.t5_visual_offset_mm != curr.t5_visual_offset_mm
    ):
        return True
    return False


# ── Fonction principale ───────────────────────────────────────────────────────
def parse_file(
    filepath: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    min_dt: float = 2.0,
) -> List[MachineState]:
    """
    Parse un fichier .old et retourne la liste des frames.

    min_dt   : intervalle minimal entre deux frames conservés (secondes).
                Défaut 2.0 s → ~1 frame/2 s + tous les événements clés.
                Un frame est toujours ajouté en cas de changement significatif.
    progress_cb(done_bytes, total_bytes) est appelé périodiquement.
    """
    total = os.path.getsize(filepath)
    done  = 0
    chunk = 1024 * 1024   # callback tous les 1 Mo

    frames: List[MachineState] = []
    current       = MachineState()
    prev_saved:    Optional[MachineState] = None
    current_ts:    Optional[float] = None
    first_ts:      Optional[float] = None
    last_saved_ts: float = -999.0
    ctx: dict     = {}

    # Mots-clés rapides pour pré-filtrer les lignes utiles
    KEYWORDS = ('T0:', 'T1:', 'T2:', 'tEA-T3', 'tT3/T4', 'tT4*T5',
                'T5:', 'BdD:', 'sur T5', 'Rech.', '-->', 'idCB1', 'idCB2', 'CB1:', 'CB2:',
                'boite est charg', 'BOITE-LOAD', 'EA->T3', 'rendu',
                'supp.', 'suppression', 'Suppr.', 'D\xe9place', 'MAJ (BUTEE', 'MAJ (APRES',
                'ALPHA:T5-LIST-PACK', 'Cr\xe9ation',
                'AjoutBtT5', 'DeplBtSurT5', 'capteurC1', 'FlagPoubelle', 'LzB', 'longueur boite',
                'mesure de longueur', 'tassement', 'diffT4')

    file_line = 0
    with open(filepath, encoding='latin-1', errors='replace') as fh:
        for raw in fh:
            file_line += 1
            done += len(raw)
            if progress_cb and done % chunk < len(raw):
                progress_cb(done, total)

            # Pré-filtre ultra-rapide : cherche '|' (séparateur timestamp)
            if '|' not in raw:
                continue

            mo = _HDR.search(raw)
            if not mo:
                continue

            day, h, m, s, ds, text = mo.groups()
            ts     = _ts(day, h, m, s, ds)
            ts_str = f"{h}:{m}:{s}"

            if first_ts is None:
                first_ts          = ts
                current_ts        = ts
                current.timestamp     = 0.0
                current.timestamp_str = ts_str
                current.line_num      = file_line

            if ts != current_ts:
                # -- Sauvegarde conditionnelle du frame courant ---------------
                dt = current.timestamp - last_saved_ts
                if prev_saved is None:
                    frames.append(current.deep_copy())
                    prev_saved    = frames[-1]
                    last_saved_ts = current.timestamp
                elif min_dt <= 0 or dt >= min_dt or _is_significant(prev_saved, current):
                    frames.append(current.deep_copy())
                    prev_saved    = frames[-1]
                    last_saved_ts = current.timestamp

                # -- Mise à jour timestamp (in-place, sans copie) -------------
                current.timestamp     = ts - first_ts
                current.timestamp_str = ts_str
                current.line_num      = file_line   # première ligne de ce groupe
                current.raw_lines     = []
                current.events        = []
                current_ts = ts

            is_known = any(k in text for k in KEYWORDS)
            current.raw_lines.append((file_line, text.rstrip(), is_known))
            if is_known:
                _update(current, text, ctx, file_line)

    # Dernier frame
    if current_ts is not None:
        frames.append(current.deep_copy())

    if progress_cb:
        progress_cb(total, total)

    return frames
