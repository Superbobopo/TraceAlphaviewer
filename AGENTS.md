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
- Le manuel debutant est dans `docs/manuel-utilisateur/index.html` ; son PDF est genere depuis ce meme HTML. Apres un changement visible de l'interface, verifier les instructions, reperes et captures concernes. Regenerer les captures et le PDF seulement si leur contenu devient obsolete. Utiliser alors `Tools/generate_user_manual.py --captures --pdf` avec des donnees fictives et une capture du HWND du viewer uniquement ; ne jamais capturer le bureau ou publier les traces terrain. Controler la pagination et les images du PDF regenere avant livraison.

## Lancement et commandes

Depuis la racine du depot :

```powershell
python TraceAlphaViewer\Main.py
```

Pour une correction ciblee, compiler uniquement les fichiers Python modifies avec `python -m py_compile <fichiers_modifies>`. Pour une validation globale, compiler aussi les fichiers principaux :

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
- Pour un travail risque, conserver les etapes validees localement ; aucun commit ni push intermediaire automatique. Integrer a `main` seulement apres validation finale ; les controles obligatoires restent applicables a chaque commit demande.
- Ne pas pousser les fichiers de traces sur GitHub : pas de `*.old`, pas de gros `.txt` de trace.
- Avant chaque commit, verifier `git status --short` et la liste des fichiers indexes.
- Si des traces sont indexees, les retirer avant de committer.
- Les traces restent locales pour validation, sauf demande explicite de versionner un petit echantillon precis.

### Commit et push sur demande explicite

Cette regle s'applique aux prochaines interventions Codex sur ce projet, y compris dans une nouvelle conversation, et remplace l'ancienne autorisation de commit et push automatiques. Laisser les modifications locales sans les indexer automatiquement. L'utilisateur effectue lui-meme le commit et le push en fin de journee ; ne pas les declencher a une heure donnee ni a la fin d'une tache. Effectuer une indexation, un commit ou un push uniquement sur demande explicite de l'utilisateur. Une demande de commit n'autorise pas implicitement le push. Preserver les changements deja indexes par l'utilisateur.

Lorsqu'un commit ou un push est explicitement demande, appliquer les etapes pertinentes ci-dessous, dans cet ordre. Les validations proportionnees restent applicables aux modifications meme sans commit :

1. Verifier que la tache est terminee et relire les modifications pour reperer les erreurs evidentes.
2. Appliquer la validation proportionnee de la checklist ci-dessous. Reutiliser les controles deja reussis si aucune modification ulterieure ne peut affecter leur resultat ; aucun second passage systematique avant le commit. Signaler les controles pertinents ignores faute de trace locale. Si un test pertinent echoue ou si une validation requise pour le changement est impossible, ne pas committer ni pousser ; expliquer le blocage.
3. Examiner `git status --short`, `git diff`, `git diff --cached` et `git diff --cached --name-only`. Verifier aussi les fichiers non suivis susceptibles d'appartenir a la tache et lancer `git diff --check`.
4. Indexer uniquement les fichiers ou morceaux de modification lies a la tache. Preserver les changements utilisateur preexistants, y compris ceux deja indexes ; ne jamais utiliser un ajout global aveugle comme `git add .` ou `git add -A`. Si un fichier contient des modifications melangees, indexer seulement les morceaux autorises. Le commit final ne doit contenir aucune modification sans rapport avec la tache.
5. Exclure les secrets, tokens, cles, fichiers d'authentification, traces locales, fichiers temporaires et artefacts non demandes. Respecter les exclusions de traces et l'exception d'echantillon precis deja definies plus haut. Inspecter le contenu a committer sans afficher de donnees sensibles.
6. Creer un commit avec un message clair et descriptif en francais. Ne pas contourner les hooks Git ni modifier l'identite Git pour contourner un echec. Si le commit echoue, signaler la cause et ne pas pousser.
7. Verifier la branche courante et le remote `origin` avant le push. La configuration verifiee a l'installation est `main` avec suivi `origin/main`, et `origin` pointe vers le depot GitHub `Superbobopo/TraceAlphaviewer`. Cette information est un constat, pas une obligation de pousser sur `main` : toujours pousser la branche courante vers la branche de meme nom sur `origin` avec `git push origin <branche_courante>`.
8. Examiner tous les commits locaux et leurs changements qui seraient envoyes par le push. Ne pas envoyer de commits contenant des fichiers sensibles, des traces interdites ou des modifications non autorisees sans rapport avec la tache. Si la destination est ambigue, si la branche est detachee, si `origin` ne correspond plus au depot GitHub attendu ou si les commits a envoyer ne peuvent pas etre verifies, ne pas pousser et expliquer le blocage sans choisir une autre destination.
9. Si le push echoue, conserver le commit local et signaler l'echec sans forcer l'operation. Ne jamais utiliser `git push --force`, `--force-with-lease`, ni aucune autre option de force. Ne jamais ecraser, supprimer ou reecrire l'historique Git, ni annuler les changements utilisateur pour rendre le push possible.
10. Si un commit ou un push a ete demande, confirmer separement le resultat des operations demandees, avec le message et l'identifiant du commit concerne. Ne jamais annoncer un push reussi sans l'avoir verifie ; preciser les erreurs ou validations restantes.

Cette mise a jour des instructions reste elle aussi locale, sans indexation, commit ni push automatiques. Ne modifier aucune configuration globale, memoire personnelle ou hook Git pour mettre en place ce fonctionnement.

## Fichiers importants

