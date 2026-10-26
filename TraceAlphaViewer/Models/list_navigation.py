"""Index compacts de navigation des listes, prepares dans le worker."""
from array import array
from bisect import bisect_right


PAGE_SIZE = 500


class LineIndex:
    def __init__(self, items, attribute='line_num'):
        order = sorted(range(len(items)), key=lambda i: (getattr(items[i], attribute), -i))
        self.lines = array('Q', (getattr(items[i], attribute) for i in order))
        self.positions = array('Q', order)

    def position_for_line(self, line):
        index = bisect_right(self.lines, line) - 1
        return self.positions[index] if index >= 0 else None


def error_events(events, diagnostics):
    from Models.state import MachineEvent
    return [event for event in events if event.severity == 'error'] + [MachineEvent(
        line_num=row.first_line, timestamp=row.start_time, timestamp_str=row.start_time_str,
        severity='error', kind='DIAG', title=f'{row.title} ({row.code})', detail=row.summary)
        for row in diagnostics if row.code == 'T5_STALE_UNMEASURED_BOX' and row.severity == 'error']


def prepare_navigation(events, diagnostics, references):
    errors = error_events(events, diagnostics)
    return {'events': LineIndex(events), 'errors': LineIndex(errors), 'error_events': errors,
            'references': LineIndex(references, 'first_line')}
