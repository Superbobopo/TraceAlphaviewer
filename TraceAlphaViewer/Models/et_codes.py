"""
Descriptions partagees des codes eT firmware.
"""
from __future__ import annotations


ET_DESCRIPTIONS: dict[str, dict[int, str]] = {
    'T0': {
        -1: 'Variables init.', 1: 'Init mec.', 11: 'Init mec.',
        2: 'Init terminee', 4: 'Auto: attend C0', 41: 'Auto: tempo',
        42: 'Auto: tempo repos', 5: 'Arret moteur', 51: 'Arret moteur',
        6: 'Vidage rapide', 61: 'Vidage rapide',
        7: 'Vidage lent', 71: 'Vidage lent',
    },
    'T1': {
        -1: 'Variables init.', 1: 'Init mec.', 11: 'Init mec.',
        2: 'Init terminee', 41: 'Lance T1 rech. boite',
        42: 'Attend boite C1', 43: 'Arret T1',
        44: 'Attend tempo/BP/boite', 45: 'Arret T1 (boite C1)',
        46: 'Boite en bout T1', 47: 'Fin mvt court T1',
        5: 'Arret moteur', 51: 'Arret moteur',
        6: 'Vidage', 61: 'Vidage',
    },
    'T2': {
        -1: 'Variables init.', 1: 'Init mec.', 11: 'Init mec.',
        2: 'Init terminee', 42: 'Attend C2 actif', 43: 'Tempo veille',
        44: 'Attend boite C3', 46: 'Arret T2 (apres C3)',
        49: 'Boite chargee, prete', -48: 'Err: boite non arrivee C3',
        -49: 'Err: Laser non init', 5: 'Arret moteur', 51: 'Arret moteur',
        6: 'Vidage', 61: 'Vidage', 71: 'Attend fin mesure',
        78: 'Mesure ok, attend transfert', -79: 'Err: mesure erreur',
        8: 'Transfert T2->EA', 81: 'Declenche T2',
        82: 'Attend boite C4', 83: 'Arret T2 (boite C4)',
        89: 'Transfert termine', -87: 'Err: temps C4 depasse',
        -88: 'Err: boite deja C4', -89: 'Err: pas de boite C3',
    },
    'T3': {
        -1: 'Variables init.', 1: 'Init mec.', 11: 'Init mec.',
        2: 'Init terminee', 42: 'Attend tare', 43: 'Demarre T3 + ejection',
        44: 'Attend C5 actif', 46: 'Arret T3', 47: 'Attend fin poids',
        -43: 'Err: boite coincee', 49: 'Boite bout T3, poids ok',
        -44: 'Err: tare impossible', -45: 'Err: poids impossible',
        -46: 'Err: C5 non atteint', -47: 'Err: init MDM4/5',
        -48: 'Err: pas de boite C4', -49: 'Err: boite deja C5',
        5: 'Arret moteur', 51: 'Arret moteur',
        6: 'Vidage', 61: 'Vidage', 7: 'Vers C5', 71: 'Vers C5', 72: 'Vers C5',
    },
    'T4': {
        -1: 'Variables init.', 1: 'Demande init', 11: 'Vidage init',
        12: 'Init mec.', 13: 'Init mec.', 14: 'Rech. index',
        15: 'Arret tapis init', 16: 'Vers position repos',
        -17: 'Err: index non degage', -18: 'Err: index non trouve',
        -19: 'Err: init en erreur', 2: 'Init terminee',
        4: 'Charge T3->T4', 41: 'Charge boite T3->T4',
        42: 'Mesure longueur', 43: 'Arret en cours',
        46: 'Mesure ok, attend transfert', 48: 'Relance mesure',
        49: 'Recul tassement', -44: 'Err: boite sur C5',
        -45: 'Err: boite face T6', -46: 'Err: boite deja en attente',
        -47: 'Err: pas de boite C5', -48: 'Err: T3 non init',
        -49: 'Err: T4 non init', 5: 'Arret moteur', 51: 'Arret moteur',
        6: 'Vidage', 61: 'Vidage',
        7: 'Charge sans mesure', 71: 'Charge sans mesure',
        72: 'Charge sans mesure', 73: 'Charge sans mesure',
        8: 'Transfert T4->T5', 81: 'Attend fin transfert',
        82: 'Index vers repos', 83: 'Boite sur T5, index retour',
        85: 'Transfert termine', -85: "Err: T5 pas a l'arret",
        -86: 'Err: rien sur C6', -87: 'Err: FlagTransfert',
        -88: 'Err: T5 non init', -89: 'Err: T4 non init',
        9: 'Mesure longueur tapis', 91: 'Rech. debut cordon',
        92: 'Rech. cordon', 93: 'Rech. cordon (2e tour)',
        94: 'Arret T4', 96: 'Mesure terminee',
        -91: 'Err: pas de vitesse', -92: 'Err: cordon non vu (1er)',
        -93: 'Err: cordon non vu (2e)',
    },
    'T5': {
        -1: 'Variables init.', 1: 'Init mec.', 11: 'Init mec.',
        2: 'Init terminee', 4: 'Positionnement absolu',
        41: 'Positionnement absolu', -49: 'Err: erreur moteur',
        5: 'Arret moteur', 51: 'Arret moteur',
        6: 'Vidage', 61: 'Vidage',
        7: 'Positionnement relatif (mesure larg)',
        71: 'Positionnement relatif',
        9: 'Test depl. boite', 91: 'Attend pos. maxi / capteur',
        92: 'Attend arret reel', 93: 'Attend surplus', 94: 'Test depl.',
        99: 'Err: erreur moteur test',
    },
}


def et_description(belt: str, code: int | str | None) -> str:
    if code is None:
        return ''
    try:
        et = int(code)
    except (TypeError, ValueError):
        return ''
    return ET_DESCRIPTIONS.get(belt, {}).get(et, '')
