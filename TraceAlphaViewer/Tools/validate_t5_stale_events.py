from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "TraceAlphaViewer"))

from Models.diagnostic import build_diagnostics
from Models.diagnostic_report import build_report_payload
from Models.event_cycles import build_business_events
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


def main() -> None:
    trace_path = ROOT / "TraceAlphaViewer" / "TracAlpha1ortiz.txt"
    if not trace_path.exists():
        print(f"Trace absente, controle ignore: {trace_path}")
        return

    frames = parse_file(str(trace_path), min_dt=0.0)
    events = _events_for(frames)
    incidents = build_diagnostics(frames, events)

    stale = [
        incident for incident in incidents
        if incident.code == "T5_STALE_UNMEASURED_BOX"
    ]
    _check(stale, "diagnostic T5_STALE_UNMEASURED_BOX absent")
    root = next((incident for incident in stale if "73111" in incident.summary), None)
    _check(root is not None, "diagnostic 73111 absent")
    _check(root.severity == "error", "diagnostic 73111 non critique")
    for token in ("73111", "HALDOL", "73127", "pas assez de place", "vidage T5"):
        _check(token in root.summary, f"resume 73111 incomplet: {token}")

    rows = build_business_events(frames, events, "T5")
    joined = "\n".join(f"{row.title} {row.detail}" for row in rows)
    _check("IdA=73111" in joined and "HALDOL" in joined, "cycle T5 73111 absent")
    _check("IdA=73126" in joined and "Mesure complete Alpha" in joined, "cycle complet 73126 absent")
    _check("IdA=73127" in joined and "Mesure largeur absente" in joined, "cycle incomplet 73127 absent")

    payload = build_report_payload(incidents, frames=frames)
    report_group = next(
        (group for group in payload["groups"] if group.get("code") == "T5_STALE_UNMEASURED_BOX"),
        None,
    )
    _check(report_group is not None, "groupe rapport T5_STALE_UNMEASURED_BOX absent")
    label = str(report_group.get("affected_label", ""))
    _check("566/658" not in label, "libelle rapport T5 bloquant trompeur")
    _check("2 boite(s) T5 non mesuree(s)" in label, "nombre de boites T5 non mesurees absent")
    _check("566 messages" in label, "nombre de messages de blocage T5 absent")
    _check("73111" in label and "73127" in label, "IdA bloquantes absentes du libelle rapport")
    business = "\n".join(str(line) for line in report_group.get("business_lines", []))
    _check("IdA 73111: 335 messages" in business, "detail 73111 absent du rapport")
    _check("IdA 73127: 231 messages" in business, "detail 73127 absent du rapport")

    print("Diagnostic T5 stale/events: validation OK")


if __name__ == "__main__":
    main()
