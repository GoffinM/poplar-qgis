# Recette du plugin sur votre poste

Version 0.7.0. Une seule liste, dans l'ordre des onglets. Passée entièrement une fois, elle sert de **recette de référence** ; aux versions suivantes, seules les lignes marquées dans `CHANGELOG.md` sont à repasser.

- Durée : environ 45 minutes. Les sections marquées « facultatif » ajoutent 15 minutes.
- Environnement : QGIS 3.40 LTR sous Windows, puis QGIS 4 si vous l'avez.
- Pour chaque ligne en échec, notez le numéro et ce que vous avez vu, avec une capture si possible. En cas d'erreur Python, copiez le texte complet de la fenêtre.

## 0. Préparer

1. **Plugin** : téléchargez `poplar-0.7.0.zip` :
   https://github.com/GoffinM/poplar-qgis/raw/claude/legacy-code-assessment-frf66q/dist/poplar-0.7.0.zip
2. **Jeu d'exemple** : sur GitHub, branche `claude/legacy-code-assessment-frf66q`, cliquez sur **Code › Download ZIP**, puis décompressez l'archive. Le dossier `data/test/muramvya/` contient les scénarios et les données.
3. Si une version précédente de Poplar est installée : **Extensions › Installer/Gérer les extensions › Installées › Poplar › Désinstaller**.

⚠️ Installez seulement `poplar-0.7.0.zip`, jamais l'archive complète du dépôt : QGIS la refuserait avec l'erreur « No module named 'poplar-qgis-…' ». Si c'est déjà arrivé, fermez QGIS, supprimez le dossier `poplar-qgis-…` de `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`, puis relancez QGIS.

| # | Action | Résultat attendu |
|---|---|---|
| I.1 | **Extensions › Installer depuis un ZIP** › `poplar-0.7.0.zip` | Une barre d'outils **Population** (9 boutons) et un menu **Population** apparaissent |
| I.2 | Survolez chaque bouton | Une bulle d'aide s'affiche pour chacun |
| I.3 | Bouton **À propos** | Version 0.7.0 ; crédits « Michel – SHER (contributions : Keyvan, Marine) » |

## 1. Scénario

