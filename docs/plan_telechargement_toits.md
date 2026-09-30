# Plan : téléchargement automatique des toits

| | |
|---|---|
| **Statut** | Validé le 30/09/2026 (§5) ; étape 1 (moteur Google) et étape 2 (contrôle Muramvya) réalisées |
| **Demande** | Bouton « Télécharger les toits de la zone d'étude » ; Google Open Buildings en priorité, Overture Maps en deuxième source (accord du 30/09) |
| **Durée estimée** | 3 à 4 jours pour Google (étapes 1 à 3) ; 1 à 2 jours de plus pour Overture (étape 4) |

## 1. Ce qui a été vérifié (30/09)

### Google Open Buildings v3

- Stockage public (Google Cloud Storage), sans compte ni clé. Les fichiers sont découpés en **tuiles S2 de niveau 6** (environ 150 km de côté).
- Il existe une version **« points »** : latitude, longitude, **surface en m²**, **confiance**, plus code. C'est exactement ce que le calage utilise (centroïde et surface).
- Volumes compressés :

| Emprise | Tuiles | Points | Polygones |
|---|---|---|---|
| Muramvya | 2 (`19c1`, `19c3`) | 129 Mo | 488 Mo |
| Burundi entier | 6 | environ 190 Mo | environ 720 Mo |

- Les tuiles sont repérées par un calcul S2 écrit en Python pur (vérifié sur Londres et Muramvya), **sans nouvelle dépendance**.
- Un fichier de seuils de confiance par tuile (`score_thresholds_s2_level_4.csv`) est publié. Il peut servir à proposer un seuil.
- **Licence** : CC BY 4.0 et ODbL. L'attribution doit figurer dans les rapports.
- Images de 2022 à 2023 environ. Le décalage avec l'année du recensement est déjà absorbé par le TCAM de décalage (décision C6).

### Overture Maps

- GeoParquet public sur S3 : environ 500 Mo par fichier, plusieurs centaines de fichiers, **sans découpage par pays**.
- La couche fusionne Google, Microsoft et OpenStreetMap, avec une nouvelle version chaque mois (la dernière date du 23/09/2026).
- Il faut que le GDAL de QGIS ait le **pilote Parquet**. Il est absent du GDAL 3.8 de mon environnement de test. **À vérifier sur votre poste** (§4, Q1).
- Pour ne lire que la zone utile, il faut l'index des fichiers (catalogue STAC d'Overture) ou les statistiques de chaque fichier. C'est faisable, mais plus lourd que Google.

## 2. Principe

```
zone d'étude → tuiles concernées → téléchargement (cache local) → lecture en flux
      → filtre : dans la zone, confiance, surfaces → GeoPackage de toits + rapport
      → couche ajoutée au projet et choisie dans l'onglet Calage
```

- **Moteur** (`src/engine/downloads/`, sans `qgis`) :
  - calcul des tuiles, lecture des CSV compressés en flux, filtres, écriture du GeoPackage via OGR ;
  - la fonction de téléchargement est **injectable**. Le plugin fournit celle de QGIS, qui respecte le proxy et l'authentification configurés dans QGIS (réseau SHER). Hors de QGIS, `urllib` est utilisé.
- **Cache** : les tuiles téléchargées sont gardées dans un dossier réglable et réutilisées. Les tuiles Google v3 ne changent pas ; pour Overture, la version est notée.
- **Sortie** : un GeoPackage de points, en projection de calcul, avec les champs `area_m2`, `confidence`, `source` et `plus_code` ; en option, des polygones.
- **Rapport** : un `download.json` à côté du GeoPackage indique la source, la version, la date, les tuiles et adresses, les toits lus et retenus par motif, les filtres et la licence. Il est repris dans `calibration.json` et dans le rapport HTML.
- **Ligne de commande** : `python -m engine download-roofs --source google --zone … --out …`.

## 3. Étapes

| # | Contenu | Tests |
|---|---|---|
| 1 | Moteur Google : tuiles S2, lecture en flux, filtres, GeoPackage, cache, rapport | Tuile compressée synthétique (sans réseau) ; tuiles connues pour quelques points. Un test réel sur Muramvya est lancé seulement si une variable d'environnement le demande, comme pour PostGIS |
| 2 | **Contrôle sur Muramvya** : comparaison avec les 38 942 toits des classeurs de Lionel (qui viennent probablement de Google). On mesure le nombre, la surface totale et l'écart de population calée | Écarts documentés |
| 3 | Plugin : bouton dans l'onglet Calage et fenêtre de téléchargement. On y choisit la zone, la source, le format, le seuil de confiance (désactivé par défaut) et la destination. La taille est estimée avant de lancer. Le téléchargement tourne en tâche de fond, avec progression et annulation. À la fin, la couche est ajoutée au projet et choisie comme couche de toits, avec son champ de surface | Tests du plugin avec un faux téléchargeur |
| 4 | Overture, si le pilote Parquet est présent : lecture de la zone seulement, surface calculée en mètres, même sortie et même rapport | Selon Q1 |
| 5 | Aide « Calage » complétée, liste de vérification sur le poste, version 0.4.0 | |

