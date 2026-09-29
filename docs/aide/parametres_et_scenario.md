# Paramètres et scénario

Un **scénario** rassemble dans un seul fichier toutes les données et tous les réglages d'un calcul. Le même scénario donne toujours le même résultat. Il est copié à côté des résultats (`scenario_used.json`), pour garder la trace de ce qui a été calculé.

Un exemple complet se trouve dans `data/test/muramvya/scenario_muramvya.json`.

## Données d'entrée

| Entrée | Rôle | Obligatoire |
|---|---|---|
| `study_area` | Zone d'étude (limites administratives) | oui |
| `typology` | Couche des zones et champ qui porte leur classe (`Rural`, `Urbain1`, *haut standing*…). Les noms de classes sont libres | oui |
| `base_population` | Raster de densité de population à l'année de base | oui |
| `admin_units` | Unités administratives et champ de leur nom, pour les bilans et le recalage | non |
| `parameter_zones` | Zones de paramètres, si les taux ou densités varient selon des limites différentes de la typologie | non |
| `exclusions` | Zones d'exclusion (voir plus bas) | non |
| `projections` | Projections démographiques (voir plus bas) | non |

Les chemins sont relatifs au fichier de scénario.

## Temps

| Réglage | Rôle | Exemple |
|---|---|---|
| `base_year` | Année que représente la population de base (année du recensement) | 2024 |
| `end_year` | Horizon final | 2060 |
| `time_step` | Pas de temps, en années (10, 5, 1, 0,5…) | 5 |
| `output_years` | Années pour lesquelles les résultats sont écrits (par défaut, la fin de chaque pas) | 2030, 2040… |
| `migration_frequency` | `annual` : migration chaque année (plus précis) ; `time_step` : une migration par pas (plus rapide) | `annual` |
| `first_migration_year` | Première année où la migration s'applique (avant : croissance seule) | 2025 |
| `start_mode` | `census` : départ du recensement (prudent) ; `projection` : départ d'une année de projection | `census` |

## Paramètres : TCAM et densités maximales

Chaque paramètre peut prendre l'une de ces formes :

```json
"growth_rate": 2.2
"growth_rate": {"Rural": 2.0, "Urbain1": 3.5}
"growth_rate": {"*": {"2026": 3.0, "2040": 2.0}, "Urbain1": 4.0}
```

- `*` désigne la valeur par défaut, qui s'applique aux classes et aux zones non citées.
- Avec des années, les valeurs sont **interpolées en ligne droite** entre les années citées. Avant la première et après la dernière année, elles restent **constantes**, sauf si `"extrapolation": "linear"` est indiqué.
- Une valeur donnée pour une **zone de paramètres** l'emporte sur celle de la **classe**, qui l'emporte sur la valeur **par défaut**.
- `growth_rate` est en % par an. `dmax` est dans l'unité choisie par `density_unit` (`hab/km2` ou `hab/ha`).

## Zones d'exclusion

| Comportement | Effet |
|---|---|
| `outside` | Retiré du calcul : hors pays, lacs… |
| `no_inflow` | N'accueille plus personne ; ses habitants restent et sa croissance part ailleurs : forêts, domaines militaires… |
| `relocate` | Tous ses habitants sont relocalisés : barrage… |

Une exclusion peut porter une **année** (`"year": 2030`) : elle s'applique alors à partir de cette année, et les résultats de l'année 2030 en tiennent déjà compte. Les rivières données sous forme de lignes reçoivent une largeur de tampon (`"buffer_m": 50`).

## Projections démographiques (optionnel)

Il s'agit d'un fichier CSV à trois colonnes : `admin`, `year`, `population`.
- `"recalibrate": true` recale chaque année la population de chaque unité administrative sur la projection, avec interpolation entre les années du fichier.
- `"start_mode": "projection"` avec `"start_year"` fait partir le calcul d'une année de projection.

## Migration

| Réglage | Rôle | Défaut |
|---|---|---|
| `k` | Nombre de mailles voisines qui se partagent l'excès | 3 |
| `tolerance` | Excès minimal pour déclencher un déplacement (nombre entier d'habitants) | 1 |
| `policy` | Réponse en cas de manque de place : `stop`, `raise_dmax`, `sink`, `unallocated` (voir **Non-convergence**) | `stop` |
| `max_auto_increase` | Hausse des densités acceptée sans validation, en mode automatique (0,25 = +25 %) | 0 |
| `sink_width_cells` | Largeur de la couronne de mailles puits | 4 |

## Système de coordonnées

Les couches peuvent être dans n'importe quel système de coordonnées : l'outil les reprojette. Le **calcul** se fait toujours dans un système **projeté en mètres**, pour que les surfaces et les densités soient justes.

| Valeur de `crs` | Système de calcul |
|---|---|
| (absent) | Celui du raster de population s'il est en mètres, sinon la zone UTM de la zone d'étude |
| `EPSG:32735`, WKT… | Le système indiqué (refusé s'il est en degrés) |
| `auto-utm` | La zone UTM du centre de la zone d'étude |
| `auto-equal-area` | Un système à surfaces conservées centré sur la zone : recommandé pour un grand pays |

Si le système choisi déforme les surfaces de plus de 0,5 % sur la zone d'étude, le rapport le signale.

Le raster de population peut contenir une **densité** (`"value_type": "density"`, dans l'unité `density_unit`) ou un **nombre d'habitants par pixel** (`"value_type": "count"`, comme WorldPop).

## Autres réglages

| Réglage | Rôle | Défaut |
|---|---|---|
| `cell_size` | Taille de maille, en mètres | 250 |
| `crs` | Système de coordonnées de calcul (voir plus haut) | automatique |
| `language` | Langue du rapport et des tableaux (`fr`, `en`) | `fr` |
| `output.directory` | Dossier des résultats | `outputs` |

## Lancer un calcul sans QGIS

```bash
python -m engine run scenario.json
python -m engine run scenario.json --language en
```
