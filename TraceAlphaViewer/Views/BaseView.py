import customtkinter as ctk
from queue import Empty, Queue
import threading


class BaseView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        self._pending_jobs = set()
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self.master = master
        self._shortcut_bindings = []
        self._ui_queue = Queue()
        self._disposed = threading.Event()
        self._ui_job = self.after(40, self._poll_ui)

    def after(self, ms, func=None, *args):
        if func is None:
            return super().after(ms)
        job = None
        def run():
            self._pending_jobs.discard(job)
            func(*args)
        job = super().after(ms, run)
        self._pending_jobs.add(job)
        return job

    def after_cancel(self, job) -> None:
        self._pending_jobs.discard(job)
        super().after_cancel(job)

    def post_ui(self, callback, *args) -> None:
        if not self._disposed.is_set():
            self._ui_queue.put((callback, args))

    def _poll_ui(self) -> None:
        self._ui_job = None
        try:
            for _ in range(100):
                callback, args = self._ui_queue.get_nowait()
                callback(*args)
                if self._disposed.is_set():
                    return
        except Empty:
            pass
        self._ui_job = self.after(40, self._poll_ui)

    def bind_shortcut(self, sequence, callback) -> None:
        def handle(event):
            widget_class = event.widget.winfo_class()
            if widget_class in ('Entry', 'TEntry', 'Spinbox'):
                return
            if widget_class == 'Text' and str(event.widget.cget('state')) != 'disabled':
                return
            callback()
            return 'break'
        binding = self.master.bind(sequence, handle, add='+')
        self._shortcut_bindings.append((sequence, binding))

    def _unbind_shortcuts(self) -> None:
        for sequence, binding in self._shortcut_bindings:
            self.master.unbind(sequence, binding)
        self._shortcut_bindings.clear()

    def destroy(self) -> None:
        self._disposed.set()
        for job in tuple(self._pending_jobs):
            self.after_cancel(job)
        self._ui_job = None
        try:
            while True:
                self._ui_queue.get_nowait()
        except Empty:
            pass
        self._unbind_shortcuts()
        super().destroy()

    def show(self) -> None:
        self.pack(fill='both', expand=True)

    def hide(self) -> None:
        self._unbind_shortcuts()
        self.pack_forget()
