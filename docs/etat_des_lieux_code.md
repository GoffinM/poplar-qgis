# BUR71 – État des lieux du code existant

| | |
|---|---|
| **Objet** | Analyse du code fourni (commune test de Muramvya), sans modification |
| **Référence** | `docs/BUR71_fiche_diagnostic_outil_SIG_population.md` |
| **Date** | 29/09/2026 |
| **Statut** | Analyse statique (lecture du code et inspection des données). Le code **n'a pas été exécuté** : les points marqués *« à confirmer à l'exécution »* restent des hypothèses |

---

## 1. Inventaire des fichiers fournis

Tous les fichiers sont dans `Donne_COMMUNE_MURAMVYA_BUR71/`.

| Fichier | Nature | Contenu |
|---|---|---|
| `Code/Modeleur de migration_Q 2.model3` | Modèle graphique QGIS (Model Builder), nom interne `ModèleMigration_V2`, groupe `CAM12` | **Préparation** : raster de densité → grille vectorielle de 250 m, densité et capacité (`Pmax`) par maille, exclusions, croissance 2023 → 2025 |
| `Code/CAM12_migration.py` | Algorithme Processing en Python (modèle exporté puis retouché à la main). En-tête : `Name: Migration`, `Group: NGA03`, QGIS 3.16. Classe `Zefze`, algorithme `OUG05_migration` | **Migration** itérative de l'excédent au-delà de `Pmax` |
| `Raster/POP2023 MURAMVYA.tif` | GeoTIFF float32, 109 × 98 pixels de **250 m**, EPSG:32735 (UTM 35S), nodata −3,4·10³⁸ | Densité de population 2023 en **hab/km²** (3 109 pixels valides, max 16 597) |
| `SHAPEFILE DU COMMUNE/COMMUNE MURAMVYA.*` | 2 polygones | `Type` = `Rural` (236 km²) et `Urbain1` (20 km²) : typologie qui détermine la densité max |
| `SHAPEFILE DU COMMUNE/ZONE SANS MIGRATION.*` | 1 polygone OSM (`fclass` = `Forest`) | Zone d'exclusion |
| `BUR71_Pop admin2024 1.xlsx` | 1 feuille, 19 communes | Population totale par commune (Muramvya : 171 010). Total `=SUM(B2:B20)` comparé à une valeur saisie (5 751 850), avec leur ratio en E21 |

**Vérification des unités.** La somme des pixels multipliée par la surface d'un pixel (0,0625 km²) donne **171 280 habitants**, contre 171 010 dans l'Excel (écart de 0,16 %). Cela confirme que le raster est en hab/km² et qu'il est déjà calé sur le total communal.

**Ce qui n'a pas été fourni :**
- aucun script **R** ;
- aucun fichier du **calage bâti → population** (la régression polynomiale Excel décrite dans la fiche). Le raster de densité 2023 arrive déjà calculé ;
- aucune **sortie de référence** de l'outil actuel ;
- la couche « Zone d'étude » attendue par le modèle (on peut probablement utiliser la commune à sa place, *à confirmer*) ;
- rien sur l'**enchaînement des horizons** (2030, 2035…) ni sur la **re-rasterisation** des résultats.

---

## 2. Chaîne de traitement et ordre d'exécution

```
[Amont, hors code fourni]
  Bâti (surfaces de toit) ──régression Excel──► raster densité 2023 (hab/km², 250 m)
                                                     │
[Étape 1 – Modèle « ModèleMigration_V2 » (.model3)]  ▼
  gdal:merge (→ float32) ─► gdal:polygonize (champ P2023value1)
        │                         │
        │                  native:creategrid (maille = « Dimension polygone » = 250 m, emprise du polygonisé)
        │                         │
        └──── native:intersection (grille ∩ polygones) ─► native:union (grille ∪ résultat)
                                  │
      Area = $area/100 ─► Pop2023_1 = P2023value1 × Area
                                  │
      native:intersection avec la commune (récupère « Type »)
      Inter_Area = $area/100 ─► Pop2023 = Pop2023_1 × Inter_Area / Area ─► P2023value = Pop2023 / Inter_Area
                                  │
      Pm1 = densité max selon Type (règle §4.1) ─► Pmax = Pm1, sinon densité max rurale
                                  │
      native:difference (retire la zone sans migration) ─► native:clip (zone d'étude)
                                  │
      native:retainfields ─► P2025value = P2023value × (1+0,049)^1 ─► native:deletecolumn
                                  │
                           sortie « P2023entrée » (+ sortie intermédiaire « Pmax »)
                                  │
[Étape 2 – manuelle, déduite du code]
  ajout d'un identifiant « ID » par maille, ajout des colonnes P2030value … P2060value,
  création du dossier <Year> sous C:/Users/LGI/Desktop/SHER CONSULT/PROJECT/BUR71/GIS/BUR71_Data/
                                  │
[Étape 3 – CAM12_migration.py, lancé une fois par horizon avec « Year »]
  boucle : dP = Pmax − P_sum ─► mailles en déficit et en excès ─► 3 plus proches voisins
           ─► répartition ─► mise à jour de P_sum ─► jusqu'à ce qu'il n'y ait plus d'excès
                                  │
  sortie : couche vectorielle « Nbrep_<n>Nbfeature_0 » (P_sum, P_sper, Distance_max)
                                  │
[Étape 4 – hors code] retour éventuel en raster, cartes, tableaux
```

