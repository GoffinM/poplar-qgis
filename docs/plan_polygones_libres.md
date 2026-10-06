# Plan : évolution des polygones dans le temps (mode « libre »)

| | |
|---|---|
| **Statut** | Version 2 du 06/10/2026 : plan validé dans ses grandes lignes, avec les corrections B1, B2 et S1 intégrées. **À valider avant tout code** |
| **Demande** | Chantier prioritaire du 06/10 : un polygone saturé déborde sur ses voisines, qui prennent son identité et toutes ses propriétés. La vitesse du front est un résultat, publié comme indicateur |
| **Références** | Fiche diagnostic §3.4 (extension urbaine) et §3.5 (strates dynamiques, ajoutée le 06/10 ; cohérence vérifiée au §13). La fiche fixe les principes ; **en cas d'écart, ce plan prévaut** (fiche §3.5). Plan précédent : `plan_categories_dynamiques.md`, que ce plan remplace pour le mode libre (§11) |
| **Décisions du 06/10** | B1 (nouveau déclencheur de colonisation), B2 (mailles coupées au front), S1 (double comptage, §4) ; P1, P2, P5 et P6 acceptés |
| **Durée estimée** | 8 à 10 jours pour le moteur et ses sorties (6 étapes), plus 1,5 jour pour l'interface |

## 1. Ce qui existe aujourd'hui (à respecter)

- La **grille** (250 m pour Muramvya) est découpée en **unités de calcul**. Une maille traversée par une limite (typologie, zones de paramètres, communes, exclusions) est coupée en morceaux, et chaque morceau est une unité. Tout le calcul se fait sur des tableaux par unité (`units.codes[couche]`).
- **Paramètres** : le TCAM, la densité maximale et les indicateurs sont lus par unité, selon la classe de typologie ou leurs propres couches, éventuellement croisées.
- **Migration** (`migration.py`) : chaque unité au-dessus de sa capacité envoie son excédent à parts égales vers ses k unités les plus proches qui ont au moins `tolerance` places libres (1 habitant par défaut), **sans limite de polygone**.
  - Une itération calcule tous les transferts à partir du même état, puis les applique.
  - Une receveuse trop remplie devient émettrice à l'itération suivante.
  - La population est conservée exactement : elle est seulement déplacée, jamais arrondie.
- **Capacité** (règle A4) : `C = surface × max(densité de départ, dmax)`. Une unité déjà surchargée au départ garde sa densité de départ comme plafond. Une maille rurale ne dépasse donc jamais sa dmax rurale : c'est ce qui a imposé le déclencheur B1.
- **Temps** : avec `migration_frequency = "annual"`, le moteur découpe déjà chaque pas en sous-pas d'un an.
- **Communes** : la couche administrative (`admin_units`) est déjà une couche fixe des unités (`codes["admin"]`). Elle sert aux statistiques et au recalage sur les projections.

Le mode libre se greffe sur cette base. Il ne la remplace pas.

## 2. Architecture

### 2.1 L'état : `polygon_id`

