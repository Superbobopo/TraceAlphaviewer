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
