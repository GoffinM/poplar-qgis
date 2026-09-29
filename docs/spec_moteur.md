# Spécification du moteur de croissance et de migration

| | |
|---|---|
| **Objet** | Comportement attendu du moteur `src/engine/` : entrées, calculs, sorties, invariants et cas de test |
| **Sources** | `docs/BUR71_fiche_diagnostic_outil_SIG_population.md`, `docs/etat_des_lieux_code.md` (décisions §6 à §10) |
| **Date** | 29/09/2026 |
| **Statut** | **Projet, à valider.** Les points marqués **[S…]** sont des choix que je propose sans les avoir tranchés. Ils sont regroupés au §10 |

---

## 1. Principes

1. **La population est la grandeur conservée.** La densité sert à fixer les plafonds et à publier les résultats, mais on transfère toujours des habitants (décision A1/R1).
2. **Pas d'arrondi pendant le calcul.** L'état interne reste en réels. Seules les populations publiées sont arrondies à l'entier, avec un total conservé (R2).
3. **Aucun habitant ne disparaît sans être compté.** À chaque pas, population après = population avant + croissance ± recalage. Les habitants qui n'ont pas pu être placés sont comptés à part comme « non relocalisés ».
4. **Tout est paramétrable** : taille de maille, typologie, taux, plafonds, unités, années, pas de temps (§2).
5. **Comportement déterministe.** Les mêmes entrées donnent toujours le même résultat, y compris en cas d'égalité de distance (§6.3).
6. **Le moteur n'importe pas `qgis`.** Il n'utilise que numpy, scipy et GDAL/osgeo.

## 2. Entrées et paramètres

### 2.1 Données

| Donnée | Format | Obligatoire | Contenu |
|---|---|---|---|
| Population de base | Raster GDAL | oui | Densité de population à l'année de base, dans l'unité `density_unit` |
| Zone d'étude | Vecteur (polygones) | oui | Emprise du calcul |
| Zones de typologie | Vecteur (polygones) | oui | Un champ de classe à valeurs libres (par exemple `Rural`, `Urbain1`, ou `haut standing`, `ville satellite`…) |
| Zones sans migration | Vecteur (polygones) | non | Zones qui ne reçoivent jamais de migration (A7 = c) |
| Paramètres | Table (GeoPackage, CSV) ou valeur unique | oui | Voir §2.3 |
| Projections démographiques | Table | non | Totaux cibles par zone et par année, pour le recalage (§5.2) |

### 2.2 Paramètres du scénario

| Paramètre | Type | Défaut | Rôle |
|---|---|---|---|
| `base_year` | réel | — | Année de la population de base : l'année du recensement (RF4), 2024 pour le Burundi |
| `end_year` | réel | — | Horizon final, par exemple 2060 |
| `time_step` | réel > 0 | 1 | Pas de temps en années : 10, 5, 1, ou moins d'un an |
| `output_years` | liste | chaque pas | Années pour lesquelles les résultats sont écrits |
| `cell_size` | réel (m) | 250 | Côté de la maille |
| `density_unit` | `hab/km2` ou `hab/ha` | `hab/km2` | Unité des densités en entrée et en sortie (A8) |
| `k_neighbours` | entier ≥ 1 | 3 | Nombre de mailles receveuses par maille en excès (A2) |
| `interpolation` | `linear` | `linear` | Interpolation des paramètres entre années charnières |
| `extrapolation` | `constant` ou `linear` | `constant` | Valeur des paramètres avant la première et après la dernière année charnière |
| `nonconvergence_policy` | `stop`, `raise_dmax`, `sink`, `unallocated` | `stop` | Traitement de l'excédent sans capacité (§7) |
| `max_iterations` | entier | 10 000 | Garde-fou de la migration |
| `tolerance` | réel (habitants) | 0,01 | Seuil en dessous duquel un excès ou une capacité est considéré comme nul |
| `migration_mode` | `conservative` ou `legacy` | `conservative` | `legacy` reproduit l'outil actuel et sert uniquement à la comparaison (§6.5) |

