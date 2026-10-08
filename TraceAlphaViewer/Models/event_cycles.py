from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from Models.state import MachineEvent, MachineState


@dataclass
class BusinessEvent:
    line_num: int
    timestamp: float
    timestamp_str: str
    severity: str
    kind: str
    title: str
    detail: str = ""
    indent: int = 0
    header: bool = False


_DC = "<Dc2>"
_BOX_CREATE = re.compile(
    r"Cr\S*ation de la boite '([^']*)'\s+(.+?)\s+x=(\d+)"
    r"\s+\((\d+)x(\d+)x(\d+)\)\s+IdA:(\d+)",
    re.IGNORECASE,
)
_AJOUT_T5 = re.compile(r"AjoutBtT5\.idA(\d+)\.idB(-?\d+)", re.IGNORECASE)
_MAJ_T5_POS = re.compile(
    r"MAJ \(BUTEE-T5\) boite Id:(\d+) ref:(\S*).*?nvlle dim:\d+x(\d+)\s+X:(\d+)",
    re.IGNORECASE,
)
_MAJ_T5_MESURE = re.compile(
    r"MAJ \(APRES-MESURE-LARG\) bt IdA:(\d+) '([^']*)'.*?"
    r"nvlle lxH:(\d+)x(\d+) \[x(\d+)\] X:(\d+)"
    r"(?:.*?\(BdD:(\d+)x(\d+)x(\d+)\))?",
    re.IGNORECASE,
)
_DEPL_T5_ACTIVE = re.compile(r"DeplBtSurT5\.(-?\d+)mm\.Ref\S+\.idA(\d+)", re.IGNORECASE)
_BOX_REMOVE = re.compile(r"supp\. de T5 la boite Id:(\d+)\s+ref:(\S+)", re.IGNORECASE)
_BOX_REMOVE2 = re.compile(r"-suppression de la boite ID:(\d+)", re.IGNORECASE)
_BOX_REMOVE3 = re.compile(r"Suppr\. la boite IdA:(\d+)", re.IGNORECASE)
_T4_LENGTH = re.compile(
    r"longueur boite .*?\(BdD\)=(-?\d+).*?\(T2T\)=(-?\d+)"
    r".*?\(T4C\)=(-?\d+).*?\(T4T\)=(-?\d+).*?diffT4=(-?\d+)mm",
    re.IGNORECASE,
)
_T5_STATE = re.compile(r"\bT5:\s+(\S+).*?larg:(-?\d+).*?C9:(\d+).*?pT5:(-?\d+)")
_NBOITE = re.compile(r"\b(?:Nboite|idB)\s*=?\s*(\d+)", re.IGNORECASE)
_IDA = re.compile(r"\bIdA[:=]?(\d+)|\bidA(\d+)|\bId:(\d+)", re.IGNORECASE)
_BELT_RE = re.compile(r"\bT[0-5]\b", re.IGNORECASE)
_TOKEN_BELTS = {
    "C0": "T1",
    "C1": "T1",
    "C2": "T2",
    "C3": "T2",
    "C4": "T2",
    "CB1": "T2",
    "EA": "T2",
    "C5": "T3",
    "CB2": "T3",
    "C6": "T4",
    "LG": "T4",
    "PT4": "T4",
    "C9": "T5",
    "LZB": "T5",
    "PT5": "T5",
    "IDA": "T5",
    "BUTEE": "T5",
    "POUBELLE": "T5",
}


def _line_states(frames: list[MachineState]) -> list[tuple[int, str, MachineState]]:
    lines: list[tuple[int, str, MachineState]] = []
    seen: set[int] = set()
    for frame in frames:
        for line_num, text, *_ in frame.raw_lines:
            if line_num in seen:
                continue
            seen.add(line_num)
            lines.append((line_num, text, frame))
    return lines


def _short(text: str, limit: int = 34) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "."


def _record_identity(identity: dict[str, Any], *, id_a: int = 0, id_b: int = 0,
                     barcode: str = "", name: str = "", lot: str = "") -> None:
    if id_a:
        identity["id_alpha"] = id_a
    if id_b:
        identity["id_b"] = id_b
    if barcode:
        identity["barcode"] = barcode
    if name:
        identity["name"] = name
    if lot:
        identity["lot"] = lot


