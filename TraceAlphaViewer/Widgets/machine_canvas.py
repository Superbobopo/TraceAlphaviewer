"""
MachineCanvas – widget Canvas dessinant l'état de la machine Alpha à un instant t.

Disposition (4 rangées, schéma physique) :

  Rangée 1 :  [  T0  ] ──► [   C0    T1    C1   ]
                                          │ (U-turn)
  Rangée 2 :  [C3 C2  T2  ◄──────────── ]
                │
  Rangée 3 :  [EA C4] ──► [ T3  C5 ] ──► [   T4   ]
                                           [ C6 bar ]
  Rangée 4 :  [Poub  C9    T5 →   T4-entry  MesureH|butée]

Capteurs dessinés comme barres colorées sur les tapis (fidèle au schéma physique) :
  C0 : barre verticale début T1
  C1 : barre verticale fin T1
  C2, C3 : barres verticales gauche T2
  C4 : barre verticale sur EA
  C5 : barre verticale droite T3
  C6 : barre horizontale sur T4
  C9 : barre verticale T5
  Poubelle : barre verticale gauche T5 (FlagPoubellePleine)
  Mesure H. : point droite T5 (LzB)
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional

from Models.state import BoxInfo, MachineState

# ── Couleurs ──────────────────────────────────────────────────────────────────
C = {
    'bg':         '#1a1a2e',
    'belt_idle':  '#252535',
    'belt_run':   '#1b3a5f',
    'belt_ready': '#1a3a20',
    'belt_init':  '#1a1a2e',
    'belt_error': '#4a1f2a',
    'belt_bdr':   '#445566',
    'belt_lbl':   '#bbccdd',
    'st_lbl':     '#556677',
    'sens_off':   '#2a3540',
    'sens_on':    '#ff4444',
    'sens_C5':    '#44cc44',
    'sens_C6':    '#ffaa00',
    'sens_C9':    '#00aaff',
    'dir_run':    '#44cc44',
    'dir_idle':   '#335566',
    'dir_error':  '#ff5555',
    'box_bdr':    '#111122',
}

# ── Dimensions canvas ─────────────────────────────────────────────────────────
CANVAS_W = 920
CANVAS_H = 540
X_SHIFT = 110

# ── Rectangles des tapis (x1, y1, x2, y2) ────────────────────────────────────
L0 = {
    'T0': ( 20,  34,  102,  88),
    'T1': (128,  34,  388,  88),
    'T2': ( 20, 132,  392, 188),
    'EA': ( 20, 252,  142, 344),
    'T3': (163, 266,  354, 334),
    'T4': (428, 242,  540, 400),
    'T5': ( 20, 418,  638, 530),   # s'arrête à la butée (Mesure Hauteur)
}
L = {
    name: (x1 + X_SHIFT, y1, x2 + X_SHIFT, y2)
    for name, (x1, y1, x2, y2) in L0.items()
}
T4_PHYSICAL_MM = 500
T4_C6_FROM_BUTEE_MM = 436
T4_C6_Y = int(L['T4'][1] + (L['T4'][3] - L['T4'][1]) * T4_C6_FROM_BUTEE_MM / T4_PHYSICAL_MM)

# Dimensions physiques pour mise à l'échelle
T3_MM       = 220    # longueur T3 (mm)
T4_MM       = T4_PHYSICAL_MM    # hauteur T4 physique (mm)
T3_C5_X     = 320 + X_SHIFT
T3_BOX_SCALE = 0.60
T3_BOX_HEIGHT = 22
T4_BOX_SCALE = 1.00
T4_BOX_WIDTH_RATIO = 0.30
T4_T5_TRANSFER_START_PT4 = T4_C6_FROM_BUTEE_MM
# T5 : coordonnées machine (x diminue vers la droite / butée, augmente vers la gauche / Poubelle)
T5_PHYSICAL_MM = 770
T5_C9_FROM_BUTEE_MM = 310
# X:942 est observe sur les lignes MAJ (BUTEE-T5), quand la boite est contre la butee.
# Boîte arrivant de T4 ≈ 1011 mm (lu dans la trace : sur T5: … x=1011)
# T5_X_MAX = extent gauche estimé (zone Poubelle) — ajuster si les boîtes sortent du canvas
T5_X_BUTEE = 942    # X apres MAJ (BUTEE-T5), cote butee / mesure hauteur
# La plage metier reste large pour accepter les positions Alpha cote poubelle
# sans ajouter de contrainte geometrique artificielle cote C9 ou butee.
T5_X_MAX   = 1750   # plage visuelle rendue: dezoom position T5, sans changer les dimensions produit
T5_ENTRY_X = 1060
T5_BOX_DIM_SCALE = 0.75
T5_BOX_Y_PAD = 8


# ── Helpers de dessin ─────────────────────────────────────────────────────────

def _belt_color(state_str: str, eT: int) -> str:
    if eT < 0:
        return C['belt_error']
    s = state_str.upper()
    if s in ('INIT', ''):
        return C['belt_init']
    if s in ('PRET', 'WAIT-COND', 'FIN-VIDAGE', 'MODE-AUTO'):
        return C['belt_idle'] if abs(eT) <= 2 else C['belt_run']
    if 'TRSF' in s or 'CHG' in s or 'AUTO' in s or 'LOAD' in s:
        return C['belt_run']
    if 'BOITE-EN-BUTEE' in s or 'POS' in s:
        return C['belt_ready']
    return C['belt_idle']


def _sensor_color(name: str, active: int) -> str:
    if not active:
        return C['sens_off']
    if name == 'C5':
        return C['sens_C5']
    if name == 'C6':
        return C['sens_C6']
    if name == 'C9':
        return C['sens_C9']
    return C['sens_on']


def _canvas_state_label(state_str: str) -> str:
    """Libelle court du tapis sur le schema, sans les etats de fond."""
    s = state_str.upper()
    if s.startswith('WAIT-COND') or s in ('PRET', 'MODE-AUTO', 'FIN-VIDAGE'):
        return ''
    return state_str[:15]


def _draw_belt(cv: tk.Canvas, rect: tuple, label: str,
               state_str: str, eT: int, state_outside: bool = False) -> None:
    x1, y1, x2, y2 = rect
    outline = '#ff5555' if eT < 0 else C['belt_bdr']
    width = 3 if eT < 0 else 2
    cv.create_rectangle(x1, y1, x2, y2,
                        fill=_belt_color(state_str, eT),
                        outline=outline, width=width)
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    cv.create_text(cx, cy - 7, text=label,
                   fill=C['belt_lbl'], font=('Consolas', 10, 'bold'))
    state_label = _canvas_state_label(state_str)
    if state_label:
        sy = y2 + 10 if state_outside else cy + 8
        cv.create_text(cx, sy, text=state_label,
                       fill=C['st_lbl'], font=('Consolas', 7))


def _sensor_vbar(cv: tk.Canvas, name: str, cx: int,
                 belt_rect: tuple, active: int,
                 on_color: Optional[str] = None) -> None:
    """Capteur = barre verticale sur tapis horizontal (fidèle au schéma)."""
    _, y1, _, y2 = belt_rect
    color = on_color if (active and on_color) else _sensor_color(name, active)
    cv.create_line(cx, y1, cx, y2, fill=color, width=2)
    r = 4
    cv.create_oval(cx - r, y1 - r, cx + r, y1 + r,
                   fill=color, outline='#444455', width=1)
    cv.create_text(cx, y1 - r - 5, text=name,
                   fill='#aabbcc', font=('Consolas', 7, 'bold'), anchor='s')


def _sensor_hbar(cv: tk.Canvas, name: str, cy: int,
                 belt_rect: tuple, active: int) -> None:
    """Capteur = barre horizontale sur tapis vertical (T4)."""
    x1, _, x2, _ = belt_rect
    color = _sensor_color(name, active)
    cv.create_line(x1, cy, x2, cy, fill=color, width=2)
    r = 4
    cv.create_oval(x2 - r, cy - r, x2 + r, cy + r,
                   fill=color, outline='#444455', width=1)
    cv.create_text(x2 + 8, cy, text=name,
                   fill='#aabbcc', font=('Consolas', 7, 'bold'), anchor='w')


def _draw_box_h(cv: tk.Canvas, belt_rect: tuple, x_px: int, w_px: int,
                box: Optional[BoxInfo], height_px: int = 0,
                y_align: str = 'center') -> Optional[tuple[int, int, int, int]]:
    """Boîte sur tapis horizontal."""
    _, y1, _, y2 = belt_rect
    x1b, x2b = belt_rect[0], belt_rect[2]
    if x_px + w_px <= x1b:   # boîte entièrement hors canvas gauche → fantôme évité
        return None
    bx1 = max(x1b + 2, min(x_px, x2b - w_px - 2))
    bx2 = min(x2b - 2, bx1 + max(w_px, 6))
    belt_h = y2 - y1
    h_px = height_px if height_px > 0 else belt_h - 6
    h_px = max(12, min(belt_h - 6, h_px))
    if y_align == 'bottom':
        by2 = y2 - 3
        by1 = by2 - h_px
    else:
        cy = (y1 + y2) // 2
        by1 = cy - h_px // 2
        by2 = by1 + h_px
    fill = box.color if box else '#4FC3F7'
    cv.create_rectangle(bx1, by1, bx2, by2,
                        fill=fill, outline=C['box_bdr'], width=1)
    lbl = box.short_label() if box else ''
    if lbl:
        cv.create_text((bx1 + bx2) // 2, (by1 + by2) // 2,
                       text=lbl, fill='#111122',
                       font=('Consolas', 7, 'bold'),
                       width=max(bx2 - bx1 - 4, 10))
    return bx1, by1, bx2, by2


def _draw_box_h_to_x(cv: tk.Canvas, belt_rect: tuple, right_x: int, w_px: int,
                     box: Optional[BoxInfo], height_px: int = 0,
                     y_align: str = 'center') -> Optional[tuple[int, int, int, int]]:
    """Boite horizontale avec son bord d'attaque aligne sur right_x."""
    x1b, _, _, _ = belt_rect
    x_px = max(x1b + 2, right_x - max(w_px, 6))
    return _draw_box_h(cv, belt_rect, x_px, w_px, box, height_px, y_align)


