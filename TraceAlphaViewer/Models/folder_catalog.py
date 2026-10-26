"""Catalogue Python des traces, independant du parser des frames."""
from collections import defaultdict
from datetime import datetime, timedelta
import filecmp
import hashlib
import os
from pathlib import Path
import re

_BASE = re.compile(r"\b(BASEALPHA(?:2)?_[^\\/:*?\"<>|\r\n']*?\.MDB|BASEFIC[^\\/:*?\"<>|\r\n']*?\.MDB)\b", re.I)
_STAMP = re.compile(r'^\s*[*L ]?\s*(\d{1,2})\|(\d{2}):(\d{2}):(\d{2})\.(\d+)')
_DATE = re.compile(r'\ble\s+(\d{2}/\d{2}/\d{4})', re.I)
_NUMBER = re.compile(r'^BASEALPHA(?:2)?_#?(?:\d{4}\.)?(\d+)\.MDB$')
_IGNORED = {'.trace_work', '.git', 'node_modules', '.venv', '__pycache__', 'target', '.next'}


def identity_from_bases(alpha, pharmacy):
    alpha, pharmacy = {name.upper() for name in alpha}, {name.upper() for name in pharmacy}
    if len(alpha) != 1 or len(pharmacy) != 1:
        return None
    a, p = next(iter(alpha)), next(iter(pharmacy))
    number = _NUMBER.match(a)
    return {'alpha_database': a, 'pharmacy_database': p,
            'alpha_number': number[1] if number else None,
            'pharmacy': re.sub(r'^[\d_-]+', '', p[7:-4]).title() or p}


def read_source_identity(path):
    alpha, pharmacy = set(), set()
    with Path(path).open(encoding='latin-1') as stream:
        for text in stream:
            if 'BASE' not in text.upper():
                continue
            for name in _BASE.findall(text):
                (alpha if name.upper().startswith('BASEALPHA') else pharmacy).add(name)
    return identity_from_bases(alpha, pharmacy)


def scan_source(path):
    alpha, pharmacy, headers = set(), set(), []
    date = first = last = pending = None
    invalid = False
    digest = hashlib.sha256()
    size = lines = stamps = 0
    with path.open('rb') as stream:
        stat = os.fstat(stream.fileno())
        for raw in stream:
            lines += 1
            size += len(raw)
            digest.update(raw)
            text = raw.decode('latin-1')
            for name in _BASE.findall(text):
                (alpha if name.upper().startswith('BASEALPHA') else pharmacy).add(name.upper())
            if 'OUVERTURE DE LA TRACE' in text.upper() or 'ATION DE LA TRACE' in text.upper():
                found = _DATE.search(text)
                if found:
                    try:
                        date = datetime.strptime(found[1], '%d/%m/%Y')
                        headers.append(text.rstrip())
                        if first is None and pending:
                            if date.day == pending[0]:
                                first = last = date + timedelta(seconds=pending[1])
                            else:
                                invalid = True
                    except ValueError:
                        invalid = True
            stamp = _STAMP.match(text)
            if stamp:
                stamps += 1
                day, hour, minute, second, fraction = map(int, stamp.groups())
                seconds = hour * 3600 + minute * 60 + second + fraction * .1
                pending = pending or (day, seconds)
                if date:
                    try:
                        month = date.replace(day=1)
                        if day < date.day:
                            if date.day >= 28 and day <= 3:
                                month = (month + timedelta(days=32)).replace(day=1)
                            else:
                                invalid = True
                        moment = month.replace(day=day) + timedelta(seconds=seconds)
                        date = moment.replace(hour=0, minute=0, second=0, microsecond=0)
                        first = min(first, moment) if first else moment
                        last = max(last, moment) if last else moment
                    except ValueError:
                        invalid = True
    if not stamps:
        return None
    identity = identity_from_bases(alpha, pharmacy)
    issues = []
    if identity is None:
        issues.append('Identité Alpha/pharmacie absente, incomplète ou contradictoire')
    if not first or not last or invalid:
        first = last = None
        issues.append('Calendrier de trace absent ou incohérent')
    return {'filepath': str(path.resolve()), 'line_count': lines, 'bytes': size,
            'identity': identity, 'start': first.isoformat() if first else None,
            'end': last.isoformat() if last else None,
            'start_timestamp': (first - datetime(1970, 1, 1)).total_seconds() if first else None,
            'end_timestamp': (last - datetime(1970, 1, 1)).total_seconds() if last else None,
            'status': 'verify' if issues else 'ready', 'issues': issues, 'duplicate_of': None,
            'python_fingerprint': digest.hexdigest(), 'mtime_ns': stat.st_mtime_ns,
            '_headers': headers}


