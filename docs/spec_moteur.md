# Spécification du moteur de croissance et de migration

| | |
|---|---|
| **Objet** | Comportement attendu du moteur `src/engine/` : entrées, calculs, sorties, invariants et cas de test |
| **Sources** | `docs/BUR71_fiche_diagnostic_outil_SIG_population.md`, `docs/etat_des_lieux_code.md` (décisions §6 à §10) |
| **Date** | 29/09/2026 |
| **Statut** | **Projet v2.** Choix S1 à S7 tranchés le 29/09/2026 (§10). Reste à valider dans son ensemble |

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
| Limites administratives | Vecteur (polygones) | oui | Unités administratives (pays, provinces, communes, collines…). Elles définissent la zone d'étude et servent aux bilans par unité |
| Frontière nationale | Vecteur (polygones) | non | Tout ce qui est hors du pays est retiré du calcul : les bâtiments situés hors du pays ne sont pas comptés et aucune population n'y est placée |
| Zones d'exclusion | Une ou plusieurs couches vectorielles (polygones ou lignes) | non | Forêts, lacs, rivières, zones tampons, domaines militaires, périmètres de sécurité… Chaque couche, ou chaque catégorie, a un comportement (§2.4). Les lignes, comme les rivières, sont transformées en polygones avec une largeur de tampon paramétrable |
| Toits (bâti) | Vecteur (polygones, ou points avec un champ de surface) lu directement depuis sa source : Google Open Buildings en priorité, puis PostGIS, GeoPackage, shapefile, WFS, GeoParquet | oui pour le calage | Empreintes des bâtiments (§3 bis) |
| Recensement | Table ou champ d'une couche de limites administratives, **avec son année** | oui pour le calage | Population par unité administrative. Elle sert au calage (§3 ter) et fixe `base_year` |
| Projections démographiques | Table : unité, année, total | non | Totaux cibles pour une ou plusieurs années, qui servent au recalage (§5.2) |
| Population de base déjà calculée | Raster GDAL | non | Alternative au calage : densité de population à l'année de base, comme le raster `POP2023` actuel |
| Zones de typologie | Vecteur (polygones) | oui | Un champ de classe à valeurs libres (par exemple `Rural`, `Urbain1`, ou `haut standing`, `ville satellite`…) |
| Strates de calage | Vecteur (polygones) | non | Nombre et regroupement des régressions (§3 ter.1). Par défaut, les limites administratives croisées avec la typologie |
| Paramètres | Table (GeoPackage, CSV) ou valeur unique | oui | Taux de croissance (TCAM) et densités max, par zone et dans le temps (§2.3) |
| Coefficients de traduction | Table ou valeur unique | non | Dotations en eau potable par habitant et par jour, ou autre ratio (§8.4) |

### 2.2 Paramètres du scénario