- La construction Windows utilise `TraceAlphaViewer.spec` et `Tools/build_exe.py` ; inclure les ressources customtkinter, le logo et le build React, jamais les traces locales.
- Reconstruire le .exe uniquement sur demande explicite de l'utilisateur pour cette construction. Une correction, une fonctionnalite, une validation ou une modification du packaging n'autorise pas sa reconstruction automatique. Cette regle s'applique aussi aux prochaines conversations. Le push GitHub reste soumis a une demande explicite distincte, selon les regles Git ci-dessus.
- Refuser la construction du .exe si Tcl/Tk est inaccessible ; ne jamais accepter l'exclusion silencieuse de tkinter par PyInstaller. Nettoyer son cache et valider le demarrage masque du binaire construit avant livraison.
- Les dossiers restent en Python par defaut, comme une trace seule. Le moteur Rust est experimental (`TRACE_ALPHA_FOLDER_ENGINE=rust`) ; ne le generaliser que si un gain significatif est mesure sur le chargement complet, conversion et analyses comprises. Conserver le regroupement Alpha/pharmacie et les limites des segments dans les deux modes.
- Le bouton dossier utilise uniquement `native/folder_engine` (protocole JSONL version 1, blocs MessagePack de 500 frames maximum). Le bouton trace seule conserve le parser Python. Construire avec `python TraceAlphaViewer/Tools/build_folder_engine.py --bootstrap --test` ; la chaine locale et le binaire sont ignores par Git, sans modifier le PATH utilisateur. Le .exe embarque le moteur sous `bin` ; aucun fallback silencieux vers Python si le moteur manque.
- Le catalogue dossier lit toutes les declarations de bases et regroupe par paire de noms complets Alpha/BASEFIC sans tenir compte de leur casse ou repertoire. Identite/calendrier incertains et recouvrements ambigus restent isoles. Chaque fichier est un segment independant : aucune identite boite, attente parser ou sequence capteur ne franchit cette limite ; conserver fichier et ligne source dans navigation et preuves. Les dossiers internes `.trace_work`, `.git`, `.venv` et `node_modules` sont exclus du parcours. Les sous-dossiers inaccessibles sont signales sans interrompre le catalogue.
- Les sources du catalogue portent une empreinte des octets verifiee avant le parsing natif ; taille et date de modification restent controlees apres. Une source changee impose de rouvrir le dossier, sans publier un resultat de groupe partiel ou une identite perimee.
- En mode .exe, lancer les workers via `--loading-worker` avant les imports Tk ; recuperer le pipe Windows lorsque `sys.stdout` est absent. Les sessions restent dans `%LOCALAPPDATA%/TraceAlphaViewer/.trace_work`, hors du bundle temporaire.

- `TraceAlphaViewer/Main.py` : point d'entree customtkinter.
- `TraceAlphaViewer/Views/traceView.py` : viewer principal, navigation, player et callbacks.
- Dans le viewer principal, masquer le champ de recherche brute au demarrage et garder sa loupe a cote du bouton Afficher/Masquer details. La loupe rouvre les details si besoin ; masquer le champ conserve la saisie et les resultats. Les autres usages de `TracePanel` gardent leur recherche visible par defaut.
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

- Les relectures CB1 apres un echec EA->T3 restent dans le meme passage physique. La demande EA->T3 ouvre une attente ; sa confirmation ou la progression physique suivante la consomme. Une nouvelle lecture seule et les compteurs Hist_LectCB ne prouvent pas une nouvelle boite. Conserver toutes les tentatives et erreurs comme preuves.
- Une copie de trace est exclue avant parsing seulement apres confirmation d'un entete date identique et de lignes contigues strictement identiques, horodatages compris. Conserver les numeros de ligne source et la correspondance des plages copiees dans `FrameStore.source_metadata` ; le clic sur une copie rejoint la ligne originale. Ne jamais dedupliquer des messages isoles ni modifier le fichier brut.
- La boite provisoire T4->T5 porte `t5_transfer_id` jusqu'a sa creation BdD, qui consomme l'attente. Ce jeton suit les clones et listes T5 et relie la premiere attribution IdA sans fusionner des IdA differents. Un transfert explicitement anonyme n'herite pas de l'identite camera ni de la BdD d'une autre boite. Recharger la trace et regenerer les anciens rapports pour recalculer les compteurs.

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
- `identified_barcode`/`identified_name` conservent le produit confirme, distinct de `barcode` (reference machine courante) et de `source_ref`. Une reference contradictoire marque le cycle ambigu pour les mesures ; ne jamais lui attacher les dimensions d'une ancienne recherche BdD d'un autre produit.
- Les champs de provenance produit/BdD/T4C/T4T doivent suivre `clone`, les transferts et les listes T5. Le resume T4C/T4T se rattache uniquement au transfert T4->T5 en attente, par identite unique, et consomme cette attente ; ne jamais le reporter sur la prochaine boite T3/T4.
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
- Les statuts/couleurs de mesure partagent `Models/dimension_check.py` : longueur violet, largeur turquoise, hauteur jaune, plusieurs axes rouge ; `c9_error` reste prioritaire et `bad` reste rouge.

## UI et navigation

- L'en-tete web/PDF affiche la pharmacie et le numero Alpha depuis `FrameStore.source_metadata.identity`, prepare dans le worker aussi pour une trace seule. Reutiliser l'identification des bases du catalogue, lire toute la source pour exclure les contradictions et conserver les zeros initiaux. Sans numero fiable, garder le nom technique Alpha ; sans paire de bases unique, ne pas inventer d'identite. Aucun parcours des frames ou du fichier dans Tk pour cet affichage.

