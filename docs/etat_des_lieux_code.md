# BUR71 – État des lieux du code existant

| | |
|---|---|
| **Objet** | Analyse du code fourni (commune test de Muramvya), sans modification |
| **Référence** | `docs/BUR71_fiche_diagnostic_outil_SIG_population.md` |
| **Date** | 29/09/2026 |
| **Statut** | v2 : décisions du 29/09 intégrées (§6 à §9). Analyse statique (lecture du code et inspection des données). Le code **n'a pas été exécuté** : les points marqués *« à confirmer à l'exécution »* restent des hypothèses |

---

## 1. Inventaire des fichiers fournis

Les fichiers ont été rangés le 29/09/2026, sans modification de contenu : le code est dans `legacy/`, les données dans `data/test/muramvya/`. La correspondance avec les noms d'origine figure dans les `README.md` de ces deux dossiers.

| Fichier | Nature | Contenu |
|---|---|---|
| `legacy/Modeleur de migration_Q 2.model3` | Modèle graphique QGIS (Model Builder), nom interne `ModèleMigration_V2`, groupe `CAM12` | **Préparation** : raster de densité → grille vectorielle de 250 m, densité et capacité (`Pmax`) par maille, exclusions, croissance 2023 → 2025 |
| `legacy/CAM12_migration.py` | Algorithme Processing en Python (modèle exporté puis retouché à la main). En-tête : `Name: Migration`, `Group: NGA03`, QGIS 3.16. Classe `Zefze`, algorithme `OUG05_migration` | **Migration** itérative de l'excédent au-delà de `Pmax` |
| `data/test/muramvya/pop2023_muramvya.tif` | GeoTIFF float32, 109 × 98 pixels de **250 m**, EPSG:32735 (UTM 35S), nodata −3,4·10³⁸ | Densité de population 2023 en **hab/km²** (3 109 pixels valides, max 16 597) |
| `data/test/muramvya/commune_muramvya.*` | 2 polygones | `Type` = `Rural` (236 km²) et `Urbain1` (20 km²) : typologie qui détermine la densité max |
| `data/test/muramvya/zone_sans_migration.*` | 1 polygone OSM (`fclass` = `Forest`) | Zone d'exclusion |
| `data/test/muramvya/pop_admin2024.xlsx` | 1 feuille, 19 communes | Population totale par commune (Muramvya : 171 010). Total `=SUM(B2:B20)` comparé à une valeur saisie (5 751 850), avec leur ratio en E21 |

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

## 6. Ambiguïtés sur la logique métier et décisions

Décisions recueillies auprès de Michel le 29/09/2026. Les lignes marquées **ouvert** restent à trancher.

| # | Question | Décision |
|---|---|---|
| A1 | Faut-il transférer des habitants ou des densités ? | **On transfère de la population.** La densité reste la grandeur de travail : elle sert à comparer chaque maille à son plafond. Mais la quantité déplacée est une population, qui tient compte de la surface réelle de chaque maille, y compris des mailles incomplètes (voir R1) |
| A2 | Faut-il garder la règle des « 3 plus proches voisins » ? | **Oui.** Elle a été retenue pour faire converger le modèle et reste pertinente. Le nombre de voisins deviendra un paramètre, avec 3 par défaut |
| A3 | Que devient l'excédent quand il n'y a plus de capacité ? | Le calcul ne doit plus boucler indéfiniment. Il doit détecter la non-convergence, l'annoncer par un message explicite et proposer des options (détail au §8.4) : augmenter les densités max, de façon globale ou par zone ; déverser l'excédent dans des mailles « puits » en périphérie ; enregistrer la population non relocalisée. **Dans tous les cas**, un rapport d'exécution lisible et un raster par pas de temps indiquent si tout a pu être réparti |
| A4 | Une maille déjà au-dessus de `dmax` à l'année de base garde-t-elle sa densité comme plafond ? | **Oui, par défaut** : le plafond d'une maille déjà en surcharge est sa densité de l'année de base (`Pmax = max(densité de base, dmax)`), comme aujourd'hui. Une option pour ramener progressivement ces mailles vers un seuil plus faible est notée pour plus tard, sans être développée pour l'instant |
| A5 | Le taux de croissance est-il annuel ou par période ? | La croissance devient un **paramètre**, défini par des valeurs cibles à des années charnières (par exemple 2026, 2040, 2060), avec une **interpolation linéaire** par défaut entre elles. L'exposant de 1 entre 2023 et 2025 compensait un décalage de dates entre le recensement et la base de données du bâti : c'est un bug à corriger. L'année de la population de base doit donc devenir un paramètre explicite |
| A6 | Un horizon repart-il de la population après ou avant la migration de l'horizon précédent ? | **Après** la migration de l'horizon précédent |
| A7 | Que devient la population qui habite dans une zone sans migration ? | **Option c : ne plus accueillir personne.** Le plafond d'export est la population de l'année de base (A7-bis = c1). La zone ne reçoit aucune population venue d'ailleurs. Ses habitants restent comptés et croissent, et l'excédent issu de leur croissance migre vers les mailles autorisées. On ne supprime jamais d'habitants déjà présents |
| A8 | Quelle unité pour les densités : hab/km² ou hab/ha ? | **Les deux sont possibles** : l'unité est un paramètre secondaire. L'utilisateur saisit et lit les densités dans l'unité de son choix (hab/km² ou hab/ha). Le moteur convertit tout en interne dans une seule unité, et le rapport rappelle l'unité utilisée. La cohérence est ainsi garantie |
| A9 | Comment se fait l'étape manuelle (identifiant, colonnes 2030 à 2060) ? | **Sans objet** : cette étape est entièrement automatisée dans le nouvel outil |