| Paramètre | Type | Défaut | Rôle |
|---|---|---|---|
| `base_year` | réel | — | Année que représente la population de base (RF4). Pour BUR71 : 2024, année du recensement sur lequel le raster est calé |
| `start_mode` | `census` ou `projection` | `census` | Point de départ, au choix de l'utilisateur (§5.3). `census` : on part du recensement, ce qui est l'approche prudente. `projection` : on part d'une année de projection, avec la population remise à l'échelle des totaux projetés, si le client fait confiance à ses projections |
| `first_migration_year` | réel | **à fixer par l'utilisateur** | Première année où la migration s'applique. Avant cette année, on n'applique que la croissance. Ce choix dépend des dates des données sources : par exemple toits de 2023 et population de 2024 (S7) |
| `end_year` | réel | — | Horizon final, par exemple 2060 |
| `time_step` | réel > 0 | 1 | Pas de temps en années : 10, 5, 1, ou moins d'un an |
| `migration_frequency` | `annual` ou `time_step` | `annual` | `annual` : croissance et migration année par année, quel que soit le pas. `time_step` : une seule migration par pas. Ce second mode est plus rapide, mais la répartition est de moindre qualité (S6) |
| `output_years` | liste | chaque pas | Années pour lesquelles les résultats sont écrits |
| `cell_size` | réel (m) | 250 | Côté de la maille |
| `density_unit` | `hab/km2` ou `hab/ha` | `hab/km2` | Unité des densités en entrée et en sortie (A8) |
| `k_neighbours` | entier ≥ 1 | 3 | Nombre de mailles receveuses par maille en excès (A2) |
| `interpolation` | `linear` | `linear` | Interpolation des paramètres entre années charnières |
| `extrapolation` | `constant` ou `linear` | `constant` | Valeur des paramètres avant la première et après la dernière année charnière |
| `nonconvergence_policy` | `stop`, `raise_dmax`, `sink`, `unallocated` | `stop` | Traitement de l'excédent sans capacité (§7) |
| `max_iterations` | entier | 10 000 | Garde-fou de la migration |
| `tolerance` | entier ≥ 1 (habitants) | 1 | Seuil en dessous duquel un excès ou une capacité libre n'est pas pris en compte. Il est entier, car on ne déplace pas une fraction d'habitant (décision du 29/09/2026). Un excès inférieur au seuil reste sur place et n'est pas perdu : il sera déplacé au pas suivant s'il dépasse alors le seuil |
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

### 2.4 Comportement des zones d'exclusion (validé)

Chaque couche ou catégorie d'exclusion reçoit l'un de ces deux comportements :

| Comportement | Effet | Exemples, par défaut |
|---|---|---|
| `outside` | La zone est **retirée du domaine de calcul** : on n'y compte aucun bâtiment et on n'y place aucune population | Hors pays (frontière nationale), lacs |
| `no_inflow` | La zone ne reçoit **aucune population nouvelle**. Ses habitants existants restent comptés, avec un plafond égal à leur population de base : leur croissance est exportée vers les zones autorisées (A7 = c, A7-bis = c1) | Forêts, rivières et leurs tampons, domaines militaires, périmètres de sécurité |

**Date d'effet (validé).** Une zone d'exclusion peut porter une année d'effet `exclusion_year`, par exemple un périmètre de sécurité créé en 2030. Avant cette année, la zone est traitée comme une zone ordinaire. À partir de cette année, elle suit le même comportement qu'une zone exclue dès le départ :
- `no_inflow` : la zone n'accueille plus personne. Son plafond devient la population présente à `exclusion_year`, et la croissance qui suit est exportée ;
- pour une zone qui devient inhabitable en cours de période (X1, validé), l'utilisateur choisit entre deux traitements :
  - `relocate` : **tous les habitants** présents à `exclusion_year` sont relocalisés vers les zones autorisées par la migration normale, puis la zone est retirée du domaine. C'est le cas d'un lac de barrage. Le nombre de personnes déplacées figure dans le rapport ;
  - `no_inflow` : on **arrête la croissance** de la zone. Ses habitants restent, et leur croissance est traitée comme un excès qui migre ailleurs.

  Aucun habitant n'est jamais retiré du total sans être relocalisé.

## 3. Grille et unités de calcul

- La grille est alignée sur l'origine du raster de base, avec un pas de `cell_size`.
- **Unités de calcul (S1/S2).** Chaque maille est découpée par intersection avec :
  - la zone d'étude,
  - les zones de typologie,
  - les zones sans migration.

  Chaque sous-polygone obtenu, éventuellement multi-parties, est une **unité** *u*. C'est l'équivalent des fragments de l'outil actuel.
- Une unité porte :
  - sa maille `m_u` ;
  - sa **surface** `a_u` (km², en réel, calculée à partir de la géométrie, **sans arrondi**, voir F19) ;
  - sa **classe** `c_u` ;
  - son statut **sans migration** `x_u` ;
  - sa **position**, le **centroïde** de sa géométrie (S3).