- Le rapport web utilise une colonne camera compacte a droite des 1360 px ; sous ce seuil elle passe sous les priorites. Les orientations gardent quatre references visibles, avec detail complet depliable et pagination conservee. Ne pas dupliquer le bandeau robot dans le web/PDF lorsque son diagnostic figure deja dans les trois premieres priorites ; garder le detail et la navigation.
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
- Pour une meme vue, reutiliser le rapport deja prepare et son URL locale sans worker ni relecture des preuves. Verifier les fichiers HTML/JSON et ressources avant reutilisation ; regenerer si necessaire. Le cache reste propre a la vue source.
- Le rapport web/PDF doit rester lisible comme un rapport terrain : synthese visuelle, priorites visibles, groupes compacts, pas de pavés repetitifs ni de PDF texte brut.
- Le rapport web React se reconstruit depuis `TraceAlphaViewer/report_app` avec `npm install` puis `npm run build`; si le build statique manque, le generateur Python garde un fallback HTML local.
- Les titres de diagnostics eT doivent utiliser la table partagee `Models/et_codes.py`, identique a la table d'etats, avant de tomber sur un libelle generique.
- Dans l'onglet Erreur, afficher a droite des lignes la signification des couples tapis/code eT via `Models/et_codes.py`, sans modifier les titres des evenements ni repeter un libelle deja present. Les clics et la surbrillance couvrent aussi la signification.
- Raccourcis clavier : Left/Right, Space, Home/End, `e` / `E`.
- La saisie dans un champ de recherche ne declenche pas les raccourcis du player.
- La recherche brute reste masquee au depart ; la loupe du player ou Ctrl+F l'ouvre, Echap la ferme sans effacer la saisie. La vue globale Diagnostic ne repete pas le bilan detaille des mesures ; les details des diagnostics et le rapport le conservent.
- Les workers de chargement transmettent leurs resultats par une file ; les appels Tk et `after` restent sur le thread UI. Fermer une vue annule ses callbacks ; remplacer une trace brute invalide les anciens resultats de chargement.
- Une vue abandonnee est detruite pour liberer ses frames ; seule une vue explicitement gardee comme `_return_view` reste disponible.
- Le canvas reutilise ses primitives sans changer leur ordre, leurs options ni la geometrie T5. Comparer le rendu reutilise au dessin complet avant toute modification de ce mecanisme.
- Les lignes issues des frames parser sont ordonnees par numero de fichier ; les recherches de contexte diagnostic utilisent cette propriete pour borner leurs parcours, avec des limites inclusives et l'ordre des libelles conserve.
- La trace brute est inseree par blocs avec un appel Tk groupe conservant les tags de chaque segment. Garder les callbacks entre blocs et leur annulation au remplacement ou a la fermeture.
- Les listes Evenements, Erreur et References affichent des pages de 500 elements ; filtres et recherches gardent toute leur portee. Le worker prepare leurs index de lignes ; une navigation vers une ligne rejoint sa page. Un changement de filtre revient a la premiere page et annule les anciennes insertions. Attendre les analyses et les premieres pages avant d'afficher le viewer.
- Les analyses d'un segment de dossier partagent un parcours de ses frames pour evenements, mesures, references, lignes diagnostiques et attentes. Les accumulateurs sont reinitialises a chaque fichier ; conserver le cache FrameStore de deux blocs. Le calendrier partage reste propre aux lignes immuables du segment, jamais un cache entre traces.
- Sous Windows, le worker dossier analyse au plus deux segments a la fois dans des sous-processus sans Tk, avec lecteurs independants et reunion des resultats dans l'ordre des fichiers. Les requetes restent sous la session proprietaire. Un Job Object prive tue tous les descendants si le worker parent est annule ; ne pas generaliser le parallelisme sans ce nettoyage et les comparaisons completes.
- Les lignes diagnostiques du worker dossier retiennent une projection immuable timestamp/timestamp_str/C6, pas les MachineState complets ni leurs boites. Si un diagnostic a besoin d'un nouveau champ, etendre explicitement cette projection et verifier l'equivalence des incidents ; ne pas reintroduire la retention de toutes les frames du segment.
- Les prefiltres de diagnostics doivent couvrir toutes les regex et lignes de controle de leur domaine ; conserver les controles de temps, interruptions et fins de contexte sur toutes les lignes avant de les ignorer. Le bilan des boites robot se calcule une fois par segment et se partage avec le diagnostic et le regroupement ; conserver le repere absolu des groupes et la compatibilite d'une trace seule.
- Les raccourcis des mesures et references comparent uniquement des etats consecutifs strictement identiques, avec identites fortes uniques et alias non ambigus. Leur signature couvre tous les champs lus, y compris exclusions et provenance ; l'etendre avec toute nouvelle dependance. Les references continuent de mettre a jour leurs premieres/dernieres lignes et heures. Ne jamais utiliser les seules positions du tapis ou le seul CIP pour sauter une mise a jour.
- Le chargement fichier/dossier utilise un processus autonome qui importe uniquement le parser et les modules metier, jamais Tk ni `Views`. La reception/deserialisation reste hors du thread Tk, avec une file bornee et un identifiant par worker.
- `FrameStore` conserve toutes les frames par blocs de 500, avec deux blocs en cache et un index compact des lignes. Ne pas recreer une liste ni parcourir toute cette sequence dans un constructeur de viewer. Les filtres metier et rapports utilisent un lecteur independant dans un worker.
- Les fichiers `.trace_work/session-*` sont un stockage temporaire de session, jamais un cache de reouverture. Leur proprietaire annule ses workers et ferme ses lecteurs a sa destruction ; le nettoyage attend hors du thread Tk. Une vue `_return_view` conserve sa session, un popup de dossier l'emprunte sans la fermer.
- La reception UI utilise un budget d'environ 8 ms, la trace brute une file bornee et des blocs de 500 lignes maximum, les listes une insertion progressive groupee. Attendre la preparation des analyses/listes avant de quitter l'accueil. Annuler aussi les callbacks de mise en page et retirer les bindings a la destruction des panneaux.
- Les raccourcis se lient via `tkinter.Misc.bind/unbind` avec leur identifiant, pour retirer seulement les callbacks de la vue ; les wrappers `CTkFrame.bind` ne rendent pas cet identifiant et peuvent conserver une vue detruite.
- Ne jamais remplacer le champ interne `_canvas` d'une `CTkFrame` : le graphique du viewer utilise `_machine_canvas`, conserve 920 x 540 pixels et un conteneur Tk sans agrandissement DPI. La trace brute adapte sa hauteur pour garder T5 visible.
- Le rapport terrain commence par trois priorites maximum, puis les cartes Longueur/Largeur/Hauteur et leurs boutons precis. La repartition suit les observations : cinq ecarts les plus frequents par defaut, bouton accessible pour afficher/reduire la liste complete sans modifier les calculs ni le PDF ; les depliants Statistiques et explications et leur section PDF sont retires, sans modifier les calculs. Les observations des diagnostics se trient par effectif decroissant, puis axe et signe. Garder variantes et preuves techniques dans les details produit ; le PDF partage cette hierarchie avec des tableaux de mesures.
- L'en-tete du rapport separe marque/liaison, titre centre et metadonnees/export. Les blocs Premier controle partagent leurs lignes de grille sur les trois colonnes ; verifier leur alignement avec des textes de longueurs differentes. La capture du manuel des priorites vise directement `.priority-grid`, sans recadrage dependante de la hauteur de l'en-tete.
- Les cartes Longueur/Largeur/Hauteur partagent leurs lignes de grille sur ordinateur : observations, repartitions, tableaux et statistiques restent alignes avec zero, une ou deux observations, des textes longs et des legendes absentes. Garder des hauteurs naturelles et la disposition mobile independante ; verifier aussi les listes depliees.
- Le rapport React et le secours HTML partagent `report_app/public/report-ui.js` et sa feuille de style. Les exemples de mesures restent structures, avec trois cas representatifs puis des pages de 25.
- Pour les diagnostics hors dimensions/orientations, preparer dix preuves distinctes maximum par groupe sur toute la periode, premiere et derniere comprises et positions intermediaires reparties dans l'ordre chronologique. Selectionner avant toute lecture de contexte et tout export de detail ; les cartes de series et incidents exportes sont limites aux preuves retenues, avec leurs propres bornes et fichiers. Les compteurs, gravites et priorites utilisent toutes les observations avant cette selection. Ne jamais fusionner deux episodes separes. Les mesures et orientations conservent leurs preuves et leur pagination. Les bilans quotidiens robot restent complets ; demandes et prises confirmees partagent la limite globale de dix preuves.
- Le compteur UNKNOWN du rapport compte les finales confirmees CB1+CB2 sur les passages physiques reconstitues, meme sous le seuil. Exclure les refus REFERENCE_ABSENT et REFERENCE_NON_ALPHATISABLE des UNKNOWN de decodage. Il est compact (60 px), informatif et non cliquable : vert sous 8 %, jaune de 8 a 12 % inclus, rouge au-dela de 12 %, neutre si le denominateur manque. Comparer avant arrondi. Aucun bandeau ni deroulant UNKNOWN dedie ; le diagnostic habituel conserve son seuil strictement superieur a 7 % et son classement.
- Le worker reutilise les statistiques camera des diagnostics dans `camera_report.pkl`, propre a la session. Le rapport lit les contextes par indices de frames et blocs ordonnes ; les anciens stores gardent un fallback. Ne pas deplacer un parcours complet vers Tk.
- Les liens des numeros de ligne sont enregistres uniquement depuis les contextes exportes et restent distincts des cibles de mesures completes. La trace brute est un panneau separe : la rendre visible si besoin, sans supposer l'existence d'un onglet Trace dans `_analysis_tabs`.
- Apres une mise a jour des sources du rapport, reconstruire le build React local avant validation navigateur et livraison ; recuperer Git ne met pas a jour `report_app/out` ni le .exe.
- Les compteurs metier UNKNOWN, cameras et resets proviennent de `DiagnosticIncident.metrics`, pas du texte de resume ; le parsing de resume reste seulement un fallback de compatibilite. Conserver les anciens fichiers `_next` lors d'un nouvel export pour garder les rapports deja enregistres lisibles hors connexion.
- La liaison rapport/viewer reste locale a `127.0.0.1`, protegee par un jeton de session et limitee aux exemples enregistres pour la vue source. Les commandes passent par une file Tk ; fermeture/remplacement invalide la liaison et les commandes perimees ne naviguent pas.

