# Bilan : polygones libres, étapes 1 à 5 (Muramvya)

| | |
|---|---|
| **Date** | 06/10/2026 |
| **Plan** | `plan_polygones_libres.md` (décisions B1, B2, S1, B ; P3 à P19) |
| **Banc** | Cas `muramvya_libre` ajouté à `tools/banc.py` |
| **Statut** | Moteur et sorties terminés. Décisions D1, D2 et D3 **acceptées le 06/10** ; D2 appliquée ; plan de D1 dans `plan_polygones_libres.md` §15, à valider ; l'interface (étape 6) attend D1 |

## 1. Ce qui est fait

| Étape | Contenu |
|---|---|
| 1 | Règle de colonisation (`polygons.py`) et cas synthétiques (ville carrée, limite en biais) |
| 2 | Suivi des flux dans la migration ; partage des ex aequo en mode libre (P16) |
| 3 | Mode libre branché dans la simulation : état `polygon_id`, paramètres qui suivent le polygone, pas annuel, conservation contrôlée à chaque pas, effet de reclassement mesuré |
| B | Condition de pression : population **exportée** par le colonisateur (le front ne se bloque plus après la première couronne) |
| 4 | Sorties : `polygon_id_AAAA.tif`, `statut_AAAA.tif`, `annee_colonisation.tif`, `polygones.gpkg` (polygones lissés, extensions, généalogie), champs de `mailles.gpkg` ; règle des nouveaux noyaux, désactivée par défaut |
| 5 | Indicateurs de plausibilité (`plausibilite.csv` et `.json`, section du rapport HTML) ; comparaison des deux modes (`python -m engine compare <planifié> <libre>`) ; cas Muramvya au banc |

**Mode planifié** : à chaque commit, la suite complète, le banc et `reference_outputs/` sont restés identiques au chiffre près.

## 2. Muramvya en mode libre (2024 → 2060)

Le scénario d'exemple a été lancé tel quel en mode libre (rangs : Rural 1, Urbain1 2), puis avec d'autres réglages. Durée : environ 9 s, contre 6 s en mode planifié.

| Réglage | Mailles colonisées | Nouveaux noyaux | Surface urbaine 2060 (unités, km²) | Front max (m/an) | Non accueillis |
|---|---|---|---|---|---|
| Mode planifié | – | – | 20,13 | – | 0 |
| Libre, valeurs par défaut (part saturée 80 %, flux 10 %) | **0** | 0 | 20,13 | 0 | 0 |
| Part saturée 50 % | 0 | 0 | 20,13 | 0 | 0 |
| Part saturée 25 % | 16 | 0 | 20,20 | 0,8 | 0 |
| Part saturée 10 % | 11 | 0 | 20,15 | 0,2 | 0 |
| Part saturée 25 %, flux 5 % | 16 | 0 | 20,20 | 0,7 | 0 |
| Part saturée 10 %, flux 2 % | 19 | 0 | 20,28 | 0,8 | 0 |
| Défaut + **nouveaux noyaux** (strate Urbain1, 4 mailles) | 0 | **58** | 35,34 | – | 0 |

Population 2060 : 320 361 dans tous les cas, puisque le TCAM est le même partout et qu'il n'y a donc pas d'effet de reclassement. Le bilan de masse est nul à chaque horizon.

**Pourquoi le front ne bouge presque pas.** Les polygones urbains de Muramvya sont des **limites administratives** : toute la commune urbaine, en deux morceaux de 10 km² chacun. Ce ne sont pas des taches bâties.

| Polygone | Densité moyenne 2024 → 2060 | Médiane des mailles 2060 | 90e centile 2060 | Part saturée 2060 |
|---|---|---|---|---|
| Urbain1, ville de Muramvya | 2 471 → 4 665 hab/km² | 3 739 | 10 000 (= dmax) | 27 % |
| Urbain1, second morceau | 731 → 1 375 hab/km² | 372 | 3 945 | 7 % |
| Rural | 584 → 1 096 hab/km² | 827 | 2 500 (= dmax) | 20 % |

Le centre-ville sature, mais la commune urbaine a encore de la place autour de lui. La ville se **densifie dans ses limites** au lieu de déborder. Les 16 à 19 colonisations des réglages bas sont des **résidus** : des morceaux ruraux de mailles déjà majoritairement urbaines (P13), à la limite de la commune. Compté maille par maille, la surface urbaine est donc la même dans les deux modes (20,81 km²).

**Nouveaux noyaux.** Activée, la règle crée 58 noyaux de 2025 à 2060 : 269 mailles et 44 000 habitants en 2060, presque tous de la taille minimale de 4 mailles (0,25 km²). Aucun n'est marqué « à vérifier ». Ils naissent là où des mailles rurales voisines atteignent ensemble la dmax rurale (2 500 hab/km²), puis prennent la dmax urbaine de 10 000 hab/km² : leur capacité est multipliée par 4. Avec ces réglages, c'est trop de noyaux pour être plausible.

## 3. Comparaison des deux modes (décision Q11)

