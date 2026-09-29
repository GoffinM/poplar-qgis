# Plan de la phase 6 : source des toits et calage bâti → population

| | |
|---|---|
| **Statut** | Validé le 29/09/2026 (§5 et §6) ; étapes 6.1 à 6.6 réalisées (version 0.3.0) |
| **Références** | Spécification §3 bis et §3 ter ; état des lieux §11 (classeurs de Lionel, fragilités F20 à F27) |
| **Déjà en place** | Lecture rapide des toits par paquets (`engine/buildings.py`) : polygones, points avec champ de surface, CSV Google Open Buildings, filtre spatial sur l'emprise, un million de toits lus en 3 à 19 s, affectation aux mailles |
| **Durée estimée** | 3 à 4 jours, en quatre étapes testées séparément |

## 1. Ce que la phase apporte

Aujourd'hui, la population de départ vient d'un raster préparé à part, par la chaîne Excel de Lionel : toits → habitants par toit → somme par pixel. La phase 6 fait entrer cette chaîne dans l'outil :

```
toits (fichier ou base)  →  filtres et usage  →  strates de calage  →  régression par groupe
      →  habitants par toit  →  recalage éventuel sur le recensement  →  population de départ par maille
```

Le raster de population reste une entrée possible : l'utilisateur choisit, dans l'onglet Données, entre « raster » et « toits calés ».

## 2. Étapes

### Étape 6.1 : source des toits et usage (moteur)

| Élément | Contenu |
|---|---|
| Source | Toute source déjà acceptée par le bouton « … » : fichier (GeoPackage, shapefile, CSV Google Open Buildings, GeoParquet si GDAL le lit) ou base de données (PostGIS…). Le mot de passe n'est jamais enregistré |
| Surface | Champ en m² (points), ou surface calculée du polygone dans le système de calcul (en mètres) |
| Usage | Champ de catégories lu tel quel, et un **coefficient par catégorie** (habitation = 1, mixte = 0,5, commerce = 0…). Tableau éditable, avec une ligne par valeur trouvée dans le champ, comme pour le TCAM |
| Règles automatiques | Surfaces minimale et maximale (10 et 450 m² par défaut) ; seuil de confiance pour Google Open Buildings |
| Rattachement | Centroïde (ou point intérieur en option) → maille et strate de calage |
| Rapport | Toits lus, retenus et exclus, par motif (surface, confiance, usage à 0, hors zone d'étude) |

**Tests** : les 38 942 toits de Muramvya (extraits des classeurs) ; un fichier Open Buildings synthétique compressé ; des polygones ; un champ d'usage à trois catégories.

### Étape 6.2 : calage (moteur, `engine/calibration.py`)

**Mode `legacy`** : reproduit exactement les classeurs (10 classes de surface, habitants par classe, polynôme de degré 3 aux coefficients arrondis, plafond p(80) au-delà de 70 m², 0 hors de 10 à 450 m²).
**Critère d'acceptation** : **139 100** habitants en rural et **33 253** en urbain, au centième près.

**Mode amélioré** : il corrige les fragilités F20 à F24.
- **Courbe monotone** : un toit plus grand n'a jamais moins d'habitants (F21). Voir la question C2 pour la forme.
- **Coefficients en pleine précision** (F20) et ajustement sur la **surface moyenne** de chaque classe (F22).
- **Régression multiple** quand un groupe contient assez de strates (communes, collines…) : population recensée de chaque strate = Σ (nombre de toits de la classe k × habitants par toit de la classe k). Elle est résolue par moindres carrés à coefficients positifs (`scipy.optimize.nnls`), ce qui garantit des valeurs ≥ 0. C'est la seule façon de tirer la forme de la courbe des données plutôt que d'hypothèses.
- **Recalage** optionnel de chaque strate sur son recensement (F24), avec le facteur appliqué dans le rapport.
- **Diagnostics** : monotonie, valeurs négatives, part des toits plafonnés, écart au recensement, strates avec trop peu de toits.

**Tests** : reproduction des classeurs ; données synthétiques où la vraie relation est connue et doit être retrouvée ; monotonie ; recalage exact.

### Étape 6.3 : population de départ à partir des toits

- Somme des habitants des toits par unité de calcul, puis même chemin que le raster (arrondi des populations publiées, P2).
- Écriture d'un raster `population_base_AAAA.tif`, réutilisable, et option du scénario `base_population.source = "buildings"`.
- **Critère d'acceptation** : sur Muramvya, avec le mode `legacy`, le raster `POP2023` est retrouvé (rapport médian de 1,002 par pixel, 98 % des pixels entre 0,99 et 1,02, comme dans l'état des lieux §11.3).

