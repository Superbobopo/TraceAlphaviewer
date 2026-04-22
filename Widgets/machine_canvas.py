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
    'dir_arr':    '#2a6a2a',
    'box_bdr':    '#111122',
}

# ── Dimensions canvas ─────────────────────────────────────────────────────────
CANVAS_W = 920
CANVAS_H = 480

# ── Rectangles des tapis (x1, y1, x2, y2) ────────────────────────────────────
L = {
    'T0': ( 20,  34,  102,  88),
    'T1': (128,  34,  388,  88),
    'T2': ( 20, 132,  392, 188),
    'EA': ( 20, 252,  142, 344),
    'T3': (163, 266,  354, 334),
    'T4': (374, 242,  540, 400),
    'T5': ( 20, 418,  638, 472),   # s'arrête à la butée (Mesure Hauteur)
}

# Dimensions physiques pour mise à l'échelle
T3_MM       = 220    # longueur T3 (mm)
T4_MM       = 530    # hauteur T4 (mm) — pT4 décroît de T4_MM→0 en descendant
# T5 : coordonnées machine (x diminue vers la droite / butée, augmente vers la gauche / Poubelle)
# Butée physique = 734 mm  (lu dans la trace : MAJ BUTEE-T5 X:734)
# Boîte arrivant de T4 ≈ 1011 mm (lu dans la trace : sur T5: … x=1011)
# T5_X_MAX = extent gauche estimé (zone Poubelle) — ajuster si les boîtes sortent du canvas
T5_X_BUTEE = 734    # coordonnée machine de la butée (droite du T5)
# Chaque nouveau cycle de tassement décale les boîtes existantes de +89 mm net (+361 retour
# − ~272 poussée) + micro-ajustements de +27 mm intercycles. Avec 3 boîtes simultanées la
# plus ancienne peut atteindre ~1600 mm, déclenchant un clamp visuel indésirable avec 1600.
# 2500 couvre confortablement jusqu'à ~15 boîtes simultanées sans effet de bord.
T5_X_MAX   = 2500   # coordonnée machine de l'extrémité Poubelle (gauche du T5)


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


def _draw_belt(cv: tk.Canvas, rect: tuple, label: str,
               state_str: str, eT: int) -> None:
    x1, y1, x2, y2 = rect
    outline = '#ff5555' if eT < 0 else C['belt_bdr']
    width = 3 if eT < 0 else 2
    cv.create_rectangle(x1, y1, x2, y2,
                        fill=_belt_color(state_str, eT),
                        outline=outline, width=width)
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    cv.create_text(cx, cy - 7, text=label,
                   fill=C['belt_lbl'], font=('Consolas', 10, 'bold'))
    cv.create_text(cx, cy + 8, text=state_str[:15],
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
                box: Optional[BoxInfo]) -> None:
    """Boîte sur tapis horizontal."""
    _, y1, _, y2 = belt_rect
    x1b, x2b = belt_rect[0], belt_rect[2]
    if x_px + w_px <= x1b:   # boîte entièrement hors canvas gauche → fantôme évité
        return
    bx1 = max(x1b + 2, min(x_px, x2b - w_px - 2))
    bx2 = min(x2b - 2, bx1 + max(w_px, 6))
    fill = box.color if box else '#4FC3F7'
    cv.create_rectangle(bx1, y1 + 3, bx2, y2 - 3,
                        fill=fill, outline=C['box_bdr'], width=1)
    lbl = box.short_label() if box else ''
    if lbl:
        cv.create_text((bx1 + bx2) // 2, (y1 + y2) // 2,
                       text=lbl, fill='#111122',
                       font=('Consolas', 7, 'bold'),
                       width=max(bx2 - bx1 - 4, 10))


