"""Familles independantes sur une projection privee de la session."""
from pathlib import Path
from queue import Empty
import pickle
import time
import uuid


GROUPS = ('signals', 'c5', 'communication')
KEYS = ('C2', 'C3', 'cubestop', 't5_drive', 'C5', 'communication', 'resets', 'stale')
PROJECTION_BLOCK_SIZE = 8192


def pack_projection(lines):
    previous, compact = None, None
    rows = []
    for number, text, state in lines:
        if state is not previous:
            compact = (state.timestamp, state.timestamp_str, state.C6)
            previous = state
        rows.append((number, text, compact))
    return rows


def unpack_projection(rows):
    from Models.diagnostic import DiagnosticState
    from Models.trace_calendar import TraceLines
    previous, state = None, None
    result = TraceLines()
    for number, text, compact in rows:
        if compact is not previous:
            state = DiagnosticState(*compact)
            previous = compact
        result.append((number, text, state))
    return result


def write_projection(path, lines, origin):
    # Borner les tuples temporaires et le memo pickle au bloc courant.
    with Path(path).open('wb') as output:
        pickle.dump((3, origin), output, protocol=pickle.HIGHEST_PROTOCOL)
        for start in range(0, len(lines), PROJECTION_BLOCK_SIZE):
            rows = pack_projection(lines[start:start + PROJECTION_BLOCK_SIZE])
            pickle.dump(rows, output, protocol=pickle.HIGHEST_PROTOCOL)
        pickle.dump(None, output, protocol=pickle.HIGHEST_PROTOCOL)


def read_projection(path):
    from Models.trace_calendar import TraceLines
    lines = TraceLines()
    with Path(path).open('rb') as source:
        header = pickle.load(source)
        if not isinstance(header, tuple) or len(header) != 2 or header[0] != 3:
            raise OSError('Projection diagnostique incompatible')
        while True:
            rows = pickle.load(source)
            if rows is None:
                break
            lines.extend(unpack_projection(rows))
    return header[1], lines


def analyze_family(group, lines, origin):
    from Models import diagnostic as model
    if group == 'signals':
        result = {sensor: model._build_signal_incidents(lines, sensor) for sensor in ('C2', 'C3')}
        result['cubestop'] = model._build_cubestop_c4_blocked_incidents(lines)
        result['t5_drive'] = model._build_t5_drive_incidents(lines, origin)
        return result
    if group == 'c5':
        return {'C5': model._build_c5_incidents(lines, origin)}
    if group == 'communication':
        return {'communication': model._build_communication_and_mode_incidents(lines, origin),
                'resets': model._build_alpha_card_reset_incident(lines),
                'stale': model._build_stale_unmeasured_t5_incidents(lines)}
    raise ValueError('Famille diagnostique inconnue')


class DiagnosticExecution:
    def __init__(self, lines, origin, directory, policy):
        self.lines, self.origin = lines, origin
        self.directory = Path(directory) / ('diagnostic-workers-' + uuid.uuid4().hex)
        self.policy = policy
        self.tasks = []
        self.pending_groups = list(GROUPS)
        self.results = {}
        self.timings = {}

    def __enter__(self):
        self.directory.mkdir(parents=True)
        self.projection = self.directory / 'projection.pkl'
        self.timings['projection'] = 0.
        try:
            self._launch()
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def _launch(self):
        from Models.loading_client import WorkerTask
        from Models.resource_policy import launch_capacity
        capacity = launch_capacity(self.policy, additional=True)
        running = sum(not item['done'] for item in self.tasks)
        if self.pending_groups and running < capacity and not self.projection.exists():
            from Models.worker_process_tree import own_process_tree
            own_process_tree()
            started = time.perf_counter()
            write_projection(self.projection, self.lines, self.origin)
            self.timings['projection'] = time.perf_counter() - started
        while self.pending_groups and running < capacity:
            group = self.pending_groups.pop(0)
            task = WorkerTask(self.directory / group, dict(mode='diagnostic_family',
                projection=str(self.projection), family=group, session=str(self.directory)))
            self.tasks.append(dict(task=task, group=group, result=None, done=False))
            running += 1

    def finish(self, on_complete=None):
        while self.pending_groups or any(not item['done'] for item in self.tasks):
            received = False
            for item in self.tasks:
                if item['done']:
                    continue
                task = item['task']
                try:
                    kind, payload = task.results.get_nowait()
                except Empty:
                    if task.finished.is_set():
                        raise OSError('Sous-worker diagnostique termine sans resultat')
                    continue
                received = True
                if kind == 'family_result':
                    item['result'] = payload
                elif kind == 'error':
                    raise OSError(payload)
                elif kind == 'done':
                    if item['result'] is None:
                        raise OSError('Famille diagnostique incomplete')
                    item['done'] = True
                    self.results.update(item['result'])
                    self.timings[item['group']] = payload.get('timings', {})
                    if on_complete:
                        for key in item['result']:
                            on_complete(key)
            self._launch()
            if self.pending_groups and not any(not item['done'] for item in self.tasks):
                group = self.pending_groups.pop(0)
                started = time.perf_counter()
                result = analyze_family(group, self.lines, self.origin)
                self.results.update(result)
                self.timings[group] = {'lecture_projection': 0., 'calcul': time.perf_counter() - started}
                if on_complete:
                    for key in result:
                        on_complete(key)
                received = True
            if not received:
                time.sleep(.005)
        return self.results

    def __exit__(self, *_):
        for item in self.tasks:
            if not item['done'] and not item['task'].finished.is_set():
                item['task'].cancel()
        for item in self.tasks:
            if not item['task'].finished.wait(10):
                raise OSError('Le sous-worker diagnostique ne se ferme pas')
        self.projection.unlink(missing_ok=True)
