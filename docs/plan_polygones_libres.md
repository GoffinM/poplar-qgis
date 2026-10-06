# Plan : évolution des polygones dans le temps (mode « libre »)

| | |
|---|---|
| **Statut** | Proposé le 06/10/2026, **à valider avant tout code** |
| **Demande** | Chantier prioritaire du 06/10 : un polygone saturé déborde sur ses voisines, qui prennent son identité et toutes ses propriétés. La vitesse du front est un résultat, publié comme indicateur |
| **Références** | Fiche diagnostic §3.4 (extension urbaine). La fiche du dépôt s'arrête au §3.4 : **la section 3.5 citée n'y figure pas** (voir §9, point P0). Plan précédent : `plan_categories_dynamiques.md`, que ce plan remplace pour le mode libre (§10) |
| **Durée estimée** | 7 à 9 jours pour le moteur et ses sorties (6 étapes), plus 1,5 jour pour l'interface |

## 1. Ce qui existe aujourd'hui (à respecter)

- La **grille** (250 m pour Muramvya) est découpée en **unités de calcul**. Une maille traversée par une limite (typologie, zones de paramètres, communes, exclusions) est coupée en morceaux, et chaque morceau est une unité. Tout le calcul se fait sur des tableaux par unité (`units.codes[couche]`).
- **Paramètres** : le TCAM, la densité maximale et les indicateurs sont lus par unité, selon la classe de typologie ou leurs propres couches, éventuellement croisées.
- **Migration** (`migration.py`) : chaque unité au-dessus de sa capacité envoie son excédent à parts égales vers ses k unités les plus proches qui ont de la place, **sans limite de polygone**. On itère jusqu'à convergence. La population est conservée exactement : elle est seulement déplacée, jamais arrondie.
- **Capacité** (règle A4) : `C = surface × max(densité de départ, dmax)`. Une unité déjà surchargée au départ garde sa densité de départ comme plafond.
- **Temps** : avec `migration_frequency = "annual"`, le moteur découpe déjà chaque pas en sous-pas d'un an.
- **Communes** : la couche administrative (`admin_units`) est déjà une couche fixe des unités (`codes["admin"]`). Elle sert aux statistiques et au recalage sur les projections.

Le mode libre se greffe sur cette base. Il ne la remplace pas.

## 2. Architecture proposée

### 2.1 L'état : `polygon_id`