### Étape 6.4 : onglet Calage du plugin

| Zone de l'onglet | Contenu |
|---|---|
| Toits | Couche ou base (« … »), champ de surface ou « calculée », champ d'usage et tableau des coefficients, seuil de confiance, surfaces minimale et maximale |
| Strates | Couche et champ de la strate, champ du groupe de régression (facultatif), population recensée : champ de la couche ou tableau (csv, xlsx) |
| Régressions | Une ligne par groupe : mode, nombre de toits, population calculée, recensement, écart. Pour le groupe sélectionné : **courbe et points de calage** (dessinés avec Qt, sans bibliothèque de plus), tableau des classes éditable (habitants par classe), seuils, coefficients saisissables, diagnostics |
| Actions | Calculer le calage ; appliquer la régression d'un autre groupe à une strate trop petite ; exporter et importer un calage (réutilisable pour une autre commune) ; produire le raster de population de départ |

Chaque modification manuelle est enregistrée dans le scénario et dans le rapport : quoi, valeur avant et après, date et nom de l'utilisateur Windows.

**Avant de coder l'onglet**, je mets à jour la maquette HTML pour validation.

### Étape 6.5 : documentation et livraison

Pages d'aide « Calage » (français), spécification, bilan de phase, captures, liste de vérification, version 0.3.0.

## 3. Questions à trancher

### Toits

