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
| `parameter_zones` | Ancien format : zones de paramètres communes au TCAM et aux densités. Remplacé par les zones propres à chaque paramètre (voir plus bas) | non |
| `exclusions` | Zones d'exclusion (voir plus bas) | non |
| `projections` | Projections démographiques (voir plus bas) | non |

Les chemins sont relatifs au fichier de scénario.

### Routes OpenStreetMap

Le bouton **Télécharger les routes OpenStreetMap…** (onglet Données) récupère toutes les voies de la zone d'étude (champ OSM `highway` : routes, pistes, chemins) par l'API **Overpass**, en tâche de fond.

- Zone : la zone d'étude par défaut, élargie d'une marge (2 km par défaut), et gardée dans une limite facultative (une frontière).
- Les lignes sont coupées à la zone et écrites dans le système de calcul, dans `routes/routes_osm_<zone>.gpkg` à côté du scénario, avec les champs `highway`, `classe`, `nom`, `ref`, `surface`, `osm_id` et `longueur_m`.
- Classes : **nationale** (motorway, trunk, primary), **provinciale** (secondary, tertiary), **autre** (tout le reste). Les voies en projet ou en construction sont écartées.
- La couche est ajoutée au projet, colorée par classe. Le fichier `.download.json` voisin garde la date, le serveur, la requête et les longueurs par classe.
- Si un serveur Overpass est saturé, le suivant est essayé. Si aucun ne répond, réessayez plus tard ou vérifiez le proxy (**Préférences › Options › Réseau**).
- Licence ODbL : citez « © OpenStreetMap contributors ».
- Le modèle ne se sert **pas encore** des routes : l'attraction des routes est à l'étude (plan B).

En ligne de commande : `python -m engine download-roads <zone.gpkg> <sortie.gpkg> --crs EPSG:32735 [--margin 2000]`.

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