- Les unités de surface inférieure à `min_unit_area` (par défaut 1 m²) sont rattachées à l'unité voisine de même maille ayant la plus grande surface. Cela évite les éclats numériques.
- **Population de base** `P0_u`, à partir d'un raster de densité : somme sur les pixels de (densité × surface commune entre pixel et unité). Un pixel à cheval sur la limite du domaine est traité selon `boundary_mode` :
  - `area_weighted` : seule la part du pixel située dans le domaine est comptée ;
  - `renormalized` : toute la population du pixel est répartie entre les unités qui le couvrent.

  **Décision (29/09/2026) : `area_weighted` par défaut.** Le pixel est découpé et seule la surface située dans le domaine est retenue. `renormalized` reste disponible en option. Les pixels sans valeur (nodata) comptent pour zéro, et leur surface est reportée.
- **Mise en œuvre (phase 4).** Seules les mailles traversées par une limite sont découpées, avec la géométrie OGR/GDAL. Les mailles intérieures restent entières (une unité = une maille) et sont traitées en tableau. Le moteur manipule un tableau 1D d'unités, pas une image.
- **Sorties raster** : pour chaque maille, population = somme des unités, et densité = population / surface utile totale de la maille. Une couche vectorielle des unités peut aussi être produite en option.

## 3 bis. Lecture des toits et affectation aux unités

**Volumes visés** : 38 000 bâtiments pour Muramvya, et **de plusieurs centaines de milliers à quelques millions** pour des emprises régionales ou nationales.

**Principe.** Un bâtiment est réduit à un **point** (son centroïde) et à sa **surface de toit**, comme dans la pratique actuelle. Le moteur ne conserve jamais les polygones en mémoire.

| Étape | Mise en œuvre |
|---|---|
| 1. Filtrage à la source | Seuls les bâtiments de l'emprise de la zone d'étude sont demandés (filtre spatial OGR). Pour PostGIS, le filtre et le calcul du centroïde et de la surface s'exécutent **sur le serveur** (`ST_Centroid`, `ST_Area`), si bien que seuls des points et des nombres transitent |
| 2. Lecture par paquets | Lecture de 50 000 à 100 000 bâtiments à la fois. Pour chaque paquet, on extrait x, y et la surface dans des tableaux numpy (3 réels par bâtiment : environ 24 Mo par million) |
| 3. Surface en projection métrique | Si la source est en degrés (EPSG:4326, cas des jeux mondiaux), les géométries sont reprojetées dans le système de la grille avant de calculer la surface |
| 4. Affectation aux unités | Pour une maille entière, l'affectation est un simple calcul d'indice (`floor((x − x0) / cell_size)`), vectorisé. Le test point-dans-polygone (OGR) n'est fait que pour les points qui tombent dans une maille découpée, soit une petite fraction du total |
| 5. Stockage | Un tableau (unité, surface) par bâtiment. On garde la surface **de chaque bâtiment**, et pas seulement la somme par unité, car une régression non linéaire se calcule bâtiment par bâtiment avant d'être sommée (§3 bis.1) |

**Entrée « points » acceptée.** Si l'utilisateur a déjà extrait les centroïdes avec un champ de surface, les étapes 1 à 3 se réduisent à la lecture de deux coordonnées et d'un champ.

**Objectif de performance** : 1 million de bâtiments lus et affectés en **moins de 2 minutes** sur un poste standard, à partir d'un GeoPackage local. Il sera vérifié par un test sur un jeu synthétique d'un million de polygones.

### 3 bis.1 Décisions (29/09/2026)