| # | Action | Résultat attendu |
|---|---|---|
| S.1 | **Scénario › Ouvrir…** › `data/test/muramvya/scenario_muramvya.json` | La commune, la forêt et le raster sont ajoutés au projet ; les onglets sont remplis |
| S.2 | Pastilles à gauche des onglets | Pétrole : complet ; ocre : à vérifier (Paramètres, à cause d'`Urbain2`) ; cercle vide : pas utilisé |
| S.3 | Choisissez un dossier des résultats vide | — |
| S.3 bis | « Couche des mailles » | GeoPackage par défaut ; choix Shapefile, les deux, aucune |
| S.4 | **Bibliothèque… › Ajouter le scénario actuel…**, puis **Partir de ce scénario** | Le scénario est rechargé ; « Enregistrer… » demande un nouveau fichier |
| S.5 | Bouton **?** en haut à droite | La page d'aide de l'onglet s'ouvre ; la recherche fonctionne |

## 2. Données

| # | Action | Résultat attendu |
|---|---|---|
| D.1 | Parcourez l'onglet | Couches et champs renseignés ; la forêt est « Sans nouvel arrivant » |
| D.2 | Bouton **…** à côté de « Zone d'étude » › **Fichier…** › un GeoPackage à plusieurs couches | L'outil demande laquelle ; elle est ajoutée et sélectionnée. Une couche de points proposée dans une liste de polygones est refusée, avec une explication |
| D.3 | Exclusions : ajoutez une couche de **lignes** (une route) sans tampon, puis **Lancer › Vérifier le scénario** | Le contrôle demande un tampon ; avec 50 m, il passe |
| D.4 | Projections : un fichier xlsx avec une colonne par année | L'aperçu indique « Une colonne par année · … unités · années » ; testez aussi un .xls |
| D.5 | Posez un filtre sur la couche des communes (clic droit › Filtrer…), puis lancez | Le calcul ne porte que sur les entités filtrées ; retirez ensuite le filtre |

## 3. Paramètres

| # | Action | Résultat attendu |
|---|---|---|
| P.1 | Tableaux TCAM et densités | Le TCAM est le même partout ; les densités sont liées à `commune_muramvya` / `Type`, avec `Urbain2` en ocre (absent de la couche) |
| P.2 | TCAM : couche `commune_muramvya`, champ `COMMUNES` | Deux lignes et « Hors zones (défaut) » ; mettez 3,5 pour l'urbain |
| P.3 | Cochez **Croiser avec une seconde couche** | La valeur 3,5 est gardée, sur la ligne « URBAIN \| (toutes) » |
| P.4 | Seconde couche `commune_muramvya` / `Type` | Une ligne par paire commune × type |
| P.5 | Décochez **Croiser** | Retour aux deux lignes, 3,5 toujours là, **aucun avertissement ocre** |
| P.6 | **Exporter…** un tableau en xlsx, modifiez une valeur dans Excel, puis **Importer…** | La valeur modifiée apparaît |
| P.7 | Remettez le TCAM d'origine (rouvrir le scénario) | — |

## 4. Indicateurs

| # | Action | Résultat attendu |
|---|---|---|
| N.1 | Onglet **Indicateurs** | Six onglets (Dotation, Non domestique, Volume fixe, Rendement, Pointe jour., Pointe hor.), avec les valeurs du scénario |
| N.2 | Dotation : couche `commune_muramvya`, champ `Type` | Lignes « Rural » et « Urbain1 » ajoutées d'elles-mêmes ; saisissez 20 et 60 |
| N.3 | Rendement : une autre couche de polygones et un autre champ | Lignes remplies avec les valeurs de ce champ |
| N.4 | Dotation : cochez puis décochez **Croiser** | Valeurs gardées, aucun avertissement |
| N.5 | Dotation : videz « Hors zones (défaut) » et une ligne de zone, puis lancez | Le calcul s'arrête sur un message qui nomme la dotation incomplète ; remettez la valeur |

## 5. Calage

| # | Action | Résultat attendu |
|---|---|---|
| C.1 | **Scénario › Ouvrir…** › `scenario_muramvya_toits.json`, onglet **Calage** | Toits `buildings_muramvya`, surface `area_m2` ; strates `commune_muramvya` / `COMMUNES`, groupe `Type` ; population connue 136 759 et 34 251 |
| C.2 | **Calculer le calage** | « 38 942 toits lus » ; rural 16,9 m² par habitant (écart +0,05 %), urbain 12,34 m² (+0,61 %) |
| C.3 | Groupe Rural : nombre de classes, découpage (ruptures naturelles, surfaces égales, percentiles, **manuel**), plancher, plafond | Graphique, tableau et écart se mettent à jour aussitôt, sans erreur |
| C.4 | Courbe : paliers, segments, polynôme | Le dessin change avec la méthode |
| C.5 | Faites glisser une limite de classe ; modifiez un « habitant retenu » | Découpage « manuel » ; la case modifiée est colorée |
| C.6 | Vue **Cumul** | Parts cumulées des toits et de la population |
| C.7 | **Exporter le calage…**, puis **Importer un calage…** | Les réglages reviennent à l'identique |
| C.8 | **Exporter en Excel…** (après C.5, avec une case modifiée) | Le classeur s'ouvre : Synthèse, Classes et Distribution par groupe, Hypothèses, Sources ; la case modifiée est colorée, les graphiques sont des graphiques Excel |
| C.9 | Dans la feuille Classes, changez un nombre d'habitants retenus | La population de la classe et le total se recalculent |

### Téléchargement des toits (connexion Internet)

| # | Action | Résultat attendu |
|---|---|---|
| T.1 | **Télécharger les toits…** | Zone `commune_muramvya`, marge 1 km, destination `toits\google_open_buildings_commune_muramvya.gpkg` |
| T.2 | **Estimer** | « … 2 tuile(s), dont 0 déjà en cache ; 129 Mo à télécharger » (0 Mo si déjà téléchargé) |
| T.3 | Marge 0, **Télécharger** | Progression ; « ✔ Terminé : 39 126 toits… » ; « Fermer » mis en avant |
| T.4 | Fermer | Sous la couche des toits : « ✔ Toits téléchargés le … : 39 126 toits » ; **Année des images** : 2023 |
| T.5 | Rouvrir la fenêtre, **Télécharger à nouveau** | « Déjà téléchargé le … » ; une confirmation est demandée |
| T.6 | **Calculer le calage** | Rural 16,9 m² par habitant ; urbain 12,40 m², écart d'environ +1,0 % |
| T.7 | Marge 2 km, **Télécharger**, puis **Annuler** en cours de route | « Téléchargement annulé » ; aucun fichier partiel dans le cache |
| T.8 | **Source : Overture Maps**, marge 0 | Destination `toits\overture_buildings_commune_muramvya.gpkg` ; **Estimer** explique qu'il n'y a pas de tuiles à estimer |
| T.9 | **Télécharger** | La fenêtre indique « Lecture de 1 fichier(s) Overture… » puis le nombre de bâtiments lus ; moins d'une minute ; « ✔ Terminé : 39 385 toits… » (le nombre peut varier un peu avec la version mensuelle d'Overture) |
| T.9 bis | Relancez, puis **Annuler** pendant la lecture | « Annulation en cours… » puis « Téléchargement annulé » en quelques secondes ; un nouveau téléchargement peut être lancé |
| T.10 | Table attributaire de la couche | Champs `source` (google, microsoft, osm), `year`, `confidence` (Google seulement) |
| T.11 | **Calculer le calage** | Rural 16,9 m² par habitant ; urbain environ 12,5 m² |

