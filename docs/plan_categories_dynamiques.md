# Plan : catégories qui changent dans le temps (extension urbaine et changements planifiés)

| | |
|---|---|
| **Statut** | Proposé le 30/09/2026 ; questions Q1 à Q10 tranchées le 30/09 (§9). À lancer après les retours du beta testing |
| **Demandes** | (i) extension progressive des taches urbaines sous l'effet de la migration ; (iii) changements d'affectation planifiés, par exemple un camp qui ferme et devient village ou centre secondaire |
| **Références** | Fiche diagnostic §3.4 (extension urbaine) ; note de suivi §3.5 (strates dynamiques) ; décisions du 30/09 (`reste_a_faire.md` §5) ; règle A4 de l'état des lieux |
| **Durée estimée** | 7 à 9 jours, en six étapes testées séparément (généalogie dès la première version) |

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
| `seuil_entree` | Densité à partir de laquelle la maille peut changer | Choisi par l'utilisateur, **pré-rempli à partir des densités déjà fixées** (voir plus bas) |
| `seuil_sortie` | Densité sous laquelle elle revient en arrière, si c'est permis | Aucun : irréversible |
| `voisins_min` | Nombre de mailles voisines déjà dans la catégorie `vers`, parmi les 8 voisines | 1 (extension d'une tache existante) ; 0 permet un **nouveau noyau** (autorisé, Q3) |
| `duree_min` | Nombre d'années consécutives au-dessus du seuil avant le changement | 1 |
| `taille_min` | Population (ou surface) minimale de la tache pour qu'un nouveau noyau compte | Aucune |

- **Seuil d'entrée lié aux densités déjà fixées** (Q2) : une maille ne peut pas dépasser la densité maximale de sa catégorie, puisque la capacité l'en empêche. Le seuil d'entrée doit donc être **au plus égal à la densité maximale de la catégorie `de`**, sinon la transition ne se déclenche jamais.
  - Proposition : le seuil se saisit soit en hab/km², soit en **pourcentage de la densité maximale de la catégorie de départ** (par exemple 80 %). Dans ce second cas, il suit la densité maximale si elle varie dans le temps ou selon la zone.
  - Un seuil impossible à atteindre (au-dessus de la densité maximale) est signalé à la validation du scénario.
- **Nouveaux noyaux et contraintes artificielles** (Q3) : un nouveau noyau peut signaler un **nouveau centre potentiel**. Il peut aussi naître d'une contrainte du modèle plutôt que d'une vraie urbanisation, par exemple une petite enclave entourée d'exclusions ou de zones réservées, où la migration reste bloquée et entasse la population. Chaque nouveau noyau reçoit donc un **diagnostic**, sans être rejeté :
  - la **part de sa croissance venue de la migration redirigée** (population qui n'a pas trouvé de place ailleurs), comparée à la croissance locale ;
  - la **surface de terrain disponible d'un seul tenant** autour de lui (l'enclave), comparée à un seuil ;
  - la **distance** à la tache urbaine la plus proche.
  - Un noyau qui dépasse ces repères est marqué **« à vérifier »**, avec sa raison, dans `taches.gpkg` et dans le rapport. Une option permet d'interdire les noyaux dans les enclaves trop petites (`enclave_min`, en km²). Les repères par défaut sont à fixer sur le cas Muramvya (étape 6).
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
| `verrou` | Quand la zone échappe-t-elle aux règles du modèle ? | « Jusqu'à la fin du départ » (par défaut) : la zone est protégée avant le changement et pendant le départ du surplus, puis elle suit les règles de sa nouvelle catégorie. Un ex-camp devenu village peut donc s'urbaniser ensuite (Q7). Autre choix : « toujours » |

**Départ progressif du surplus** : au changement, la nouvelle capacité peut être inférieure à la population présente. Le plafond de la maille passe alors, **en ligne droite sur `duree_depart` années** (variable d'ajustement, de l'ordre de 5 ans en pratique ; Q6), de la population du moment à la nouvelle capacité. À chaque pas, ce qui dépasse le plafond est déplacé par la **migration existante**, vers les mailles voisines qui ont de la place, avec les mêmes règles et les mêmes politiques en cas de manque de place. Le rapport montre, année par année, les départs de chaque zone planifiée.

Le même mécanisme sert à l'option prévue par la règle A4 de l'état des lieux : ramener progressivement une maille surchargée vers un seuil plus faible.

## 5. Sorties

| Sortie | Contenu |
|---|---|
| `categorie_AAAA.tif` | Catégorie de chaque maille à chaque date de sortie (codes entiers, légende fournie : fichier de style QGIS) |
| `annee_changement.tif` | Année du dernier changement de catégorie ; vide si jamais |
| `statut_urbain_AAAA.tif` | Codes de la fiche §3.4 : 0 non urbain, 1 urbain au départ, 2 extension, 3 nouveau noyau, 9 exclusion |
| `taches.gpkg` | Polygones des taches de chaque catégorie suivie, par date de sortie, **lissés pour l'affichage** (filtre majoritaire, suppression des îlots, polygonisation, lissage de Chaikin). La grille reste la référence du calcul |
| Généalogie des taches (**dès la première version**, Q9) | Identifiant stable de chaque tache (`id_tache`) d'une date à l'autre ; événements : apparition, croissance, fusion, séparation ; table `genealogie`. C'est elle qui permet de dessiner les **nouveaux polygones urbains** : couche `extensions` (ce que chaque tache a gagné entre deux dates) et couche des nouveaux noyaux, avec leur diagnostic (§3) |
| `mailles.gpkg` | Champs `categorie_AAAA` en plus |
| Rapport, `summary.csv` | Par unité administrative et par année : population et surface par catégorie, taux d'urbanisation, part des extensions et des nouveaux noyaux, départs des zones planifiées |

## 6. Interface

Une maquette HTML sera soumise **avant** de coder l'interface, comme pour le calage. Principe :

- Onglet Paramètres, nouvelle section **« Catégories dynamiques »**, avec une case à cocher désactivée par défaut et un avertissement : « le calcul relit chaque maille à chaque pas ».
- **Tableau des catégories** : nom, rang, réservée ou non, couleur. Il est rempli d'office avec les valeurs de la typologie.
- **Modèles de catégories** (Q8) : rien n'est propre au Burundi dans le moteur. Les catégories, leurs rangs et les transitions s'enregistrent dans un petit fichier modèle, qu'on importe dans un autre scénario. Un modèle « Burundi » est fourni d'abord ; les dossiers Cameroun, Rwanda, Nigeria et RDC auront le leur.
- **Tableau des transitions** (mode Libre) et **tableau des changements planifiés** (mode Planifié), avec les zones et les catégories choisies dans des listes, sans rien taper.
- Les tableaux de paramètres (TCAM, densités, indicateurs) liés à la typologie reçoivent une ligne par catégorie, nouvelles comprises.

## 7. Étapes

| # | Contenu | Tests | Durée |
|---|---|---|---|
| 1 | Socle : catégorie courante, paramètres qui la suivent, liste étendue des catégories | Option désactivée : banc identique ; catégorie changée à la main en cours de calcul : paramètres suivis | 1,5 j |
| 2 | Mode Planifié : table, verrou, départ progressif du surplus (plafond qui descend) | Camp fictif fermé en 2030 : départs sur 5 ans, population conservée, destination voisine | 1 j |
| 3 | Mode Libre : seuils, voisinage, durée minimale, hystérésis, taille minimale, hiérarchie | Monde synthétique : extension en anneau autour d'un noyau ; zone réservée jamais touchée ; pas d'aller-retour | 1,5 j |
| 4 | Sorties : rasters, taches lissées, généalogie, couches des extensions et des nouveaux noyaux, diagnostic des noyaux, rapport, `mailles.gpkg` | Fusion et séparation de taches connues ; noyau dans une enclave fictive marqué « à vérifier » ; totaux par catégorie = population | 2,5 j |
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
    {"from": "Rural", "to": "Urbain secondaire", "entry_density": {"share_of_dmax": 0.8}, "neighbours_min": 0, "years_min": 2, "enclave_min_km2": 1},
    {"from": "Urbain secondaire", "to": "Urbain1", "entry_density": 5000, "neighbours_min": 2, "years_min": 2}
  ],
  "planned": [
    {"zones": {"source": "camps.gpkg", "field": "nom", "value": "Musasa"}, "year": 2030,
     "to": "Village ex-camp", "departure_years": 5, "lock": "until_departed"}
  ]
}
```

Les paramètres liés à la typologie reçoivent simplement des valeurs pour les nouvelles catégories, par exemple `"Village ex-camp": 3000` dans `dmax`.

## 9. Questions tranchées le 30/09

| # | Question | Réponse |
|---|---|---|
| Q1 | Unité d'évaluation des règles | La **maille** ; seules les parties de la bonne catégorie changent |
| Q2 | Seuils du passage rural → urbain | **Choisis par l'utilisateur**, en lien avec les densités déjà fixées : saisie en hab/km² ou en pourcentage de la densité maximale de la catégorie de départ (§3) |
| Q3 | Nouveaux noyaux isolés | **Oui** : ils signalent de nouveaux centres potentiels. Chaque noyau reçoit un diagnostic pour repérer ceux qui viennent d'une contrainte artificielle (enclave, migration bloquée) et est marqué « à vérifier » au besoin (§3) |
| Q4 | Retour urbain → rural | **Non** a priori ; le seuil de sortie reste disponible mais vide par défaut |
| Q5 | Destination du surplus | Les **mailles voisines**, par la migration existante |
| Q6 | Rythme du départ | **En ligne droite** ; la durée est une variable d'ajustement, de l'ordre de 5 ans |
| Q7 | Verrou après le changement | Un ex-camp **peut s'urbaniser** : verrou par défaut jusqu'à la fin du départ du surplus, « toujours » en option (§4) |
| Q8 | Catégories | Rural, urbain secondaire, urbain, plus des catégories réservées pour le Burundi. Rien de propre au Burundi dans le moteur : modèles de catégories par pays, en prévision du Cameroun, du Rwanda, du Nigeria et de la RDC (§6) |
| Q9 | Généalogie des taches | **Dès la première version** : elle sert à dessiner les nouveaux polygones urbains (§5) |
| Q10 | Zones à population planifiée (camp dont la population est connue chaque année) | **Laissé ouvert**, hors de ce chantier, mais noté comme un besoin récurrent (`reste_a_faire.md` §6) |

**Point encore ouvert** : les repères par défaut du diagnostic des nouveaux noyaux (part de migration redirigée, taille d'enclave, distance). Ils seront proposés à partir du cas Muramvya (étape 6), puis validés avec vous.