def _t5_box_dims_px(box: BoxInfo, belt_rect: tuple, scale_t5: float) -> tuple[int, int]:
    """Dimensions visuelles T5: C6 donne la longueur, C9 donne la largeur."""
    _, y1, _, y2 = belt_rect
    max_h = max(12, (y2 - y1) - 2 * T5_BOX_Y_PAD)

    length_mm = max(0, int(box.length_mm or 0))
    width_mm = max(0, int(box.width_mm or 0))

    fallback_mm = max(0, int(box.t5_footprint_mm or 0))
    horizontal_mm = width_mm or fallback_mm or length_mm or 40
    vertical_mm = length_mm or width_mm or min(fallback_mm, 80) or 40

    dim_scale = scale_t5 * T5_BOX_DIM_SCALE
    if vertical_mm * dim_scale > max_h:
        dim_scale = max_h / max(vertical_mm, 1)

    w_px = max(8, int(horizontal_mm * dim_scale))
    h_px = max(12, int(vertical_mm * dim_scale))
    return w_px, h_px


def _draw_t5_box(cv: tk.Canvas, belt_rect: tuple, x_px: int, w_px: int,
                 h_px: int, box: BoxInfo) -> Optional[tuple[int, int, int, int]]:
    """Boite T5 en vue de dessus, centree dans l'epaisseur du tapis."""
    x1, y1, x2, y2 = belt_rect
    if x_px + w_px <= x1:
        return None

    bx1 = max(x1 + 2, min(x_px, x2 - w_px - 2))
    bx2 = min(x2 - 2, bx1 + max(w_px, 6))
    cy = (y1 + y2) // 2
    by1 = max(y1 + T5_BOX_Y_PAD, cy - h_px // 2)
    by2 = min(y2 - T5_BOX_Y_PAD, by1 + h_px)
    by1 = max(y1 + T5_BOX_Y_PAD, by2 - h_px)

    cv.create_rectangle(bx1, by1, bx2, by2,
                        fill=box.color, outline=C['box_bdr'], width=1)
    lbl = box.short_label()
    if lbl:
        cv.create_text((bx1 + bx2) // 2, (by1 + by2) // 2,
                       text=lbl, fill='#111122',
                       font=('Consolas', 7, 'bold'),
                       width=max(bx2 - bx1 - 4, 10))
    return bx1, by1, bx2, by2


def _draw_box_v(cv: tk.Canvas, belt_rect: tuple,
                pos_from_top_mm: int, total_mm: int,
                box: Optional[BoxInfo],
                length_mm: float = 0.0,
                dim_scale: float = 1.0,
                width_ratio: float = 1.0) -> Optional[tuple[int, int, int, int]]:
    """Boîte sur tapis vertical (T4 — descend de haut en bas)."""
    x1, y1, x2, y2 = belt_rect
    belt_h = y2 - y1
    scale  = belt_h / max(total_mm, 1)
    measured_len = float(length_mm or (box.length_mm if box else 0) or 50)
    h_px   = max(12, min(belt_h - 6, int(measured_len * scale * dim_scale)))
    pos_px = max(0, int(pos_from_top_mm * scale))
    pos_px = min(pos_px, max(0, (belt_h - 6) - h_px))
    by1    = y1 + 3 + pos_px
    by2    = by1 + h_px
    width_ratio = max(0.20, min(1.0, width_ratio))
    box_w = max(16, int((x2 - x1) * width_ratio))
    if width_ratio <= T4_BOX_WIDTH_RATIO and box_w >= h_px:
        box_w = max(12, h_px - 2)
    bx1 = (x1 + x2 - box_w) // 2
    bx2 = bx1 + box_w
    fill   = box.color if box else '#4FC3F7'
    cv.create_rectangle(bx1, by1, bx2, by2,
                        fill=fill, outline=C['box_bdr'], width=1)
    lbl = box.short_label() if box else ''
    if lbl:
        cv.create_text((bx1 + bx2) // 2, (by1 + by2) // 2,
                       text=lbl, fill='#111122',
                       font=('Consolas', 7, 'bold'), width=max(box_w - 6, 10))
    return bx1, by1, bx2, by2


def _draw_box_v_to_y(cv: tk.Canvas, belt_rect: tuple, bottom_y: int,
                     total_mm: int, box: Optional[BoxInfo],
                     length_mm: float = 0.0,
                     dim_scale: float = 1.0,
                     width_ratio: float = 1.0) -> Optional[tuple[int, int, int, int]]:
    """Boite verticale avec son bord d'attaque aligne sur bottom_y."""
    _, y1, _, y2 = belt_rect
    belt_h = y2 - y1
    scale = belt_h / max(total_mm, 1)
    measured_len = float(length_mm or (box.length_mm if box else 0) or 50)
    h_px = max(12, min(belt_h - 6, int(measured_len * scale * dim_scale)))
    by1 = max(y1 + 3, min(bottom_y - h_px, y2 - 3 - h_px))
    pos_from_top_mm = int((by1 - y1 - 3) / max(scale, 0.001))
    return _draw_box_v(
        cv, belt_rect, pos_from_top_mm, total_mm, box, length_mm,
        dim_scale, width_ratio
    )


def _t4_t5_transfer_bottom_y(st: MachineState) -> int:
    """Position visuelle de sortie T4->T5 apres perte C6."""
    travel_px = max(1, L['T4'][3] - T4_C6_Y)
    progress = (T4_T5_TRANSFER_START_PT4 - max(st.pT4, 0)) / T4_T5_TRANSFER_START_PT4
    progress = max(0.0, min(1.0, progress))
    return int(T4_C6_Y + travel_px * progress)


def _t5_entry_aligned_x(w_px: int) -> int:
    """Aligne l'entree T5 sur l'axe visuel central de T4."""
    t4_center_x = (L['T4'][0] + L['T4'][2]) // 2
    return t4_center_x - w_px // 2


def _t5_visual_origin(st: MachineState) -> int:
    # Origine du repere visuel T5 : normalement le X de butee lu dans la trace.
    # Si la trace utilise un grand repere Alpha, on revient a la butee canonique.
    if 0 < st.t5_x_butee <= T5_X_MAX:
        return int(st.t5_x_butee)
    return T5_X_BUTEE


def _t5_normalized_x(st: MachineState, x_pos: int) -> int:
    """Ramene les grands X Alpha dans le repere visuel sans perdre la distance a la butee."""
    x_pos = int(x_pos)
    butee_x = int(st.t5_x_butee or 0)
    if butee_x > T5_X_MAX and x_pos > T5_X_MAX:
        # Certaines traces ont une butee a plusieurs milliers de mm. La seule
        # valeur utile pour le canvas est la distance entre la boite et cette
        # butee, surtout quand X > butee apres passage C9.
        return T5_X_BUTEE + abs(x_pos - butee_x)
    return x_pos


def _t5_physical_scale() -> float:
    return (L['T5'][2] - L['T5'][0]) / max(T5_PHYSICAL_MM, 1)


def _t5_c9_x() -> int:
    return L['T5'][2] - int(T5_C9_FROM_BUTEE_MM * _t5_physical_scale())


def _t5_render_x_pos(
    st: MachineState,
    box: BoxInfo,
    include_visual_offset: bool = True,
) -> int:
    """Retourne la position T5 stable, puis l'animation signee du tapis."""
    # Le rendu part de la position visuelle continue quand elle existe, puis
    # ajoute seulement l'offset temporaire signe issu de pT5.
    x_pos = _t5_normalized_x(st, int(box.t5_visual_x_pos or box.x_pos or T5_X_BUTEE))
    if include_visual_offset:
        x_pos += int(st.t5_visual_offset_mm or 0)
    return x_pos


def _t5_is_initial_entry(box: BoxInfo, st: MachineState) -> bool:
    return (
        box.t5_entry_aligned
        and not st.t5_visual_offset_mm
        and not box.t5_visual_x_pos
        and abs(int(box.x_pos or T5_ENTRY_X) - T5_ENTRY_X) <= 10
    )


def _conn(cv: tk.Canvas, *pts: int) -> None:
    """Ligne de connexion entre tapis (avec flèche)."""
    cv.create_line(*pts, fill='#445566', width=2,
                   arrow=tk.LAST, arrowshape=(8, 10, 4))


def _dir_arrow(
    cv: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: str = C['dir_run'],
) -> None:
    """Flèche verte indiquant le sens de rotation du tapis."""
    cv.create_line(x1, y1, x2, y2, fill=color,
                   arrow=tk.LAST, arrowshape=(6, 8, 3), width=2)


def _arrow_color(eT: int, is_running: bool) -> str:
    if eT < 0:
        return C['dir_error']
    return C['dir_run'] if is_running else C['dir_idle']


def _is_fixed_belt_running(state_str: str, eT: int) -> bool:
    if eT < 0:
        return False
    if eT in (0, 1, 2, 5, 11, 43, 46, 49, 51, 83, 85, 89):
        return False
    s = state_str.upper()
    return any(token in s for token in ('AUTO', 'CHG', 'TRSF', 'VIDAGE', 'LOAD'))


def _is_t2_running(st: MachineState) -> bool:
    if st.eT2 < 0:
        return False
    if st.eT2 in (41, 42, 44, 45, 47, 61, 81, 82):
        return True
    return st.eT2 == 6 and 'VIDAGE' in st.state_T2.upper()


def _draw_t2_dir_arrow(cv: tk.Canvas, st: MachineState) -> None:
    cx = (L['T2'][0] + L['T2'][2]) // 2
    cy = L['T2'][3] - 8
    span = 22
    _dir_arrow(cv, cx + span, cy, cx - span, cy, _arrow_color(st.eT2, _is_t2_running(st)))


def _draw_t5_dir_arrow(cv: tk.Canvas, st: MachineState) -> None:
    cx = (L['T5'][0] + L['T5'][2]) // 2
    cy = L['T5'][3] - 8
    span = 28
    color = _arrow_color(st.eT5, st.t5_direction != 0)
    if st.t5_direction < 0:
        _dir_arrow(cv, cx + span, cy, cx - span, cy, color)
    elif st.t5_direction > 0:
        _dir_arrow(cv, cx - span, cy, cx + span, cy, color)
    else:
        _dir_arrow(cv, cx - span, cy, cx + span, cy, color)


def _draw_t4_dir_arrow(cv: tk.Canvas, st: MachineState) -> None:
    cx = L['T4'][2] - 10
    cy = (L['T4'][1] + L['T4'][3]) // 2
    span = 18
    color = _arrow_color(st.eT4, st.t4_direction != 0)
    if st.t4_direction < 0:
        _dir_arrow(cv, cx, cy + span, cx, cy - span, color)
    elif st.t4_direction > 0:
        _dir_arrow(cv, cx, cy - span, cx, cy + span, color)
    else:
        _dir_arrow(cv, cx, cy - span, cx, cy + span, color)


# ── Widget principal ──────────────────────────────────────────────────────────
class MachineCanvas(tk.Canvas):

    def __init__(self, master, **kwargs):
        kwargs.setdefault('bg', C['bg'])
        kwargs.setdefault('highlightthickness', 0)
        super().__init__(master, **kwargs)
        self._state: Optional[MachineState] = None
        self._t5_hitboxes: list[tuple[tuple[int, int, int, int], BoxInfo]] = []
        self._tooltip_id: Optional[int] = None
        self.bind('<Motion>', self._on_motion)
        self.bind('<Leave>', self._hide_tooltip)

    def update_state(self, state: MachineState) -> None:
        self._state = state
        self.delete('all')
        self._t5_hitboxes = []
        self._tooltip_id = None
        self._draw(state)

    def _hide_tooltip(self, event=None) -> None:
        if self._tooltip_id is not None:
            self.delete('t5_tooltip')
            self._tooltip_id = None

    def _on_motion(self, event) -> None:
        for (x1, y1, x2, y2), box in reversed(self._t5_hitboxes):
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self._show_t5_tooltip(event.x, event.y, box)
                return
        self._hide_tooltip()

    def _show_t5_tooltip(self, x: int, y: int, box: BoxInfo) -> None:
        self._hide_tooltip()
        lines = [
            f'IdA:{box.id_alpha}' if box.id_alpha else 'IdA:-',
            f'idB:{box.id_b}' if box.id_b else 'idB:-',
        ]
        if box.barcode:
            lines.append(box.barcode)
        if box.dim_label():
            lines.append(box.dim_label())
        text = '\n'.join(lines)
        tx = min(x + 12, CANVAS_W - 150)
        ty = max(8, y - 44)
        tid = self.create_text(
            tx + 6, ty + 5, text=text, anchor='nw',
            fill='#ddeeff', font=('Consolas', 8),
            tags='t5_tooltip',
        )
        bbox = self.bbox(tid)
        if bbox:
            pad = 5
            rect = self.create_rectangle(
                bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad,
                fill='#101820', outline='#88aacc', width=1,
                tags='t5_tooltip',
            )
            self.tag_raise(tid, rect)
        self._tooltip_id = tid

    def _draw(self, st: MachineState) -> None:
        cv = self

        # ── Connexions entre tapis ────────────────────────────────────────────
        _conn(cv, L['T0'][2], 61,  L['T1'][0], 61)                       # T0 → T1
        _conn(cv, L['T1'][2], 61,  420 + X_SHIFT, 61, 420 + X_SHIFT, 160, L['T2'][2], 160)   # T1 → T2 (U-turn)
        _conn(cv, L['T2'][0], 160, 8 + X_SHIFT,   160, 8 + X_SHIFT,   298, L['EA'][0], 298)  # T2 → EA
        _conn(cv, L['EA'][2], 298, L['T3'][0], 298)                       # EA → T3
        _conn(cv, L['T3'][2], 300, L['T4'][0], 300)                       # T3 → T4
        t4_drop_x = L['T4'][2] - 2
        _conn(cv, t4_drop_x, L['T4'][3], t4_drop_x, L['T5'][1])           # T4 → T5 (sortie côté droit)

        # ── Tapis ─────────────────────────────────────────────────────────────
        _draw_belt(cv, L['T0'], 'T0', st.state_T0,    st.eT0)
        _draw_belt(cv, L['T1'], 'T1', st.state_T1,    st.eT1)
        _draw_belt(cv, L['T2'], 'T2', st.state_T2,    st.eT2)

        # Zone EA (pointillés bleus)
        ea_fill = _belt_color(st.state_tEA_T3, st.eT3)
        x1, y1, x2, y2 = L['EA']
        cv.create_rectangle(x1, y1, x2, y2, fill=ea_fill,
                            outline='#aaddff', width=2, dash=(4, 2))
        cv.create_text((x1+x2)//2, (y1+y2)//2 - 8, text='EA',
                       fill='#aaddff', font=('Consolas', 10, 'bold'))
        ea_state_label = _canvas_state_label(st.state_tEA_T3)
        if ea_state_label:
            cv.create_text((x1+x2)//2, (y1+y2)//2 + 8,
                           text=ea_state_label[:14],
                           fill=C['st_lbl'], font=('Consolas', 7))

        _draw_belt(cv, L['T3'], 'T3', st.state_tT3_T4, st.eT3, state_outside=True)
        _draw_belt(cv, L['T4'], 'T4', st.state_tT4_T5, st.eT4)
        _draw_belt(cv, L['T5'], 'T5', st.state_T5,     st.eT5)

        # ── Capteurs (barres sur les tapis) ───────────────────────────────────

        # T1 : C0 début, C1 fin
        _sensor_vbar(cv, 'C0', 160 + X_SHIFT, L['T1'], st.C0)
        _sensor_vbar(cv, 'C1', 360 + X_SHIFT, L['T1'], st.C1)

        # T2 : C3 et C2 (sortie gauche)
        _sensor_vbar(cv, 'C3',  47 + X_SHIFT, L['T2'], st.C3)
        _sensor_vbar(cv, 'C2',  82 + X_SHIFT, L['T2'], st.C2)

        # EA : C4
        _sensor_vbar(cv, 'C4', 115 + X_SHIFT, L['EA'], st.C4)

        # T3 : C5 (côté droit)
        _sensor_vbar(cv, 'C5', T3_C5_X, L['T3'], st.C5)

        # T4 : C6 (barre horizontale)
        _sensor_hbar(cv, 'C6', T4_C6_Y, L['T4'], st.C6)
        if st.LgBtT4 > 0:
            t4 = L['T4']
            lg_color = '#ffcc66' if st.C6 else '#887744'
            cv.create_text(
                (t4[0] + t4[2]) // 2,
                t4[3] - 13,
                text=f'Lg {st.LgBtT4:.0f}mm',
                fill=lg_color,
                font=('Consolas', 8, 'bold'),
            )

        # T5 : Poubelle (gauche), C9 (entree T4->T5), Mesure Hauteur (droite)
        poub_color = '#ff8800' if st.flag_poubelle_pleine else '#334433'
        _sensor_vbar(cv, 'Poubelle', L['T5'][0] + 35, L['T5'],
                     st.flag_poubelle_pleine, on_color=poub_color)
        if st.flag_poubelle_pleine:
            cv.create_text(L['T5'][0] + 35, L['T5'][1] - 17, text='PLEINE',
                           fill='#ff8800', font=('Consolas', 6, 'bold'), anchor='s')

        c9_x = _t5_c9_x()
        _sensor_vbar(cv, 'C9', c9_x, L['T5'], st.C9)

        # Mesure Hauteur (LzB) : hors tapis pour ne pas etre masquee par les boites.
        mh_x = L['T5'][2] - 18
        mh_y = L['T5'][1] - 16
        mh_c = '#cc3333' if st.lzb > 0 else '#335566'
        cv.create_oval(mh_x - 5, mh_y - 5, mh_x + 5, mh_y + 5,
                       fill=mh_c, outline='#667788', width=1)
        cv.create_text(mh_x, mh_y - 7, text='Mesure H.',
                       fill='#cc6666', font=('Consolas', 7), anchor='s')

        # Butée T5 (paroi droite)
        cv.create_line(L['T5'][2] - 3, L['T5'][1], L['T5'][2] - 3, L['T5'][3],
                       fill='#889900', width=3)
        cv.create_text(L['T5'][2] - 3, L['T5'][1] - 5, text='butée',
                       fill='#889900', font=('Consolas', 6), anchor='s')

        # ── Flèches sens de rotation (vertes, bas des tapis) ─────────────────
        for rect, dx, dy, state_str, eT in [
            (L['T0'], 22, 0, st.state_T0, st.eT0),          # T0 →
            (L['T1'], 22, 0, st.state_T1, st.eT1),          # T1 →
            (L['T3'], 18, 0, st.state_tT3_T4, st.eT3),      # T3 →
        ]:
            cx = (rect[0] + rect[2]) // 2
            cy = rect[3] - 8
            color = _arrow_color(eT, _is_fixed_belt_running(state_str, eT))
            _dir_arrow(cv, cx - dx, cy + dy, cx + dx, cy + dy, color)

        # T2: sens physique vers EA, couleur selon activite moteur.
        _draw_t2_dir_arrow(cv, st)

        # T4 ↓ (flèche verticale sur le côté droit du tapis)
        _draw_t4_dir_arrow(cv, st)

        # T5: sens dynamique deduit du deplacement encodeur pT5.
        _draw_t5_dir_arrow(cv, st)

        # ── Boîte en EA ──────────────────────────────────────────────────────
        if st.C4 or st.box_in_EA:
            box  = st.box_in_EA
            fill = box.color if box else '#4FC3F7'
            bx1, by1 = L['EA'][0] + 5, L['EA'][1] + 5
            bx2, by2 = L['EA'][2] - 5, L['EA'][3] - 5
            cv.create_rectangle(bx1, by1, bx2, by2,
                                fill=fill, outline=C['box_bdr'], width=1)
            lbl = (box.short_label() if box
                   else ('CB1…' if st.idCB1_state else '?'))
            cv.create_text((bx1 + bx2) // 2, (by1 + by2) // 2, text=lbl,
                           fill='#111122', font=('Consolas', 7, 'bold'),
                           width=(bx2 - bx1) - 4)

        # ── Boîte sur T3 (pT3 ≤ 0) ───────────────────────────────────────────
        if st.C5 and st.box_on_T3:
            t3    = L['T3']
            bw    = t3[2] - t3[0]
            scale = bw / max(T3_MM, 1)
            lg_mm = st.box_on_T3.length_mm if st.box_on_T3.length_mm > 5 else 32.0
            w_px  = max(10, int(lg_mm * scale * T3_BOX_SCALE))
            _draw_box_h_to_x(
                cv, t3, T3_C5_X, w_px, st.box_on_T3,
                T3_BOX_HEIGHT, 'center'
            )

        # ── Boîte sur T4 (pT4 > 0, décroît vers T5) ──────────────────────────
        t4_t5_transfer = (
            st.box_on_T4
            and st.fgBfinT4 == 1
            and 'TRANSFERT-T4/T5' in st.state_tT4_T5
        )
        if st.box_on_T4 and (st.C6 or t4_t5_transfer or 0 < st.pT4 <= T4_MM + 50):
            length_mm = st.box_on_T4.length_mm or st.LgBtT4
            if st.C6:
                bbox = _draw_box_v_to_y(
                    cv, L['T4'], T4_C6_Y, T4_MM, st.box_on_T4, length_mm,
                    T4_BOX_SCALE, T4_BOX_WIDTH_RATIO
                )
            elif t4_t5_transfer:
                if st.pT4 <= 0:
                    bbox = None
                else:
                    bbox = _draw_box_v_to_y(
                        cv, L['T4'], _t4_t5_transfer_bottom_y(st), T4_MM,
                        st.box_on_T4, length_mm, T4_BOX_SCALE, T4_BOX_WIDTH_RATIO
                    )
            else:
                pos_from_top = T4_MM - st.pT4 if 0 < st.pT4 <= T4_MM + 50 else T4_MM - 60
                bbox = _draw_box_v(
                    cv, L['T4'], pos_from_top, T4_MM, st.box_on_T4, length_mm,
                    T4_BOX_SCALE, T4_BOX_WIDTH_RATIO
                )
            if bbox and st.box_on_T4.id_b:
                cv.create_text(
                    L['T4'][2] + 10, (bbox[1] + bbox[3]) // 2,
                    text=f'idB:{st.box_on_T4.id_b}',
                    fill='#d7e6ff', font=('Consolas', 8, 'bold'), anchor='w',
                )

        # ── Boîtes sur T5 ────────────────────────────────────────────────────
        # Coord. machine : x diminue vers la droite (butee=942), augmente vers la gauche.
        t5       = L['T5']
        t5_origin = _t5_visual_origin(st)
        scale_t5 = _t5_physical_scale()

        for box in st.boxes_on_T5:
            w_px, h_px = _t5_box_dims_px(box, t5, scale_t5)
            if _t5_is_initial_entry(box, st):
                x_px = _t5_entry_aligned_x(w_px)
            else:
                animated_x = _t5_render_x_pos(st, box, include_visual_offset=True)
                x_px = t5[2] - int((animated_x - t5_origin) * scale_t5) - w_px
            bbox = _draw_t5_box(cv, t5, x_px, w_px, h_px, box)
            if bbox:
                self._t5_hitboxes.append((bbox, box))

        # Indicateur encodeur T5 : pT5 est la position moteur (0→~3000mm).
        # Il est dans un repère différent des x_pos BdD → échelle propre.
        # ── Étiquettes d'info ─────────────────────────────────────────────────
        ix = L['T4'][2] + 8
        cv.create_text(ix, L['T3'][1] + 2,  text=f'pT3: {st.pT3} mm',
                       fill='#556677', font=('Consolas', 8), anchor='nw')
        cv.create_text(ix, L['T4'][1] + 2,  text=f'pT4: {st.pT4} mm',
                       fill='#556677', font=('Consolas', 8), anchor='nw')
        cv.create_text(ix, L['T4'][1] + 18, text=f'Lg:  {st.LgBtT4:.0f} mm',
                       fill='#556677', font=('Consolas', 8), anchor='nw')
        cv.create_text(ix, L['T4'][1] + 34, text=f'larg:{st.larg_T5} mm',
                       fill='#556677', font=('Consolas', 8), anchor='nw')

        n = len(st.boxes_on_T5)
        cv.create_text(L['T5'][0] + 4, L['T5'][3] + 6,
                       text=f'{n} boîte(s) sur T5    pT5={st.pT5}',
                       fill='#99aabb', font=('Consolas', 8), anchor='nw')

        cv.create_text(CANVAS_W - 4, 4, text=st.timestamp_str,
                       fill='#445566', font=('Consolas', 9), anchor='ne')
