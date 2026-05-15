# Notes agent TraceAlphaViewer

## Vue du projet
TraceAlphaViewer est un viewer local Python/customtkinter pour traces Alpha `.old`.
Le flux principal est :
- parser les lignes de trace en `MachineState` ;
- conserver le cycle physique des boites entre EA, T3, T4 et T5 ;
- afficher l'etat machine dans le canvas, les tables, les evenements et le diagnostic ;
- aider a comprendre les incidents sans inventer de positions ou d'identites.
Ce fichier est la memoire projet versionnee. Les regles techniques ci-dessous doivent rester ici, pas dans une memoire personnelle Codex.

## Lancement et commandes
Depuis la racine du projet :
```powershell
python Main.py
```
Compilation minimale apres modification de code :
```powershell
python -m py_compile Main.py Models\state.py Parser\trace_parser.py Views\traceView.py Widgets\machine_canvas.py
```
Pour explorer rapidement :
```powershell
rg -n "motif" Parser Widgets Models Views
rg --files
```

## Carte d'architecture
- `Main.py` lance l'application customtkinter.
- `Models/state.py` contient `MachineState`, `BoxInfo` et `MachineEvent`.
- `Parser/trace_parser.py` lit les `.old`, applique les transitions et construit les frames.
- `Widgets/machine_canvas.py` dessine le schema machine, les capteurs, les fleches et les boites.
- `Widgets/state_table.py` affiche les etats tapis, capteurs et codes firmware.
- `Views/traceView.py` gere le viewer principal, navigation, player et callbacks.
- `Models/diagnostic.py` et `Models/diagnostic_knowledge.py` extraient et expliquent les incidents.

## Regles de codage
- Lire le code existant avant de modifier ; ne pas supposer les conventions.
- Garder les changements scopes au bug ou a la fonctionnalite demandee.
- Utiliser `apply_patch` pour les editions manuelles.
- Ne jamais annuler des changements utilisateur non lies.
- Ne pas faire de refactor large pendant une correction trace/rendu.
- Pour les donnees structurees de trace, preferer regex/helpers dedies plutot que du parsing fragile par positions ad hoc.
- Ajouter des commentaires courts seulement quand ils evitent une erreur de comprehension.
- Pour eviter les boucles, ne pas retoucher des constantes visuelles avant d'avoir prouve quel etat parser ou quelle coordonnee est faux.
- Apres une correction T5, valider par script sur frames en plus du controle visuel.
- Ne jamais afficher de secrets, tokens, cles, fichiers d'authentification ou contenu prive hors projet.
- Pour une trace longue ou un document metier, relire les lignes sources ciblees avant de conclure.
- Si un bug revient, renforcer l'invariant dans ce fichier au lieu de refaire une correction fragile.
- Les fleches tapis utilisent les couleurs communes actif/repos/erreur ; ne pas reutiliser les couleurs capteurs pour elles.

## Workflow de base
- Clarifier le but, le critere d'acceptation et les contraintes de securite/scope.
- Lire les fichiers concernes avant de modifier ; verifier les invariants applicables dans ce fichier.
- Si la demande depend d'une information recente externe, verifier une source officielle avant de repondre.
- Faire le plus petit changement sur les bons objets metier, pas sur les symptomes visuels.
- Verifier avec la commande ou le scenario trace adapte avant de conclure.