| Élément | Forme | Rôle |
|---|---|---|
| `polygon_id[unité]` | tableau int32, une valeur par unité de calcul | **Variable d'état**, mise à jour à chaque pas. C'est elle qui porte la vérité du calcul |
| Raster `polygon_id` | int32, une valeur par maille | Vue maille de l'état : identifiant du morceau le plus grand de la maille. Il sert au voisinage, à la colonisation et aux sorties |
| Table `polygons` | une ligne par identifiant | `id`, `strate` (classe de typologie), `rang`, `colonisable`, `parent` (polygone d'origine), `annee_creation`. Le TCAM, la dmax et le seuil de colonisation se lisent **par strate**, avec leurs séries dans le temps |
| `admin_zone` | les codes `admin` des unités, existants | **Fixe**. Ne bouge jamais. Sert aux statistiques, au recensement et au recalage |

- **Pourquoi un tableau par unité, et le raster en plus** : les mailles coupées par une limite ont plusieurs unités. Un raster par maille ne peut pas les représenter sans perte, et le mode figé (« planned ») doit rester identique au chiffre près.
  - Le raster `polygon_id` est **dérivé** de l'état, et non l'inverse.
  - Pour les mailles entières, c'est-à-dire la très grande majorité, les deux sont strictement équivalents.
- **Héritage** : coloniser une unité, c'est **changer son `polygon_id`**. Au pas suivant, son TCAM, sa dmax et son seuil sont relus dans la table du nouveau polygone. Rien d'autre n'est à recopier.
- **Identifiant initial** : un identifiant par **partie connexe** de chaque entité de la couche de typologie. À Muramvya, l'entité « Urbain1 » est un multipolygone en deux parties, donc deux polygones distincts qui croissent et se suivent séparément (point P2).

### 2.2 L'option de scénario

`strata_mode = "planned"` (par défaut) ou `"free"`.

- **`planned`** : `polygon_id` est figé, et le code suit exactement le chemin actuel. Les résultats sont garantis inchangés : le banc de non-régression et les sorties de `reference_outputs/` sont comparés avant chaque commit.
- **`free`** : la colonisation est activée, et le calcul interne est **annuel**, quel que soit le pas des sorties (point P1).

## 3. Ordre des opérations à chaque pas annuel

Tout est calculé à partir de l'état `t`. Les changements d'identifiant prennent effet à `t + 1`.

**a. Croissance.** `P ← P × (1 + tcam)`, avec le TCAM du polygone de chaque unité à l'état `t`. C'est le code actuel ; seule change la façon de lire le TCAM.

**b. Migration.** Même algorithme qu'aujourd'hui : l'excédent au-delà de la capacité part vers les k unités les plus proches qui ont de la place, y compris hors du polygone. Deux ajouts, sans effet sur les résultats :
- le **suivi des flux** : pour chaque unité receveuse, la population reçue de chaque polygone émetteur. Il sert à l'arbitrage des conflits et au diagnostic des nouveaux noyaux ;
- l'**origine des migrants** : celui qui donne réellement. Une unité receveuse qui déborde à son tour transmet sous son propre identifiant (point P5).

**c. Colonisation**, sur le raster maille, en une seule passe vectorisée (`scipy.ndimage` et décalages de tableaux) :
1. **Candidates** : les mailles voisines d'au moins un polygone de rang supérieur au leur, sur les 8 voisins.
2. **Conditions**, toutes requises :
   - la **densité** de la maille (population ÷ surface habitable, toutes unités confondues) atteint le **seuil de colonisation du polygone colonisateur** ;
   - au moins **`min_neighbors`** de ses 8 voisines (3 par défaut) appartiennent à ce polygone, **à l'état `t`** ;
   - le colonisateur est de **rang strictement supérieur** ;
   - la maille n'est **pas une zone d'exclusion**, ni une strate marquée « non colonisable » (point P6).
3. **Une seule couronne par pas**, garantie par construction : les voisins sont comptés sur l'état `t`, donc une maille colonisée à ce pas ne compte pas encore comme voisine.
4. **Conflits** (plusieurs colonisateurs possibles) : le rang le plus élevé gagne, puis le polygone qui a envoyé le plus de migrants à la maille pendant ce pas, puis le plus petit identifiant (règle déterministe).
5. **Mailles coupées** : seules les unités de la maille qui ne sont ni exclues ni de rang supérieur ou égal changent d'identifiant.
6. **Mémoire** : `annee_colonisation` de la maille et un événement « extension » dans la généalogie.

**d. Contrôle de conservation**, à chaque pas et dans les deux modes : `P_après_migration + non_accueillis_du_pas + variation_du_puits = P_après_croissance`, à 1e-6 près en relatif. En cas d'écart, le calcul s'arrête avec un message qui nomme l'année. Ce n'est qu'un contrôle : il ne change aucun résultat.

> **Conséquence à connaître** (point P4) : une couronne par pas annuel, avec des mailles de 250 m, **plafonne la vitesse du front à 250 m/an**, et un peu moins en diagonale à cause de la règle des 3 voisins. La vitesse publiée reste un résultat, mais elle a ce plafond structurel.

## 4. Sorties (aux années de sortie seulement)

| Sortie | Contenu |
|---|---|
| `polygon_id_AAAA.tif` | int32, identifiant de chaque maille. Il est accompagné d'une table de légende (id → strate, rang) et d'un style QGIS |
| `annee_colonisation.tif` | int16 : année où la maille a changé de polygone. Vide si jamais ; 0 pour l'état initial. Un seul raster suffit pour animer toute la série |
| `polygones.gpkg`, couche `polygones` | Une entité par polygone et par année de sortie. Attributs : `id` conservé, `strate`, `rang`, `parent`, `annee`, `surface_km2`, `population`, `densite_moyenne`. Géométrie vectorisée à partir du raster, puis **lissée pour l'affichage seulement** (lissage de Chaikin, sans toucher aux sommets partagés). La grille reste la référence de tous les chiffres |
| `polygones.gpkg`, table `genealogie` | `id`, `annee`, `evenement` (`initial`, `extension`, `nouveau_noyau`), `parent`, `mailles`, `population` |
| `polygones.gpkg`, couche `extensions` | Pour chaque polygone et chaque intervalle entre deux sorties, la surface gagnée : les nouveaux polygones urbains à superposer aux réseaux |
| `plausibilite.csv`, avec une section du rapport HTML | Indicateurs du §5, par polygone et par horizon |
| `mailles.gpkg` | Champs `poly_AAAA` et `an_colon` en plus |
| `summary.csv` | Inchangé. Toujours par commune, la couche fixe |

## 5. Indicateurs de plausibilité (par polygone et par horizon)

| Indicateur | Définition proposée | Lecture |
|---|---|---|
| **Vitesse moyenne du front** (m/an) | `ΔS / (P̄ × Δt)` : surface gagnée ÷ périmètre moyen sur l'intervalle (périmètre du contour en mailles) ÷ durée. On donne aussi la variation du rayon équivalent `Δ√(S/π) / Δt` | À comparer au plafond de 250 m/an et aux vitesses observées sur images |
| **Étalement ou densification** | Élasticité `(ΔS/S) / (ΔP/P)` ; plus de 1 : étalement, moins de 1 : densification | Repère : l'étalement urbain en Afrique subsaharienne se situe souvent entre 1 et 2 |
| **Distribution des densités** | Quantiles 10, 50 et 90 des densités des mailles du polygone, et part des mailles à la dmax | Un polygone tout entier à la dmax signale une saturation forcée |
| **Compacité** | Indice de Polsby-Popper `4πS / P²`, calculé sur le contour lissé pour limiter le biais des marches d'escalier | Une baisse forte signale des « doigts » d'extension, dus par exemple à des exclusions |
| **Nouveaux noyaux** | Nombre et population, avec leur diagnostic (part de migration redirigée, taille d'enclave ; décision Q3 du 30/09) | Un noyau « à vérifier » vient peut-être d'une contrainte artificielle |
| **Population non accueillie** | Cumul `unallocated` du polygone et de sa zone | Ce qui ne trouve pas de place |
| **Bilan de masse** | `P_fin = P_début + croissance ± migrations nettes − non accueillis`, avec l'écart, qui doit être nul | Contrôle |

## 6. Fichiers touchés

**Nouveaux modules** (le moteur reste sans `qgis`) :

| Fichier | Contenu |
|---|---|
| `src/engine/polygons.py` | `PolygonTable` (propriétés par id), `initial_polygons(units)` (identifiants par partie connexe), `cell_ids(units, polygon_id)` (vue maille), `colonise(...)` (règles du §3c, conflits, événements) |
| `src/engine/polygon_outputs.py` | Rasters `polygon_id` et `annee_colonisation`, vectorisation et lissage (GDAL Polygonize et numpy), généalogie, extensions |
| `src/engine/plausibility.py` | Indicateurs du §5 |
| `tests/test_free_polygons.py` | Cas synthétique (§7) |
| `tests/test_polygons.py` | Tests unitaires de `colonise` : rang, voisins, exclusions, couronne unique, conflits |

**Modifications du moteur existant :**

| Fichier | Modification | Effet en mode `planned` |
|---|---|---|
| `scenario.py` | Lecture et validation du bloc `strata` (§8) | Aucun |
| `simulation.py` | Dans la boucle, après la migration : colonisation, mise à jour de `polygon_id`, relecture des paramètres des seules unités changées. Contrôle de conservation | Aucun résultat changé (le contrôle est passif) |
| `parameters.py` | Valeur par unité d'après la strate courante : pour une unité colonisée, la clé « classe » devient celle de son nouveau polygone. Les autres couches liées (zones de service…) ne bougent pas (point P3) | Aucun |
| `migration.py` | Option `track_sources` : flux reçus par receveur et par polygone émetteur | Aucun (option désactivée) |
| `timeline.py` | En mode `free` : sous-pas annuels imposés | Aucun |
| `outputs.py`, `grid_layer.py`, `html_report.py` | Nouvelles sorties et champs | Aucun |
| `locales/fr.json`, `en.json` | Messages | Aucun |

**Plugin** (étape 6, après validation d'une maquette) : dans l'onglet Paramètres, le choix « Strates figées / libres ». Les rangs, les seuils de colonisation, la case « non colonisable » et `min_neighbors` se règlent dans le tableau des densités, lié à la typologie. Il faut aussi charger les nouvelles sorties.

## 7. Cas test synthétique (écrit en premier, en pytest)

**Le monde** : une grille de 21 × 21 mailles de 250 m, sans raster ni fichier, construite en mémoire comme les tests actuels.

| Élément | Position | Paramètres |
|---|---|---|
| Ville « U » (rang 2) | Carré central de 3 × 3 mailles | dmax 10 000 hab/km², soit 625 habitants par maille ; **saturée au départ** ; TCAM 5 % ; seuil de colonisation 800 hab/km² (50 hab/maille), choisi pour être franchi dès l'année 1 par les mailles qui reçoivent des migrants |
| Rural « R » (rang 1) | Tout le reste | dmax 2 500 hab/km² (156 hab/maille) ; 500 hab/km² au départ ; TCAM 0 % |
| Exclusion (sans arrivée) | Bande de 2 mailles collée au bord est de la ville | — |

**Résultats attendus**, à vérifier dans le test :
1. **Année 1** : l'excédent de la ville (5 % de 9 × 625, soit 281 habitants) part vers les mailles rurales les plus proches. Plusieurs d'entre elles franchissent le seuil, mais seules les **3 mailles libres à mi-côté** (nord, sud, ouest) passent dans U, car ce sont les seules à avoir 3 voisines dans un carré 3 × 3. La mi-côté est est dans l'exclusion. Les mailles qui jouxtent un angle (2 voisines) reçoivent autant de migrants mais restent rurales : c'est la règle `min_neighbors` qui est testée là.
2. **Une couronne par an** : aucune maille ne passe dans U si elle n'était pas voisine de U à l'état `t`.
3. **L'exclusion n'est jamais colonisée** : U la contourne.
4. **Le rural ne colonise jamais U** (rang inférieur).
5. **Héritage** : une maille colonisée a, l'année suivante, le TCAM et la dmax de U. Sa capacité passe de 156 à 625 habitants.
6. **Conservation** : le total est exact chaque année. Avec un TCAM rural nul, `total(t) = total(0) + croissance de U`.
7. **Conflit** : avec une seconde ville « V » de même rang à égale distance d'une maille, la maille va à la ville qui lui a envoyé le plus de migrants. Avec un rang plus élevé pour V, elle va à V.
8. **Front** : la vitesse publiée est positive, au plus 250 m/an, et la forme reste symétrique nord-sud.
9. **Mode `planned` sur le même monde** : `polygon_id` ne bouge pas, et les populations sont identiques à celles du moteur actuel.

Les valeurs exactes de population, année par année, seront calculées à la main dans le test pour les deux premières années.

**Non-régression** : le banc complet (`tools/banc.py` : raster → 2060, toits, classeurs) et `reference_outputs/` sont rejoués en mode `planned` à chaque étape. Ils doivent être identiques au chiffre près.

## 8. Paramètres ajoutés au scénario

```json
"strata": {
  "mode": "free",
  "min_neighbors": 3,
  "classes": {
    "Rural":   {"rank": 1},
    "Urbain2": {"rank": 2},
    "Urbain1": {"rank": 3},
    "Camp":    {"rank": 2, "colonisable": false}
  }
},
"parameters": {
  "colonisation_threshold": {
    "zones": [{"source": "commune_muramvya.shp", "field": "Type"}],
    "values": {"Urbain1": {"share_of_dmax_of_target": 0.8}, "Urbain2": 1500}
  }
}
```

- `mode` : `"planned"` par défaut. Un scénario existant ne change pas.
- `rank` : entier, plus grand = plus urbain. À saisir pour chaque classe en mode libre ; une classe sans rang ne colonise pas et n'est pas colonisée.
- `colonisable` : `true` par défaut ; `false` pour un camp ou une zone protégée (décision du 30/09 : un camp n'est jamais une zone de débordement).
- `colonisation_threshold` : un paramètre comme les autres, par classe, variable dans le temps, dans l'unité de densité du scénario. On peut aussi le donner en part de la dmax de la classe colonisée (point P7).
- `min_neighbors` : de 1 à 8, 3 par défaut.

## 9. Points de logique métier à trancher

| # | Point | Ma proposition |
|---|---|---|
| **P0** | La section 3.5 de la fiche n'est pas dans le dépôt : la fiche s'arrête au §3.4. Existe-t-il une version plus récente à déposer dans `docs/` ? | La déposer avant l'étape 1, pour vérifier que ce plan la respecte |
| **P1** | « Pas de calcul interne ANNUEL » : je comprends que **le pas de calcul interne est annuel**, quel que soit le pas des sorties. C'est bien ça ? | Oui, imposé en mode libre. En mode figé, rien ne change (il est déjà annuel à Muramvya) |
| **P2** | Identité initiale : un polygone par **entité** de la typologie, ou par **partie connexe** ? À Muramvya, « Urbain1 » est une entité en deux morceaux | Par partie connexe : chaque tache a sa propre vitesse et sa propre généalogie |
| **P3** | « Toutes les propriétés » : un paramètre lié à **une autre couche** que la typologie (zone de desserte, croisement) doit-il aussi suivre le polygone ? | Non : seules les propriétés de la strate suivent le polygone. Ce qui vient d'une couche fixe (zones, communes) reste attaché au lieu. Sinon, une zone de desserte « voyagerait » avec la ville |
| **P4** | Plafond de vitesse : une couronne par an fait au plus 250 m/an, avec un front plus lent en diagonale (forme en losange ou en octogone) | Accepter, publier ce plafond, et le signaler quand un front l'atteint plusieurs années de suite (front « bridé ») |
| **P5** | « Celui qui a envoyé le plus de migrants » : seulement l'émetteur direct, ou l'origine première, après plusieurs rebonds dans la même itération de migration ? | L'émetteur direct, avec l'identifiant qu'il a à l'état `t` |
| **P6** | Le cahier des charges ne protège que les zones d'exclusion. Or le 30/09, vous avez décidé qu'un camp n'est jamais une zone de débordement | Une propriété `colonisable: false` par strate, en plus des exclusions |
| **P7** | Le seuil de colonisation est-il atteignable ? Une maille rurale ne dépasse pas la dmax rurale (2 500 hab/km² à Muramvya), à cause de sa capacité. Un seuil plus haut ne se déclencherait jamais | À la validation, refuser un seuil supérieur à la dmax de la classe colonisée, ou permettre de le saisir en part de cette dmax (par exemple 80 %) |
| **P8** | **Nouveaux noyaux** : avec au moins 3 voisins du colonisateur exigés, la colonisation ne peut jamais créer de noyau isolé. Or la généalogie prévoit l'événement « nouveau noyau » (et le 30/09, vous les avez acceptés) | Une règle à part, désactivée par défaut : une maille isolée qui dépasse le seuil de création d'une strate, avec au moins `n` mailles contiguës au-dessus de ce seuil, crée un **nouveau polygone**. Il reçoit un nouvel identifiant, la strate choisie et le diagnostic « à vérifier » si une contrainte artificielle peut l'expliquer |
| **P9** | Deux polygones de même rang qui se touchent : ils ne fusionnent pas, puisque ni l'un ni l'autre n'est de rang supérieur. Faut-il un événement « contact » ou « fusion » ? | Pas de fusion des identifiants : chaque polygone garde son id. On ajoute un événement « contact », informatif, dans la généalogie |
| **P10** | Recalage sur les projections (`projections.recalibrate`) : en mode libre, il continue de se faire par commune (`admin_zone` fixe), entre la croissance et la migration ? | Oui, inchangé : le recalage par commune est indépendant des polygones |
| **P11** | Densité testée pour une maille coupée par une exclusion ou une limite d'étude | Population de toutes les unités habitables de la maille ÷ leur surface. Les unités exclues ne comptent ni au numérateur ni au dénominateur |
| **P12** | Faut-il garder le calcul de la capacité A4 (plafond = densité de départ si elle dépasse la dmax) après colonisation ? | Oui : une maille colonisée prend `max(densité de départ, dmax du colonisateur)` |

## 10. Rapport avec le plan du 30/09 (`plan_categories_dynamiques.md`)

Ce plan **remplace le mode « Libre »** du plan du 30/09, avec les règles que vous avez imposées :
- 3 voisins par défaut au lieu de 1 ;
- une couronne par pas ;
- le rang strictement supérieur ;
- les conflits arbitrés par le rang puis par les migrants ;
- un état `polygon_id` au lieu d'une simple catégorie.

Les réponses du 30/09 restent valables : Q1 (évaluation par maille), Q3 (nouveaux noyaux et leur diagnostic, voir P8), Q4 (pas de retour en arrière) et Q9 (généalogie dès la première version).

Le mode **« Planifié »** du plan du 30/09 (fermeture d'un camp, départ progressif du surplus) **reste à faire, en second temps**. Il s'écrira naturellement sur la même architecture : à une date donnée, un changement de `polygon_id` ou des propriétés d'un polygone, avec un plafond qui descend en ligne droite. Le nom de l'option prête à confusion : `strata_mode = "planned"` désigne ici les strates **figées** (le comportement actuel), et non les changements planifiés. Je propose `"fixed"` | `"free"` pour l'option, et de garder « planifié » pour les changements datés. **À confirmer.**

## 11. Étapes

| # | Contenu | Tests | Durée |
|---|---|---|---|
| 1 | **Cas synthétique en pytest** (§7), d'abord en échec ; `polygons.py` : identifiants initiaux, vue maille, `colonise` seul | Tests unitaires de `colonise` | 1,5 j |
| 2 | Branchement dans `simulation.py` : état, paramètres relus, conservation, sous-pas annuels ; option `strata` du scénario | Cas synthétique vert ; banc identique en mode figé | 2 j |
| 3 | Suivi des flux dans la migration, conflits par migrants ; nouveaux noyaux (P8) | Conflit à égalité de rang ; noyau isolé | 1 j |
| 4 | Sorties : rasters, vectorisation et lissage, généalogie, extensions, `mailles.gpkg` | Contours fermés, id conservés, surfaces cohérentes avec la grille | 1,5 j |
| 5 | Indicateurs de plausibilité, rapport HTML ; Muramvya en mode libre, avec bilan | Bilan de masse nul ; vitesses ≤ 250 m/an | 1,5 j |
| 6 | Interface du plugin (maquette d'abord), aide, version | Tests du plugin | 1,5 j |

Chaque étape passe tous les tests, y compris le banc en mode figé, avant la suivante.