`python -m engine compare <dossier planifié> <dossier libre>` écrit `comparaison_modes.csv` et `.html` dans le dossier libre. Pour chaque année de sortie, on y trouve :
- la surface et la population urbaines dans chaque mode ;
- la population urbaine hors du périmètre planifié ;
- la population non accueillie dans chaque mode ;
- les vitesses de front moyenne et maximale.

À Muramvya, avec les données actuelles, les deux modes donnent la même surface urbaine et aucun non-accueilli. La pression d'urbanisation hors du périmètre est nulle, puisque le périmètre planifié (la commune urbaine) suffit jusqu'en 2060. Sur la ville carrée du cas test, en revanche, la comparaison montre bien un écart croissant.

## 4. Décisions demandées

| # | Question | Ma proposition |
|---|---|---|
| **D1** | **Polygones de départ du mode libre.** Avec des limites administratives, le mode libre n'a presque rien à faire. Faut-il partir des **taches bâties** (fiche §3.4) ? | Une étape de préparation, facultative : les mailles au-dessus d'un seuil de densité (de population ou de toits), regroupées en taches contiguës, deviennent les polygones urbains de départ ; le reste de la commune urbaine devient une strate de transition. Seuils à fixer avec vous (repère DEGURBA : 1 500 hab/km² et 50 000 habitants pour un centre, 300 hab/km² et 5 000 habitants pour un amas, sur des mailles de 1 km) |
| **D2** | **Nouveaux noyaux** : trop nombreux avec 4 mailles et la strate Urbain1 | Taille minimale portée à **16 mailles (1 km²)**, et strate des noyaux **intermédiaire** (Urbain2, dmax 7 500) plutôt que la strate la plus urbaine. La règle reste désactivée par défaut |
| **D3** | Valeurs par défaut P14 (part saturée 80 %, flux 10 %) | Les garder tant que D1 n'est pas tranché : sur des polygones administratifs, aucune valeur ne donne de front plausible, et une valeur plus basse ne colonise que des résidus. Elles seront à recaler sur les taches bâties |

Les vitesses de front ne peuvent pas être jugées sur Muramvya en l'état : elles sont presque nulles. Cela vient des polygones de départ (D1), pas de la règle de colonisation.

## 5. D1 : Muramvya sur les taches bâties (06/10)

`python -m engine patches scenario_muramvya.json` (1 500 hab/km², 5 000 habitants, lissage en deux passes) trouve deux taches :

| Tache | Classe | Mailles | Surface | Habitants (2024) | Dans la commune urbaine |
|---|---|---|---|---|---|
| Ville de Muramvya | Urbain1 | 85 | 5,3 km² | 22 933 | 98 % |
| Village dense | Urbain2 (Q-b) | 28 | 1,7 km² | 6 268 | 0 % |

Le reste de la commune urbaine (14,3 km²) devient la strate **Transition**, avec la dmax rurale (2 500) et le TCAM urbain (Q-c). Les rangs sont Rural 1, Transition 2, Urbain2 3 et Urbain1 4 ; seules les taches comptent comme urbaines (`urban_rank` = 3).

**Les deux modes sur la nouvelle typologie, 2024 → 2060.** Aucun non-accueilli dans tous les cas, et le bilan de masse est nul.

| Réglage du mode libre | Mailles colonisées | Premières colonisations | Surface urbaine 2060 (planifié 7,06 km²) | Habitants hors du périmètre planifié en 2060 | Front de la ville (m/an) |
|---|---|---|---|---|---|
| Défaut : part saturée 80 %, flux 10 % | 0 | – | 7,06 | 0 | 0 |
| Part saturée 50 % | 19 | 2056 | 8,06 | 2 527 | 7 (2055–2060) |
| Part saturée 25 % | 47 | 2041 | 8,25 | 4 103 | 1 à 3 |
| Défaut, dmax urbaine 6 000 au lieu de 10 000 | 28 | 2051 | 8,25 (en 2055) | 4 270 | 12 (2050–2055) |

Considérer une maille comme saturée à 95 % ou à 90 % de sa capacité, au lieu d'une place libre, ne change presque rien : 50 à 53 mailles avec une part saturée de 25 %.

**Lecture.** La ville part d'une densité médiane de 3 800 hab/km² (2030), pour une dmax de 10 000. Elle peut donc encore se **densifier** beaucoup, et elle le fait :
- en 2060, sa densité médiane atteint 9 150 hab/km², mais seulement 54 % de sa surface est saturée ;
- le débordement du centre remplit d'abord les bords de la tache, moins denses, avant de sortir.

Le front ne part que si l'on demande moins de 80 % de saturation, ou si la dmax urbaine est plus proche des densités observées. Les vitesses restent faibles (1 à 12 m/an), et l'élasticité ne dépasse 1 (étalement) qu'en fin de période. **C'est à vous de juger la plausibilité de ces fronts (P14)**. Les leviers sont la part saturée demandée et la dmax urbaine ; tous deux sont des paramètres du scénario, sans rien à coder.
