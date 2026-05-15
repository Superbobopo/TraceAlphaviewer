from __future__ import annotations

import bisect
import math
from typing import Callable, Optional

import customtkinter as ctk
import tkinter as tk

from Models.folder_report import TraceReportEntry
from Models.state import MachineState
from Views.BaseView import BaseView
from Widgets.machine_canvas import CANVAS_H, CANVAS_W, MachineCanvas


PLAY_DELAY_DEFAULT = 300
SPEED_MIN = 0.1
SPEED_MAX = 10.0
SPEED_SLIDER_MIN = math.log2(SPEED_MIN)
SPEED_SLIDER_MAX = math.log2(SPEED_MAX)


class FolderPlaybackView(BaseView):
    def __init__(
        self,
        master,
        entry: TraceReportEntry,
        on_frame: Callable[[TraceReportEntry, MachineState], None] | None = None,
        on_close: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(master, fg_color='#12121f', **kwargs)
        self._entry = entry
        self._frames = entry.frames
        self._on_frame = on_frame
        self._on_close = on_close
        self._idx = 0
        self._playing = False
        self._play_job: Optional[str] = None
        self._play_delay = PLAY_DELAY_DEFAULT
        self._speed_value = 1.0
        self._error_events = entry.error_events
        self._current_error_line: Optional[int] = None
        self._line_map: list[tuple[int, int]] = sorted(
            [(frame.line_num, index) for index, frame in enumerate(self._frames)],
            key=lambda item: item[0],
        )

    def show(self) -> None:
        super().show()
        self._build()
        if self._frames:
            self._go_to(0)

    def hide(self) -> None:
        self._stop_playback()
        super().hide()
        for widget in self.winfo_children():
            widget.destroy()

    def _build(self) -> None:
        self._build_title_bar()

        body = ctk.CTkFrame(self, fg_color='#12121f', corner_radius=0)
        body.pack(fill='both', expand=True)

        canvas_frame = ctk.CTkFrame(
            body,
            fg_color='#1a1a2e',
            width=CANVAS_W + 8,
            height=CANVAS_H + 8,
            corner_radius=6,
        )
        canvas_frame.pack(fill='both', expand=True, padx=6, pady=(6, 3))
        canvas_frame.pack_propagate(False)

        self._canvas = MachineCanvas(canvas_frame, width=CANVAS_W, height=CANVAS_H)
        self._canvas.pack(padx=2, pady=2)

        self._build_player(body)

    def _build_title_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color='#1e1e30', height=38, corner_radius=0)
        bar.pack(fill='x', side='top')
        bar.pack_propagate(False)

        ctk.CTkLabel(
            bar,
            text=f'  Viewer : {self._entry.name}',
            font=('Consolas', 12, 'bold'),
            text_color='#88aacc',
        ).pack(side='left', padx=12)

        self._lbl_ts = ctk.CTkLabel(
            bar,
            text='00:00:00',
            font=('Consolas', 13, 'bold'),
            text_color='#4FC3F7',
        )
        self._lbl_ts.pack(side='left', padx=16)

        self._lbl_frame = ctk.CTkLabel(
            bar,
            text='0 / 0',
            font=('Consolas', 10),
            text_color='#778899',
        )
        self._lbl_frame.pack(side='left', padx=4)

        self._lbl_line = ctk.CTkLabel(
            bar,
            text='L. -',
            font=('Consolas', 10),
            text_color='#ffaa44',
        )
        self._lbl_line.pack(side='left', padx=8)

        ctk.CTkButton(
            bar,
            text='Fermer',
            width=80,
            height=28,
            fg_color='#2a2a3e',
            hover_color='#aa2233',
            text_color='#cc8888',
            font=('Consolas', 11),
            command=self._close,
        ).pack(side='right', padx=8, pady=4)

    def _build_player(self, parent) -> None:
        nav_bar = ctk.CTkFrame(parent, fg_color='#1a1a2e', height=42, corner_radius=0)
        nav_bar.pack(fill='x', side='bottom', padx=6, pady=(3, 6))
        nav_bar.pack_propagate(False)

        btn_cfg = dict(
            width=36,
            height=30,
            fg_color='#252538',
            hover_color='#353555',
            font=('Consolas', 13),
            text_color='#aabbcc',
        )

        ctk.CTkButton(nav_bar, text='|◄', **btn_cfg, command=self._go_start).pack(side='left', padx=(8, 2), pady=4)
        ctk.CTkButton(nav_bar, text='◄', **btn_cfg, command=self._step_back).pack(side='left', padx=2)
        self._btn_play = ctk.CTkButton(nav_bar, text='▶', **btn_cfg, command=self._toggle_play)
        self._btn_play.pack(side='left', padx=2)
        ctk.CTkButton(nav_bar, text='►', **btn_cfg, command=self._step_fwd).pack(side='left', padx=2)
        ctk.CTkButton(nav_bar, text='►|', **btn_cfg, command=self._go_end).pack(side='left', padx=2)

        ctk.CTkButton(
            nav_bar,
            text='Err◄',
            width=48,
            height=30,
            fg_color='#3a2028',
            hover_color='#5a2834',
            font=('Consolas', 11, 'bold'),
            text_color='#ff9999',
            command=self._prev_error,
        ).pack(side='left', padx=(10, 2), pady=4)
        ctk.CTkButton(
            nav_bar,
            text='Err►',
            width=48,
            height=30,
            fg_color='#3a2028',
            hover_color='#5a2834',
            font=('Consolas', 11, 'bold'),
            text_color='#ff9999',
            command=self._next_error,
        ).pack(side='left', padx=2, pady=4)
        self._lbl_error_pos = ctk.CTkLabel(
            nav_bar,
            text=self._error_pos_text(),
            font=('Consolas', 10),
            text_color='#cc7777',
            width=62,
        )
        self._lbl_error_pos.pack(side='left', padx=(4, 8))

        ctk.CTkLabel(nav_bar, text='×', font=('Consolas', 10), text_color='#445566').pack(side='left', padx=(10, 0))

        speed_btn_cfg = dict(
            width=32,
            height=26,
            fg_color='#252538',
            hover_color='#353555',
            font=('Consolas', 11, 'bold'),
            text_color='#aabbcc',
        )
        ctk.CTkButton(nav_bar, text='◄◄', **speed_btn_cfg, command=self._speed_down).pack(side='left', padx=(4, 2), pady=6)
        self._speed_var = tk.DoubleVar(value=0.0)
        ctk.CTkSlider(
            nav_bar,
            from_=SPEED_SLIDER_MIN,
            to=SPEED_SLIDER_MAX,
            number_of_steps=200,
            variable=self._speed_var,
            width=88,
            height=14,
            command=self._on_speed_change,
        ).pack(side='left', padx=2, pady=14)
        ctk.CTkButton(nav_bar, text='►►', **speed_btn_cfg, command=self._speed_up).pack(side='left', padx=(2, 4), pady=6)
        self._lbl_speed = ctk.CTkLabel(nav_bar, text='x1.00', font=('Consolas', 10), text_color='#778899', width=42)
        self._lbl_speed.pack(side='left', padx=(0, 6))

        n = max(1, len(self._frames) - 1)
        self._slider_var = tk.IntVar(value=0)
        self._slider = ctk.CTkSlider(
            nav_bar,
            from_=0,
            to=n,
            number_of_steps=n,
            variable=self._slider_var,
            command=self._on_slider,
        )
        self._slider.pack(side='left', fill='x', expand=True, padx=8, pady=14)

        self._lbl_time = ctk.CTkLabel(
            nav_bar,
            text='--:--:--',
            font=('Consolas', 13, 'bold'),
            text_color='#4FC3F7',
            width=80,
        )
        self._lbl_time.pack(side='right', padx=10)

    def _go_to(self, idx: int) -> None:
        if not self._frames:
            return
        idx = max(0, min(idx, len(self._frames) - 1))
        self._idx = idx
        state = self._frames[idx]

        self._canvas.update_state(state)
        self._lbl_ts.configure(text=state.timestamp_str)
        self._lbl_frame.configure(text=f'{idx + 1} / {len(self._frames)}')
        self._lbl_line.configure(text=f'L. {state.line_num:,}')
        total_seconds = int(state.timestamp)
        hours, rest = divmod(total_seconds, 3600)
        minutes, seconds = divmod(rest, 60)
        self._lbl_time.configure(text=f'{hours:02d}:{minutes:02d}:{seconds:02d}')
        self._slider_var.set(idx)

        if self._on_frame is not None:
            self._on_frame(self._entry, state)

    @property
    def entry_filepath(self) -> str:
        return self._entry.filepath

    def is_entry(self, entry: TraceReportEntry) -> bool:
        return self._entry.filepath == entry.filepath

    def go_to_file_line(self, file_line: int, stop: bool = True) -> None:
        if stop:
            self._stop_playback()
            self._reset_error_reference()
        self._go_to(self._frame_for_file_line(file_line))

    def _go_start(self) -> None:
        self._stop_playback()
        self._reset_error_reference()
        self._go_to(0)

    def _go_end(self) -> None:
        self._stop_playback()
        self._reset_error_reference()
        self._go_to(len(self._frames) - 1)

    def _step_fwd(self) -> None:
        self._reset_error_reference()
        self._go_to(self._idx + 1)

    def _step_back(self) -> None:
        self._reset_error_reference()
        self._go_to(self._idx - 1)

    def _on_slider(self, val) -> None:
        self._stop_playback()
        self._reset_error_reference()
        self._go_to(int(float(val)))

    def _on_speed_change(self, val) -> None:
        speed = max(SPEED_MIN, min(SPEED_MAX, 2 ** float(val)))
        self._speed_value = speed
        self._play_delay = max(10, int(PLAY_DELAY_DEFAULT / speed))
        self._lbl_speed.configure(text=f'x{speed:.2f}')

    def _set_speed(self, speed: float) -> None:
        speed = max(SPEED_MIN, min(SPEED_MAX, speed))
        self._speed_var.set(math.log2(speed))
        self._on_speed_change(math.log2(speed))

    def _speed_down(self) -> None:
        self._set_speed(self._speed_value / 2)

    def _speed_up(self) -> None:
        self._set_speed(self._speed_value * 2)

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
        if hasattr(self, '_btn_play'):
            self._btn_play.configure(text='▶')
        if self._play_job:
            self.after_cancel(self._play_job)
            self._play_job = None

    def _schedule_next(self) -> None:
        if not self._playing:
            return
        if self._idx >= len(self._frames) - 1:
            self._stop_playback()
            return
        self._reset_error_reference()
        self._go_to(self._idx + 1)
        self._play_job = self.after(self._play_delay, self._schedule_next)

    def _error_pos_text(self) -> str:
        if not self._error_events:
            return 'Err 0/0'
        if self._current_error_line is None:
            return f'Err -/{len(self._error_events)}'
        for index, event in enumerate(self._error_events, 1):
            if event.line_num == self._current_error_line:
                return f'Err {index}/{len(self._error_events)}'
        return f'Err -/{len(self._error_events)}'

    def _set_error_reference(self, line_num: Optional[int]) -> None:
        self._current_error_line = line_num
        if hasattr(self, '_lbl_error_pos'):
            self._lbl_error_pos.configure(text=self._error_pos_text())

    def _reset_error_reference(self) -> None:
        self._set_error_reference(None)

    def _frame_for_file_line(self, file_line: int) -> int:
        keys = [item[0] for item in self._line_map]
        pos = bisect.bisect_right(keys, file_line) - 1
        if pos < 0:
            return 0
        return self._line_map[pos][1]

    def _go_to_event(self, event) -> None:
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

    def _close(self) -> None:
        self._stop_playback()
        if self._on_close is not None:
            self._on_close()
