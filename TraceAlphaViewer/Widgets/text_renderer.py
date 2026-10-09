"""Insertion bornee de listes texte sur le thread Tk."""
import time


class TextRenderer:
    def __init__(self, owner, text, on_row=None, on_done=None):
        self.owner = owner
        self.text = text
        self.on_row = on_row
        self.on_done = on_done
        self.loading = False
        self._job = None
        self._rows = None
        self._line = 1

    def cancel(self):
        if self._job is not None:
            self.owner.after_cancel(self._job)
            self._job = None
        self._rows = None
        self.loading = False

    def start(self, rows):
        self.cancel()
        self._rows = iter(rows)
        self._line = 1
        self.loading = True
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.configure(state='disabled')
        self._insert()

    def _insert(self):
        self._job = None
        segments = []
        deadline = time.perf_counter() + 0.004
        exhausted = False
        for _ in range(250):
            try:
                value, tags, item = next(self._rows)
            except StopIteration:
                exhausted = True
                break
            if item is not None and self.on_row is not None:
                self.on_row(self._line, item)
            self._line += value.count('\n')
            segments.extend((value, tags))
            if time.perf_counter() >= deadline:
                break
        if segments:
            self.text.configure(state='normal')
            self.text.insert('end', *segments)
            self.text.configure(state='disabled')
        if exhausted:
            self.loading = False
            self._rows = None
            if self.on_done is not None:
                self.on_done()
        else:
            self._job = self.owner.after(5, self._insert)