def _draw_box_v(cv: tk.Canvas, belt_rect: tuple,
                pos_from_top_mm: int, total_mm: int,
                box: Optional[BoxInfo]) -> None:
    """Boîte sur tapis vertical (T4 — descend de haut en bas)."""
    x1, y1, x2, y2 = belt_rect
    belt_h = y2 - y1
    scale  = belt_h / max(total_mm, 1)
    h_px   = max(12, int(50 * scale))
    by1    = y1 + max(0, int(pos_from_top_mm * scale))
    by2    = min(y2 - 3, by1 + h_px)
    by1    = max(y1 + 3, by1)
    fill   = box.color if box else '#4FC3F7'
    cv.create_rectangle(x1 + 5, by1, x2 - 5, by2,
                        fill=fill, outline=C['box_bdr'], width=1)
    lbl = box.short_label() if box else ''
    if lbl:
        cv.create_text((x1 + x2) // 2, (by1 + by2) // 2,
                       text=lbl, fill='#111122',
                       font=('Consolas', 7, 'bold'), width=(x2 - x1) - 10)


def _conn(cv: tk.Canvas, *pts: int) -> None:
    """Ligne de connexion entre tapis (avec flèche)."""
    cv.create_line(*pts, fill='#445566', width=2,
                   arrow=tk.LAST, arrowshape=(8, 10, 4))


def _dir_arrow(cv: tk.Canvas, x1: int, y1: int, x2: int, y2: int) -> None:
    """Flèche verte indiquant le sens de rotation du tapis."""
    cv.create_line(x1, y1, x2, y2, fill=C['dir_arr'],
                   arrow=tk.LAST, arrowshape=(6, 8, 3), width=2)