| # | Question | Proposition |
|---|---|---|
| T1 | Coefficient d'une catégorie d'usage **absente du tableau** (valeur nouvelle ou vide) | Ligne « autres catégories » comme pour le TCAM, **à 1 par défaut** (comme aujourd'hui : tout est habitation), avec la liste des catégories concernées dans le rapport |
| T2 | Seuil de confiance Google Open Buildings | **Désactivé par défaut** (le jeu ne publie déjà que des toits de confiance ≥ 0,65) ; proposé à 0,75 quand on l'active |
| T3 | Surfaces minimale et maximale | 10 et 450 m² par défaut, **réglables par groupe de régression** (un seuil urbain peut différer du rural) |
| T4 | Toit à cheval sur deux mailles ou deux strates | Rattaché entièrement à la maille et à la strate de son **centroïde**, comme aujourd'hui (S3). Un toit dans une zone sans migration compte normalement : ses habitants existent |

### Calage

| # | Question | Proposition |
|---|---|---|
| C1 | Mode par défaut | **Amélioré**, le mode `legacy` restant disponible pour comparer avec les anciens résultats |
| C2 | Forme de la courbe en mode amélioré | **Habitants par classe de surface, reliés par des segments** (courbe en escalier lissé), croissante et plafonnée à la dernière classe. Elle est lisible (une valeur par classe, comme la « valeur de solveur » de Lionel), toujours monotone, et n'explose pas au-delà de 80 m² comme le polynôme. Le polynôme de degré 3 reste disponible, avec un avertissement s'il n'est pas monotone |
| C3 | D'où viennent les habitants par classe quand un groupe n'a **qu'une strate** (cas de Muramvya : un seul recensement rural, un seul urbain) ? Un seul total ne suffit pas à déterminer une courbe | Deux sources, au choix : (a) **saisie** par l'utilisateur, comme les valeurs de solveur actuelles ; (b) **hypothèses** de la feuille `Classes_detaillees` (5 personnes par ménage, 6,5 m² par personne, 10 au maximum), puis mise à l'échelle sur le recensement. **La régression multiple n'est proposée que si le groupe a au moins autant de strates que de classes** |
| C4 | Recalage sur le recensement (F24) | **Activé par défaut en mode amélioré** : la population de chaque strate est ramenée exactement à son recensement, et le facteur est donné dans le rapport. Désactivé en mode `legacy` |
| C5 | Source de la population recensée | Champ de la couche de strates, ou tableau csv/xlsx (strate, population), lu comme les projections |
| C6 | Année des toits et année du recensement | Aucune correction : l'année de base du scénario est celle du recensement. Si l'image des toits est plus ancienne ou plus récente, la différence est absorbée par le recalage (C4). Le rapport rappelle les deux années si elles sont saisies |
| C7 | Nombre et bornes des classes de surface | Les 10 classes des classeurs par défaut (0-5 … 70-80 m²), **modifiables par groupe** |

## 4. Ordre et points de validation

1. 6.1 et 6.2 (moteur), avec le test de reproduction 139 100 / 33 253 ;
2. 6.3, avec la comparaison au raster `POP2023` ;
3. maquette de l'onglet Calage → **votre validation** ;
4. 6.4 puis 6.5.

Chaque étape passe tous les tests avant la suivante, et je vous signale tout écart avec les classeurs.

## 5. Décisions du 29/09/2026

| # | Décision |
|---|---|
| T1 | Ligne « autres catégories » à 1, catégories listées dans le rapport |
| T2 | Seuil de confiance **activable**, désactivé par défaut |
| T3 | Surfaces minimale et maximale réglables par groupe ; **le nombre de strates est réglable** aussi (couche de strates, champ de groupe, ou une seule strate pour toute la zone) |
| T4 | Centroïde comme critère de rattachement |
| C1 | Mode amélioré par défaut |
| C2 | Segments par défaut (plus simples et plus rapides à calculer) ; **polynôme disponible**. Toutes les valeurs du calage sont **exportables dans un rapport JSON** : classes, points, courbes échantillonnées, coefficients, indicateurs de qualité et de précision. Ce format de rapport est étendu à tout le reste, pour produire un **rapport automatique hors de QGIS** (étape 6.6) |
| C3 | Les classes peuvent être **proposées par une analyse fréquentielle** de la distribution des surfaces (points de rupture naturels), même avec une ou deux strates |
| C4 | Recalage sur le recensement activé par défaut en mode amélioré |
| C5 | Recensement : champ de la couche de strates ou tableau |
| C6 | L'écart entre l'année du recensement et l'année visée est **absorbé par un TCAM** appliqué sur la période de décalage |
| C7 | Les limites des classes sont **ajustables à la main sur un graphique** montrant la distribution des surfaces (courbe de densité) et les courbes de calage |

### Étape 6.6 : rapport automatique hors de QGIS

- Chaque exécution et chaque calage écrivent un rapport JSON complet (`report.json`, `calibration.json`) : données d'entrée, paramètres, bilans par pas, avertissements, calage et indicateurs de qualité.
- Une commande `python -m engine report <dossier>` produit à partir de ces fichiers un **rapport HTML autonome** (tableaux et graphiques SVG, sans dépendance), lisible dans un navigateur et imprimable en PDF.

## 6. Modèle final (29/09/2026, après la maquette de l'onglet Calage)

Habitants **entiers par toit** selon la classe de surface ; classes entre plancher et plafond (percentile, valeur ou aucun ; 1er et 90e percentiles par défaut) ; découpage par ruptures naturelles, surfaces égales, percentiles ou à la main ; un seul paramètre ajusté au recensement, la **surface de toit par habitant** ; valeurs modifiables ; recalage proposé mais non appliqué (facteur 1), alerte à ±2 % ; vues Distribution et Cumul. Détail : spécification §3 ter.3.
