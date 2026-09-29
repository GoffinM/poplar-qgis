# Bilan de la phase 2 : migration et non-convergence

| | |
|---|---|
| **Date** | 29/09/2026 |
| **Périmètre** | Migration, contrôle de capacité, quatre politiques de non-convergence, couronne de mailles puits, évacuation, rapport d'un pas |
| **Statut** | Terminée : 82 tests rapides et 3 tests de performance passent |

## 1. Ce qui a été développé (`src/engine/`)

| Module | Rôle | Spécification |
|---|---|---|
| `migration.py` | **Migration conservative** : partage égal de l'excès entre les k plus proches unités receveuses (3 par défaut), itérations jusqu'à ce qu'il n'y ait plus d'excès. Recherche des voisins avec `cKDTree`, égalités de distance départagées par l'indice le plus petit, transferts vectorisés. **Mode `legacy`** : reproduction de l'ancien script (transfert en densité, arrondis à l'entier), pour la comparaison | §6 |
| `nonconvergence.py` | Contrôle préalable de capacité. Politiques `stop`, `raise_dmax` (hausse minimale proposée par paliers de 5 %, appliquée seulement après validation ou dans la limite automatique fixée par le scénario), `sink` et `unallocated`. Évacuation d'une zone (plafond nul, plus aucun accueil) | §7, X1 |
| `units.py` | Construction de la couronne de mailles puits (`build_sink_units`) | §7.2, S5 |
| `report.py` | Rapport d'un pas, en JSON et en texte, avec un bilan de population qui doit être nul | §8.3 |

## 2. Tests

| Fichier | Contenu |
|---|---|
| `test_migration.py` | T4, T5, T6 (dans les deux modes), T7, T8, T9 (stop, hausse des densités validée ou refusée, arrondi au palier supérieur, non relocalisés, couronne suffisante ou non), T12 (déterminisme et égalités de distance), évacuation, tolérance, invariants I1, I2, I3 et I7 sur 5 grilles aléatoires, rapport |
| `test_muramvya_migration.py` | Un pas de 2024 à 2025 ; 36 pas annuels successifs ; comparaison avec l'ancien algorithme |
| `test_performance.py` | Migration sur 2,25 millions d'unités (`-m slow`) |

## 3. Résultats

| Contrôle | Résultat |
|---|---|
| Muramvya, 2024 → 2025, croissance de 2,2 % | Statut « réussi ». 590 habitants déplacés en une itération. **Écart de bilan : 0,000000 habitant.** Aucune maille au-dessus de son plafond (à moins d'un habitant près) |
| Muramvya, 36 pas annuels | Population finale égale à P0 × 1,022³⁶ à 10⁻¹² près. Aucun dépassement de plafond |
| Ancien algorithme, mêmes données, un seul pas | **57 habitants perdus** (164 357 → 164 300), à cause des arrondis et du transfert en densité |
| Vitesse | **6,1 s** pour 2,25 millions d'unités dont 5 % en excès (5 itérations). Objectif : moins de 60 s. Muramvya : instantané |

## 4. Effet de la tolérance entière, à connaître

Avec une tolérance d'**un habitant**, un excès de moins d'un habitant reste dans sa maille (décision du 29/09/2026). Il n'est pas perdu : il part dès qu'il atteint un habitant. La conséquence est que **chaque maille peut dépasser son plafond de moins d'un habitant**.

L'effet est visible sur les zones sans migration découpées en nombreux petits morceaux. À Muramvya, la forêt compte 1 899 morceaux, peu peuplés chacun. En un an, sa population passe de 9 746 à 9 932 habitants, au lieu de rester à 9 746 : sur ces 186 habitants de croissance, la plupart restent sur place, par fractions de moins d'un habitant par morceau.

Ce surplus est **borné** (moins d'un habitant par morceau, donc moins de 1 899 pour la forêt) et **ne s'accumule pas** d'une année à l'autre : dès qu'un morceau atteint un habitant d'excès, celui-ci part. Il sera signalé dans le rapport.

**Si ce comportement ne convient pas pour les zones sans migration**, une variante simple consiste à ce que ces zones exportent **tout** leur excès, même fractionnaire. Leur population resterait alors exactement égale à leur population de base, et la tolérance continuerait de s'appliquer ailleurs. **À décider.**

## 5. Documentation

Premières pages d'aide du futur menu Aide du plugin (`docs/aide/`) :
- `croissance_plafonds_migration.md` : fonctionnement pas à pas, avec des exemples ;
- `non_convergence.md` : les quatre réponses possibles et un exemple chiffré.

## 6. Prochaine étape : phase 3

Enchaînement automatique des pas de temps, de l'année de départ à l'horizon final :
- pas de temps libre, et fréquence de migration annuelle ou par pas ;
- première année de migration (T14) ;
- paramètres variables dans l'espace et le temps (TCAM, densités max) ;
- zones exclues à partir d'une date (relocalisation ou arrêt de la croissance) ;
- départ au recensement ou à une année de projection, et recalage optionnel ;
- fichier de scénario, rapport consolidé et rasters de sortie par année.

Le plan détaillé sera soumis avant d'écrire le code.
