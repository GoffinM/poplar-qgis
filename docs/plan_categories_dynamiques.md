# Plan : catégories qui changent dans le temps (extension urbaine et changements planifiés)

| | |
|---|---|
| **Statut** | Proposé le 30/09/2026, à valider après les retours du beta testing |
| **Demandes** | (i) extension progressive des taches urbaines sous l'effet de la migration ; (iii) changements d'affectation planifiés, par exemple un camp qui ferme et devient village ou centre secondaire |
| **Références** | Fiche diagnostic §3.4 (extension urbaine) ; note de suivi §3.5 (strates dynamiques) ; décisions du 30/09 (`reste_a_faire.md` §5) ; règle A4 de l'état des lieux |
| **Durée estimée** | 6 à 8 jours, en six étapes testées séparément |

## 1. Principe : un seul mécanisme, deux façons de le piloter

Aujourd'hui, la **catégorie** d'une maille (rural, urbain, camp…) est lue une fois, au départ, dans la couche de typologie. Le TCAM, la densité maximale, la capacité d'accueil et les indicateurs en dépendent pour toute la durée du calcul.

La catégorie devient un **état de la maille, qui peut changer à chaque pas de temps** :

| Pilotage | Exemple | Déclenchement |
|---|---|---|
| **Par le modèle** (mode « Libre ») | Une maille rurale voisine d'une tache urbaine dépasse le seuil de densité pendant 2 ans : elle devient urbaine | Règles de transition, évaluées à chaque pas |
| **Par l'utilisateur** (mode « Planifié ») | Le camp de Musasa ferme en 2030 et devient un village | Table des changements planifiés : zone, année, nouvelle catégorie |

- **Priorité à l'utilisateur** (décision du 30/09) : une zone planifiée n'est jamais modifiée par le modèle. Par exemple, un camp n'est pas une zone de débordement de l'urbain.
- **Changement de catégorie** : dès le pas suivant, la maille prend **tous les paramètres de sa nouvelle catégorie** (TCAM, densité maximale, eau…).
- **Capacité qui baisse** : si la nouvelle densité maximale est plus basse que la population présente, le **surplus part progressivement** vers d'autres mailles (décision du 30/09 ; §4).
- **Option désactivée par défaut** : sans elle, les résultats restent **identiques au chiffre près**, ce que le banc de non-régression garantit.

## 2. Ce qui change dans le moteur

| Aujourd'hui | Avec les catégories dynamiques |
|---|---|
| `units.codes["class"]` lu une fois | Un tableau `category[unité]` mis à jour à chaque pas ; l'ancien tableau reste la catégorie de départ |
| Paramètres liés à la typologie : valeur fixe par unité | Paramètres liés à la typologie : valeur relue selon la catégorie courante. Les paramètres liés à une autre couche (zones de service…) ne changent pas |
| Plafond d'une maille en surcharge : sa densité de départ (A4) | Même règle, sauf pour une maille dont la catégorie a changé : son plafond descend progressivement vers la nouvelle densité maximale (§4) |
| Liste des catégories = valeurs du champ de typologie | Valeurs du champ **plus** catégories introduites par les transitions et les changements planifiés (« Village ex-camp »…) : les tableaux de paramètres ont une ligne pour chacune |

Coût : les paramètres ne sont relus que pour les mailles qui ont changé. Le repérage des taches urbaines (`scipy.ndimage`) est vectorisé et peu coûteux. Il faut compter un calcul un peu plus long, d'où l'option et son avertissement (décision du 30/09).

## 3. Règles du mode « Libre » (extension urbaine)

Les règles sont évaluées **par maille de la grille**, sur sa densité (population ÷ surface utile), à la fin de chaque pas de temps. Les changements prennent effet au pas suivant, ce qui évite qu'un changement dans le pas influence le reste du même pas.

**Table des transitions**, une ligne par passage autorisé :

