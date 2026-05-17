from __future__ import annotations

from dataclasses import dataclass, field

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
    alias_to_key: dict[str, str],
    box: BoxInfo,
) -> ReferenceRecord:
    aliases = _aliases(box)
    existing_key = next((alias_to_key[a] for a in aliases if a in alias_to_key), None)
    desired_key = _best_key(box)
    key = existing_key or desired_key

    if key not in records:
        records[key] = ReferenceRecord(key=key)

    record = records[key]
    if desired_key != key and desired_key.startswith('A:') and desired_key not in records:
        records[desired_key] = record
        del records[key]
        record.key = desired_key
        key = desired_key
    elif desired_key != key and desired_key in records and records[desired_key] is not record:
        other = records[desired_key]
        _merge_records(other, record)
        del records[key]
        record = other
        key = desired_key

    for alias in aliases:
        alias_to_key[alias] = key
    return record


def _update_record(record: ReferenceRecord, box: BoxInfo, stage: str, frame: MachineState) -> None:
    record.barcode = record.barcode or box.barcode
    record.source_ref = record.source_ref or box.source_ref
    record.name = record.name or box.name
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
    alias_to_key: dict[str, str],
    event: MachineEvent,
) -> None:
    text = f'{event.title} {event.detail}'
    id_alpha = 0
    for token in ('IdA=', 'IdA:'):
        if token in text:
            tail = text.split(token, 1)[1]
            digits = ''.join(ch for ch in tail[:12] if ch.isdigit())
            if digits:
                id_alpha = int(digits)
                break
    if not id_alpha:
        return
    key = alias_to_key.get(f'A:{id_alpha}', f'A:{id_alpha}')
    record = records.setdefault(key, ReferenceRecord(key=key, id_alpha=id_alpha))
    alias_to_key[f'A:{id_alpha}'] = key
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
    alias_to_key: dict[str, str] = {}

    for frame in frames:
        for stage, box in (
            ('EA', frame.box_in_EA),
            ('T3', frame.box_on_T3),
            ('T4', frame.box_on_T4),
        ):
            if box is None:
                continue
            record = _record_for_box(records, alias_to_key, box)
            _update_record(record, box, stage, frame)
        for box in frame.boxes_on_T5:
            record = _record_for_box(records, alias_to_key, box)
            _update_record(record, box, 'T5', frame)

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
        if record.key != 'UNKNOWN' and (record.first_line or record.last_line)
    ]
    return sorted(unique_records, key=lambda r: (r.first_line or r.last_line, r.main_ref()))
