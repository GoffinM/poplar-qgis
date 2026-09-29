# Prise en main

Cette page déroule un premier calcul sur le jeu d'exemple de Muramvya, fourni avec le projet.

## 1. Ouvrir le scénario d'exemple

1. Dans la barre d'outils **Population**, cliquez sur **Scénario**.
2. Cliquez sur **Ouvrir…** et choisissez `scenario_muramvya.json`.
3. Les couches du scénario (commune, forêt, raster de population) sont ajoutées au projet si elles n'y sont pas déjà.

## 2. Vérifier les données et les paramètres

- **Scénario** : nom, langue du rapport, dossier des résultats, taille de maille (250 m) et système de calcul, qui doit être en mètres.
- **Données** : zone d'étude, typologie et son champ (`Type`), unités administratives, raster de population et son contenu (densité ou nombre d'habitants par pixel), zones d'exclusion (la forêt est « sans nouvel arrivant »).
- **Paramètres** : années (2024 → 2060), pas de temps, TCAM et densités maximales par classe, réglages de la migration.
- **Indicateurs** : demande en eau potable (dotation, rendement, pointes).

Passez la souris sur un libellé pour lire sa bulle d'aide. Le bouton **?** en haut de la fenêtre ouvre la page d'aide de l'onglet affiché.

## 3. Lancer le calcul

1. Onglet **Lancer** : cliquez sur **Vérifier le scénario**. Chaque problème est signalé avec l'entrée à corriger.
2. Cliquez sur **Lancer le calcul**. Le calcul se fait en arrière-plan : QGIS reste utilisable, et le calcul peut être annulé.
3. Si la place manque, une fenêtre propose des solutions (voir **Non-convergence : que faire ?**).

## 4. Consulter les résultats

- À la fin du calcul, la population et la densité de l'horizon final sont chargées dans un groupe « Poplar – *nom du scénario* ».
- Onglet **Résultats** : choisissez d'autres grandeurs et d'autres années à charger, ouvrez le tableau `summary.csv` ou le dossier.
- Onglet **Rapport** : statut, bilans de chaque pas de temps, avertissements.

## 5. Enregistrer

Cliquez sur **Enregistrer…** pour garder tous les réglages dans un fichier `.json`. Le même fichier peut être lancé depuis la boîte à outils de traitement (**Poplar › Lancer un scénario**), dans un traitement par lots ou dans le Model Builder.
