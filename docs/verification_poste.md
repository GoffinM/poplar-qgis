# Vérification du plugin sur votre poste

Version 0.2.2. Si une version précédente est installée, désinstallez-la d'abord (**Extensions › Installer/Gérer les extensions › Installées › Poplar › Désinstaller**), puis installez la nouvelle.

Durée : 20 à 25 minutes. Environnement : QGIS 3.40 LTR sous Windows, puis QGIS 4 si vous l'avez.

## 0. Récupérer les fichiers

Deux fichiers sont nécessaires : **le plugin** (un petit zip) et **le jeu d'exemple**.

1. **Plugin** : téléchargez directement `poplar-0.2.2.zip` :
   https://github.com/GoffinM/poplar-qgis/raw/claude/legacy-code-assessment-frf66q/dist/poplar-0.2.2.zip
2. **Jeu d'exemple** : sur GitHub, branche `claude/legacy-code-assessment-frf66q`, cliquez sur **Code › Download ZIP**, puis **décompressez** l'archive. Le dossier `data/test/muramvya/` contient le scénario et les données.

⚠️ **N'installez pas dans QGIS l'archive complète du dépôt** (`poplar-qgis-claude-legacy-code-assessment-frf66q.zip`). Ce n'est pas un plugin : QGIS refuse alors de le charger, avec l'erreur « No module named 'poplar-qgis-…/plugin/poplar' ». Le seul fichier à installer est `poplar-0.2.2.zip`, que l'on trouve aussi, une fois l'archive du dépôt décompressée, dans son dossier `dist/`.

