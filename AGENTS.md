# Notes agent TraceAlphaViewer

## Vue du projet

TraceAlphaViewer est un viewer local Python/customtkinter pour traces Alpha `.old`.
Il parse les lignes de trace en frames `MachineState`, puis affiche le schema machine, les capteurs, les boites, les evenements, les diagnostics et la navigation dans la trace brute.

Ce fichier est la memoire projet versionnee. Les regles techniques partagees doivent rester ici, pas dans une memoire personnelle Codex.

## Langue et documentation

- `README.md` et `AGENTS.md` doivent rester en francais.
- Les nouveaux commentaires de code doivent etre en francais.
- Ne pas traduire les identifiants techniques, noms de fichiers, constantes, classes, fonctions ou libelles issus des traces.
- Garder les commentaires courts et utiles ; ne pas commenter ce que le code dit deja clairement.
- Le manuel debutant est dans `docs/manuel-utilisateur/index.html` ; son PDF est genere depuis ce meme HTML. Apres un changement visible de l'interface, verifier les instructions, reperes et captures concernes. Utiliser `Tools/generate_user_manual.py --captures --pdf` avec des donnees fictives et une capture du HWND du viewer uniquement ; ne jamais capturer le bureau ou publier les traces terrain. Controler la pagination et les images du PDF avant livraison.

## Lancement et commandes

Depuis la racine du depot :

```powershell
python TraceAlphaViewer\Main.py
```

Compilation minimale apres modification de code :

```powershell
python -m py_compile TraceAlphaViewer\Main.py TraceAlphaViewer\Models\state.py TraceAlphaViewer\Parser\trace_parser.py TraceAlphaViewer\Views\traceView.py TraceAlphaViewer\Widgets\machine_canvas.py
```

Pour explorer rapidement :

```powershell
rg -n "motif" TraceAlphaViewer\Parser TraceAlphaViewer\Widgets TraceAlphaViewer\Models TraceAlphaViewer\Views
rg --files
```

## Regles Git

- `main` doit representer la derniere version utilisable du projet.
- Conserver les anciens etats par l'historique Git normal et les tags, pas par des branches d'archive.
- Utiliser une branche courte seulement pour un travail risque, puis revenir sur `main`.
- Pour un travail risque, pousser la branche de travail apres chaque etape fonctionnelle terminee et validee, afin de garder des points de retour sur GitHub. Integrer a `main` seulement apres validation finale ; les controles obligatoires restent applicables a chaque commit.
- Ne pas pousser les fichiers de traces sur GitHub : pas de `*.old`, pas de gros `.txt` de trace.
- Avant chaque commit, verifier `git status --short` et la liste des fichiers indexes.
- Si des traces sont indexees, les retirer avant de committer.
- Les traces restent locales pour validation, sauf demande explicite de versionner un petit echantillon precis.

### Commit et push automatiques

Cette autorisation est permanente pour les prochaines interventions Codex sur ce projet, y compris dans une nouvelle conversation. A la fin de chaque tache ayant modifie le projet, effectuer automatiquement le commit et le push sans demander de confirmation, sauf si une autorisation technique est obligatoire ou si l'utilisateur donne une instruction contraire pour la tache. Une question, un plan ou une tache sans modification ne cree aucun commit.

Procedure obligatoire, dans cet ordre :

