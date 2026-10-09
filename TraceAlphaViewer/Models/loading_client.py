"""Processus metier et sessions temporaires, sans appel Tk."""
from __future__ import annotations

from pathlib import Path
import pickle
from queue import Queue, Full
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import weakref

from Models.frame_store import FrameStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / '.trace_work'


class WorkerTask:
    def __init__(self, directory: Path, request: dict):
        self.job_id = uuid.uuid4().hex
        self.results = Queue(maxsize=4)
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.process = None
        self._directory = directory
        self._request = dict(request, job_id=self.job_id)
        threading.Thread(target=self._run, daemon=True).start()

    def _put(self, kind, payload) -> None:
        while not self.cancelled.is_set():
            try:
                self.results.put((kind, payload), timeout=0.05)
                return
            except Full:
                pass

    def _run(self) -> None:
        completed = False
        stderr = bytearray()
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            request_path = self._directory / 'request.pkl'
            with request_path.open('wb') as output:
                pickle.dump(self._request, output, protocol=pickle.HIGHEST_PROTOCOL)
            self._request = None
            if self.cancelled.is_set():
                return
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            self.process = subprocess.Popen(
                [sys.executable, '-u', '-m', 'Models.loading_worker', str(request_path)],
                cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=flags,
            )

            def drain_errors():
                while chunk := self.process.stderr.read(4096):
                    if len(stderr) < 8192:
                        stderr.extend(chunk[:8192 - len(stderr)])

            error_thread = threading.Thread(target=drain_errors, daemon=True)
            error_thread.start()
            while not self.cancelled.is_set():
                try:
                    job_id, kind, payload = pickle.load(self.process.stdout)
                except EOFError:
                    break
                if job_id != self.job_id:
                    continue
                self._put(kind, payload)
                if kind in ('done', 'error'):
                    completed = True
                    break
            if not completed and not self.cancelled.is_set():
                self.process.wait(timeout=5)
                error_thread.join(timeout=1)
                detail = stderr.decode('utf-8', errors='replace').strip()
                self._put('error', detail or 'Le worker de chargement a quitte sans resultat')
        except Exception as exc:
            if not self.cancelled.is_set():
                self._put('error', str(exc))
        finally:
            try:
                if self.process is not None:
                    if self.cancelled.is_set() and self.process.poll() is None:
                        try:
                            self.process.terminate()
                        except OSError:
                            pass
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
                    if 'error_thread' in locals():
                        error_thread.join(timeout=1)
                    self.process.stdout.close()
                    self.process.stderr.close()
            finally:
                self.finished.set()

    def cancel(self) -> None:
        self.cancelled.set()

        def stop():
            process = self.process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass

        threading.Thread(target=stop, daemon=True).start()


class LoadingSession:
    def __init__(self):
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='session-', dir=WORK_ROOT)).resolve()
        self.closed = threading.Event()
        self.cleaned = threading.Event()
        self.cleanup_error = None
        self._tasks = weakref.WeakSet()
        self._stores = []

    def start(self, mode: str, **arguments) -> WorkerTask:
        if self.closed.is_set():
            raise RuntimeError('La session de trace est fermee')
        if mode in ('file', 'folder'):
            arguments['path'] = str(Path(arguments['path']).resolve())
        task = WorkerTask(self.directory / ('job-' + uuid.uuid4().hex),
                          dict(arguments, mode=mode, session=str(self.directory)))
        self._tasks.add(task)
        return task

    def open_store(self, directory) -> FrameStore:
        path = Path(directory).resolve()
        if not path.is_relative_to(self.directory) or self.closed.is_set():
            raise OSError('Stockage de frames hors de la session active')
        store = FrameStore(path)
        self._stores.append(store)
        return store

    def close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for store in self._stores:
            store.close()
        self._stores.clear()

        def clean():
            try:
                for task in tasks:
                    task.finished.wait()
                # Ne supprimer que le dossier cree par cette session.
                path = self.directory.resolve()
                if path.parent != WORK_ROOT.resolve() or not path.name.startswith('session-'):
                    raise OSError('Dossier temporaire inattendu')
                # Windows peut garder un handle quelques instants apres la sortie.
                for attempt in range(6):
                    try:
                        shutil.rmtree(path)
                        break
                    except FileNotFoundError:
                        break
                    except OSError:
                        if attempt == 5:
                            raise
                        threading.Event().wait(0.1 * (attempt + 1))
            except Exception as exc:
                self.cleanup_error = str(exc)
            finally:
                self.cleaned.set()

        threading.Thread(target=clean, daemon=False).start()
