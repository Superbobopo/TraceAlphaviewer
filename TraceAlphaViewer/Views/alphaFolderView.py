"""Catalogue par Alpha, avec preparation du bilan uniquement a la demande."""
from __future__ import annotations

from pathlib import Path
from queue import Empty
import time
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from Models.folder_report import FolderReport, TraceReportEntry, export_folder_report_csv
from Views.BaseView import BaseView


class AlphaFolderView(BaseView):
    def __init__(self, master, directory, catalog, load_session, **kwargs):
        super().__init__(master, **kwargs)
        self._directory = directory
        self._catalog = catalog or {'groups': []}
        self._groups = self._catalog.get('groups', [])
        self._load_session = load_session
        self._cache = {}
        self._prepared = False
        self._task = None
        self._data = None
        self._selected = None
        self._export_path = None
        self._export_queue = []
        self._prepared_view = None
        self._exporting = False
        self._export_cancel = threading.Event()

    def prepare(self, on_ready, on_error=None):
        self._build()

        def insert(start=0):
            try:
                for index in range(start, min(start + 100, len(self._groups))):
                    group = self._groups[index]
                    period = self._period(group)
                    self._tree.insert('', 'end', iid=str(index), text=group['label'],
                                      values=(len(group['sources']), period,
                                              'À vérifier' if group.get('status') == 'verify' else 'À analyser'))
                if start + 100 < len(self._groups):
                    self.after(5, insert, start + 100)
                else:
                    self._prepared = True
                    on_ready()
            except Exception as exc:
                if on_error:
                    on_error(str(exc))
                else:
                    raise
        self.after(5, insert)

    def show(self):
        super().show()
        if not self._prepared:
            self.prepare(lambda: None)

    @staticmethod
    def _period(group):
        start, end = group.get('start'), group.get('end')
        return f'{start or "Dates indisponibles"} → {end or "?"}'

    def _build(self):
        bar = ctk.CTkFrame(self, height=45)
        bar.pack(fill='x')
        ctk.CTkLabel(bar, text=f'Dossier : {Path(self._directory).name}',
                     font=('Segoe UI', 16, 'bold')).pack(side='left', padx=15, pady=10)
        ctk.CTkButton(bar, text='Fermer', width=85, command=self._close).pack(side='right', padx=10)
        self._csv_button = ctk.CTkButton(bar, text='Exporter CSV complet', width=165, command=self._export_csv)
        self._csv_button.pack(side='right', padx=10)
        ctk.CTkLabel(self, text=(f'{len(self._groups)} groupe(s) identifié(s). '
                              'Sélectionnez un Alpha pour préparer puis ouvrir son bilan.'),
                     anchor='w').pack(fill='x', padx=15, pady=8)
        body = ctk.CTkFrame(self)
        body.pack(fill='both', expand=True, padx=12)
        style = ttk.Style()
        style.configure('AlphaFolder.Treeview', rowheight=33)
        self._tree = ttk.Treeview(body, columns=('files', 'period', 'status'),
                                 style='AlphaFolder.Treeview', selectmode='browse')
        self._tree.heading('#0', text='Alpha / pharmacie')
        self._tree.heading('files', text='Fichiers')
        self._tree.heading('period', text='Période')
        self._tree.heading('status', text='État')
        self._tree.column('#0', width=300, minwidth=160)
        self._tree.column('files', width=65, stretch=False)
        self._tree.column('period', width=360)
        self._tree.column('status', width=110, stretch=False)
        scroll = ttk.Scrollbar(body, orient='vertical', command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self._tree.pack(fill='both', expand=True)
        self._tree.bind('<<TreeviewSelect>>', self._on_select)
        self._details = tk.Text(self, height=7, bg='#171b25', fg='#c7d5e5',
                                relief='flat', wrap='word', state='disabled')
        self._details.pack(fill='x', padx=12, pady=8)
        if not self._groups:
            self._set_details('Aucune trace .old ou .txt trouvée dans ce dossier.')
        footer = ctk.CTkFrame(self)
        footer.pack(fill='x', padx=12, pady=(0, 12))
        self._status = ctk.CTkLabel(footer, text='Choisissez un groupe.', anchor='w')
        self._status.pack(fill='x', padx=8, pady=4)
        self._progress = ctk.CTkProgressBar(footer)
        self._progress.set(0)
        self._progress.pack(side='left', fill='x', expand=True, padx=8, pady=8)
        self._cancel = ctk.CTkButton(footer, text='Annuler', width=90, state='disabled', command=self._cancel_loading)
        self._cancel.pack(side='right', padx=8)
        self._open = ctk.CTkButton(footer, text='Ouvrir le bilan', width=140, command=self._open_selected)
        self._open.pack(side='right', padx=8)

    def _set_details(self, text):
        self._details.configure(state='normal')
        self._details.delete('1.0', 'end')
        self._details.insert('end', text)
        self._details.configure(state='disabled')

    def _on_select(self, _event=None):
        selection = self._tree.selection()
        if not selection or self._task is not None or self._prepared_view is not None or self._exporting:
            return
        self._selected = int(selection[0])
        group = self._groups[self._selected]
        lines = [group['label'], self._period(group)]
        lines += [str(issue) for issue in group.get('issues', [])]
        lines += [str(source.get('filepath', source.get('path', ''))) for source in group['sources']]
        for duplicate in group.get('duplicates', []):
            lines.append(f"Copie exclue : {duplicate.get('filepath', '')} → {duplicate.get('duplicate_of', '')}")
        self._set_details('\n'.join(lines))
        self._open_selected()

    def _open_selected(self):
        if self._selected is None or self._task is not None or self._prepared_view is not None or self._exporting:
            return
        self._start_group(self._selected)

    def _start_group(self, index):
        if self._task is not None or self._prepared_view is not None or self._exporting:
            return
        if index in self._cache:
            if self._export_path:
                self._continue_export()
            else:
                self._open_viewer(self._cache[index])
            return
        self._loading_index = index
        self._data = None
        self._progress.set(0)
        self._status.configure(text=f"Préparation : {self._groups[index]['label']}")
        self._cancel.configure(state='normal')
        self._open.configure(state='disabled')
        self._csv_button.configure(state='disabled')
        self._task = self._load_session.start('folder_group', path=self._directory, group=self._groups[index])
        self.after(10, self._poll)

    def _poll(self):
        if self._task is None:
            return
        deadline = time.perf_counter() + 0.008
        try:
            while time.perf_counter() < deadline:
                kind, payload = self._task.results.get_nowait()
                if kind == 'step':
                    self._status.configure(text=f'{payload[0]} · {payload[1]}')
                elif kind == 'progress':
                    self._progress.set(float(payload))
                elif kind == 'entry':
                    self._data = dict(payload, events=[], diagnostics=[], references=[])
                    self._data['frames'] = self._load_session.open_store(payload['store'])
                elif kind in ('events', 'diagnostics', 'references'):
                    self._data[kind].extend(payload)
                elif kind == 'entry_done':
                    if any(len(self._data[key]) != count for key, count in payload.items()):
                        raise OSError('Bilan de groupe incomplet')
                elif kind == 'error':
                    raise OSError(payload)
                elif kind == 'done':
                    if self._data is None:
                        raise OSError('Aucun bilan préparé')
                    self._data['timings'] = payload.get('timings', {})
                    self._cache[self._loading_index] = self._data
                    self._tree.set(str(self._loading_index), 'status', 'Prêt')
                    data = self._data
                    self._reset_loading()
                    if self._export_path:
                        self._continue_export()
                    else:
                        self._open_viewer(data)
                    return
        except Empty:
            pass
        except Exception as exc:
            self._cancel_loading()
            self._status.configure(text=str(exc))
            messagebox.showerror('Bilan du dossier', str(exc), parent=self)
            return
        self.after(10, self._poll)

    def _reset_loading(self):
        self._task = None
        self._data = None
        self._cancel.configure(state='disabled')
        self._open.configure(state='normal')
        self._csv_button.configure(state='normal')
        self._progress.set(1)

    def _cancel_loading(self):
        self._export_cancel.set()
        if self._task is not None:
            self._task.cancel()
        if self._data and self._data.get('frames') is not None:
            self._data['frames'].close()
        if self._prepared_view is not None:
            self._prepared_view.destroy()
            self._prepared_view = None
        self._export_path = None
        self._export_queue = []
        self._reset_loading()
        self._status.configure(text='Chargement annulé. Les bilans déjà prêts sont conservés.')

    def _open_viewer(self, data):
        from Views.traceView import TraceView
        view = TraceView(self.master, data['filepath'], data['frames'], events=data['events'],
                         diagnostics=data['diagnostics'], references=data['references'], return_view=self,
                         load_session=self._load_session, owns_load_session=False, source_name=data['name'],
                         navigation=data.get('navigation'))
        self._prepared_view = view
        self._open.configure(state='disabled')
        self._cancel.configure(state='normal')

        def ready():
            self._prepared_view = None
            self._open.configure(state='normal')
            self._cancel.configure(state='disabled')
            self.master.switch_view(view)

        def failed(message):
            view.destroy()
            self._prepared_view = None
            self._open.configure(state='normal')
            self._cancel.configure(state='disabled')
            self._status.configure(text=message)
        view.prepare(ready, on_error=failed)

    def _export_csv(self):
        if self._task is not None or self._prepared_view is not None or self._exporting or not self._groups:
            return
        path = filedialog.asksaveasfilename(parent=self, title='Exporter tous les bilans du dossier',
                                          defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if path:
            self._export_path = path
            self._export_queue = [index for index in range(len(self._groups)) if index not in self._cache]
            self._continue_export()

    def _continue_export(self):
        if self._export_queue:
            self._start_group(self._export_queue.pop(0))
            return
        entries = []
        for index in range(len(self._groups)):
            data = self._cache[index]
            entries.append(TraceReportEntry(filepath=data['filepath'], name=data['name'], frames=data['frames'],
                                            events=data['events'], diagnostics=data['diagnostics']))
        destination = Path(self._export_path)
        self._export_path = None
        self._exporting = True
        self._export_cancel.clear()
        self._csv_button.configure(state='disabled')
        self._open.configure(state='disabled')
        self._cancel.configure(state='normal')

        def export():
            temporary = None
            error = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.tracealpha-', suffix='.tmp', delete=False) as handle:
                    temporary = Path(handle.name)
                export_folder_report_csv(FolderReport(self._directory, entries), temporary)
                if not self._export_cancel.is_set() and not self._disposed.is_set():
                    temporary.replace(destination)
            except Exception as exc:
                error = str(exc)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            self.post_ui(self._export_finished, error)
        threading.Thread(target=export, daemon=True).start()

    def _export_finished(self, error):
        self._exporting = False
        self._reset_loading()
        if error:
            self._status.configure(text=error)
            messagebox.showerror('Export CSV', error, parent=self)
        elif self._export_cancel.is_set():
            self._status.configure(text='Export CSV annulé.')
        else:
            self._status.configure(text='CSV complet exporté ; tous les groupes ont été analysés.')

    def _close(self):
        from Views.accueilView import AccueilView
        self.master.switch_view(AccueilView(self.master))

    def destroy(self):
        self._export_cancel.set()
        if self._prepared_view is not None:
            self._prepared_view.destroy()
        self._cache.clear()
        self._load_session.close()
        super().destroy()