# ── Widget principal ──────────────────────────────────────────────────────────
class MachineCanvas(tk.Canvas):

    def __init__(self, master, **kwargs):
        kwargs.setdefault('bg', C['bg'])
        kwargs.setdefault('highlightthickness', 0)
        super().__init__(master, **kwargs)
        self._state: Optional[MachineState] = None

    def update_state(self, state: MachineState) -> None:
        self._state = state
        self.delete('all')
        self._draw(state)

    def _draw(self, st: MachineState) -> None:
        cv = self

        # ── Connexions entre tapis ────────────────────────────────────────────
        _conn(cv, L['T0'][2], 61,  L['T1'][0], 61)                       # T0 → T1
        _conn(cv, L['T1'][2], 61,  420, 61, 420, 160, L['T2'][2], 160)   # T1 → T2 (U-turn)
        _conn(cv, L['T2'][0], 160, 8,   160, 8,   298, L['EA'][0], 298)  # T2 → EA
        _conn(cv, L['EA'][2], 298, L['T3'][0], 298)                       # EA → T3
        _conn(cv, L['T3'][2], 300, L['T4'][0], 300)                       # T3 → T4
        _conn(cv, 538, L['T4'][3], 538, L['T5'][1])                       # T4 → T5 (sortie côté droit)

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
        cv.create_text((x1+x2)//2, (y1+y2)//2 + 8,
                       text=st.state_tEA_T3[:14],
                       fill=C['st_lbl'], font=('Consolas', 7))

        _draw_belt(cv, L['T3'], 'T3', st.state_tT3_T4, st.eT3)
        _draw_belt(cv, L['T4'], 'T4', st.state_tT4_T5, st.eT4)
        _draw_belt(cv, L['T5'], 'T5', st.state_T5,     st.eT5)

        # ── Capteurs (barres sur les tapis) ───────────────────────────────────

        # T1 : C0 début, C1 fin
        _sensor_vbar(cv, 'C0', 160, L['T1'], st.C0)
        _sensor_vbar(cv, 'C1', 360, L['T1'], st.C1)

        # T2 : C3 et C2 (sortie gauche)
        _sensor_vbar(cv, 'C3',  47, L['T2'], st.C3)
        _sensor_vbar(cv, 'C2',  82, L['T2'], st.C2)

        # EA : C4
        _sensor_vbar(cv, 'C4', 115, L['EA'], st.C4)

        # T3 : C5 (côté droit)
        _sensor_vbar(cv, 'C5', 320, L['T3'], st.C5)

        # T4 : C6 (barre horizontale)
        _sensor_hbar(cv, 'C6', 368, L['T4'], st.C6)
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
        _sensor_vbar(cv, 'Poubelle', 55, L['T5'],
                     st.flag_poubelle_pleine, on_color=poub_color)
        if st.flag_poubelle_pleine:
            cv.create_text(55, L['T5'][1] - 17, text='PLEINE',
                           fill='#ff8800', font=('Consolas', 6, 'bold'), anchor='s')

        c9_x = L['T4'][0] - 12
        _sensor_vbar(cv, 'C9', c9_x, L['T5'], st.C9)

        # Mesure Hauteur (LzB) — droite de T5, juste avant la butée
        mh_x = L['T5'][2] - 18    # ~620, près de la butée droite
        mh_y = (L['T5'][1] + L['T5'][3]) // 2
        mh_c = '#cc3333' if st.lzb > 0 else '#335566'
        cv.create_oval(mh_x - 5, mh_y - 5, mh_x + 5, mh_y + 5,
                       fill=mh_c, outline='#667788', width=1)
        cv.create_text(mh_x, L['T5'][1] - 10, text='Mesure H.',
                       fill='#cc6666', font=('Consolas', 7), anchor='s')

        # Butée T5 (paroi droite)
        cv.create_line(L['T5'][2] - 3, L['T5'][1], L['T5'][2] - 3, L['T5'][3],
                       fill='#889900', width=3)
        cv.create_text(L['T5'][2] - 3, L['T5'][1] - 5, text='butée',
                       fill='#889900', font=('Consolas', 6), anchor='s')

        # ── Flèches sens de rotation (vertes, bas des tapis) ─────────────────
        for rect, dx, dy in [
            (L['T0'],  22,  0),   # T0 →
            (L['T1'],  22,  0),   # T1 →
            (L['T2'], -22,  0),   # T2 ←
            (L['T3'],  18,  0),   # T3 →
        ]:
            cx = (rect[0] + rect[2]) // 2
            cy = rect[3] - 8
            _dir_arrow(cv, cx - dx, cy + dy, cx + dx, cy + dy)

        # T4 ↓ (flèche verticale sur le côté droit du tapis)
        cx4 = L['T4'][2] - 10
        cy4 = (L['T4'][1] + L['T4'][3]) // 2
        _dir_arrow(cv, cx4, cy4 - 18, cx4, cy4 + 18)

        # T5 → (vers butée droite)
        cx5 = (L['T5'][0] + L['T5'][2]) // 2
        cy5 = L['T5'][3] - 8
        _dir_arrow(cv, cx5 - 28, cy5, cx5 + 28, cy5)

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
        if st.pT3 < 0:
            t3    = L['T3']
            bw    = t3[2] - t3[0]
            scale = bw / max(T3_MM, 1)
            lg_mm = st.LgBtT4 if st.LgBtT4 > 5 else 32.0
            w_px  = max(10, int(lg_mm * scale))
            x_px  = t3[0] + int(abs(st.pT3) * scale)
            _draw_box_h(cv, t3, x_px, w_px, st.box_on_T4 or st.box_in_EA)

        # ── Boîte sur T4 (pT4 > 0, décroît vers T5) ──────────────────────────
        if 0 < st.pT4 <= T4_MM + 50:
            _draw_box_v(cv, L['T4'], T4_MM - st.pT4, T4_MM, st.box_on_T4)

        # ── Boîtes sur T5 ────────────────────────────────────────────────────
        # Coord. machine : x diminue → droite (butée=734), x augmente → gauche (Poubelle)
        t5       = L['T5']
        t5_w     = t5[2] - t5[0]
        scale_t5 = t5_w / max(T5_X_MAX - T5_X_BUTEE, 1)

        for box in st.boxes_on_T5:
            # width_mm = largeur mesurée par MAJ (nvlle dim:WxH → H).
            # Fallback 40mm si pas encore mesuré.
            dim_mm = box.width_mm if box.width_mm > 0 else 40
            w_px   = max(8, int(dim_mm * scale_t5))
            x_px = t5[2] - int((box.x_pos - T5_X_BUTEE) * scale_t5) - w_px
            _draw_box_h(cv, t5, x_px, w_px, box)

        # Indicateur encodeur T5 : pT5 est la position moteur (0→~3000mm).
        # Il est dans un repère différent des x_pos BdD → échelle propre.
        if st.pT5 != 0:
            T5_MOTOR_MAX = 3000
            ind_x = t5[2] - int(abs(st.pT5) / T5_MOTOR_MAX * t5_w)
            ind_x = max(t5[0], min(ind_x, t5[2]))
            cv.create_line(ind_x, t5[1], ind_x, t5[3],
                           fill='#ffff44', width=2, dash=(4, 3))

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
