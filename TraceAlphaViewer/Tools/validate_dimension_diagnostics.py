from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "TraceAlphaViewer"))

from Models.diagnostic import _dimension_finding_code, build_diagnostics
from Models.state import BoxInfo
from Parser.trace_parser import _classify_alpha_measurement, parse_file


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _check_rules() -> None:
    expected = (76, 62, 110)
    _check(_dimension_finding_code((76, 62, 110), expected) == "", "cas nominal refuse")
    _check(_dimension_finding_code((79, 65, 113), expected) == "", "tolerance 3 mm refusee")
    _check(_dimension_finding_code((110, 76, 62), expected) == "ORIENTATION", "orientation non detectee")
    _check(_dimension_finding_code((76, 62, 115), expected) == "T4_LENGTH", "defaut T4 non detecte")
    _check(_dimension_finding_code((76, 66, 110), expected) == "T5_HEIGHT", "defaut hauteur non detecte")
    _check(_dimension_finding_code((82, 62, 110), expected) == "T5_WIDTH", "defaut largeur non detecte")
    _check(_dimension_finding_code((133, 62, 78), expected) == "GLOBAL", "incoherence globale non detectee")


def _status_for(measured: tuple[int, int, int], expected: tuple[int, int, int]) -> str:
    box = BoxInfo(
        bdd_width_mm=expected[0],
        bdd_height_mm=expected[1],
        bdd_length_mm=expected[2],
        measured_t5_width_mm=measured[0],
        measured_t5_height_mm=measured[1],
        measured_t4_length_mm=measured[2],
    )
    _classify_alpha_measurement(box)
    return box.measurement_status


def _check_statuses() -> None:
    expected = (76, 62, 110)
    _check(_status_for((76, 62, 110), expected) == "ok", "statut ok absent")
    _check(_status_for((110, 76, 62), expected) == "orientation", "statut orientation absent")
    _check(_status_for((133, 62, 78), expected) == "multiple", "statut multiple absent")


def _check_routes_trace() -> None:
    trace_path = ROOT / "TraceAlphaViewer" / "TracAlpharoutes.txt"
    if not trace_path.exists():
        print(f"Trace absente, controle terrain ignore: {trace_path}")
        return

    frames = parse_file(str(trace_path), min_dt=0.0)
    events = [event for frame in frames for event in frame.events]
    incidents = build_diagnostics(frames, events)
    dimension_incidents = {
        incident.code: incident
        for incident in incidents
        if incident.code in {"ORIENTATION", "T4_LENGTH", "T5_HEIGHT", "T5_WIDTH", "GLOBAL"}
    }
    _check(
        any(incident.code == "C9_WIDTH_INVALID" for incident in incidents),
        "diagnostic C9_WIDTH_INVALID absent sur TracAlpharoutes",
    )
    _check(
        any(box.measurement_status == "c9_error" for frame in frames for box in frame.boxes_on_T5),
        "statut c9_error absent sur TracAlpharoutes",
    )
    _check("GLOBAL" in dimension_incidents, "diagnostic GLOBAL absent sur TracAlpharoutes")
    _check("T5_WIDTH" in dimension_incidents, "diagnostic T5_WIDTH absent sur TracAlpharoutes")
    _check("T4_LENGTH" in dimension_incidents, "diagnostic T4_LENGTH absent sur TracAlpharoutes")
    all_example_lines = [
        line
        for incident in dimension_incidents.values()
        for line in incident.event_lines
    ]
    _check(any(1400 <= line <= 1500 for line in all_example_lines), "fenetre 10:14 non couverte")
    _check(any(4100 <= line <= 4360 for line in all_example_lines), "fenetre 11:05 non couverte")
    _check(
        any(
            incident.first_line <= 16972 <= incident.last_line
            for incident in dimension_incidents.values()
        ),
        "fenetre 16:10 non couverte",
    )


def main() -> None:
    _check_rules()
    _check_statuses()
    _check_routes_trace()
    print("Diagnostic dimensions: validation OK")


if __name__ == "__main__":
    main()
