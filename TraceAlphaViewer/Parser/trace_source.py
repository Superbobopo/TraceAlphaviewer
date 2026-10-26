"""Lecture canonique des traces, sans modifier les lignes du fichier source."""
import re


_OPENING = re.compile(rb'OUVERTURE DE LA TRACE.*\ble\s+\d{2}/\d{2}/\d{4}')
_STAMP = re.compile(rb'\s*[*L ]?\s*\d{1,2}\|\d{2}:\d{2}:\d{2}\.\d+')


def canonical_lines(filepath, metadata=None):
    """Ignore les copies exactes ancrees sur un meme entete date."""
    ranges = []
    if metadata is not None:
        metadata.update(duplicate_ranges=ranges)
    openings = {}
    line = 0
    with open(filepath, 'rb') as source, open(filepath, 'rb') as previous:
        while True:
            offset = source.tell()
            raw = source.readline()
            if not raw:
                break
            line += 1
            if _OPENING.search(raw):
                resume = source.tell()
                for old_offset, old_line in openings.get(raw, []):
                    previous.seek(old_offset)
                    source.seek(offset)
                    count = stamps = 0
                    while previous.tell() < offset:
                        position = source.tell()
                        candidate = source.readline()
                        if not candidate or candidate != previous.readline():
                            source.seek(position)
                            break
                        count += 1
                        stamps += bool(_STAMP.match(candidate))
                    if stamps >= 3:
                        ranges.append({'first_line': line, 'last_line': line + count - 1,
                                       'source_first_line': old_line})
                        line += count - 1
                        break
                else:
                    source.seek(resume)
                    openings.setdefault(raw, []).append((offset, line))
                    yield line, raw.decode('latin-1').rstrip('\r\n'), source.tell()
                if ranges and ranges[-1]['last_line'] == line:
                    continue
            else:
                yield line, raw.decode('latin-1').rstrip('\r\n'), source.tell()


def canonical_line(line, ranges):
    for span in ranges:
        if span['first_line'] <= line <= span['last_line']:
            return span['source_first_line'] + line - span['first_line']
    return line
