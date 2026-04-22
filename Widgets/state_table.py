"""
StateTable – tableau temps-réel des capteurs et états des tapis.

Deux sections :
  • Capteurs : C0, C1, C2, C3, C4, C5, C6, C9, Poubelle, LzB
  • Tapis     : T0-T5 — state string (logiciel) + code eT (firmware) + description
"""
from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
from typing import Optional

from Models.state import MachineState

# ── Descriptions des codes eT (firmware, doc_alpha PDF) ──────────────────────
_ET_DESC: dict[str, dict[int, str]] = {
    'T0': {
        -1: 'Variables init.',   1: 'Init méc.',    11: 'Init méc.',
         2: 'Init terminée',     4: 'Auto: attend C0', 41: 'Auto: tempo',
        42: 'Auto: tempo repos', 5: 'Arrêt moteur', 51: 'Arrêt moteur',
         6: 'Vidage rapide',    61: 'Vidage rapide',
         7: 'Vidage lent',      71: 'Vidage lent',
    },
    'T1': {
        -1: 'Variables init.',   1: 'Init méc.',    11: 'Init méc.',
         2: 'Init terminée',    41: 'Lance T1 rech. boite',
        42: 'Attend boite C1', 43: 'Arrêt T1',
        44: 'Attend tempo/BP/boite', 45: 'Arrêt T1 (boite C1)',
        46: 'Boite en bout T1', 47: 'Fin mvt court T1',
         5: 'Arrêt moteur',    51: 'Arrêt moteur',
         6: 'Vidage',          61: 'Vidage',
    },
    'T2': {
        -1: 'Variables init.',  1: 'Init méc.',    11: 'Init méc.',
         2: 'Init terminée',   42: 'Attend C2 actif', 43: 'Tempo veille',
        44: 'Attend boite C3', 46: 'Arrêt T2 (après C3)',
        49: 'Boite chargée, prête', -48: 'Err: boite non arrivée C3',
       -49: 'Err: Laser non init', 5: 'Arrêt moteur', 51: 'Arrêt moteur',
         6: 'Vidage', 61: 'Vidage', 71: 'Attend fin mesure',
        78: 'Mesure ok, attend transfert', -79: 'Err: mesure erreur',
         8: 'Transfert T2→EA',  81: 'Déclenche T2',
        82: 'Attend boite C4', 83: 'Arrêt T2 (boite C4)',
        89: 'Transfert terminé', -87: 'Err: temps C4 dépassé',
       -88: 'Err: boite déjà C4', -89: 'Err: pas de boite C3',
    },
    'T3': {
        -1: 'Variables init.',  1: 'Init méc.',    11: 'Init méc.',
         2: 'Init terminée',   42: 'Attend tare', 43: 'Démarre T3 + éjection',
        44: 'Attend C5 actif', 46: 'Arrêt T3',   47: 'Attend fin poids',
       -43: 'Err: boite coincée', 49: 'Boite bout T3, poids ok',
       -44: 'Err: tare impossible', -45: 'Err: poids impossible',
       -46: 'Err: C5 non atteint', -47: 'Err: init MDM4/5',
       -48: 'Err: pas de boite C4', -49: 'Err: boite déjà C5',
         5: 'Arrêt moteur', 51: 'Arrêt moteur',
         6: 'Vidage', 61: 'Vidage', 7: 'Vers C5', 71: 'Vers C5', 72: 'Vers C5',
    },
    'T4': {
        -1: 'Variables init.',   1: 'Demande init', 11: 'Vidage init',
        12: 'Init méc.',        13: 'Init méc.',   14: 'Rech. index',
        15: 'Arrêt tapis init', 16: 'Vers position repos',
       -17: 'Err: index non dégagé', -18: 'Err: index non trouvé',
       -19: 'Err: init en erreur', 2: 'Init terminée',
         4: 'Charge T3→T4',    41: 'Charge boite T3→T4',
        42: 'Mesure longueur', 43: 'Arrêt en cours',
        46: 'Mesure ok, attend transfert', 48: 'Relance mesure',
        49: 'Recul tassement', -44: 'Err: boite sur C5',
       -45: 'Err: boite face T6', -46: 'Err: boite déjà en attente',
       -47: 'Err: pas de boite C5', -48: 'Err: T3 non init',
       -49: 'Err: T4 non init', 5: 'Arrêt moteur', 51: 'Arrêt moteur',
         6: 'Vidage', 61: 'Vidage',
         7: 'Charge sans mesure', 71: 'Charge sans mesure',
        72: 'Charge sans mesure', 73: 'Charge sans mesure',
         8: 'Transfert T4→T5', 81: 'Attend fin transfert',
        82: 'Index vers repos', 83: 'Boite sur T5, index retour',
        85: 'Transfert terminé', -85: "Err: T5 pas à l'arrêt",
       -86: 'Err: rien sur C6', -87: 'Err: FlagTransfert',
       -88: 'Err: T5 non init', -89: 'Err: T4 non init',
         9: 'Mesure longueur tapis', 91: 'Rech. début cordon',
        92: 'Rech. cordon',    93: 'Rech. cordon (2e tour)',
        94: 'Arrêt T4',        96: 'Mesure terminée',
       -91: 'Err: pas de vitesse', -92: 'Err: cordon non vu (1er)',
       -93: 'Err: cordon non vu (2e)',
    },
    'T5': {
        -1: 'Variables init.',  1: 'Init méc.',    11: 'Init méc.',
         2: 'Init terminée',    4: 'Positionnement absolu',
        41: 'Positionnement absolu', -49: 'Err: erreur moteur',
         5: 'Arrêt moteur',   51: 'Arrêt moteur',
         6: 'Vidage',         61: 'Vidage',
         7: 'Positionnement relatif (mesure larg)',
        71: 'Positionnement relatif',
         9: 'Test dépl. boite', 91: 'Attend pos. maxi / capteur',
        92: 'Attend arrêt réel', 93: 'Attend surplus', 94: 'Test dépl.',
        99: 'Err: erreur moteur test',
    },
}