1. Verifier que la tache est terminee et relire les modifications pour reperer les erreurs evidentes.
2. Executer `python TraceAlphaViewer\Tools\validate_all.py`, ainsi que la compilation et les validations specifiques deja exigees dans ce fichier. Signaler les controles ignores faute de trace locale. Si un test echoue ou si une validation obligatoire est impossible, ne pas committer ni pousser ; expliquer le blocage.
3. Examiner `git status --short`, `git diff`, `git diff --cached` et `git diff --cached --name-only`. Verifier aussi les fichiers non suivis susceptibles d'appartenir a la tache et lancer `git diff --check`.
4. Indexer uniquement les fichiers ou morceaux de modification lies a la tache. Preserver les changements utilisateur preexistants, y compris ceux deja indexes ; ne jamais utiliser un ajout global aveugle comme `git add .` ou `git add -A`. Si un fichier contient des modifications melangees, indexer seulement les morceaux autorises. Le commit final ne doit contenir aucune modification sans rapport avec la tache.
5. Exclure les secrets, tokens, cles, fichiers d'authentification, traces locales, fichiers temporaires et artefacts non demandes. Respecter les exclusions de traces et l'exception d'echantillon precis deja definies plus haut. Inspecter le contenu a committer sans afficher de donnees sensibles.
6. Creer un commit avec un message clair et descriptif en francais. Ne pas contourner les hooks Git ni modifier l'identite Git pour contourner un echec. Si le commit echoue, signaler la cause et ne pas pousser.
7. Verifier la branche courante et le remote `origin` avant le push. La configuration verifiee a l'installation est `main` avec suivi `origin/main`, et `origin` pointe vers le depot GitHub `Superbobopo/TraceAlphaviewer`. Cette information est un constat, pas une obligation de pousser sur `main` : toujours pousser la branche courante vers la branche de meme nom sur `origin` avec `git push origin <branche_courante>`.
8. Examiner tous les commits locaux et leurs changements qui seraient envoyes par le push. Ne pas envoyer de commits contenant des fichiers sensibles, des traces interdites ou des modifications non autorisees sans rapport avec la tache. Si la destination est ambigue, si la branche est detachee, si `origin` ne correspond plus au depot GitHub attendu ou si les commits a envoyer ne peuvent pas etre verifies, ne pas pousser et expliquer le blocage sans choisir une autre destination.
9. Si le push echoue, conserver le commit local et signaler l'echec sans forcer l'operation. Ne jamais utiliser `git push --force`, `--force-with-lease`, ni aucune autre option de force. Ne jamais ecraser, supprimer ou reecrire l'historique Git, ni annuler les changements utilisateur pour rendre le push possible.
10. A la fin de la reponse, confirmer separement le resultat du commit et celui du push, avec le message du commit et son identifiant. Ne jamais annoncer un push reussi sans l'avoir verifie ; preciser les erreurs ou validations restantes.

Exception d'installation : cette mise a jour des instructions reste locale, sans commit ni push uniquement pour l'installer. Inclure cette mise a jour dans le prochain commit d'une tache validee necessitant un commit, sauf instruction contraire de l'utilisateur. Cette inclusion est explicitement autorisee. Ne modifier aucune configuration globale, memoire personnelle ou hook Git pour mettre en place ce fonctionnement.

## Fichiers importants

- La construction Windows utilise `TraceAlphaViewer.spec` et `Tools/build_exe.py` ; inclure les ressources customtkinter, le logo et le build React, jamais les traces locales.
- En mode .exe, lancer les workers via `--loading-worker` avant les imports Tk ; recuperer le pipe Windows lorsque `sys.stdout` est absent. Les sessions restent dans `%LOCALAPPDATA%/TraceAlphaViewer/.trace_work`, hors du bundle temporaire.

- `TraceAlphaViewer/Main.py` : point d'entree customtkinter.
- `TraceAlphaViewer/Views/traceView.py` : viewer principal, navigation, player et callbacks.
- `TraceAlphaViewer/Widgets/machine_canvas.py` : dessin machine et logique de placement/echelle.
- `TraceAlphaViewer/Widgets/reference_panel.py` : liste des references/boites et navigation vers leur premiere apparition.
- `TraceAlphaViewer/Widgets/state_table.py` : etats tapis, capteurs et codes firmware.
- `TraceAlphaViewer/Parser/trace_parser.py` : parser `.old`, evenements, cycle des boites, parsing T5.
- `TraceAlphaViewer/Models/state.py` : `MachineState`, `BoxInfo`, `MachineEvent`.
- `TraceAlphaViewer/Models/diagnostic.py` : extraction des incidents.
- `TraceAlphaViewer/Models/diagnostic_knowledge.py` : base de connaissance terrain.
- `TraceAlphaViewer/Models/reference_index.py` : index references/boites utilise par l'onglet References.

## Regles de codage

- Lire le code existant avant de modifier ; ne pas supposer les conventions.
- Garder les changements scopes au bug ou a la fonctionnalite demandee.
- Utiliser `apply_patch` pour les editions manuelles.
- Ne jamais annuler des changements utilisateur non lies.
- Ne pas faire de refactor large pendant une correction trace/rendu.
- Pour les donnees structurees de trace, preferer regex/helpers dedies plutot que du parsing fragile par positions ad hoc.
- Apres une correction T5, valider par script sur frames en plus du controle visuel.
- Ne jamais afficher de secrets, tokens, cles, fichiers d'authentification ou contenu prive hors projet.
- Pour une trace longue ou un document metier, relire les lignes sources ciblees avant de conclure.
- Si un bug revient, renforcer l'invariant dans ce fichier au lieu de refaire une correction fragile.
- Les fleches tapis utilisent les couleurs communes actif/repos/erreur ; ne pas reutiliser les couleurs capteurs pour elles.

