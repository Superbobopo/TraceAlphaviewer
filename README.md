# TraceAlphaViewer

TraceAlphaViewer est un viewer local Python/customtkinter pour traces Alpha `.old`.

Il parse les lignes de trace en frames `MachineState`, puis affiche :

- le schema machine et les convoyeurs ;
- les capteurs et les etats tapis ;
- les boites qui circulent entre EA, T3, T4 et T5 ;
- les evenements et diagnostics ;
- la trace brute avec navigation cliquable.

## Etat actuel

Le depot suit la derniere version utilisable sur `main`.

Comportement UI/runtime actuel :

- le demarrage charge les traces directement en mode precision complete (`min_dt=0.0`) ;
- l'ecran d'accueil n'a plus de selecteur de qualite ;
- le rendu du transfert T4 vers T5 reste aligne sous l'axe visuel de T4 jusqu'a l'arrivee d'un `X` T5 stable ;
- les traces `.old` et gros `.txt` restent locales et ne doivent pas etre poussees sur GitHub.

## Prerequis

- Windows
- Python 3.13+
- `customtkinter`

Tkinter est fourni par l'installation Python standard.

## Lancer l'application

Depuis la racine du depot :

```powershell
python TraceAlphaViewer\Main.py
```

## Rapport web React

Le bouton `Rapport web` utilise le build statique React/Next si celui-ci existe.
Pour reconstruire le rapport web :

```powershell
cd TraceAlphaViewer\report_app
npm install
npm run build
```

Si le build React est absent, le generateur Python conserve un fallback HTML local.

## Validation rapide

Compiler les modules principaux :

```powershell
python -m py_compile TraceAlphaViewer\Main.py TraceAlphaViewer\Models\state.py TraceAlphaViewer\Models\diagnostic.py TraceAlphaViewer\Models\diagnostic_report.py TraceAlphaViewer\Parser\trace_parser.py TraceAlphaViewer\Views\traceView.py TraceAlphaViewer\Widgets\machine_canvas.py TraceAlphaViewer\Widgets\diagnostic_panel.py
```

Points de controle visuel utiles avec les traces locales :

- autour de `09:03:36` a `09:03:39` : le transfert T4 vers T5 doit etre aligne sous T4 ;
- autour de `09:03:41` : `MAJ (BUTEE-T5) ... X:942` doit placer la boite cote butee ;
- autour de `09:03:45` : les boites `178372` et `178373` doivent etre separees visuellement sur T5.

## Raccourcis clavier

- `Left` / `Right` : frame precedente / suivante
- `Space` : lecture / pause
- `Home` / `End` : premiere / derniere frame
- `e` / `E` : incident ou erreur suivant / precedent

## Recherche par CIP

Dans l'onglet `References`, saisir un CIP, un barcode, un nom ou un identifiant
(`idB:102`, `IdA:201`). Chaque boite conserve sa propre ligne, meme si plusieurs
boites partagent le meme CIP. Cliquer sur une ligne pour rejoindre son premier
passage ; `Enter` ouvre le premier resultat filtre.

Dans la trace brute, le champ `CIP / texte` retrouve les occurrences d'un CIP,
d'une heure ou de tout autre texte. Les boutons `<` / `>` et les touches
`Enter`, `F3` / `Shift-F3` dans le champ permettent de passer entre les
occurrences et de synchroniser le viewer. La recherche attend la fin du
chargement de la trace brute.

## Controles automatiques

Depuis la racine du depot :

```powershell
python TraceAlphaViewer\Tools\validate_all.py
```

Cette commande lance les controles metier existants et les regressions du
viewer : identite des boites, recherche CIP, fermeture des vues et comparaison
du rendu canvas avec un dessin complet. Les controles qui dependent d'une
trace locale absente indiquent explicitement qu'ils sont ignores.

## Mesurer l'ouverture des grosses traces

Le benchmark conserve la precision complete et mesure separement le parsing,
les evenements, les diagnostics, les references, la preparation de la vue et
l'insertion de toute la trace brute. La fenetre est masquee par defaut ; ajouter
`--show` pour la rendre visible. Il ne cree aucun cache de trace.

```powershell
python TraceAlphaViewer\Tools\benchmark_loading.py TraceAlphaViewer\TracAlpha1_monistrol.txt
```

Pour comparer avec un commit anterieur, remplacer `REVISION_AVANT` par son
identifiant Git et executer ces commandes separement, sans autre traitement lourd :

```powershell
python TraceAlphaViewer\Tools\benchmark_loading.py TraceAlphaViewer\TracAlpha1_monistrol.txt --revision REVISION_AVANT --results-json TraceAlphaViewer\Tools\__pycache__\avant.json
python TraceAlphaViewer\Tools\benchmark_loading.py TraceAlphaViewer\TracAlpha1_monistrol.txt --compare-results TraceAlphaViewer\Tools\__pycache__\avant.json
```

La version Git des trois modules optimises est chargee en memoire, sans modifier
le depot. La comparaison verifie tous les champs et l'ordre des diagnostics et
references, ainsi que les nombres de frames, evenements et lignes. Le JSON
contient des donnees de diagnostic de la trace : il reste local et ne doit pas
etre versionne. Les temps incluent l'ouverture complete, sans profileur.

Les recherches de contexte diagnostic parcourent seulement la fenetre de lignes
utile. Les boites sans identite ne creent pas de fiches temporaires. Le texte brut
est insere par blocs en conservant les tags et la navigation ; les callbacks
entre blocs laissent l'interface traiter les autres actions.

Mesures locales du 8 octobre 2026, sans profileur et sans cache applicatif,
jusqu'a la fin du chargement du texte brut :

| Trace | Avant | Apres | Acceleration |
| --- | ---: | ---: | ---: |
| Monistrol | 242,4 s | 69,8 s | x3,47 |
| Marche | 125,8 s | 42,8 s | x2,94 |
| Domineuc | 4,2 s | 3,3 s | x1,27 |

Les diagnostics et references ont ete compares integralement et sont identiques
sur les trois traces. Ces durees correspondent a la machine de validation.

## Fichiers importants

- `TraceAlphaViewer/Main.py` : point d'entree de l'application
- `TraceAlphaViewer/Views/traceView.py` : viewer principal et controles
- `TraceAlphaViewer/Widgets/machine_canvas.py` : dessin machine et logique de placement
- `TraceAlphaViewer/Parser/trace_parser.py` : parser et cycle des boites
- `TraceAlphaViewer/Models/reference_index.py` : index references/boites
- `TraceAlphaViewer/Widgets/reference_panel.py` : onglet References
- `AGENTS.md` : decisions techniques, regles de contribution et points de validation

## Notes

- Le projet est centre sur l'inspection locale des traces Alpha.
- La position metier T5 utilise le `x_pos` trace, pas l'encodeur moteur `pT5`.
- Pour les details d'implementation et les decisions parser/rendu, voir `AGENTS.md`.
