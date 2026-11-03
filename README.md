# TraceAlphaViewer

Les cartes CB1 et CB2 montrent les boites decodees par chaque groupement sur
le meme total de passages decodes, avec leur pourcentage. Chaque passage compte
une fois, pour le premier lecteur qui reussit. Les passages sans decodage sont
exclus de ce total ; UNKNOWN final conserve le denominateur de tous les passages.
Les anciens rapports demandent une regeneration de cette repartition.

Les diagnostics Longueur, Largeur et Hauteur reprennent les memes boites hors
tolerance que les cartes du rapport, y compris les defauts sur plusieurs axes.
Une boite compte sur chaque axe concerne et une seule fois au bilan global.
Les anciennes analyses doivent etre rechargees et leurs rapports regeneres.

Le diagnostic T3/C5 signale aussi un transfert T3->T4 durablement bloque : refus
`-47` associe a une instabilite C5, ou etat logiciel en erreur observe pendant
au moins deux minutes. Un retour du code moteur a la normale ou une
initialisation ne prouve pas la reprise. Les durees portent sur les observations,
sans conclure a la presence physique de la meme boite pendant toute la periode.

TraceAlphaViewer est un viewer local Python/customtkinter pour traces Alpha `.old`.

Le rapport web et son PDF affichent la pharmacie et le numero Alpha lorsque la
paire de bases est identifiee sans contradiction. Cette identification fonctionne
pour une trace seule comme pour un dossier, avec les zeros initiaux du numero.

Les bilans distinguent les communications moteurs perturbees (`MOTOR_COMM`),
les peremptions explicitement absentes apres identification (`DP_MISSING`) et
les periodes de lecture en mode 123 (`CAMERA_CODE_MODE`, DataMatrix et
codes-barres, au lieu du mode 1 DataMatrix seul attendu). Les relectures DP
recuperees restent informatives ; seuls les episodes moteurs critiques apparaissent
dans les diagnostics (les reessais recuperes restent dans la trace brute). Les rejets DP
confirmes sont exclus des UNKNOWN de decodage, sans reduire le total des passages.
Les episodes et leurs preuves ne traversent pas les limites des fichiers.

Les ecarts internes T4C/T4T partagent une seule carte par Alpha : total des
controles, maximum absolu et fichiers concernes. Ils ne prouvent pas un ecart
avec la longueur du produit en base. Les details restent separes par fichier.
Le PDF terrain vise quatre a cinq pages : priorites, mesures, lecture/exploitation,
puis autres controles. Il conserve tous les types de problemes critiques/en alerte,
avec trois reperes au maximum et sans listes de preuves ni bilans quotidiens.
Les tableaux peuvent continuer sur une page supplementaire pour rester lisibles.

Il parse les lignes de trace en frames `MachineState`, puis affiche :

- le schema machine et les convoyeurs ;
- les capteurs et les etats tapis ;
- les boites qui circulent entre EA, T3, T4 et T5 ;
- les evenements et diagnostics ;
- la trace brute avec navigation cliquable.

## Manuel utilisateur illustre

Pour decouvrir le logiciel sans connaitre les traces Alpha :

- [Guide HTML « Bien demarrer avec TraceAlphaViewer »](docs/manuel-utilisateur/index.html) : ouvrir le fichier local dans un navigateur, avec sommaire cliquable et captures expliquees.
- [Manuel PDF a partager ou imprimer](docs/manuel-utilisateur/Bien-demarrer-avec-TraceAlphaViewer.pdf).

Le guide couvre l'ouverture, les capteurs et couleurs, le player, la recherche
CIP, les references, les diagnostics, les evenements, les rapports et les
dossiers/CSV. Il comprend une prise en main en cinq minutes, trois exercices,
une fiche des commandes et un glossaire. Les treize captures utilisent des
donnees fictives ; les traces terrain restent locales. Pour distribuer la
version HTML hors connexion, conserver le dossier du manuel avec `assets`.

Pour reproduire les captures et reconstruire le PDF, sous Windows avec Pillow
et Edge (Chrome est accepte en fallback) :

```powershell
python -m pip install pillow
python TraceAlphaViewer\Tools\generate_user_manual.py --captures --pdf
```

Les illustrations utilisent les vrais widgets et les parcours sont verifies
pendant leur generation. Apres un changement d'interface, relire les reperes
du HTML et controler le PDF. Les donnees de demonstration et profils navigateur
sont crees dans `.trace_work`, puis nettoyes.

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
- `msgpack` uniquement pour les essais du moteur Rust facultatif

Tkinter est fourni par l'installation Python standard.

## Lancer l'application

Depuis la racine du depot :

```powershell
python TraceAlphaViewer\Main.py
```

### Acceleration locale des calculs

Les calculs du parser, des references et des diagnostics peuvent etre compiles
depuis leurs sources Python avec Cython et Zig, sous CPython Windows 64 bits
avec GIL. Pour preparer cette acceleration sur le poste :

```powershell
python TraceAlphaViewer\Tools\build_acceleration.py --bootstrap
python TraceAlphaViewer\Tools\build_acceleration.py --check
```

La chaine est installee uniquement sous `build/python-acceleration`, sans
modifier Python ni le PATH utilisateur. Les extensions restent locales sous
`TraceAlphaViewer/bin/python-acceleration`, ignore par Git. Cette commande ne
reconstruit pas le viewer `.exe`. Le premier lancement de l'application ne
telecharge et ne compile rien.

Au demarrage, le lot actif doit correspondre aux sources, a la version de Python et aux
empreintes de toutes ses extensions. Sinon, l'application utilise les sources
Python ; relancer la commande de construction pour retrouver l'acceleration.
Les sources conservent les memes frames, analyses et fonctions du viewer.
Pour un controle comparatif, `TRACE_ALPHA_ACCELERATION=python` force les sources
Python dans le processus concerne. Une construction explicite ulterieure du
viewer peut embarquer le lot valide ; un lot present mais perime bloque ce
packaging jusqu'a sa reconstruction.

## Dossiers de traces par Alpha

`Ouvrir un dossier de traces` parcourt les sous-dossiers et presente les groupes
Alpha/pharmacie avant leur analyse. L'identite vient des noms complets des bases
`BASEALPHA_...MDB` et `BASEFIC...MDB` releves dans chaque fichier, sans utiliser
son nom ni sa date Windows. Par exemple, `BASEALPHA_#2025.031.MDB` avec
`BASEFIC1560LAHLOU.MDB` donne `Alpha 031 — Pharmacie Lahlou`.