## Invariants parser

- L'identite boite suit le cycle Alpha, pas seulement le CIP/barcode.
- Priorite de matching : `id_alpha`, puis `id_b`, puis barcode uniquement si unique.
- Ne jamais mettre a jour ou supprimer toutes les boites qui partagent le meme barcode.
- L'index References conserve une fiche par cycle boite : un CIP partage ne suffit jamais a fusionner des identites differentes. Les alias de reference peuvent designer plusieurs fiches ; le fallback barcode doit etre unique et encore present dans le cycle courant.
- L'index References ignore les boites sans `id_alpha`, `id_b`, barcode ni `source_ref` avant toute allocation de fiche ; creer puis filtrer des fiches `UNKNOWN` rend le chargement des grosses traces quadratique.
- Une re-identification CB2 conserve le parcours et `source_ref`, mais remplace le barcode de la fiche par le CIP identifie pour permettre sa recherche.
- `box_in_EA` represente la boite sur C4 / CB1.
- `box_on_T3` represente la boite sur T3 / C5 / CB2.
- `box_on_T4` represente la boite sur T4 / C6.
- `boxes_on_T5` represente les boites T5/BdD controlees par `IdA`.
- `BoxInfo.id_b` est l'identite pre-T5 (`Nboite` / `idB`).
- `BoxInfo.id_alpha` est l'identite T5/BdD utilisee par les lignes robot.
- `BoxInfo.source_ref` conserve la reference initiale `ALPHA-INC-xxx` quand CB2 identifie ensuite le vrai produit.
- `CB1: ajout Hist_LectCB` concerne EA/C4 uniquement.
- `CB2: ajout Hist_LectCB` concerne T3/C5 uniquement.
- `CubeStop:Y` indique que la trace/machine utilise le volet CubeStop entre EA/C4 et T3.
- `CubeStop:N` signifie qu'il ne faut ni afficher le volet ni declencher de diagnostic CubeStop specifique.
- `mvt CubeStop vers le HAUT` autorise le passage EA/C4 vers T3 ; `mvt CubeStop vers le BAS` accompagne le transfert T2 vers EA/C4.
- `idCB2: Identif. sur le lecteur1 Ok ... (Nboite=X)` assigne `idB=X` seulement a la boite deja sur T3.
- Ne jamais assigner un `Nboite/idB` a une ancienne boite CB2 cachee si `box_on_T3` est vide.
- `ALPHA:T5-LIST-PACK` est une source fiable de positions multi-boites T5.
- `ALPHA:T5-LIST-PACK` peut utiliser `<Dc2>` ou le separateur reel `chr(182)`.
- Une boite issue de `ALPHA:T5-LIST-PACK` a une position robot stable fiable.

## Regles de rendu T5

