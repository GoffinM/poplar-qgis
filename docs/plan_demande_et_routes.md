# Plan : demande calculée à part, puis attraction des routes

| | |
|---|---|
| **Statut** | A validé (A-a à A-d) et livré en 0.8.2, avec le téléchargement OpenStreetMap des routes (B-c) ; **B à valider avant tout code** |
| **Demandes du 06/10** | (A) lancer le calcul de la demande seul, sur un calcul de population déjà fait ; (B) P14 : les fronts ne doivent pas être circulaires ; premier facteur d'attraction : les routes |
| **Ordre** | A d'abord, B ensuite |

## A. Demande calculée à part

### A1. Aujourd'hui

- La demande (eau) est calculée **pendant** le calcul de population, à chaque année de sortie : `model.indicator_values(population, année)`, puis les rasters `water_*_AAAA.tif`, les colonnes de `summary.csv` et les champs de `mailles.gpkg`.
- Changer une dotation ou un rendement oblige donc à **tout relancer** (6 s à Muramvya, mais des minutes à l'échelle nationale).
- La population n'est gardée que **par maille**, dans les rasters. Or la demande se calcule **par unité de calcul** : une maille coupée par une limite de zone d'eau (zone de desserte, commune…) a plusieurs unités, avec des paramètres différents.

### A2. Proposition

1. **Chaque calcul garde sa population par unité** aux années de sortie, avec les non-accueillis et, en mode libre, le polygone de chaque unité. Le fichier `populations.npz` pèse quelques dizaines de Ko à Muramvya, comme le `mailles_base.npz` actuel.
2. **Nouvelle fonction du moteur** `recompute_demand(dossier_du_calcul, scénario)` :
   - la grille est redécoupée à partir des couches du scénario, comme pour régénérer la couche des mailles. Si elle ne correspond plus à celle du calcul (une couche a changé), le calcul s'arrête et l'explique ;
   - la population par unité est relue, puis la demande est recalculée avec les **paramètres d'eau actuels** du scénario ;
   - on réécrit les rasters `water_*_AAAA.tif`, les colonnes de demande de `summary.csv`, le rapport HTML et la couche des mailles, si elle existe ;
   - on écrit `demande_parametres.json`, qui garde les paramètres utilisés et la date, pour garder la trace de ce qui a produit les chiffres.
3. **Plugin** : un bouton **« Recalculer la demande »** dans l'onglet Indicateurs (et un rappel dans Résultats). Il agit sur le calcul affiché dans Résultats, avec les paramètres d'eau du moment, en tâche de fond. Les couches de demande sont rechargées ensuite.
4. **Ligne de commande** : `python -m engine demand <dossier du calcul> [--scenario scénario.json]`.

### A3. Points à trancher

| # | Question | Proposition |
|---|---|---|
| A-a | Où écrire la nouvelle demande : **à la place** de l'ancienne dans le dossier du calcul, ou dans un **sous-dossier** daté (pour comparer plusieurs jeux de paramètres) ? | Sous-dossier `demande_AAAAMMJJ_HHMM/` (rasters, tableau, paramètres) ; le dernier est celui chargé dans QGIS. Rien n'est écrasé, et les variantes se comparent |
| A-b | Calculs faits **avant** cette version, sans population par unité | Répartir la population de chaque maille entre ses unités au prorata de leur surface, avec un avertissement (exact pour les mailles entières, c'est-à-dire la grande majorité) |
| A-c | Mode libre : les paramètres d'eau liés à la typologie suivent le polygone (une maille colonisée prend la dotation urbaine) | Oui, comme dans le calcul : on utilise le polygone de chaque unité à chaque année de sortie, gardé dans `populations.npz` |
| A-d | Faut-il aussi pouvoir **ajouter** un indicateur (eau) à un calcul lancé sans indicateur ? | Oui, c'est le même mécanisme |

**Durée** : environ 1 jour, tests compris (moteur, ligne de commande, plugin).

## B. Attraction des routes (P14)

### B1. Constat

En mode libre, toutes les directions se valent : une ville s'étend en anneau presque circulaire (essai sur Muramvya, colonisations de 2039 à 2060). Seules les zones d'exclusion la freinent. En réalité, l'urbanisation suit d'abord les routes.

### B2. Principe proposé

Les routes agissent à **deux endroits** du modèle, sans changer la vitesse comme paramètre (la vitesse reste un résultat) :

1. **Où va la migration.** Aujourd'hui, l'excédent part vers les k unités les plus proches qui ont de la place. Avec les routes, la distance utilisée devient une **distance « ressentie »** : la distance réelle, divisée par un facteur d'attractivité de la maille d'arrivée, plus grand près d'une route. Les migrants vont donc plutôt le long des routes.
2. **Quelles mailles sont colonisées en premier.** Une maille voisine près d'une route demande moins de voisines déjà urbaines, par exemple 2 au lieu de 3. Le front avance ainsi plus vite le long des axes, ce qui donne des « doigts » d'urbanisation.

**Données** : une couche de lignes (routes), avec, au choix, un champ de **classe** (nationale, provinciale, piste…) qui donne le poids de chaque route. Pour chaque maille, on calcule la distance à la route la plus proche (raster de distance, une seule fois au départ).

**Attractivité d'une maille** : `1 + poids × exp(− distance / portée)`, avec une **portée** par défaut de 500 m. Une maille sur une route nationale de poids 1 est deux fois plus attractive qu'une maille loin de toute route.

**Sorties** :
- le raster d'attractivité ;
- un indicateur de plausibilité nouveau : la part des extensions à moins de 500 m d'une route ;
- l'**indice de compacité**, qui doit baisser par rapport à l'anneau.

### B3. Points à trancher

| # | Question | Proposition |
|---|---|---|
| B-a | Les routes agissent-elles sur la migration (1), sur la colonisation (2), ou les deux ? | Les deux, chacune réglable et désactivable. La migration seule suffit peut-être : à tester sur Muramvya |
| B-b | En mode **planifié** aussi (la migration y suivrait les routes, dans les limites des polygones) ? | Non par défaut : le mode planifié reste identique à l'outil actuel. Option possible |
| B-c | Source des routes | Couche fournie par l'utilisateur (n'importe quel format), ou téléchargée depuis OpenStreetMap (fait en 0.8.2 : champ `classe` nationale / provinciale / autre) |
| B-d | Poids par classe de route, portée | Poids par défaut : nationale 1, provinciale 0,6, autre 0,3 ; portée de 500 m ; tout est modifiable dans l'onglet Strates |
| B-e | Autres facteurs d'attraction plus tard (pente, centres, services) | Le même mécanisme les acceptera : l'attractivité est un produit de facteurs. On commence par les routes seules |

**Durée** : environ 2 à 3 jours, avec un cas test synthétique (une ville et une route droite : l'extension doit s'allonger le long de la route) et un essai sur Muramvya, si une couche de routes est disponible.

**Question pratique** : avez-vous une couche de routes pour Muramvya ou le Burundi ? Sinon, je peux préparer un extrait OpenStreetMap pour les tests.