Une identite incomplete ou contradictoire, un calendrier absent ou un
recouvrement ambigu garde le fichier isole sous `Identite a verifier`.
Les copies entieres strictement identiques, avec leurs en-tetes dates, sont
exclues du calcul et restent mentionnees dans le catalogue.

Selectionner un groupe prepare son viewer complet et son rapport commun.
Chaque fichier garde son propre cycle machine ; les boites et attentes ne
traversent pas les limites des fichiers. La navigation conserve le fichier et
la ligne d'origine. Fermer le viewer retrouve le catalogue et ses bilans deja
prepares. `Exporter CSV complet` analyse les groupes restants avant l'export.

Le catalogue et le parsing des dossiers utilisent Python, comme une trace seule.
Le moteur Rust reste disponible pour les comparaisons de performance, sans etre
requis au lancement. Pour preparer ce moteur experimental depuis les sources :

```powershell
python -m pip install msgpack
python TraceAlphaViewer\Tools\build_folder_engine.py --bootstrap --test
```

La chaine Windows GNU autonome reste dans `build/rust-toolchain`, sans modifier
le PATH utilisateur. Le binaire release est copie dans `TraceAlphaViewer/bin`.
Ces artefacts restent locaux et sont ignores par Git. Pour un essai explicite,
definir `TRACE_ALPHA_FOLDER_ENGINE=rust` dans le processus de lancement ; un moteur
absent ou incompatible produit alors une erreur. La valeur par defaut est `python`.

Essai local du 22 octobre 2026 sur les deux traces du groupe Martin : preparation
complete du bilan en 159,2 s avec Python, contre 164,4 s avec Rust (parsing,
conversion, stockage et analyses compris, hors affichage). Cette passe unique ne
demontre pas un gain global et ne constitue pas une garantie de performance.
Python reste donc le moteur par defaut. Comparaison reproductible :

```powershell
python TraceAlphaViewer\Tools\benchmark_folder_loading.py TraceAlphaViewer --group Martin --runs 3 --output build\folder-benchmark.json
```

## Executable Windows

Le fichier `dist/TraceAlphaViewer.exe` se lance par double-clic, sans installer
Python ni ouvrir PowerShell. Il contient le logo Alpha/convoyeur, les widgets
et le rapport web React. Les traces restent des fichiers externes : utiliser
`Ouvrir une trace` ou `Ouvrir un dossier` pour les choisir.

Les sessions temporaires du .exe sont creees dans
`%LOCALAPPDATA%/TraceAlphaViewer/.trace_work`, puis supprimees a la fermeture.
Le .exe peut etre copie seul sur un autre poste Windows 64 bits.

Pour reconstruire sous Windows, avec le rapport React deja construit :

```powershell
python -m pip install customtkinter pillow pyinstaller msgpack
python TraceAlphaViewer\Tools\build_folder_engine.py --bootstrap
python TraceAlphaViewer\Tools\build_exe.py
```

La recette `TraceAlphaViewer.spec` inclut uniquement les ressources necessaires,
jamais les traces locales. Le .exe et les fichiers intermediaires restent locaux
dans `dist/` et `build/`, ignores par Git.

Le logo est cree avec l'outil integre `imagegen`. Consigne de creation :
« Icone Windows TraceAlphaViewer : A angulaire, convoyeur avec deux boites,
signal de trace, tuile bleu marine, symbole turquoise et bleu, point diagnostic
ambre, sans texte, fond transparent autour de la tuile. »
Le PNG source et l'icone multi-resolution sont dans `TraceAlphaViewer/assets/`.
La [consigne exacte de creation](TraceAlphaViewer/assets/README.md) est conservee
avec ces deux fichiers.

## Compatibilite Alpha 1

Compatibilite Alpha 1 : les messages principaux de la trace gen1 examinee
sont reconnus, mais la qualification complete des diagnostics reste a faire.
Voir [les observations et limites Alpha 1](docs/compatibilite-alpha1.md).
Aucune correction automatique des mesures selon la generation n'est appliquee.

## Rapport web React

Les rapports sont conserves dans `Alpha reports` sur le Bureau Windows, classes
dans un sous-dossier par pharmacie. Le nom de chaque nouveau rapport contient
sa date et son heure de generation ; plusieurs rapports peuvent coexister.
Sans pharmacie fiable, le rangement utilise `Pharmacie non identifiée`.
Conserver avec chaque HTML son JSON, son manifeste et le dossier `_next`.

Le bouton `Rapport web` utilise le build statique React/Next si celui-ci existe.
Pour reconstruire le rapport web :

```powershell
cd TraceAlphaViewer\report_app
npm install
npm run build
```

Si le build React est absent, le generateur Python conserve un fallback HTML local.

Le rapport et ce secours partagent le meme affichage : synthese, filtres par niveau
et famille, recherche, fiches de problemes et exemples pages par 25. Le PDF se
telecharge directement. `Voir dans AlphaViewer` rejoint un exemple dans sa trace
source encore ouverte ; cette liaison locale expire a la fermeture de la vue.
Les fichiers enregistres restent consultables hors connexion.
Pour une meme vue, un nouveau clic sur `Rapport web` rouvre le rapport et sa
liaison locale sans recalculer les preuves. Une nouvelle trace ou des fichiers
de rapport supprimes imposent une nouvelle generation.
Le rapport se prepare dans la session temporaire apres affichage du viewer,
sans attendre le premier clic. Seul le clic le conserve dans `Alpha reports` ;
une preparation jamais demandee est supprimee avec la vue. Si le calcul est
encore en cours, le bouton indique l'attente avant ouverture.

Les boites T5 disposent d'une legende permanente : bleu clair non evalue,
vert conforme (hauteur jusqu'a 2 mm, longueur/largeur jusqu'a 3 mm inclus), orange orientation probable
ou indecidable, violet longueur T4/C6,
turquoise largeur T5/C9, jaune hauteur T5/LzB, rouge plusieurs dimensions hors
tolerance, rose largeur invalide avec C9 actif. Le survol donne les mesures,
references et ecarts. Le graphique garde sa taille native 920 x 540, y compris
lorsque Windows agrandit les autres controles.

