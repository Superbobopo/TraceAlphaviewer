from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "TraceAlphaViewer"))

from Models.diagnostic import build_diagnostics
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
            if key in seen:
                continue
            seen.add(key)
            events.append(event)
    return sorted(events, key=lambda event: (event.line_num, event.kind, event.title))


def _diagnostics_for(path: Path):
    frames = parse_file(str(path), min_dt=0.0)
    events = _events_for(frames)
    return frames, build_diagnostics(frames, events)


def main() -> None:
    nominal_path = ROOT / "TraceAlphaViewer" / "TracAlpha1.txt"
    if nominal_path.exists():
        frames, incidents = _diagnostics_for(nominal_path)
        positions = {frame.cubestop_position for frame in frames if frame.cubestop_present}
        _check("BAS" in positions, "CubeStop BAS absent sur trace nominale")
        _check("HAUT" in positions, "CubeStop HAUT absent sur trace nominale")
        _check(
            not any(incident.code == "CUBESTOP_C4_BLOCKED" for incident in incidents),
            "faux positif CUBESTOP_C4_BLOCKED sur trace nominale",
        )

    blocked_path = ROOT / "TraceAlphaViewer" / "TracAlpha1_017.old"
    if blocked_path.exists():
        _, incidents = _diagnostics_for(blocked_path)
        cubestop = [
            incident for incident in incidents
            if incident.code == "CUBESTOP_C4_BLOCKED"
        ]
        _check(cubestop, "diagnostic CUBESTOP_C4_BLOCKED absent")
        incident = cubestop[0]
        _check(incident.severity == "error", "diagnostic CubeStop non critique")
        joined = " ".join([
            incident.title,
            incident.summary,
            incident.symptom,
            " ".join(incident.probable_causes),
            " ".join(incident.checks),
        ])
        for token in ("CubeStop", "C4", "C5", "EA->T3"):
            _check(token in joined, f"diagnostic CubeStop incomplet: {token}")
        _check(any(line >= 235970 for line in incident.event_lines), "preuve ligne blocage C4 absente")

    no_cubestop_path = ROOT / "TraceAlphaViewer" / "TracAlpha1_005.old"
    if no_cubestop_path.exists():
        frames, incidents = _diagnostics_for(no_cubestop_path)
        _check(
            not any(frame.cubestop_present for frame in frames),
            "CubeStop affiche present malgre CubeStop:N",
        )
        _check(
            not any(incident.code == "CUBESTOP_C4_BLOCKED" for incident in incidents),
            "diagnostic CubeStop present sur trace CubeStop:N",
        )

    print("Diagnostic CubeStop: validation OK")


if __name__ == "__main__":
    main()
