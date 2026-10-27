"""Snapshots locaux, lus par blocs sans charger toute la trace dans Tk."""
from __future__ import annotations

from array import array
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
import pickle
import operator
import sys
import threading

from Models.state import MachineState


BLOCK_SIZE = 500
CACHE_BLOCKS = 2


def block_memory(frames):
    """Compte le graphe du bloc, en evitant les alias et les objets de classes."""
    pending, seen, total = [frames], set(), 0
    while pending:
        value = pending.pop()
        identifier = id(value)
        if identifier in seen:
            continue
        seen.add(identifier)
        total += sys.getsizeof(value)
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
        elif type(value).__module__ == 'Models.state':
            pending.append(vars(value))
    return total + 256


def update_store_metadata(directory, **values):
    """Finalise les metadonnees sans reecrire les blocs de frames."""
    directory = Path(directory)
    with (directory / 'index.pkl').open('rb') as source:
        metadata = pickle.load(source)
    metadata.update(values)
    temporary = directory / 'index.tmp'
    with temporary.open('wb') as output:
        pickle.dump(metadata, output, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(directory / 'index.pkl')


def write_frame_store_iter(frames, directory: Path, *, measurement_summary=None,
                           trace_period=None, source_metadata=None) -> int:
    """Ecrit un flux de frames avec un seul bloc en memoire."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lines = array('Q')
    offsets = array('Q')
    batch = []
    start_time = end_time = '--:--:--'
    previous_line = -1
    with (directory / 'frames.bin').open('wb') as output:
        for frame in frames:
            if frame.line_num < previous_line:
                raise ValueError('Les frames doivent suivre les lignes sources')
            previous_line = frame.line_num
            if not lines:
                start_time = frame.timestamp_str
            end_time = frame.timestamp_str
            lines.append(frame.line_num)
            batch.append(frame)
            if len(batch) == BLOCK_SIZE:
                offsets.append(output.tell())
                pickle.dump(batch, output, protocol=pickle.HIGHEST_PROTOCOL)
                batch = []
        if batch:
            offsets.append(output.tell())
            pickle.dump(batch, output, protocol=pickle.HIGHEST_PROTOCOL)
    metadata = {'version': 1, 'block_size': BLOCK_SIZE, 'lines': lines, 'offsets': offsets,
                'start_time': start_time, 'end_time': end_time,
                'measurement_summary': measurement_summary or {}, 'trace_period': trace_period or {},
                'source_metadata': source_metadata or {}}
    temporary = directory / 'index.tmp'
    with temporary.open('wb') as output:
        pickle.dump(metadata, output, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(directory / 'index.pkl')
    return len(lines)


def write_frame_store(frames: Sequence[MachineState], directory: Path,
                      release: bool = False, measurement_summary=None, trace_period=None,
                      source_metadata=None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = array('Q', (frame.line_num for frame in frames))
    start_time = frames[0].timestamp_str if frames else '--:--:--'
    end_time = frames[-1].timestamp_str if frames else '--:--:--'
    offsets = array('Q')
    with (directory / 'frames.bin').open('wb') as output:
        for start in range(0, len(frames), BLOCK_SIZE):
            batch = frames[start:start + BLOCK_SIZE]
            offsets.append(output.tell())
            pickle.dump(batch, output, protocol=pickle.HIGHEST_PROTOCOL)
            if release:
                frames[start:start + len(batch)] = [None] * len(batch)
    metadata = {'version': 1, 'block_size': BLOCK_SIZE, 'lines': lines, 'offsets': offsets,
                'start_time': start_time, 'end_time': end_time,
                'measurement_summary': measurement_summary or {}, 'trace_period': trace_period or {},
                'source_metadata': source_metadata or {}}
    temporary = directory / 'index.tmp'
    with temporary.open('wb') as output:
        pickle.dump(metadata, output, protocol=pickle.HIGHEST_PROTOCOL)
    # L'index n'est publie qu'apres la fermeture du fichier de frames.
    temporary.replace(directory / 'index.pkl')


class FrameStore(Sequence[MachineState]):
    def __init__(self, directory: str | Path, *, cache_governor=None):
        self.directory = Path(directory).resolve()
        try:
            with (self.directory / 'index.pkl').open('rb') as source:
                metadata = pickle.load(source)
            if not isinstance(metadata, dict) or not all(key in metadata for key in (
                    'version', 'block_size', 'lines', 'offsets', 'start_time', 'end_time')):
                raise ValueError('Index incomplet')
        except (EOFError, pickle.UnpicklingError, ValueError) as exc:
            raise OSError('Impossible de lire l\'index de la trace') from exc
        if metadata['version'] != 1 or metadata['block_size'] != BLOCK_SIZE:
            raise OSError('Format du stockage de frames incompatible')
        self.line_numbers = metadata['lines']
        self.start_time_str = metadata['start_time']
        self.end_time_str = metadata['end_time']
        self.measurement_summary = metadata.get('measurement_summary', {})
        self.trace_period = metadata.get('trace_period', {})
        self.source_metadata = metadata.get('source_metadata', {})
        self._source_starts = tuple(item['first_line'] for item in self.source_metadata.get('sources', []))
        self._segment_starts = tuple(item['first_frame'] for item in self.source_metadata.get('segments', []))
        self._offsets = metadata['offsets']
        if len(self._offsets) != (len(self) + BLOCK_SIZE - 1) // BLOCK_SIZE:
            raise OSError('Index de frames incomplet')
        self._file = (self.directory / 'frames.bin').open('rb')
        self._cache = OrderedDict()
        self._cache_sizes = {}
        self._cache_lock = threading.RLock()
        self._cache_governor = cache_governor
        self.cache_hits = self.cache_misses = 0

    def __len__(self) -> int:
        return len(self.line_numbers)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        with self._cache_lock:
            return self._get_frame(index)

    def _get_frame(self, index):
        index = operator.index(index)
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        if self._file.closed:
            raise OSError('Le stockage de la trace est ferme')
        block = index // BLOCK_SIZE
        if block not in self._cache:
            self.cache_misses += 1
            try:
                self._file.seek(self._offsets[block])
                frames = pickle.load(self._file)
                expected = min(BLOCK_SIZE, len(self) - block * BLOCK_SIZE)
                if len(frames) != expected:
                    raise ValueError('Bloc de frames incomplet')
            except (EOFError, pickle.UnpicklingError, ValueError) as exc:
                raise OSError('Impossible de lire les frames de la trace') from exc
            self._cache[block] = frames
            if self._cache_governor is not None:
                self._cache_sizes[block] = block_memory(frames)
        else:
            self.cache_hits += 1
        self._cache.move_to_end(block)
        self._trim_cache()
        return self._cache[block][index % BLOCK_SIZE]

    def _trim_cache(self, extra_limit=None):
        if self._cache_governor is None:
            while len(self._cache) > CACHE_BLOCKS:
                self._cache.popitem(last=False)
            return
        extra = sum(self._cache_sizes[key] for key in list(self._cache)[:-CACHE_BLOCKS])
        allowance = self._cache_governor.cache_allowance(self, extra) if extra_limit is None else extra_limit
        while len(self._cache) > CACHE_BLOCKS and extra > allowance:
            key, _ = self._cache.popitem(last=False)
            extra -= self._cache_sizes.pop(key)
        self._cache_governor.cache_allowance(self, extra)

    def trim_extra_cache(self):
        with self._cache_lock:
            if not self._file.closed:
                self._trim_cache(0)

    def frame_index_for_line(self, line: int) -> int:
        from Parser.trace_source import canonical_line
        line = canonical_line(line, self.source_metadata.get('duplicate_ranges', []))
        return max(0, bisect_right(self.line_numbers, line) - 1)

    def source_location(self, line: int) -> dict:
        """Retrouve le fichier et la ligne originale d'une session de dossier."""
        from Parser.trace_source import canonical_line
        line = canonical_line(line, self.source_metadata.get('duplicate_ranges', []))
        sources = self.source_metadata.get('sources', [])
        if not sources:
            return {'line': line, 'source_line': line, 'filepath': '', 'name': ''}
        index = bisect_right(self._source_starts, line) - 1
        if index < 0 or line > sources[index]['last_line']:
            return {'line': line, 'source_line': line, 'filepath': '', 'name': ''}
        source = sources[index]
        return {'line': line, 'source_line': line - source['line_offset'],
                'filepath': source['filepath'], 'name': source['name'],
                'segment': source.get('segment', index)}

    def segment_index_for_frame(self, index: int) -> int:
        segments = self.source_metadata.get('segments', [])
        if not segments:
            return 0
        return max(0, bisect_right(self._segment_starts, index) - 1)

    def read_events(self):
        with (self.directory / 'events.pkl').open('rb') as source:
            return pickle.load(source)

    def read_camera_report(self):
        from Models.diagnostic import camera_report_stats
        path = self.directory / 'camera_report.pkl'
        if not path.exists():
            return camera_report_stats(self)
        with path.open('rb') as source:
            return pickle.load(source)

    def frames_for_lines(self, lines):
        """Lire une fois les frames utiles, dans l'ordre des blocs."""
        indices = {self.frame_index_for_line(line) for line in lines
                   if len(self) and line >= 1}
        for index in sorted(indices):
            yield self[index]

    def read_measurements(self):
        from Models.measurement_analysis import analyze_measurements
        path = self.directory / 'measurements.pkl'
        if not path.exists():
            return analyze_measurements(self)
        with path.open('rb') as source:
            return pickle.load(source)

    def close(self) -> None:
        with self._cache_lock:
            self._cache.clear()
            self._cache_sizes.clear()
            if self._cache_governor is not None:
                self._cache_governor.release_cache(self)
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