**Ordre d'exécution effectif :**
1. modèle `.model3`, lancé une fois (année de base 2023) ;
2. préparation manuelle de la couche de mailles : identifiant et colonnes de population par horizon ;
3. script de migration, lancé **à la main pour chaque horizon** (paramètre `Year`), ce qui confirme D2.

Le lien entre l'étape 1 et l'étape 3 n'est pas automatisé. Les deux fichiers ne sont d'ailleurs pas au même niveau de version :
- le script vient de QGIS 3.16 et reste marqué par des projets antérieurs (NGA03, OUG05). Sa liste de colonnes à supprimer cite encore `D2022_km2`, `Q_fixed` et `P2022` ;
- le modèle utilise des paramètres récents (`METHOD` de `fixgeometries`, `GRID_SIZE`, `retainfields`), sans doute QGIS 3.28 ou plus *(à confirmer)*.

---

## 3. Répartition PyQGIS / R et dépendances

| Composant | Technologie | Part |
|---|---|---|
| Préparation (modèle) | Model Builder QGIS : 21 algorithmes `native:*` et `gdal:*` | ~ 50 % |
| Migration (script) | PyQGIS / Processing : ~ 25 appels `processing.run` par itération | ~ 50 % |
| R | **Absent** des fichiers fournis | 0 % |
| Calage bâti → population | Excel (non fourni) | — |

**Dépendances :**
- **QGIS** : l'en-tête du script indique 3.16, le modèle semble dater de 3.28 ou plus.
- **Algorithmes Processing** :
  - natifs : `native:fieldcalculator`, `native:joinattributestable`, `native:centroids`, `native:saveselectedfeatures`, `native:fixgeometries`, `native:union`, `native:intersection`, `native:difference`, `native:clip`, `native:creategrid`, `native:retainfields`, `native:deletecolumn` ;
  - `qgis:*` en Python, plus anciens : `qgis:distancematrix`, `qgis:selectbyattribute`, `qgis:deletecolumn` ;
  - GDAL : `gdal:merge`, `gdal:polygonize`, qui passent par des scripts Python GDAL externes.
- **Système de fichiers** : chemin Windows codé en dur (`CAM12_migration.py:65`). Un sous-dossier par année doit exister avant le lancement.
- **Format de sortie** : les sorties intermédiaires sont écrites sans extension. Elles prennent le format vectoriel par défaut de QGIS, normalement GeoPackage. Avec le shapefile, les noms de champs longs (`Distance_max`, `tempGain_pop`…) seraient tronqués à 10 caractères et la chaîne casserait.
- **Aucune bibliothèque tierce** : ni numpy, ni R, ni pandas.

**Conséquence pour le projet :** la dépendance à R évoquée dans la fiche (D6) n'existe pas dans ce qui a été fourni. En revanche, la chaîne dépend entièrement de l'exécution d'algorithmes Processing sur des **couches vectorielles**. C'est de là que viennent l'essentiel des problèmes de performance (§5).

---

## 4. Algorithme tel qu'il est codé

### 4.1 Préparation (modèle `.model3`)

Paramètres du modèle, avec les valeurs par défaut enregistrées :