| Élément | Forme | Rôle |
|---|---|---|
| `polygon_id[unité]` | tableau int32, une valeur par unité de calcul | **Variable d'état**, mise à jour à chaque pas. C'est elle qui porte la vérité du calcul |
| Raster `polygon_id` | int32, une valeur par maille | Vue maille de l'état, selon la règle d'appartenance du §2.2. Il sert au voisinage, à la colonisation et aux sorties |
| Table `polygons` | une ligne par identifiant | `id`, `strate` (classe de typologie), `rang`, `colonizable`, `parent` (polygone d'origine), `annee_creation`. Le TCAM, la dmax et les paramètres de colonisation se lisent **par strate**, avec leurs séries dans le temps |
| `admin_zone` | les codes `admin` des unités, existants | **Fixe**. Ne bouge jamais. Sert aux statistiques, au recensement et au recalage |

- **Pourquoi un tableau par unité, et le raster en plus** : les mailles coupées par une limite ont plusieurs unités. Un raster par maille ne peut pas les représenter sans perte, et le mode figé doit rester identique au chiffre près. Le raster est **dérivé** de l'état, et non l'inverse. Pour les mailles entières, c'est-à-dire la très grande majorité, les deux sont strictement équivalents.
- **Héritage** : coloniser une unité, c'est **changer son `polygon_id`**. Au pas suivant, son TCAM, sa dmax et ses paramètres de colonisation sont relus dans la table du nouveau polygone. Rien d'autre n'est à recopier.
- **Identifiant initial** (P2, accepté) : un identifiant par **partie connexe** de chaque entité de la typologie. À Muramvya, l'entité « Urbain1 » est un multipolygone en deux parties, donc deux polygones distincts qui croissent et se suivent séparément.

### 2.2 Mailles coupées (B2)

**(a) Appartenance d'une maille à un polygone**, pour le comptage des voisins et pour le raster `polygon_id` :
- une maille appartient au polygone P si les unités de P couvrent au moins **`cell_membership_share`** (50 % par défaut, paramétrable) de la surface de la maille comprise dans la zone d'étude ;
- les morceaux en zone d'exclusion comptent dans cette surface, avec l'identifiant de leur strate ;
- une maille où aucun polygone n'atteint ce seuil (par exemple 40/30/30) n'appartient à **aucun** polygone. Elle ne compte comme voisine pour personne, et elle reçoit la valeur « sans polygone majoritaire » dans le raster.

**(b) Colonisation d'une maille** : **toutes ses unités de rang inférieur au colonisateur et colonisables** changent d'identifiant.
- Les morceaux en zone d'exclusion ne bougent pas, ni ceux de rang supérieur ou égal, ni ceux d'une strate non colonisable.
- Les codes `admin` (commune) ne bougent jamais.

**(c) Maille déjà majoritairement dans le colonisateur** (proposition, point P13) : elle peut garder un résidu de rang inférieur, par exemple 30 % de rural dans une maille à 70 % urbaine. Ce résidu est colonisable sans condition de voisinage, puisque la maille appartient déjà au colonisateur. Les conditions B1 de saturation et de flux s'appliquent, elles, au résidu.

### 2.3 L'option de scénario

`strata.mode = "planned"` (par défaut) ou `"free"`.

- **`planned`** (strates figées) : `polygon_id` ne bouge pas, et le code suit exactement le chemin actuel. Les résultats sont garantis inchangés : le banc de non-régression et les sorties de `reference_outputs/` sont comparés avant chaque commit.
- **`free`** : la colonisation est activée, et le calcul interne est **annuel**, quel que soit le pas des sorties (P1, accepté).

## 3. Ordre des opérations à chaque pas annuel

Tout est calculé à partir de l'état `t`. Les changements d'identifiant prennent effet à `t + 1`.

**a. Croissance.** `P ← P × (1 + tcam)`, avec le TCAM du polygone de chaque unité à l'état `t`. C'est le code actuel ; seule change la façon de lire le TCAM.

**a bis. Recalage par commune**, s'il est activé (`projections.recalibrate`). Il est inchangé : chaque commune est ramenée à son total projeté (§4).

**b. Migration.** Même algorithme qu'aujourd'hui. On y ajoute le **suivi des flux**, sans effet sur les résultats : pour chaque unité receveuse, la population **reçue** pendant le pas de chaque polygone émetteur, toutes itérations confondues.
- L'émetteur est l'**émetteur direct**, avec l'identifiant qu'il a à l'état `t` (P5, accepté). Une receveuse rurale qui déborde à son tour transmet sous son propre identifiant rural.
- Conséquence voulue : une maille de deuxième couronne ne reçoit que des migrants « ruraux », tant que la première couronne n'a pas été colonisée. Le front avance donc couronne par couronne, aussi par la logique des flux.

**c. Colonisation (B1).** Définition commune, sans nouveau paramètre : une unité est **à capacité** si sa place libre est inférieure à la tolérance de la migration (`C − P < tolerance`), c'est-à-dire si elle ne peut plus rien recevoir.

1. **Candidates** : pour chaque polygone P, les mailles voisines de P (8 voisins, appartenance au sens du §2.2a) qui contiennent des unités de rang inférieur à P et colonisables. On y ajoute les résidus du §2.2c.
2. **Conditions**, toutes requises, évaluées après la migration du pas :
   1. **La maille est saturée** : toutes ses unités candidates sont à capacité, c'est-à-dire à leur propre capacité, celle de leur strate actuelle.
   2. **Elle a reçu du colonisateur un flux suffisant** : la somme reçue de P par ses unités candidates pendant le pas atteint au moins **`colonization_min_inflow`**. Ce seuil se donne en habitants, ou en part de la capacité des unités candidates.
   3. **Le colonisateur est lui-même saturé** : la part de sa surface habitable à capacité atteint au moins **`saturation_share`**. On compte la part de **surface**, et non le nombre d'unités, pour que les petits morceaux ne pèsent pas autant que les mailles entières. Les morceaux en zone d'exclusion n'entrent pas dans ce calcul.
   4. **Contiguïté** : au moins **`min_neighbors`** voisines (3 sur 8 par défaut) appartiennent à P **à l'état `t`**.
   5. **Rang et protection** : P est de rang strictement supérieur ; l'unité n'est pas en zone d'exclusion, et sa strate est colonisable (P6, accepté).
3. **Une seule couronne par pas**, garantie par construction : les voisins sont comptés sur l'état `t`, donc une maille colonisée à ce pas ne compte pas encore comme voisine.
4. **Conflits** (plusieurs colonisateurs possibles) : le rang le plus élevé gagne, puis le polygone qui a envoyé le plus de migrants à la maille pendant ce pas, puis le plus petit identifiant (règle déterministe).
5. **Mémoire** : `annee_colonisation` de la maille et un événement « extension » dans la généalogie.

**Ce que produit cette règle.** Une maille colonisée, saturée à 156 habitants (dmax rurale de Muramvya), prend au pas suivant la dmax urbaine : sa capacité monte à 625 habitants. Le polygone doit alors d'abord **remplir ses nouvelles mailles** avant de redevenir saturé (condition 3), et seulement ensuite il peut avancer à nouveau. La vitesse du front naît ainsi de l'écart entre les densités et du taux de croissance, sans paramètre de vitesse, comme demandé.

**d. Contrôle de conservation**, à chaque pas et dans les deux modes : `P_après_migration + non_accueillis_du_pas + variation_du_puits = P_après_croissance_et_recalage`, à 1e-6 près en relatif. En cas d'écart, le calcul s'arrête avec un message qui nomme l'année. Ce n'est qu'un contrôle : il ne change aucun résultat.

> **Plafond structurel** (P4) : une couronne par pas annuel, avec des mailles de 250 m, plafonne la vitesse du front à 250 m/an, un peu moins en diagonale. Avec B1, ce plafond ne sera atteint que par un polygone qui remplit ses nouvelles mailles en moins d'un an.

## 4. Croissance, migration, recalage : pas de double comptage (S1)

**Dans le moteur, aucune personne n'est comptée deux fois :**
- la **migration** ne fait que déplacer : elle ne crée ni ne supprime personne (contrôle d), et la somme est la même avant et après ;
- le **TCAM** s'applique une seule fois par pas, à la population présente dans chaque unité au début du pas (étape a). Les migrants arrivés pendant le pas `t` croissent à partir de `t + 1`, au taux de l'unité où ils se trouvent ;
- la **colonisation** ne déplace personne : elle change seulement l'identifiant, donc les paramètres du pas suivant.

**Le vrai risque : l'effet de reclassement.** Un TCAM urbain plus élevé que le TCAM rural contient souvent l'exode rural, c'est-à-dire des ruraux qui partent en ville. Quand une maille rurale devient urbaine, ses habitants, qui étaient ruraux, croissent ensuite au taux urbain. Si rien ne vient compenser :
- la population totale augmente de `Σ P_colonisées × (tcam_urbain − tcam_rural)` chaque année, au-delà de la projection ;
- l'exode rural est alors compté deux fois : une fois dans le TCAM urbain, qui s'applique à plus de monde, et une fois de trop parce que les mailles rurales restantes ne perdent pas ces habitants.

**Le rôle du recalage par commune.** Avec `projections.recalibrate`, chaque commune est ramenée à son total projeté juste après la croissance (étape a bis).
- L'effet de reclassement ne change alors plus les **totaux**, mais seulement la **répartition** à l'intérieur de la commune : les mailles urbaines y pèsent un peu plus. Le total par commune est exact par construction.
- Le recalage multiplie toutes les unités de la commune par le même facteur. Une maille saturée peut alors repasser au-dessus de sa capacité ; la migration du même pas s'en charge, comme aujourd'hui.
- Un polygone qui déborde sur une autre commune : ses nouvelles mailles restent dans leur commune (`admin_zone` fixe), et elles sont recalées avec elle.

**Ce que je propose :**
1. **Indicateur « effet de reclassement »** (§6), par commune et par horizon, en habitants et en % : ce que le changement de TCAM a ajouté par rapport à un TCAM inchangé. Il est publié même avec le recalage, pour montrer ce que le recalage a corrigé.
2. **Avertissement** en mode libre si les TCAM diffèrent entre les strates et qu'aucun recalage n'est activé : « les totaux peuvent s'écarter des projections par effet de reclassement ».
3. **Pour éviter l'effet à la source**, une autre voie existe : lier le TCAM aux communes (couche fixe) plutôt qu'aux strates. La croissance reste alors attachée au lieu (P3), et seule la dmax suit le polygone. À Muramvya, le TCAM est le même partout (`*`), donc l'effet est nul.

## 5. Sorties (aux années de sortie seulement)

| Sortie | Contenu |
|---|---|
| `polygon_id_AAAA.tif` | int32, identifiant de chaque maille selon la règle d'appartenance (§2.2a) ; « sans polygone majoritaire » = valeur à part. Il est accompagné d'une table de légende (id → strate, rang) et d'un style QGIS |
| `statut_AAAA.tif` (proposé, fiche §3.4) | uint8, dérivé de `polygon_id` et de la généalogie : 0 non urbain, 1 urbain dès l'état initial, 2 extension, 3 nouveau noyau, 9 exclusion. « Urbain » = rang au moins égal à un rang choisi (fiche Q8). La fiche fait du §3.4 le cas simple du mécanisme du §3.5 |
| `annee_colonisation.tif` | int16 : année où la maille, ou son résidu, a changé de polygone. Vide si jamais ; 0 pour l'état initial. Un seul raster suffit pour animer toute la série |
| `polygones.gpkg`, couche `polygones` | Une entité par polygone et par année de sortie. Attributs : `id` conservé, `strate`, `rang`, `parent`, `annee`, `surface_km2`, `population`, `densite_moyenne`, `part_saturee`. Géométrie vectorisée à partir du raster, puis **lissée pour l'affichage seulement** (lissage de Chaikin, sans toucher aux sommets partagés). La surface et la population viennent des **unités**, jamais du contour lissé |
| `polygones.gpkg`, table `genealogie` | `id`, `annee`, `evenement` (`initial`, `extension`, `nouveau_noyau`, `contact`), `parent`, `mailles`, `population` |
| `polygones.gpkg`, couche `extensions` | Pour chaque polygone et chaque intervalle entre deux sorties, la surface gagnée : les nouveaux polygones urbains à superposer aux réseaux |
| `plausibilite.csv`, avec une section du rapport HTML | Indicateurs du §6, par polygone et par horizon |
| `mailles.gpkg` | Champs `poly_AAAA` et `an_colon` en plus |
| `summary.csv` | Inchangé. Toujours par commune, la couche fixe |

## 6. Indicateurs de plausibilité (par polygone et par horizon)

| Indicateur | Définition proposée | Lecture |
|---|---|---|
| **Vitesse moyenne du front** (m/an) | `ΔS / (P̄ × Δt)` : surface gagnée ÷ périmètre moyen sur l'intervalle (périmètre du contour en mailles) ÷ durée. On donne aussi la variation du rayon équivalent `Δ√(S/π) / Δt` | À comparer au plafond de 250 m/an et aux vitesses observées sur images. Front « bridé » s'il atteint le plafond plusieurs années de suite |
| **Étalement ou densification** | Élasticité `(ΔS/S) / (ΔP/P)` ; plus de 1 : étalement, moins de 1 : densification | Repère : l'étalement urbain en Afrique subsaharienne se situe souvent entre 1 et 2 |
| **Distribution des densités** | Quantiles 10, 50 et 90 des densités des mailles du polygone, et part saturée (condition B1-3) | Un polygone tout entier saturé signale une pression qui ne trouve pas de débouché |
| **Compacité** | Indice de Polsby-Popper `4πS / P²`, calculé sur le contour lissé pour limiter le biais des marches d'escalier | Une baisse forte signale des « doigts » d'extension, dus par exemple à des exclusions |
| **Nouveaux noyaux** | Nombre et population, avec leur diagnostic (part de migration redirigée, taille d'enclave ; décision Q3 du 30/09) | Un noyau « à vérifier » vient peut-être d'une contrainte artificielle |
| **Population non accueillie** | Cumul `unallocated` du polygone et de sa zone | Ce qui ne trouve pas de place |
| **Effet de reclassement** (S1) | Par commune : population ajoutée par le changement de TCAM des mailles colonisées, avant recalage | Proche de 0 : pas de double comptage ; sinon, à corriger par le recalage ou par un TCAM lié aux communes |
| **Bilan de masse** | `P_fin = P_début + croissance ± migrations nettes − non accueillis`, avec l'écart, qui doit être nul | Contrôle |

## 7. Fichiers touchés

**Nouveaux modules** (le moteur reste sans `qgis`) :

| Fichier | Contenu |
|---|---|
| `src/engine/polygons.py` | `PolygonTable` (propriétés par id), `initial_polygons(units)` (identifiants par partie connexe), `cell_membership(units, polygon_id, share)` (§2.2a), `saturated(...)` (définition commune), `colonise(...)` (règles du §3c, conflits, événements) |
| `src/engine/polygon_outputs.py` | Rasters `polygon_id` et `annee_colonisation`, vectorisation et lissage (GDAL Polygonize et numpy), généalogie, extensions |
| `src/engine/plausibility.py` | Indicateurs du §6, dont l'effet de reclassement |
| `tests/test_free_polygons.py` | Cas synthétiques du §8 |
| `tests/test_polygons.py` | Tests unitaires de `colonise` : chacune des conditions B1 prise seule, rang, exclusions, couronne unique, conflits, appartenance |

**Modifications du moteur existant :**

| Fichier | Modification | Effet en mode `planned` |
|---|---|---|
| `scenario.py` | Lecture et validation du bloc `strata` (§9) | Aucun |
| `simulation.py` | Dans la boucle, après la migration : colonisation, mise à jour de `polygon_id`, relecture des paramètres des seules unités changées. Contrôle de conservation ; effet de reclassement mesuré avant le recalage | Aucun résultat changé (contrôles passifs) |
| `parameters.py` | Valeur par unité d'après la strate courante : pour une unité colonisée, la clé « classe » devient celle de son nouveau polygone. Les autres couches liées (zones de service, communes) ne bougent pas (P3) | Aucun |
| `migration.py` | Option `track_sources` : flux reçus par receveur et par polygone émetteur, toutes itérations confondues | Aucun (option désactivée) |
| `timeline.py` | En mode `free` : sous-pas annuels imposés | Aucun |
| `outputs.py`, `grid_layer.py`, `html_report.py` | Nouvelles sorties et champs | Aucun |
| `locales/fr.json`, `en.json` | Messages | Aucun |

**Plugin** (étape 6, après validation d'une maquette) : dans l'onglet Paramètres, le choix « Strates figées / libres ». Le rang, la case « colonisable », le flux minimal et la part saturée se règlent par strate dans le tableau des densités, lié à la typologie ; `min_neighbors` et `cell_membership_share` sont des réglages généraux. Il faut aussi charger les nouvelles sorties.

## 8. Cas tests synthétiques (écrits en premier, en pytest)

Les mondes sont construits en mémoire, sans raster ni fichier, comme les tests actuels. La migration garde ses réglages par défaut (k = 3, tolérance de 1 habitant).

### 8.1 Ville carrée, rural et exclusion

**Le monde** : une grille de 21 × 21 mailles de 250 m (0,0625 km² par maille).

| Élément | Position | Paramètres |
|---|---|---|
| Ville « U » (rang 2) | Carré central de 3 × 3 mailles | dmax 10 000 hab/km², soit 625 habitants par maille ; **saturée au départ** ; TCAM 5 % |
| Rural « R » (rang 1) | Tout le reste | dmax 2 500 hab/km², soit 156,25 habitants par maille ; **2 400 hab/km² au départ** (150 habitants, donc 6,25 places libres) ; TCAM 0 % |
| Exclusion (sans arrivée) | Bande de 2 colonnes collée au bord est de la ville, sur 7 lignes | — |
| Colonisation | — | `colonization_min_inflow` = 10 % de la capacité (15,6 habitants) ; `saturation_share` = 0,8 ; `min_neighbors` = 3 |

**Résultats attendus**, à vérifier dans le test :
1. **Année 1** : chaque maille de U envoie 31,25 habitants, en trois parts de 10,4 vers ses trois receveuses les plus proches. Chiffres vérifiés le 06/10 avec la fonction de migration actuelle :

   | Maille | Reçu de U | Saturée | Voisines dans U | Résultat |
   |---|---|---|---|---|
   | Mi-côté nord | 41,7 | oui | 3 | **passe dans U** |
   | Mi-côtés sud et ouest | 31,3 | oui | 3 | **passent dans U** |
   | Mi-côté est | 0 (zone d'exclusion) | — | 3 | reste hors de U |
   | Jouxtant un angle | 20,8 à 31,3 | oui | 2 | reste rurale (condition 4) |
   | Coin en diagonale nord-ouest | 10,4 | oui | 1 | reste rurale (conditions 2 et 4) |

   Après la migration, U est saturée à 100 % (condition 3), et la population totale est exacte.
2. **Année 2, pause du front** : U compte maintenant 12 mailles, dont 3 nouvelles à environ 156 habitants pour une capacité de 625. Sa part saturée est de 9/12, soit 75 %, sous les 80 % exigés : **aucune colonisation**. Le front reprend quand les nouvelles mailles sont remplies, ce qui doit prendre environ 5 ans. C'est la vitesse « qui résulte de la densité et du taux de croissance ».
3. **Une couronne par an** : aucune maille ne passe dans U si elle n'était pas voisine de U à l'état `t`.
4. **L'exclusion n'est jamais colonisée** : U la contourne.
5. **Le rural ne colonise jamais U** (rang inférieur).
6. **Héritage** : une maille colonisée a, l'année suivante, le TCAM et la dmax de U. Sa capacité passe de 156,25 à 625 habitants.
7. **Conservation** : le total est exact chaque année. Avec un TCAM rural nul et sans recalage, `total(t) = total(t−1) + croissance de U`.
8. **Conflit** : avec une seconde ville « V » de même rang, une maille qui reçoit des deux villes va à celle qui lui a envoyé le plus de migrants. Avec un rang plus élevé pour V, elle va à V.
9. **Chaque condition B1 seule** : on la rend fausse une à une (`saturation_share` = 1,0 avec une maille non pleine, flux minimal à 100 % de la capacité, etc.). La colonisation de l'année 1 disparaît à chaque fois.
10. **Front** : la vitesse publiée est positive et au plus 250 m/an. La forme n'est **pas** exactement symétrique : voir P16.
11. **Mode `planned` sur le même monde** : `polygon_id` ne bouge pas, et les populations sont identiques à celles du moteur actuel.

### 8.2 Limite de polygone en biais (B2)

**Le monde** : une grille de 12 × 12 mailles.
- La ville U occupe le demi-plan au-dessus d'une droite à 45° décalée d'une fraction de maille. Toutes les mailles traversées sont donc coupées en deux morceaux, de parts connues (par exemple 87,5 % et 12,5 %).
- Une **zone d'exclusion** en biais coupe aussi quelques mailles du front.
- Une **limite de commune** (`admin`) oblique traverse le front.

**Résultats attendus :**
1. **Appartenance** : une maille à 87,5 % dans U compte comme voisine de U ; une maille à 12,5 % ne compte pas. Avec `cell_membership_share` = 0,9, la première ne compte plus.
2. **Colonisation d'une maille coupée** : son morceau rural change d'identifiant, son morceau en zone d'exclusion ne change pas, et ses codes de commune restent identiques.
3. **Résidu (§2.2c)** : le morceau rural de 12,5 % d'une maille à 87,5 % dans U est colonisé dès qu'il est saturé et qu'il a reçu assez de U, sans condition de voisinage.
4. **Raster** : `polygon_id` d'une maille coupée = le polygone majoritaire, ou « sans polygone majoritaire ».
5. **Conservation**, et totaux par commune identiques à la somme des unités de chaque commune.

**Non-régression** : le banc complet (`tools/banc.py` : raster → 2060, toits, classeurs) et `reference_outputs/` sont rejoués en mode `planned` à chaque étape. Ils doivent être identiques au chiffre près.

## 9. Paramètres ajoutés au scénario

```json
"strata": {
  "mode": "free",
  "min_neighbors": 3,
  "cell_membership_share": 0.5,
  "classes": {
    "Rural":   {"rank": 1},
    "Urbain2": {"rank": 2},
    "Urbain1": {"rank": 3},
    "Camp":    {"rank": 2, "colonizable": false}
  }
},
"parameters": {
  "colonization_min_inflow": {
    "zones": [{"source": "commune_muramvya.shp", "field": "Type"}],
    "values": {"Urbain1": {"share_of_capacity": 0.1}, "Urbain2": {"inhabitants": 20}}
  },
  "saturation_share": {
    "zones": [{"source": "commune_muramvya.shp", "field": "Type"}],
    "values": {"*": 0.8}
  }
}
```

- `mode` : `"planned"` (strates figées) par défaut. Un scénario existant ne change pas.
- `rank` : entier, plus grand = plus urbain. À saisir pour chaque classe en mode libre ; une classe sans rang ne colonise pas et n'est pas colonisée.
- `colonizable` : `true` par défaut ; `false` pour un camp ou une zone protégée.
- `colonization_min_inflow` : un paramètre du **colonisateur**, lu par strate et variable dans le temps, comme la dmax. Il se donne en habitants (`inhabitants`) ou en part de la capacité des unités candidates (`share_of_capacity`). Proposition par défaut : 10 % de la capacité, à caler sur Muramvya.
- `saturation_share` : part de la surface habitable du colonisateur à capacité, de 0 à 1. Paramètre du colonisateur, 0,8 par défaut, à caler sur Muramvya.
- `min_neighbors` : de 1 à 8, 3 par défaut.
- `cell_membership_share` : de 0,5 à 1, 0,5 par défaut. En dessous de 0,5, une maille pourrait appartenir à deux polygones à la fois.
- « À capacité » utilise la tolérance de la migration déjà présente (`migration.tolerance`) : aucun paramètre de plus.

## 10. Points de logique métier

**Tranchés :**

| # | Décision |
|---|---|
| P1 | Le pas de calcul interne est annuel, imposé en mode libre |
| P2 | Un polygone par partie connexe |
| P5 | Les migrants comptent pour l'émetteur direct, avec son identifiant à l'état `t` |
| P6 | Propriété `colonizable: false` par strate, en plus des exclusions |
| P7 | Remplacé par B1 : il n'y a plus de seuil de densité, mais saturation, flux et saturation du colonisateur |
| P11 | Remplacé par B2 : appartenance à 50 % de surface, et colonisation des seules unités de rang inférieur et colonisables |
| P0 | **Réglé le 06/10** : la fiche §3.5 est dans le dépôt (commit 108266f), relue et cohérente avec ce plan (§13) |
| P15 | **Réglé par la fiche §3.5** : l'option garde les noms `planned` (Planifié, polygones figés) et `free` (Libre). Les fermetures de camp et autres changements datés s'appelleront « changements datés », pour ne pas confondre |

**Encore ouverts :**

| # | Point | Ma proposition |
|---|---|---|
| **P3** | « Toutes les propriétés » : un paramètre lié à **une autre couche** que la typologie (zone de desserte, commune) suit-il aussi le polygone ? | Non : seules les propriétés de la strate suivent le polygone. Ce qui vient d'une couche fixe reste attaché au lieu. C'est aussi la parade à l'effet de reclassement (§4) |
| **P4** | Plafond de 250 m/an, avec un front plus lent en diagonale | Accepter, publier le plafond, signaler un front « bridé » |
| **P8** | **Nouveaux noyaux** : avec au moins 3 voisins exigés, la colonisation ne crée jamais de noyau isolé. Pourtant la généalogie prévoit l'événement, et vous les avez acceptés le 30/09 | Une règle à part, désactivée par défaut : un amas d'au moins `n` mailles contiguës, toutes saturées et éloignées de tout polygone de rang supérieur, crée un **nouveau polygone** de la strate choisie. Il reçoit le diagnostic « à vérifier » quand une contrainte artificielle peut l'expliquer (enclave, migration bloquée) |
| **P9** | Deux polygones de même rang qui se touchent | Pas de fusion des identifiants ; événement « contact », informatif, dans la généalogie |
| **P10** | Recalage par commune en mode libre | Inchangé : après la croissance, avant la migration. Il neutralise l'effet de reclassement sur les totaux (§4) |
| **P12** | Règle A4 après colonisation | Une maille colonisée prend `max(densité de départ, dmax du colonisateur)` |
| **P13** | Résidu de rang inférieur dans une maille déjà majoritairement colonisée (§2.2c) | Colonisable sans condition de voisinage, mais avec les conditions de saturation et de flux |
| **P14** | Valeurs par défaut de `colonization_min_inflow` (10 % de la capacité) et de `saturation_share` (0,8) | À caler sur Muramvya (étape 5), avec le bilan des vitesses de front obtenues |
| **P17** | Nouveaux noyaux : la fiche §3.5 prévoit qu'ils reçoivent un nouvel identifiant et les compte parmi les indicateurs. Elle suppose donc que la règle P8 existe | Réaliser P8 dès la première version (étape 4). Reste à décider si elle est active par défaut ; je propose qu'elle soit désactivée par défaut et signalée dans le rapport |
| **P18** | Fiche Q10 : surface minimale de tache et niveau de lissage des polygones de sortie | Surface minimale paramétrable (par défaut, une maille, soit 0,0625 km²) pour l'affichage seulement ; lissage de Chaikin en 2 passes. Les chiffres restent ceux de la grille |
| **P19** | Fiche §3.5 : « maille de référence de 250 m ». Le scénario permet une autre taille de maille | En mode libre, avertir si la maille n'est pas de 250 m : le plafond de vitesse (250 m/an) et la règle des 3 voisins en dépendent |
| **P16** | **Biais d'orientation de la migration** (constaté le 06/10 sur le cas test) : le moteur départage les receveuses à égale distance par le plus petit indice (spec §6.3, déterministe). Le nord et l'ouest sont donc favorisés : la mi-côté nord reçoit 41,7 habitants, la sud 31,3. C'est sans effet visible aujourd'hui, mais avec la colonisation, ce biais peut orienter la croissance des fronts. | Garder la règle en mode figé, pour ne rien changer. En mode libre, partager à parts égales entre les receveuses ex aequo, ce qui reste déterministe et rend le front symétrique |

## 11. Rapport avec le plan du 30/09 (`plan_categories_dynamiques.md`)

Ce plan **remplace le mode « Libre »** du plan du 30/09 :
- un déclencheur par saturation et par flux (B1) au lieu d'un seuil de densité ;
- 3 voisins par défaut au lieu de 1 ;
- une couronne par pas ;
- le rang strictement supérieur ;
- les conflits arbitrés par le rang puis par les migrants ;
- un état `polygon_id` au lieu d'une simple catégorie.

Les réponses du 30/09 restent valables : Q1 (évaluation par maille, précisée par B2), Q3 (nouveaux noyaux et leur diagnostic, voir P8), Q4 (pas de retour en arrière) et Q9 (généalogie dès la première version).

Les **changements datés** du plan du 30/09 (fermeture d'un camp, départ progressif du surplus) **restent à faire, en second temps**. Ils s'écriront sur la même architecture : à une date donnée, un changement de `polygon_id` ou des propriétés d'un polygone, avec un plafond qui descend en ligne droite.

## 12. Étapes

| # | Contenu | Tests | Durée |
|---|---|---|---|
| 1 | **Cas synthétiques en pytest** (§8.1 et §8.2), d'abord en échec ; `polygons.py` : identifiants initiaux, appartenance, saturation, `colonise` seul | Tests unitaires de `colonise`, une condition à la fois | 2 j |
| 2 | Suivi des flux dans la migration (`track_sources`) | Flux reçus = population déplacée ; résultats de la migration identiques avec ou sans suivi | 0,5 j |
| 3 | Branchement dans `simulation.py` : état, paramètres relus, conservation, effet de reclassement, sous-pas annuels ; bloc `strata` du scénario | Cas synthétiques verts ; banc identique en mode figé | 2 j |
| 4 | Sorties : rasters, vectorisation et lissage, généalogie, extensions, `mailles.gpkg` ; nouveaux noyaux (P8), si retenus | Contours fermés, identifiants conservés, surfaces égales à celles des unités | 1,5 j |
| 5 | Indicateurs de plausibilité, rapport HTML ; Muramvya en mode libre ; calage des valeurs par défaut (P14) et bilan | Bilan de masse nul ; vitesses ≤ 250 m/an ; effet de reclassement publié | 2 j |
| 6 | Interface du plugin (maquette d'abord), aide, version | Tests du plugin | 1,5 j |

Chaque étape passe tous les tests, y compris le banc en mode figé, avant la suivante.

## 13. Cohérence avec la fiche §3.5 (vérifiée le 06/10)

| Sujet de la fiche §3.5 | Dans ce plan | Accord |
|---|---|---|
| Deux modes, Planifié (par défaut, résultats identiques) et Libre | §2.3 : `planned` / `free`, banc de non-régression en mode figé | Oui |
| Excédent jamais perdu en silence, population non accueillie par horizon | Politiques existantes (`stop` arrête avec un diagnostic, `unallocated` enregistre ce qui n'a pas trouvé de place) ; contrôle de conservation à chaque pas (§3d) | Oui |
| `polygon_id` par unité, héritage de toutes les propriétés | §2.1 | Oui. La fiche cite strate, TCAM, densité max et paramètres de colonisation : ce sont les propriétés de la strate (P3) |
| Couche communale séparée et fixe | §2.1, §4 | Oui |
| Hiérarchie, exclusions et strates non colonisables | §3c, conditions 4 et 5 | Oui |
| Déclencheur : saturation, flux, saturation du colonisateur, contiguïté | §3c (B1) | Oui |
| 250 m, une couronne par pas, pas interne annuel | §2.3, §3c | Oui ; avertissement ajouté si la maille n'est pas de 250 m (P19) |
| Vitesse du front comme résultat publié | §3c, §6 | Oui |
| Identité conservée, nouveaux noyaux avec un nouvel identifiant, généalogie | §2.1, §5 | Oui, à condition de réaliser la règle des nouveaux noyaux (P17) |
| Polygones lissés pour l'affichage seulement, grille comme référence | §5 | Oui |
| Indicateurs de plausibilité (sept indicateurs) | §6 : les sept, plus l'effet de reclassement (S1) | Oui |
| Fiche §4 : modules `strates.py` et `polygones.py` | §7 : `polygons.py`, `polygon_outputs.py` et `plausibility.py` (identifiants en anglais, règle de CLAUDE.md) | Écart de noms seulement ; le plan prévaut |
| Fiche §3.4 comme cas simple du §3.5 (raster de statut, année d'urbanisation) | §5 : `statut_AAAA.tif` dérivé (proposé) et `annee_colonisation.tif` | Oui, avec la sortie proposée |
| Fiche Q9 (strates, rangs, non colonisables), Q10 (lissage, surface minimale), Q11 (mode par défaut pour BUR71) | §9 (réglages par strate), P18 ; Q11 reste à trancher par vous | Questions reprises |

Une précision de S1 : la fiche dit que le TCAM est hérité. La parade « TCAM lié aux communes » (§4, point 3) reste un choix de l'utilisateur, au moment de régler ses paramètres. Le TCAM n'est alors plus une propriété de la strate : il reste attaché au lieu, et rien ne le fait voyager avec le polygone.