| # | Question | Décision |
|---|---|---|
| B1 | Quelle source de bâti traiter en priorité ? | **Google Open Buildings.** Les fichiers de ce jeu donnent déjà, pour chaque bâtiment, `latitude`, `longitude`, `area_in_meters` et `confidence`. Le moteur peut donc lire ces colonnes directement, sans décoder les polygones, ce qui est très rapide. Il ne reste qu'à projeter les centroïdes dans le système de la grille. **À confirmer à l'implémentation** : le format exact des fichiers téléchargés (CSV compressé par tuile) et la présence de ces colonnes |
| B2 | Centroïde ou point intérieur ? | Centroïde par défaut, point intérieur en option |
| B3 | La régression est-elle appliquée par bâtiment ou par zone ? | **Par bâtiment**, d'après les classeurs Excel (état des lieux, §11) : population = f(surface), puis somme par pixel. On conserve donc la surface de chaque bâtiment |
| B4 | Quels attributs lire pour chaque bâtiment ? | Pour l'instant, **la surface seule**. Un champ d'usage (habitat ou non), s'il existe, pourra servir de filtre. Pour Google Open Buildings, le champ `confidence` est lu et un seuil minimal de confiance est proposé en option |

## 3 ter. Calage bâti → population (phase 6)

**Mode `legacy`.** Il reproduit exactement la méthode Excel décrite dans l'état des lieux (§11.2), avec pour chaque strate (rural, urbain…) les paramètres suivants :
- `min_area` (10 m²) et `max_area` (450 m²) : en dehors de cet intervalle, le bâtiment compte 0 habitant ;
- `cap_area` (70 m²) et `cap_value_area` (80 m²) : au-delà de `cap_area`, la population est plafonnée à p(`cap_value_area`) ;
- les coefficients du polynôme de degré 3.

Ce mode sert à vérifier qu'on retrouve 139 100 et 33 253 habitants sur Muramvya, avec les coefficients arrondis.

**Mode amélioré (par défaut, à valider)** :
- ajustement direct par moindres carrés, avec les coefficients en pleine précision (F20) ;
- choix de la forme de la courbe : polynôme, log-linéaire ou par morceaux ;
- contrainte de **monotonie** : un bâtiment plus grand n'a jamais moins d'habitants (F21) ;
- ajustement sur la surface moyenne de chaque classe (F22), ou directement sur les bâtiments quand les données le permettent ;
- **recalage optionnel** sur la population administrative de chaque strate (F24), avec un rapport des écarts ;
- toutes les strates dans un seul calage (F27).

### 3 ter.1 Strates de calage : combien de régressions ?

L'utilisateur choisit le **nombre de régressions** au moyen d'une couche de **strates de calage** (polygones), par exemple un shapefile de communes découpées en rural et urbain.

| Champ | Rôle |
|---|---|
| `stratum_id` | Identifiant de la strate. **Chaque strate a sa propre population administrative** et son recalage |
| `regression_group` (optionnel) | Strates qui **partagent une même régression**. Par défaut, chaque strate a la sienne |
| `census_pop` (optionnel) | Population administrative de la strate, qui sert au calage et au recalage |

Exemples :
- **Muramvya aujourd'hui** : 2 strates (rural, urbain), donc 2 régressions ;
- **plusieurs communes, une régression par commune et par type** : `regression_group` = commune + type ;
- **plusieurs communes, une régression rurale et une urbaine communes à toutes** : `regression_group` = type. On ajuste la courbe sur l'ensemble des communes, puis chaque commune est recalée sur sa propre population.

**Garde-fou** : une strate qui a trop peu de bâtiments, ou pas de population administrative, est signalée. L'utilisateur choisit alors la régression d'un autre groupe à lui appliquer.

### 3 ter.2 Ajustement manuel des régressions

Pour chaque régression, l'utilisateur peut, au choix :
1. **accepter** la régression calculée par l'outil ;
2. **modifier** les points de calage (habitants par classe de surface), puis relancer l'ajustement. C'est l'équivalent de la colonne « valeur de solveur » d'Excel ;
3. **saisir directement** la forme et les coefficients de la courbe ;
4. **modifier les seuils** : surfaces minimale et maximale, surface de plafonnement.

Le plugin affiche pour chaque régression :
- la courbe et les points de calage ;
- l'écart avec la population administrative ;
- des diagnostics : monotonie, valeurs négatives, part des bâtiments plafonnés.

