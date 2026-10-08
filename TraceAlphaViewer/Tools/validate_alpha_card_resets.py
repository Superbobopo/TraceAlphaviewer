from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "TraceAlphaViewer"))

from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload
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


def main() -> None:
    reset_path = ROOT / "TraceAlphaViewer" / "TracAlpha1_002centre.old"
    _check(reset_path.exists(), f"Trace absente: {reset_path}")
    frames, incidents = _diagnostics_for(reset_path)
    resets = [item for item in incidents if item.code == "ALPHA_CARD_RESET"]
    _check(len(resets) == 1, "une synthese reset carte Alpha attendue")
    reset = resets[0]
    _check(reset.severity == "error", "le reset confirme doit etre critique")
    _check(reset.count == 1, "la suite 0, 1, 2 mn doit compter comme un seul reset")
    _check("1832 -> 0 mn" in reset.summary, "chute 1832 -> 0 absente")
    _check("L.46026" in reset.summary, "ligne de reset absente")
    details = " ".join(reset.probable_causes + reset.checks).lower()
    for word in ("cubestop", "balance", "shunt"):
        _check(word in details, f"controle {word} absent")

    payload = build_report_payload(incidents, frames=frames)
    group = next(group for group in payload["groups"] if group["code"] == "ALPHA_CARD_RESET")
    _check(group["field_severity"] == "error", "criticite terrain reset incorrecte")
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
