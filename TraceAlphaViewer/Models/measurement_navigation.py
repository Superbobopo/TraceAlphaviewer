"""Cible de lecture complete, distincte des lignes sources de chaque capteur."""
from Models.measurement_identity import measurement_exclusion


def measurement_display_target(sample):
    index, line = sample.get('display_frame_index'), sample.get('display_line')
    if type(index) is not int or index < 0 or type(line) is not int or line <= 0:
        raise ValueError('Etat complet absent de ce rapport. Rouvrir la trace et regenerer le rapport.')
    if any(not sample.get('sources', {}).get(axis) for axis in ('length', 'width', 'height')):
        raise ValueError('Les sources des trois mesures sont indisponibles.')
    return index, line


def measurement_box_in_frame(frame, sample):
    _, line = measurement_display_target(sample)
    if frame.line_num != line:
        raise ValueError('Cet instant ne correspond plus a la trace ouverte. Regenerer le rapport.')
    if sample.get('id_alpha'):
        matches = [box for box in frame.boxes_on_T5 if box.id_alpha == sample['id_alpha']]
    elif sample.get('id_b'):
        matches = [box for box in frame.boxes_on_T5 if box.id_b == sample['id_b']]
    else:
        matches = [box for box in frame.boxes_on_T5 if box.identified_barcode == sample.get('barcode')]
    if len(matches) != 1:
        raise ValueError('La boite mesuree est absente ou son identite est ambigue dans cet etat.')
    box = matches[0]
    if measurement_exclusion(box):
        raise ValueError('La reconnaissance ou la BdD de cette boite ne permet plus une comparaison fiable.')
    measured = [box.measured_t5_width_mm, box.measured_t5_height_mm, box.measured_t4_length_mm]
    expected = [box.bdd_width_mm, box.bdd_height_mm, box.bdd_length_mm]
    sources = [box.measured_t4_line, box.measured_t5_line, box.measured_height_line]
    if (any(value <= 0 for value in measured + expected + sources)
            or measured != sample.get('measured') or expected != sample.get('expected')
            or sources != [sample['sources'][axis] for axis in ('length', 'width', 'height')]
            or box.identified_barcode != sample.get('barcode')):
        raise ValueError('Les trois mesures de cette boite ne correspondent plus au rapport.')
    return box