- `pT5` est un encodeur moteur, jamais une coordonnee absolue de boite.
- `pT5` peut seulement fournir un offset visuel temporaire entre deux positions stables.
- Les positions T5 stables viennent des lignes `MAJ`, de `ALPHA:T5-LIST-PACK`, ou des deplacements BdD confirmes.
- `BoxInfo.x_pos` est la position stable Alpha ; `BoxInfo.t5_visual_x_pos` est seulement la base visuelle continue.
- Ne pas changer les rectangles canvas `L['T4']` et `L['T5']` pour calibrer les tapis.
- Calibrage physique T4 : longueur `500 mm`, C6 a `436 mm` depuis la butee/debut T4.
- Calibrage physique T5 : longueur `770 mm`, C9 a `310 mm` depuis la butee T5.
- Conserver les calibrages T5 metier sauf demande explicite : `T5_X_BUTEE = 942`, `T5_X_MAX = 1750`, `T5_BOX_DIM_SCALE = 0.75`, `_T5_ENTRY_X = 1060`.
- `T5_X_BUTEE` correspond au cote butee / mesure hauteur, a droite du tapis.
- C9 est l'entree T4 vers T5 ; il est aligne visuellement sur le bord gauche de T4, sans changer l'echelle physique T5.
- Certaines traces utilisent de grands `X` Alpha pour T5 : les normaliser par distance a la butee observee, jamais avec un clamp qui transforme `X > butee` en butee.
- Une suppression T5 par le robot signifie normalement que la boite a ete prise physiquement ; la classer en evenement `info`, pas en erreur.
- `BoxInfo.t5_after_c9=True` est un etat de cycle/diagnostic, pas une contrainte geometrique.
- Les boites T5 suivent toutes le meme tapis : tout mouvement signe de T5 deplace le groupe, y compris les boites deja passees par C9.
- Le rendu doit conserver les positions relatives issues de `x_pos`, `t5_visual_x_pos`, `ALPHA:T5-LIST-PACK` et des deplacements BdD confirmes.
- Avant tout reset de `t5_visual_offset_mm`, committer l'offset courant dans `t5_visual_x_pos` via le repere visuel normalise, jamais par addition directe sur un grand `X` Alpha.
- Une ligne BdD `Deplace toutes les boites ...` met a jour les positions stables des boites deja etablies sur T5, mais conserve la continuite visuelle deja animee par `pT5`.
- Une nouvelle boite `t5_entry_aligned=True` attend sa premiere `MAJ` stable pour changer `x_pos`, mais elle suit visuellement le mouvement T5 comme le reste du tapis.
- Ne pas ajouter de clamp final sur C9 ou sur la butee : les dimensions physiques et les positions Alpha doivent porter le rendu.
- `MAJ (BUTEE-T5)` peut remettre `t5_after_c9=False` seulement pour la meme boite active revenue en cycle butee.
- `MAJ (APRES-MESURE-LARG)` recale toujours `x_pos` et `t5_visual_x_pos` sur le `X` trace de la boite mesuree, puis marque cette boite `t5_after_c9=True`.
- Une activation C9 de la boite active marque cette boite `t5_after_c9=True`.
- Une nouvelle arrivee T4->T5 demarre `t5_after_c9=False` et `t5_entry_aligned=True` jusqu'a position stable.
- Une boite `t5_entry_aligned=True` reste sous l'axe T4 tant qu'aucun offset visuel T5 n'existe ; si `pT5` fournit un offset, elle peut suivre ce mouvement sans changer son `x_pos` stable.
- L'interpolation de lecture est autorisee, mais jamais a travers les evenements T5 discrets (`MAJ`, `Deplace toutes`, `AjoutBtT5`, suppression robot, `ALPHA:T5-LIST-PACK`).
- C9/`width_mm` se dessine sur l'axe horizontal T5.
- C6/`length_mm` se dessine dans l'epaisseur verticale T5.
- `t5_footprint_mm` de `ALPHA:T5-LIST-PACK` est seulement un fallback si les dimensions C6/C9 manquent.
- Les couleurs de diagnostic mesure Alpha changent uniquement le remplissage des boites T5 ; elles ne doivent pas recalibrer T5 ni modifier les dimensions/positions.
- La ligne jaune de position `pT5` ne doit pas etre reintroduite dans le canvas.
- Le point `Mesure H.` / `LzB` reste hors tapis pour ne pas etre masque par les boites.

## UI et navigation