| Champ | Rôle | Proposition par défaut |
|---|---|---|
| `de` → `vers` | Passage autorisé, par exemple Rural → Urbain | À saisir |
| `seuil_entree` | Densité à partir de laquelle la maille peut changer | À saisir (hab/km²) |
| `seuil_sortie` | Densité sous laquelle elle revient en arrière, si c'est permis | Aucun : irréversible |
| `voisins_min` | Nombre de mailles voisines déjà dans la catégorie `vers`, parmi les 8 voisines | 1 (extension d'une tache existante) ; 0 permet un **nouveau noyau** |
| `duree_min` | Nombre d'années consécutives au-dessus du seuil avant le changement | 1 |
| `taille_min` | Population (ou surface) minimale de la tache pour qu'un nouveau noyau compte | Aucune |

- **Hiérarchie** (décision du 30/09, à organiser proprement) : les catégories ont un **rang**, par exemple rural < périurbain < urbain secondaire < urbain.
  - Le modèle ne fait monter une maille **que d'un rang à la fois**, et seulement par une transition de la table.
  - Les catégories « réservées » (camp, zone protégée…) ne sont **jamais** atteintes ni quittées par le modèle : seuls les changements planifiés les touchent.
- **Mailles à cheval** sur deux catégories (limite de typologie) : la règle regarde la maille entière, mais seules les parties qui ont la catégorie `de` changent.

## 4. Mode « Planifié » et départ progressif du surplus

**Table des changements planifiés**, une ligne par changement :

| Champ | Rôle | Exemple |
|---|---|---|
| Zone | Polygones d'une couche, ou une valeur d'un champ | Couche `camps`, champ `nom` = « Musasa » |
| `annee` | Année du changement | 2030 |
| `vers` | Nouvelle catégorie | « Village ex-camp » |
| `duree_depart` | Années sur lesquelles le surplus quitte la zone | 5 |
| `verrou` | La zone est-elle protégée des règles du modèle ? | Avant et après le changement (par défaut) |

**Départ progressif du surplus** : au changement, la nouvelle capacité peut être inférieure à la population présente. Le plafond de la maille passe alors, **en ligne droite sur `duree_depart` années**, de la population du moment à la nouvelle capacité. À chaque pas, ce qui dépasse le plafond est déplacé par la **migration existante**, vers les mailles voisines qui ont de la place, avec les mêmes règles et les mêmes politiques en cas de manque de place. Le rapport montre, année par année, les départs de chaque zone planifiée.

Le même mécanisme sert à l'option prévue par la règle A4 de l'état des lieux : ramener progressivement une maille surchargée vers un seuil plus faible.

## 5. Sorties

| Sortie | Contenu |
|---|---|
| `categorie_AAAA.tif` | Catégorie de chaque maille à chaque date de sortie (codes entiers, légende fournie : fichier de style QGIS) |
| `annee_changement.tif` | Année du dernier changement de catégorie ; vide si jamais |
| `statut_urbain_AAAA.tif` | Codes de la fiche §3.4 : 0 non urbain, 1 urbain au départ, 2 extension, 3 nouveau noyau, 9 exclusion |
| `taches.gpkg` | Polygones des taches de chaque catégorie suivie, par date de sortie, **lissés pour l'affichage** (filtre majoritaire, suppression des îlots, polygonisation, lissage de Chaikin). La grille reste la référence du calcul |
| Généalogie des taches | Identifiant stable de chaque tache (`id_tache`) d'une date à l'autre ; événements : apparition, croissance, fusion, séparation ; table `genealogie` |
| `mailles.gpkg` | Champs `categorie_AAAA` en plus |
| Rapport, `summary.csv` | Par unité administrative et par année : population et surface par catégorie, taux d'urbanisation, part des extensions et des nouveaux noyaux, départs des zones planifiées |

## 6. Interface

Une maquette HTML sera soumise **avant** de coder l'interface, comme pour le calage. Principe :

- Onglet Paramètres, nouvelle section **« Catégories dynamiques »**, avec une case à cocher désactivée par défaut et un avertissement : « le calcul relit chaque maille à chaque pas ».
- **Tableau des catégories** : nom, rang, réservée ou non, couleur. Il est rempli d'office avec les valeurs de la typologie.
- **Tableau des transitions** (mode Libre) et **tableau des changements planifiés** (mode Planifié), avec les zones et les catégories choisies dans des listes, sans rien taper.
- Les tableaux de paramètres (TCAM, densités, indicateurs) liés à la typologie reçoivent une ligne par catégorie, nouvelles comprises.

## 7. Étapes

| # | Contenu | Tests | Durée |
|---|---|---|---|
| 1 | Socle : catégorie courante, paramètres qui la suivent, liste étendue des catégories | Option désactivée : banc identique ; catégorie changée à la main en cours de calcul : paramètres suivis | 1,5 j |
| 2 | Mode Planifié : table, verrou, départ progressif du surplus (plafond qui descend) | Camp fictif fermé en 2030 : départs sur 5 ans, population conservée, destination voisine | 1 j |
| 3 | Mode Libre : seuils, voisinage, durée minimale, hystérésis, taille minimale, hiérarchie | Monde synthétique : extension en anneau autour d'un noyau ; zone réservée jamais touchée ; pas d'aller-retour | 1,5 j |
| 4 | Sorties : rasters, taches lissées, généalogie, rapport, `mailles.gpkg` | Fusion et séparation de taches connues ; totaux par catégorie = population | 1,5 j |
| 5 | Interface (après validation de la maquette), aide, recette | Tests du plugin | 1,5 j |
| 6 | Cas Muramvya avec des règles réalistes ; bilan ; version | Banc complété | 0,5 j |

Chaque étape passe tous les tests avant la suivante. Le calcul **sans** l'option reste identique au banc de référence.

## 8. Format dans le scénario (proposition)

```json
"categories": {
  "enabled": true,
  "list": [
    {"name": "Rural", "rank": 1},
    {"name": "Urbain secondaire", "rank": 2},
    {"name": "Urbain1", "rank": 3},
    {"name": "Camp", "reserved": true},
    {"name": "Village ex-camp", "rank": 1}
  ],
  "transitions": [
    {"from": "Rural", "to": "Urbain secondaire", "entry_density": 1500, "neighbours_min": 1, "years_min": 2},
    {"from": "Urbain secondaire", "to": "Urbain1", "entry_density": 5000, "neighbours_min": 2, "years_min": 2}
  ],
  "planned": [
    {"zones": {"source": "camps.gpkg", "field": "nom", "value": "Musasa"}, "year": 2030,
     "to": "Village ex-camp", "departure_years": 5, "lock": "always"}
  ]
}
```

Les paramètres liés à la typologie reçoivent simplement des valeurs pour les nouvelles catégories, par exemple `"Village ex-camp": 3000` dans `dmax`.

## 9. Questions à trancher avant de coder

Les réponses du 30/09 sont reprises ; les autres points sont à décider, idéalement à la lumière du beta.

| # | Question | Proposition |
|---|---|---|
| Q1 | Unité d'évaluation des règles : la maille entière ou chaque partie de maille ? | La **maille** (densité sur sa surface utile) ; seules les parties de la bonne catégorie changent |
| Q2 | Seuils par défaut du passage rural → urbain | À fixer avec vous. Repère : la méthode « Degree of Urbanisation » (ONU, Eurostat) retient 300 hab/km² pour les amas urbains et 1 500 hab/km² pour les centres, sur des mailles de 1 km ; il faut adapter ces valeurs à 250 m |
| Q3 | Nouveaux noyaux isolés : autorisés ? | Oui, mais seulement au-delà d'une taille minimale (population de la tache) ; sinon, seulement des extensions |
| Q4 | Retour en arrière (urbain → rural) | Non par défaut (la fiche §3.4 dit « une maille urbaine le reste ») ; un seuil de sortie le permet au besoin |
| Q5 | Départ du surplus : vers où ? | Par la migration existante, vers les mailles voisines qui ont de la place. Faut-il aussi pouvoir désigner des **zones d'accueil**, comme des sites de réinstallation ? |
| Q6 | Rythme du départ | En ligne droite sur `duree_depart` années (5 par défaut ?) |
| Q7 | Verrou des zones planifiées | Toujours, avant et après le changement. Faut-il pouvoir libérer une zone après son changement, par exemple un ex-camp devenu village qui peut ensuite s'urbaniser ? |
| Q8 | Nombre de rangs et catégories de départ pour le Burundi | Rural, urbain secondaire, urbain, plus des catégories réservées (camp, zone protégée…) : à confirmer |
| Q9 | Généalogie des taches dès la première version, ou dans un second temps ? | Second temps : d'abord les rasters et les polygones lissés |
| Q10 | Les zones à population planifiée au lieu d'une catégorie, par exemple un camp dont la population est connue chaque année, entrent-elles dans ce chantier ? | Non : c'est un autre besoin, à noter à part s'il existe |
