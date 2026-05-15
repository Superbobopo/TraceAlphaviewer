"""
TraceView – vue principale de visualisation d'une trace .old.

Layout (fidèle au PNG Layout_app) :
  ┌──────────────────────────────────────────────────────────────┐
  │  Barre titre : nom fichier | nb frames | bouton Fermer       │
  ├──────────────────────────────────┬───────────────────────────┤
  │                                  │  État capteurs & tapis    │
  │   MachineCanvas (graphique)      │  (StateTable)             │
  │                                  │                           │
  ├──────────────────────────────────┴───────────────────────────┤
  │  [|◄][◄][▶/⏸][►][►|]  ×spd ────slider──── HH:MM:SS          │
  │  Trace complète (cliquable, ligne courante surlignée)        │
  └──────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import bisect
import math
import os
import threading
from typing import Callable, List, Optional

import customtkinter as ctk
import tkinter as tk

from Models.diagnostic import DiagnosticIncident, build_diagnostics
from Models.state import MachineEvent, MachineState
from Views.BaseView import BaseView
from Widgets.diagnostic_panel import DiagnosticPanel
from Widgets.event_panel import EventPanel
from Widgets.machine_canvas import MachineCanvas, CANVAS_W, CANVAS_H
from Widgets.state_table import StateTable
from Widgets.trace_panel import TracePanel

PLAY_DELAY_DEFAULT = 300   # ms entre frames en lecture auto
SPEED_MIN = 0.1
SPEED_MAX = 10.0
SPEED_SLIDER_MIN = math.log2(SPEED_MIN)
SPEED_SLIDER_MAX = math.log2(SPEED_MAX)
NAV_BAR_H = 42
RESIZE_HANDLE_H = 7


class TraceView(BaseView):

    def __init__(
        self,
        master,
        filepath: str,
        frames: List[MachineState],
        return_view: BaseView | None = None,
        on_close: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(master, fg_color='#12121f', **kwargs)
        self._filepath    = filepath
        self._frames      = frames
        self._return_view = return_view
        self._on_close    = on_close
        self._events      = self._collect_events(frames)
        self._diagnostics = build_diagnostics(frames, self._events)
        self._error_events = [e for e in self._events if e.severity == 'error']
        self._idx         = 0
        self._playing     = False
        self._play_job: Optional[str] = None
        self._play_delay  = PLAY_DELAY_DEFAULT
        self._details_visible = True
        self._current_error_line: Optional[int] = None
        self._details_height = 280
        self._speed_value = 1.0
        self._resize_job: Optional[str] = None
        self._drag_start_y = 0
        self._drag_start_details_height = self._details_height

        # Table de correspondance fichier-ligne → index frame (tri croissant)
        # Chaque entrée = (line_num_fichier, frame_idx)
        self._line_map: List[tuple] = sorted(
            [(f.line_num, i) for i, f in enumerate(frames)],
            key=lambda x: x[0]
        )

    def _collect_events(self, frames: List[MachineState]) -> List[MachineEvent]:
        events: list[MachineEvent] = []
        seen: set[tuple] = set()
        for frame in frames:
            for event in frame.events:
                key = (event.line_num, event.kind, event.title)
                if key in seen:
                    continue
                events.append(event)
                seen.add(key)
        return sorted(events, key=lambda e: (e.line_num, e.kind, e.title))

    # ── Affichage / fermeture ─────────────────────────────────────────────────
    def show(self) -> None:
        super().show()
        self._build_title_bar()
        self._build_split_layout()
        if self._frames:
            self._go_to(0)
        # Charge le fichier trace complet en arrière-plan
        self._trace_panel.load_file(self._filepath)

    def hide(self) -> None:
        super().hide()
        self._stop_playback()
        for w in self.winfo_children():
            w.destroy()

    # ── Barre de titre ────────────────────────────────────────────────────────
    def _build_title_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color='#1e1e30', height=38, corner_radius=0)
        bar.pack(fill='x', side='top')
        bar.pack_propagate(False)

        fname = os.path.basename(self._filepath)
        ctk.CTkLabel(bar, text=f'  {fname}',
                     font=('Consolas', 12, 'bold'),
                     text_color='#88aacc').pack(side='left', padx=12)

        ctk.CTkLabel(bar, text=f'{len(self._frames)} frames | {len(self._diagnostics)} incidents | {len(self._events)} evenements',
                     font=('Consolas', 11),
                     text_color='#556677').pack(side='left', padx=8)

        # Heure + numéro de ligne courant
        self._lbl_ts = ctk.CTkLabel(bar, text='00:00:00',
                                     font=('Consolas', 13, 'bold'),
                                     text_color='#4FC3F7')
        self._lbl_ts.pack(side='left', padx=16)

        self._lbl_frame = ctk.CTkLabel(bar, text='0 / 0',
                                        font=('Consolas', 10),
                                        text_color='#445566')
        self._lbl_frame.pack(side='left', padx=4)

        self._lbl_line = ctk.CTkLabel(bar, text='L. —',
                                       font=('Consolas', 10),
                                       text_color='#ffaa44')
        self._lbl_line.pack(side='left', padx=8)

        ctk.CTkButton(bar, text='✕ Fermer', width=80, height=28,
                      fg_color='#2a2a3e', hover_color='#aa2233',
                      text_color='#cc8888', font=('Consolas', 11),
                      command=self._close).pack(side='right', padx=8, pady=4)

    # ── Zone centrale : graphique (gauche) + état capteurs/tapis (droite) ─────
    def _build_split_layout(self) -> None:
        self._main_pane = ctk.CTkFrame(self, fg_color='#12121f', corner_radius=0)
        self._main_pane.pack(fill='both', expand=True, side='top')

        self._bottom_pane = ctk.CTkFrame(
            self._main_pane,
            fg_color='#0f0f1c',
            corner_radius=0,
            height=self._bottom_total_height(),
        )
        self._bottom_pane.pack(fill='x', side='bottom')
        self._bottom_pane.pack_propagate(False)

        self._middle_pane = ctk.CTkFrame(self._main_pane, fg_color='#12121f', corner_radius=0)
        self._middle_pane.pack(fill='both', expand=True, side='top')

        self._build_middle(self._middle_pane)
        self._build_bottom(self._bottom_pane)
        self.after(80, lambda: self._set_bottom_height(self._details_height))

    def _bottom_total_height(self) -> int:
        details_h = self._details_height if self._details_visible else 0
        handle_h = RESIZE_HANDLE_H if self._details_visible else 0
        return NAV_BAR_H + handle_h + details_h

    def _current_bottom_height(self) -> int:
        if not hasattr(self, '_details_frame') or not self._details_visible:
            return self._details_height
        height = self._details_frame.winfo_height()
        return max(160, height if height > 1 else self._details_height)

    def _set_bottom_height(self, bottom_height: int) -> None:
        if not hasattr(self, '_bottom_pane'):
            return

        self._details_height = max(160, int(bottom_height))
        if self._details_visible:
            self._details_frame.configure(height=self._details_height)
            self._bottom_pane.configure(height=self._bottom_total_height())

    def _start_details_resize(self, event) -> None:
        self._drag_start_y = event.y_root
        self._drag_start_details_height = self._current_bottom_height()

    def _drag_details_resize(self, event) -> None:
        delta = event.y_root - self._drag_start_y
        self._queue_bottom_height(self._drag_start_details_height - delta)

    def _queue_bottom_height(self, bottom_height: int) -> None:
        self._pending_details_height = max(160, int(bottom_height))
        if self._resize_job is None:
            self._resize_job = self.after_idle(self._apply_pending_bottom_height)

    def _apply_pending_bottom_height(self) -> None:
        self._resize_job = None
        self._set_bottom_height(getattr(self, '_pending_details_height', self._details_height))

    def _build_middle(self, parent) -> None:
        mid = ctk.CTkFrame(parent, fg_color='#12121f', corner_radius=0)
        mid.pack(fill='both', expand=True)

        # Graphique machine (gauche, largeur fixe = taille native du canvas)
        canvas_frame = ctk.CTkFrame(mid, fg_color='#1a1a2e',
                                    width=CANVAS_W + 8, corner_radius=6)
        canvas_frame.pack(side='left', fill='y', padx=(6, 3), pady=6)
        canvas_frame.pack_propagate(False)

        self._canvas = MachineCanvas(canvas_frame, width=CANVAS_W, height=CANVAS_H)
        self._canvas.pack(padx=2, pady=2)

        analysis_frame = ctk.CTkFrame(mid, fg_color='#12121f', corner_radius=0)
        analysis_frame.pack(side='right', fill='both', expand=True, padx=(3, 6), pady=6)
        self._build_analysis_tabs(analysis_frame)

    # ── Zone bas : navigation + trace complète ────────────────────────────────
    def _build_bottom(self, parent) -> None:
        bottom = ctk.CTkFrame(parent, fg_color='#0f0f1c', corner_radius=0)
        bottom.pack(fill='both', expand=True)

        # -- Barre navigation --
        nav_bar = ctk.CTkFrame(bottom, fg_color='#1a1a2e',
                                height=42, corner_radius=0)
        nav_bar.pack(fill='x', side='top')
        nav_bar.pack_propagate(False)

        btn_cfg = dict(width=36, height=30, fg_color='#252538',
                       hover_color='#353555', font=('Consolas', 13),
                       text_color='#aabbcc')

        ctk.CTkButton(nav_bar, text='|◄', **btn_cfg,
                      command=self._go_start).pack(side='left', padx=(8, 2), pady=4)
        ctk.CTkButton(nav_bar, text='◄',  **btn_cfg,
                      command=self._step_back).pack(side='left', padx=2)
        self._btn_play = ctk.CTkButton(nav_bar, text='▶', **btn_cfg,
                                        command=self._toggle_play)
        self._btn_play.pack(side='left', padx=2)
        ctk.CTkButton(nav_bar, text='►',  **btn_cfg,
                      command=self._step_fwd).pack(side='left', padx=2)
        ctk.CTkButton(nav_bar, text='►|', **btn_cfg,
                      command=self._go_end).pack(side='left', padx=2)

        ctk.CTkButton(nav_bar, text='Err◄', width=48, height=30,
                      fg_color='#3a2028', hover_color='#5a2834',
                      font=('Consolas', 11, 'bold'), text_color='#ff9999',
                      command=self._prev_error).pack(side='left', padx=(10, 2), pady=4)
        ctk.CTkButton(nav_bar, text='Err►', width=48, height=30,
                      fg_color='#3a2028', hover_color='#5a2834',
                      font=('Consolas', 11, 'bold'), text_color='#ff9999',
                      command=self._next_error).pack(side='left', padx=2, pady=4)
        self._lbl_error_pos = ctk.CTkLabel(nav_bar, text=self._error_pos_text(),
                                           font=('Consolas', 10),
                                           text_color='#cc7777', width=62)
        self._lbl_error_pos.pack(side='left', padx=(4, 8))

        ctk.CTkLabel(nav_bar, text='×', font=('Consolas', 10),
                     text_color='#445566').pack(side='left', padx=(10, 0))
        speed_btn_cfg = dict(width=32, height=26, fg_color='#252538',
                             hover_color='#353555', font=('Consolas', 11, 'bold'),
                             text_color='#aabbcc')
        ctk.CTkButton(nav_bar, text='◄◄', **speed_btn_cfg,
                      command=self._speed_down).pack(side='left', padx=(4, 2), pady=6)
        self._speed_var = tk.DoubleVar(value=0.0)
        ctk.CTkSlider(nav_bar, from_=SPEED_SLIDER_MIN, to=SPEED_SLIDER_MAX,
                      number_of_steps=200,
                      variable=self._speed_var, width=88, height=14,
                      command=self._on_speed_change).pack(
            side='left', padx=2, pady=14)
        ctk.CTkButton(nav_bar, text='►►', **speed_btn_cfg,
                      command=self._speed_up).pack(side='left', padx=(2, 4), pady=6)
        self._lbl_speed = ctk.CTkLabel(nav_bar, text='x1.00',
                                       font=('Consolas', 10),
                                       text_color='#778899', width=42)
        self._lbl_speed.pack(side='left', padx=(0, 6))

        n = max(1, len(self._frames) - 1)
        self._slider_var = tk.IntVar(value=0)
        self._slider = ctk.CTkSlider(nav_bar, from_=0, to=n,
                                      number_of_steps=n,
                                      variable=self._slider_var,
                                      command=self._on_slider)
        self._slider.pack(side='left', fill='x', expand=True, padx=8, pady=14)

        self._lbl_time = ctk.CTkLabel(nav_bar, text='--:--:--',
                                       font=('Consolas', 13, 'bold'),
                                       text_color='#4FC3F7', width=80)
        self._lbl_time.pack(side='right', padx=10)

        self._btn_details = ctk.CTkButton(nav_bar, text='Masquer details',
                                          width=116, height=28,
                                          fg_color='#252538',
                                          hover_color='#353555',
                                          font=('Consolas', 10),
                                          text_color='#aabbcc',
                                          command=self._toggle_details)
        self._btn_details.pack(side='right', padx=(0, 6), pady=5)

        self._resize_handle = tk.Frame(bottom, bg='#263142', height=RESIZE_HANDLE_H, cursor='sb_v_double_arrow')
        self._resize_handle.pack(fill='x', side='top')
        self._resize_handle.bind('<ButtonPress-1>', self._start_details_resize)
        self._resize_handle.bind('<B1-Motion>', self._drag_details_resize)

        self._details_frame = ctk.CTkFrame(bottom, fg_color='#12121f', corner_radius=0)
        self._details_frame.pack(fill='both', expand=True, side='top')
        self._details_frame.pack_propagate(False)
        self._build_trace_area(self._details_frame)

        # Raccourcis clavier
        self.master.bind('<Left>',  lambda e: self._step_back())
        self.master.bind('<Right>', lambda e: self._step_fwd())
        self.master.bind('<space>', lambda e: self._toggle_play())
        self.master.bind('<Home>',  lambda e: self._go_start())
        self.master.bind('<End>',   lambda e: self._go_end())
        self.master.bind('e',       lambda e: self._next_error())
        self.master.bind('E',       lambda e: self._prev_error())

    def _build_analysis_tabs(self, parent) -> None:
        if hasattr(ctk, 'CTkTabview'):
            tabs = ctk.CTkTabview(parent, fg_color='#12121f',
                                  segmented_button_fg_color='#1e1e30',
                                  segmented_button_selected_color='#1e3a5f',
                                  segmented_button_selected_hover_color='#2a4a7f',
                                  segmented_button_unselected_color='#252538',
                                  segmented_button_unselected_hover_color='#353555',
                                  text_color='#aabbcc',
                                  height=250)
            tabs.pack(fill='both', expand=True)
            state_tab = tabs.add('Capteurs & Tapis')
            diag_tab = tabs.add('Diagnostic')
            error_tab = tabs.add('Erreur')
            events_tab = tabs.add('Evenements')
            self._state_table = StateTable(state_tab)
            self._state_table.pack(fill='both', expand=True, padx=0, pady=0)
            self._diagnostic_panel = DiagnosticPanel(
                diag_tab, self._diagnostics,
                on_incident_click=self._on_incident_click,
            )
            self._diagnostic_panel.pack(fill='both', expand=True, padx=0, pady=0)
            self._error_panel = EventPanel(
                error_tab, self._error_events,
                on_event_click=self._on_event_click,
                title='ERREURS',
                empty_text='Aucune erreur detectee',
            )
            self._error_panel.pack(fill='both', expand=True, padx=0, pady=0)
            self._event_panel = EventPanel(
                events_tab, self._events,
                on_event_click=self._on_event_click,
                show_belt_filters=True,
            )
            self._event_panel.pack(fill='both', expand=True, padx=0, pady=0)
            tabs.set('Diagnostic')
            self._analysis_tabs = tabs
            return

        self._build_analysis_fallback_tabs(parent)

    def _build_analysis_fallback_tabs(self, parent) -> None:
        header = ctk.CTkFrame(parent, fg_color='#1e1e30', height=32, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)
        content = ctk.CTkFrame(parent, fg_color='#12121f', corner_radius=0)
        content.pack(fill='both', expand=True)

        self._analysis_fallback_tab_frames = {}
        for name in ('Capteurs & Tapis', 'Diagnostic', 'Erreur', 'Evenements'):
            frame = ctk.CTkFrame(content, fg_color='#12121f', corner_radius=0)
            self._analysis_fallback_tab_frames[name] = frame
            ctk.CTkButton(
                header, text=name, width=110, height=26,
                fg_color='#252538', hover_color='#353555',
                text_color='#aabbcc', font=('Consolas', 10),
                command=lambda n=name: self._show_analysis_fallback_tab(n),
            ).pack(side='left', padx=4, pady=3)

        self._state_table = StateTable(self._analysis_fallback_tab_frames['Capteurs & Tapis'])
        self._state_table.pack(fill='both', expand=True)
        self._diagnostic_panel = DiagnosticPanel(
            self._analysis_fallback_tab_frames['Diagnostic'], self._diagnostics,
            on_incident_click=self._on_incident_click,
        )
        self._diagnostic_panel.pack(fill='both', expand=True)
        self._error_panel = EventPanel(
            self._analysis_fallback_tab_frames['Erreur'], self._error_events,
            on_event_click=self._on_event_click,
            title='ERREURS',
            empty_text='Aucune erreur detectee',
        )
        self._error_panel.pack(fill='both', expand=True)
        self._event_panel = EventPanel(
            self._analysis_fallback_tab_frames['Evenements'], self._events,
            on_event_click=self._on_event_click,
            show_belt_filters=True,
        )
        self._event_panel.pack(fill='both', expand=True)
        self._show_analysis_fallback_tab('Diagnostic')

    def _show_analysis_fallback_tab(self, name: str) -> None:
        for tab_name, frame in self._analysis_fallback_tab_frames.items():
            if tab_name == name:
                frame.pack(fill='both', expand=True)
            else:
                frame.pack_forget()

    def _build_trace_area(self, parent) -> None:
        self._trace_panel = TracePanel(
            parent,
            on_line_click=self._on_trace_click,
            height=240,
        )
        self._trace_panel.pack(fill='both', expand=True)

    def _toggle_details(self) -> None:
        if self._details_visible:
            self._details_height = max(160, self._current_bottom_height())
            self._details_frame.pack_forget()
            self._resize_handle.pack_forget()
            self._btn_details.configure(text='Afficher details')
            self._details_visible = False
            self._bottom_pane.configure(height=self._bottom_total_height())
        else:
            self._resize_handle.pack(fill='x', side='top')
            self._details_frame.pack(fill='both', expand=True, side='top')
            self._btn_details.configure(text='Masquer details')
            self._details_visible = True
            self.after(20, lambda: self._set_bottom_height(self._details_height))

    def _error_pos_text(self) -> str:
        if not self._error_events:
            return 'Err 0/0'
        if self._current_error_line is None:
            return f'Err -/{len(self._error_events)}'
        for idx, event in enumerate(self._error_events, 1):
            if event.line_num == self._current_error_line:
                return f'Err {idx}/{len(self._error_events)}'
        return f'Err -/{len(self._error_events)}'

    def _set_error_reference(self, line_num: Optional[int]) -> None:
        self._current_error_line = line_num
        if hasattr(self, '_lbl_error_pos'):
            self._lbl_error_pos.configure(text=self._error_pos_text())

    def _reset_error_reference(self) -> None:
        self._set_error_reference(None)

    # ── Navigation ────────────────────────────────────────────────────────────
    def _go_to(self, idx: int) -> None:
        if not self._frames:
            return
        idx = max(0, min(idx, len(self._frames) - 1))
        self._idx = idx
        st = self._frames[idx]

        # Canvas
        self._canvas.update_state(st)

        # Tableau capteurs + tapis
        self._state_table.update_state(st)

        # Titre
        self._lbl_ts.configure(text=st.timestamp_str)
        self._lbl_frame.configure(text=f'{idx + 1} / {len(self._frames)}')
        self._lbl_line.configure(text=f'L. {st.line_num:,}')
        t = int(st.timestamp)
        h, r = divmod(t, 3600); m, s = divmod(r, 60)
        self._lbl_time.configure(text=f'{h:02d}:{m:02d}:{s:02d}')

        # Slider
        self._slider_var.set(idx)

        # Surlignage de la trace
        start_line = st.line_num
        # Fin = dernière ligne raw du frame, ou start si vide
        if st.raw_lines:
            end_line = st.raw_lines[-1][0]
        else:
            end_line = start_line
        self._trace_panel.highlight_lines(start_line, end_line)
        self._event_panel.highlight_for_line(start_line)
        if hasattr(self, '_error_panel'):
            self._error_panel.highlight_for_line(start_line)
        self._diagnostic_panel.highlight_for_line(start_line)

    def _frame_for_file_line(self, file_line: int) -> int:
        """Retourne l'index du frame qui contient la ligne fichier donnée."""
        keys = [x[0] for x in self._line_map]
        pos = bisect.bisect_right(keys, file_line) - 1
        if pos < 0:
            return 0
        return self._line_map[pos][1]

    def _on_trace_click(self, file_line: int) -> None:
        """Callback clic sur la trace → navigation vers le frame correspondant."""
        idx = self._frame_for_file_line(file_line)
        self._stop_playback()
        self._reset_error_reference()
        self._go_to(idx)

    def _on_event_click(self, event: MachineEvent) -> None:
        """Callback clic sur un événement → navigation vers le frame correspondant."""
        idx = self._frame_for_file_line(event.line_num)
        self._stop_playback()
        self._set_error_reference(event.line_num if event.severity == 'error' else None)
        self._go_to(idx)

    def _on_incident_click(self, incident: DiagnosticIncident) -> None:
        """Callback clic sur un incident → navigation vers la première ligne utile."""
        idx = self._frame_for_file_line(incident.first_line)
        self._stop_playback()
        self._reset_error_reference()
        self._go_to(idx)

    def _go_to_event(self, event: MachineEvent) -> None:
        self._stop_playback()
        self._set_error_reference(event.line_num if event.severity == 'error' else None)
        self._go_to(self._frame_for_file_line(event.line_num))

    def _next_error(self) -> None:
        if not self._error_events:
            return
        current_line = (
            self._current_error_line
            if self._current_error_line is not None
            else (self._frames[self._idx].line_num if self._frames else 0)
        )
        for event in self._error_events:
            if event.line_num > current_line:
                self._go_to_event(event)
                return
        self._go_to_event(self._error_events[0])

    def _prev_error(self) -> None:
        if not self._error_events:
            return
        current_line = (
            self._current_error_line
            if self._current_error_line is not None
            else (self._frames[self._idx].line_num if self._frames else 0)
        )
        for event in reversed(self._error_events):
            if event.line_num < current_line:
                self._go_to_event(event)
                return
        self._go_to_event(self._error_events[-1])

    def _go_start(self) -> None:
        self._stop_playback(); self._reset_error_reference(); self._go_to(0)

    def _go_end(self) -> None:
        self._stop_playback(); self._reset_error_reference(); self._go_to(len(self._frames) - 1)

    def _step_fwd(self) -> None:
        self._reset_error_reference()
        self._go_to(self._idx + 1)

    def _step_back(self) -> None:
        self._reset_error_reference()
        self._go_to(self._idx - 1)

    def _on_slider(self, val) -> None:
        self._stop_playback(); self._reset_error_reference(); self._go_to(int(float(val)))

    def _on_speed_change(self, val) -> None:
        speed = max(SPEED_MIN, min(SPEED_MAX, 2 ** float(val)))
        self._speed_value = speed
        self._play_delay = max(10, int(PLAY_DELAY_DEFAULT / speed))
        if hasattr(self, '_lbl_speed'):
            self._lbl_speed.configure(text=f'x{speed:.2f}')

    def _set_speed(self, speed: float) -> None:
        speed = max(SPEED_MIN, min(SPEED_MAX, speed))
        self._speed_var.set(math.log2(speed))
        self._on_speed_change(math.log2(speed))

    def _speed_down(self) -> None:
        self._set_speed(self._speed_value / 2)

    def _speed_up(self) -> None:
        self._set_speed(self._speed_value * 2)

    # ── Lecture automatique ───────────────────────────────────────────────────
    def _toggle_play(self) -> None:
        if self._playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self) -> None:
        self._playing = True
        self._btn_play.configure(text='⏸')
        self._schedule_next()

    def _stop_playback(self) -> None:
        self._playing = False
        self._btn_play.configure(text='▶')
        if self._play_job:
            self.after_cancel(self._play_job)
            self._play_job = None

    def _schedule_next(self) -> None:
        if not self._playing:
            return
        if self._idx >= len(self._frames) - 1:
            self._stop_playback(); return
        self._reset_error_reference()
        self._go_to(self._idx + 1)
        self._play_job = self.after(self._play_delay, self._schedule_next)

    # ── Fermeture ─────────────────────────────────────────────────────────────
    def _close(self) -> None:
        self._stop_playback()
        if self._on_close is not None:
            self._on_close()
            return
        if self._return_view is not None:
            self.master.switch_view(self._return_view)
            return
        from Views.accueilView import AccueilView
        self.master.switch_view(AccueilView(self.master))