## Diagnostics terrain

- `Models/diagnostic_summary.py` partage la presentation viewer/web/PDF. `diffT4` utilise une identite stable sans maximum dans son titre : sommer les controles > 10 mm et prendre le maximum absolu structure, jamais un nombre de boites deduit des messages. Conserver les series par fichier et le nombre de sources analysees ; une plage d'observations n'est pas une panne continue. Les anciennes metriques insuffisantes invitent a regenerer.
- Seuls les episodes `MOTOR_COMM` avec defaut explicite sont visibles dans les listes, priorites et compteurs. Resume, dates et preuves portent sur ces episodes critiques uniquement. Les reessais recuperes/indetermines restent dans l'analyse brute. Une reconnexion du socket ne prouve pas la reprise des commandes ; IX/BL/LL ne designent pas un tapis.
- Le PDF terrain est une synthese de quatre a cinq pages ciblees, sans limite rigide au detriment des alertes : trois priorites, bilan mesures/produits/orientations, cameras/identification/robot/moteurs puis autres actions. Trois reperes maximum au total ; pas de traces brutes, listes d'IdA, details d'episodes ou tableaux quotidiens. Garder tous les types critiques/en alerte, les tableaux pagines et les cartes indivisibles. Les distributions completes, variantes et preuves restent dans le web.

