from __future__ import annotations

from dataclasses import dataclass, field
import re

from Models.state import BoxInfo, MachineEvent, MachineState


@dataclass
class ReferenceRecord:
    key: str
    barcode: str = ""
    source_ref: str = ""
    name: str = ""
    id_b: int = 0
    id_alpha: int = 0
    first_line: int = 0
    last_line: int = 0
    first_time_str: str = ""
    last_time_str: str = ""
    stages: set[str] = field(default_factory=set)
    event_count: int = 0
    taken_by_robot: bool = False
    robot_line: int = 0
    robot_time_str: str = ""

    def main_ref(self) -> str:
        if self.barcode:
            return self.barcode
        if self.source_ref:
            return self.source_ref
        if self.id_alpha:
            return f'IdA:{self.id_alpha}'
        if self.id_b:
            return f'idB:{self.id_b}'
        return self.key

    def label(self) -> str:
        title = self.name or self.source_ref or self.barcode or self.key
        ids = []
        if self.id_b:
            ids.append(f'idB:{self.id_b}')
        if self.id_alpha:
            ids.append(f'IdA:{self.id_alpha}')
        return f'{title}  {" ".join(ids)}'.strip()

    def stages_label(self) -> str:
        order = ['EA', 'T3', 'T4', 'T5', 'ROBOT']
        return '>'.join(stage for stage in order if stage in self.stages) or '-'

    def is_unknown(self) -> bool:
        text = f'{self.barcode} {self.source_ref} {self.name}'.upper()
        return (
            'ALPHA-INC' in text
            or 'ALPHA-DET' in text
            or 'UNKNOW' in text
        )


def _aliases(box: BoxInfo) -> list[str]:
    aliases: list[str] = []
    if box.id_alpha:
        aliases.append(f'A:{box.id_alpha}')
    if box.id_b:
        aliases.append(f'B:{box.id_b}')
    if box.barcode:
        aliases.append(f'C:{box.barcode}')
    if box.source_ref:
        aliases.append(f'R:{box.source_ref}')
        if box.source_ref != box.barcode:
            aliases.append(f'C:{box.source_ref}')
    return aliases


def _best_key(box: BoxInfo) -> str:
    aliases = _aliases(box)
    return aliases[0] if aliases else 'UNKNOWN'


def _merge_records(target: ReferenceRecord, source: ReferenceRecord) -> None:
    target.barcode = target.barcode or source.barcode
    target.source_ref = target.source_ref or source.source_ref
    target.name = target.name or source.name
    target.id_b = target.id_b or source.id_b
    target.id_alpha = target.id_alpha or source.id_alpha
    if source.first_line and (not target.first_line or source.first_line < target.first_line):
        target.first_line = source.first_line
        target.first_time_str = source.first_time_str
    if source.last_line and source.last_line > target.last_line:
        target.last_line = source.last_line
        target.last_time_str = source.last_time_str
    target.stages.update(source.stages)
    target.event_count += source.event_count
    if source.taken_by_robot:
        target.taken_by_robot = True
        target.robot_line = source.robot_line
        target.robot_time_str = source.robot_time_str


def _record_for_box(
    records: dict[str, ReferenceRecord],
    alias_to_key: dict[str, set[str]],
    box: BoxInfo,
    active_keys: set[str] | None = None,
) -> ReferenceRecord:
    aliases = _aliases(box)
    key = None
    for alias in aliases:
        candidates = []
        candidate_keys = alias_to_key.get(alias, set())
        if alias.startswith(('C:', 'R:')) and active_keys is not None:
            candidate_keys = candidate_keys & active_keys
        for candidate_key in candidate_keys:
            candidate = records[candidate_key]
            if box.id_alpha and candidate.id_alpha and box.id_alpha != candidate.id_alpha:
                continue
            if (box.id_b and candidate.id_b and box.id_b != candidate.id_b
                    and not (box.id_alpha and box.id_alpha == candidate.id_alpha)):
                continue
            if alias.startswith(('C:', 'R:')):
                if not box.id_alpha and not box.id_b and (candidate.id_alpha or candidate.id_b):
                    continue
                if candidate.id_alpha and not box.id_alpha:
                    continue
            candidates.append(candidate_key)
        if len(candidates) == 1:
            key = candidates[0]
            break
    if key is None:
        base = _best_key(box)
        key = base
        suffix = 2
        while key in records:
            key = f'{base}#{suffix}'
            suffix += 1
        records[key] = ReferenceRecord(key=key)
    record = records[key]
    for alias in aliases:
        alias_to_key.setdefault(alias, set()).add(key)
    return record