# ── Couleurs capteurs ─────────────────────────────────────────────────────────
_SENS_COLORS: dict[str, str] = {
    'C0': '#ff4444', 'C1': '#ff4444', 'C2': '#ff4444', 'C3': '#ff4444',
    'C4': '#ff4444', 'C5': '#44cc44', 'C6': '#ffaa00', 'C9': '#00aaff',
    'Poubelle': '#ff8800', 'LzB': '#cc6666',
}
_OFF_COLOR = '#2a3540'


def _et_color(et: int) -> str:
    """Couleur du code eT selon son type (normal / erreur / init)."""
    if et in (0, -1, 1, 2, 11):
        return '#556677'      # init / neutre
    if et < 0:
        return '#ff5555'      # erreur
    if et >= 80:
        return '#44cc44'      # terminé / ok
    return '#4FC3F7'          # actif


class StateTable(ctk.CTkFrame):
    """Affiche l'état courant des capteurs et des tapis en temps réel."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault('fg_color', '#161625')
        kwargs.setdefault('corner_radius', 6)
        super().__init__(master, **kwargs)
        self._build()

    # ── Construction ─────────────────────────────────────────────────────────
    def _build(self) -> None:
        # ── En-tête ───────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color='#1e1e30', corner_radius=0)
        hdr.pack(fill='x')
        ctk.CTkLabel(hdr, text='CAPTEURS & TAPIS',
                     font=('Consolas', 10, 'bold'),
                     text_color='#445566').pack(pady=4)

        # ── Zone scrollable ───────────────────────────────────────────────
        scroll_frame = ctk.CTkScrollableFrame(self, fg_color='#161625',
                                               corner_radius=0)
        scroll_frame.pack(fill='both', expand=True, padx=2, pady=2)
        inner = scroll_frame

        # ── Section Capteurs ──────────────────────────────────────────────
        ctk.CTkLabel(inner, text='── Capteurs ──',
                     font=('Consolas', 9, 'bold'),
                     text_color='#445566').pack(anchor='w', padx=8, pady=(6, 2))

        self._sensor_rows: dict[str, ctk.CTkLabel] = {}
        sensors = [
            ('C0',      'Début T1'),
            ('C1',      'Fin T1'),
            ('C2',      'T2'),
            ('C3',      'T2 (chargé)'),
            ('C4',      'EA'),
            ('C5',      'T3'),
            ('C6',      'T4'),
            ('C9',      'Laser T5'),
            ('Poubelle','Poubelle pleine'),
            ('LzB',     'Mesure hauteur T5'),
        ]
        for name, desc in sensors:
            row = ctk.CTkFrame(inner, fg_color='transparent')
            row.pack(fill='x', padx=6, pady=1)
            dot = ctk.CTkLabel(row, text='●', font=('Consolas', 16),
                                text_color=_OFF_COLOR, width=24)
            dot.pack(side='left', padx=2)
            ctk.CTkLabel(row, text=f'{name}', font=('Consolas', 10, 'bold'),
                          text_color='#667788', width=70,
                          anchor='w').pack(side='left')
            ctk.CTkLabel(row, text=desc, font=('Consolas', 9),
                          text_color='#445566', anchor='w').pack(side='left', padx=4)
            self._sensor_rows[name] = dot

        # ── Section Tapis ─────────────────────────────────────────────────
        ctk.CTkFrame(inner, fg_color='#2a2a3e', height=1).pack(
            fill='x', padx=8, pady=6)
        ctk.CTkLabel(inner, text='── Tapis ──',
                     font=('Consolas', 9, 'bold'),
                     text_color='#445566').pack(anchor='w', padx=8, pady=(0, 2))

        self._belt_et_labels: dict[str, ctk.CTkLabel] = {}
        self._belt_st_labels: dict[str, ctk.CTkLabel] = {}
        self._belt_desc_labels: dict[str, ctk.CTkLabel] = {}

        # EA = zone d'identification (tâche logicielle, pas de moteur dédié)
        # T3 = moteur T3 (eT3) + tâche tT3/T4
        belt_names = [
            ('T0', '#557799'), ('T1', '#557799'), ('T2', '#557799'),
            ('EA', '#7799aa'),  # couleur distincte pour EA
            ('T3', '#557799'), ('T4', '#557799'), ('T5', '#557799'),
        ]
        for name, color in belt_names:
            row = ctk.CTkFrame(inner, fg_color='#1a1a2e', corner_radius=4)
            row.pack(fill='x', padx=6, pady=2)
            ctk.CTkLabel(row, text=name, font=('Consolas', 10, 'bold'),
                          text_color=color, width=36).pack(side='left', padx=4)
            et_lbl = ctk.CTkLabel(row, text='eT:—', font=('Consolas', 9, 'bold'),
                                   text_color='#556677', width=52)
            et_lbl.pack(side='left')
            st_lbl = ctk.CTkLabel(row, text='—', font=('Consolas', 8),
                                   text_color='#4477aa', width=100, anchor='w')
            st_lbl.pack(side='left', padx=2)
            desc_lbl = ctk.CTkLabel(row, text='', font=('Consolas', 9),
                                     text_color='#445566', anchor='w',
                                     wraplength=300)
            desc_lbl.pack(side='left', padx=4, fill='x', expand=True)
            self._belt_et_labels[name] = et_lbl
            self._belt_st_labels[name] = st_lbl
            self._belt_desc_labels[name] = desc_lbl

    # ── Mise à jour ───────────────────────────────────────────────────────────
    def update_state(self, st: MachineState) -> None:
        # Capteurs
        sensor_vals = {
            'C0': st.C0, 'C1': st.C1, 'C2': st.C2, 'C3': st.C3,
            'C4': st.C4, 'C5': st.C5, 'C6': st.C6, 'C9': st.C9,
            'Poubelle': st.flag_poubelle_pleine,
            'LzB': 1 if st.lzb > 0 else 0,
        }
        for name, dot in self._sensor_rows.items():
            val = sensor_vals.get(name, 0)
            color = _SENS_COLORS.get(name, '#ff4444') if val else _OFF_COLOR
            dot.configure(text_color=color)

        # Tapis
        # EA : tâche logicielle tEA-T3 (pas de code eT moteur propre)
        # T3 : moteur eT3 + tâche tT3/T4 (chargement T3→T4)
        # T4 : moteur eT4 + tâche tT4*T5
        belts = {
            'T0': (st.eT0, st.state_T0),
            'T1': (st.eT1, st.state_T1),
            'T2': (st.eT2, st.state_T2),
            'EA': (None,   st.state_tEA_T3),
            'T3': (st.eT3, st.state_tT3_T4),
            'T4': (st.eT4, st.state_tT4_T5),
            'T5': (st.eT5, st.state_T5),
        }
        for name, (et, state_str) in belts.items():
            desc = _ET_DESC.get(name, {}).get(et, '') if et is not None else ''
            if et is not None and et < 0 and et != -1 and not desc:
                desc = 'Err: code eT non documenté'
            if et is None:
                self._belt_et_labels[name].configure(text='tâche', text_color='#445566')
            else:
                self._belt_et_labels[name].configure(
                    text=f'eT:{et}', text_color=_et_color(et))
            self._belt_st_labels[name].configure(text=state_str[:14])
            self._belt_desc_labels[name].configure(text=desc)