def _identity_label(identity: dict[str, Any]) -> str:
    parts: list[str] = []
    if identity.get("id_alpha"):
        parts.append(f"IdA={identity['id_alpha']}")
    if identity.get("id_b"):
        parts.append(f"idB={identity['id_b']}")
    if identity.get("name"):
        parts.append(_short(str(identity["name"]), 42))
    elif identity.get("barcode"):
        parts.append(str(identity["barcode"]))
    return " | ".join(parts) if parts else "boite"


def _iter_t5_list_records(text: str) -> list[list[str]]:
    records: list[list[str]] = []
    if "ALPHA:T5-LIST-PACK" not in text:
        return records
    for part in text.split("@"):
        if _DC not in part:
            continue
        fields = part.split(_DC)
        if fields and fields[0] == "":
            fields = fields[1:]
        if len(fields) >= 23 and fields[0].isdigit():
            records.append(fields)
    return records


def _business_event(
    line_num: int,
    state: MachineState,
    severity: str,
    kind: str,
    title: str,
    detail: str = "",
    indent: int = 1,
    header: bool = False,
) -> BusinessEvent:
    return BusinessEvent(
        line_num=line_num,
        timestamp=state.timestamp,
        timestamp_str=state.timestamp_str,
        severity=severity,
        kind=kind,
        title=title,
        detail=detail,
        indent=indent,
        header=header,
    )


def _ensure_cycle(
    cycles: dict[int, dict[str, Any]],
    id_a: int,
    line_num: int,
    state: MachineState,
) -> dict[str, Any]:
    cycle = cycles.get(id_a)
    if cycle is None:
        cycle = {
            "id_alpha": id_a,
            "identity": {"id_alpha": id_a},
            "steps": [],
            "first_line": line_num,
            "first_time": state.timestamp,
            "first_time_str": state.timestamp_str,
            "last_line": line_num,
            "last_time": state.timestamp,
            "last_time_str": state.timestamp_str,
            "measured": False,
            "butee": False,
            "first_list": False,
            "last_status": "",
            "no_space_count": 0,
        }
        cycles[id_a] = cycle
    else:
        cycle["last_line"] = max(int(cycle["last_line"]), line_num)
        cycle["last_time"] = max(float(cycle["last_time"]), state.timestamp)
        cycle["last_time_str"] = state.timestamp_str
    return cycle


def _add_step(
    cycle: dict[str, Any],
    line_num: int,
    state: MachineState,
    severity: str,
    title: str,
    detail: str = "",
) -> None:
    cycle["steps"].append(_business_event(line_num, state, severity, "T5", title, detail))
    cycle["last_line"] = max(int(cycle["last_line"]), line_num)
    cycle["last_time"] = max(float(cycle["last_time"]), state.timestamp)
    cycle["last_time_str"] = state.timestamp_str


