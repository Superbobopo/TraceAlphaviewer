from __future__ import annotations

DIMENSION_TOLERANCE_MM = 3

MEASUREMENT_STYLES = {
    '': ('#4FC3F7', 'Mesure non evaluee'),
    'ok': ('#2ECC71', 'Conforme (+/-3 mm)'),
    'orientation': ('#F5B041', 'Orientation differente'),
    'length': ('#A78BFA', 'Longueur T4/C6 hors tol.'),
    'width': ('#14B8A6', 'Largeur T5/C9 hors tol.'),
    'height': ('#FDE047', 'Hauteur T5/LzB hors tol.'),
    'multiple': ('#E74C3C', 'Plusieurs dim. hors tol.'),
    'c9_error': ('#FF2DAA', 'Largeur invalide / C9'),
}
MEASUREMENT_STATUS_COLORS = {key: value[0] for key, value in MEASUREMENT_STYLES.items()}
MEASUREMENT_STATUS_COLORS['bad'] = MEASUREMENT_STATUS_COLORS['multiple']


def measurement_label(status: str) -> str:
    return MEASUREMENT_STYLES.get('multiple' if status == 'bad' else status,
                                  MEASUREMENT_STYLES[''])[1]


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
    return {'': 'ok', 'ORIENTATION': 'orientation', 'T4_LENGTH': 'length',
            'T5_WIDTH': 'width', 'T5_HEIGHT': 'height', 'GLOBAL': 'multiple'}.get(code, 'bad')
