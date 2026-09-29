# Bilan de la phase 3 : simulation complète

| | |
|---|---|
| **Date** | 29/09/2026 |
| **Périmètre** | Fichier de scénario, calendrier, paramètres par zone et dans le temps, exclusions datées, départ sur recensement ou projection, recalage, sorties, indicateurs (eau potable), langues, ligne de commande |
| **Statut** | Terminée : 121 tests rapides et 4 tests de performance passent |

## 1. Ce qui a été développé (`src/engine/`)

| Module | Rôle |
|---|---|
| `scenario.py` | Fichier de scénario JSON : lecture, écriture sans perte, contrôles. **Tous les problèmes sont signalés en une fois**, par des messages traduits qui nomment l'entrée concernée (par exemple `migration.tolerance`) |
| `timeline.py` | Calendrier : pas libre (y compris inférieur à un an) ; années de sortie et dates d'exclusion toujours atteintes exactement ; sous-pas annuels ou migration par pas ; première année de migration |
| `units.py` | Découpage des mailles selon **plusieurs couches** : typologie, zones de paramètres, exclusions datées, unités administratives. En cas de chevauchement dans une couche, le premier polygone l'emporte, et le chevauchement est reporté |
| `parameters.py` | Paramètres par **zone**, par **classe** ou par **défaut**, dans cet ordre de priorité ; combinaisons calculées une seule fois par run |
| `simulation.py` | Boucle complète. À chaque sous-pas : exclusions qui prennent effet, croissance au taux moyen, recalage optionnel, migration avec la politique choisie. Écriture des résultats aux années de sortie ; rapport consolidé ; progression et annulation (pour le plugin) |
| `outputs.py` | Rasters par année (noms fixes en anglais) et tableau `summary.csv` (en-têtes dans la langue choisie) |
| `indicators.py` | **Cadre générique** d'indicateurs et **demande en eau potable** : consommation domestique, besoins non domestiques (part et volumes fixes), production moyenne avec le rendement, jour et heure de pointe |
| `i18n.py`, `locales/` | Messages par codes, catalogues **français et anglais**, séparateurs des nombres selon la langue |
| `__main__.py` | `python -m engine run scenario.json [--language en]` |

## 2. Muramvya, de 2024 à 2060 (scénario d'exemple)

Le scénario `data/test/muramvya/scenario_muramvya.json` reprend les taux par période de l'ancien résultat final. Il utilise des sorties tous les 5 ans et une migration annuelle.

| Contrôle | Résultat |
|---|---|
| Statut, durée | Réussi, en **7 s**. 6 297 unités, 4 378 mailles de 250 m |
| Population | 170 565 en 2024 → **320 361** en 2060. Écart de bilan nul à chaque pas |
| Croissance totale 2024 → 2060 | **× 1,8782**, contre × 1,8788 dans l'ancien résultat final (écart de 0,03 %) |
| Répartition spatiale comparée à l'ancien résultat final | Corrélation maille par maille de 0,99 en 2024, 0,98 en 2040 et **0,97 en 2060** |
| Écarts de niveau avec l'ancien résultat | Expliqués : la forêt est conservée (9 746 habitants), le raster fourni diffère légèrement (6 pixels), et l'ancien outil appliquait un plafond effectif d'environ 0,91 × Pmax (RF3) |
| Mailles peuplées en 2060 | 3 679, contre 3 474 dans l'ancien résultat. Cette différence reflète notamment la croissance de la forêt, exportée vers les mailles voisines |
| Eau potable 2060 | Rasters et tableau produits ; les formules sont vérifiées par les tests |

## 3. Performance

| Mesure | Résultat |
|---|---|
| Simulation de 36 ans sur **1 million de mailles** (100 m sur 100 × 100 km), migration annuelle, 2,6 millions d'habitants déplacés au total | **29 s**, contre 146 s avant l'optimisation (les combinaisons zone × classe sont désormais calculées une seule fois) |
| Muramvya, de 2024 à 2060 | 7 s |

## 4. Conventions retenues (validées le 29/09/2026)

| # | Convention | Raison |
|---|---|---|
| C1 | Une exclusion datée de l'année Y s'applique au pas **qui se termine en Y** : les résultats de l'année Y en tiennent déjà compte. Pour une zone fermée à l'accueil, le plafond devient la population du début de ce pas | Une zone « inhabitable à partir de 2027 » n'a plus d'habitants dans les résultats de 2027 |
| C2 | Une **relocalisation** a lieu même si l'année est antérieure à `first_migration_year` | Les habitants d'une zone inhabitable doivent être placés |
| C3 | Une hausse des densités max acceptée (`raise_dmax`) **reste appliquée** pour les pas suivants | Sinon, le même manque de place réapparaîtrait au pas suivant |
| C4 | La population de la **couronne de mailles puits** croît au taux moyen de la zone d'étude | Ce sont des habitants de la zone, installés en périphérie |
| C5 | La densité max d'un pas est celle de **la fin du pas** | C'est la contrainte à respecter à la date des résultats |
| C6 | En départ `projection`, la population remise à l'échelle sert de base pour les plafonds (A4 et c1) | C'est la nouvelle situation de départ |
| C7 | Tableau CSV en français : séparateur « ; » et virgule décimale ; en anglais : « , » et point | Pour que le fichier s'ouvre directement dans un tableur |

## 5. Documentation

Pages d'aide ajoutées dans `docs/aide/` :
- `parametres_et_scenario.md` : toutes les entrées du scénario, avec des exemples ;
- `resultats_et_indicateurs.md` : fichiers produits, lecture du rapport, formules de l'eau potable.

## 6. Suite

**Phase 4 (performance et grandes emprises)** : l'essentiel est déjà atteint. Un million de mailles sur 36 ans prend 29 s, un million de bâtiments est lu en 3 à 19 s, et la migration de 2,25 millions d'unités prend 6 s. Il reste à mesurer la mémoire et le découpage des mailles sur une emprise nationale réelle, avec des limites administratives complexes. Cette mesure demande les couches nationales du Burundi ou un autre pays. Je propose de ne pas en faire une phase à part, mais de la mener dès que ces données seront disponibles.

**Prochaine étape proposée : phase 5, le plugin QGIS.** Elle comprend l'interface (barre d'outils, fenêtres, bulles d'aide, menu Aide), l'algorithme Processing, le calcul en tâche de fond et le dialogue de non-convergence. Elle commencera par une **maquette des fenêtres à valider**. Il faudra aussi pouvoir tester dans QGIS 3.40 et 4 : je peux essayer d'installer QGIS dans l'environnement de développement, et une vérification sur votre poste sera de toute façon nécessaire.
