"""Snapshots locaux, lus par blocs sans charger toute la trace dans Tk."""
from __future__ import annotations

from array import array
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
import pickle
import operator

from Models.state import MachineState


BLOCK_SIZE = 500
CACHE_BLOCKS = 2


def write_frame_store(frames: Sequence[MachineState], directory: Path,
                      release: bool = False, measurement_summary=None) -> None:
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
                'measurement_summary': measurement_summary or {}}
    temporary = directory / 'index.tmp'
    with temporary.open('wb') as output:
        pickle.dump(metadata, output, protocol=pickle.HIGHEST_PROTOCOL)
    # L'index n'est publie qu'apres la fermeture du fichier de frames.
    temporary.replace(directory / 'index.pkl')


class FrameStore(Sequence[MachineState]):
    def __init__(self, directory: str | Path):
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
        self._offsets = metadata['offsets']
        if len(self._offsets) != (len(self) + BLOCK_SIZE - 1) // BLOCK_SIZE:
            raise OSError('Index de frames incomplet')
        self._file = (self.directory / 'frames.bin').open('rb')
        self._cache = OrderedDict()

    def __len__(self) -> int:
        return len(self.line_numbers)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        index = operator.index(index)
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        if self._file.closed:
            raise OSError('Le stockage de la trace est ferme')
        block = index // BLOCK_SIZE
        if block not in self._cache:
            try:
                self._file.seek(self._offsets[block])
                frames = pickle.load(self._file)
                expected = min(BLOCK_SIZE, len(self) - block * BLOCK_SIZE)
                if len(frames) != expected:
                    raise ValueError('Bloc de frames incomplet')
            except (EOFError, pickle.UnpicklingError, ValueError) as exc:
                raise OSError('Impossible de lire les frames de la trace') from exc
            self._cache[block] = frames
            if len(self._cache) > CACHE_BLOCKS:
                self._cache.popitem(last=False)
        self._cache.move_to_end(block)
        return self._cache[block][index % BLOCK_SIZE]

    def frame_index_for_line(self, line: int) -> int:
        return max(0, bisect_right(self.line_numbers, line) - 1)

    def read_events(self):
        with (self.directory / 'events.pkl').open('rb') as source:
            return pickle.load(source)

    def read_measurements(self):
        from Models.measurement_analysis import analyze_measurements
        path = self.directory / 'measurements.pkl'
        if not path.exists():
            return analyze_measurements(self)
        with path.open('rb') as source:
            return pickle.load(source)

    def close(self) -> None:
        self._cache.clear()
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
