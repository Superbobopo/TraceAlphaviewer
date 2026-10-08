from __future__ import annotations


DIAGNOSTIC_KNOWLEDGE: dict[str, dict[str, object]] = {
    'alpha_card_reset': {
        'symptom': "Le compteur 'Temps depuis RESET carte ALPHA' chute et repart pres de zero pendant la trace.",
        'causes': [
            "Defaut electrique ou perturbation provenant du CubeStop.",
            "Defaut electrique ou perturbation provenant de la balance.",
            "Shunt CubeStop ou balance absent, desserre ou incorrect.",
            "Alimentation, masse ou cablage de la carte Alpha instable.",
            "Defaut de la carte Alpha elle-meme.",
        ],
        'checks': [
            "Verifier les shunts du CubeStop et de la balance.",
            "Controler le cablage, les masses et l'alimentation de la carte Alpha.",
            "Comparer l'heure du reset avec les commandes CubeStop et les operations de pesee.",
            "Rechercher d'autres chutes du compteur pour confirmer la repetition.",
        ],
        'confidence': 'forte',
    },
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
    't2_error_minus_88_c4': {
        'symptom': "T2 signale qu'une boite est deja presente sur C4 au moment du transfert.",
        'causes': [
            "Boite bloquee sur C4.",
            "Ejecteur C4 qui n'ejecte pas correctement.",
            "Capteur C4 mal regle ou faux actif.",
            "Cubestop qui ne se leve pas et ne laisse pas passer les boites.",
        ],
        'checks': [
            "Verifier si C4 reste actif autour des occurrences.",
            "Controler l'ejecteur C4 et le guidage de sortie.",
            "Verifier le reglage du capteur C4 et l'etat du cubestop.",
        ],
        'confidence': 'probable',
    },
    't3_error_minus_48_c4_missing': {
        'symptom': "T3 attend une boite venant de C4 mais la boite n'est pas vue au moment attendu.",
        'causes': [
            "Ejection ou transfert ponctuel depuis C4 incomplet.",
            "Boite attendue absente ou deja evacuee.",
            "Detection C4/T3 ponctuellement incoherente.",
            "CubeStop ou guidage C4/T3 a verifier si le defaut se repete.",
        ],
        'checks': [
            "Verifier les lignes proches si l'occurrence est isolee.",
            "Controler le transfert C4 vers T3 seulement si le defaut se repete.",
            "Verifier la commande CubeStop HAUT/BAS si la trace indique CubeStop:Y.",
        ],
        'confidence': 'possible',
    },
    't3_error_minus_43_c4_stuck': {
        'symptom': "T3 signale une boite coincee pendant le transfert EA/C4 vers T3.",
        'causes': [
            "Boite bloquee sur C4 ou dans le rail d'ejection.",
            "Ejecteur C4 qui pousse mal ou pas assez longtemps.",
            "CubeStop commande en haut mais reste mecaniquement en bas.",
            "Capteur C4 faux actif ou mal regle.",
        ],
        'checks': [
            "Verifier si C4 reste actif pendant WAIT-FIN-TRSF.",
            "Controler le mouvement reel du CubeStop au moment de la commande HAUT.",
            "Controler l'ejecteur C4, le rail d'ejection et le passage vers T3.",
        ],
        'confidence': 'probable',
    },
    'cubestop_c4_blocked': {
        'symptom': "Le systeme demande le passage vers T3, mais C4 reste actif et C5 ne voit pas la boite.",
        'causes': [
            "CubeStop commande en haut mais volet reste mecaniquement en bas.",
            "Boite bloquee sur C4 ou guidee contre le volet.",
            "Ejecteur C4 qui n'ejecte pas correctement.",
            "Capteur C4 mal regle ou signal faux actif.",
        ],
        'checks': [
            "Observer physiquement si le CubeStop remonte lors de la commande HAUT.",
            "Verifier que la boite quitte C4 et arrive sur C5 pendant le transfert EA->T3.",
            "Controler l'ejecteur, le rail d'ejection et le reglage du capteur C4.",
        ],
        'confidence': 'forte',
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
    't4_init_repeated_c6_active': {
        'symptom': "T4 demande plusieurs initialisations d'affilee alors que C6 reste actif.",
        'causes': [
            "Capteur C6 trop bas et voit la bande du tapis en permanence.",
            "Corps etranger devant C6: cheveu, papier, bouchon, plastique ou depot.",
            "Capteur C6 HS, mal positionne ou signal bloque actif.",
        ],
        'checks': [
            "Nettoyer la zone C6 et verifier qu'aucun objet ne reste devant le capteur.",
            "Verifier le reglage hauteur/alignement de C6.",
            "Controler que C6 s'allume seulement au passage du boudin T4.",
        ],
        'confidence': 'probable',
    },
    't4_init_repeated_index_missing': {
        'symptom': "T4 demande plusieurs initialisations d'affilee sans retrouver correctement son index C6.",
        'causes': [
            "Capteur C6 trop haut, mal regle ou decale.",
            "Capteur C6 HS, debranche ou instable.",
            "Moteur T4 qui patine ou n'arrive jamais a destination.",
            "Rouleau moteur HS: le moteur tourne mais le tapis n'est pas entraine.",
        ],
        'checks': [
            "Verifier que le boudin T4 passe bien devant C6 pendant l'initialisation.",
            "Verifier le moteur T4, la transmission et le rouleau moteur.",
            "Comparer pT4, eT4 et les transitions C6 autour des demandes d'init.",
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
    'camera_unknown_rate': {
        'symptom': "Une proportion elevee de boites finit en reference unknown apres lecture datamatrix.",
        'causes': [
            "Datamatrix absent, abime, mal oriente ou mal presente aux cameras.",
            "Camera deconnectee, sale, mal reglee ou non contributive.",
            "Eclairage, mise au point ou lecteur code-barres a controler.",
            "Probleme reseau ou communication avec le groupement camera.",
        ],
        'checks': [
            "Comparer les taux CB1 et CB2 pour localiser le groupement le plus suspect.",
            "CB1 utilise les cameras 1, 2, 4, 5 et 6.",
            "CB2 utilise la camera 3.",
            "Verifier les cameras qui n'ont aucune reussite observee dans la trace.",
        ],
        'confidence': 'possible',
    },
    'camera_no_success': {
        'symptom': "Une camera attendue ne produit aucune lecture reussie dans une trace significative.",
        'causes': [
            "Camera HS ou deconnectee.",
            "Cable, reseau ou lecteur code-barres a controler.",
            "Camera sale, masquee, mal reglee ou hors focus.",
            "Eclairage insuffisant ou declenchement camera non effectif.",
        ],
        'checks': [
            "Verifier alimentation, connexion et communication de la camera indiquee.",
            "Controler nettoyage, mise au point, eclairage et position de la camera.",
            "Comparer avec les compteurs PR/Soh des autres cameras du meme groupement.",
        ],
        'confidence': 'probable',
    },
}


def knowledge(rule_id: str) -> dict[str, object]:
    return DIAGNOSTIC_KNOWLEDGE.get(rule_id, {})
