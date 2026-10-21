"""Suit les passages physiques pour distinguer lecture et reference absente."""
from __future__ import annotations

from dataclasses import dataclass, field
import re


_HIST = re.compile(r'\bCB([12]):\s+ajout Hist_LectCB .*?(\d+)code\(s\) lu\(s\)', re.I)
_RESULT = re.compile(r'idCB([12]):\s*-->\s*R\S*f:(\S+)', re.I)
_REFUSED = re.compile(
    r"idCB([12]):\s+la r\S*f\.\s+(\d+)\s+n'est pas dans les tables.*"
    r'pas dans BdD,\s*refus de cr\S*ation dans param', re.I)
_CB2_SOURCE = re.compile(r'idCB2:.*?idCB1\.Ref:(\S+)', re.I)
_ID_B = re.compile(r'idCB2:.*?\(Nboite=\s*(\d+)\)', re.I)
_T4_ID = re.compile(r'transfert T3->T4 termin.*?idB=(\d+)', re.I)
_CREATE = re.compile(r"Cr\S*ation de la boite '([^']*)'\s+(.+?)(?:\s+x=|$)", re.I)
_ID_A = re.compile(r'\bIdA:(\d+)', re.I)
_ADDED = re.compile(r'AjoutBtT5\.idA(\d+)\.idB(-?\d+)', re.I)
_TRANSFER = re.compile(r"demande le transfert de (EA->T3|T3->T4).*?'([^']*)'", re.I)
_TO_T5 = re.compile(r"Demande le transfert \(physique\).*?T4 vers T5 '([^']*)'", re.I)


def unknown_reference(reference: str) -> bool:
    return reference.upper().startswith(('ALPHA-INC', 'ALPHA-DET', 'ALPHA-DIF'))


@dataclass(eq=False)
class IdentificationCycle:
    first_line: int
    parent: IdentificationCycle | None = None
    codes: dict[str, list[int]] = field(default_factory=dict)
    unknown_readers: set[str] = field(default_factory=set)
    refusals: list[dict] = field(default_factory=list)
    references: set[str] = field(default_factory=set)
    reference: str = ''
    result_line: int = 0
    id_b: int = 0
    id_alpha: int = 0
    creation: tuple | None = None

    def root(self):
        if self.parent is not None:
            self.parent = self.parent.root()
            return self.parent
        return self


def identification_cycles(line_states):
    """Les compteurs Hist_LectCB sont des preuves de lecture, pas des identites."""
    cycles = []
    slots = dict(ea=None, t3=None, t4=None, t5=None)
    aliases, by_b, by_a = {}, {}, {}

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
        left.unknown_readers.update(right.unknown_readers)
        left.refusals.extend(right.refusals)
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

    for line, text, state in line_states:
        # Une reouverture du fichier de trace ne redemarre pas la machine.
        if 'version logiciel VBalpha:' in text:
            slots = dict.fromkeys(slots)
            aliases, by_b, by_a = {}, {}, {}

        match = _TRANSFER.search(text)
        if match:
            source, target = ('ea', 't3') if match[1].upper() == 'EA->T3' else ('t3', 't4')
            cycle = technical(match[2]) or slots[source] or new(line)
            slots[target], slots[source] = cycle.root(), None

        match = _TO_T5.search(text)
        if match:
            slots['t5'] = technical(match[1]) or slots['t4'] or new(line)
            slots['t4'] = None

        match = _CB2_SOURCE.search(text)
        if match and slots['t3'] is None:
            # La ligne relie explicitement la lecture CB2 a la reference CB1.
            cycle = technical(match[1])
            ea = slots['ea']
            if cycle is None and ea is not None and ea.root().reference == match[1]:
                cycle = ea.root()
            if cycle is not None and cycle.creation is None:
                slots['t3'] = cycle
                if ea is not None and ea.root() is cycle:
                    slots['ea'] = None

        match = _HIST.search(text)
        if match:
            reader = 'CB' + match[1]
            slot = 'ea' if reader == 'CB1' else 't3'
            cycle = current(slot, line)
            if reader == 'CB1' and reader in cycle.codes and cycle.result_line:
                cycle = slots[slot] = new(line)
            cycle.codes.setdefault(reader, []).append(int(match[2]))

        match = _REFUSED.search(text)
        if match:
            reader = 'CB' + match[1]
            cycle = current('ea' if reader == 'CB1' else 't3', line)
            cycle.refusals.append(dict(line=line, barcode=match[2], reader=reader,
                time=state.timestamp, time_str=state.timestamp_str, technical_reference=''))

        match = _RESULT.search(text)
        if match:
            reader, ref = 'CB' + match[1], match[2]
            slot = 'ea' if reader == 'CB1' else 't3'
            cycle = current(slot, line)
            previous = technical(ref) if unknown_reference(ref) else None
            if previous is not None and previous.creation is None:
                cycle = join(cycle, previous)
            cycle.reference, cycle.result_line = ref, line
            cycle.references.add(ref)
            if unknown_reference(ref):
                aliases[ref] = cycle
                cycle.unknown_readers.add(reader)
            for refusal in cycle.refusals:
                if refusal['reader'] == reader and not refusal['technical_reference']:
                    refusal.update(technical_reference=ref, reference_line=line)
            slots[slot] = cycle

        match = _ID_B.search(text)
        if match:
            cycle = current('t3', line)
            id_b = int(match[1])
            if cycle.id_b and cycle.id_b != id_b:
                cycle = new(line)
            if id_b in by_b and by_b[id_b].root().creation is None:
                cycle = join(cycle, by_b[id_b])
            cycle.id_b = id_b
            by_b[id_b] = slots['t3'] = cycle

        match = _T4_ID.search(text)
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

        match = _CREATE.search(text)
        if match:
            ref, name = match[1], match[2]
            id_match = _ID_A.search(text)
            id_a = int(id_match[1]) if id_match else 0
            cycle = by_a.get(id_a) if id_a else None
            candidates = [cycle, technical(ref), slots['t5'], slots['t4']]
            cycle = next((item.root() for item in candidates if item is not None and
                          (item.root().creation is None or (id_a and item.root().id_alpha == id_a))), None)
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

        match = _ADDED.search(text)
        if match:
            id_a, id_b = int(match[1]), int(match[2])
            cycle = by_a.get(id_a) or slots['t5'] or by_b.get(id_b) or new(line)
            cycle = cycle.root()
            if id_b > 0 and id_b in by_b:
                cycle = join(cycle, by_b[id_b])
            cycle.id_alpha = id_a
            by_a[id_a] = cycle
            if id_b > 0:
                cycle.id_b = id_b
                by_b[id_b] = cycle
            slots['t5'] = None

    return [cycle for cycle in cycles if cycle.parent is None and
            (cycle.codes or cycle.refusals or cycle.result_line or cycle.id_b or cycle.creation)]
