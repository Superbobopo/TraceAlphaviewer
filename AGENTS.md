# Instructions TraceAlphaViewer

## Projet et périmètre

TraceAlphaViewer est un viewer local Python/customtkinter de traces Alpha `.old` : parsing en frames `MachineState`, schéma machine, événements, diagnostics et navigation brute.

- Python est le moteur de référence pour une trace comme pour un dossier. Le code Rust résiduel ne nécessite ni construction, ni validation, ni comparaison de parité ; sa suppression relève d'une tâche distincte.
- Cette mémoire projet est versionnée : conserver les règles communes ici et les spécifications détaillées dans le référentiel lié ci-dessous, sans mémoire personnelle.
- Lire le code existant ; limiter les changements à la demande, sans refactor large ni annulation des changements utilisateur. Utiliser `apply_patch` pour les éditions manuelles.
- Ne modifier aucun fichier hors dépôt, configuration globale ou hook Git sans demande explicite.

## Langue, confidentialité et documentation

- Garder README.md, AGENTS.md, la documentation et les nouveaux commentaires en français. Commentaires courts ; ne pas traduire les identifiants techniques ni les libellés issus des traces.
- Préserver l'UTF-8 des sources et de l'interface, notamment les accents, `●` et `—`. Corriger localement les caractères corrompus, sans conversion globale ni changement de lecture Latin-1 des traces.
- Ne jamais afficher ni versionner de secrets, clés, tokens, fichiers d'authentification ou contenu privé hors projet.
- Les traces restent locales : pas de `*.old` ni de gros `.txt` de trace dans Git, sauf demande explicite pour un petit échantillon précis.
- Ranger les traces terrain dans `traces-locales/` à la racine (ignoré par Git). L'espace `TraceAlphaViewer.code-workspace` sépare sources, outils, rapport, documentation et traces ; caches et builds y sont masqués, sans suppression.
- **Ne pas générer ni régénérer le manuel, ses captures ou son PDF sans demande explicite.** Le manuel existant est dans `docs/manuel-utilisateur/index.html`. Si une génération est demandée, utiliser des données fictives et capturer uniquement le HWND du viewer, jamais le bureau ni les traces terrain ; vérifier images et pagination du PDF.
- Documenter les nouveaux invariants qui évitent une régression, dans la section métier concernée du référentiel.

## Référentiel à consulter selon le changement

Lire uniquement les sections pertinentes de [docs/referentiel-technique.md](docs/referentiel-technique.md), sans charger tout le document pour une tâche ciblée :