def _update_record(record: ReferenceRecord, box: BoxInfo, stage: str, frame: MachineState) -> None:
    record.barcode = box.barcode or record.barcode
    record.source_ref = record.source_ref or box.source_ref
    record.name = box.name or record.name
    record.id_b = record.id_b or box.id_b
    record.id_alpha = record.id_alpha or box.id_alpha
    if frame.line_num and (not record.first_line or frame.line_num < record.first_line):
        record.first_line = frame.line_num
        record.first_time_str = frame.timestamp_str
    if frame.line_num and frame.line_num >= record.last_line:
        record.last_line = frame.line_num
        record.last_time_str = frame.timestamp_str
    record.stages.add(stage)


def _mark_robot_take(
    records: dict[str, ReferenceRecord],
    alias_to_key: dict[str, set[str]],
    event: MachineEvent,
) -> None:
    text = f'{event.title} {event.detail}'
    match = re.search(r'\bIdA\s*[:=]\s*(\d+)\b', text)
    id_alpha = int(match.group(1)) if match else 0
    if not id_alpha:
        return
    candidates = alias_to_key.get(f'A:{id_alpha}', set())
    key = max(candidates, key=lambda k: records[k].last_line) if candidates else f'A:{id_alpha}'
    record = records.setdefault(key, ReferenceRecord(key=key, id_alpha=id_alpha))
    alias_to_key.setdefault(f'A:{id_alpha}', set()).add(key)
    record.id_alpha = record.id_alpha or id_alpha
    record.stages.add('ROBOT')
    record.taken_by_robot = True
    record.robot_line = event.line_num
    record.robot_time_str = event.timestamp_str
    if not record.first_line:
        record.first_line = event.line_num
        record.first_time_str = event.timestamp_str
    record.last_line = max(record.last_line, event.line_num)
    record.last_time_str = event.timestamp_str
    record.event_count += 1


def build_reference_records(
    frames: list[MachineState],
    events: list[MachineEvent],
) -> list[ReferenceRecord]:
    records: dict[str, ReferenceRecord] = {}
    alias_to_key: dict[str, set[str]] = {}
    active_keys: set[str] = set()

    for frame in frames:
        current_keys: set[str] = set()
        for stage, box in (
            ('EA', frame.box_in_EA),
            ('T3', frame.box_on_T3),
            ('T4', frame.box_on_T4),
        ):
            if box is None:
                continue
            record = _record_for_box(records, alias_to_key, box, active_keys | current_keys)
            _update_record(record, box, stage, frame)
            current_keys.add(record.key)
        for box in frame.boxes_on_T5:
            record = _record_for_box(records, alias_to_key, box, active_keys | current_keys)
            _update_record(record, box, 'T5', frame)
            current_keys.add(record.key)
        active_keys = current_keys

    for event in events:
        if event.kind == 'BOITE' and (
            event.title.startswith('Robot prend')
            or event.title.startswith('Robot supprime')
            or event.title.startswith('Boite retiree de T5')
            or event.title.startswith('Suppression boite IdA')
        ):
            _mark_robot_take(records, alias_to_key, event)

    unique_records = list({id(record): record for record in records.values()}.values())
    unique_records = [
        record for record in unique_records
        if record.key.split('#', 1)[0] != 'UNKNOWN' and (record.first_line or record.last_line)
    ]
    return sorted(unique_records, key=lambda r: (r.first_line or r.last_line, r.main_ref()))