def _build_t5_business_events(frames: list[MachineState]) -> list[BusinessEvent]:
    cycles: dict[int, dict[str, Any]] = {}
    active_id = 0
    pending_length: BusinessEvent | None = None

    for line_num, text, state in _line_states(frames):
        length_match = _T4_LENGTH.search(text)
        if length_match:
            pending_length = _business_event(
                line_num,
                state,
                "info",
                "T4",
                "Fin transfert T4 -> T5 / longueur connue",
                (
                    f"BdD={length_match.group(1)}mm, T4C={length_match.group(3)}mm, "
                    f"T4T={length_match.group(4)}mm, diff={length_match.group(5)}mm"
                ),
            )

        create_match = _BOX_CREATE.search(text)
        if create_match:
            id_a = int(create_match.group(7))
            active_id = id_a
            cycle = _ensure_cycle(cycles, id_a, line_num, state)
            _record_identity(
                cycle["identity"],
                id_a=id_a,
                barcode=create_match.group(1),
                name=create_match.group(2).strip(),
            )
            if pending_length:
                cycle["steps"].append(pending_length)
                pending_length = None
            _add_step(
                cycle,
                line_num,
                state,
                "info",
                "Creation BdD / arrivee T5",
                (
                    f"Ref={create_match.group(1)} ; BdD initiale="
                    f"{create_match.group(4)}x{create_match.group(5)}x{create_match.group(6)} ; "
                    f"X={create_match.group(3)}"
                ),
            )

        ajout_match = _AJOUT_T5.search(text)
        if ajout_match:
            id_a = int(ajout_match.group(1))
            id_b = int(ajout_match.group(2))
            active_id = id_a
            cycle = _ensure_cycle(cycles, id_a, line_num, state)
            _record_identity(cycle["identity"], id_a=id_a, id_b=id_b)
            _add_step(cycle, line_num, state, "info", "Ajout T5", f"Lien cycle IdA={id_a}, idB={id_b}")

        pos_match = _MAJ_T5_POS.search(text)
        if pos_match:
            id_a = int(pos_match.group(1))
            active_id = id_a
            cycle = _ensure_cycle(cycles, id_a, line_num, state)
            _record_identity(cycle["identity"], id_a=id_a, barcode=pos_match.group(2))
            cycle["butee"] = True
            _add_step(
                cycle,
                line_num,
                state,
                "info",
                "Butee T5 / hauteur",
                f"Hauteur={pos_match.group(3)}mm ; X={pos_match.group(4)}",
            )

        if "Hauteur de boite vue par laser T5" in text and active_id:
            cycle = _ensure_cycle(cycles, active_id, line_num, state)
            _add_step(cycle, line_num, state, "info", "Lecture hauteur T5", text.strip())

        if "Ph4-DEM-MESURE-ET-POS-REPOS" in text and active_id:
            cycle = _ensure_cycle(cycles, active_id, line_num, state)
            _add_step(cycle, line_num, state, "info", "Demande mesure largeur + position repos")

        if "mesure de largeur de boite sur T5 en cours" in text and active_id:
            cycle = _ensure_cycle(cycles, active_id, line_num, state)
            if not cycle.get("width_in_progress"):
                cycle["width_in_progress"] = True
                _add_step(cycle, line_num, state, "info", "Mesure largeur en cours", "Passage devant C9")

        t5_match = _T5_STATE.search(text)
        if t5_match and active_id and t5_match.group(3) == "1":
            cycle = _ensure_cycle(cycles, active_id, line_num, state)
            if not cycle.get("c9_seen"):
                cycle["c9_seen"] = True
                _add_step(
                    cycle,
                    line_num,
                    state,
                    "info",
                    "C9 detecte une boite",
                    f"Etat={t5_match.group(1)} ; larg={t5_match.group(2)} ; pT5={t5_match.group(4)}",
                )

        mesure_match = _MAJ_T5_MESURE.search(text)
        if mesure_match:
            id_a = int(mesure_match.group(1))
            active_id = id_a
            cycle = _ensure_cycle(cycles, id_a, line_num, state)
            _record_identity(cycle["identity"], id_a=id_a, barcode=mesure_match.group(2))
            cycle["measured"] = True
            _add_step(
                cycle,
                line_num,
                state,
                "info",
                "Mesure complete Alpha",
                (
                    f"Mesure={mesure_match.group(3)}x{mesure_match.group(4)}x{mesure_match.group(5)} ; "
                    f"X={mesure_match.group(6)}"
                ),
            )

        if "Ph4-POS-REPOS-OK" in text and active_id:
            cycle = _ensure_cycle(cycles, active_id, line_num, state)
            _add_step(cycle, line_num, state, "info", "Position repos OK", text.strip())

        for record in _iter_t5_list_records(text):
            id_a = int(record[0])
            status = record[1]
            cycle = _ensure_cycle(cycles, id_a, line_num, state)
            _record_identity(
                cycle["identity"],
                id_a=id_a,
                barcode=record[2],
                name=record[3],
                lot=record[8] if len(record) > 8 else "",
            )
            cycle["last_status"] = status
            cycle["last_line"] = line_num
            cycle["last_time"] = state.timestamp
            cycle["last_time_str"] = state.timestamp_str
            if not cycle.get("first_list") or cycle.get("last_list_status") != status:
                cycle["first_list"] = True
                cycle["last_list_status"] = status
                _add_step(
                    cycle,
                    line_num,
                    state,
                    "info" if status == "Y" else "warning",
                    "Liste robot T5",
                    f"Statut={status} ; dim={record[4]}x{record[5]}x{record[6]} ; X={record[13]} ; goulotte={record[19]}",
                )

        remove_match = _BOX_REMOVE.search(text) or _BOX_REMOVE2.search(text) or _BOX_REMOVE3.search(text)
        if remove_match:
            id_a = int(remove_match.group(1))
            cycle = _ensure_cycle(cycles, id_a, line_num, state)
            _add_step(cycle, line_num, state, "info", "Suppression T5 / prise robot ou vidage", text.strip())

        depl_match = _DEPL_T5_ACTIVE.search(text)
        if depl_match:
            id_a = int(depl_match.group(2))
            active_id = id_a
            cycle = _ensure_cycle(cycles, id_a, line_num, state)
            _add_step(cycle, line_num, state, "info", "Deplacement T5", f"Delta={depl_match.group(1)}mm")

        if "pas assez de place" in text.lower() and active_id:
            cycle = _ensure_cycle(cycles, active_id, line_num, state)
            cycle["no_space_count"] = int(cycle.get("no_space_count", 0)) + 1
            if not cycle.get("no_space_reported"):
                cycle["no_space_reported"] = True
                _add_step(cycle, line_num, state, "warning", "Place T5 insuffisante", text.strip())

    output: list[BusinessEvent] = []
    for cycle in sorted(cycles.values(), key=lambda item: int(item["first_line"])):
        steps = sorted(cycle["steps"], key=lambda event: (event.line_num, event.title))
        if not steps:
            continue
        identity = _identity_label(cycle["identity"])
        header_severity = "warning" if not cycle.get("measured") and cycle.get("butee") else "info"
        output.append(_business_event(
            int(cycle["first_line"]),
            frames[0] if frames else MachineState(),
            header_severity,
            "T5",
            identity,
            "Cycle T5",
            indent=0,
            header=True,
        ))
        output[-1].timestamp = float(cycle["first_time"])
        output[-1].timestamp_str = str(cycle["first_time_str"])
        output.extend(steps)
        if cycle.get("butee") and not cycle.get("measured"):
            duration = int(float(cycle["last_time"]) - float(cycle["first_time"]))
            output.append(BusinessEvent(
                line_num=int(cycle["last_line"]),
                timestamp=float(cycle["last_time"]),
                timestamp_str=str(cycle["last_time_str"]),
                severity="warning",
                kind="T5",
                title="Mesure largeur absente",
                detail=(
                    f"Boite non validee APRES-MESURE-LARG ; duree observee {duration}s ; "
                    f"pas assez de place={int(cycle.get('no_space_count', 0))}"
                ),
                indent=1,
            ))
    return output