- `MOTOR_COMM` regroupe les reessais et defauts StepMotors, Winsock, ports non ouverts et anciens `028-Avt` sans doubler les cartes. Reessai explicitement recupere : Information ; defaut explicite : Critique ; resultat absent : indetermine. Apparier commande et connexion dans les 120 s. Reconnexion socket et echanges retablis sont distincts ; une fermeture normale n'est pas une panne. Conserver les initialisations T0-T5 observees dans les deux secondes suivant la reconnexion, sans les presenter comme de nouvelles coupures.
- `DP_MISSING` compte les cycles identifies terminant explicitement sans peremption (`manque la DP` ou renommage `[MqDP]`). Une demande `[manque DP]` n'est pas un rejet ; une DP camera retrouvee avant le constat final est une recuperation. Les dates generiques 2099 et la BdD ne prouvent pas une lecture. Les cycles DP confirmes sont exclus des UNKNOWN de decodage, sans changer le denominateur ni les statistiques camera. Associer par IdB/IdA et contexte de creation, jamais par CIP seul ; garder les signalements non attribuables distincts. Un code brut limite au CIP ne prouve pas l'absence physique du DataMatrix.
- `CAMERA_CODE_MODE` signale le mode 123 (DataMatrix et codes-barres) en Alerte, avec periodes CB1/CB2 separees ; le mode 1 signifie DataMatrix seul. Correspondance confirmee par l'utilisateur ; les autres valeurs restent non interpretees. Changements de mode, redemarrage, interruption d'observation >120 s et fichier terminent les periodes. Les demandes de photos ne sont pas des incidents supplementaires. Les nouveaux diagnostics partagent des episodes structures et dix preuves maximum par episode ; leur preparation reste dans les workers.

- Le classement relatif C5/T5 bloquant utilise `Models/priority_impact.py` : a criticite egale, cycles touches, episodes distincts, duree cumulee puis premiere ligne. Les bascules C5, creations virtuelles, associations incompletes et messages T5 ne sont pas des cycles supplementaires. Les intervalles T5 se regroupent seulement s'ils se chevauchent dans le meme segment ; les durees simultanees ne se multiplient pas. Un nouvel IdA cree ouvre un autre cycle, meme si sa valeur est reutilisee. Permuter seulement les positions C5/T5, avant toute limite, sans changer les autres priorites ni les criticites. Des anciennes metriques insuffisantes conservent leur ordre et invitent a regenerer ; ne pas inventer de zero.

- Le bilan des vidages T5 compte les boites seulement dans un bloc collectif complet rattache a une commande explicite OMEGA:T5-DemVidageComplet. Les confirmations OMEGA:T5-DEL-PACK@Ok comptent les prises par cycle IdA sur toute la periode ; les suppressions seules, photos FinTrsfT3-T4-ERREUR et CIP partages ne prouvent pas une prise. Conserver les suppressions non attribuables et les demandes sans bilan complet, les preuves et les limites des segments. Une attente ou interruption de plus de 120 s invalide le rattachement plutot que d'inventer une causalite. Les compteurs ne changent jamais la criticite ni le score des demandes. Les anciens rapports sans ces metriques invitent a regenerer.

- Le defaut T2 eT:-88 (boite deja C4) reste en alerte sous 10 occurrences sur 24 h glissantes ; des 10, bornes incluses, il devient critique. Viewer et rapport partagent `max_24h_count`, sans utiliser le total multi-jours. Une ancienne synthese sans cette metrique reste en alerte et doit etre regeneree pour evaluer le seuil. Les initialisations repetees T4 gardent leur classement propre.