### A7 : que faire de la population d'une zone sans migration ? (décision : option c)

Aujourd'hui, le modèle **découpe** les zones sans migration (ici la forêt) et les **retire** de la couche de mailles. Il en résulte que :
- ces zones ne reçoivent jamais de population, ce qui est sans doute le but recherché ;
- **mais les habitants qui y vivent déjà à l'année de base disparaissent aussi du calcul** : ils sont absents des totaux, ils ne croissent pas et ils ne migrent pas.

À Muramvya, la forêt est probablement presque vide, et l'effet est faible. Sur une autre zone d'exclusion, par exemple une zone inondable déjà habitée, il peut être important. Il faut choisir le comportement par défaut :

| Option | Comportement | Conséquence |
|---|---|---|
| a | **Retirer** la zone, comme aujourd'hui | Les habitants existants sortent des totaux |
| b | **Figer** la zone | Elle ne reçoit personne, mais ses habitants restent comptés, sans croissance ni migration |
| c | **Garder sans accueil** | Elle ne reçoit personne, mais ses habitants restent comptés et croissent. L'excédent issu de leur croissance est envoyé vers les mailles voisines |
| d | **Évacuer** | Ses habitants sont redistribués vers les mailles autorisées dès le premier pas |

### Remarques R1 et R2 (validées)

**R1 – Le transfert doit conserver la population.** Le code actuel retire un excès de X hab/km² à la source, puis ajoute X/3 hab/km² à chacune des 3 destinations, quelle que soit leur surface.

Exemple avec une maille source entière de 6,25 ha qui dépasse de 800 hab/km² : l'excédent est de 50 habitants.
- Si les 3 destinations sont des mailles entières, elles reçoivent 16,7 habitants chacune. Total : 50, la population est conservée.
- Si l'une d'elles est un fragment de 1 ha, elle ne reçoit que 2,7 habitants. Total : 36, donc **14 habitants disparaissent**.
- Inversement, un fragment qui émet vers des mailles entières **crée** de la population.

**Décision : le transfert porte sur la population.** Pour chaque source :
- population à déplacer = excès de densité × surface utile de la source ;
- cette population est partagée entre les destinations ;
- chaque part est reconvertie en densité pour la destination : part ÷ surface utile de la destination.

La population totale est conservée exactement. L'ancien comportement reste disponible dans un mode « compatibilité », qui sert **uniquement** à la comparaison avec l'outil actuel.

**R2 – On arrondit les populations, jamais les densités.** Le code actuel arrondit des densités en hab/km² à l'entier. Pour une maille de 250 m, 1 hab/km² correspond à 0,0625 habitant : les populations qui en résultent ne sont donc pas entières.

**Décision :**
- le calcul se fait en réels (float32) ;
- la **population** de chaque maille est arrondie à l'entier dans les sorties, avec une méthode qui conserve le total (répartition des restes) ;
- les densités publiées sont calculées à partir de ces populations entières.

---

## 7. Réponses aux questions Q1 à Q8 de la fiche