- Les boutons player gardent des icones compactes.
- `|<` / `>|` : premiere/derniere frame.
- `<` / `>` : frame precedente/suivante.
- Le bouton lecture utilise `Play` / pause selon l'etat de l'interface existante.
- `Err<` / `Err>` : erreur precedente/suivante.
- `<<` et `>>` pres du slider ralentissent/accelerent la lecture.
- Le slider de vitesse est logarithmique.
- Le resize handle des details reste sous la barre player.
- Le chargement demarrage utilise toujours le comportement `Precision trace` (`min_dt=0.0`).
- Pendant le chargement depuis l'accueil, afficher l'etape en cours sous la barre : lecture trace, construction evenements, diagnostic, references, preparation affichage.
- L'ouverture d'une trace seule attend diagnostics et references avant affichage ; ne pas afficher une vue partiellement chargee.
- Les onglets bas sont `Diagnostic`, `Erreur`, `Evenements`, `Trace`, avec `Erreur` filtre sur `severity == "error"`.
- Dans l'onglet `Diagnostic`, le panneau gauche affiche la vue globale de tous les diagnostics au chargement ; le detail d'un incident s'affiche seulement apres selection.
- La vue globale `Diagnostic` doit rester une synthese groupee par type de probleme, pas une liste de chaque occurrence.
- La synthese globale `Diagnostic` doit faire ressortir les priorites et les diagnostics metier importants comme `UNKNOWN` et `CAM-NO-READ`.
- Le bouton `Rapport web` du diagnostic genere une page HTML locale interactive ; l'export PDF doit telecharger un PDF direct de la synthese globale, sans ouvrir la fenetre d'impression.
- Le rapport web/PDF doit rester lisible comme un rapport terrain : synthese visuelle, priorites visibles, groupes compacts, pas de pavés repetitifs ni de PDF texte brut.
- Le rapport web React se reconstruit depuis `TraceAlphaViewer/report_app` avec `npm install` puis `npm run build`; si le build statique manque, le generateur Python garde un fallback HTML local.
- Les titres de diagnostics eT doivent utiliser la table partagee `Models/et_codes.py`, identique a la table d'etats, avant de tomber sur un libelle generique.
- Raccourcis clavier : Left/Right, Space, Home/End, `e` / `E`.
- La saisie dans un champ de recherche ne declenche pas les raccourcis du player.
- Les workers de chargement transmettent leurs resultats par une file ; les appels Tk et `after` restent sur le thread UI. Fermer une vue annule ses callbacks ; remplacer une trace brute invalide les anciens resultats de chargement.
- Une vue abandonnee est detruite pour liberer ses frames ; seule une vue explicitement gardee comme `_return_view` reste disponible.
- Le canvas reutilise ses primitives sans changer leur ordre, leurs options ni la geometrie T5. Comparer le rendu reutilise au dessin complet avant toute modification de ce mecanisme.
- Les lignes issues des frames parser sont ordonnees par numero de fichier ; les recherches de contexte diagnostic utilisent cette propriete pour borner leurs parcours, avec des limites inclusives et l'ordre des libelles conserve.
- La trace brute est inseree par blocs avec un appel Tk groupe conservant les tags de chaque segment. Garder les callbacks entre blocs et leur annulation au remplacement ou a la fermeture.
- Le chargement fichier/dossier utilise un processus autonome qui importe uniquement le parser et les modules metier, jamais Tk ni `Views`. La reception/deserialisation reste hors du thread Tk, avec une file bornee et un identifiant par worker.
- `FrameStore` conserve toutes les frames par blocs de 500, avec deux blocs en cache et un index compact des lignes. Ne pas recreer une liste ni parcourir toute cette sequence dans un constructeur de viewer. Les filtres metier et rapports utilisent un lecteur independant dans un worker.
- Les fichiers `.trace_work/session-*` sont un stockage temporaire de session, jamais un cache de reouverture. Leur proprietaire annule ses workers et ferme ses lecteurs a sa destruction ; le nettoyage attend hors du thread Tk. Une vue `_return_view` conserve sa session, un popup de dossier l'emprunte sans la fermer.
- La reception UI utilise un budget d'environ 8 ms, la trace brute une file bornee et des blocs de 500 lignes maximum, les listes une insertion progressive groupee. Attendre la preparation des analyses/listes avant de quitter l'accueil. Annuler aussi les callbacks de mise en page et retirer les bindings a la destruction des panneaux.
- Les raccourcis se lient via `tkinter.Misc.bind/unbind` avec leur identifiant, pour retirer seulement les callbacks de la vue ; les wrappers `CTkFrame.bind` ne rendent pas cet identifiant et peuvent conserver une vue detruite.

## Diagnostics terrain

- `Temps depuis RESET carte ALPHA` est un compteur d'uptime : une valeur elevee et croissante est normale.
- Un reset carte Alpha est compte uniquement quand ce compteur chute vers `0..10 mn` pendant la trace ; les releves bas consecutifs apres la chute appartiennent au meme reset.
- Le rapport doit afficher le nombre de resets carte Alpha et la duree couverte par la trace, jamais un ratio par nombre de boites.
- En cas de reset carte Alpha, faire verifier en priorite les shunts CubeStop/balance, leur cablage, les masses et l'alimentation.

