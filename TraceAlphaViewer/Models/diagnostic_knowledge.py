from __future__ import annotations


DIAGNOSTIC_KNOWLEDGE: dict[str, dict[str, object]] = {
    'motor_error_generic': {
        'symptom': "Un code eT negatif documente comme erreur apparait sur un tapis.",
        'causes': [
            "Defaut moteur ou entrainement sur le tapis concerne.",
            "Capteur associe absent, instable ou mal regle.",
            "Etat mecanique local a verifier autour de la premiere erreur.",
        ],
        'checks': [
            "Ouvrir les lignes proches de la premiere apparition.",
            "Comparer le code eT, les capteurs associes et la position du tapis.",
        ],
        'confidence': 'possible',
    },
    't4_error_minus_18': {
        'symptom': "T4 termine son initialisation sur ERREUR -18 ou repete eT:-18.",
        'causes': [
            "Probleme moteur ou rouleau moteur sur T4.",
            "Capteur C6 trop haut, mal regle ou decale.",
            "Capteur/index T4 HS, debranche ou non vu.",
        ],
        'checks': [
            "Verifier le moteur et l'entrainement T4.",
            "Verifier la position mecanique et le cablage de C6/index.",
            "Regarder si pT4 tourne en boucle sans sortir de l'initialisation.",
        ],
        'confidence': 'probable',
    },
    't4_init_loop': {
        'symptom': "T4 reentre souvent en initialisation sans stabiliser un cycle normal.",
        'causes': [
            "Probleme moteur ou rouleau moteur sur T4.",
            "Capteur C6 trop haut ou mal positionne.",
            "Capteur C6 ou index T4 HS.",
        ],
        'checks': [
            "Compter les occurrences d'init T4 et d'eT:-18.",
            "Verifier que T4 atteint bien un etat stable apres init.",
        ],
        'confidence': 'probable',
    },
    't2_block_before_ea': {
        'symptom': "C2 et C3 restent actifs alors qu'un transfert vers EA est demande et que C4 ne s'allume pas dans le delai attendu.",
        'causes': [
            "Boite probablement bloquee sur T2 avant EA.",
            "Transfert incomplet entre T2 et EA.",
            "Probleme mecanique convoyeur T2 ou avance de boite insuffisante.",
        ],
        'checks': [
            "Verifier les lignes autour du debut de WAIT-COND-TRSF/WAIT-FIN-TRSF.",
            "Verifier si C4 reste a 0 alors que C2/C3 restent a 1.",
        ],
        'confidence': 'probable',
    },
    't5_dem_vidage_complet': {
        'symptom': "Le robot demande plusieurs vidages complets de T5.",
        'causes': [
            "Le robot tape une boite lors de la prise sur T5.",
            "Apprentissage Alpha incorrect ou decalage informatique.",
            "Probleme mecanique T5 sur moteur ou rouleau moteur.",
        ],
        'checks': [
            "Compter les occurrences OMEGA:T5-DemVidageComplet.",
            "Verifier la position des boites T5 et le comportement robot autour des occurrences.",
        ],
        'confidence': 'probable',
    },
    'code_017_c4_eject': {
        'symptom': "La trace signale une boite coincee sur C4 apres plusieurs ejects.",
        'causes': [
            "Probleme probable d'ejecteur sur C4.",
            "Boite mal guidee ou ejection incomplete.",
        ],
        'checks': [
            "Verifier le mecanisme d'ejection cote C4.",
            "Regarder si la boite reste longtemps sur C4 dans la trace.",
        ],
        'confidence': 'probable',
    },
    'code_028_motor_comm': {
        'symptom': "La trace signale un defaut de communication carte moteurs.",
        'causes': [
            "Probleme de communication avec la carte moteurs.",
            "Cablage, alimentation ou carte a verifier.",
        ],
        'checks': [
            "Verifier la communication avec la carte moteurs.",
            "Verifier alimentation et connexions.",
        ],
        'confidence': 'probable',
    },
    'code_118_t5_bin_block': {
        'symptom': "Le T5 est vide apres un blocage poubelle.",
        'causes': [
            "Mauvaise lecture des cameras avec accumulation de boites unknown.",
            "Blocage de la zone poubelle ou chaine T5 perturbee.",
        ],
        'checks': [
            "Verifier les lectures camera et la proportion de boites unknown.",
            "Verifier la zone poubelle et le flux T5.",
        ],
        'confidence': 'possible',
    },
}


def knowledge(rule_id: str) -> dict[str, object]:
    return DIAGNOSTIC_KNOWLEDGE.get(rule_id, {})
