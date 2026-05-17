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
- Ne pas pousser les fichiers de traces sur GitHub : pas de `*.old`, pas de gros `.txt` de trace.
- Avant chaque commit, verifier `git status --short` et la liste des fichiers indexes.
- Si des traces sont indexees, les retirer avant de committer.
- Les traces restent locales pour validation, sauf demande explicite de versionner un petit echantillon precis.

## Fichiers importants

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
- `box_in_EA` represente la boite sur C4 / CB1.
- `box_on_T3` represente la boite sur T3 / C5 / CB2.
- `box_on_T4` represente la boite sur T4 / C6.
- `boxes_on_T5` represente les boites T5/BdD controlees par `IdA`.
- `BoxInfo.id_b` est l'identite pre-T5 (`Nboite` / `idB`).
- `BoxInfo.id_alpha` est l'identite T5/BdD utilisee par les lignes robot.
- `BoxInfo.source_ref` conserve la reference initiale `ALPHA-INC-xxx` quand CB2 identifie ensuite le vrai produit.
- `CB1: ajout Hist_LectCB` concerne EA/C4 uniquement.
- `CB2: ajout Hist_LectCB` concerne T3/C5 uniquement.
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
- Avant tout reset de `t5_visual_offset_mm`, committer l'offset courant dans `t5_visual_x_pos`.
- Exception : une ligne BdD `Deplace toutes les boites ...` resynchronise seulement les boites deja etablies sur T5 ; une nouvelle boite `t5_entry_aligned=True` attend sa premiere `MAJ` stable.
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
- Les onglets bas sont `Diagnostic`, `Erreur`, `Evenements`, `Trace`, avec `Erreur` filtre sur `severity == "error"`.
- Raccourcis clavier : Left/Right, Space, Home/End, `e` / `E`.

## Checklist de validation

- Compiler les fichiers principaux avec la commande `py_compile` indiquee plus haut apres toute modification Python.
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