| Domaine modifié | Sections à consulter |
| --- | --- |
| Packaging Windows, catalogue et identité des sources | [Construction et catalogue](docs/referentiel-technique.md#construction-et-catalogue) |
| Cython, préfiltrage et temps parser | [Accélération et parsing](docs/referentiel-technique.md#accélération-et-parsing) |
| Cycles boîtes, CB1/CB2, transferts et références | [Identités et parser](docs/referentiel-technique.md#identités-et-parser) |
| Positions, dimensions ou fantômes T5 | [Rendu T5](docs/referentiel-technique.md#rendu-t5) et [scénarios ciblés](docs/referentiel-technique.md#scénarios-terrain-ciblés) |
| Interface, workers, ressources, FrameStore et rapports | [Interface, chargement et rapports](docs/referentiel-technique.md#interface-chargement-et-rapports) |
| Diagnostics, mesures, caméras, robot et radar | [Diagnostics terrain](docs/referentiel-technique.md#diagnostics-terrain) |
| Sources et build du rapport web/PDF | [Livraison des rapports](docs/referentiel-technique.md#livraison-des-rapports) |

## Invariants critiques

- L'identité suit le cycle boîte : matching `id_alpha`, puis `id_b`, puis barcode uniquement si unique. Ne jamais fusionner, modifier ou supprimer plusieurs boîtes sur le seul CIP.
- Conserver les provenances produit, caméra, BdD et mesures à travers clones et transferts. Une recherche BdD ne prouve pas une identification caméra ; une référence contradictoire ne récupère pas les dimensions d'un autre produit.
- Chaque fichier de dossier est un segment indépendant : identités, attentes parser et séquences capteurs ne franchissent pas sa limite. Conserver fichier et ligne source dans les preuves et la navigation.
- Relire les lignes sources ciblées avant toute conclusion métier. Ne pas inférer une cause physique d'un seul code ou un résultat du nom de la trace. Ne jamais modifier le fichier brut.
- `pT5` est un encodeur moteur, pas une position absolue ni une preuve de mouvement physique. Les positions stables viennent de MAJ, T5-LIST-PACK ou déplacements BdD confirmés.
- Préserver les positions relatives et la continuité T5 ; ne pas corriger un état parser erroné par un clamp ou un changement des constantes canvas. Les calibrages métier restent inchangés sans demande explicite.
- Les UNKNOWN supprimées informatiquement restent dans `t5_ghost_boxes`, hors boîtes actives, analyses et compteurs. Leur déplacement visuel est supposé ; conserver la preuve de suppression et réinitialiser entre fichiers.
- Les appels Tk et `after` restent sur le thread UI ; les workers communiquent par file. Aucun join bloquant dans un callback Tk. Fermeture/remplacement annule callbacks, bindings et travaux périmés.
- Ne pas retenir toutes les frames en mémoire ni parcourir tout FrameStore dans Tk. Conserver les blocs bornés, les snapshots indépendants et les analyses dans les workers.
- Cython compile les mêmes sources Python avec `annotation_typing=False` et `infer_types=False`. Préserver types, champs et événements ; un lot absent ou périmé revient aux sources. Après modification d'un module accéléré, recompiler et valider les deux modes ; ne pas distribuer d'extension périmée.

## Commandes et validation proportionnée

Depuis la racine : `python TraceAlphaViewer/Main.py`.

- Documentation seule : relire le diff, vérifier les liens et `git diff --check` ; aucun test métier.
- Petite modification visuelle : contrôler le composant concerné, sans tester les fonctions indépendantes.
- Correction fonctionnelle : `python -m py_compile <fichiers_modifiés>`, puis tests ciblés de la fonction et des dépendances directement touchées.
- Modification transversale du parser, des identités, du stockage ou du chargement : `python TraceAlphaViewer/Tools/validate_all.py` et compilation des fichiers principaux ci-dessous.
- Après correction T5, vérifier les frames par script en plus du rendu concerné ; pour les fantômes, utiliser `python TraceAlphaViewer/Tools/validate_t5_ghosts.py`.
- Les tests réussis restent acquis tant qu'aucun changement ne peut affecter leur résultat. Signaler les contrôles pertinents impossibles ; ne pas relancer uniquement pour un commit.
- **Benchmarks uniquement sur demande explicite**, y compris pour une optimisation. Conserver les scripts existants ; aucun objectif historique de gain ni protocole de performance obligatoire.
- Les validations restent en arrière-plan sans prise de focus ; un contrôle visible demande une instruction explicite.
- **Reconstruire le .exe uniquement sur demande explicite pour cette construction.** Valider alors le binaire avant livraison ; `validate_all.py` l'exclut par défaut, `--exe` sert après reconstruction demandée.
- Reconstruire React lorsque ses sources changent, avant validation navigateur et livraison ; aucun build pour une modification documentaire.

Compilation globale :

```powershell
python -m py_compile TraceAlphaViewer/Main.py TraceAlphaViewer/Models/state.py TraceAlphaViewer/Parser/trace_parser.py TraceAlphaViewer/Views/traceView.py TraceAlphaViewer/Widgets/machine_canvas.py
```

## Git et livraison

- `main` représente la dernière version utilisable. Garder l'historique normal et les tags ; branche courte pour un travail risqué, retour à main après validation finale, sans commits intermédiaires automatiques.
- **Indexation, commit et push uniquement sur demande explicite.** Un commit n'autorise pas le push. Ne rien déclencher en fin de tâche ou à heure fixe ; préserver les changements utilisateur, y compris déjà indexés.
- Avant un commit demandé : terminer et relire la tâche, appliquer la validation proportionnée, examiner `git status --short`, `git diff`, `git diff --cached`, `git diff --cached --name-only`, les fichiers non suivis concernés et `git diff --check`.
- Ne pas committer ni pousser si un contrôle requis échoue ou reste impossible. Indexer uniquement les fichiers ou morceaux autorisés, jamais `git add .` ou `git add -A`. Exclure traces interdites, secrets, temporaires et artefacts non demandés ; retirer les traces interdites de l'index avant commit sans effacer les fichiers locaux.
- Message de commit descriptif en français ; ne contourner ni hooks ni identité Git. Si le commit échoue, expliquer et ne pas pousser.
- Avant un push demandé, vérifier branche courante, origin attendu `Superbobopo/TraceAlphaviewer` et tous les commits à envoyer. Ne pas pousser de changements non autorisés, sensibles ou invérifiables ; si destination ambiguë ou HEAD détachée, s'arrêter et expliquer.
- Pousser uniquement avec `git push origin <branche_courante>`, vers la branche de même nom. Ne jamais forcer, réécrire l'historique ni annuler les changements utilisateur pour rendre le push possible. Conserver le commit local en cas d'échec.
- Confirmer séparément les opérations demandées, avec message et identifiant du commit ; annoncer un push réussi seulement après vérification.
- Pour terminer une tâche, résumer les changements, contrôles et limites. Rechercher seulement le code utile, regrouper les inspections indépendantes et garder les journaux détaillés locaux non versionnés avec leur code de sortie.
