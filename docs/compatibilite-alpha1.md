# Compatibilite Alpha 1

Le viewer peut ouvrir la trace Alpha 1 examinee et aider a son diagnostic.
La compatibilite complete des diagnostics automatiques avec cette generation
reste a qualifier ; une lecture reussie ne valide pas toutes les interpretations.

## Comparaison locale du 27 octobre 2026

Comparaison de `TracAlpha1_016.txt` (Edeline, fichier terrain conserve localement)
avec `TracAlpha1_017.old` (Alpha 2). Le nom `TracAlpha1` et `NumALPHA = 1`
ne designent pas a eux seuls la generation materielle.

| Declaration | Edeline | Trace Alpha 2 comparee |
| --- | --- | --- |
| TapisAlph | gen1 | gen2 |
| CaptVertical | laser | UltraSon |
| CubeStop | N | Y |
| Firmware carte | V0.54 | V0.61 |

Le parser produit 43 036 frames pour Edeline et suit 459 identites T5.
Les familles principales de messages (etats T0-T5, CB1/CB2, identites,
listes et positions T5) sont reconnues. Les codes d'etat observes sans libelle
existent aussi dans la trace Alpha 2 comparee. L'absence de CubeStop et les
grandes coordonnees T5 ont deja des traitements dedies dans le logiciel.

## Limites d'interpretation

Sur les 94 cycles retenus par les exclusions habituelles pour comparer les
dimensions, tous sont hors tolerance en longueur, avec une concentration
autour de -18 mm. Ce sous-ensemble ne represente pas toutes les boites.
Les ecarts existent dans les lignes sources : a la ligne 875, la longueur
BdD est de 131 mm, T4C de 114 mm et T4T de 139 mm (diffT4 = -25 mm).

Ces observations ne distinguent pas un defaut de reglage d'une particularite
de mesure de la generation. Confirmer sur plusieurs cycles identifies, des
dimensions physiques/BdD et la documentation technique du materiel avant
de conclure a une panne ou de proposer un reglage.

Aucune compensation automatique de longueur et aucun changement des seuils,
des valeurs sources ou des diagnostics ne sont appliques pour Alpha 1.
La qualification reste a etendre a plusieurs traces gen1 et a des incidents
confirmes sur le terrain, en verifiant aussi les interpretations des capteurs
et des codes firmware. Les traces terrain ne sont pas versionnees.