def _event_belts(event: MachineEvent) -> set[str]:
    text = f"{event.kind} {event.title} {event.detail}".upper()
    belts = {match.group(0).upper() for match in _BELT_RE.finditer(text)}
    for token, belt in _TOKEN_BELTS.items():
        if token in text:
            belts.add(belt)
    return belts


def _build_identity_index(frames: list[MachineState]) -> dict[str, dict[int, dict[str, Any]]]:
    index: dict[str, dict[int, dict[str, Any]]] = {"ida": {}, "idb": {}}
    for frame in frames:
        boxes = [frame.box_in_EA, frame.box_on_T3, frame.box_on_T4, *frame.boxes_on_T5]
        for box in boxes:
            if not box:
                continue
            identity: dict[str, Any] = {
                "id_alpha": box.id_alpha,
                "id_b": box.id_b,
                "barcode": box.barcode or box.source_ref,
                "name": box.name or box.source_ref,
                "lot": box.lot,
            }
            if box.id_alpha:
                index["ida"][box.id_alpha] = {**index["ida"].get(box.id_alpha, {}), **identity}
            if box.id_b:
                index["idb"][box.id_b] = {**index["idb"].get(box.id_b, {}), **identity}
    return index


def _identity_from_text(text: str, index: dict[str, dict[int, dict[str, Any]]]) -> str:
    for match in _IDA.finditer(text):
        raw = match.group(1) or match.group(2) or match.group(3)
        if not raw:
            continue
        identity = index["ida"].get(int(raw))
        if identity:
            return _identity_label(identity)
    match = _NBOITE.search(text)
    if match:
        identity = index["idb"].get(int(match.group(1)))
        if identity:
            return _identity_label(identity)
    return ""


def _build_simple_belt_events(
    frames: list[MachineState],
    events: list[MachineEvent],
    belt: str,
) -> list[BusinessEvent]:
    index = _build_identity_index(frames)
    rows: list[BusinessEvent] = []
    for event in events:
        if belt not in _event_belts(event):
            continue
        label = _identity_from_text(f"{event.title} {event.detail}", index)
        title = event.title if not label or label in event.title else f"{event.title} | {label}"
        rows.append(BusinessEvent(
            line_num=event.line_num,
            timestamp=event.timestamp,
            timestamp_str=event.timestamp_str,
            severity=event.severity,
            kind=event.kind,
            title=title,
            detail=event.detail,
            indent=0,
        ))
    return rows


def build_business_events(
    frames: list[MachineState],
    events: list[MachineEvent],
    belt: str,
) -> list[BusinessEvent]:
    if belt == "T5":
        return _build_t5_business_events(frames)
    return _build_simple_belt_events(frames, events, belt)
