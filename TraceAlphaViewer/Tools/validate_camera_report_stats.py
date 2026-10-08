from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "TraceAlphaViewer"))

from Models.diagnostic import build_diagnostics, camera_report_stats
from Parser.trace_parser import parse_file


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _chart_counts(stats: dict[str, object]) -> dict[tuple[str, str], int]:
    return {
        (str(item["reader"]), str(item["camera"])): int(item["success_count"])
        for item in stats.get("chart", [])
    }


def _zero_alerts(stats: dict[str, object]) -> set[tuple[str, str]]:
    return {
        (str(item["reader"]), str(item["camera"]))
        for item in stats.get("alerts", [])
        if item.get("status") == "zero"
    }


def _stats_for(trace_name: str) -> dict[str, object] | None:
    trace_path = ROOT / "TraceAlphaViewer" / trace_name
    if not trace_path.exists():
        print(f"Trace absente, controle ignore: {trace_path}")
        return None
    frames = parse_file(str(trace_path), min_dt=0.0)
    return camera_report_stats(frames)


def _check_ortiz() -> None:
    stats = _stats_for("TracAlpha1ortiz.txt")
    if stats is None:
        return
    counts = _chart_counts(stats)
    expected = {
        ("CB1", "1"),
        ("CB1", "2"),
        ("CB1", "4"),
        ("CB1", "5"),
        ("CB1", "6"),
        ("CB2", "3"),
    }
    _check(int(stats["total_boxes"]) >= 50, "total_boxes Ortiz insuffisant")
    for key in expected:
        _check(counts.get(key, 0) > 0, f"reussite camera Ortiz absente: {key}")
    zero_alerts = _zero_alerts(stats)
    _check(not (zero_alerts & expected), "alerte zero camera injustifiee sur Ortiz")


def _check_routes() -> None:
    stats = _stats_for("TracAlpharoutes.txt")
    if stats is None:
        return
    counts = _chart_counts(stats)
    _check(int(stats["total_boxes"]) > 0, "total_boxes routes absent")
    _check(sum(counts.values()) > 0, "reussites cameras routes absentes")
    _check(counts.get(("CB2", "3"), 0) > 0, "camera 3 CB2 routes absente")


def main() -> None:
    _check_ortiz()
    _check_routes()
    print("Diagnostic cameras: validation OK")


if __name__ == "__main__":
    main()
