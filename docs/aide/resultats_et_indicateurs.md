# Résultats, rapport et indicateurs

## Fichiers produits

Les noms de fichiers sont **fixes et en anglais**, quelle que soit la langue. `AAAA` désigne l'année.

| Fichier | Contenu |
|---|---|
| `population_AAAA.tif` | Population par maille, en **nombres entiers**. Le total est conservé |
| `density_AAAA.tif` | Densité par maille, dans l'unité choisie, calculée sur la surface utile de la maille |
| `unallocated_AAAA.tif` | Population non relocalisée cumulée, si la politique `unallocated` est utilisée |
| `capacity_AAAA.tif` | Population maximale de chaque maille |
| `water_…_AAAA.tif` | Indicateurs de demande en eau (voir plus bas) |
| `summary.csv` | Tableau par unité administrative et par année : population, surface, densité, non relocalisés, indicateurs. Les en-têtes sont dans la langue choisie ; en français, le séparateur est « ; » et la virgule sert de séparateur décimal |
| `report.txt` / `report.json` | Rapport d'exécution, pour une personne ou pour un programme |
| `scenario_used.json` | Copie du scénario utilisé |

Les résultats de l'année de départ sont toujours écrits.

## Le rapport d'exécution

Le rapport indique :
- le **statut** : réussi, réussi avec ajustements, partiel (population non relocalisée) ou échec ;
- la population au départ et à l'horizon final ;
- le nombre de mailles et la durée du calcul ;
- les **avertissements**, par exemple une résolution grossière ou des zones sans classe ;
- les **événements**, par exemple une zone relocalisée ou fermée à une date ;
- pour **chaque pas** : la population avant et après la croissance, après la migration, le nombre d'habitants déplacés et un **écart de bilan**, qui doit être nul.

## Demande en eau potable

| Paramètre | Unité | Défaut |
|---|---|---|
| `water_per_capita` (dotation) | l/hab/j | obligatoire |
| `non_domestic_share` (besoins non domestiques) | % de la consommation domestique | 0 |
| `non_domestic_volume` (volume fixe par zone, réparti selon la population) | m³/j | 0 |
| `network_efficiency` (rendement du réseau) | % | 100 |
| `peak_day_factor` (coefficient de pointe journalière) | — | 1 |
| `peak_hour_factor` (coefficient de pointe horaire) | — | 1 |

Ces paramètres peuvent varier par classe, par zone et dans le temps, comme le TCAM.

| Résultat | Calcul |
|---|---|
| `water_domestic` | population × dotation / 1 000 (m³/j) |
| `water_consumption_mean` | consommation domestique + besoins non domestiques (m³/j) |
| `water_production_mean` | consommation moyenne / rendement (m³/j) |
| `water_production_peak_day` | production moyenne × coefficient de pointe journalière (m³/j) |
| `water_peak_hour` | consommation moyenne × pointe journalière × pointe horaire / 24 (m³/h) : le rendement ne s'applique pas à la pointe horaire |

## Autres usages

La demande en eau est le premier « indicateur ». D'autres (déchets, énergie, places scolaires…) peuvent être ajoutés de la même façon : chacun calcule des grandeurs à partir de la population, avec ses propres paramètres.