Le diagnostic affiche des incidents multiligne et deux panneaux defilants avec
des barres sombres arrondies. Les bilans donnent les bonnes et mauvaises mesures
sur le total comparable, les exclusions et le nombre de cycles analyses sur T5.
Une boite compte une fois par cycle Alpha, meme si plusieurs axes sont en erreur.
Les mauvaises mesures sont presentees en premier : plage signee (mesure moins
BdD), pire ecart en moins et en trop, decalage moyen signe et erreur moyenne
independamment du sens. Exemple : +6, -4 et +9 mm donnent une plage -4 a +9 mm,
un decalage moyen +3,7 mm et une erreur moyenne 6,3 mm. Les chiffres sur toutes
les mesures restent accessibles dans les details. Le **Bilan des mesures de la
trace** distingue les observations, leur repetition par produit et les controles
a envisager, sans conclure automatiquement a une cause.
Une anomalie depasse 2 mm en hauteur et 3 mm en longueur/largeur, en valeur
absolue. Les limites exactes restent conformes. Ces seuils partages s'appliquent
aux couleurs, aux diagnostics et au PDF. Regenerer le rapport pour utiliser le
nouveau seuil hauteur ; les anciens rapports gardent leurs seuils historiques. Les references sont des produits
distincts : 28 references anormales sur 119 comparables signifie 28 produits avec
au moins une mauvaise mesure sur cet axe, pas 28 boites. Les ecarts de signes
opposes se compensent dans le decalage moyen ; l'erreur moyenne mesure leur
amplitude sans signe. Une moyenne seule ne permet pas de choisir un reglage.

Le bilan exige une preuve explicite de reconnaissance CB1 ou CB2 et la BdD du
meme produit. Une recherche BdD seule, une identite contradictoire ou une mesure
incomplete est exclue. Une UNKNOWN correctement relue reste eligible, comme
un produit reconnu puis rejete `[Dinh]`. La rubrique **Boites dans le mauvais sens** liste toutes les references avec une
orientation probable, sans filtre de 10 %, et separe les orientations indecidables.
Les proportions portent sur les cycles exploitables du produit avant exclusion
pour orientation. Un clic rejoint sa premiere boite concernee apres les trois
mesures ; chaque boite conserve sa navigation. Les permutations les plus proches
restent une deduction, pas une certification du sens physique.
Le sens est estime en comparant la somme
des ecarts absolus pour chaque permutation distincte des dimensions BdD : une
autre presentation meilleure, ou a egalite, exclut le cycle. Les orientations
probables et indecidables sont comptees separement ; cette estimation ne certifie
pas le sens physique de la boite.