- La periode du rapport vient de `FrameStore.trace_period`, metadonnee optionnelle preparee dans le worker meme sans vidage robot. Afficher dates completes et duree totale en heures ; les anciens stores sans origine fiable invitent a recharger. Aucun parcours des frames dans Tk pour obtenir ces dates.
- Les orientations probables se repartissent par cycle : echange longueur/largeur (`flat_rotation`), largeur/hauteur (`on_edge`), autres permutations (`other`). Un seul meilleur echange simple avec trois dimensions distinctes autorise les deux premiers cas ; garder les egalites et dimensions egales a part, et les orientations indécidables separees. Une reference peut appartenir a plusieurs categories avec le meme denominateur avant exclusion ; aucun double compte global. Les controles sur tranche concernent la presentation a plat et la hauteur de restitution du robot, sans hauteur chiffree inventee ni certitude sur le sens physique.
- Le bilan des vidages robot affiche le total sur les jours calendaires de toute la trace, dates incluses, puis les effectifs quotidiens (y compris zero) et dix preuves maximum sur toute la periode, demandes et prises confirmees comprises. Les seuils restent internes au classement, sans conditions ni pics repetes dans les cartes. Le worker lit l'origine complete dans les 256 premieres lignes ; `Models/robot_drain.py` reconstitue les mois/annees a partir des timestamps relatifs, sans date ajoutee a chaque frame. Une ancienne session sans origine affiche Dates indisponibles et invite a recharger ; ne pas inventer le mois depuis le seul prefixe de jour.
- Les commandes explicites `OMEGA:T5-DemVidageComplet` comptent une fois par ligne source. Information sous 10 demandes sur 24 h glissantes, Critique des 10, bornes incluses ; aucun seuil horaire ni renforcement a 15. Sous 10, garder details et preuves par journee, y compris sans demande, sans bandeau ni presence dans les priorites viewer/web/PDF. Recalculer depuis le maximum sur 24 h, jamais les anciens flags critical/reinforced. `Models/robot_drain.py` partage cette regle et les scores T5. Les causes restent des controles a confirmer ; regenerer les anciens rapports exportes.
- `C2_SIGNAL_ANOMALY`, famille T2, regroupe les episodes dans une seule carte. Alerte : au moins 10 bascules brutes sur 5 minutes sans progression T2, C3/C4 a zero. Critique : relance explicite du vidage suivie dans les 3 lignes et 2 secondes d'un etat complet avec C2 seul actif parmi C2/C3/C4/C5/C6/C9. Les doublons ne comptent pas ; progression T2, C3/C4 actifs, redemarrage logiciel ou observations interrompues plus de 120 s terminent une sequence. Compter episodes, bascules, relances et initialisations T2 separement ; le score depend des episodes, pas des bascules. Conserver les dates, durees et sources des alternances/blocages/reprises via metrics/examples ; une reprise ne prouve pas une reparation. Controler obstacle, proprete, alignement et cablage sans conclure automatiquement a un capteur HS.
- `C3_SIGNAL_ANOMALY` utilise le meme moteur et les memes seuils, avec C2/C4 a zero pour l'instabilite et C3 seul actif pour le blocage explicite. Garder une carte T2 distincte de C2 et des compteurs/preuves independants. L'activation C2 termine le contexte C3 sans prouver une reprise ; conserver cette borne comme source, sans lien de reprise invente. Plusieurs capteurs actifs ne prouvent aucun blocage exclusif C3. Preserver le comportement et les resultats C2 ; valider C3 sur donnees fictives et l'absence de faux positifs sur les traces disponibles, sans annoncer une validation terrain C3 sans exemple reel.
- `C5_SIGNAL_ANOMALY`, zone T3/C5, utilise un moteur distinct : au moins dix bascules brutes `tEA-T3` dans cinq minutes glissantes, bornes incluses, entre confirmations EA->T3. Une demande seule ne termine pas le contexte. Transfert confirme, redemarrage, interruption >120 s, cinq minutes observees sans bascule et limite de fichier terminent un episode sans prouver une reparation. Critique seulement pour une chaine IdB/IdA explicite : longueur T3->T4 nulle, absence signalee sur C6, suppression T5 pour largeur <2 mm et C9=0. Ne jamais lier par CIP ; garder ambiguites, impulsions C6 et creations virtuelles apres pesee separees. Dix preuves maximum par episode ; boites et compteurs UNKNOWN inchanges.
- La priorite robot affiche deux lignes de bilan puis Premier controle ; garder dates et bilans incomplets dans le detail. La part evacuee est calculee en Python par evacuees/(evacuees+prises confirmees), apres sommation des segments. Les prises confirmees excluent les vidages ; ne pas appeler ce ratio taux d'echec de prise. Denominateur nul : Ratio indisponible ; anciennes metriques absentes : regenerer le rapport.
- Les seuils d'anomalie mesure/BdD sont stricts et partages par axe : ecart absolu > 2 mm en hauteur, > 3 mm en longueur/largeur. A la limite exacte, la mesure reste conforme. Appliquer ces seuils aux diagnostics, listes, repetitions, couleurs et PDF via `Models/dimension_check.py`. Les rapports sans seuils par axe conservent leur interpretation historique a 3 mm ; regenerer le rapport pour utiliser le nouveau seuil hauteur.
- Le bilan exige `camera_identity_line` et `camera_identity_source` issus d'une identification CB1/CB2 explicite ; une recherche ou creation BdD ne confirme pas une lecture camera. Ces champs suivent `clone`, les transferts et les listes T5, sans ecraser la provenance initiale de l'identite.
- Comparer les permutations distinctes des dimensions BdD par somme des ecarts absolus avant de classer un defaut : une autre orientation meilleure est probable, une egalite est indecidable. Exclure et compter ces cas separement ; ne pas certifier leur presentation physique. Les permutations identiques ne creent pas d'ambiguite.
- Dans le rapport, un clic sur une reference Trop petites/Trop grandes ouvre le detail et rejoint la pire mesure pour l'axe et le cote choisis ; departager les egalites par ligne source puis cycle. Les liens de mesure rejoignent `display_frame_index` / `display_line`, ou la meme boite porte les trois valeurs retenues ; l'axe choisit le detail, pas l'instant. Verifier identite, BdD, mesures et provenance dans cette seule frame, sans parcours Tk. Une cible complete absente ou perimee interdit la navigation et invite a regenerer le rapport.
- La rubrique Boites dans le mauvais sens du rapport web/PDF utilise `orientation_references` preparees dans le worker : derniere mesure complete par cycle, toutes les references sans filtre de 10 %, orientations probables et indecidables separees. Le denominateur par produit inclut ses cycles exploitables avant exclusion pour orientation. Trier par effectif, proportion puis reference. Les preuves conservent toutes les permutations au meilleur score et leur cible complete ; le clic produit rejoint la premiere boite dans l'ordre des frames, puis ligne et cycle. Garder le code interne ORIENTATION sans dupliquer sa carte dans les autres diagnostics du rapport.
- Les bilans de dimensions se calculent dans le worker via `Models/measurement_analysis.py`, une fois par cycle avec la derniere mesure complete exploitable. Les preuves distinctes restent dans `measurements.pkl` ; seule la synthese compacte est lue par le thread UI.
- La longueur principale, les couleurs et l'infobulle utilisent T4C avec sa ligne source ; T4T reste distinct, sans fallback. Les vraies UNKNOWN meme dimensionnees, les identifications non confirmees et les references contradictoires sont exclues explicitement. Une reconnaissance CB2 et un produit identifie puis renomme `[Dinh]` restent comparables sous le produit identifie, avec mention du rejet.
- La presentation des listes de defauts distingue les produits avec au moins 10 % de defauts du cote choisi et les Cas rares (< 10 %) consultables, avec navigation et pagination. Comparer `count * 10 >= total` avant arrondi, sans retirer de mesures des calculs. Les ecarts mis en avant portent sur les produits retenus ; la repartition conserve aussi les ecarts des cas rares.
- La criticite des dimensions (hors orientations) utilise les comparables de la trace : au moins 10 boites et 10 % rendent le diagnostic critique. Son score recoit `round(1000 * affected_ratio)` a partir de 10 boites. Conserver les compteurs par groupe ; recalculer gravite et priorite sur chaque trace, sans privilegier un axe ni masquer les incidents systeme.
- Les listes Trop petites/Trop grandes utilisent uniquement les mesures finales comparables, groupees par produit et triees par pire ecart absolu, nombre de boites puis reference. Le denominateur est le total comparable du produit. Le worker charge references et preuves par pages de 25 depuis `measurements.pkl` ; aucun parcours complet de `FrameStore` dans Tk. Les lignes sources restent des preuves ; la navigation des mesures utilise la frame complete enregistree.
- L'ecart signe vaut mesure moins BdD. Orientations differentes, C9 invalide, references absentes, mesures incompletes et identites ambigues sont exclus du bilan de reglage et comptes separement. `diffT4` compare T4C/T4T et ne constitue pas une comparaison mesure/BdD.
- Afficher les bonnes/mauvaises mesures sur le total comparable, le total des cycles T5 et les exclusions. Le bilan global compte une boite hors tolerance une seule fois, meme si plusieurs axes sont en erreur. Les plages et pires ecarts gardent leur signe ; distinguer moyenne signee et erreur moyenne absolue. Un cote sans anomalie affiche « Aucune », jamais un zero invente.
- Le « Bilan des mesures de la trace » distingue faits, repetition par produit et hypotheses. Les frequences des defauts restent separees par signe ; chaque centre principal est l'ecart hors tolerance le plus frequent, puis le plus proche de zero en cas d'egalite. Compter toutes les comparables a +/-1 mm, y compris conformes, avec effectifs des defauts et des bonnes mesures voisines, proportions et plage observee. La repartition de toutes les comparables reste dans les details ; ne jamais extrapoler un groupe a toute la machine.
- Verifier la repetition sur toutes les comparables de chaque produit, regroupees par dimensions BdD identiques. Signaler les variantes sans les melanger pour l'interpretation. Une seule mesure ne confirme rien ; au moins deux mesures avec 80 % a +/-1 mm d'un centre decrit une repetition sur ce produit. Au moins deux produits mesures plusieurs fois doivent satisfaire ce critere pour etayer une repetition commune. Afficher la contribution du produit dominant. Ne pas changer la nature de l'observation entre 9 et 10 boites : sous 10, ajouter seulement « effectif limite ».
- Une repetition commune oriente vers parametrage/reglage/calibrage, avec mesure physique de quelques boites et controle de leur BdD ; sur un seul produit, verifier d'abord sa fiche et sa presentation. Ces controles restent des hypotheses a confirmer, jamais une conclusion automatique de mauvais reglage.
- Qualifier une dispersion seulement au sein d'un meme produit et d'une meme variante BdD : rechercher la fenetre de 2 mm la plus dense ; sa couverture doit etre inferieure a 80 % et la plage totale superieure a 2 mm. Pour cette dispersion uniquement, proposer sur T4/C6 l'entrainement/patinage pour les ecarts en moins, le positionnement/detections parasites de C6 pour ceux en trop. Garder C9/LzB distincts. Une difference entre produits ou l'absence de groupe ne prouve pas une variation mecanique.
- Garder les groupes opposes distincts ; s'ils concernent le meme produit, signaler des comportements differents et inviter a examiner presentation, chronologie et lignes sources. Le critere global historique (10 comparables, 80 % a +/-1 mm de la mediane) reste descriptif et ne contourne jamais la verification par produit.
- `Temps depuis RESET carte ALPHA` est un compteur d'uptime : une valeur elevee et croissante est normale.
- Un reset carte Alpha est compte uniquement quand ce compteur chute vers `0..10 mn` pendant la trace ; les releves bas consecutifs apres la chute appartiennent au meme reset.
- Les resets carte Alpha restent en alerte tant qu'aucune journee civile ne compte au moins trois resets. Trois resets dans une meme journee rendent le diagnostic critique ; le total sur plusieurs jours ne suffit pas. Le viewer et le rapport partagent `max_daily_count` ; une ancienne synthese sans cette metrique reste en alerte et doit etre regeneree pour evaluer ce seuil.
- Le rapport doit afficher le nombre de resets carte Alpha et la duree couverte par la trace, jamais un ratio par nombre de boites.
- En cas de reset carte Alpha, faire verifier en priorite les shunts CubeStop/balance, leur cablage, les masses et l'alimentation.

