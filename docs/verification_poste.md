# Vérification du plugin sur votre poste

Durée : 15 à 20 minutes. Environnement : QGIS 3.40 LTR sous Windows, puis QGIS 4 si vous l'avez.

## 0. Récupérer les fichiers

1. Sur GitHub, ouvrez le dépôt `GoffinM/poplar-qgis` et choisissez la branche `claude/legacy-code-assessment-frf66q`.
2. Cliquez sur **Code › Download ZIP** et décompressez l'archive.
3. Vous y trouverez :
   - le plugin, `dist/poplar-0.1.0.zip` ;
   - le jeu d'exemple, `data/test/muramvya/`.

## 1. Installer

1. Dans QGIS : **Extensions › Installer/Gérer les extensions › Installer depuis un ZIP**.
2. Choisissez `dist/poplar-0.1.0.zip`, puis cliquez sur **Installer l'extension**.
3. ✅ Vérifiez qu'une barre d'outils **Population** (9 boutons) et un menu **Population** apparaissent.

## 2. Parcourir l'interface

| # | Action | Résultat attendu |
|---|---|---|
| 2.1 | Survolez chaque bouton de la barre d'outils | Une bulle d'aide s'affiche ; le bouton Calage est grisé (phase 6) |
| 2.2 | Cliquez sur **Scénario**, puis **Ouvrir…**, puis choisissez `data/test/muramvya/scenario_muramvya.json` | La commune, la forêt et le raster sont ajoutés au projet ; les onglets sont remplis |
| 2.3 | Parcourez les onglets Données, Paramètres et Indicateurs | Les couches, les champs, le tableau TCAM et densités max, et la forêt « Sans nouvel arrivant » sont renseignés |
| 2.4 | Onglet **Scénario** : choisissez un dossier des résultats vide | — |
| 2.5 | Cliquez sur **?** en haut à droite | La page d'aide de l'onglet s'ouvre ; la recherche fonctionne |

## 3. Calculer

| # | Action | Résultat attendu |
|---|---|---|
| 3.1 | Onglet **Lancer** : **Vérifier le scénario** | « Scénario complet et cohérent » |
| 3.2 | **Lancer le calcul** | La barre de progression avance ; QGIS reste utilisable ; fin en moins d'une minute environ |
| 3.3 | Fin du calcul | Message « Calcul réussi » ; groupe « Poplar – Muramvya – exemple » avec la population et la densité 2060, colorées |
| 3.4 | Onglet **Rapport** | Statut « réussi », population de 170 565 à 320 361 habitants |
| 3.5 | Onglet **Résultats** : cochez « Eau – production moyenne » et 2040, puis **Charger les couches** | La couche s'ajoute au groupe |
| 3.6 | **Ouvrir le tableau** | `summary.csv` s'ouvre dans Excel avec des colonnes séparées et des virgules décimales |

## 4. Manque de place (facultatif)

1. Onglet **Paramètres** : mettez la densité max de la ligne `Rural` à **600**, puis lancez le calcul.
2. ✅ Une fenêtre « Manque de place en … » propose une hausse des densités, une couronne de mailles puits ou l'enregistrement des non relocalisés.
3. Choisissez une solution, puis **Appliquer et relancer**. ✅ Le calcul se termine, et le rapport indique l'ajustement appliqué.

## 5. Autres points

| # | Action | Résultat attendu |
|---|---|---|
| 5.1 | **Traitement › Boîte à outils › Poplar › Lancer un scénario** avec `scenario_muramvya.json` | Le calcul tourne et le texte d'aide s'affiche à droite |
| 5.2 | Bouton **À propos** | La fiche s'affiche (auteurs, licence et contact encore à confirmer) |
| 5.3 | Facultatif : QGIS en anglais (**Préférences › Général › Langue**) | L'interface et le rapport passent en anglais |
| 5.4 | Facultatif : QGIS 4 | Mêmes vérifications |

## À me renvoyer

Pour chaque ligne en échec : le numéro, ce que vous avez vu, et si possible une capture d'écran. En cas de message d'erreur Python, copiez le texte complet de la fenêtre d'erreur.
