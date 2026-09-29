# Plan de la phase 3 : déroulé temporel, paramètres spatio-temporels et sorties

| | |
|---|---|
| **Statut** | Proposition, à valider avant d'écrire le code |
| **Référence** | `docs/spec_moteur.md`, §2, §5 et §8 |
| **Durée estimée** | 1,5 à 2 jours |

## 1. Objectif

Faire tourner une simulation complète, de l'année de départ à l'horizon final, **à partir d'un seul fichier de scénario**, sans aucune étape manuelle. Elle produit les rasters par année, les tableaux et le rapport.

## 2. Modules

| Module | Contenu |
|---|---|
| `scenario.py` | **Fichier de scénario (JSON)** : données d'entrée (chemins, couches, champs), années, pas de temps, taille de maille, unité de densité, paramètres, exclusions, politique de non-convergence, sorties. Lecture, écriture et **contrôle complet**, avec une liste d'erreurs claires en français (« le champ `Type` est absent de la couche des zones », « la densité max de la classe `Urbain2` est manquante »…) |
| `units.py` (extension) | Découpage selon **plusieurs couches** à la fois : typologie, zones de paramètres, exclusions datées, unités administratives pour les bilans. Chaque unité porte l'identifiant de chacune de ces couches |
| `parameters.py` (extension) | Paramètres **par zone** (en plus de par classe) et par année charnière ; lecture depuis une couche (GeoPackage ou shapefile) ou une table CSV |
| `timeline.py` | Calendrier des pas :<br>• de l'année de base à l'horizon final, avec un pas libre ;<br>• années de sortie atteintes exactement ;<br>• sous-pas annuels si `migration_frequency = annual` ;<br>• première année de migration (`first_migration_year`) ;<br>• dates d'effet des exclusions |
| `simulation.py` | Boucle principale. À chaque pas :<br>• croissance au taux moyen ;<br>• recalage optionnel sur les projections ;<br>• application des exclusions datées : `relocate` (évacuation) ou `no_inflow` (arrêt de la croissance) ;<br>• migration avec la politique choisie ;<br>• bilans et écriture des sorties.<br>Départ au recensement ou à une année de projection (`start_mode`) |
| `outputs.py` | Pour chaque année de sortie :<br>• rasters de population (entiers, total conservé) ;<br>• rasters de densité (float32, dans l'unité choisie) ;<br>• rasters de population non relocalisée et de capacité ;<br>• tableau CSV par unité administrative.<br>En option, une couche GeoPackage des unités |
| `indicators.py` | **Demande en eau potable** (§8.4) : consommation domestique, besoins non domestiques, production moyenne (avec le rendement du réseau), jour de pointe, heure de pointe. Rasters et tableaux, avec des paramètres éventuellement variables par zone et dans le temps |
| `report.py` (extension) | **Rapport consolidé** du run (JSON et texte) :<br>• paramètres et versions ;<br>• avertissement si la résolution est grossière (S6) ;<br>• bilans par pas ;<br>• ajustements appliqués ;<br>• personnes évacuées ;<br>• statut global |
| `__main__.py` | Lancement en ligne de commande : `python -m engine run scenario.json` |

## 3. Tests

| Type | Contenu |
|---|---|
| Cas calculés à la main | T14 (première année de migration) ; zone exclue à partir d'une date, dans les modes `relocate` et `no_inflow` ; I5 (même croissance quel que soit le pas) ; migration annuelle ou par pas ; départ sur une année de projection ; recalage |
| Scénario | Lecture et écriture sans perte ; chaque erreur de saisie produit un message explicite |
| Sorties | Rasters relisibles, bien géoréférencés, total des entiers égal au total arrondi (I6), aucune valeur négative ni manquante (I7) ; formules de la demande en eau |
| Muramvya de bout en bout | De 2024 à 2060, avec les taux par période de l'ancien résultat final (2,2 % puis 2,23 %, 2,14 %… jusqu'à 1,29 %), sorties tous les 5 ans. On vérifie la conservation à chaque pas et l'absence de dépassement. Comparaison qualitative avec `pentree_final` : totaux, répartition entre urbain et rural, nombre de mailles nouvellement peuplées. Les écarts dus aux anomalies connues (forêt supprimée, plafond effectif d'environ 0,91 × Pmax) sont expliqués |
| Performance (`-m slow`) | Une simulation de 36 ans sur une grande grille synthétique, pour mesurer la durée totale |

## 4. Documentation livrée avec la phase

- `docs/bilan_phase3.md`.
- Pages d'aide : « Paramètres et scénario », « Résultats, rapport et indicateurs », et un exemple de scénario commenté pour Muramvya (`data/test/muramvya/scenario_muramvya.json`).

## 5. Choix proposés (à valider)

| # | Question | Proposition |
|---|---|---|
| P1 | Les zones de paramètres (TCAM, densités max) peuvent-elles avoir des limites différentes de la typologie ? | **Oui.** Les mailles sont découpées selon chaque couche fournie (typologie, zones de paramètres, exclusions, unités administratives). Plus il y a de couches, plus il y a de morceaux, mais le calcul reste rapide (phase 1) |
| P2 | Les populations entières publiées sont-elles arrondies par maille ou par morceau de maille ? | **Par maille** : un raster donne une valeur par maille. Le total reste conservé. Les tableaux par unité administrative additionnent les populations non arrondies, puis arrondissent le total de chaque unité |
| P3 | Quels formats de sortie ? | Rasters **GeoTIFF**, un par année et par grandeur ; tableaux **CSV** ; rapport **JSON et texte** ; en option, un **GeoPackage** des morceaux de mailles avec leurs populations |
| P4 | La demande en eau potable fait-elle partie de la phase 3 ? | **Oui** : ce n'est qu'un calcul à partir des populations, et c'est l'usage prioritaire. Les autres indicateurs utiliseront le même mécanisme |
| P5 | Nom des fichiers de sortie | `population_2030.tif`, `densite_2030.tif`, `non_relocalises_2030.tif`, `eau_production_moyenne_2030.tif`, `bilan_par_unite.csv`, `rapport.json`, `rapport.txt` |