**Si cette erreur est déjà apparue**, supprimez d'abord l'installation ratée :
1. Fermez QGIS.
2. Supprimez le dossier `poplar-qgis-claude-legacy-code-assessment-frf66q` situé dans `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\` (collez ce chemin dans la barre d'adresse de l'explorateur Windows).
3. Relancez QGIS.

## 1. Installer

1. Dans QGIS : **Extensions › Installer/Gérer les extensions › Installer depuis un ZIP**.
2. Choisissez `dist/poplar-0.2.2.zip`, puis cliquez sur **Installer l'extension**.
3. ✅ Vérifiez qu'une barre d'outils **Population** (9 boutons) et un menu **Population** apparaissent.

## 2. Parcourir l'interface

| # | Action | Résultat attendu |
|---|---|---|
| 2.1 | Survolez chaque bouton de la barre d'outils | Une bulle d'aide s'affiche ; le bouton Calage est grisé (phase 6) |
| 2.2 | Cliquez sur **Scénario**, puis **Ouvrir…**, puis choisissez `data/test/muramvya/scenario_muramvya.json` | La commune, la forêt et le raster sont ajoutés au projet ; les onglets sont remplis |
| 2.3 | Parcourez les onglets Données, Paramètres et Indicateurs | Les couches, les champs et la forêt « Sans nouvel arrivant » sont renseignés. Paramètres : deux tableaux ; le TCAM est le même partout, les densités sont liées à `commune_muramvya` / `Type`, avec `Urbain2` signalé en ocre (absent de la couche) |
| 2.3 bis | Pastilles à gauche des onglets | Pétrole : complet ; ocre : à vérifier (Paramètres, à cause d'`Urbain2`) ; cercle vide : pas encore utilisé |
| 2.4 | Onglet **Scénario** : choisissez un dossier des résultats vide | — |
| 2.5 | Cliquez sur **?** en haut à droite | La page d'aide de l'onglet s'ouvre ; la recherche fonctionne |

## 3. Calculer

| # | Action | Résultat attendu |
|---|---|---|
| 3.1 | Onglet **Lancer** : **Vérifier le scénario** | « Scénario complet et cohérent » |
| 3.2 | **Lancer le calcul** | La barre de progression avance ; QGIS reste utilisable ; fin en moins d'une minute environ |
| 3.3 | Fin du calcul | Message « Calcul réussi » ; groupe « Poplar – Muramvya – exemple – *date heure* » avec la population et la densité 2060, colorées. Les résultats sont dans un sous-dossier daté du dossier choisi |
| 3.3 bis | Relancez le calcul **sans rien retirer du projet** | Plus d'erreur « permission denied » : un second sous-dossier daté est créé |
| 3.4 | Onglet **Rapport** | Statut « réussi », population de 170 565 à 320 361 habitants |
| 3.5 | Onglet **Résultats** : cochez « Eau – production moyenne » et 2040, puis **Charger les couches** | La couche s'ajoute au groupe |
| 3.6 | **Ouvrir le tableau** | `summary.csv` s'ouvre dans Excel avec des colonnes séparées et des virgules décimales |

## 4. Nouveautés de la version 0.2.0

| # | Action | Résultat attendu |
|---|---|---|
| 4.1 | Onglet **Résultats** : choisissez une exécution dans la liste, cochez **À conserver ★** et donnez-lui un nom | La liste affiche ★ et le nom |
| 4.2 | **Nettoyer…** | Les exécutions non conservées sont cochées « Supprimer », avec leur taille ; **Supprimer la sélection** retire leurs couches du projet puis efface leurs dossiers |
| 4.3 | Lancez un calcul, puis fermez la fenêtre Poplar | La même liste est proposée (fin de session) |
| 4.4 | Onglet **Paramètres**, TCAM : choisissez la couche `commune_muramvya` et le champ `COMMUNES` | Deux lignes (les deux communes) et la ligne « Hors zones (défaut) » ; mettez 3,5 pour l'urbain et lancez |
| 4.5 | Cochez **Croiser avec une seconde couche**, choisissez `commune_muramvya` / `Type` | Une ligne par paire commune × type |
| 4.6 | **Exporter…** un tableau en xlsx, modifiez une valeur dans Excel, puis **Importer…** | La valeur modifiée apparaît |
| 4.7 | Onglet **Données**, exclusions : ajoutez une couche de **lignes** (une route) sans tampon, puis **Vérifier le scénario** | Le contrôle demande un tampon ; avec 50 m, le calcul passe |
| 4.8 | Onglet **Données**, projections : choisissez un fichier xlsx avec une colonne par année (par exemple une projection de l'ISTEEBU par commune) | L'aperçu indique « Une colonne par année · 2 unités · années » ; testez aussi un fichier .xls |
| 4.9 | **Bibliothèque…** › **Ajouter le scénario actuel…**, puis **Partir de ce scénario** | Le scénario est rechargé ; « Enregistrer… » demande un nouveau fichier |
| 4.11 | Onglet **Données** : bouton **…** à côté de « Zone d'étude » › **Fichier…**, choisissez un GeoPackage qui contient plusieurs couches | L'outil demande laquelle ; elle est ajoutée au projet et sélectionnée. Une couche de points dans une liste de polygones est refusée avec une explication |
| 4.12 | Bouton **…** › **Base de données ou autre source…** : une table PostGIS de vos connexions | La table est ajoutée et sélectionnée ; après **Enregistrer…**, le fichier .json ne contient pas le mot de passe |
| 4.13 | Posez un filtre sur la couche des communes (clic droit › Filtrer…), puis lancez | Le calcul ne porte que sur les entités filtrées |
| 4.10 | Facultatif : un thème sombre (**Préférences › Général › Thème de l'interface › Night Mapping**, puis redémarrer QGIS) | La fenêtre Poplar passe en couleurs sombres |

## 5. Manque de place (facultatif)

1. Onglet **Paramètres** : mettez la densité max de la ligne `Rural` à **600**, puis lancez le calcul.
2. ✅ Une fenêtre « Manque de place en … » propose une hausse des densités, une couronne de mailles puits ou l'enregistrement des non relocalisés.
3. Choisissez une solution, puis **Appliquer et relancer**. ✅ Le calcul se termine, et le rapport indique l'ajustement appliqué.

## 6. Autres points

| # | Action | Résultat attendu |
|---|---|---|
| 5.1 | **Traitement › Boîte à outils › Poplar › Lancer un scénario** avec `scenario_muramvya.json` | Le calcul tourne et le texte d'aide s'affiche à droite |
| 5.2 | Bouton **À propos** | La fiche s'affiche (auteurs, licence et contact encore à confirmer) |
| 5.3 | Facultatif : QGIS en anglais (**Préférences › Général › Langue**) | L'interface et le rapport passent en anglais |
| 5.4 | Facultatif : QGIS 4 | Mêmes vérifications |

## À me renvoyer

Pour chaque ligne en échec : le numéro, ce que vous avez vu, et si possible une capture d'écran. En cas de message d'erreur Python, copiez le texte complet de la fenêtre d'erreur.