Chaque modification manuelle est **enregistrée dans le fichier de scénario et signalée dans le rapport** (qui, quoi, valeurs avant et après). Un calage peut être sauvegardé, puis réutilisé pour une autre commune.

## 4. Capacité

À l'instant *t*, la capacité en habitants de chaque unité vaut :

- pour une unité ordinaire : `C_u(t) = a_u × max(d0_u, dmax(c_u, t))` ;
- pour une unité sans migration (A7-bis = c1) : `C_u(t) = P0_u`.

Ici `d0_u = P0_u / a_u` est la densité de l'année de base. Le `max` applique la règle A4 : une unité déjà en surcharge à l'année de base garde sa densité de base comme plafond.

**Unités éligibles à recevoir** : toutes les unités avec `a_u > 0` et `x_u` faux. Une unité sans migration ne reçoit jamais de population.

Dans la suite (§5 à §7), le terme « maille » désigne une unité de calcul.

## 5. Déroulé d'un pas de temps [t, t + Δ]

1. **Croissance** (§5.1).
2. **Recalage**, s'il est activé (§5.2).
3. **Contrôle de capacité** (§7.1).
4. **Migration** (§6), ou application de la politique de non-convergence (§7). Cette étape n'a lieu que si `t + Δ ≥ first_migration_year`.
5. **Bilan et rapport** du pas (§8).
6. **Écriture** des sorties si `t + Δ` fait partie de `output_years`.

Avec `migration_frequency = annual`, un pas de Δ années est découpé en sous-pas d'au plus un an. Chaque sous-pas enchaîne croissance, recalage et migration, et les sorties ne sont écrites qu'à la fin du pas. Avec `migration_frequency = time_step`, le pas est traité d'un seul bloc.

Le pas suivant repart de la population **après migration** (A6).

La simulation commence à `base_year`. Le dernier pas est raccourci pour tomber exactement sur `end_year`, et chaque année de `output_years` est aussi atteinte exactement.

### 5.1 Croissance

`P_u ← P_u × (1 + r̄_u / 100)^Δ`

`r̄_u` est le **taux moyen de l'unité sur le (sous-)pas** (S4), c'est-à-dire la moyenne de `r_u(s)` pour s allant de t à t + Δ. Avec une interpolation linéaire, c'est la valeur au milieu du pas lorsqu'aucune année charnière ne tombe à l'intérieur. Sinon, c'est la moyenne pondérée par la durée de chaque segment.

La croissance s'applique à **toutes** les unités, y compris celles sans migration. Pour ces dernières, la croissance dépasse leur capacité et devient un excès, exporté à l'étape de migration.

**Sensibilité au pas.** Un pas grossier ne change le facteur de croissance que marginalement (T3). En revanche, il change la migration (S6). Le rapport l'indique (§8.3).

### 5.2 Recalage en cours de simulation (option, Q5)

Pour chaque zone *z* de la table de projections, la population est remise à l'échelle du total cible : `P_i ← P_i × T_z(t+Δ) / Σ_{i∈z} P_i`. Le total cible `T_z` est interpolé comme au §2.3. Le facteur appliqué est reporté dans le rapport.

### 5.3 Point de départ : recensement ou projection (validé)

| `start_mode` | Année de départ | Population de départ |
|---|---|---|
| `census` (prudent) | Année du recensement | Population calée sur le recensement (§3 ter). Les projections, si elles sont fournies, ne servent qu'au recalage optionnel (§5.2) ou à une comparaison dans le rapport |
| `projection` | Une année de projection choisie par l'utilisateur | Population du recensement, répartie comme au calage, puis remise à l'échelle des totaux projetés pour cette année, unité par unité. On n'applique aucune croissance entre le recensement et cette année |

