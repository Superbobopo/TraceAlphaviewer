from __future__ import annotations

DIMENSION_TOLERANCE_MM = 3


def dimension_ok(measured: int, expected: int) -> bool:
    return abs(measured - expected) <= DIMENSION_TOLERANCE_MM


def dimension_tuple_matches_unordered(
    measured: tuple[int, int, int],
    expected: tuple[int, int, int],
) -> bool:
    used = [False, False, False]

    def match_at(idx: int) -> bool:
        if idx >= len(measured):
            return True
        for exp_idx, exp_value in enumerate(expected):
            if used[exp_idx]:
                continue
            if not dimension_ok(measured[idx], exp_value):
                continue
            used[exp_idx] = True
            if match_at(idx + 1):
                return True
            used[exp_idx] = False
        return False

    return match_at(0)


def dimension_finding_code(
    measured: tuple[int, int, int],
    expected: tuple[int, int, int],
) -> str:
    width_ok = dimension_ok(measured[0], expected[0])
    height_ok = dimension_ok(measured[1], expected[1])
    length_ok = dimension_ok(measured[2], expected[2])
    if width_ok and height_ok and length_ok:
        return ""
    if dimension_tuple_matches_unordered(measured, expected):
        return "ORIENTATION"
    if not length_ok and width_ok and height_ok:
        return "T4_LENGTH"
    if not height_ok and width_ok and length_ok:
        return "T5_HEIGHT"
    if not width_ok and height_ok and length_ok:
        return "T5_WIDTH"
    return "GLOBAL"


def measurement_status_from_code(code: str) -> str:
    if not code:
        return "ok"
    if code == "ORIENTATION":
        return "orientation"
    return "bad"
