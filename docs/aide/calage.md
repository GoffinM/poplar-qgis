# Calage : des toits à la population

L'onglet **Calage** calcule la population de départ à partir des **toits**, au lieu d'un raster préparé à part. Pour chaque toit, l'outil donne un **nombre entier d'habitants** selon sa surface. La somme par maille donne la carte de densité de départ.

## 1. Les toits

| Réglage | Rôle |
|---|---|
| Couche des toits | Polygones, dont la surface est calculée, ou points avec un champ de surface, depuis un fichier ou une base de données (bouton **…**) |
| Surface | Champ en m² ; vide : surface calculée dans le système de calcul |
| Usage | Champ de catégories, avec un **coefficient** par catégorie (habitation = 1, mixte = 0,5, commerce = 0…). Les catégories absentes du tableau comptent 1 et sont listées dans le rapport |
| Confiance | Seuil **désactivé par défaut** ; activé, il écarte les toits douteux |

Chaque toit est rattaché à une maille et à une strate par son **centroïde**.

Les anciens scénarios qui lisaient directement une tuile CSV de Google Open Buildings restent utilisables : la tuile est indiquée sous la couche des toits, et choisir une couche la remplace. Pour de nouveaux toits, utilisez **Télécharger les toits…**.

### Télécharger les toits

Le bouton **Télécharger les toits…** va chercher les toits de **Google Open Buildings v3**, des données publiques accessibles sans compte, sur la zone d'étude.

| Réglage | Rôle |
|---|---|
| Zone | Couche de polygones : par défaut, la couche des strates |
| Marge | Élargit la zone (1 km par défaut) pour voir les abords : des secteurs qu'on pourrait croire libres pour l'extension sont parfois déjà très bâtis |
| Sans sortir de | Facultatif : une limite que la zone élargie ne dépasse pas (frontière nationale, par exemple) |
| Format | **Points** (centre, surface, confiance), suffisants pour le calage ; ou **polygones**, quatre fois plus lourds, pour la cartographie |
| Seuil de confiance | Désactivé par défaut : Google ne publie que des toits de confiance ≥ 0,65 |
| Enregistrer sous | GeoPackage, par défaut dans le dossier `toits` à côté du scénario |
| Cache des tuiles | Les fichiers téléchargés y sont gardés et ne sont plus téléchargés ensuite, pour ce projet comme pour les autres |

- **Estimer** donne la surface de la zone, le nombre de tuiles et les mégaoctets à télécharger. Pour Muramvya, il faut 129 Mo et environ 20 secondes ; pour le Burundi entier, environ 190 Mo.
- À la fin, la couche est ajoutée au projet et choisie comme couche des toits, avec ses champs de surface et de confiance.
- Un rapport `.download.json` est écrit à côté du GeoPackage : source, date, tuiles, toits lus et gardés, licence. Le rapport HTML du calage le reprend.
- **Licence** : CC BY 4.0 ou ODbL v1.0. Citez « Google Open Buildings v3 » dans les rapports.
- Contrôle sur Muramvya : les toits des anciens classeurs sont ceux de Google Open Buildings v3. On en retrouve 38 936 sur 38 942 à l'identique.
- Le téléchargement passe par le proxy des réglages de QGIS (**Préférences › Options › Réseau**) s'il y en a un.

#### Source Overture Maps

La liste **Source** propose aussi **Overture Maps**, qui fusionne Google Open Buildings, Microsoft et OpenStreetMap en retirant les doublons. Une nouvelle version sort chaque mois.

- Rien n'est téléchargé en entier : seuls les fichiers qui couvrent la zone sont lus, et seulement pour la zone. Pour Muramvya, cela fait un fichier et environ 50 Mo, soit moins d'une minute.
- Un **index** (le rectangle couvert par chacun des 512 fichiers d'une version d'Overture) indique quels fichiers lire. Il est fourni avec le plugin et publié sur GitHub à chaque nouvelle version d'Overture.
- Si Overture vient de publier une version pas encore indexée, le plugin prend la version indexée la plus récente encore en ligne. Si aucune ne l'est, il construit l'index lui-même : il lit alors l'en-tête des 512 fichiers, soit environ 360 Mo, une seule fois, et le garde en cache. La fenêtre le signale.
- **Annuler** arrête le téléchargement en quelques secondes.
- Chaque toit garde sa **source** (`google`, `microsoft`, `osm`) et son **année**. Il garde aussi sa **confiance** si c'est un toit Google, et son **type** et sa **hauteur** quand OpenStreetMap les donne.
- La surface est mesurée sur le contour, dans le système de calcul.
- **Attention au seuil de confiance de l'onglet Calage** : les toits Microsoft et OpenStreetMap n'ont pas de confiance, donc un seuil activé les écarterait. Le seuil de la fenêtre de téléchargement, lui, ne s'applique qu'aux toits qui ont une confiance.
- **Année des images** : l'année la plus fréquente parmi les toits (2023 à Muramvya).
- **Licence** : ODbL v1.0 ; citez « Overture Maps » et ses sources.
- Il faut le pilote Parquet de GDAL. QGIS 3.40 sous Windows l'a ; sinon, le choix est grisé.
- À Muramvya (version du 23/09/2026) : **39 385 bâtiments**, dont 79 % de Google, 19 % de Microsoft et 2 % d'OpenStreetMap. On en comptait 39 126 avec Google seul. Calage : rural 16,9 m² par habitant (identique), urbain 12,5 m² (12,4 avec Google seul).