| Paramètre | Défaut | Rôle |
|---|---|---|
| `Raster densité de population` | — | densité 2023 (hab/km²) |
| `Commune Study area` | — | polygones portant le champ `Type` |
| `Zone d Etude` | — | emprise de découpage |
| `Zone Sans Migration` | — | exclusion |
| `Dimension polygone` | 250 | côté de la maille (m) |
| `Densité max Rural (hab/km²)` | 2 500 | = 25 hab/ha |
| `Densité max Urbain1 (hab/km²)` | 10 000 | = 100 hab/ha |
| `Densité max Urbain2 (hab/km²)` | 7 500 | = 75 hab/ha |

Étapes :

1. **Vectorisation.** Le raster est converti en float32 (`gdal:merge`), puis polygonisé (4-connexité, champ `P2023value1`). On croise ensuite une grille régulière de 250 m calée sur l'emprise du polygonisé, par intersection puis union. Au final, **chaque pixel devient une entité polygone**.
2. **Densité par fragment.** On calcule `Area = $area/100` (en centaines de m²) et `Pop2023_1 = P2023value1 × Area`. Après intersection avec la commune, on calcule `Inter_Area` et `Pop2023 = Pop2023_1 × Inter_Area / Area`, puis `P2023value = Pop2023 / Inter_Area`.
   → Algébriquement, **`P2023value = P2023value1`** : cette pondération par les surfaces n'a aucun effet sur la densité. `Pop2023_1` et `Pop2023` ne sont pas des populations, car le facteur d'unité est faux (hab/km² × centaines de m²). Ces deux champs ne sont pas réutilisés ensuite.
3. **Capacité `Pmax`** (densité en hab/km², pas une population), selon le `Type` de la commune :
   - si `P2023value > dmax(Type)` → `Pm1 = P2023value`. Une maille déjà au-dessus du seuil en 2023 reçoit sa propre densité comme plafond : elle n'émet pas d'excès au départ ;
   - si `P2023value < dmax(Type)` → `Pm1 = dmax(Type)` ;
   - autrement (égalité stricte, `Type` inconnu, densité NULL) → `Pm1 = NULL`, puis `Pmax = @densit_max_rurale_habkm`.
   - Autrement dit, **`Pmax = max(densité 2023, dmax du type)`**.
4. **Exclusion.** Les mailles de la zone sans migration sont **supprimées** (`native:difference`), puis le tout est découpé sur la zone d'étude. La population de ces zones sort donc complètement du calcul : elle n'est ni conservée, ni plafonnée.
5. **Croissance.** `P2025value = P2023value × (1 + 0,049)^1` : un taux unique de 4,9 %, codé en dur, avec un **exposant de 1** alors que 2023 → 2025 représente 2 ans (voir §6).

### 4.2 Migration (`CAM12_migration.py`)

**Entrée.** La couche de mailles `Pixelpop` doit contenir :
- `P<Year>value` : densité à l'horizon, avant migration ;
- `Pmax` ;
- un identifiant `ID`/`id`, appelé en minuscules (`id`) à certains endroits et en majuscules (`ID`) à d'autres ;
- les colonnes `P2023value` à `P2060value`, qui sont supprimées au début.

**Initialisation** (`CAM12_migration.py:74-101`) :
- `P<Year>m = P<Year>value`, stocké en **texte** (`FIELD_TYPE 2`) ;
- `P_sum = P<Year>m`, en réel.

**Boucle** `while j > 0` (`:106-524`). Chaque itération suit ces étapes :

