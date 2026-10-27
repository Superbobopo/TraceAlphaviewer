"""Suit les passages physiques pour distinguer lecture et reference absente."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import re


_HIST = re.compile(r'\bCB([12]):\s+ajout Hist_LectCB .*?(\d+)code\(s\) lu\(s\)', re.I)
_RESULT = re.compile(r'idCB([12]):\s*-->\s*R\S*f:(\S+)', re.I)
_REFUSED = re.compile(
    r"idCB([12]):\s+la r\S*f\.\s+(\d+)\s+n'est pas dans les tables.*"
    r'pas dans BdD,\s*refus de cr\S*ation dans param', re.I)
_NON_ALPHATISABLE = re.compile(
    r"idCB([12]):\s+la r\S*f\.\s+(\d+)\s+n'est pas dans les tables.*?"
    r'\((r\S*f\.\s+non\s+Alphatisable\b.*)\)\s*$', re.I)
_CB2_SOURCE = re.compile(r'idCB2:.*?idCB1\.Ref:(\S+)', re.I)
_ID_B = re.compile(r'idCB2:.*?\(Nboite=\s*(\d+)\)', re.I)
_T4_ID = re.compile(r'transfert T3->T4 termin.*?idB=(\d+)', re.I)
_CREATE = re.compile(r"Cr\S*ation de la boite '([^']*)'\s+(.+?)(?:\s+x=|$)", re.I)
_ID_A = re.compile(r'\bIdA:(\d+)', re.I)
_ADDED = re.compile(r'AjoutBtT5\.idA(\d+)\.idB(-?\d+)', re.I)
_TRANSFER = re.compile(r"demande le transfert de (EA->T3|T3->T4).*?'([^']*)'", re.I)
_TO_T5 = re.compile(r"Demande le transfert \(physique\).*?T4 vers T5 '([^']*)'", re.I)
_DP_FINAL = re.compile(r'boite n\S*\s*(\d+)\s+manque la DP\s+(\d+)', re.I)
_DP_RENAME = re.compile(r'Change r\S*f derni\S* boite transf\S*.*?IdBdD:(\d+)\s+IdT5:(\d+).*?\)\s+(\S+)\s*->\s*(\S*\[MqDP\]\S*)', re.I)
_CAMERA_DP = re.compile(r'\bDP:(\d{1,2}(?:/\d{1,2})?/\d{4})\b')
_RAW_CAMERA = re.compile(r'idCB([12]):.*?PR<Soh>')
_RAW_CODE = re.compile(r'<Soh>\d+<Dc2>(.*?)<Dc2>')
_RAW_RECORD = re.compile(r'<Soh>(\d+)<Dc2>(.*?)<Dc2>')
_PHOTO_REQUEST = re.compile(r'idCB([12]):.*?demande prise photos',re.I)
_RELEVANT = re.compile(
    r'CB[12]:|EA->T3|T2->EA|T3->T4|Cr\S*ation de la boite|AjoutBtT5|'
    r'T4 vers T5|manque la DP|Change|DataArrival\[|version logiciel VBalpha:', re.I)

_CAMERA = 1
_TRANSFER_ROW = 2
_TO_T5_ROW = 4
_CREATE_ROW = 8
_ADDED_ROW = 16
_DP_FINAL_ROW = 32
_DP_RENAME_ROW = 64
_RAW_ROW = 128
_CONTROL_ROW = 256
_ALL_ROWS = 511


def _identification_candidates(text):
    # Les correspondances Unicode de re.I gardent le parcours complet.
    if not text.isascii():
        return _ALL_ROWS
    lower = text.lower()
    flags = 0
    if 'cb1:' in lower or 'cb2:' in lower:
        flags |= _CAMERA | _RAW_ROW
    if 'ea->t3' in lower or 't3->t4' in lower:
        flags |= _TRANSFER_ROW | _CONTROL_ROW
    if 't4 vers t5' in lower:
        flags |= _TO_T5_ROW
    if 'ation de la boite' in lower:
        flags |= _CREATE_ROW
    if 'ajoutbtt5' in lower:
        flags |= _ADDED_ROW
    if 'manque la dp' in lower:
        flags |= _DP_FINAL_ROW
    if 'change' in lower:
        flags |= _DP_RENAME_ROW
    if 'dataarrival[' in lower:
        flags |= _RAW_ROW
    if 't2->ea' in lower or 'version logiciel vbalpha:' in lower:
        flags |= _CONTROL_ROW
    return flags


def unknown_reference(reference: str) -> bool:
    return reference.upper().startswith(('ALPHA-INC', 'ALPHA-DET', 'ALPHA-DIF'))


@dataclass(eq=False)
class IdentificationCycle:
    first_line: int
    parent: IdentificationCycle | None = None
    codes: dict[str, list[int]] = field(default_factory=dict)
    reader_last_lines: dict[str, int] = field(default_factory=dict)
    reader_success_lines: dict[str, int] = field(default_factory=dict)
    reader_first_success_lines: dict[str, int] = field(default_factory=dict)
    unknown_readers: set[str] = field(default_factory=set)
    refusals: list[dict] = field(default_factory=list)
    references: set[str] = field(default_factory=set)
    reference: str = ''
    result_line: int = 0
    id_b: int = 0
    id_alpha: int = 0
    creation: tuple | None = None
    dp_attempts: list[dict] = field(default_factory=list)
    dp_recoveries: list[dict] = field(default_factory=list)
    dp_final: list[dict] = field(default_factory=list)
    raw_codes: list[dict] = field(default_factory=list)

    def root(self):
        if self.parent is not None:
            self.parent = self.parent.root()
            return self.parent
        return self


def identification_cycles(line_states, *, dp_output=None, progress_cb=None, camera_row_cb=None):
    """Les compteurs Hist_LectCB sont des preuves de lecture, pas des identites."""
    cycles = []
    slots = dict(ea=None, t3=None, t4=None, t5=None)
    aliases, by_b, by_a = {}, {}, {}
    pending_ea = None
    failed_ea = False
    attempts = {}
    pending_dp = None
    unassigned_dp = []
    raw_pending = {}
    candidate_flags = lru_cache(maxsize=2048)(_identification_candidates)
    try:
        total = len(line_states)
    except TypeError:
        total = 0
    if progress_cb is not None:
        progress_cb(0, total)

    def dp_proof(line, state, **values):
        return dict(line=line,time=state.timestamp,time_str=state.timestamp_str,**values)

    def attach_dp(cycle, proof):
        cycle=cycle.root()
        if proof['barcode'] not in cycle.references and not any(row['code']==proof['barcode'] for row in cycle.raw_codes):
            return False
        if not any(row['line']==proof['line'] for row in cycle.dp_final):cycle.dp_final.append(proof)
        return True

    def complete_ea():
        nonlocal pending_ea, failed_ea
        if pending_ea is not None:
            cycle = pending_ea.root()
            slots['t3'] = cycle
            if slots['ea'] is not None and slots['ea'].root() is cycle:
                slots['ea'] = None
            pending_ea = None
            failed_ea = False

    def new(line):
        cycle = IdentificationCycle(line)
        cycles.append(cycle)
        return cycle

    def current(slot, line):
        cycle = slots[slot]
        if cycle is None:
            cycle = slots[slot] = new(line)
        return cycle.root()

    def join(left, right):
        left, right = left.root(), right.root()
        if left is right:
            return left
        if ((left.id_b and right.id_b and left.id_b != right.id_b) or
                (left.id_alpha and right.id_alpha and left.id_alpha != right.id_alpha)):
            return left
        right.parent = left
        left.first_line = min(left.first_line, right.first_line)
        for reader, codes in right.codes.items():
            left.codes.setdefault(reader, []).extend(codes)
        for field_name in ('reader_last_lines', 'reader_success_lines'):
            destination = getattr(left, field_name)
            for reader, line in getattr(right, field_name).items():
                destination[reader] = max(destination.get(reader, 0), line)
        for reader, line in right.reader_first_success_lines.items():
            left.reader_first_success_lines[reader] = min(left.reader_first_success_lines.get(reader, line), line)
        left.unknown_readers.update(right.unknown_readers)
        left.refusals.extend(right.refusals)
        for key in ('dp_attempts','dp_recoveries','dp_final','raw_codes'):
            getattr(left,key).extend(getattr(right,key))
        left.references.update(right.references)
        if right.result_line > left.result_line:
            left.reference, left.result_line = right.reference, right.result_line
        left.id_b = left.id_b or right.id_b
        left.id_alpha = left.id_alpha or right.id_alpha
        left.creation = left.creation or right.creation
        return left

    def technical(ref):
        cycle = aliases.get(ref)
        if cycle is not None and cycle.root().creation is None:
            return cycle.root()
        return None

    for index, (line, text, state) in enumerate(line_states):
        if progress_cb is not None and index and index % 4096 == 0:
            progress_cb(index, total)
        if pending_dp and state.timestamp-pending_dp['time']>120:
            if not pending_dp.get('attributed'):unassigned_dp.append(pending_dp)
            pending_dp=None
        flags = candidate_flags(text)
        if not flags or (not text.isascii() and not _RELEVANT.search(text)):
            continue
        if camera_row_cb is not None and flags & _CAMERA:
            camera_row_cb(line, text, state)
        # Une reouverture du fichier de trace ne redemarre pas la machine.
        if 'version logiciel VBalpha:' in text:
            if pending_dp and not pending_dp.get('attributed'):unassigned_dp.append(pending_dp)
            pending_dp=None
            slots = dict.fromkeys(slots)
            aliases, by_b, by_a = {}, {}, {}
            pending_ea = None
            failed_ea = False
            attempts = {}
            raw_pending = {}

        if 'ERREUR transfert EA->T3' in text:
            failed_ea = True

        if 'le transfert (EA->T3) est termin' in text:
            complete_ea()
        if 'T2: Transfert de T2->EA termin' in text:
            complete_ea()
            slots['ea'] = None

        match = _TRANSFER.search(text) if flags & _TRANSFER_ROW else None
        if match:
            source, target = ('ea', 't3') if match[1].upper() == 'EA->T3' else ('t3', 't4')
            if source == 't3' and slots['t3'] is None:
                complete_ea()
            cycle = technical(match[2]) or slots[source] or new(line)
            if source == 'ea':
                if pending_ea is not None and pending_ea.root() is not cycle.root():
                    failed_ea = False
                pending_ea = cycle.root()
                slots['ea'] = pending_ea
            else:
                slots[target], slots[source] = cycle.root(), None

        match = _TO_T5.search(text) if flags & _TO_T5_ROW else None
        if match:
            slots['t5'] = technical(match[1]) or slots['t4'] or new(line)
            slots['t4'] = None

        match = _CB2_SOURCE.search(text) if flags & _CAMERA else None
        if match and slots['t3'] is None:
            # La ligne relie explicitement la lecture CB2 a la reference CB1.
            cycle = technical(match[1])
            ea = slots['ea']
            if cycle is None and ea is not None and ea.root().reference == match[1]:
                cycle = ea.root()
            if cycle is not None and cycle.creation is None:
                slots['t3'] = cycle
                if pending_ea is not None and pending_ea.root() is cycle:
                    pending_ea = None
                    failed_ea = False
                if ea is not None and ea.root() is cycle:
                    slots['ea'] = None

        if match and '[manque DP]' in text and slots['t3'] is not None:
            cycle=slots['t3'].root()
            cycle.dp_attempts.append(dp_proof(line,state,barcode=match[1],reader='CB2'))

        request=_PHOTO_REQUEST.search(text) if flags & _CAMERA else None
        if request:raw_pending['CB'+request[1]]={'time':state.timestamp,'codes':[]}
        raw_camera=_RAW_CAMERA.search(text) if flags & _CAMERA else None
        if raw_camera or ('DataArrival[' in text and 'R<Soh>' in text):
            for camera,code in _RAW_RECORD.findall(text):
                reader=('CB'+raw_camera[1] if raw_camera else
                        'CB2' if camera=='3' else 'CB1' if camera in {'1','2','4','5','6'} else '')
                pending=raw_pending.get(reader)
                if pending and 0<=state.timestamp-pending['time']<=120 and len(pending['codes'])<10:
                    pending['codes'].append(dp_proof(line,state,reader=reader,code=code[:256]))

        match = _HIST.search(text) if flags & _CAMERA else None
        if match:
            reader = 'CB' + match[1]
            slot = 'ea' if reader == 'CB1' else 't3'
            if reader == 'CB2' and slots['t3'] is None:
                complete_ea()
            cycle = current(slot, line)
            if (reader == 'CB1' and pending_ea is not None and not failed_ea
                    and cycle is pending_ea.root() and cycle.result_line):
                # La nouvelle tentative sera rattachee au meme passage si le produit ne change pas.
                previous = cycle
                cycle = slots[slot] = new(line)
                attempts[cycle] = previous
            code_count = int(match[2])
            cycle.codes.setdefault(reader, []).append(code_count)
            cycle.reader_last_lines[reader] = line
            if code_count:
                cycle.reader_success_lines[reader] = line
                cycle.reader_first_success_lines.setdefault(reader, line)
            pending=raw_pending.pop(reader,None)
            if pending and 0<=state.timestamp-pending['time']<=120:
                cycle.raw_codes.extend(pending['codes'][:max(0,10-len(cycle.raw_codes))])

        match = (_NON_ALPHATISABLE.search(text) or _REFUSED.search(text)) if flags & _CAMERA else None
        if match:
            reader = 'CB' + match[1]
            cycle = current('ea' if reader == 'CB1' else 't3', line)
            cycle.refusals.append(dict(line=line, barcode=match[2], reader=reader,
                time=state.timestamp, time_str=state.timestamp_str, technical_reference='',
                reason='non_alphatisable' if match.re is _NON_ALPHATISABLE else 'absent',
                reason_detail=match[3] if match.re is _NON_ALPHATISABLE else ''))

        match = _RESULT.search(text) if flags & _CAMERA else None
        if match:
            reader, ref = 'CB' + match[1], match[2]
            slot = 'ea' if reader == 'CB1' else 't3'
            cycle = current(slot, line)
            previous_attempt = attempts.pop(cycle, None) if reader == 'CB1' else None
            if previous_attempt is not None and previous_attempt.reference == ref:
                cycle = join(previous_attempt, cycle)
            previous = technical(ref) if unknown_reference(ref) else None
            if previous is not None and previous.creation is None:
                cycle = join(cycle, previous)
            cycle.reference, cycle.result_line = ref, line
            cycle.references.add(ref)
            dp=_CAMERA_DP.search(text)
            if dp and cycle.dp_attempts and not dp[1].endswith('/2099'):
                parts=dp[1].split('/')
                if 1<=int(parts[-2])<=12 and any(row['barcode']==ref for row in cycle.dp_attempts):
                    cycle.dp_recoveries.append(dp_proof(line,state,barcode=ref,reader=reader,dp=dp[1]))
            if unknown_reference(ref):
                aliases[ref] = cycle
                cycle.unknown_readers.add(reader)
            for refusal in cycle.refusals:
                if refusal['reader'] == reader and not refusal['technical_reference']:
                    refusal.update(technical_reference=ref, reference_line=line)
            slots[slot] = cycle

        match = _ID_B.search(text) if flags & _CAMERA else None
        if match:
            if slots['t3'] is None:
                complete_ea()
            cycle = current('t3', line)
            id_b = int(match[1])
            if cycle.id_b and cycle.id_b != id_b:
                cycle = new(line)
            if id_b in by_b and by_b[id_b].root().creation is None:
                cycle = join(cycle, by_b[id_b])
            cycle.id_b = id_b
            by_b[id_b] = slots['t3'] = cycle

        match = _T4_ID.search(text) if flags & _TRANSFER_ROW else None
        if match:
            id_b = int(match[1])
            cycle = by_b.get(id_b) or slots['t4'] or slots['t3'] or new(line)
            cycle = cycle.root()
            if id_b in by_b:
                cycle = join(cycle, by_b[id_b])
            cycle.id_b = id_b
            by_b[id_b] = slots['t4'] = cycle
            if slots['t3'] is not None and slots['t3'].root() is cycle:
                slots['t3'] = None

        match = _CREATE.search(text) if flags & _CREATE_ROW else None
        if match:
            ref, name = match[1], match[2]
            id_match = _ID_A.search(text)
            id_a = int(id_match[1]) if id_match else 0
            cycle = by_a.get(id_a) if id_a else None
            if cycle is not None and cycle.root().creation is not None:
                cycle=None
            candidates = [cycle, technical(ref), slots['t5'], slots['t4']]
            cycle = next((item.root() for item in candidates if item is not None and
                          item.root().creation is None), None)
            cycle = cycle or new(line)
            cycle = cycle.root()
            cycle.reference = ref
            cycle.id_alpha = id_a
            cycle.creation = (line, ref, state.timestamp, state.timestamp_str, name)
            if id_a:
                by_a[id_a] = cycle
            slots['t5'] = cycle
            if slots['t4'] is not None and slots['t4'].root() is cycle:
                slots['t4'] = None

        match = _ADDED.search(text) if flags & _ADDED_ROW else None
        if match:
            id_a, id_b = int(match[1]), int(match[2])
            cycle = by_a.get(id_a) or slots['t5'] or by_b.get(id_b) or new(line)
            cycle = cycle.root()
            if (id_b > 0 and id_b in by_b and
                    (by_b[id_b].root() is cycle or by_b[id_b].root().creation is None)):
                cycle = join(cycle, by_b[id_b])
            cycle.id_alpha = id_a
            by_a[id_a] = cycle
            if id_b > 0:
                cycle.id_b = id_b
                by_b[id_b] = cycle
            slots['t5'] = None

        final=_DP_FINAL.search(text) if flags & _DP_FINAL_ROW else None
        if final:
            if pending_dp and not pending_dp.get('attributed'):unassigned_dp.append(pending_dp)
            pending_dp=dp_proof(line,state,id_b=int(final[1]),barcode=final[2])
            cycle=by_b.get(int(final[1]))
            if cycle is not None and cycle.root().creation and attach_dp(cycle,pending_dp):
                pending_dp['attributed']=True
        rename=_DP_RENAME.search(text) if flags & _DP_RENAME_ROW else None
        if rename:
            id_a,id_t5=int(rename[1]),int(rename[2])
            proof=dp_proof(line,state,id_alpha=id_a,barcode=rename[3],technical_reference=rename[4])
            cycle=by_a.get(id_a)
            if id_a==id_t5 and cycle is not None and attach_dp(cycle,proof):
                if pending_dp and pending_dp['barcode']==rename[3] and 0<=line-pending_dp['line']<=10:
                    attach_dp(cycle,pending_dp)
                    pending_dp['attributed']=True
            else:unassigned_dp.append(proof)

    if pending_dp and not pending_dp.get('attributed'):unassigned_dp.append(pending_dp)
    if dp_output is not None:dp_output['unattributed']=unassigned_dp
    for attempt, previous in attempts.items():
        if not attempt.result_line:
            join(previous, attempt)
    result = [cycle for cycle in cycles if cycle.parent is None and
              (cycle.codes or cycle.refusals or cycle.result_line or cycle.id_b or cycle.creation)]
    if progress_cb is not None:
        progress_cb(total, total)
    return result