## 2. Strates et population connue

- Une **strate** est un polygone qui a sa propre population connue (commune, colline…). Sans couche de strates, toute la zone d'étude forme une seule strate.
- Le **groupe de régression** regroupe les strates qui partagent une même courbe (par exemple : rural, urbain). Sans groupe, chaque strate a sa courbe.
- La **population connue** vient du recensement ou d'une projection validée. Elle se lit dans un champ de la couche ou se saisit dans le tableau.
- Si l'**année visée** diffère de l'année de la population connue, celle-ci y est ramenée avec un **TCAM de décalage** (par défaut, celui du scénario).

Cliquez sur **Calculer le calage** : les toits sont lus une fois. Ensuite, tous les réglages du groupe réagissent immédiatement.

## 3. Les classes de surface

| Réglage | Rôle | Défaut |
|---|---|---|
| Plancher | Les toits plus petits comptent 0 habitant (abris, annexes) | 1er percentile des surfaces |
| Plafond | Fin de la dernière classe ; les toits plus grands prennent la valeur de la dernière classe | 90e percentile |
| Exclusion | Au-delà, un toit compte 0 habitant (bâtiment non résidentiel) | 450 m² |
| Classes | Nombre de classes, entre plancher et plafond | 8 |
| Découpage | Ruptures naturelles, surfaces égales, effectifs égaux (percentiles), ou manuel | ruptures naturelles |

Plancher, plafond et exclusion peuvent être un percentile, une valeur en m², ou « aucun ».

Le graphique a deux vues :
- **Distribution** : nombre de toits par m² de surface, courbe des habitants par toit et limites des classes ;
- **Cumul** : part cumulée des toits et part cumulée de la population, avec la part de chaque classe.

Les limites de classe se **font glisser** sur le graphique : le découpage passe alors en « manuel ».

**Quel découpage choisir ?**
- Les ruptures naturelles suivent les creux de la distribution des surfaces.
- Les surfaces égales sont les plus simples à expliquer.
- Les effectifs égaux donnent le même poids à chaque classe : c'est le meilleur choix pour une régression sur plusieurs strates.

## 4. Habitants par toit

- **Habitants proposés** pour une classe = arrondi(surface moyenne des toits de la classe ÷ **surface de toit par habitant**). Le résultat reste entre le minimum et le maximum par toit, et une classe n'a jamais moins d'habitants que la précédente.
- **Ajuster au recensement** cherche la surface de toit par habitant qui redonne au mieux la population connue du groupe.
- La colonne **Habitants retenus** se modifie à la main. Chaque modification est notée dans le rapport, avec la valeur proposée.

L'**écart** à la population connue est affiché ; au-delà de **±2 %**, il est signalé.

Le **recalage** ramène exactement chaque strate à sa population connue. Son facteur est toujours calculé et affiché, mais il n'est appliqué que si la case est cochée (facteur 1 par défaut).

## 5. TCAM suggéré

Avec une **surface de toit par habitant de référence** venue d'ailleurs (autre commune calée, étude antérieure), l'année des images et celle de la population connue, l'outil suggère un TCAM :

`TCAM suggéré = (population connue ÷ population des toits)^(1 ÷ écart d'années) − 1`

S'il est très différent du TCAM par défaut, l'une des deux hypothèses est à revoir.

## 6. Mode des anciens classeurs

Pour comparer avec les anciens résultats, le mode `legacy` reproduit exactement les classeurs Excel : 139 100 habitants en rural et 33 253 en urbain à Muramvya. Il n'est accessible que par le fichier de scénario (voir la spécification, §3 ter).

## 7. Rapport

Le fichier `calibration.json`, écrit avec les résultats, contient pour chaque groupe :
- les limites et les classes ;
- les habitants proposés et retenus ;
- la surface par habitant ;
- les écarts ;
- les distributions et les cumuls ;
- les diagnostics.

## 8. Classeur Excel du calage

Le bouton **Exporter en Excel…** enregistre le calage **tel qu'il est affiché**, réglages en cours compris, dans un classeur `.xlsx`. Chaque calcul qui part des toits écrit aussi un `calage.xlsx` dans son dossier de résultats.

| Feuille | Contenu |
|---|---|
| Synthèse | Toits lus et retenus, population calculée, recalage ; un tableau par groupe et par strate : m² de toit par habitant, population calculée et connue, écart, facteurs proposé et appliqué |
| Classes – *groupe* | Limites, toits, surface moyenne, habitants proposés et retenus. La population de chaque classe est une **formule Excel** (toits × habitants) : changer un nombre d'habitants met la population à jour. Graphiques : habitants par toit selon la surface, et toits par classe |
| Distribution – *groupe* | Toits par tranche de 1 m², parts cumulées des toits et de la population, avec leurs graphiques |
| Hypothèses | Le modèle en cinq phrases, les réglages généraux et ceux de chaque groupe (plancher, plafond, découpage, surface par habitant ajustée ou saisie, valeurs modifiées à la main) |
| Sources | Toits (fichier ou base, champ de surface ; pour un téléchargement : jeu de données, version, date, licence, citation), strates, population connue, version de Poplar |

- Les graphiques sont de **vrais graphiques Excel**, liés aux cellules : on peut les modifier ou les copier dans un rapport.
- Le mot de passe d'une base de données n'apparaît jamais dans le classeur.
- En ligne de commande : `python -m engine excel <dossier de résultats>`.