| # | Ligne | Opération |
|---|---|---|
| 1 | 120 | `dP = Pmax − P_sum`, stocké en **entier** |
| 2 | 139-173 | **Mailles en déficit (U)** : `dP > 0`, réduites à leur centroïde |
| 3 | 181-214 | **Mailles en excès (O)** : `dP < 0`, réduites à leur centroïde. Les mailles où `dP = 0` ou `NULL` sont neutres |
| 4 | 218-223 | Si O est vide, `j = 0` : on arrête **après** avoir terminé l'itération en cours, qui tourne à vide |
| 5 | 237 | `qgis:distancematrix` : pour chaque maille O, les **3 mailles U les plus proches** (distance euclidienne entre centroïdes), **sans limite de distance** |
| 6 | 257-303 | Jointure des attributs de U (`Upop_*`) et de O (`Opop_*`) sur chaque couple (O, U, distance) |
| 7 | 312 | `NumSplit = count(InputID, InputID)` : nombre de destinations par source (3, ou moins s'il y a moins de 3 mailles U) |
| 8 | 325 | `Gain_pop = Opop_dP / NumSplit` : **partage égal** de l'excès entre les 3 destinations, stocké en **entier** |
| 9 | 340 | `NumSplit_T` : calculé mais **jamais utilisé** |
| 10 | 353 | `Gain_pop = sum(Gain_pop, TargetID)` : total reçu par chaque destination |
| 11 | 384 | `Distance_max = maximum(Distance, TargetID)` : diagnostic seulement |
| 12 | 400-432 | Retour sur la couche complète : jointure des gains sur les destinations (préfixe `temp`) et de l'excès sur les sources |
| 13 | 440 | Destinations : `P_sum = P_sum + |tempGain_pop|`, stocké en **entier** |
| 14 | 457 | Sources : `P_sum = Pmax` (la maille est ramenée exactement à sa capacité) |
| 15 | 474 | `P_sper = P_sum / Pmax × 100` : taux de remplissage |
| 16 | 492-518 | Nettoyage des colonnes (liste codée en dur) et mise à jour de `Distance_max` |

**Propriétés qui découlent du code :**
- **Voisinage.** Ce ne sont pas les voisins immédiats : ce sont les 3 mailles en déficit les plus proches, où qu'elles soient. Sur une grande emprise, l'excès peut « sauter » plusieurs kilomètres.
- **Pondération.** Aucune : ni par la distance, ni par la capacité disponible, ni par l'attractivité.
- **Capacité des destinations non vérifiée.** Une maille U peut recevoir plus que son `dP`. Elle passe alors en excès à l'itération suivante et redistribue à son tour : l'excès se propage de proche en proche.
- **Pas de retour vers la source.** La source est ramenée à `dP = 0` et devient neutre, ce qui évite les allers-retours.
- **Arrêt.** La boucle s'arrête quand il n'existe plus aucune maille avec `dP < 0` après arrondi entier. Il n'y a **ni nombre maximal d'itérations, ni critère de tolérance**.
- **Excédent sans capacité.** Aucun traitement n'est prévu. Si toutes les mailles sont pleines (ensemble U vide) alors qu'il reste de l'excès, la matrice de distances est vide et `P_sum` ne change plus : **la boucle ne se termine jamais**.
- **Unité transférée : la densité, pas la population.** Pour un transfert à surface égale, c'est la même chose. Mais les mailles en bordure de commune, de zone exclue ou de zone d'étude sont des **fragments de surface variable**. Transférer X hab/km² d'une maille entière vers un fragment de 1 ha ne conserve pas la population.
- **Arrondis.**
  - `dP`, `Gain_pop` et `P_sum` sont convertis en entiers à chaque itération. Un petit excès (par exemple `dP = −1`, partagé en −0,33 ×3 puis arrondi à 0) est **perdu** : la source est remise à `Pmax`, mais personne ne reçoit rien.
  - Inversement, les arrondis vers le haut **créent** de la population.
  - En hab/km² sur des mailles de 6,25 ha, l'effet par maille est faible (1 hab/km² ≈ 0,06 habitant), mais il s'accumule sur les itérations.
- **Pas de chaînage entre horizons.** Chaque horizon repart de `P<Year>value`, préparé à l'étape manuelle. Le code ne montre pas si `P2030value` est calculé à partir de la population *après* migration de 2025 ou *avant* (voir §6).

---

## 5. Points fragiles et causes probables des plantages sur les gros jeux de données

### 5.1 Causes structurelles de lenteur et de plantage

| # | Constat dans le code | Effet sur un gros jeu de données |
|---|---|---|
| P1 | **Chaque pixel est un polygone vectoriel** (polygonize + grille + union + intersection). Le calcul ne se fait jamais sur un raster | À 100 m sur tout le Burundi (~27 800 km²), on obtient environ 2,8 millions d'entités, avant découpage aux frontières. Les opérations d'union et d'intersection entre polygones sont coûteuses en mémoire et en temps : c'est le premier point de rupture probable, **avant même la migration** |
| P2 | Chaque itération de migration exécute **~25 algorithmes** et **réécrit la couche complète sur disque 8 fois** (`DP_Nbrep_*`, `Testh*`, `Testi*`, `Testj*`, `Testk*`, `Testl*`, `Nbrep_*`…) | Le coût par itération est proportionnel au nombre total de mailles, même si seules quelques-unes débordent |
| P3 | **Aucun fichier intermédiaire n'est supprimé.** Il y a ~22 fichiers par itération, nommés d'après le compteur, dans le dossier de l'année | Le disque se remplit sur les longues séries d'itérations |
| P4 | Toutes les sorties intermédiaires sont chargées dans le contexte Processing (`is_child_algorithm=True`) et **jamais libérées** pendant la boucle | La mémoire et le nombre de fichiers ouverts augmentent à chaque itération. C'est une cause probable de plantage après de nombreuses itérations *(à confirmer à l'exécution)* |
| P5 | Expressions d'agrégat groupées : `count(…, InputID)`, `sum(…, TargetID)`, `maximum(…, TargetID)` | QGIS évalue un agrégat par groupe distinct, ce qui peut aller jusqu'à un coût quadratique sur la table des couples (3 × nombre de mailles en excès) |
| P6 | Le **nombre d'itérations n'est pas borné** et croît avec la distance que l'excès doit parcourir. L'excès avance d'environ un « anneau » de mailles par itération | Sur une grande ville dense, cela fait des dizaines ou des centaines d'itérations, chacune avec les coûts P2 à P5 |
| P7 | **Boucle infinie** si la capacité totale est insuffisante (§4.2) | Le calcul ne s'arrête jamais : le disque se remplit, puis la mémoire, puis le calcul plante. C'est une cause directe de plantage, indépendante de la taille du jeu de données |

