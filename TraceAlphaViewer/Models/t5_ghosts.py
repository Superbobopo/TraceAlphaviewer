"""Suivi visuel des UNKNOWN supprimees, sans participation aux analyses."""
from Models.measurement_identity import is_unknown_reference

# Geometrie du schema T5 existant ; les validations la comparent au canvas.
BELT_WIDTH_PX = 618
BELT_HEIGHT_PX = 112
ENTRY_FROM_RIGHT_PX = 154
BELT_LENGTH_MM = 770
SCALE = BELT_WIDTH_PX / BELT_LENGTH_MM


def box_size_px(box, scale=SCALE, max_h=BELT_HEIGHT_PX - 16):
    length = max(0, int(box.length_mm or 0))
    width = max(0, int(box.width_mm or 0))
    fallback = max(0, int(box.t5_footprint_mm or 0))
    horizontal = width or fallback or length or 40
    vertical = length or width or min(fallback, 80) or 40
    dim_scale = min(scale * 0.75, max_h / max(vertical, 1))
    return max(8, int(horizontal * dim_scale)), max(12, int(vertical * dim_scale))


def remember_deleted(state, box, line):
    reference = box.identified_barcode or box.barcode
    if not reference or not is_unknown_reference(reference):
        return
    ghost = box.clone()
    ghost.t5_deleted_line = line
    width, _ = box_size_px(box)
    offset = state.t5_visual_offset_mm
    if box.t5_entry_aligned:
        delta = offset + (box.t5_visual_x_pos - (box.x_pos or 1060) if box.t5_visual_x_pos else 0)
        x = BELT_WIDTH_PX - ENTRY_FROM_RIGHT_PX - width // 2
        if delta:
            x = max(0, min(BELT_WIDTH_PX - width, x - int(delta * SCALE)))
    else:
        base = box.t5_visual_x_pos or box.x_pos or 942
        butee = state.t5_x_butee
        if butee > 1750 and base > 1750:
            base = 942 + abs(base - butee)
        origin = butee if 0 < butee <= 1750 else 942
        x = BELT_WIDTH_PX - int((base + offset - origin) * SCALE) - width
    if x + width <= 0:
        return
    # Reprendre exactement le rectangle affiche avant suppression, meme en entree.
    x = max(2, min(x, BELT_WIDTH_PX - width - 2))
    right = min(BELT_WIDTH_PX - 2, x + max(width, 6))
    ghost.t5_ghost_x_mm = (BELT_WIDTH_PX - right) / SCALE
    state.t5_ghost_boxes.append(ghost)


def advance_ghosts(state, delta):
    for ghost in state.t5_ghost_boxes:
        ghost.t5_ghost_x_mm += delta
    state.t5_ghost_boxes = [
        ghost for ghost in state.t5_ghost_boxes
        if ghost.t5_ghost_x_mm < BELT_LENGTH_MM
        and ghost.t5_ghost_x_mm + box_size_px(ghost)[0] / SCALE > 0
    ]


def same_cycle(ghost, box):
    if ghost.id_alpha and box.id_alpha and ghost.id_alpha != box.id_alpha:
        return False
    if ghost.id_b and box.id_b and ghost.id_b != box.id_b:
        return False
    if ghost.t5_transfer_id and box.t5_transfer_id:
        return ghost.t5_transfer_id == box.t5_transfer_id
    return bool(ghost.id_alpha and ghost.id_alpha == box.id_alpha)


def reconcile_ghosts(state):
    state.t5_ghost_boxes = [
        ghost for ghost in state.t5_ghost_boxes
        if not any(same_cycle(ghost, box) for box in state.boxes_on_T5)
    ]