### 2.3 Paramètres variables dans l'espace et le temps

Chaque paramètre peut être donné sous l'une de ces formes, de la plus simple à la plus détaillée :
1. **une valeur unique**, identique partout et tout le temps ;
2. **une valeur par classe** de typologie ;
3. **une valeur par classe ou par zone, et par année charnière.**

| Paramètre | Unité | Rôle |
|---|---|---|
| `growth_rate` | % par an | Taux de croissance annuel moyen |
| `dmax` | `density_unit` | Densité maximale au-delà de laquelle la population migre |

**Format long**, une ligne par valeur : `zone` (ou `class`), `year`, `parameter`, `value`.

**Interpolation (RF2).**
- Avec **une** année charnière, la valeur est constante.
- Avec **deux ou plus**, la valeur est interpolée linéairement entre elles.
- Avant la première et après la dernière année charnière, la valeur est constante par défaut, ou prolongée linéairement si `extrapolation = linear`.
- Une extrapolation linéaire peut donner un taux ou une densité aberrants (négatifs par exemple). Le moteur borne alors les valeurs (`dmax > 0`, `growth_rate > −100 %`) et signale le cas dans le rapport.

## 3. Grille de calcul

- La grille est alignée sur l'origine du raster de base, avec un pas de `cell_size`.
- **Surface utile** `a_i` (km², en réel) : surface de la maille *i* comprise dans la zone d'étude, calculée à partir de la géométrie, **sans arrondi** (voir F19). Les mailles de surface nulle sont ignorées.
- **Population de base** `P0_i` : somme sur les pixels du raster de base de (densité × surface commune entre pixel, maille et zone d'étude).
  - Si `cell_size` est un multiple du pixel, cela revient à additionner les populations des pixels.
  - Si la maille est plus petite que le pixel, la population du pixel est répartie au prorata des surfaces, avec un avertissement dans le rapport.
- **Classe** `c_i` de chaque maille : **[S1]** la classe qui couvre la plus grande part de la maille.
- **Statut « sans migration »** `x_i` : **[S2]** vrai si plus de 50 % de la surface utile de la maille est dans une zone sans migration.
- **Position** de la maille pour les calculs de distance : **[S3]** le centroïde de sa surface utile.

## 4. Capacité

À l'instant *t*, la capacité en habitants de chaque maille vaut :

- pour une maille ordinaire : `C_i(t) = a_i × max(d0_i, dmax(c_i, t))` ;
- pour une maille sans migration (A7-bis = c1) : `C_i(t) = P0_i`.

Ici `d0_i = P0_i / a_i` est la densité de l'année de base. Le `max` applique la règle A4 : une maille déjà en surcharge à l'année de base garde sa densité de base comme plafond.

**Mailles éligibles à recevoir** : toutes les mailles avec `a_i > 0` et `x_i` faux. Une maille sans migration ne reçoit jamais de population.

## 5. Déroulé d'un pas de temps [t, t + Δ]

1. **Croissance** (§5.1).
2. **Recalage**, s'il est activé (§5.2).
3. **Contrôle de capacité** (§7.1).
4. **Migration** (§6), ou application de la politique de non-convergence (§7).
5. **Bilan et rapport** du pas (§8).
6. **Écriture** des sorties si `t + Δ` fait partie de `output_years`.

Le pas suivant repart de la population **après migration** (A6).

Le premier pas commence à `base_year`. Le dernier pas est raccourci pour tomber exactement sur `end_year`, et chaque année de `output_years` est aussi atteinte exactement.

### 5.1 Croissance

`P_i ← P_i × G_i(t, Δ)`

**[S4]** Le facteur de croissance `G_i` est calculé en découpant le pas en sous-intervalles d'au plus un an. Sur chaque sous-intervalle de durée δ, on applique `(1 + r_i(s_mid)/100)^δ`, où `s_mid` est le milieu du sous-intervalle et `r_i` le taux interpolé pour la maille. Ainsi, une croissance calculée en 5 pas d'un an ou en 1 pas de 5 ans donne le même résultat.

La croissance s'applique à **toutes** les mailles, y compris celles sans migration. Pour ces dernières, la croissance dépasse leur capacité et devient un excès, exporté à l'étape de migration.

### 5.2 Recalage (option, Q5)

Pour chaque zone *z* de la table de projections, la population est remise à l'échelle du total cible : `P_i ← P_i × T_z(t+Δ) / Σ_{i∈z} P_i`. Le total cible `T_z` est interpolé comme au §2.3. Le facteur appliqué est reporté dans le rapport.

## 6. Migration

### 6.1 Définitions

À chaque itération :
- **Excès** : `E_i = P_i − C_i` pour toute maille où cette différence dépasse `tolerance`. Ces mailles sont les **sources**, et peuvent être éligibles ou sans migration.
- **Capacité libre** : `K_j = C_j − P_j` pour toute maille **éligible** où cette différence dépasse `tolerance`. Ces mailles sont les **receveuses**.

### 6.2 Itération (mode `conservative`)

Pour chaque source *i* :
1. On choisit ses `n_i = min(k_neighbours, nombre de receveuses)` receveuses les plus proches, selon la distance euclidienne entre positions (§3). La maille *i* elle-même est exclue.
2. Chacune de ces receveuses reçoit `E_i / n_i` habitants. Le partage est **égal**, et **la capacité libre des receveuses n'est pas vérifiée**, comme dans l'outil actuel (A2).
3. La source est ramenée à sa capacité : `P_i ← C_i`.

Toutes les sources d'une itération sont traitées **à partir du même état** : on calcule tous les transferts, puis on les applique ensemble.

Les itérations s'enchaînent jusqu'à ce qu'il n'y ait plus de source (convergence) ou qu'on atteigne `max_iterations` (non-convergence, §7).

**Propriétés attendues :**
- la population totale est conservée à chaque itération ;
- une maille remise à sa capacité n'est plus receveuse, donc aucun excès ne revient vers sa source ;
- l'excès total ne peut que baisser d'une itération à l'autre, et il baisse strictement dès qu'une receveuse absorbe quelque chose. S'il existe assez de capacité libre, le calcul converge.

### 6.3 Égalités de distance

Si plusieurs receveuses sont à la même distance, on retient celle qui a le plus petit indice de maille (ordre ligne par ligne, du nord au sud puis d'ouest en est).

### 6.4 Performance (pour la phase 4, sans effet sur le résultat)

- La recherche des plus proches receveuses se fait avec `scipy.spatial.cKDTree`, reconstruit à chaque itération et limité aux receveuses.
- Les transferts se font de façon vectorisée avec `numpy.add.at`.
- Seules les mailles actives (sources et receveuses) sont manipulées. Le reste de la grille n'est pas relu.

### 6.5 Mode `legacy` (comparaison uniquement)

Ce mode reproduit l'algorithme de `legacy/CAM12_migration.py` (état des lieux, §4.2) :
- transfert en densité, sans tenir compte des surfaces ;
- arrondi à l'entier de `dP`, du gain et de `P_sum` à chaque itération ;
- la source est remise à `Pmax` en densité.

Il ne conserve pas la population. Il ne sert qu'à mesurer l'écart avec l'outil actuel.

## 7. Non-convergence

### 7.1 Contrôle préalable

Avant de migrer, le moteur compare :
- la population des mailles éligibles, plus l'excès des mailles sans migration ;
- la capacité totale des mailles éligibles.

Si la première dépasse la seconde, la non-convergence est **certaine**. Comme les receveuses sont cherchées sans limite de distance, toute capacité libre est atteignable : ce contrôle global suffit.

La non-convergence est aussi déclarée si `max_iterations` est atteint.

### 7.2 Politiques

| Politique | Comportement |
|---|---|
| `stop` (défaut) | Arrêt avec un message explicite : manque de capacité en habitants, zones saturées. Les sorties déjà produites et le rapport sont conservés |
| `raise_dmax` | Le moteur calcule le **facteur minimal** *f* tel que `Σ a_i × max(d0_i, f × dmax_i) ≥` population à placer (par dichotomie). Il le propose arrondi au 5 % supérieur (+10 %, +25 %…), sur toute l'emprise ou sur les zones choisies. En mode interactif (plugin), l'utilisateur valide. En mode automatique, le facteur est appliqué seulement si le scénario l'autorise |
| `sink` | Une couronne de `sink_width` mailles autour de la zone d'étude, avec une densité max `sink_dmax`, s'ajoute aux receveuses. La population placée dans la couronne est reportée à part **[S5]** |
| `unallocated` | La migration continue jusqu'à épuisement de la capacité. L'excès restant est retiré des sources et enregistré comme **population non relocalisée**, à l'emplacement de la source. Il est reporté par maille, par zone et par année |

Dans tous les cas, la population non relocalisée est comptée à part : elle n'est jamais perdue silencieusement.

## 8. Sorties et rapport

### 8.1 Rasters, pour chaque année de `output_years`

| Sortie | Type | Contenu |
|---|---|---|
| `population_AAAA` | int32 | Population entière par maille (§8.2) |
| `density_AAAA` | float32 | `population_AAAA / a_i`, dans l'unité `density_unit` |
| `unallocated_AAAA` | float32 | Population non relocalisée, cumulée jusqu'à l'année AAAA |
| `capacity_AAAA` | float32 | Capacité `C_i` (utile au contrôle) |

### 8.2 Arrondi des populations publiées

On part de la population réelle `P_i`. On prend la partie entière de chaque maille, puis on attribue les habitants manquants, un par un, aux mailles qui ont les **plus grands restes**. Le nombre d'habitants manquants est `round(Σ P_i) − Σ ⌊P_i⌋`. En cas d'égalité de reste, on prend le plus petit indice de maille.

Cet arrondi ne concerne que les sorties : l'état interne n'est jamais arrondi.

### 8.3 Rapport d'exécution

Le rapport est produit en JSON (lisible par une machine) et en texte (lisible par une personne).

**Il contient :**
- les paramètres du scénario et les versions des logiciels ;
- pour chaque pas de temps : population avant et après croissance, facteur de recalage, capacité totale, nombre d'itérations, convergence, population non relocalisée, ajustements appliqués (facteur `raise_dmax`, population placée en couronne) ;
- le contrôle de conservation : écart entre population attendue et obtenue ;
- un **statut global** : `success`, `success_with_adjustments`, `partial` (population non relocalisée) ou `failed`.

## 9. Invariants vérifiés par les tests

| # | Invariant |
|---|---|
| I1 | Après migration : Σ P = Σ P avant migration − non relocalisés + placés en couronne, à 10⁻⁶ près en valeur relative |
| I2 | Après convergence, aucune maille éligible ne dépasse sa capacité de plus de `tolerance` |
| I3 | Une maille sans migration ne reçoit rien. Sa population après migration vaut exactement `P0_i` (c1) |
| I4 | Mêmes entrées, même résultat (déterminisme) |
| I5 | La croissance calculée en N pas de Δ ou en un pas de N × Δ donne le même facteur, à 10⁻⁹ près |
| I6 | Σ des populations entières publiées = `round(Σ P_i)` |
| I7 | Aucune valeur négative, aucun NaN dans les sorties |

## 10. Choix proposés, à valider

| # | Question | Proposition |
|---|---|---|
| S1 | À quelle classe appartient une maille coupée par une limite de typologie ? | La classe majoritaire en surface. L'outil actuel découpe la maille en fragments ; le moteur raster ne le fait pas. Une maille de 250 m à cheval sur la limite rural/urbain prend donc une seule classe |
| S2 | Quand une maille est-elle « sans migration » ? | Si plus de 50 % de sa surface utile est dans une zone sans migration |
| S3 | Quelle position retenir pour mesurer les distances ? | Le centroïde de la surface utile. Pour une maille entière, c'est son centre |
| S4 | Comment appliquer un taux qui varie pendant un pas ? | Sous-intervalles d'au plus un an, avec le taux au milieu de chaque sous-intervalle. Cela rend la croissance indépendante du pas choisi (I5) |
| S5 | Quels paramètres pour la couronne de mailles puits ? | `sink_width` = 4 mailles et `sink_dmax` = `dmax` de la classe la moins dense, par défaut |
| S6 | Le pas de temps influence la migration : migrer tous les ans ou tous les 5 ans ne donne pas exactement la même répartition. Est-ce acceptable ? | Oui, en le documentant. Proposition : un pas interne de 1 an par défaut, quelles que soient les années de sortie |
| S7 | Faut-il migrer au premier pas, dès l'année de base ? L'outil actuel ne migre pas en 2024 | Oui : chaque pas comprend croissance puis migration. En particulier, les mailles sans migration exportent leur croissance dès le premier pas |

---

## 11. Cas de test calculés à la main

**Conventions**, sauf mention contraire :
- les mailles sont alignées sur une ligne, aux positions x = 0, 1, 2… ;
- `a_i` = 1 km² ;
- `k_neighbours` = 3 ;
- les densités sont en hab/km² ;
- dans les tableaux, les populations sont données par maille dans l'ordre des positions.

### T1 – Croissance à taux constant
- **Entrée** : une maille, `P0` = 100, `growth_rate` = 2 %, un pas de 5 ans.
- **Attendu** : 100 × 1,02⁵ = **110,40808**.
- **Contrôle I5** : 5 pas de 1 an donnent le même résultat.

### T2 – Interpolation et extrapolation du taux
- **Entrée** : années charnières 2026 → 3 %, 2040 → 2 %.
- **Attendu** :
  - `r(2033)` = **2,5 %** ;
  - `r(2020)` = 3 % (extrapolation constante) ;
  - `r(2060)` = 2 % (constante), ou **0,5714 %** si l'extrapolation est linéaire.

### T3 – Croissance sur un pas avec un taux variable (S4)
- **Entrée** : mêmes taux que T2, `P0` = 1 000, un pas de 5 ans de 2026 à 2031.
- **Attendu** : facteur = Π des 5 années de (1 + r(y + 0,5)) = 1,1492569, donc **P = 1 149,2569**.

### T4 – Migration simple, une itération
- **Entrée** : 5 mailles, `C` = 10 chacune, `P` = [0, 0, 25, 0, 0].
- **Calcul** :
  - la maille 2 a un excès de 15 ;
  - receveuses les plus proches : 1 et 3 (distance 1), puis 0 et 4 à égalité (distance 2) → on retient 0 (§6.3) ;
  - chacune reçoit 5.
- **Attendu** : `P` = [**5, 5, 10, 5, 0**], 1 itération, total 25.

### T5 – Cascade sur deux itérations
- **Entrée** : `C` = 10 chacune, `P` = [0, 0, 46, 0, 0].
- **Itération 1** : excès 36 → +12 pour les mailles 1, 3 et 0 → [12, 12, 10, 12, 0].
- **Itération 2** : les mailles 0, 1 et 3 ont chacune un excès de 2. Seule la maille 4 est receveuse : elle reçoit 3 × 2.
- **Attendu** : [**10, 10, 10, 10, 6**], 2 itérations, total 46.

### T6 – Maille incomplète (R1)
- **Entrée** : 2 mailles, `a` = [1 ; 0,25], `dmax` = 10, `P0` = [10, 0], `k_neighbours` = 1, un pas de 1 an avec `growth_rate` = 20 %.
- **Croissance** : [12, 0]. Capacités `C` = [10 ; 2,5].
- **Migration** : excès 2 → la maille 1 reçoit 2 habitants.
- **Attendu en mode `conservative`** : `P` = [**10, 2**], soit une densité de 8 hab/km² pour la maille 1. Total 12.
- **Attendu en mode `legacy`** : la maille 1 reçoit +2 en **densité**, soit 0,5 habitant. `P` = [10 ; 0,5], total 10,5 : **1,5 habitant perdu**.

### T7 – Zone sans migration (A7 = c, c1)
- **Entrée** : maille 0 sans migration avec `P0` = 10 ; maille 1 éligible avec `P0` = 0 et `dmax` = 10 ; `growth_rate` = 10 %, un pas de 1 an.
- **Croissance** : [11, 0]. Capacité de la maille 0 : `C_0` = `P0` = 10, d'où un excès de 1.
- **Attendu** : `P` = [**10, 1**], total 11. La maille 0 reste à 10 (I3).

### T8 – Maille en surcharge à l'année de base (A4)
- **Entrée** : maille 0 avec `d0` = 12 et `dmax` = 10, donc `C_0` = 12 ; maille 1 avec `P0` = 0 et `C_1` = 10 ; `growth_rate` = 10 %, un pas de 1 an.
- **Croissance** : [13,2 ; 0].
- **Attendu** : `P` = [**12 ; 1,2**], total 13,2.

### T9 – Non-convergence
- **Entrée** : 2 mailles éligibles, `d0` = [8, 8], `dmax` = 10, `C` = [10, 10], état à migrer `P` = [15, 10].
- **Contrôle préalable** : population 25 > capacité 20 → non-convergence certaine.
- **Attendu selon la politique** :

| Politique | Résultat |
|---|---|
| `stop` | Erreur « capacité insuffisante : 5 habitants », statut `failed` |
| `raise_dmax` | f minimal = 1,25, proposé +25 %. Après application, `C` = [12,5 ; 12,5] et `P` = [**12,5 ; 12,5**]. Statut `success_with_adjustments` |
| `unallocated` | `P` = [**10, 10**], avec **5** habitants non relocalisés sur la maille 0. Statut `partial`. Invariant I1 : 20 + 5 = 25 |

### T10 – Arrondi des populations publiées
- **Entrée** : `P` = [1,4 ; 1,4 ; 1,2], total 4.
- **Calcul** : parties entières [1, 1, 1], soit 3. Il manque 1 habitant. Les plus grands restes sont 0,4 et 0,4, à égalité → on retient le plus petit indice.
- **Attendu** : [**2, 1, 1**], total 4.

### T11 – Agrégation de la grille
- **Entrée** : raster de 4 × 4 pixels de 250 m, de densité uniforme 1 000 hab/km², et `cell_size` = 500 m.
- **Attendu** : 4 mailles de 0,25 km² et de **250 habitants** chacune. Total 1 000 = 16 pixels × 62,5 habitants.

### T12 – Déterminisme
- **Entrée** : T4 exécuté deux fois, et avec l'ordre des sources permuté.
- **Attendu** : des résultats identiques bit à bit (I4).

---

## 12. Données de référence

| Référence | Usage |
|---|---|
| `reference_outputs/muramvya/p2023_entree` | Comparaison chiffrée de la préparation (densité par maille, `Pmax` par classe). Tolérances : 1 % sur la population par maille, pour tenir compte de F19 et du passage des fragments aux mailles raster (S1) ; 0,5 % sur le total |
| `reference_outputs/muramvya/pentree_final` | Référence qualitative (état des lieux §10.5). On relance le moteur avec les taux par période du §10.3, puis on compare les totaux, l'absence de dépassement et la répartition urbain/rural. Les écarts dus à RF3 et F19 sont attendus et documentés |
