from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "TraceAlphaViewer"))

from Models.diagnostic import build_diagnostics, _build_alpha_card_reset_incident
from Models.diagnostic_report import build_report_payload
from Models.state import MachineState
from Parser.trace_parser import parse_file


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _events_for(frames) -> list:
    events = []
    seen = set()
    for frame in frames:
        for event in frame.events:
            key = (event.line_num, event.kind, event.title)
            if key not in seen:
                seen.add(key)
                events.append(event)
    return events


def _diagnostics_for(path: Path):
    frames = parse_file(str(path), min_dt=0.0)
    incidents = build_diagnostics(frames, _events_for(frames))
    return frames, incidents


def _validate_daily_threshold() -> None:
    def check_case(reset_times, expected, maximum, month_rollover=False):
        frames = []
        for moment in reset_times:
            for seconds, uptime in ((moment - 1, 100), (moment, 0), (moment + 60, 1), (moment + 120, 2)):
                line = len(frames) + 1
                day_seconds = seconds % 86400
                clock = f'{day_seconds // 3600:02d}:{day_seconds // 60 % 60:02d}:{day_seconds % 60:02d}'
                timestamp = seconds - (31 * 86400 if month_rollover and seconds >= 86400 else 0)
                frames.append(MachineState(timestamp=timestamp, timestamp_str=clock, line_num=line,
                    raw_lines=[(line, f'Temps depuis RESET carte ALPHA : {uptime} mn')]))
        lines = [(frame.line_num, frame.raw_lines[0][1], frame) for frame in frames]
        incident = _build_alpha_card_reset_incident(lines)[0]
        _check(incident.count == len(reset_times), 'les releves bas doivent rester un seul reset')
        _check(incident.severity == expected, f'gravite incorrecte pour {reset_times}')
        _check(incident.metrics['max_daily_count'] == maximum, 'maximum journalier incorrect')
        payload = build_report_payload([incident], frames)
        group = next(group for group in payload['groups'] if group['code'] == 'ALPHA_CARD_RESET')
        _check(group['field_severity'] == expected, 'gravite du rapport differente du viewer')

    check_case([3600], 'warning', 1)
    check_case([3600, 7200], 'warning', 2)
    check_case([3600, 7200, 10800], 'error', 3)
    check_case([3600, 90000, 176400], 'warning', 1)
    check_case([82800, 86400, 90000], 'warning', 2)
    check_case([82800, 86400, 90000, 93600], 'error', 3)
    check_case([82800, 86400, 90000], 'warning', 2, month_rollover=True)
    check_case([82800, 86400, 90000, 93600], 'error', 3, month_rollover=True)
    print('Validation seuil journalier resets (donnees fictives): OK')


def main() -> None:
    _validate_daily_threshold()
    reset_path = ROOT / "TraceAlphaViewer" / "TracAlpha1_002centre.old"
    if not reset_path.exists():
        print(f"Trace absente, controle terrain ignore: {reset_path}")
        return
    frames, incidents = _diagnostics_for(reset_path)
    resets = [item for item in incidents if item.code == "ALPHA_CARD_RESET"]
    _check(len(resets) == 1, "une synthese reset carte Alpha attendue")
    reset = resets[0]
    _check(reset.severity == "warning", "un reset isole doit rester en alerte")
    _check(reset.count == 1, "la suite 0, 1, 2 mn doit compter comme un seul reset")
    _check("1832 -> 0 mn" in reset.summary, "chute 1832 -> 0 absente")
    _check("L.46026" in reset.summary, "ligne de reset absente")
    details = " ".join(reset.probable_causes + reset.checks).lower()
    for word in ("cubestop", "balance", "shunt"):
        _check(word in details, f"controle {word} absent")

    payload = build_report_payload(incidents, frames=frames)
    group = next(group for group in payload["groups"] if group["code"] == "ALPHA_CARD_RESET")
    _check(group["field_severity"] == "warning", "criticite terrain reset incorrecte")
    _check("1 reset(s) sur" in group["affected_label"], "metrique reset/duree absente")
    _check("boite" not in group["affected_label"].lower(), "ratio boites trompeur sur reset")

    stable_path = ROOT / "TraceAlphaViewer" / "TracAlpha1centre.txt"
    if stable_path.exists():
        _, stable_incidents = _diagnostics_for(stable_path)
        stable = next(item for item in stable_incidents if item.code == "ALPHA_CARD_RESET")
        _check(stable.severity == "info", "trace stable signalee en anomalie")
        _check(stable.count == 0, "reset invente sur trace stable")
        _check("0 reset carte Alpha" in stable.summary, "bilan zero reset absent")

    print("Validation resets carte Alpha: OK")


if __name__ == "__main__":
    main()