Remarque sur le diagnostic D1 de la fiche : le code ne contient **ni boucle cellule par cellule en Python, ni chargement complet de raster en mémoire**. Le coût vient du traitement **vectoriel** de chaque maille et des écritures disque massives. La conclusion de la fiche (passer à un traitement matriciel en numpy, par blocs) reste valable.

### 5.2 Anomalies et fragilités fonctionnelles

| # | Emplacement | Constat | Conséquence |
|---|---|---|---|
| F1 | modèle, `Calculer Pmax` | La variable `@densit_max_rurale_habkm` n'existe pas : le paramètre s'appelle `densit_max_rural_habkm` | Le repli vaut NULL. Une maille à `Pmax` NULL est neutre dans la migration : elle ne reçoit rien et ne peut pas émettre d'excès |
| F2 | modèle, `Calculer Pmax1` | La variable `@densit_max_urbain2_habkm` n'existe pas : le paramètre s'appelle `densit_max_urbain2habkm`. Le second test Urbain2 compare aussi au seuil Urbain1 | Pour les mailles `Urbain2`, `Pmax` vaut NULL ou est faux. Pas d'impact à Muramvya (pas de zone Urbain2), mais **bloquant pour d'autres communes** |
| F3 | modèle, `Calculer Pmax1` | Comparaisons strictes `>` et `<` : le cas d'égalité n'est pas traité | Le repli est NULL (cf. F1). Cas rare sur des flottants |
| F4 | modèle, `Calcul 2025` | Taux de 4,9 % codé en dur, exposant 1 pour 2 ans | Taux effectif sur 2023 → 2025 : 4,9 % au lieu de 10,04 % *(ambiguïté, §6)* |
| F5 | modèle, `retainfields` / `deletecolumn` | Champs `" Area"` et `" Inter_Area"` avec une espace en tête, suppression de `Pm` au lieu de `Pm1`, suppression de `left`/`right`/`top`/`bottom` alors que `retainfields` les a déjà écartés | Champs orphelins dans la sortie. Signe que le modèle a été modifié sans être relu en entier |
| F6 | modèle, `P2023value` | Chaîne de pondération par les surfaces sans effet (§4.1-2), avec des champs `Pop2023*` aux unités fausses | Risque d'interprétation erronée si ces champs sont réutilisés comme populations |
| F7 | modèle, `gdal:polygonize` | Polygonisation d'un raster float32 | Selon la version de GDAL, les valeurs peuvent être **tronquées en entiers** dans `P2023value1` *(à confirmer à l'exécution)* |
| F8 | script, l. 65 | Chemin absolu Windows codé en dur, dossier par année à créer à la main | Le script ne tourne pas sur un autre poste sans modification |
| F9 | script, l. 111 et 494 | Listes de colonnes codées en dur (années 2023-2060, champs hérités de NGA03/OUG05 : `P2022`, `D2022_km2`, `Q_fixed`) | Dépend du schéma exact de la couche d'entrée. Les colonnes absentes sont ignorées, mais tout nouveau champ joint s'accumule |
| F10 | script, l. 76-78 | `P<Year>m` est stocké en **texte** puis reconverti en réel | Conversion implicite, fragile selon la locale (séparateur décimal) |
| F11 | script, l. 120, 325, 440 | `dP`, `Gain_pop` et `P_sum` sont stockés en **entiers** | La population n'est pas conservée exactement (§4.2) |
| F12 | script, l. 239 et 261 | Identifiant appelé `id` dans la matrice et `ID` dans les jointures. Son unicité n'est pas garantie : après intersection et différence, plusieurs fragments peuvent hériter du même `id` de grille | Si des identifiants sont dupliqués, un gain est appliqué à plusieurs fragments et de la population est **créée** *(à vérifier sur la couche réellement utilisée)* |
| F13 | script, l. 430 | La jointure de bilan écrit dans le paramètre de sortie `Testb`, écrasé à chaque itération | Comportement dépendant de la destination choisie dans la boîte de dialogue |
| F14 | script, l. 492-512 | `tempDistance_max` est supprimé (l. 494) puis relu dans la formule de `Distance_max` (l. 512) | `Distance_max` est probablement NULL ou faux *(à confirmer)*. Cela ne concerne que le diagnostic, pas la population |
| F15 | script, l. 218-223 | Condition d'arrêt testée au milieu de l'itération | Une dernière itération complète tourne à vide (coût inutile) |
| F16 | script, l. 28 | `param` créé mais jamais ajouté. `Upop`, `Opop` et `Testa` à `Testq` sont déclarés en sortie mais ne servent pas | Interface Processing encombrée de 20 sorties sans intérêt |
| F17 | script | Algorithmes `qgis:deletecolumn`, `qgis:selectbyattribute` et `qgis:distancematrix` | Anciens identifiants, compatibilité avec QGIS 3.40 et 4 **à vérifier** |
| F18 | ensemble | Aucun contrôle de conservation (somme avant / après), aucun journal, aucun test | Une dérive ne peut pas être détectée |