### Toits dans une base PostGIS (facultatif)

1. Chargez les toits dans la base (OSGeo4W Shell) :
   `ogr2ogr -f PostgreSQL "PG:host=SERVEUR dbname=BASE user=UTILISATEUR" data\test\muramvya\buildings_muramvya.gpkg -nln burundi.batiments -lco SPATIAL_INDEX=GIST`
2. Dans QGIS : **Explorateur › PostgreSQL › Nouvelle connexion**, puis **Tester la connexion**.

| # | Action | Résultat attendu |
|---|---|---|
| B.1 | Bouton **…** de « Couche des toits » › **Base de données ou autre source…** › `burundi.batiments`, surface `area_m2`, puis **Calculer le calage** | Mêmes chiffres qu'en C.2 |
| B.2 | **Enregistrer…** le scénario, puis l'ouvrir dans un éditeur de texte | `"source": "PG:…"`, **sans mot de passe** |
| B.3 | Fermer QGIS, le rouvrir, **Ouvrir…** le scénario | La table est retrouvée (notez si QGIS demande le mot de passe) |

## 6. Lancer, Résultats, Rapport

| # | Action | Résultat attendu |
|---|---|---|
| L.1 | Rouvrez `scenario_muramvya.json` ; **Lancer › Vérifier le scénario** | « Scénario complet et cohérent » |
| L.2 | **Lancer le calcul** | Progression ; QGIS reste utilisable ; quelques secondes |
| L.3 | Fin du calcul | « Calcul réussi » ; groupe « Poplar – Muramvya – exemple – *date heure* » avec population et densité de **toutes les années de sortie** (2025 à 2060), seule 2060 cochée |
| L.3 bis | Dans le groupe des résultats : « mailles (tous les résultats) », décochée, sous les rasters | Table attributaire : une ligne par maille, champs `population_2024` … `population_2060`, `density_…`, `water_…` ; la somme de `population_2060` vaut 320 361 |
| L.3 ter | Onglet Scénario : « Couche des mailles » = Shapefile, relancez | Dans le dossier : `mailles.shp` (champs `pop2030`, `den2030`…) et `mailles_champs.csv` |
| L.4 | Relancez **sans rien retirer du projet** | Un second sous-dossier daté est créé, sans erreur « permission denied » |
| R.1 | Onglet **Rapport** | Statut « réussi », population de 170 565 à 320 361 habitants |
| R.2 | **Ouvrir le rapport complet (HTML)** | Page lisible dans le navigateur, avec les graphiques |
| R.3 | Onglet **Résultats** : « Eau – production moyenne », 2040, **Charger les couches** | La couche s'ajoute au groupe |
| R.4 | **Ouvrir le tableau** | `summary.csv` s'ouvre dans Excel, colonnes séparées, virgules décimales |
| R.5 | Choisissez une exécution, cochez **À conserver ★**, donnez un nom | La liste affiche ★ et le nom |
| R.6 | **Nettoyer…** | Les exécutions non conservées sont proposées, avec leur taille ; **Supprimer la sélection** retire leurs couches et efface leurs dossiers |
| R.7 | Fermez la fenêtre Poplar | La même liste est proposée (fin de session) |
| R.8 | Scénario « toits » (`scenario_muramvya_toits.json`) : lancez | Le calcul part des toits ; le rapport HTML montre le calage |
| R.9 | Dossier des résultats de ce calcul | Un `calage.xlsx` s'y trouve, à côté de `report.html` |

## 7. Manque de place

| # | Action | Résultat attendu |
|---|---|---|
| M.1 | Paramètres : densité max de `Rural` à **600**, puis lancez | Une fenêtre « Manque de place en … » propose trois solutions |
| M.2 | Choisissez une solution, **Appliquer et relancer** | Le calcul se termine ; le rapport indique l'ajustement appliqué |

## 8. Autres points

| # | Action | Résultat attendu |
|---|---|---|
| A.1 | **Traitement › Boîte à outils › Poplar › Lancer un scénario** avec `scenario_muramvya.json` | Le calcul tourne et l'aide s'affiche à droite |
| A.2 | Facultatif : QGIS en anglais (**Préférences › Général › Langue**) | Interface et rapport en anglais |
| A.3 | Facultatif : thème sombre (**Préférences › Général › Thème de l'interface › Night Mapping**, redémarrer) | La fenêtre Poplar passe en couleurs sombres |
| A.4 | Facultatif : QGIS 4 | Mêmes vérifications |
| A.5 | Facultatif, **banc de non-régression** : dans l'OSGeo4W Shell, dossier du dépôt décompressé, `python tools\banc.py --reseau` | Tableau des chiffres clés et « **Tout est conforme.** » ; résumé dans `banc.md` |
