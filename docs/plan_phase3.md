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

## 5. Choix validés (29/09/2026)

| # | Question | Décision |
|---|---|---|
| P1 | Les zones de paramètres peuvent-elles avoir des limites différentes de la typologie ? | **Oui.** Les mailles sont découpées selon chaque couche fournie |
| P2 | Les populations publiées sont-elles arrondies par maille ou par morceau ? | **Par maille**, avec un total conservé |
| P3 | Quels formats de sortie ? | GeoTIFF, CSV, rapport JSON et texte, GeoPackage des morceaux en option |
| P4 | Quels indicateurs dans cette phase ? | **L'eau potable**, dans un **cadre générique** : un indicateur est un module qui calcule des grandeurs à partir des populations et de ses propres paramètres (par zone et dans le temps). D'autres usages pourront être ajoutés sans toucher au reste du moteur |
| P5 | Noms des fichiers de sortie | **Noms fixes, en anglais, quelle que soit la langue** : `population_2030.tif`, `density_2030.tif`, `unallocated_2030.tif`, `capacity_2030.tif`, `water_production_mean_2030.tif`, `summary.csv`, `report.json`, `report.txt`. Le contenu du rapport texte et les en-têtes des tableaux suivent la langue choisie |

**Langues (spécification §15)** : dans cette phase, le moteur produit ses messages à partir de codes et d'un catalogue par langue. Le français et l'anglais sont livrés.