| # | Question de la fiche | État |
|---|---|---|
| **Q1** | Quelle est la répartition entre PyQGIS et R, et qui est le référent ? | **Réglé.** Tout est dans QGIS : le modèle `.model3` établit la population de référence, le script Python fait la migration. Il n'y a pas de R. Auteur du code : Keyvan (dossier `C:/Users/Keyvan` dans le script ; orthographe à confirmer). Le nouvel outil sera entièrement dans QGIS et Python |
| **Q2** | Comment fonctionne la migration ? | **Réglé** pour la description (§4.2) : 3 plus proches voisins en déficit, partage égal, itérations jusqu'à ce qu'il n'y ait plus d'excès. Référent : Keyvan. Les évolutions sont celles de A2, A3 et R1 |
| **Q3** | Les paramètres sont-ils fournis sur une grille ou sur des zones ? | **Réglé.** Les paramètres (densités max, croissance…) sont donnés dans des **couches vectorielles d'entrée** (shapefile ou GeoPackage). Par défaut, une valeur uniforme dans le temps et dans l'espace ; en option, des valeurs qui varient par zone et par année charnière. La **typologie** est libre : ses classes et leurs noms sont définis par l'utilisateur (urbain / périurbain / rural, haut / bas standing, capitale / ville secondaire / ville satellite…) |
| **Q4** | Quelles années charnières et quels horizons de sortie ? | **Réglé.** Tout devient paramétrable : année de départ, année finale (par exemple 2026 → 2060), **pas de temps libre** (10 ans, 5 ans, 1 an, ou moins d'un an), années de sortie au choix. Le calcul enchaîne automatiquement tous les pas jusqu'à l'horizon final |
| **Q5** | Faut-il recaler sur les projections démographiques officielles (totaux nationaux ou provinciaux par année) ? Si oui, lesquelles ? | **Réglé : c'est une option.** On ne dispose pas toujours de projections démographiques. Quand elles existent, l'outil peut recaler la population simulée sur ces totaux (national, provincial ou par zone, pour chaque année). Le rapport indique alors les écarts corrigés. Sans projection, la croissance vient uniquement des taux saisis. Aujourd'hui, le code ne fait aucun recalage : le raster 2023 est seulement calé sur les totaux communaux de l'Excel `Pop admin2024` |
| **Q6** | Quelle résolution cible, sur quelle emprise ? | **Réglé en partie.** La taille de maille devient un **paramètre**. On l'agrandit pour les grandes emprises, afin de limiter la mémoire. On descend rarement sous 250 m, car une maille doit contenir plusieurs bâtiments. L'emprise cible de BUR71 reste à préciser pour dimensionner le traitement par blocs |
| **Q7** | Quelle est la politique interne sur l'envoi de données vers des API d'IA externes (pour l'assistant de calage de niveau B) ? | **Reste ouvert.** L'assistant IA n'interviendrait qu'à des étapes précises et limitées. En attendant une règle interne, le principe de la fiche s'applique : seules des statistiques agrégées sont envoyées, et uniquement après accord de l'utilisateur |
| **Q8** | Quelle définition de l'urbain retenir (seuil de densité, taille minimale de tache, référence nationale) ? | **Ouvert**, à réfléchir. Aujourd'hui l'urbain n'est qu'une typologie d'entrée, qui ne sert qu'à choisir `dmax` |

---

## 8. Exigences retenues pour le nouvel outil

### 8.1 Grille de calcul

- La taille de maille est un paramètre, 250 m par défaut. Elle est en pratique rarement inférieure à 250 m.
- Si la maille de calcul est plus grossière que le raster d'entrée, on agrège en **conservant la population** : on somme les populations, puis on recalcule la densité.
- Si elle est plus fine, on désagrège uniformément, avec un avertissement : l'affinage ne crée pas d'information.
- Les mailles partiellement couvertes (en bordure) portent leur **surface utile**. C'est l'équivalent raster des fragments actuels.

### 8.2 Typologie et paramètres

- Une couche vectorielle de zones porte un champ de classe dont les valeurs sont libres. Les densités max, les taux de croissance et les exclusions sont définis par classe ou par zone.
- Chaque paramètre peut prendre une valeur unique (uniforme dans le temps et dans l'espace, c'est le défaut), une valeur par zone, ou une valeur par zone **et** par année charnière.
- Entre les années charnières, l'interpolation est linéaire par défaut.
- **Unité des densités** : c'est un paramètre secondaire (hab/km² ou hab/ha). Les densités sont converties à la lecture vers une unité interne unique, puis reconverties à l'écriture. L'unité figure dans le scénario, dans les noms ou métadonnées des sorties et dans le rapport (A8).
- **Zones sans migration** (A7 = option c, A7-bis = c1) : elles ne reçoivent jamais de population venue d'ailleurs. Leurs habitants restent comptés. Leur plafond est leur **population de l'année de base** : toute leur croissance est exportée vers les mailles autorisées, et leur population reste constante.
- **Mailles déjà en surcharge** à l'année de base : leur plafond est leur densité de base (A4). L'option « ramener vers un seuil plus faible » est notée pour plus tard, sans être développée.
- Fichier de scénario (JSON) qui enregistre tous les paramètres d'un run.

### 8.3 Déroulé temporel

- Paramètres : année de la population de base (2023 pour BUR71), année de départ, année finale, pas de temps (y compris fractionnaire), années de sortie.
- À chaque pas de temps : croissance avec le taux interpolé et un exposant égal à la durée réelle du pas, puis migration. Le pas suivant repart de la population **après migration**.
- La croissance entre l'année de base et l'année de départ est calculée explicitement : c'est la correction du bug A5.
- **Recalage optionnel** sur des projections démographiques (Q5). Quand l'utilisateur fournit une table de totaux par année et par zone (pays, province, commune…), la population simulée est remise à l'échelle de ces totaux après la croissance, avant la migration. Les écarts corrigés sont reportés dans le rapport.

### 8.4 Non-convergence

- **Contrôle préalable à chaque pas.** Si la population totale dépasse la capacité totale (somme de `Pmax` × surface), la non-convergence est **certaine** et détectée avant d'itérer. Comme la règle des k plus proches voisins n'a pas de limite de distance, toute capacité libre est atteignable : ce contrôle global suffit.
- **Garde-fou** : un nombre maximal d'itérations, et un seuil de tolérance sur l'excès restant.
- **Politique en cas de non-convergence**, fixée dans le scénario ou choisie en cours de run depuis le plugin :
  1. **arrêt** avec un message explicite (par défaut) ;
  2. **hausse des densités max** de x % (+10 %, +20 %…), sur toute l'emprise ou sur des zones choisies. L'outil calcule et propose la hausse minimale nécessaire, et l'utilisateur la valide ;
  3. **mailles puits en périphérie** : une couronne de mailles hors du périmètre accueille l'excédent ;
  4. **population non relocalisée** : elle est enregistrée et reportée par année et par zone.
- **Rapport d'exécution** : fichier texte ou JSON lisible, avec pour chaque pas les populations totales avant et après, le nombre d'itérations, la convergence, la population non relocalisée et les ajustements appliqués. Il comprend aussi un **raster de population non relocalisée** par pas de sortie.

---

## 9. Plan de développement révisé

**Aucune ligne de code ne sera écrite avant validation.** Chaque phase se termine par des tests pytest verts et une comparaison aux sorties de référence.

### Phase 0 – Référence et spécification

- ~~Réorganiser le dépôt~~ : **fait** le 29/09/2026.
- **Sorties de référence** : **fournies** le 29/09/2026 (`reference_outputs/muramvya/`) et analysées au §10. Il reste à documenter la procédure qui les a produites (§10.5).
- **Rédiger `docs/spec_moteur.md`** : spécification de la migration et des exigences du §8. Elle inclut des cas de test calculés à la main (grilles de 5 × 5 mailles, fragments, non-convergence).
- **Décisions encore à obtenir** : questions sur les résultats de référence (§10.5) ; Q8 (définition de l'urbain), nécessaire seulement pour la phase 6 bis.

### Phase 1 – Socle du moteur (`src/engine/`, sans import de `qgis`)

- Grille de calcul paramétrable : agrégation et désagrégation en conservant la population, surface utile des mailles.
- Rasterisation de la typologie libre, des zones et des exclusions.
- Calcul de `Pmax`, avec correction des défauts F1 à F3.
- Croissance sur un pas de temps quelconque.
- Contrôle de conservation de la population.
- Tests : cas de la spécification, puis comparaison avec la sortie de préparation de référence.

### Phase 2 – Migration et non-convergence

- Migration vectorisée en numpy/scipy (`cKDTree`), avec k voisins (3 par défaut).
- Mode **par défaut** : transfert de population (R1), calcul en réels et arrondi des populations dans les sorties seulement (R2). Mode **« compatibilité »**, qui reproduit l'existant arrondis compris : il sert uniquement à la non-régression.
- Contrôle préalable de capacité, garde-fous, les 4 politiques de non-convergence, rapport d'exécution et raster de population non relocalisée.
- Tests : cas de la spécification, puis Muramvya comparé à `reference_outputs/`.

### Phase 3 – Déroulé temporel et paramètres spatio-temporels

- Année de base, année de départ, année finale, pas de temps libre, années de sortie.
- Enchaînement automatique des pas après migration.
- Lecture des couches de paramètres (shapefile ou GeoPackage), valeurs par défaut uniformes, interpolation linéaire, contrôles de cohérence.
- Unité des densités au choix (A8), recalage optionnel sur des projections (Q5).
- Fichier de scénario JSON. Rapport d'exécution consolidé sur tout le run.

### Phase 4 – Performance et grandes emprises

- Traitement par blocs pour la croissance, les capacités et les sorties.
- Pour la migration, la recherche des voisins porte uniquement sur les mailles concernées (en excès et en déficit), ce qui réduit fortement le volume.
- Mesures de mémoire et de temps à différentes tailles de maille, sur l'emprise cible de BUR71.

### Phase 5 – Plugin QGIS

- Algorithme Processing et panneau de paramètres : typologie, pas de temps, horizons, taille de maille, politique de non-convergence.
- Calcul en tâche de fond (`QgsTask`), avec progression et journal.
- **Dialogue interactif en cas de non-convergence** : l'outil propose une hausse des densités, des mailles puits ou l'enregistrement de la population non relocalisée, et l'utilisateur choisit.
- Chargement des résultats et du rapport dans QGIS. Tests dans QGIS 3.40 LTR et QGIS 4.

**Premier livrable exploitable : phases 0 à 5.**

### Phases suivantes

| Phase | Contenu | Prérequis |
|---|---|---|
| 6 | Calage intégré bâti → population (niveau A) | Fichier Excel de calage et données de bâti |
| 6 bis | Repérage de l'extension urbaine | Définition de l'urbain (Q8) |
| 7 | Assistant IA BYOK (niveau B) | Politique d'envoi des données (Q7) |
| 8 | Recette : non-régression complète, installateur zip, documentation | — |

---

## 10. Analyse des résultats de référence (Muramvya)

Fichiers analysés : `reference_outputs/muramvya/p2023_entree.*` (sortie du modèle) et `pentree_final.*` (résultat final). Ils ont été produits avec QGIS 3.34.11.

### 10.1 Grille

- **4 386 mailles**, 215,1 km² au total. On compte 2 202 mailles entières et 2 184 fragments (bords de commune, limite rural/urbain, forêt). 699 mailles sont multi-parties, et 65 ont une surface arrondie à zéro.
- Les deux fichiers ont exactement la même géométrie. `pentree_final` ajoute un identifiant `ID` unique (de 157 020 à 161 405), ce qui écarte le risque F12 pour ce jeu.
- Le champ `Area` est en **km² avec 3 décimales** : une maille entière vaut 0,062 au lieu de 0,0625. Cela ne correspond pas au modèle `.model3` fourni, qui calcule `$area/100`. Par ailleurs, `p2023_entree` contient un champ `P2024` et pas de champ `Name`. **La version du modèle qui a produit ces résultats n'est donc pas exactement celle du dépôt.**

### 10.2 Bilan de la population 2023 : 6,4 % des habitants disparaissent avant toute projection

| Étape | Population | Écart |
|---|---|---|
| Raster `POP2023` (hab/km² × 0,0625 km²) | 171 280 | |
| Population située dans la forêt (zone sans migration, supprimée) | − 7 144 | confirme A7 : ces habitants sortent du calcul |
| Commune hors forêt | 164 136 | |
| Grille, avec l'aire géométrique réelle des mailles | 161 375 | − 2 761 : découpage des bords, à expliquer |
| Grille, avec le champ `Area` tronqué à 3 décimales | **160 397** | − 978 : l'arrondi de la surface (0,062 au lieu de 0,0625) retire 0,8 % |

La population de la forêt est estimée à partir des centres de pixels.

Le total de l'Excel pour Muramvya (171 010) correspond au raster, et non à la grille. **Nouvelle anomalie F19** : la surface est stockée arrondie, et c'est cette surface arrondie qui sert à convertir les densités en populations. Dans le nouvel outil, la surface sera calculée en float à partir de la géométrie, sans arrondi.

### 10.3 Croissance

- `P2025value` vaut bien 1,049 × `P2023value`, comme dans le modèle. Mais **ce champ n'est pas utilisé dans le résultat final** : `PopD2025` en diffère sur 3 204 mailles.
- Évolution des totaux dans `pentree_final` :

| Période | Population au début → à la fin | Croissance annuelle moyenne |
|---|---|---|
| 2023 → 2024 | 160 397 → 164 805 | 2,75 % |
| 2024 → 2025 | → 168 429 | 2,20 % |
| 2025 → 2030 | → 188 078 | 2,23 % |
| 2030 → 2035 | → 209 056 | 2,14 % |
| 2035 → 2040 | → 229 872 | 1,92 % |
| 2040 → 2045 | → 250 162 | 1,71 % |
| 2045 → 2050 | → 270 811 | 1,60 % |
| 2050 → 2055 | → 290 425 | 1,41 % |
| 2055 → 2060 | → 309 642 | 1,29 % |

- Les taux **décroissent par période** et n'ont rien à voir avec les 4,9 % du modèle. Ils ressemblent à une projection démographique officielle. C'est cohérent avec les besoins exprimés (taux variables dans le temps, recalage optionnel), mais **la source de ces taux n'est pas dans le code fourni**.
- La colonne 2024 est une étape de croissance seule, sans migration : 95 mailles y dépassent leur `Pmax`, dont 91 des 93 mailles en surcharge dès 2023.

### 10.4 Plafonds et migration

- Chaque `Pop<année>` est un **entier**, et `PopD<année>` vaut exactement `Pop<année> / Area`. Ce résultat est donc déjà construit selon R2 : on arrondit les populations et on en déduit les densités.
- Après migration, aucune maille ne dépasse son `Pmax`, à une exception près en 2060.
- **En revanche, le plafond effectif est d'environ 0,91 × `Pmax`, et non `Pmax` :**
  - une maille rurale entière est saturée à **141 habitants (2 274 hab/km²)**, alors que 2 500 × 0,062 = 155 habitants ;
  - 640 mailles rurales sont bloquées exactement à cette valeur en 2060 ;
  - en zone urbaine, la densité maximale atteint 0,912 × 10 000 ;
  - les 93 mailles en surcharge en 2023 croissent de 2,7 % en 2024, puis **tombent à 0,912 × leur densité 2023 en 2025** (par exemple 16 597 → 15 129 hab/km²) et restent figées ensuite. Elles perdent environ 9 % de leur population en 2025, ce qui contredit A4.
- Ce facteur uniforme d'environ 1/1,097 fait penser à une **remise à l'échelle après la migration** (par exemple un recalage sur un total cible) ou à des `Pmax` différents lors du calcul. **À expliquer (§10.5).**
- Les nouvelles mailles peuplées sont rares : entre 29 et 64 par période, pour 95 à 264 habitants. L'essentiel de la migration se fait vers des mailles déjà habitées.

### 10.5 Questions pour pouvoir utiliser ces résultats comme référence de non-régression

| # | Question |
|---|---|
| RF1 | Quelle procédure a mené de `p2023_entree` à `pentree_final` ? Le script de migration a-t-il été lancé pour chaque horizon, avec quelle couche d'entrée, et comment les colonnes ont-elles été rassemblées ? |
| RF2 | D'où viennent les taux de croissance par période (2,75 % en 2023-2024, 2,2 % en 2024-2030, … 1,29 % en 2055-2060) ? D'une projection officielle, et laquelle ? |
| RF3 | Pourquoi le plafond effectif est-il d'environ 0,91 × `Pmax` ? Y a-t-il eu une remise à l'échelle après la migration, ou des `Pmax` différents ? |
| RF4 | Pourquoi l'année 2024 : est-ce l'année du recensement administratif de l'Excel ? |
| RF5 | Existe-t-il une version plus récente du `.model3` (surface en km², champ `P2024`) ? |

**Utilisation possible dès maintenant :**
- `p2023_entree` sert de référence pour la phase 1 (règle de `Pmax`, densité par maille), avec des tolérances qui tiennent compte de F19 ;
- `pentree_final` sert de référence **qualitative** pour les phases 2 et 3 : totaux, absence de dépassement du plafond, forme de la diffusion.

Une comparaison chiffrée exacte avec `pentree_final` suppose les réponses RF1 à RF3.