- Une initialisation T4 isolee ou periodique apres beaucoup de boites est normale.
- Trois lignes `InitMachine: demande initialisation de T4 ...` d'affilee indiquent un probleme T4/C6 probable.
- Si C6 reste actif pendant ces init T4 repetees, suspecter C6 trop bas, signal bloque actif ou objet devant le capteur.
- Si C6 n'est pas toujours actif pendant ces init T4 repetees, suspecter C6 trop haut/HS/mal positionne, moteur T4 qui patine ou rouleau moteur non entraine.
- Les diagnostics camera unknown comptent les boites finales creees en `ALPHA-INC`, `ALPHA-DET` ou `ALPHA-DIF` avec `-unknow`, pas les unknown temporaires relues ensuite.
- Une unknown CB1 relue correctement par CB2 ne compte pas comme unknown finale ; une unknown finale vue par CB1 et CB2 doit etre classee `CB1+CB2`.
- Le ratio principal camera unknown compte uniquement les boites `CB1+CB2`; `CB1 seul`, `CB2 seul` et `non attribue` restent du contexte.
- Seuil diagnostic camera unknown : plus de 7% des passages physiques reconstitues avec CB1/CB2, Nboite/idB et IdA. Les compteurs `Hist_LectCB` sont reutilisables et ne sont jamais des identites de passage.
- Un refus explicite `pas dans BdD, refus de creation dans param` declenche `REFERENCE_ABSENT` des la premiere occurrence, avec CIP original, lecteur, reference technique et preuves. Compter une boite une seule fois meme si CB1 et CB2 refusent ; exclure ce cycle de tous les compteurs UNKNOWN camera. `ALPHA-DET` seul ne prouve pas une reference absente.
- Le refus explicite `ref. non Alphatisable` declenche `REFERENCE_NON_ALPHATISABLE`, distinct de la reference absente et exclu de tous les compteurs UNKNOWN de decodage. Conserver CIP, motif exact, lecteurs, idB/IdA et sources ; compter un passage une fois meme si les deux lecteurs refusent. Faire verifier la fiche et la raison de l'exclusion, sans conseiller la creation par chargement manuel ni reactiver automatiquement la reference. Une reconnaissance ulterieure n'efface pas le refus historique.
- La fiche produit doit etre creee par la zone de chargement manuel. Le diagnostic recommande ce passage sans affirmer connaitre tout son historique ; conserver les refus historiques meme apres une reconnaissance ulterieure.
- Une reouverture du fichier de trace ne redemarre pas la machine : conserver les cycles en cours. Une nouvelle initialisation logicielle ouvre un nouvel espace d'identites.
- CB1 regroupe les cameras 1, 2, 4, 5, 6 ; CB2 correspond a la camera 3.
- Une camera attendue sans aucune reussite `PR/Soh/N` sur une trace significative indique une camera potentiellement HS, deconnectee ou non contributive.
- Si CubeStop est commande `HAUT`, que le transfert EA->T3 demarre, mais que `C4` reste actif et `C5` reste inactif jusqu'a l'erreur ou la fin de course T3, suspecter CubeStop bloque mecaniquement en bas, ejecteur C4 inefficace, rail bloque ou C4 faux actif.