## 4. Points à valider

| # | Question | Proposition |
|---|---|---|
| Q1 | Pilote Parquet dans votre QGIS 3.40 | À vérifier avec la commande ci-dessous. S'il est absent, Overture est reporté ou passe par un fichier que vous téléchargez vous-même |
| Q2 | Format par défaut | **Points**, 4 fois plus légers, et suffisants pour le calage (centroïde et surface). Polygones en option, pour la cartographie |
| Q3 | Zone téléchargée | L'emprise de la **couche des strates** (il faut des toits dans chaque strate recensée), découpée sur ses polygones. Autre choix possible : l'emprise de la carte |
| Q4 | Emplacement | GeoPackage dans un sous-dossier `toits/` à côté du scénario ; cache des tuiles dans un dossier réglable, partagé entre projets |
| Q5 | Deux sources en même temps | Non : une source par téléchargement, sans fusion. La comparaison entre sources viendra plus tard si besoin |
| Q6 | Proxy du réseau SHER | Le téléchargement passe par les réglages réseau de QGIS. Y a-t-il un proxy ? |

Commande pour Q1, à taper dans la console Python de QGIS (**Extensions › Console Python**) :

```python
from osgeo import gdal, ogr; print(gdal.__version__, ogr.GetDriverByName("Parquet") is not None)
```

## 5. Décisions du 30/09/2026

| # | Décision |
|---|---|
| Q1 | QGIS 3.40 du poste : GDAL **3.10.3, pilote Parquet présent** → Overture faisable (étape 4) |
| Q2 | Points par défaut, polygones en option |
| Q3 | Zone = strates **élargies d'une marge** (réglable), **sans sortir d'une limite** (frontière nationale) si elle est donnée. But : voir les abords déjà peuplés, qu'on pourrait croire libres pour l'extension |
| Q4 | `toits/` à côté du scénario, cache réglable |
| Q5 | Une source par téléchargement dans un premier temps ; fusion étudiée plus tard (§7) |
| Q6 | Proxy : test à faire sur le poste (réponse du 30/09) |

**À signaler pour plus tard (logique métier)** : les toits de la marge sont hors des strates recensées. Ils ne servent pas au calage, mais ils ont des habitants. Leur population et leurs paramètres (TCAM, densités) seraient **hérités de la strate la plus proche**. Cela rejoint l'extension urbaine et les strates dynamiques (notes §3.4 et §3.5) ; la règle est à valider à ce moment-là.

## 6. Résultats de l'étape 2 (Muramvya, 30/09/2026)

| | Classeurs de Lionel | Téléchargement Google |
|---|---|---|
| Toits dans les deux communes | 38 942 | **39 126** |
| Toits identiques (même position à 1 m près, même surface) | 38 936 | 38 936 |
| Surface de toit par habitant, rural | 16,9 m² | 16,9 m² (identique) |
| Surface de toit par habitant, urbain | 12,34 m² (écart +0,6 %) | 12,40 m² (écart +1,0 %) |

- Les toits des classeurs **sont ceux de Google Open Buildings v3**. Les 190 toits en plus sont tous dans la strate urbaine, de confiance normale, et pas collés à la limite. Lionel a sans doute découpé avec une limite un peu différente.
- Temps : 129 Mo téléchargés, puis 5,1 millions de lignes lues et filtrées, le tout en **16 s** ; en 9 s quand les tuiles sont déjà dans le cache.
- Avec une marge de 2 km : **65 692 toits (+68 %)**. Les abords de la zone sont déjà très bâtis.

## 7. Fusion de sources (pour plus tard)

- **Deux bases en ligne** : Overture fusionne déjà Google, Microsoft et OpenStreetMap, avec ses propres règles de doublons. Pour croiser des bases en ligne, le plus simple est de prendre Overture.
- **Base locale + base en ligne** (relevés de terrain, cadastre, numérisation SHER) : c'est le cas utile. La base locale est prioritaire là où elle existe ; la base en ligne comble ailleurs.
- **Doublons non identiques** : deux contours d'un même toit, tracés par des algorithmes différents, se recouvrent sans coïncider.
  - Polygones : deux toits sont le même si leur **recouvrement** dépasse un seuil (par exemple 50 % de la surface du plus petit).
  - Points : le même si leurs centroïdes sont à moins d'une distance liée à la taille du toit (par exemple la moitié de √surface), et si les surfaces sont comparables (rapport entre 0,5 et 2).
  - Recherche des voisins avec `scipy.spatial.cKDTree`, déjà disponible. Le toit de la source prioritaire est gardé, et le rapport compte les toits appariés, ajoutés et écartés.
