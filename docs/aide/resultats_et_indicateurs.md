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
| `calibration.json` | Détail du calage, si la population de départ vient des toits |
| `report.html` | **Rapport complet autonome** : chiffres clés, évolution de la population, avertissements, calage avec ses graphiques. Il s'ouvre dans un navigateur et s'imprime en PDF ; bouton « Ouvrir le rapport complet » de l'onglet Rapport, ou `python -m engine report <dossier>` |

Les résultats de l'année de départ sont toujours écrits.

## Un dossier par exécution

Depuis le plugin, chaque calcul est écrit dans son propre **sous-dossier daté** du dossier des résultats, par exemple `2026-09-29_144805`. Un nouveau calcul n'écrase donc jamais des fichiers encore ouverts dans QGIS.

Ces dossiers sont **temporaires** tant que vous ne les conservez pas :
- dans l'onglet **Résultats**, choisissez l'exécution affichée, puis cochez **À conserver ★** et donnez-lui un nom si besoin (« référence », « dmax + 20 % ») ;
- le bouton **Nettoyer…** ouvre la liste des exécutions avec leur statut, leurs années et leur taille. Tout ce qui n'est pas conservé est coché dans la colonne « Supprimer » ; un clic efface la sélection. Les couches concernées sont d'abord retirées du projet ;
- si aucune exécution n'est conservée, la **dernière exécution réussie** est laissée décochée ;
- en **fin de session**, à la fermeture de la fenêtre Poplar ou de QGIS, la même liste est proposée si vous avez lancé des calculs.

Seuls les dossiers créés par Poplar, qui contiennent un fichier `poplar_run.json`, peuvent être supprimés : les données d'entrée ne sont jamais touchées.

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

Chaque paramètre a **son propre onglet**, lié à la couche dont il dépend, comme le TCAM : la dotation par type d'habitat, le rendement par zone de service (un autre fichier de polygones), un volume fixe par site… Choisissez la couche et le champ dans les listes : les lignes du tableau se remplissent avec les valeurs du champ, **sans rien taper**, ce qui évite les erreurs de nom. Deux couches peuvent être croisées, et chaque valeur peut changer avec les années.

- Une valeur saisie pour une zone absente de la couche est signalée par un avertissement.
- Une zone sans valeur prend la ligne « Hors zones (défaut) ». Si cette ligne est vide pour la dotation, le calcul s'arrête en nommant le paramètre incomplet.
- Un onglet vide garde la valeur par défaut du tableau ci-dessus.
- Les anciens scénarios, où les valeurs étaient données par classe de typologie, sont convertis à l'ouverture : les onglets sont liés à la couche de typologie.

| Résultat | Calcul |
|---|---|
| `water_domestic` | population × dotation / 1 000 (m³/j) |
| `water_consumption_mean` | consommation domestique + besoins non domestiques (m³/j) |
| `water_production_mean` | consommation moyenne / rendement (m³/j) |
| `water_production_peak_day` | production moyenne × coefficient de pointe journalière (m³/j) |
| `water_peak_hour` | consommation moyenne × pointe journalière × pointe horaire / 24 (m³/h) : le rendement ne s'applique pas à la pointe horaire |

## Autres usages

La demande en eau est le premier « indicateur ». D'autres (déchets, énergie, places scolaires…) peuvent être ajoutés de la même façon : chacun calcule des grandeurs à partir de la population, avec ses propres paramètres.