Dans les deux cas, le recalage sur les projections des années suivantes reste une option indépendante (§5.2).

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
- la **qualité de la résolution** : taille de maille, pas de temps, `migration_frequency`, `first_migration_year`. Si le calcul est grossier (maille plus grande que le raster de base, ou migration par pas de plus d'un an), un avertissement explicite précise que le résultat est une première approche, à affiner (S6) ;
- pour chaque pas de temps : population avant et après croissance, facteur de recalage, capacité totale, nombre d'itérations, convergence, population non relocalisée, ajustements appliqués (facteur `raise_dmax`, population placée en couronne) ;
- le contrôle de conservation : écart entre population attendue et obtenue ;
- un **statut global** : `success`, `success_with_adjustments`, `partial` (population non relocalisée) ou `failed`.

### 8.4 Traductions des résultats (indicateurs dérivés)

Un indicateur se calcule par la formule : population × coefficient. Le coefficient peut être une valeur unique, ou varier par zone et dans le temps, avec une interpolation comme au §2.3.

| Indicateur | Formule | Sorties |
|---|---|---|
| **Demande en eau potable** (prioritaire) | Voir le détail ci-dessous | Rasters par année, totaux par unité administrative et par zone de desserte |
| Autres indicateurs | Même mécanisme, avec un coefficient et une unité libres : déchets, énergie, besoins scolaires… | Raster et tableaux par unité administrative |

**Demande en eau potable (validé).** Tous les paramètres ci-dessous peuvent être une valeur unique, ou varier par zone et dans le temps (§2.3).

| Paramètre | Unité | Exemple |
|---|---|---|
| `water_per_capita` (dotation domestique) | l/hab/j | 20 en rural, comme dans les classeurs actuels |
| `non_domestic_share` (besoins non domestiques : écoles, santé, commerces, administrations) | % de la consommation domestique, ou volume fixe par zone (m³/j) | 10 % |
| `network_efficiency` (rendement du réseau) | % | 75 % |
| `peak_day_factor` (coefficient de pointe journalière) | — | 1,3 |
| `peak_hour_factor` (coefficient de pointe horaire) | — | 1,8 |

Formules proposées (à valider), pour chaque maille et chaque année de sortie :
- consommation domestique : Q_dom = population × dotation / 1 000 (m³/j) ;
- consommation totale moyenne : Q_moy = Q_dom + besoins non domestiques ;
- production moyenne : Q_prod = Q_moy / rendement ;
- production du jour de pointe : Q_jp = Q_prod × coefficient de pointe journalière ;
- débit de l'heure de pointe en distribution : Q_hp = Q_moy × coefficient de pointe journalière × coefficient de pointe horaire / 24 (m³/h).

**Rendement du réseau (X2, validé)** : il s'applique à la **demande journalière**, moyenne et de pointe (Q_prod, Q_jp), et pas au débit de l'heure de pointe en distribution (Q_hp).

Des **tableaux de synthèse** sont produits pour chaque unité administrative et chaque année de sortie : population, densité, population non relocalisée, indicateurs.

## 9. Invariants vérifiés par les tests

| # | Invariant |
|---|---|
| I1 | Après migration : Σ P = Σ P avant migration − non relocalisés + placés en couronne, à 10⁻⁶ près en valeur relative |
| I2 | Après convergence, aucune maille éligible ne dépasse sa capacité de `tolerance` (1 habitant) ou plus |
| I3 | Une maille sans migration ne reçoit rien. Sa population après migration vaut exactement `P0_i` (c1) |
| I4 | Mêmes entrées, même résultat (déterminisme) |
| I5 | À taux constant, la croissance calculée en N pas de Δ ou en un pas de N × Δ donne le même facteur, à 10⁻⁹ près. À taux variable, l'écart reste inférieur à 10⁻⁴ en valeur relative |
| I6 | Σ des populations entières publiées = `round(Σ P_i)` |
| I7 | Aucune valeur négative, aucun NaN dans les sorties |

## 10. Choix tranchés (29/09/2026)

| # | Question | Décision |
|---|---|---|
| S1 | À quelle classe appartient une maille coupée par une limite de typologie ? | La maille est **découpée en sous-polygones**. Chaque partie est une unité avec sa propre classe (§3) |
| S2 | Quand une maille est-elle « sans migration » ? | Même principe : la partie située en zone sans migration forme sa propre unité (§3) |
| S3 | Quelle position retenir pour mesurer les distances ? | Le **centroïde** de l'unité |
| S4 | Comment appliquer un taux qui varie pendant un pas ? | Le **taux moyen** sur le pas (§5.1) |
| S5 | Quels paramètres pour la couronne de mailles puits ? | `sink_width` = 4 mailles et `sink_dmax` = `dmax` de la classe la moins dense, par défaut (accepté) |
| S6 | Le pas de temps influence la migration | L'utilisateur choisit `migration_frequency` : `annual` (qualité) ou `time_step` (rapidité). Un premier run grossier, en temps et en espace, puis un run affiné est un usage prévu. Le rapport indique toujours la résolution utilisée et ses limites |
| S7 | Faut-il migrer dès le premier pas ? | Ce choix revient à l'utilisateur, avec le paramètre `first_migration_year`. Il dépend des dates des données sources (par exemple toits de 2023 et population de 2024) |

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
- **Calcul** : taux moyen r̄ = r(2028,5) = 2,82143 %.
- **Attendu** : facteur = 1,0282143⁵ = 1,1492597, donc **P = 1 149,2597**.
- **Contrôle de sensibilité** : 5 pas d'un an donnent 1 149,2569, soit un écart relatif de 2,4·10⁻⁶ (I5).

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

### T13 – Maille découpée entre deux classes (S1)
- **Entrée** : une maille de 1 km² de densité de base uniforme 800, coupée par une limite de typologie :
  - partie rurale de 0,75 km², avec `dmax` = 1 000 ;
  - partie urbaine de 0,25 km², avec `dmax` = 4 000.
- **Découpage attendu** : 2 unités.
  - Unité rurale : `P0` = 600, `C` = 750.
  - Unité urbaine : `P0` = 200, `C` = 1 000.
  - Capacité totale de la maille : 1 750, contre 1 000 (= 1 km² × `dmax` rural) si la maille entière était classée rurale.
- **Sortie raster** : population 800, densité 800.

### T14 – Premier pas sans migration (S7)
- **Entrée** : T7 avec `base_year` = 2024, `first_migration_year` = 2026 et des pas de 1 an.
- **Attendu** :
  - en 2025 (croissance seule), `P` = [11, 0] ;
  - en 2026, croissance puis migration : la maille 0 passe à 12,1 ; sa capacité est 10, donc elle exporte 2,1. Résultat : `P` = [**10 ; 2,1**], total 12,1.

---

## 12. Données de référence

| Référence | Usage |
|---|---|
| `reference_outputs/muramvya/p2023_entree` | Comparaison chiffrée de la préparation (densité par maille, `Pmax` par classe). Tolérances : 1 % sur la population par maille et 0,5 % sur le total, pour tenir compte de F19 (surface arrondie dans la référence) |
| `reference_outputs/muramvya/pentree_final` | Référence qualitative (état des lieux §10.5). On relance le moteur avec les taux par période du §10.3, puis on compare les totaux, l'absence de dépassement et la répartition urbain/rural. Les écarts dus à RF3 et F19 sont attendus et documentés |

---

## 13. Intégration dans QGIS (phase 5, aperçu)

Le moteur est livré sous forme de **plugin QGIS**, compatible avec QGIS 3.40 LTR et QGIS 4.

**Installation.** Le plugin tient dans un fichier zip, qu'on installe depuis le menu *Extensions → Installer depuis un ZIP*. Il peut aussi être publié sur un dépôt de plugins interne.

**Barre d'outils et menu « Population »**

| Bouton | Contenu |
|---|---|
| **Scénario** | Créer, ouvrir ou enregistrer un scénario (fichier JSON). Régler les années, le pas de temps, la fréquence de migration, la taille de maille et l'unité de densité |
| **Données** | Choisir les couches d'entrée dans le projet ou sur disque : bâtiments (dont Google Open Buildings), raster de population, zone d'étude, typologie, zones sans migration, strates de calage |
| **Paramètres** | Taux de croissance et densités max, par classe, par zone et par année charnière, avec un aperçu des valeurs interpolées |
| **Calage** | Régressions par strate : courbes, diagnostics, ajustement manuel (§3 ter) |
| **Lancer** | Calcul en tâche de fond, avec barre de progression, journal et possibilité d'annuler. En cas de non-convergence, une fenêtre propose les solutions (§7) |
| **Résultats** | Chargement des rasters produits dans le projet, avec des styles prêts à l'emploi, et choix de l'année affichée |
| **Rapport** | Affichage du rapport d'exécution : statut, bilans, avertissements |

**Algorithmes Processing.** Les mêmes fonctions sont disponibles dans la boîte à outils de traitement de QGIS, pour les traitements par lots et le Model Builder.

**Hors QGIS.** Le moteur fonctionne aussi en ligne de commande, à partir d'un fichier de scénario. C'est utile pour les tests et les longs calculs.

Une maquette des fenêtres sera proposée pour validation avant de développer la phase 5.

---

## 14. Documentation de l'outil (exigence du 29/09/2026)

La documentation fait partie du livrable. Elle doit être accessible **depuis QGIS**, sans connaître le code. Elle comprend deux niveaux.

### 14.1 Fiche « À propos »

Elle répond à trois questions : qui a créé l'outil, comment, et pourquoi. Elle est accessible depuis le menu du plugin et depuis le gestionnaire d'extensions de QGIS (champs `about`, `homepage` et `tracker` du fichier `metadata.txt`).

Contenu :
- objet de l'outil et contexte (projet BUR71, outil générique SHER) ;
- auteurs et contributeurs, historique (outil PyQGIS d'origine, refonte en 2026) ;
- méthode de développement : développement assisté par IA, validé par des tests et des comparaisons avec l'outil d'origine ;
- version, date, licence, contact ;
- dépendances : aucune en dehors de QGIS.

### 14.2 Aide détaillée

| Élément | Contenu |
|---|---|
| **Infobulles** | Chaque bouton, champ et paramètre affiche une bulle d'aide au survol de la souris : à quoi il sert, son unité, sa valeur par défaut et un exemple |
| **Bouton « ? »** dans chaque fenêtre | Il ouvre directement la page d'aide de cette fenêtre |
| **Menu Aide navigable** | Pages HTML fournies avec le plugin, qui fonctionnent donc hors ligne. Elles s'ouvrent dans une fenêtre de QGIS, avec un sommaire, des liens entre pages et une recherche |
| **Aide des algorithmes Processing** | Texte d'aide affiché dans le panneau de droite de chaque algorithme de la boîte à outils de traitement |

**Pages du menu Aide** :
1. prise en main : un premier calcul pas à pas sur un jeu d'exemple ;
2. données d'entrée : formats attendus et exemples ;
3. paramètres et scénario ;
4. calage bâti → population ;
5. croissance, plafonds et migration : explication de la méthode, avec schémas ;
6. non-convergence : que faire ;
7. résultats, rapport et indicateurs (eau potable) ;
8. questions fréquentes et messages d'erreur ;
9. note méthodologique : formules et hypothèses.

**Source unique.** Les pages d'aide sont écrites en Markdown dans le dépôt (`docs/aide/`), puis converties en HTML lors de la construction du plugin. Les infobulles sont définies au même endroit que les paramètres, pour ne pas diverger du code.

**Langue** : français. Une version anglaise est possible plus tard, avec le système de traduction de QGIS.

**Planning** : la documentation est rédigée au fil des phases, pour chaque fonctionnalité livrée. Elle est intégrée au plugin en phase 5 et relue en phase 8.
