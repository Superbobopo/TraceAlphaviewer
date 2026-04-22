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
    r'\bT2:\s+(\S+)\s+eT2:(-?\d+)\s+eT3:(-?\d+)\s+C2:(\d+)\s+C3:(\d+)\s+C4:(\d+)'
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
    r'\bT5:\s+(\S+)\s+eT5=(-?\d+).*?C9:(\d+).*?pT5:(-?\d+).*?eT5useO:(\d+).*?eT5useA:(\d+)'
)

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
_CB1_IDENTIF = re.compile(
    r"idCB1:\s*-->\s*R\S*f:(\S+)\s+lot:\s*(\S*)", re.IGNORECASE
)
_DB_INFO = re.compile(
    r'-->\s+(.+?)\s+(\d+)x(\d+)x(\d+)\s+\d+g'
)
_RECH_INFOS = re.compile(
    r'Rech\. infos.*?pour (\S+)'
)
_MAJ_T5_POS = re.compile(
    r'MAJ \(BUTEE-T5\) boite Id:(\d+) ref:(\S+).*?nvlle dim:\d+x(\d+)\s+X:(\d+)'
)
_ERROR_WORD = re.compile(r'\b(err|erreur|timeout|alarme|defaut|défaut)\b', re.IGNORECASE)
_ERROR_REPEAT_DELAY = 300.0
# Position approximative d'arrivée depuis T4 (mm, coord machine) — lue dans les traces
_T5_ENTRY_X = 1011
_DEPL_T5 = re.compile(
    r'D[eé]place toutes les boites.*?sur (-?\d+) mm'
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
        'C6': state.C6,
        'C9': state.C9,
        'Poubelle': state.flag_poubelle_pleine,
    }
    labels = {
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


def _update(state: MachineState, text: str, ctx: dict, line_num: int) -> None:
    """Applique une ligne de texte sur l'état courant (in-place)."""

    # T0
    mo = _T0.search(text)
    if mo:
        state.state_T0 = mo.group(1)
        state.eT0 = int(mo.group(2))
        state.C0 = int(mo.group(3))
        _track_motor_error(state, line_num, ctx, 'T0', state.eT0, text)

    # T1
    mo = _T1.search(text)
    if mo:
        state.state_T1 = mo.group(1)
        state.eT1 = int(mo.group(2))
        _track_motor_error(state, line_num, ctx, 'T1', state.eT1, text)

    # T2
    mo = _T2.search(text)
    if mo:
        state.state_T2 = mo.group(1)
        state.eT2 = int(mo.group(2))
        state.eT3 = int(mo.group(3))
        state.C2 = int(mo.group(4))
        state.C3 = int(mo.group(5))
        state.C4 = int(mo.group(6))
        _track_motor_error(state, line_num, ctx, 'T2', state.eT2, text)
        _track_motor_error(state, line_num, ctx, 'T3', state.eT3, text)

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
        state.pT4 = int(mo.group(6))
        state.LgBtT4 = float(mo.group(7).replace(',', '.'))
        _track_motor_error(state, line_num, ctx, 'T4', state.eT4, text)
        _track_t4_cycle(state, line_num, ctx)

    # tT4*T5
    mo = _TT4T5.search(text)
    if mo:
        state.state_tT4_T5 = mo.group(1)
        state.C6 = int(mo.group(2))
        state.fgBfinT4 = int(mo.group(3))
        state.pT4 = int(mo.group(4))

    # T5
    mo = _T5.search(text)
    if mo:
        state.state_T5 = mo.group(1)
        state.eT5 = int(mo.group(2))
        state.C9 = int(mo.group(3))
        state.pT5 = int(mo.group(4))
        state.eT5useO = int(mo.group(5))
        state.eT5useA = int(mo.group(6))
        _track_motor_error(state, line_num, ctx, 'T5', state.eT5, text)

    # ── Boîte initiale sur T5 ────────────────────────────────────────────────
    mo = _BOX_INIT_T5.search(text)
    if mo:
        bc, name, lot, x = mo.group(1), mo.group(2), mo.group(3), int(mo.group(4))
        if not any(b.barcode == bc for b in state.boxes_on_T5):
            state.boxes_on_T5.append(
                BoxInfo(barcode=bc, name=name, lot=lot, x_pos=x, color=box_color(bc))
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
        state.boxes_on_T5 = [b for b in state.boxes_on_T5 if b.barcode != bc]
        state.boxes_on_T5.append(BoxInfo(
            barcode=bc, name=name, x_pos=x,
            width_mm=w, height_mm=hh, length_mm=lg,
            id_alpha=id_a, color=box_color(bc),
        ))
        _add_event(
            state, line_num, 'info', 'BOITE',
            f'Creation T5 {bc}', f'{name} IdA:{id_a} x={x}'
        )
        # La boîte n'est plus en EA ni sur T4 dès qu'elle est créée sur T5
        if state.box_on_T4 and state.box_on_T4.barcode == bc:
            state.box_on_T4 = None

    # ── Suppression boîte de T5 ──────────────────────────────────────────────
    mo = _BOX_REMOVE.search(text)
    if mo:
        id_a = int(mo.group(1))   # Id: (id_alpha)
        bc   = mo.group(2)        # ref: (barcode)
        state.boxes_on_T5 = [
            b for b in state.boxes_on_T5
            if b.barcode != bc and b.id_alpha != id_a
        ]
        _add_event(state, line_num, 'warning', 'BOITE', f'Suppression T5 {bc}', f'IdA:{id_a}')

    # ── Suppression boîte de T5 (format long) ──────────────────────────────
    mo = _BOX_REMOVE2.search(text)
    if mo:
        id_a = int(mo.group(1))
        state.boxes_on_T5 = [
            b for b in state.boxes_on_T5
            if b.id_alpha != id_a
        ]
        _add_event(state, line_num, 'warning', 'BOITE', f'Suppression T5 IdA:{id_a}')

    # ── Suppression boîte (format "Suppr. la boite IdA:X") ─────────────────
    mo = _BOX_REMOVE3.search(text)
    if mo:
        id_a = int(mo.group(1))
        state.boxes_on_T5 = [
            b for b in state.boxes_on_T5
            if b.id_alpha != id_a
        ]
        _add_event(state, line_num, 'warning', 'BOITE', f'Suppression boite IdA:{id_a}')

    # ── Mise à jour position X sur T5 (après tassement) ────────────────────
    mo = _MAJ_T5_POS.search(text)
    if mo:
        id_a = int(mo.group(1))
        bc   = mo.group(2)
        w    = int(mo.group(3))   # nvlle dim: WxH → H = largeur mesurée (mm)
        x    = int(mo.group(4))
        found = False
        for b in state.boxes_on_T5:
            if b.barcode == bc or b.id_alpha == id_a:
                b.x_pos    = x
                b.id_alpha = id_a
                if w > 0:
                    b.width_mm = w
                found = True
                break
        if not found:
            # Boîte pas encore suivie (ex: arrivée non capturée) — on la crée
            state.boxes_on_T5.append(BoxInfo(
                barcode=bc, id_alpha=id_a, x_pos=x,
                width_mm=w, color=box_color(bc)
            ))
        _add_event(state, line_num, 'info', 'BOITE', f'MAJ butee T5 {bc}', f'IdA:{id_a} X:{x} larg:{w}')

    # ── Déplacement global des boîtes sur T5 (tassement) ────────────────────
    mo = _DEPL_T5.search(text)
    if mo:
        delta = int(mo.group(1))
        for b in state.boxes_on_T5:
            b.x_pos += delta

    # ── Mémorisation du code-barres cherché en BdD ──────────────────────────
    mo = _RECH_INFOS.search(text)
    if mo:
        ctx['pending_bc'] = mo.group(1)
        ctx['pending_name'] = ''
        ctx['pending_dims'] = None

    # ── Infos BdD (nom + dimensions) ────────────────────────────────────────
    mo = _DB_INFO.search(text)
    if mo and 'pending_bc' in ctx:
        ctx['pending_name'] = mo.group(1).strip()
        ctx['pending_dims'] = (int(mo.group(2)), int(mo.group(3)), int(mo.group(4)))
        bc = ctx['pending_bc']
        if state.box_in_EA and state.box_in_EA.barcode == bc:
            state.box_in_EA.name = ctx['pending_name']
            w, hh, lg = ctx['pending_dims']
            state.box_in_EA.width_mm = w
            state.box_in_EA.height_mm = hh
            state.box_in_EA.length_mm = lg

    # ── Identification CB1 terminée ──────────────────────────────────────────
    mo = _CB1_IDENTIF.search(text)
    if mo:
        bc  = mo.group(1)
        lot = mo.group(2)
        state.idCB1_barcode = bc
        state.idCB1_state   = 'IDENTIFIED'
        name = ctx.get('pending_name', '')
        dims = ctx.get('pending_dims')
        if state.box_in_EA is None:
            state.box_in_EA = BoxInfo(barcode=bc, lot=lot, name=name,
                                      color=box_color(bc))
        else:
            state.box_in_EA.barcode = bc
            state.box_in_EA.lot     = lot
            if name:
                state.box_in_EA.name = name
        if dims:
            state.box_in_EA.width_mm, state.box_in_EA.height_mm, state.box_in_EA.length_mm = dims
        _add_event(state, line_num, 'info', 'IDENTIF', f'Identification CB1 {bc}', f'lot:{lot}')

    # ── Boîte chargée sur T2 ─────────────────────────────────────────────────
    if 'T2: une boite est charg' in text or 'BOITE-LOAD' in text:
        if state.box_in_EA is None:
            state.box_in_EA = BoxInfo(color=box_color('0'))

    # ── Transfert EA → T3 terminé : boîte passe de EA vers T3/T4 ───────────
    if 'le transfert (EA->T3) est termin' in text:
        if state.box_in_EA:
            state.box_on_T4 = state.box_in_EA
            _add_event(
                state, line_num, 'info', 'TRANSFERT',
                f'EA vers T3 {state.box_on_T4.barcode or "boite"}'
            )
        state.box_in_EA = None

    # ── Fin de transfert T4 → T5 : box_on_T4 est ajoutée à boxes_on_T5 ──────
    if 'la boite est rendu (physiquement) sur T5' in text:
        bc = state.box_on_T4.barcode if state.box_on_T4 else ''
        if state.box_on_T4 is not None:
            b = state.box_on_T4
            # Évite le doublon si la boîte est déjà dans la liste
            if not any(x.barcode == b.barcode for x in state.boxes_on_T5):
                state.boxes_on_T5.append(BoxInfo(
                    barcode=b.barcode, name=b.name, lot=b.lot,
                    length_mm=b.length_mm, width_mm=b.width_mm, height_mm=b.height_mm,
                    id_alpha=b.id_alpha,
                    x_pos=abs(state.pT5) if state.pT5 != 0 else _T5_ENTRY_X,
                    color=b.color,
                ))
        _add_event(state, line_num, 'info', 'TRANSFERT', f'T4 vers T5 {bc or "boite"}')
        state.box_on_T4 = None

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
    # Transition d'état important d'un convoyeur
    for a, b in (
        (prev.state_tEA_T3, curr.state_tEA_T3),
        (prev.state_tT3_T4, curr.state_tT3_T4),
        (prev.state_tT4_T5, curr.state_tT4_T5),
        (prev.state_T5,     curr.state_T5),
    ):
        if a != b:
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
                'T5:', 'BdD:', 'sur T5', 'Rech.', '-->', 'idCB1',
                'boite est charg', 'BOITE-LOAD', 'EA->T3', 'rendu',
                'supp.', 'suppression', 'Suppr.', 'D\xe9place', 'MAJ (BUTEE', 'Cr\xe9ation',
                'capteurC1', 'FlagPoubelle', 'LzB', 'longueur boite',
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
                elif dt >= min_dt or _is_significant(prev_saved, current):
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
