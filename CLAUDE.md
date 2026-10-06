# Projet : outil SIG de croissance et migration de population (BUR71)

## Contexte
Refonte d'un outil interne SHER (PyQGIS + R) en **plugin QGIS en Python**.
Le document de référence est `docs/BUR71_fiche_diagnostic_outil_SIG_population.md` : lis-le avant toute tâche.

## Organisation du dépôt
- `docs/` : fiche diagnostic, notes, spécifications
- `legacy/` : code existant fourni par Lionel. **Ne jamais le modifier** : c'est la référence
- `data/test/` : jeu de données de test
- `reference_outputs/` : résultats de l'outil actuel sur le jeu de test (référence de non-régression)
- `src/` : nouveau code (moteur Python indépendant de QGIS, puis plugin)
- `tests/` : tests pytest

## Règles
- Langue : échanges et documentation en français, code et identifiants en anglais.
- Le moteur (`src/engine/`) ne doit **pas** importer `qgis`. Seul le plugin le fait.
- Dépendances limitées à ce qui est fourni avec QGIS : numpy, scipy, GDAL/osgeo. Aucune nouvelle dépendance sans validation.
- Cible : QGIS 3.40 LTR et QGIS 4 (Qt6). Importer Qt via `qgis.PyQt`.
- **Strates / polygones** (fiche §3.5, détail dans `docs/plan_polygones_libres.md`) : option `planned` (polygones figés, résultats identiques à l'existant) ou `free` (colonisation : la maille colonisée prend l'identifiant et toutes les propriétés du polygone colonisateur). En mode `free` : maille de 250 m, pas interne annuel, une couronne au plus par pas ; la vitesse du front est un résultat, jamais un paramètre. La couche communale reste fixe. La grille est la référence du calcul ; les polygones lissés ne servent qu'aux sorties. La population n'est jamais perdue en silence.
- On parle d'**indicateurs de plausibilité**, pas de validation scientifique : pas d'historique d'urbanisation disponible dans les zones d'étude.
- Rasters en float32, traitement par blocs pour les grandes emprises.
- Chaque étape doit passer les tests avant de passer à la suivante. Comparer systématiquement à `reference_outputs/`.
- Avant d'écrire du code sur une étape importante, proposer un plan et attendre ma validation.
- Signaler toute ambiguïté sur la logique métier (surtout la migration) au lieu de trancher seul.