## Invariants du parser
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
- C9 est l'entree T4 vers T5 ; sa position canvas vient du calibrage physique T5.
- Certaines traces utilisent de grands `X` Alpha pour T5 : les normaliser par distance a la butee observee, jamais avec un clamp qui transforme `X > butee` en butee.
- `BoxInfo.t5_after_c9=True` est un etat de cycle/diagnostic, pas une contrainte geometrique.
- Les boites T5 suivent toutes le meme tapis : tout mouvement signe de T5 deplace le groupe, y compris les boites deja passees par C9.
- Le rendu doit conserver les positions relatives issues de `x_pos`, `t5_visual_x_pos`, `ALPHA:T5-LIST-PACK` et des deplacements BdD confirmes.
- Avant tout reset de `t5_visual_offset_mm`, committer l'offset courant dans `t5_visual_x_pos`.
- Exception : une ligne BdD `Deplace toutes les boites ...` resynchronise `t5_visual_x_pos` sur le nouveau `x_pos`, car elle confirme le mouvement deja anime.
- Ne pas ajouter de clamp final sur C9 ou sur la butee : les dimensions physiques et les positions Alpha doivent porter le rendu.
- `MAJ (BUTEE-T5)` peut remettre `t5_after_c9=False` seulement pour la meme boite active revenue en cycle butee.
- `MAJ (APRES-MESURE-LARG)` recale toujours `x_pos` et `t5_visual_x_pos` sur le `X` trace de la boite mesuree, puis marque cette boite `t5_after_c9=True`.
- Une activation C9 de la boite active marque cette boite `t5_after_c9=True`.
- Une nouvelle arrivee T4->T5 demarre `t5_after_c9=False` et `t5_entry_aligned=True` jusqu'a position stable.
- Une boite `t5_entry_aligned=True` reste sous l'axe T4 seulement a l'entree initiale (`x_pos` proche de `_T5_ENTRY_X` et offset nul).
- Si une ligne BdD ou un offset a deja deplace cette boite, elle doit etre rendue depuis son X T5, pas depuis le placement fixe T4.
- C9/`width_mm` se dessine sur l'axe horizontal T5.
- C6/`length_mm` se dessine dans l'epaisseur verticale T5.
- `t5_footprint_mm` de `ALPHA:T5-LIST-PACK` est seulement un fallback si les dimensions C6/C9 manquent.
- La ligne jaune de position `pT5` ne doit pas etre reintroduite dans le canvas.
- Le point `Mesure H.` / `LzB` reste hors tapis pour ne pas etre masque par les boites.

## Checklist de validation
- Compiler les fichiers principaux avec la commande `py_compile` indiquee plus haut apres toute modification Python.
- Controler `TracAlpha1_012.old` autour de `24|08:31:15` a `08:31:18` : l'IBUPROFENE suit le mouvement T5 sans saut visuel.
- Controler `TracAlpha1_012.old` autour de `24|08:31:52` a `08:31:55` : meme invariant sur le second IBUPROFENE.
- Controler une sequence multi-boites vers `08:15:02` : les boites suivent le meme tapis et gardent leur espacement relatif.
- Controler une sequence de tassage : une nouvelle boite T4->T5 va vers la butee, et les boites deja sur T5 reculent aussi selon le meme mouvement physique.
- Controler les lignes `MAJ (APRES-MESURE-LARG)` : elles changent la position stable/dimensions sans saut visuel brutal.
- Controler visuellement T5 : transfert T4->T5, tassage butee, passage C9, retour repos, espacement multi-boites.
- Controler visuellement T2 si modifie : fleche grise a l'arret, coloree pendant les codes moteur actifs.
- Si un controle echoue, inspecter d'abord l'etat parser (`BoxInfo`, `MachineState`) avant de toucher aux constantes canvas.

## Definition de termine
- Le changement demande est implemente ou la question est repondue clairement.
- Si du code Python a change, la compilation `py_compile` a ete lancee ou l'impossibilite est expliquee.
- Si T5, le parser ou le canvas a change, les scenarios trace critiques ont ete controles.
- Les erreurs ou limites restantes sont listees explicitement, sans les cacher dans le resume.
- La documentation projet est mise a jour quand une nouvelle regle evite une repetition d'erreur.
- Les fichiers hors depot ou les memoires personnelles ne sont pas modifies sans demande explicite.

## Politique memoire
- `AGENTS.md` contient les regles techniques partagees du projet.
- Les memoires Codex personnelles ne doivent contenir que des preferences stables de travail.
- Exemple acceptable en memoire personnelle : repondre en francais pour ce projet.
- Exemple acceptable en memoire personnelle : toujours verifier les sequences T5 critiques avant de conclure.
- Ne pas stocker en memoire personnelle les constantes T5, les invariants parser, les chemins, ou les decisions d'architecture.
- Ne pas modifier `C:\Users\paulj\.codex\AGENTS.md` ni `C:\Users\paulj\.codex\memories` pendant une tache projet sauf demande explicite.
- Les notes de continuite longues sont optionnelles et reservees aux travaux longs ou multi-jours.
- Une note de continuite ne remplace jamais ce fichier et ne doit pas devenir un journal de chat.
- Si une regle aide un autre developpeur a reprendre le projet, elle appartient a ce fichier.