## Checklist de validation

- Le nom d'une trace locale ne garantit jamais son caractere nominal. Les regressions utilisent des scenarios fictifs deterministes ; les controles terrain verifient les preuves sources explicites, sans deduire le resultat attendu du nom du fichier.

- Texte ou documentation seuls : verifier le diff et les liens concernes ; aucun test metier.
- Petite modification visuelle : controler le composant concerne ; aucun benchmark ni test des fonctions independantes.
- Correction fonctionnelle : compiler les fichiers Python modifies et tester la fonction ainsi que ses dependances directement touchees.
- Modification transversale du parser, des identites de boites, du stockage des frames ou du chargement : validation globale avec `python TraceAlphaViewer\Tools\validate_all.py` et compilation des fichiers principaux. Conserver ce lanceur pour les controles complets, sans ajouter de cache complexe.
- Un test reussi reste acquis tant qu'aucune modification ulterieure du code, des dependances, des donnees de test ou de l'environnement ne peut affecter son resultat. Ne pas le relancer uniquement pour le commit.
- Les scenarios metier ci-dessous et les controles specifiques du reste du document s'appliquent aux comportements touches par le changement, pas systematiquement a chaque tache. Signaler les controles pertinents ignores faute de trace locale.
- Reserver les benchmarks aux changements de performance. Reconstruire le .exe uniquement sur demande explicite de l'utilisateur ; lorsqu'une construction est demandee, valider le binaire avant livraison. Les autres validations proportionnees des sources restent applicables sans reconstruction. Reconstruire React uniquement lorsque ses sources changent ; pour les changements documentaires, appliquer la regle du manuel ci-dessus.
- Les validations automatiques restent en arriere-plan, sans prise de focus. `validate_all.py --visual` et `benchmark_loading.py --show` sont reserves a une demande explicite de controle visible ; les controles d'affichage deja valides ne sont pas repetes sans modification pertinente.
- `validate_all.py` exclut le binaire par defaut. Ajouter `--exe` pour sa validation apres une reconstruction explicitement demandee, sans comparer automatiquement les sources modifiees a un ancien executable.
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

## Reduction des tokens et du temps de travail

- Rechercher et lire uniquement le code utile au changement ; regrouper les inspections independantes et eviter les relectures sans nouvelle raison.
- Conserver les sorties detaillees des tests dans des journaux locaux non versionnes ; lire le resume, puis les details utiles en cas d'echec. Conserver le code de sortie pour ne pas masquer un echec.
- Rapporter brievement les changements, les controles effectues et les limites ; ne pas reproduire les journaux complets.

## Definition de termine

- Le rapport doit conserver ses fonctions dans les sources versionnees `report-ui.js` / `report-ui.css`, pas seulement dans un ancien bundle React. Apres reconstruction, verifier la colonne des six cameras ouverte par defaut (empilee avant les mesures sous 1360 px), le compteur UNKNOWN compact et non cliquable, les trois categories d'orientation avec leurs controles et les journees robot, y compris celles sans demande. Les nouvelles cartes s'ajoutent sans supprimer les informations existantes.
- Les dates calendaires du rapport viennent d'une ouverture de trace explicitement datee, jamais de l'horloge du PC ni d'une date de version logiciel. Conserver le repli des anciens rapports sans calendrier ni categories d'orientation. Les demandes robot gardent leurs seuils glissants et bilans quotidiens complets ; tous les groupes hors dimensions/orientations partagent chacun dix preuves maximum sur toute la periode.

- Le changement demande est implemente ou la question est repondue clairement.
- Une fusion entre postes conserve explicitement les comportements locaux demandes (recherche, cameras, orientations et calendrier) ; integrer les ajouts metier des autres commits sans reintroduire leurs anciennes variantes d'interface. Les validations suivent le comportement retenu, y compris le detail des mesures absent de la vue globale.
- Si du code Python a change, les fichiers modifies ont ete compiles avec `py_compile` ou l'impossibilite est expliquee.
- Si T5, le parser ou le canvas a change, les scenarios trace critiques concernes ont ete controles selon la checklist proportionnee.
- Les erreurs ou limites restantes sont listees explicitement.
- La documentation projet est mise a jour quand une nouvelle regle evite une repetition d'erreur.
- Les fichiers hors depot ou les memoires personnelles ne sont pas modifies sans demande explicite.
