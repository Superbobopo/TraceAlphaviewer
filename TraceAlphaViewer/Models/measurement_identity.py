"""Identite produit et provenance communes aux comparaisons de dimensions."""


def is_unknown_reference(reference):
    value = (reference or '').strip().upper()
    return not value or value.startswith(('ALPHA-INC', 'ALPHA-DET', 'ALPHA-DIF')) or 'UNKNOW' in value


def record_identification(box, reference, name='', line=0, source='', camera_confirmed=False):
    if is_unknown_reference(reference):
        return
    if box.identified_barcode and box.identified_barcode != reference:
        box.identity_conflict = True
        return
    box.identified_barcode = reference
    if name:
        box.identified_name = name
    if line and not box.identity_line:
        box.identity_line = line
        box.identity_source = source
    if camera_confirmed and line and source in ('CB1', 'CB2') and not box.camera_identity_line:
        box.camera_identity_line = line
        box.camera_identity_source = source


def measurement_exclusion(box):
    if box.identity_conflict:
        return 'reference_conflict'
    if is_unknown_reference(box.barcode) and not (
            '[DINH]' in box.barcode.upper() and box.identified_barcode):
        return 'unknown'
    if not box.identified_barcode or not box.identity_line:
        return 'identity_unconfirmed'
    if not is_unknown_reference(box.barcode) and box.barcode != box.identified_barcode:
        return 'reference_conflict'
    if box.bdd_reference and box.bdd_reference != box.identified_barcode:
        return 'reference_conflict'
    if not box.camera_identity_line or box.camera_identity_source not in ('CB1', 'CB2'):
        return 'camera_unconfirmed'
    if not box.bdd_reference or any(v <= 0 for v in (
            box.bdd_width_mm, box.bdd_height_mm, box.bdd_length_mm)):
        return 'reference_absent'
    return ''


EXCLUSION_LABELS = {
    'orientation': 'orientations probables', 'orientation_uncertain': 'orientations indecidables',
    'camera_unconfirmed': 'identifications camera non confirmees', 'invalid': 'mesures invalides',
    'incomplete': 'mesures incompletes', 'reference_absent': 'references BdD absentes',
    'ambiguous': 'identites ambigues', 'unknown': 'UNKNOWN sans produit identifie',
    'identity_unconfirmed': 'identifications non confirmees', 'reference_conflict': 'references contradictoires',
    't4c_absent': 'longueur T4C absente',
}