---

## 6. Ambiguïtés sur la logique métier (à trancher, je ne les ai pas tranchées)

| # | Question | Pourquoi c'est ambigu |
|---|---|---|
| A1 | La migration doit-elle transférer des **habitants** (conservation stricte de la population) ou des **densités** (comportement actuel) ? | Les deux ne sont équivalents que si toutes les mailles ont la même surface. Ce n'est pas le cas en bordure |
| A2 | Faut-il reproduire **exactement** la règle « 3 plus proches voisins en déficit, partage égal, sans limite de distance », ou peut-on la faire évoluer (voisinage borné, pondération par la capacité ou la distance) ? | Une migration vectorisée efficace (§7, phase 3) sera plus naturelle avec un voisinage borné. Il faut décider si la non-régression doit être exacte ou tolérante |
| A3 | Que doit devenir l'excédent quand il ne reste plus de capacité ? | Le code actuel boucle indéfiniment. Options possibles : le laisser sur place, élargir le rayon, le signaler dans le rapport |
| A4 | `Pmax = max(densité 2023, dmax)` : une maille déjà au-dessus de `dmax` en 2023 garde-t-elle sa densité comme plafond pour **tous** les horizons ? | C'est ce que fait le code (`Pmax` calculé une seule fois). Mais la croissance la fait ensuite déborder dès le premier horizon |
| A5 | Taux de croissance : 4,9 % **par an** (exposant à corriger à 2 pour 2023 → 2025) ou **pour la période** ? | L'exposant de 1 est incohérent avec un TCAM |
| A6 | Horizons suivants : `P2030value` est-il calculé à partir de la population **après migration** de 2025, ou à partir de 2023 ou 2025 **avant migration** ? | L'étape n'est pas dans le code. Les résultats changent fortement selon le cas |
| A7 | Zones sans migration : faut-il les **retirer** (population sortie du total, comme aujourd'hui) ou les **garder figées** (population conservée, sans échange) ? | La fiche parle de « zones d'exclusion » sans préciser |
| A8 | Unités de `dmax` : le code travaille en **hab/km²**, la fiche en **hab/ha** | Il faut choisir l'unité de l'interface et du fichier de paramètres (facteur 100) |
| A9 | Quelle couche est réellement donnée au script de migration, et comment `ID` et `P2030value`…`P2060value` y sont-ils ajoutés ? | Étape manuelle non documentée (voir F12) |

---

## 7. Réponses aux questions Q1 à Q8 de la fiche

| # | Réponse d'après le code | Reste à confirmer |
|---|---|---|
| **Q1** Répartition PyQGIS / R, référent | **100 % QGIS** dans ce qui a été fourni : un modèle Model Builder pour la préparation et un script PyQGIS/Processing pour la migration. **Aucun code R.** Le calage est fait dans Excel (non fourni). Indices sur les auteurs : chemin de travail `C:/Users/LGI/…/BUR71` (l. 65), chemin commenté `C:/Users/Keyvan/…/OUG05` (l. 66). Le script a été repris de projet en projet (NGA03 → OUG05 → CAM12 → BUR71) | Existe-t-il du R en dehors de ce dépôt, par exemple pour le calage ou pour les horizons ? Qui est le référent : LGI, c'est-à-dire Lionel ? |
| **Q2** Fonctionnement de la migration | Excès = `P_sum − Pmax` (en densité). Il est réparti **à parts égales** entre les **3 mailles en déficit les plus proches** (distance entre centroïdes, **sans rayon maximal**), sans vérifier leur capacité. On **itère** jusqu'à ce qu'il n'y ait plus aucune maille en excès. **Excédent sans capacité : non géré, boucle infinie.** Détail complet au §4.2 | Voir A1 à A3 |
| **Q3** Grille ou zones | Les **densités max** sont fixées **par zone** (polygones de la commune, champ `Type` = Rural / Urbain1 / Urbain2) puis appliquées à une grille de 250 m. Le **taux de croissance** est **unique** et codé en dur (4,9 %). Les **exclusions** sont des polygones | Format souhaité pour BUR71 (fiche §3.2) |
| **Q4** Années charnières et horizons | Base **2023**. Horizons prévus dans le code (l. 111) : **2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060**, soit un pas de 5 ans après 2025. Seul 2025 est calculé dans le modèle | Années charnières des paramètres (taux, `dmax`), si elles doivent varier dans le temps |
| **Q5** Recalage sur des projections officielles | **Pas de recalage** dans le code. L'Excel `Pop admin2024` donne des totaux communaux, et le raster 2023 y est déjà calé (écart de 0,16 % à Muramvya). Le ratio E21 (somme des communes / 5 751 850) suggère une vérification de cohérence faite à la main | Quelle projection officielle utiliser, et à quelle échelle (nationale, provinciale, communale) ? |
| **Q6** Résolution et emprise | Jeu test : **250 m** (paramètre `Dimension polygone`, identique au pixel du raster), 27,3 × 24,5 km, 3 109 mailles valides | Résolution et emprise cibles de BUR71 (commune, province, pays ?) |
| **Q7** Politique d'envoi à des API d'IA | Le code ne permet pas d'y répondre | Entièrement à trancher |
| **Q8** Définition de l'urbain | Le code n'a **pas de seuil urbain**. L'urbain vient d'une **typologie administrative** en entrée (`Type` : Rural / Urbain1 / Urbain2), qui ne sert qu'à choisir `dmax` : 2 500 / 10 000 / 7 500 hab/km², soit 25 / 100 / 75 hab/ha | Seuil de densité, taille minimale de tache, référence nationale (ISTEEBU ?) |

---

## 8. Proposition de plan de développement par phases

Ce plan reprend le phasage de la fiche (§5), ajusté à ce que révèle le code. **Aucune ligne de code ne sera écrite avant validation.** Chaque phase se termine par des tests pytest verts et une comparaison aux sorties de référence.

### Phase 0 – Référence et spécification

**Objectif :** figer ce que fait l'outil actuel avant de le remplacer.

- **Réorganiser le dépôt** selon `CLAUDE.md` : `legacy/` pour le code et `data/test/muramvya/` pour les données, sans aucune modification de contenu. Écrire un `README`.
- **Produire les sorties de référence** en exécutant la chaîne actuelle sur Muramvya (modèle, puis migration pour 2025 et au moins un horizon suivant). Deux options :
  - (a) vous l'exécutez dans votre QGIS et versionnez le résultat dans `reference_outputs/muramvya/`, en y joignant le détail des étapes manuelles (A9) ;
  - (b) j'essaie d'installer QGIS en mode sans interface dans l'environnement de développement, j'exécute le code tel quel dans une copie de travail, sans toucher à `legacy/`, et je documente tout écart.
- **Rédiger `docs/spec_migration.md`** : spécification formelle de l'algorithme (§4), avec des micro-cas calculés à la main (5 × 5 mailles) qui serviront de tests unitaires.
- **Décisions à obtenir** : les ambiguïtés A1 à A9.

**Livrable :** référence versionnée, spécification validée, décisions actées.

### Phase 1 – Socle du moteur (`src/engine/`, sans import de `qgis`)

**Objectif :** remplacer l'étape 1 (le modèle) par un traitement **matriciel**.

- Lecture et écriture des rasters GDAL en float32, avec une grille de calcul alignée sur le raster.
- Rasterisation des zones (`Type` → `dmax`) et des exclusions.
- Calcul de `Pmax` : règle actuelle, avec correction des défauts F1 à F3 selon ce qui aura été décidé.
- Croissance, avec l'exposant conforme à la décision A5.
- Contrôle de conservation systématique : population totale avant et après, par zone.
- Tests : micro-cas, puis comparaison avec la couche `P2023entrée` / `Pmax` de référence.

### Phase 2 – Migration de référence

**Objectif :** reproduire fidèlement l'algorithme actuel en numpy/scipy, pour valider la non-régression.

- Recherche des k plus proches voisins avec `scipy.spatial.cKDTree`, partage égal, itérations jusqu'à ce qu'il n'y ait plus d'excès.
- Mode « compatibilité » avec les arrondis entiers, pour comparer aux résultats actuels.
- Mode « corrigé » en float, avec conservation stricte.
- Garde-fous : nombre maximal d'itérations, traitement de l'excédent sans capacité (décision A3), rapport de convergence.
- Tests : micro-cas de la spécification, puis Muramvya comparé à `reference_outputs/` avec les tolérances qui auront été convenues.

### Phase 3 – Pas de temps, paramètres spatio-temporels, scénario

**Objectif :** traiter D2 à D4.

- Chaînage automatique des horizons (décision A6), avec calcul annuel en interne et sorties aux années choisies.
- Lecture de `zones` et `parametres` en GeoPackage (et shapefile), interpolation linéaire.
- Contrôles des paramètres : chevauchements, valeurs aberrantes, cohérence `dmax` / densité.
- Fichier de scénario YAML/JSON (parseur JSON de la bibliothèque standard, ou YAML si la bibliothèque est déjà fournie avec QGIS, **à vérifier avant d'en dépendre**).

### Phase 4 – Performance et grandes emprises

**Objectif :** traiter D1.

- Traitement par blocs avec recouvrement (le recouvrement étant égal au rayon de migration), lecture et écriture fenêtrées avec GDAL.
- Migration vectorisée par blocs. Selon la décision A2, elle suppose peut-être un voisinage borné : sinon, la migration « sans limite de distance » impose un traitement global de l'ensemble des mailles en excès.
- Mesures de mémoire et de temps sur une emprise nationale synthétique, à la résolution cible (Q6).

### Phase 5 – Calage intégré (niveau A)

**Objectif :** traiter D5.

- Régression surface de toit → population : polynomiale, log-linéaire, par morceaux, par strate.
- Validation croisée, diagnostics, bornes de validité.
- **Prérequis :** le fichier Excel de calage actuel et les données de bâti, qui n'ont pas été fournis.

### Phase 5 bis – Extension urbaine

- Statut urbain, extension ou nouveau noyau, année d'urbanisation, tache urbaine, statistiques par zone (`scipy.ndimage`).
- **Prérequis :** la définition de l'urbain (Q8).

### Phase 6 – Plugin QGIS

- Algorithme Processing, panneau de paramètres, calcul en tâche de fond (`QgsTask`), journal.
- Imports via `qgis.PyQt`.
- Tests dans QGIS 3.40 LTR et QGIS 4.

### Phase 7 – Assistant IA BYOK (niveau B, optionnel)

- **Prérequis :** la politique d'envoi de données (Q7).

### Phase 8 – Recette

- Non-régression complète, installateur zip, documentation utilisateur et note méthodologique.

**Premier livrable exploitable : phases 0 à 4.** Le moteur est alors testé, fidèle à l'existant et performant, et peut déjà être utilisé en ligne de commande. Les phases 5 à 6 ajoutent le calage et l'interface. La phase 7 peut venir plus tard.

**Changements par rapport à la fiche :**
- La migration « de référence » est avancée en phase 2, avant les paramètres spatio-temporels. C'est l'élément le plus risqué, et il conditionne la non-régression.
- La performance vient après, en phase 4, une fois le comportement figé par les tests.
- L'étape « R » disparaît : il n'y a pas de code R dans ce qui a été fourni.
