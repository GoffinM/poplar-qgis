# Strates : polygones planifiés ou libres

L'onglet **Strates** décide si les polygones de la typologie (rural, urbain, camp…) restent figés, ou s'ils s'étendent avec la population (fiche §3.5).

## 1. Deux modes

| Mode | Comportement | Usage |
|---|---|---|
| **Planifié** (par défaut) | Les polygones ne changent jamais. La croissance et la migration se font dans leurs limites. Résultats identiques à l'outil actuel | Urbanisme planifié, périmètre d'urbanisation fixé, schéma directeur |
| **Libre** | Un polygone saturé déborde sur ses voisines. Une maille colonisée prend l'identité et **tous les paramètres** du polygone colonisateur (TCAM, densité maximale, eau…) | Croissance spontanée ou informelle, scénario tendanciel |

En mode libre :
- le calcul relit chaque maille chaque année : il est plus long (environ +50 % à Muramvya) ;
- le pas de calcul interne est **annuel**, quel que soit le pas des sorties ;
- la maille de référence est de **250 m** : un polygone avance au plus d'une couronne de mailles par an, soit 250 m/an ;
- la **vitesse des fronts est un résultat**, jamais un paramètre : elle dépend de la densité et de la croissance ;
- les communes (unités administratives) ne bougent jamais : les statistiques et le recalage restent par commune.

Lancer le même scénario dans les deux modes, puis les **comparer** (onglet Résultats), mesure la pression d'urbanisation hors du périmètre planifié.

## 2. Quand une maille est-elle colonisée ?

Une maille voisine d'un polygone P est colonisée par P quand **toutes** les conditions sont réunies :

1. la maille est **saturée** : elle ne peut plus recevoir personne ;
2. P a **exporté** hors de ses limites, pendant l'année, au moins le **flux minimal** (en part de la capacité de la maille, ou en habitants) ;
3. P est lui-même **saturé** : la **part saturée** de sa surface atteint son seuil (80 % par défaut) ;
4. au moins **3 voisines sur 8** (réglable) appartiennent à P. Une maille appartient à un polygone qui en couvre au moins la moitié ;
5. P est de **rang supérieur** ; les zones d'exclusion et les strates non colonisables ne sont jamais colonisées.

Une maille coupée par une limite garde ses morceaux d'exclusion et sa commune : seuls ses morceaux de rang inférieur changent de polygone. Si deux polygones visent la même maille, le rang le plus élevé gagne, puis celui qui a exporté le plus.

## 3. Le tableau des strates

| Colonne | Rôle |
|---|---|
| Rang | Plus grand = plus urbain. « – » : la strate ne colonise pas et n'est pas colonisée |
| Colonisable | Décoché pour un camp ou une zone protégée |
| Urbaine | Compte comme urbaine dans le statut et la comparaison (rang au moins égal au rang urbain) |
| Flux minimal | Paramètre du colonisateur (10 % par défaut) |
| Part saturée | Paramètre du colonisateur (80 % par défaut) |

Ces deux paramètres peuvent varier dans le temps, comme le TCAM, si on les donne par année dans le fichier du scénario : le tableau les montre alors comme une « série » et les garde.

## 3 bis. Attraction des routes

Sans autre facteur, toutes les directions se valent : une ville s'étend en anneau. Le cadre **Attraction des routes** fait suivre les routes à l'urbanisation, sans imposer de vitesse (la vitesse des fronts reste un résultat).

- **Couche** : une couche de lignes, avec un champ de classe facultatif. Le bouton **OpenStreetMap…** la télécharge (champ `classe` : nationale, provinciale, autre).
- **Attractivité** d'un lieu : `1 + poids × exp(− distance / portée)`, avec la route la plus proche de chaque classe ; on garde le plus grand terme. Elle vaut 1 loin de toute route et 2 sur une route de poids 1. Par défaut : nationale 1, provinciale 0,6, autre 0,3 ; portée 500 m.
- **Migration** : la distance « ressentie » par un migrant est la distance réelle divisée par l'attractivité de la maille d'arrivée. Les migrants vont donc plutôt le long des routes, et ces mailles se remplissent en premier.
- **Colonisation** : une maille « près d'une route » (attractivité d'au moins 1 + seuil, 1,5 par défaut) demande 2 voisines au lieu de 3.
- Chaque action peut être décochée. En mode **planifié**, les routes ne changent rien, sauf si la case dédiée est cochée (la migration suit alors les routes, dans les limites des polygones figés).