- Une initialisation T4 isolee ou periodique apres beaucoup de boites est normale.
- Trois lignes `InitMachine: demande initialisation de T4 ...` d'affilee indiquent un probleme T4/C6 probable.
- Si C6 reste actif pendant ces init T4 repetees, suspecter C6 trop bas, signal bloque actif ou objet devant le capteur.
- Si C6 n'est pas toujours actif pendant ces init T4 repetees, suspecter C6 trop haut/HS/mal positionne, moteur T4 qui patine ou rouleau moteur non entraine.
- Les diagnostics camera unknown comptent les boites finales creees en `ALPHA-INC`, `ALPHA-DET` ou `ALPHA-DIF` avec `-unknow`, pas les unknown temporaires relues ensuite.
- Une unknown CB1 relue correctement par CB2 ne compte pas comme unknown finale ; une unknown finale vue par CB1 et CB2 doit etre classee `CB1+CB2`.
- Le ratio principal camera unknown compte uniquement les boites `CB1+CB2`; `CB1 seul`, `CB2 seul` et `non attribue` restent du contexte.
- Seuil diagnostic camera unknown : plus de 7% des boites passees d'apres les `Hist_LectCB`.
- CB1 regroupe les cameras 1, 2, 4, 5, 6 ; CB2 correspond a la camera 3.
- Une camera attendue sans aucune reussite `PR/Soh/N` sur une trace significative indique une camera potentiellement HS, deconnectee ou non contributive.
- Si CubeStop est commande `HAUT`, que le transfert EA->T3 demarre, mais que `C4` reste actif et `C5` reste inactif jusqu'a l'erreur ou la fin de course T3, suspecter CubeStop bloque mecaniquement en bas, ejecteur C4 inefficace, rail bloque ou C4 faux actif.

## Checklist de validation

- Compiler les fichiers principaux avec la commande `py_compile` indiquee plus haut apres toute modification Python.
- Lancer `python TraceAlphaViewer\Tools\validate_all.py` pour regrouper les controles metier et les regressions du viewer ; signaler les controles ignores faute de trace locale.
- Pour une optimisation de chargement, mesurer les grosses traces separement et sans profileur avec `Tools/benchmark_loading.py` ; utiliser `--revision` et `--compare-results` pour comparer tous les diagnostics et references. Les exports JSON restent locaux.
- Pour la reactivite, mesurer l'ouverture depuis l'accueil avec `--ui-latency --exercise-window --require-responsive` : percentile 95 sous 100 ms, maximum sous 500 ms. Ajouter `--verify-frames --verify-analyses` pour comparer frames/evenements, six filtres et rapport hors mesure, et `--check-navigation` pour la recherche CIP et le player. Garder au moins le gain x2 face a la version precedant les premieres optimisations.
- Controler `TracAlpha1_012.old` autour de `24|08:31:15` a `08:31:18` : l'IBUPROFENE suit le mouvement T5 sans saut visuel.
- Controler `TracAlpha1_012.old` autour de `24|08:31:52` a `08:31:55` : meme invariant sur le second IBUPROFENE.
- Controler une sequence multi-boites vers `08:15:02` : les boites suivent le meme tapis et gardent leur espacement relatif.
- Controler une sequence de tassage : une nouvelle boite T4->T5 va vers la butee, et les boites deja sur T5 reculent aussi selon le meme mouvement physique.
- Controler les lignes `MAJ (APRES-MESURE-LARG)` : elles changent la position stable/dimensions sans saut visuel brutal.
- Controler visuellement T5 : transfert T4->T5, tassage butee, passage C9, retour repos, espacement multi-boites.
- Controler les lectures inconnues : beaucoup de `ALPHA-INC`, `ALPHA-DET` ou `-unknow` doivent etre visibles comme indice camera/datamatrix.
- Controler visuellement T2 si modifie : fleche grise a l'arret, coloree pendant les codes moteur actifs.
- Si un controle echoue, inspecter d'abord l'etat parser (`BoxInfo`, `MachineState`) avant de toucher aux constantes canvas.

## Definition de termine

- Le changement demande est implemente ou la question est repondue clairement.
- Si du code Python a change, la compilation `py_compile` a ete lancee ou l'impossibilite est expliquee.
- Si T5, le parser ou le canvas a change, les scenarios trace critiques ont ete controles.
- Les erreurs ou limites restantes sont listees explicitement.
- La documentation projet est mise a jour quand une nouvelle regle evite une repetition d'erreur.
- Les fichiers hors depot ou les memoires personnelles ne sont pas modifies sans demande explicite.
