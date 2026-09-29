# Bilan de la phase 1 : socle du moteur

| | |
|---|---|
| **Date** | 29/09/2026 |
| **Périmètre** | Grille, unités de calcul, population de base, paramètres, plafonds, croissance, arrondi, lecture des bâtiments |
| **Statut** | Terminée : 55 tests rapides et 2 tests de performance passent |

## 1. Ce qui a été développé (`src/engine/`)

| Module | Rôle | Spécification |
|---|---|---|
| `grid.py` | Grille régulière alignée sur l'origine du raster, `cell_size` paramétrable | §3 |
| `units.py` | Découpage des mailles en unités de calcul (typologie, zone d'étude, zones sans migration). Seules les mailles traversées par une limite sont découpées, tuile par tuile | §3, S1-S3 |
| `base_population.py` | Population de chaque unité, à partir de la surface commune entre pixels et unités ; gestion des pixels en bordure et des pixels nodata | §3 |
| `parameters.py` | Paramètres par classe et par année charnière ; interpolation linéaire, extrapolation constante ou linéaire, taux moyen exact sur un pas ; unités hab/km² et hab/ha ; lecture d'un CSV au format long | §2.3, S4, A8 |
| `capacity.py` | Plafond `C = a × max(d0, dmax)`, ou `C = P0` pour une zone sans migration | §4, A4, A7-bis |
| `growth.py` | Croissance au taux moyen sur un pas de durée quelconque | §5.1 |
| `rounding.py` | Arrondi des populations publiées par la méthode des plus grands restes, total conservé | §8.2 |
| `buildings.py` | Lecture des bâtiments depuis toute source OGR (polygones ou points), et depuis les fichiers Google Open Buildings ; rattachement aux unités | §3 bis |
| `raster_io.py`, `vector_io.py` | Lecture et écriture GDAL/OGR | — |

**Dépendances** : numpy, scipy et GDAL uniquement. Le moteur n'importe pas `qgis`. Les exceptions GDAL sont activées localement, sans modifier l'état global partagé avec QGIS et les autres extensions.

## 2. Tests

| Fichier | Contenu |
|---|---|
| `test_parameters.py` | T2 (interpolation, extrapolation), taux moyen, tables par classe, lecture CSV, unités |
| `test_growth_capacity_rounding.py` | T1, T3 (dont la sensibilité au pas), T7, T8, T10, T13 (plafond) |
| `test_grid_units.py` | Alignement de la grille, T13 (découpage), zone sans migration, lacunes et chevauchements de la typologie, rattachement des éclats |
| `test_base_population.py` | T11 (agrégation), T13 (population d'une maille découpée), grille et raster non alignés, pixels en bordure, unité hab/ha, nodata, contrôle du système de coordonnées |
| `test_buildings.py` | Polygones et points, filtre spatial, reprojection depuis les degrés, format Open Buildings (CSV.gz, seuil de confiance), rattachement aux mailles entières et découpées |
| `test_muramvya.py` | Intégration sur Muramvya et comparaison avec `reference_outputs/muramvya/p2023_entree` |
| `test_performance.py` | Un million de bâtiments (`pytest -m slow`) |

## 3. Résultats sur Muramvya

| Contrôle | Résultat |
|---|---|
| Unités de calcul | 6 297 unités, dont 1 899 en forêt, sur 256,53 km². 2 213 mailles entières et 2 165 mailles découpées. Aucune zone sans classe. Découpage en environ 3 s |
| Population de base, mode `renormalized` | **171 280 habitants** : exactement le total du raster |
| Population de base, mode `area_weighted` | 170 565 habitants : les 715 habitants des parties de pixels situées hors de la commune ne sont pas comptés |
| Population de la forêt | **9 746 habitants conservés**, alors que le modèle actuel les supprime (A7). L'estimation par centres de pixels de l'état des lieux (7 144) la sous-estimait |
| Comparaison maille par maille avec `p2023_entree`, hors forêt | Écart inférieur à 0,5 habitant sur toutes les mailles sauf **6**. Ces 6 pixels (556 habitants au total) ont une valeur dans la référence mais sont vides (nodata) dans le raster fourni : **la référence a été produite avec une version légèrement différente du raster** |
| Plafonds (`Pmax`) | Identiques à la référence (à 0,1 % près) sur 4 380 fragments sur 4 381. Le seul écart tombe sur un de ces 6 pixels |
| Bâtiments | Les 38 942 bâtiments sont lus et rattachés à une unité en 0,6 s |

## 4. Performance

| Mesure | Résultat | Objectif |
|---|---|---|
| 1 million de polygones (GeoPackage) : lecture, centroïde, surface, rattachement | **18,8 s** | < 120 s |
| 1 million de lignes Google Open Buildings (CSV.gz) : lecture, projection, rattachement | **3,4 s** | < 120 s |
| Découpage : 50 × 50 km, maille de 250 m (40 000 mailles) | 0,2 s | — |
| Découpage : 150 × 150 km, maille de 100 m (2,25 millions de mailles) | 3,1 s | — |

Le temps de découpage dépend surtout du nombre de mailles traversées par une limite et de la complexité des limites : environ 1,4 ms par maille découpée sur Muramvya.

## 5. Point à trancher

**Pixels en bordure du domaine (`boundary_mode`).** Un pixel du raster de population peut être à cheval sur la limite de la zone d'étude (commune, frontière, lac).

| Mode | Effet | Adapté quand… |
|---|---|---|
| `area_weighted` | Seule la part du pixel située dans le domaine est comptée (715 habitants de moins à Muramvya) | Le raster couvre aussi les territoires voisins, par exemple un raster national découpé sur une commune |
| `renormalized` | Toute la population du pixel est affectée aux unités du domaine | Le raster a été construit uniquement à partir des bâtiments du domaine, comme le raster BUR71 actuel. C'est aussi le bon choix pour un pixel à moitié dans un lac : ses habitants vivent sur la rive |

**Proposition** : `renormalized` par défaut quand le raster a été calculé à partir des bâtiments du domaine, `area_weighted` sinon. Le choix est rappelé dans le rapport. **À valider.**

Quand la population de base sera calculée directement à partir des bâtiments (phase 6), la question disparaît : chaque bâtiment est rattaché par son centroïde.

## 6. Environnement de développement

- Les tests tournent avec Python 3.12, GDAL 3.8, numpy 1.26 et scipy 1.11, proches des versions fournies avec QGIS 3.40.
- Un script de démarrage (`.claude/hooks/session-start.sh`) installe ces outils dans les sessions Claude Code sur le web.
- `tools/extract_legacy_buildings.py` a produit `data/test/muramvya/buildings_muramvya.gpkg` à partir des classeurs de calage. Il utilise openpyxl, un outil de développement uniquement.

## 7. Prochaine étape : phase 2, migration et non-convergence

Contenu (spécification §6 et §7) :
- migration vectorisée vers les k plus proches unités receveuses ;
- mode conservatif par défaut et mode `legacy` pour la comparaison ;
- contrôle préalable de capacité et les quatre politiques de non-convergence ;
- rapport d'exécution ;
- cas de test T4, T5, T6, T7, T9, T12 et T14.

Le plan détaillé de la phase 2 sera soumis pour validation avant d'écrire le code.
