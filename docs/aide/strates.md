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
| `polygones.gpkg` | Polygones **lissés pour l'affichage** à chaque année de sortie, extensions et généalogie. Les surfaces et populations viennent de la grille |
| `plausibilite.csv` | Indicateurs de plausibilité par polygone et par horizon : vitesse du front, étalement ou densification, densités, compacité, nouveaux noyaux, non accueillis, effet de reclassement, bilan de masse |

Ce sont des **indicateurs de plausibilité**, pas une validation : les zones d'étude n'ont pas d'historique d'urbanisation. Dans l'onglet Résultats, les polygones de la dernière année sont chargés ; les extensions, le statut et l'année de colonisation sont chargés décochés. **Comparer avec un calcul planifié…** écrit et ouvre `comparaison_modes.html`.