Dans **Trop petites / Trop grandes**, cliquer sur une reference ouvre son detail
et rejoint l'etat complet de la boite au pire ecart, apres les trois mesures.
L'axe choisit le detail ; l'instant conserve les valeurs du rapport. A egalite,
la premiere ligne source puis le cycle departagent les boites. Les autres boites
restent accessibles individuellement. Sans ligne source ou sans viewer lie, la
navigation est indisponible et le detail web reste consultable. L'identite et les
trois valeurs sont verifiees dans cette seule frame. Un ancien rapport sans cible
complete doit etre regenere depuis la trace.
Le rapport commence par trois priorites maximum, avec un constat et un premier
controle. Les diagnostics de dimensions sont critiques des 10 % des comparables
et au moins 10 boites ; leur priorite tient compte de la proportion concernee,
pour chaque trace et chaque axe, sans modifier les compteurs des groupes. Trois cartes Longueur/Largeur/Hauteur donnent les boites et produits
concernes, les boutons Trop courtes/longues, etroites/larges, basses/hautes et les
ecarts marquants des produits ayant au moins 10 % de defauts du cote choisi.
Les autres produits restent dans Cas rares (< 10 %), avec detail et navigation ;
toutes leurs mesures restent incluses dans les totaux et distributions.
La repartition affiche les cinq ecarts les plus frequents sous les observations ;
Afficher toute la repartition deroule toutes les lignes et Reduire la liste
revient a la synthese. Les calculs et le PDF incluent toujours toutes les mesures. Les depliants Statistiques et explications sont retires du web et du PDF. Les variantes restent accessibles dans le detail produit. Chaque
boite presente un tableau BdD/Mesure Alpha/Ecart ; les lignes brutes sont dans
Sources et contexte technique. Le PDF presente une synthese visuelle ; ces details restent dans le web.
Les observations courtes sont visibles directement, separees en moins et en
trop. Les calculs restent inchanges. Chaque groupe est centre sur l'ecart hors tolerance le plus frequent de
son cote (en cas d'egalite, le plus proche de zero). Il inclut les mesures a
+/-1 mm, meme conformes : le bilan distingue defauts, bonnes mesures voisines
et part du groupe sur toutes les comparables. La repartition complete est dans
les details ; un groupe ne represente pas automatiquement toute la machine.

La repetition se verifie avec toutes les mesures de chaque produit, a dimensions
BdD identiques : au moins deux mesures, dont 80 % proches du meme centre. Un
produit vu une seule fois ne la confirme pas. Deux produits mesures plusieurs
fois et montrant cette concentration etayent une repetition commune : verifier
parametrage/calibrage, mesurer quelques boites physiquement et controler leur
BdD. Sur un seul produit, examiner d'abord sa fiche et sa presentation. Les
variantes BdD restent separees ; la contribution du produit dominant est visible.
Un effectif inferieur a dix ajoute seulement une reserve sur la confiance.

Une dispersion est observee seulement au sein d'un meme produit et d'une meme
variante BdD : sa plage depasse 2 mm et aucune fenetre de 2 mm ne contient 80 %
de ses mesures. Dans ce cas, les ecarts T4 en moins peuvent orienter vers
l'entrainement/patinage et ceux en trop vers le positionnement ou les detections
parasites de C6. Les controles largeur/hauteur restent adaptes a C9/LzB. Des
ecarts differents entre produits ne prouvent pas une variation mecanique. Des
groupes opposes sur un produit invitent a examiner sa presentation, la chronologie
et les lignes sources. Toutes ces pistes restent a confirmer.
La longueur principale utilise exclusivement **T4C**, avec sa ligne source.
T4T et `diffT4` restent des complements distincts ; une T4C absente n'est jamais
remplacee par T4T. Les vraies UNKNOWN, les identifications non confirmees et les
references contradictoires sont exclues du bilan et comptees separement. Un produit
reconnu par CB2 ou identifie puis rejete en `[Dinh]` conserve sa reference produit
pour la comparaison, avec une mention du rejet.

Cliquez sur **Trop petites** ou **Trop grandes** pour retrouver les references
responsables des ecarts, triees par pire ecart absolu puis par nombre de boites.
Chaque reference donne son nom, son nombre de mauvaises mesures sur le total
comparable, son pourcentage et sa plage signee. Ouvrez-la pour les boites et leurs
lignes sources, par pages de 25, puis **Voir dans AlphaViewer** pour les retrouver.
Ces listes fonctionnent aussi dans le rapport hors connexion ; le PDF reprend
les trois references aux plus grands ecarts de chaque cote et pour chaque axe.
Les preuves detaillees sont conservees dans la session locale,
sans parcours complet de `FrameStore` dans le thread de l'interface.

Les controles de navigateur et PDF necessitent `playwright`, Microsoft Edge et
`pypdfium2` dans l'environnement de validation, pas dans le logiciel livre.
`validate_all.py` reste en arriere-plan ; ajouter `--visual` seulement pour
autoriser les controles avec fenetres visibles. Les benchmarks restent aussi
masques sauf avec `--show`, y compris avec `--exercise-window`.
Le controle du binaire est exclu par defaut ; ajouter `--exe` apres une
reconstruction explicitement demandee, pour valider le binaire courant.

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

Le diagnostic `REFERENCE_ABSENT` distingue un CIP lu dont la fiche manque dans les
tables, avec creation refusee par l'Alpha, des UNKNOWN de decodage. Sa carte
« References absentes — chargement manuel requis » indique les CIP, les boites
et les preuves dans le logiciel, le rapport web et le PDF. La fiche doit etre
creee par la zone de chargement manuel. Les ratios camera utilisent les passages
physiques ; les numeros `Hist_LectCB` reutilises ne fusionnent plus les boites.

Le diagnostic `REFERENCE_NON_ALPHATISABLE` distingue le refus explicite
`ref. non Alphatisable` des deux cas precedents. Sa carte « References non
alphatisables » conserve le CIP lu, le motif exact, les lecteurs, les identites
et les preuves. Verifier la fiche et la raison de l'exclusion Alpha ; ce cas
ne demande pas une creation par chargement manuel. Il est exclu de tous les
compteurs UNKNOWN de decodage, meme si CB1 avait d'abord echoue avant CB2.

Dans l'onglet `References`, saisir un CIP, un barcode, un nom ou un identifiant
(`idB:102`, `IdA:201`). Chaque boite conserve sa propre ligne, meme si plusieurs
boites partagent le meme CIP. Cliquer sur une ligne pour rejoindre son premier
passage ; `Enter` ouvre le premier resultat filtre.

Dans le viewer principal, cliquer sur la loupe a cote de `Masquer details`
pour afficher la recherche, masquee au demarrage. La loupe ou `Echap` dans le
champ la masque sans effacer la saisie ni les resultats.
Dans la trace brute, le champ `CIP / texte` retrouve les occurrences d'un CIP,
d'une heure ou de tout autre texte. Les boutons `<` / `>` et les touches
`Enter`, `F3` / `Shift-F3` dans le champ permettent de passer entre les
occurrences et de synchroniser le viewer. La trace brute est entierement
chargee avant l'ouverture du viewer depuis l'accueil.

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

La version Git des modules concernes est chargee en memoire, sans modifier
le depot. La comparaison verifie tous les champs et l'ordre des diagnostics et
references, ainsi que les nombres de frames, evenements et lignes. Le JSON
contient des donnees de diagnostic de la trace : il reste local et ne doit pas
etre versionne. Les temps incluent l'ouverture complete, sans profileur.

Pour isoler l'etape diagnostic sans Tk, `benchmark_diagnostics.py` mesure chaque
famille, les references, le stockage et le pic memoire. `--baseline-dir` charge
une copie locale des six modules `diagnostic`, `c2_analysis`, `c5_analysis`,
`trace_calendar`, `trace_observations` et `robot_drain`, sans toucher au depot.

```powershell
python TraceAlphaViewer\Tools\benchmark_diagnostics.py C:\Traces\Monistrol.txt --full --results-json TraceAlphaViewer\.trace_work\avant.json
python TraceAlphaViewer\Tools\benchmark_diagnostics.py C:\Traces\Monistrol.txt --full --compare-results TraceAlphaViewer\.trace_work\avant.json --results-json TraceAlphaViewer\.trace_work\apres.json
```

La comparaison exige les memes incidents complets, mesures, cameras, evenements,
references, index de navigation et metadonnees. Le total de cet outil couvre le
worker metier ; `benchmark_loading.py --ui-latency` mesure aussi l'affichage reel.
Les JSON contiennent des preuves terrain et restent strictement locaux.

Mesures locales du 26 octobre 2026 pour l'optimisation des diagnostics, en
precision trace, sans profileur et sans analyse concurrente :

| Trace | Diagnostics avant | Apres | Acceleration |
| --- | ---: | ---: | ---: |
| Monistrol | 65,2 s | 34,2 s | x1,91 |
| Astier | 78,8 s | 41,0 s | x1,92 |
| Atout Sud | 37,6 s | 22,2 s | x1,69 |

Tous les resultats compares sont identiques ; le pic memoire varie de moins de
0,4 %. L'ouverture reelle de Monistrol depuis l'accueil, texte brut compris,
passe de 127,7 a 100,0 s ; l'interface reste reactive. La navigation, la recherche
CIP et la lecture sont controlees hors mesure.
Ces temps sont indicatifs et dependent de la machine et de la trace. Lors de
cette premiere passe, le parser restait inchange. Les analyses partagent la chronologie et les faits textuels du
segment, sans cache de reouverture ni raccordement entre fichiers.

La passe suivante traite les frames au fil de la lecture : un collecteur commun
prepare evenements, mesures, references et lignes diagnostiques, puis les
snapshots independants sont ecrits par blocs de 500. Le chargement ne conserve
plus toute la liste des frames en memoire. `parse_file` reste disponible pour
les usages demandant une liste, avec les memes parametres et resultats.

La barre affiche une progression globale estimee. Les cinq etapes couvrent la
lecture/construction, les diagnostics, la finalisation des references, la
preparation du viewer et l'insertion du texte brut. Le viewer apparait lorsque
les analyses, les premieres pages et toute la trace brute sont pretes ; 100 %
est reserve a cet instant. Les phases avancees sont mesurees en travail realise,
sans animation fondant le pourcentage sur le temps ecoule.

Pour mesurer le worker complet et son pic memoire, puis comparer tous les champs
des frames et les artefacts metier hors chronometre, utiliser une copie locale
figee de l'etat precedent (repertoires `Models` et `Parser` compris) :

```powershell
python TraceAlphaViewer\Tools\benchmark_streaming_loading.py C:\Traces\Monistrol.txt --source-tree C:\Sources\Reference --results-json TraceAlphaViewer\.trace_work\flux-avant.json
python TraceAlphaViewer\Tools\benchmark_streaming_loading.py C:\Traces\Monistrol.txt --compare-results TraceAlphaViewer\.trace_work\flux-avant.json --results-json TraceAlphaViewer\.trace_work\flux-apres.json
```

Ces JSON et les copies de sources de reference restent locaux. Le benchmark
ne charge ni Tk ni les vues ; completer avec la mesure depuis l'accueil pour
inclure l'affichage et verifier la reactivite.

Mesures de cette seconde passe, le 26 octobre 2026, avec comparaison aux sources
locales deja optimisees ci-dessus. L'ouverture complete inclut le texte brut ;
le pic memoire porte sur le worker metier, avant le calcul des empreintes :

| Trace | Ouverture avant | Apres | Gain de temps | Pic worker avant / apres |
| --- | ---: | ---: | ---: | ---: |
| Monistrol | 99,0 s | 86,5 s | 12,6 % | 7 407 / 760 Mio |
| Astier | 102,3 s | 90,9 s | 11,1 % | 5 110 / 753 Mio |
| Atout Sud | 54,8 s | 50,3 s | 8,2 % | 2 413 / 415 Mio |

Toutes les frames et tous les artefacts compares sont identiques. Le gain de
temps reste sous la cible de 20 % ; la memoire du worker est divisee par 5,8 a
9,7. Le percentile 95 UI reste sous 17 ms et la pause maximale sous 267 ms.
Les poids de progression utilisent la mediane des parts mesurees sur ces trois
ouvertures, sans cache de trace. Les scenarios dossier conservent leurs limites
de fichiers et leurs deux sous-workers, dont les files sont drainees ensemble.

Les recherches de contexte diagnostic parcourent seulement la fenetre de lignes
utile. Les boites sans identite ne creent pas de fiches temporaires. Le texte brut
est insere par blocs en conservant les tags et la navigation ; les callbacks
entre blocs laissent l'interface traiter les autres actions.

Pour une trace seule, l'accueil peut preparer le texte brut pendant les calculs
si les ressources disponibles sont suffisantes. Le viewer reprend le meme
tampon Tk, sans recopier ses lignes ni relire le fichier. L'affichage attend
toujours les analyses, les premieres pages et le texte complet. Sur un poste
moins equipe, la preparation reste sequentielle. La fermeture ou une erreur
annule aussi cette preparation temporaire.

La nouvelle passe combine les calculs compiles depuis les memes sources Python,
les decodages textuels bornes au fichier, les copies independantes des snapshots,
la repartition des diagnostics, la projection diagnostique transmise par blocs
et la reutilisation de la base horaire consecutive du parser. La reference est
une copie figee des sources locales avant cette intervention, incluant les
modifications deja presentes. Mesures sans profileur ni cache applicatif de
trace, depuis l'accueil jusqu'au viewer entierement pret :

| Trace | Ouverture avant | Apres | Temps en moins | Repetitions par version |
| --- | ---: | ---: | ---: | ---: |
| Monistrol | 103,8 s | 39,2 s | 62,2 % | 3 (medianes) |
| Marche | 65,6 s | 31,4 s | 52,1 % | 1 |

Les trois ouvertures Monistrol conservent un percentile 95 UI sous 18,8 ms et
une pause maximale de 486,5 ms. La preparation anticipee du texte etait active
dans ces essais ; son activation depend de la memoire disponible. Ces mesures
qualifient ce poste et ces traces, sans promettre le meme gain sur chaque
fichier ou avec moins de ressources.

Mesures locales du 8 octobre 2026, sans profileur et sans cache applicatif,
jusqu'a la fin du chargement du texte brut :

| Trace | Avant | Apres | Acceleration |
| --- | ---: | ---: | ---: |
| Monistrol | 242,4 s | 69,8 s | x3,47 |
| Marche | 125,8 s | 42,8 s | x2,94 |
| Domineuc | 4,2 s | 3,3 s | x1,27 |

Les diagnostics et references ont ete compares integralement et sont identiques
sur les trois traces. Ces durees correspondent a la machine de validation.

Pour comparer un dossier sans perdre les modifications locales preexistantes,
conserver une copie des sources et des resultats dans `build` :

```powershell
python TraceAlphaViewer\Tools\benchmark_group_pipeline.py C:\Traces\Dossier --output build\dossier-avant --snapshot --filters
python TraceAlphaViewer\Tools\benchmark_group_pipeline.py C:\Traces\Dossier --output build\dossier-apres --compare build\dossier-avant --reuse-filter-checks
```

La comparaison relit toutes les frames et verifie les evenements, diagnostics,
references, mesures et cameras. Les six filtres deja controles sont reutilises
seulement si toutes les frames, evenements et le code de leur moteur sont
identiques ; sinon employer `--filters`. `benchmark_group_view.py` mesure
separement la preparation masquee des panneaux depuis ces resultats.
Pour une trace seule, `benchmark_loading.py --source-tree <copie-des-sources>`
permet d'utiliser cette reference locale a la place d'une revision Git.

## Garder la fenetre reactive pendant le chargement

L'accueil demarre dans une fenetre etroite de 900 x 860 (minimum 820 x 750,
adapte a l'ecran). Les pages dossier et viewer retrouvent une grande fenetre.
Son accueil bleu nuit presente deux cartes cote a cote : **Une trace** pour
un fichier et **Un dossier** pour les regroupements par machine. La frise
de signal est decorative ; elle laisse place au suivi des etapes pendant
le chargement. Les boutons conservent une largeur de 270 px.
Les textes de presentation sont centres ; le bloc de marque en haut a gauche
est retire. Le viewer reprend la palette bleu nuit et menthe via
`Widgets/ui_theme.py`, sans changer les polices ni la geometrie. Les composants
partages gardent leur style hors viewer. Les couleurs metier et les
surbrillances de recherche restent identiques.
Le lissage de la frise utilise Pillow, optionnel : sans ce module, le dessin
Tk reste disponible et l'accueil fonctionne normalement. Pour activer le
lissage, utiliser le meme Python que pour lancer le viewer :

```powershell
python -m pip install pillow
```
Sur l'accueil, les barres CPU/RAM de 160 px affichent l'utilisation globale du PC chaque
seconde, y compris pendant le chargement. Elles sont absentes du viewer.
Les indicateurs restent en haut a droite, sans reglage manuel. Les accelerations
s'adaptent toujours automatiquement au PC. Les anciens plafonds de `settings.json`
sont ignores ; ce fichier n'est plus lu ni ecrit. Le budget des accelerations
n'est pas une limite de memoire totale : les donnees indispensables s'y ajoutent.

Auto partage entre toutes les sessions un budget egal au minimum de 8 Gio, de
la moitie de la RAM disponible et de la RAM disponible apres une reserve de
max(2 Gio, 20 % de la RAM totale), sans forcer d'allocation. Les API Windows suffisent, sans dependance ajoutee.
La surveillance chaque seconde libere les caches supplementaires sous pression
et reduit les prochains lancements ; les calculs actifs peuvent se terminer.
Sans mesure fiable, le logiciel garde un seul calcul et deux blocs en cache.

Les profils paralleles doivent gagner au moins 10 % en mediane sur trois essais,
sans regression de plus de 5 % sur leurs cas de qualification. La lecture du
parser reste sequentielle. Une trace seule peut deleguer C2/C3, C5 et
communication/modes/T5/resets via une projection compacte privee ecrite une
seule fois. Le processus principal conserve camera, evenements, dimensions et
assemblage. Un dossier delegue les segments, avec diagnostics internes
sequentiels ; le logiciel limite l'ensemble a quatre calculs et laisse deux
processeurs logiques disponibles quand le PC le permet. GPU et VRAM ne sont pas
utilises. Les profils insuffisamment rapides conservent le chemin precedent.

Qualification locale du 26 octobre 2026, Python 3.13, PC de 16 processeurs
logiques et 31,1 Gio de RAM : trois ouvertures completes par configuration,
sans profileur. Le pic ci-dessous est la mediane des pics de memoire cumulee
des processus mesures pendant le chargement, pas seulement du worker principal.

| Trace | Mediane precedente | Automatique | Gain | Pic cumule avant / apres |
| --- | ---: | ---: | ---: | ---: |
| Monistrol | 96,0 s | 82,4 s | 14,1 % | 1 091 / 2 697 Mio |
| Astier | 97,6 s | 77,4 s | 20,7 % | 1 284 / 2 653 Mio |
| Atout Sud | 50,3 s | 41,5 s | 17,3 % | 715 / 1 451 Mio |

Le groupe Lahlou (quatre segments valides) passe de 9,41 a 8,34 s en mediane
sur l'ouverture complete, soit 11,4 %. Son worker seul passe de 8,06 a 6,84 s.
La mediane des pics cumules pendant l'ouverture passe de 225 a 327 Mio.
Le profil dossier a quatre segments est retenu ; a trois places disponibles,
le logiciel conserve le profil precedent a deux segments.

Les trois cas conservent integralement leurs resultats. Le percentile 95 UI
reste sous 18 ms et la pause maximale sous 291 ms. Le profil trace seule
qualifie concerne les fichiers d'au moins 64 Mio, avec assez de CPU et de budget
pour quatre calculs. Les profils a deux ou trois calculs restent sequentiels.
Ces mesures illustrent un compromis temps/memoire, sans garantir le meme gain
sur un autre PC.

Sur un parcours de 200 retours repartis entre vingt blocs, Astier passe de
1,52 a 0,45 s avec 58 Mio de cache supplementaire ; Atout Sud de 1,73 a 0,57 s
avec 75 Mio. Les lectures de blocs passent de 200 a 20, les autres acces sont
servis par le cache. Ces mesures de navigation sont distinctes du chargement.

`Tools/qualify_auto_resources.py <dossier-traces> --baseline <sources-figees>
--output <dossier-local>` repete les ouvertures de Monistrol, Astier, Atout Sud
et du groupe Alpha 031 de Lahlou. `--reuse` est reserve aux controles acquis
dont les sources sont restees inchangees. Les mesures et les copies de reference
restent locales ; aucun profil n'est active automatiquement par cet outil.

L'ouverture depuis l'accueil execute les analyses dans un processus Python
separe sans interface graphique. Pour un dossier, ce worker appelle le moteur
Python pour le catalogue et le parsing ; Rust reste un mode experimental explicite.
L'accueil affiche la progression estimee jusqu'a la preparation des analyses,
des premieres pages et de toute la trace brute. La precision reste `min_dt=0.0`.

Les frames sont conservees uniquement pour la session dans
`TraceAlphaViewer/.trace_work/session-*`, ignore par Git. `FrameStore` expose une
sequence : blocs de 500 frames, deux blocs de base et index compact des lignes.
Le viewer peut conserver jusqu'a 256 Mio supplementaires dans le budget commun
pour les retours de navigation ; les lecteurs sequentiels gardent deux blocs.
La navigation lit uniquement les blocs utiles. Ce stockage temporaire demande
de l'espace disque, mais ne constitue pas un cache de reouverture. La fermeture
ou l'annulation supprime la session en arriere-plan ; une vue gardee comme
`_return_view` garde sa session jusqu'a sa destruction. Les filtres metier et le
rapport utilisent un lecteur independant dans leur propre worker.

Les files de reception sont bornees a quatre messages. La reception et le texte
brut rendent la main apres un budget d'environ 8 ms ; chaque insertion brute
porte sur 500 lignes au maximum. Les listes sont remplies progressivement avec
un appel Tk groupe par bloc et la construction des widgets est decoupee.
Les onglets Evenements, Erreur et References affichent des pages de 500 elements.
Recherches et filtres portent sur toutes les donnees ; une navigation vers une
ligne ouvre automatiquement la page correspondante. Les premieres pages et les
analyses ainsi que le texte brut sont prets avant l'ouverture du viewer. Les analyses de dossier
partagent un parcours des frames et un calendrier par segment.
Sous Windows, un a quatre segments peuvent etre analyses selon les ressources
et le profil qualifie, puis reunis
dans l'ordre des fichiers. L'annulation ferme aussi les sous-workers et leurs
lecteurs ; aucun resultat de groupe partiel n'est affiche.
Un appel Tk individuel ne peut pas etre interrompu : la mesure des intervalles
reste donc le controle effectif de la reactivite.

Pour mesurer une ouverture reelle avec deplacements, redimensionnements et
reductions de la fenetre :

```powershell
python TraceAlphaViewer\Tools\benchmark_loading.py TraceAlphaViewer\TracAlpha1_monistrol.txt --ui-latency --exercise-window --require-responsive --timeout 180 --results-json TraceAlphaViewer\Tools\__pycache__\monistrol_reactif.json
```

Executer les deux grosses traces separement, sans profileur ni autre traitement
lourd. `--require-responsive` exige un percentile 95 sous 100 ms et aucun
intervalle superieur ou egal a 500 ms. `--compare-results` verifie les analyses
contre l'export precedent. Ajouter `--verify-frames --verify-analyses` pour
comparer tous les champs des frames et evenements au parser direct, les six
filtres metier et le rapport complet (hors date de generation). Ces comparaisons
ont lieu apres la mesure, une fois la fenetre fermee. `--check-navigation`
controle la recherche CIP, la synchronisation des frames et le player ;
`--screenshot` permet une capture locale du viewer.

Mesures locales du 9 octobre 2026, depuis l'accueil jusqu'a la fin du texte brut :

| Trace | Ouverture initiale | Chargement reactif | Gain | Percentile 95 | Pause maximale |
| --- | ---: | ---: | ---: | ---: | ---: |
| Monistrol | 242,4 s | 82,1 s | x2,95 | 20,7 ms | 230,2 ms |
| Marche | 125,8 s | 55,3 s | x2,28 | 20,2 ms | 149,4 ms |

Apres ajout des bilans de mesure, controles en arriere-plan le 9 octobre 2026 :
Monistrol 79,4 s (p95 16,5 ms, maximum 215 ms), Marche 55,3 s
(p95 16,4 ms, maximum 210,2 ms). Les benchmarks n'ouvrent plus de fenetre
visible par defaut. Les controles de disposition 1920 x 1080 ont ete valides
separement aux echelles d'interface 100 %, 125 % et 150 %.

Domineuc charge tout son texte en 4,7 s (pause maximale 131,3 ms), avec les memes
diagnostics et references et une navigation validee. Sur une petite trace, le
lancement du processus et le stockage temporaire ajoutent un cout fixe ;
l'objectif de gain x2 concerne les deux grosses traces.

Les frames, evenements, diagnostics, references, filtres et rapports ont ete
compares integralement sur les deux traces. `validate_reactive_loading.py`,
inclus dans `validate_all.py`, controle aussi les lectures aleatoires, les
limites des blocs, le cache, les erreurs de stockage/worker, les annulations,
le nettoyage, les vues de retour et le viewer de dossier.

## Rapport : UNKNOWN, series et navigation

Le compteur UNKNOWN en tete du rapport affiche les boites finales inconnues apres
CB1 et CB2 sur le total des boites passees. Compact et non cliquable, il est vert
sous 8 %, jaune de 8 a 12 % inclus, rouge au-dela de 12 % et neutre si le taux est
indisponible. Il remplace l'encart et le detail UNKNOWN dedies. Le diagnostic
habituel reste dans la liste au-dessus de 7 % strictement. Les UNKNOWN temporaires
reconnues ensuite sont exclues.

Le badge UNKNOWN se place a droite du titre des priorites. Le radar
`health_radar` v2 est une quatrieme carte apres les priorites 1, 2 et 3, sans
numero. La grille passe de quatre colonnes a deux sous 1100 px, puis une sous
700 px. Il mesure l'impact relatif sans changer la gravite des
diagnostics : rayon `1 - proportion concernee` pour les boites, et
`1 / (1 + incidents par heure couverte)` pour moteurs et resets. Ainsi, 25 boites
evacuees sur 1945 sorties representent 1,29 %, meme avec une carte critique.
Le clic donne les populations, limites et diagnostics associes ; une population
inconnue reste grise et les transferts partiellement attribuables sont signales.
Web et PDF partagent les valeurs. Recharger les traces et regenerer les anciens
rapports pour disposer des nouvelles metriques.
Pour Cameras, la couleur souligne le taux UNKNOWN : vert a 0 %, orange a 8 %,
rouge des 12 %, avec interpolation continue, sans changer le rayon proportionnel.
Pour Transferts, un meme blocage ou probleme d'initialisation T4 repete des deux
occurrences impose au moins l'orange, meme si le ratio de cycles reste faible.
Les effectifs des diagnostics ne sont pas additionnes aux cycles concernes.
Pour Mesures, la part de boites hors tolerance est en alerte strictement au-dela
de 8 %, critique strictement au-dela de 15 %, tous axes confondus sans doublons.
Le message normal de liaison au viewer est masque ; erreurs et retours de
navigation restent affiches.

Les vidages T5 demandes par le robot restent en Information sous 10 demandes sur
24 heures glissantes, sans bandeau ni presence dans les priorites. Ils deviennent
Critiques des 10, bornes incluses. Le detail garde les journees sans demande et
jusqu'a dix preuves sur toute la periode. Les anciens seuils horaires et le renforcement
a 15 ne s'appliquent plus ; regenerer les anciens rapports exportes.

La carte `C2_SIGNAL_ANOMALY`, famille T2, distingue les episodes, bascules C2,
relances de vidage et demandes d'initialisation T2. Elle devient Alerte a partir
de dix bascules sur au moins cinq minutes sans progression T2, C3/C4 a zero.
Une relance explicite suivie dans les trois lignes et deux secondes d'un etat
complet avec C2 seul actif parmi C2/C3/C4/C5/C6/C9 suffit pour un niveau Critique.
Progression T2, activation C3/C4, redemarrage logiciel ou interruption des
observations superieure a deux minutes terminent la sequence. Les exemples
conservent alternances, blocages et reprises avec navigation vers les sources.
Verifier obstacle, proprete, alignement et cablage ; une reprise ne prouve pas
une reparation du capteur.

`C3_SIGNAL_ANOMALY` ajoute une carte distincte avec les memes seuils. Ses
alternances sont surveillees avec C2/C4 a zero ; un blocage critique exige C3 seul
actif dans l'etat complet suivant la relance du vidage. Une activation C2 termine
le contexte C3 sans prouver une reprise du transfert. Le moteur d'analyse est
partage avec C2, dont les regles restent identiques. Les deux capteurs conservent
leurs propres episodes, compteurs et preuves ; les bascules n'amplifient pas la
priorite. Les exemples C3 du manuel sont fictifs.

`C5_SIGNAL_ANOMALY`, zone T3/C5, utilise une analyse distincte : dix bascules
dans cinq minutes glissantes entre deux transferts EA->T3 confirmes declenchent
une alerte. Un cycle lie par IdB/IdA devient critique si sa longueur T3->T4 est
nulle, si la trace signale explicitement l'absence sur C6 et si T5 le supprime
pour largeur < 2 mm avec C9=0. Les creations virtuelles apres pesee sont
comptees separement ; une boite fantome reste probable, sans modifier UNKNOWN.
Chaque episode garde ses limites et dix preuves au maximum. Aucune attribution
ne traverse un redemarrage, une interruption de plus de 120 s ou un fichier.

A gravite egale, les blocages confirmes pendant au moins deux minutes passent
avant les incidents ponctuels. Ils se classent par duree observee cumulee, puis
cycles touches, episodes distincts et premiere ligne. Les chevauchements ne
multiplient pas la duree ; interruptions et fichiers restent separes. Les
bascules C5 seules ne prouvent pas un blocage. Les autres diagnostics gardent
leur classement habituel. Une duree inconnue invite a regenerer le rapport.
Viewer, priorites, liste complete web et PDF partagent cette regle.

La priorite robot garde seulement le nombre de demandes sur la periode, les
boites evacuees, les prises confirmees et leur part evacuee, puis Premier
controle. Les prises confirmees excluent les vidages. Le ratio utilise
evacuees / (evacuees + prises confirmees), apres sommation des segments ; il
ne mesure pas les tentatives de prise ratees. Dates et bilans incomplets
restent consultables dans le detail.

Les repetitions d'un meme incident sont rassemblees en une carte avec son total
et sa periode. Le detail prepare au plus dix preuves distinctes par type de
probleme hors dimensions, reparties sur toute la periode, premiere et derniere
comprises. Les compteurs et gravites utilisent toutes les occurrences ; seules
les preuves selectionnees et leurs incidents sont exportes. Les series retenues
gardent leurs limites et fichiers sources. Les mesures et orientations conservent
toutes leurs preuves et leur pagination habituelle.
Un numero de ligne dans les preuves rejoint cette ligne dans le viewer ; le
bouton de boite mesuree rejoint toujours l'etat complet apres les trois mesures.

Le bilan des vidages T5 robot indique le total sur les jours calendaires de toute
la trace et distingue les boites evacuees dans les blocs complets attribues au
robot des prises confirmees par `OMEGA:T5-DEL-PACK@Ok` sur toute la periode.
Les preuves conservent les IdA et les lignes sources ; les suppressions seules,
les vidages sans origine certaine et les demandes tronquees ne deviennent pas
des prises reussies ni des boites evacuees attribuees. Regenerer les anciens rapports.

Le calendrier des vidages T5 robot couvre les jours calendaires de toute
la trace et sa periode datee. Son detail regroupe les demandes par jour, y compris
les jours a zero, avec dix preuves navigables maximum sur toute la periode, prises
confirmees comprises. Les dates viennent
de l'en-tete et de l'origine horodatee ; une ancienne session sans origine invite
a recharger la trace. Les seuils restent utilises pour le classement.

Sur grand ecran, les cameras occupent une colonne compacte a droite ; sur petit
ecran, elles passent sous les priorites. Les orientations montrent quatre
references puis un detail depliable avec la liste complete. Le bandeau robot
n'est pas duplique lorsque le diagnostic figure deja parmi les trois priorites.

La periode observee indique les dates completes et la duree totale en heures,
meme sans incident robot, depuis les metadonnees compactes de la session.
Les orientations distinguent longueur/largeur inversees (rotation a plat probable)
et largeur/hauteur inversees (boite sur la tranche probable). Les controles de ce
second cas portent sur la presentation a plat et la hauteur de restitution du
robot pour le retraitement. Les autres permutations et egalites restent a part ;
les denominateurs par produit et les exclusions des bilans ne changent pas.

Les statistiques camera sont preparees une fois par session ; les contextes sont
lus par blocs indexes. La reouverture reutilise le rapport de la vue. Apres un
`git pull` touchant le rapport, reconstruire `report_app` avec `npm.cmd run build`
sous Windows, puis relancer le viewer et regenerer le rapport.

Le benchmark `TraceAlphaViewer/Tools/benchmark_report.py` mesure duree, taille
HTML/JSON et lectures de blocs, trois fois sur la meme session :

```powershell
python TraceAlphaViewer\Tools\benchmark_report.py --session build\benchmark-rapport --prepare chemin\trace.old --label avant
python TraceAlphaViewer\Tools\benchmark_report.py --session build\benchmark-rapport --refresh-camera --label apres
```

Les sessions et resultats restent locaux dans `build/` ; `--revision` permet une
comparaison Git. La preparation de la session est hors du temps de generation.

Comparatif local du 15 octobre 2026 face a `db8e292`, mediane de trois generations,
sur les memes sessions et sans autre traitement lourd :

| Trace | Avant | Apres | Gain | Blocs lus avant / apres | HTML avant / apres |
| --- | ---: | ---: | ---: | ---: | ---: |
| Monistrol | 49,4 s | 6,9 s | x7,2 | 3 367 / 612 | 31,0 / 8,3 Mo |
| TracAlpha1_017 | 12,5 s | 3,6 s | x3,5 | 891 / 398 | 6,9 / 7,4 Mo |

Les compteurs restent identiques. Les liens de preuves ajoutent des donnees au
rapport 017, moins repetitif ; le gain de temps provient surtout des lectures
ciblees. Ces mesures concernent la generation, pas le temps d'ouverture du
navigateur ni la lecture initiale de la trace.

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