def catalog_folder(directory, progress=None):
    root = Path(directory).resolve()
    if not root.is_dir():
        raise OSError('Dossier de traces inaccessible')
    paths, issues, sources = [], [], []
    def failed(error):
        issues.append(str(error))
    for parent, directories, files in os.walk(root, onerror=failed):
        directories[:] = [name for name in directories if name.casefold() not in _IGNORED]
        paths.extend(Path(parent) / name for name in files if Path(name).suffix.casefold() in {'.old', '.txt'})
    for index, path in enumerate(sorted(paths, key=lambda p: str(p).casefold())):
        try:
            source = scan_source(path)
            if source:
                sources.append(source)
        except OSError as exc:
            issues.append(f'{path} : {exc}')
        if progress:
            progress((index + 1) / max(1, len(paths)))
    seen = defaultdict(list)
    for source in sources:
        key = (source['bytes'], source['python_fingerprint'])
        for previous in seen[key]:
            if (source['_headers'] and source['_headers'] == previous['_headers']
                    and filecmp.cmp(source['filepath'], previous['filepath'], shallow=False)):
                source['duplicate_of'] = previous['filepath']
                break
        if not source['duplicate_of']:
            seen[key].append(source)
    ready = defaultdict(list)
    for source in sources:
        if source['status'] == 'ready' and not source['duplicate_of']:
            identity = source['identity']
            ready[(identity['alpha_database'], identity['pharmacy_database'])].append(source)
    for items in ready.values():
        active = []
        for source in sorted(items, key=lambda row: row['start']):
            active = [row for row in active if row['end'] >= source['start']]
            for row in active:
                for item in (source, row):
                    item['status'] = 'verify'
                    reason = 'Recouvrement temporel ambigu : fichier isolé'
                    if reason not in item['issues']:
                        item['issues'].append(reason)
            active.append(source)
    groups = {}
    for index, source in enumerate(sources):
        source.pop('_headers')
        if source['duplicate_of']:
            continue
        identity = source['identity']
        key = ((identity['alpha_database'], identity['pharmacy_database']) if source['status'] == 'ready'
               else ('verify', index))
        if key not in groups:
            label = (f"Alpha {identity['alpha_number']}" if identity and identity['alpha_number'] else
                     identity['alpha_database'] if identity else 'Identité à vérifier')
            if identity:
                label += f" — Pharmacie {identity['pharmacy']}"
            if source['status'] == 'verify':
                label += f" — {Path(source['filepath']).name}"
            groups[key] = {'id': f'group-{index:06}', 'label': label, 'identity': identity,
                           'sources': [], 'duplicates': [], 'status': source['status'], 'issues': source['issues']}
        groups[key]['sources'].append(source)
    for group in groups.values():
        group['sources'].sort(key=lambda row: row['start'] or '')
        group['start'] = group['sources'][0]['start']
        group['end'] = group['sources'][-1]['end']
        originals = {row['filepath'] for row in group['sources']}
        group['duplicates'] = [row for row in sources if row['duplicate_of'] in originals]
    return {'path': str(root), 'groups': list(groups.values()), 'files': len(sources),
            'ignored_files': len(paths) - len(sources), 'issues': issues}


def validate_source(source):
    with open(source['filepath'], 'rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if source.get('python_fingerprint') and digest != source['python_fingerprint']:
        raise OSError('La trace a changé : rouvrez le dossier avant son analyse.')