Le TCAM (`growth_rate`, en % par an) et les densités maximales (`dmax`, dans l'unité `density_unit`) ont **chacun leur tableau**, lié à **sa propre couche** de polygones et à un champ. Les deux couches peuvent être différentes : par exemple le TCAM par province et les densités par type urbain/rural.

Dans l'onglet **Paramètres** :
1. choisissez la couche et le champ des **zones** : le tableau affiche une ligne par valeur du champ ;
2. remplissez une **constante**, ou des valeurs aux **années charnières** (bouton « + Année charnière ») ;
3. la ligne **Hors zones (défaut)** s'applique aux mailles hors des zones et aux zones laissées vides ;
4. sans couche, la valeur par défaut s'applique partout.

Une valeur saisie pour une zone qui n'existe pas dans la couche est signalée en ocre et dans le rapport : elle n'est pas utilisée.

**Croiser deux couches** : cochez « Croiser avec une seconde couche » pour donner une valeur par combinaison, par exemple province × type. Pour chaque maille, l'outil cherche dans l'ordre la paire exacte (`A|Urbain1`), puis la zone de la première couche seule (`A|*`), puis celle de la seconde (`*|Urbain1`), puis la valeur par défaut. Les valeurs déjà saisies sont gardées quand on coche ou décoche la case : « A » devient « A | (toutes) », puis redevient « A ».

**Tableur** : « Exporter… » enregistre le tableau en xlsx, ods ou csv ; « Importer… » le relit. Colonnes : `zone` (et `zone_2` en cas de croisement), `constant`, puis une colonne par année.

Dans le fichier de scénario :

```json
"growth_rate": {"zones": [{"source": "provinces.shp", "field": "PROVINCE"}],
                "values": {"Muramvya": {"2025": 2.2, "2040": 1.9}, "*": 2.0}},
"dmax": {"zones": [{"source": "typologie.shp", "field": "Type"}],
         "values": {"Rural": 2500, "Urbain1": 10000, "*": 2500}}
```

- Avec des années, les valeurs sont **interpolées en ligne droite** entre les années citées. Avant la première et après la dernière année, elles restent **constantes**, sauf si `"extrapolation": "linear"` est indiqué.
- L'ancien format reste accepté : `"growth_rate": 2.2`, ou des valeurs par classe de typologie (`{"Rural": 2.0, "*": 2.5}`), avec priorité à `parameter_zones` sur la classe. Le plugin le convertit à l'ouverture.

## Zones d'exclusion

| Comportement | Effet |
|---|---|
| `outside` | Retiré du calcul : hors pays, lacs… |
| `no_inflow` | N'accueille plus personne ; ses habitants restent et sa croissance part ailleurs : forêts, domaines militaires… |
| `relocate` | Tous ses habitants sont relocalisés : barrage… |

Une exclusion peut porter une **année** (`"year": 2030`) : elle s'applique alors à partir de cette année, et les résultats de l'année 2030 en tiennent déjà compte. Les couches de **lignes** (routes, rivières) et de **points** (forages, sources) reçoivent obligatoirement une largeur de tampon en mètres (`"buffer_m": 50`, colonne « Tampon (m) » de l'onglet Données). Pour une couche de polygones, le tampon est facultatif et élargit la zone, par exemple un lac et ses 100 m de berge. Le tampon est appliqué dans le système de calcul, donc toujours en mètres, même si la couche est en degrés.

## Changement d'affectation planifié : ce qui est possible aujourd'hui

Exemple : un camp de déplacés qui ferme en 2030 et devient un village. La gestion complète des changements de catégorie est prévue après le beta ; en attendant, deux outils existent.

1. **Paramètres de la zone qui changent avec les années.** Dessinez le camp dans une couche de zones, liez-y le TCAM et la densité maximale, puis donnez des valeurs de camp jusqu'en 2029 et des valeurs de village à partir de 2030. Entre deux années charnières, les valeurs sont interpolées en ligne droite : pour un changement net, mettez deux années proches (2029 puis 2030).
   - **Limite** : la nouvelle densité maximale ne s'applique qu'à la croissance et aux arrivées. Les habitants déjà présents au-delà de cette densité **restent sur place** ; ils ne partent pas progressivement vers d'autres mailles.
2. **Zone d'exclusion datée « relocalisée »** (`relocate`, avec une année). Tous les habitants de la zone sont relocalisés **d'un coup**, à la date donnée, et la zone n'accueille plus personne ensuite.

Aucun des deux ne reproduit encore une fermeture progressive, où le surplus migre au fil des années. C'est prévu dans le chantier des catégories qui changent dans le temps (voir `docs/reste_a_faire.md`).

## Projections démographiques (optionnel)

Le fichier peut être un **CSV**, un classeur **Excel** (xlsx, xls) ou **OpenDocument** (ods), sous l'une de ces deux formes :
- **une ligne par unité et par année** : colonnes unité, année, population ;
- **une ligne par unité et une colonne par année**, comme dans les publications des instituts de statistique.

La forme et les colonnes sont reconnues d'après les en-têtes (`admin`, `commune`, `unité`… ; `year`, `année` ; `population`, `valeur`…). Sinon, choisissez-les dans l'onglet Données : un aperçu indique ce qui sera lu. Les noms ou codes des unités doivent être ceux du champ des unités administratives.

```json
"projections": {"file": "projections_isteebu.xlsx", "sheet": "Communes", "unit_column": "Commune", "recalibrate": true}
```

- `"recalibrate": true` recale chaque année la population de chaque unité administrative sur la projection, avec interpolation entre les années du fichier. La migration qui suit peut ensuite déplacer quelques habitants d'une unité à l'autre.
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
| `output.per_run` | Un sous-dossier daté par exécution (toujours activé depuis le plugin) | `false` |
| `description` | Une phrase pour retrouver le scénario dans la bibliothèque | |

## Bibliothèque de scénarios

Le bouton **Bibliothèque…** ouvre la liste des scénarios enregistrés dans un dossier, avec leur nom et leur description.
- **Partir de ce scénario** charge une copie : l'original n'est jamais modifié, « Enregistrer… » demande un nouveau fichier.
- **Ajouter le scénario actuel…** y enregistre une copie, avec un nom et une description.
- **Changer de dossier…** : un dossier partagé sur le réseau permet à toute l'équipe de partir des mêmes scénarios de référence.

## Lancer un calcul sans QGIS

```bash
python -m engine run scenario.json
python -m engine run scenario.json --language en
```