Sorties : `attractivite.tif` ; dans `plausibilite.json` et le rapport, la part des extensions à moins de la portée d'une route principale (poids ≥ 0,5), comparée à la même part des mailles rurales au départ. Si la première dépasse nettement la seconde, les fronts suivent les routes. L'indice de compacité doit baisser par rapport au calcul sans routes.

Cas test (ville de 3 × 3 mailles au centre, une route nationale est-ouest, 25 ans) :

| Réglage | Emprise de la ville (est-ouest × nord-sud) |
|---|---|
| Sans route | 7 × 7 mailles |
| Poids par défaut (1), portée 500 m | 9 × 7 |
| Poids 3, portée 500 m | 11 × 5 |

L'effet des poids par défaut est donc modeste ; c'est surtout la migration qui l'apporte. Le réglage est à caler sur une zone dont on connaît l'urbanisation récente le long des routes.

## 4. Nouveaux noyaux

Désactivée par défaut, et signalée dans le rapport. Activée, elle transforme un amas d'au moins 16 mailles (1 km²) saturées, loin de toute ville, en un **nouveau polygone** de la strate choisie (de préférence intermédiaire, par exemple Urbain2). Un noyau est marqué **« à vérifier »** s'il est dans une enclave de moins de 5 km², ou s'il est surtout alimenté par la migration de l'année.

## 5. Taches bâties

Quand la typologie donne des limites administratives (toute une commune urbaine), la ville remplit sa commune avant de déborder, et le mode libre a peu à faire. Le bouton **Préparer les taches bâties…** repère les taches denses de la population de départ :

1. maille dense : au moins 1 500 hab/km² (repère « centre urbain » de la méthode DEGURBA) ;
2. lissage : trous bouchés, puis une maille avec 5 voisines denses sur 8 devient dense ;
3. tache gardée : au moins 5 000 habitants ; un second niveau (Urbain2) peut garder les plus petites ;
4. une tache dense hors de la commune urbaine devient Urbain2 (ou est ignorée, au choix) ;
5. le reste de la commune urbaine devient **Transition** : densité maximale rurale, TCAM urbain.

La carte et le tableau se mettent à jour à chaque réglage. **Utiliser ces taches** écrit `typologie_taches.gpkg` à côté du scénario et l'utilise. Les rangs deviennent Rural 1, Transition 2, Urbain2 3 et la classe urbaine 4. Le bouton **Revenir à la typologie d'origine** annule tout.

En ligne de commande : `python -m engine patches scenario.json` (écrit une copie du scénario).

## 6. Sorties du mode libre

| Sortie | Contenu |
|---|---|
| `polygon_id_AAAA.tif` | Polygone de chaque maille, avec son style |
| `statut_AAAA.tif` | 0 non urbain, 1 urbain dès le départ, 2 extension, 3 nouveau noyau, 9 exclusion |
| `annee_colonisation.tif` | Année où chaque maille a changé de polygone |
| `polygones.gpkg` | Polygones **lissés pour l'affichage** à chaque année de sortie, extensions (différence des contours lissés de deux années) et généalogie. Les surfaces et populations viennent de la grille |
| `plausibilite.csv` | Indicateurs de plausibilité par polygone et par horizon : vitesse du front, étalement ou densification, densités, compacité, nouveaux noyaux, non accueillis, effet de reclassement, bilan de masse |

Ce sont des **indicateurs de plausibilité**, pas une validation : les zones d'étude n'ont pas d'historique d'urbanisation. Dans l'onglet Résultats, les polygones de la dernière année sont chargés ; les extensions, le statut et l'année de colonisation sont chargés décochés. **Comparer avec un calcul planifié…** écrit et ouvre `comparaison_modes.html`.

### Lissage des contours

Le calcul se fait maille par maille ; seuls les contours de `polygones.gpkg` sont lissés, pour l'affichage :

- les escaliers des mailles sont coupés au milieu de chaque côté (une diagonale en escalier devient une droite), puis arrondis (3 passes par défaut, réglage « Lissage (passes) » ; 0 donne les mailles brutes) ;
- seuls les points où se touchent trois polygones restent fixes : deux polygones voisins sont lissés de la même façon de part et d'autre de leur frontière, sans trou ni recouvrement ;
- au bord, le contour suit la vraie limite de la zone d'étude ;
- les rasters (`polygon_id_AAAA.tif`, `statut_AAAA.tif`) restent maille par maille : c'est la vue exacte du calcul.

Les surfaces dessinées diffèrent un peu de celles des mailles (de l'ordre de 1 à 2 % ; davantage pour un polygone qui touche la limite de la zone d'étude). Les chiffres des tableaux viennent toujours des mailles.

