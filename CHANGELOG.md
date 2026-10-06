# Nouveautés par version

Plugin QGIS **Poplar**, outil de croissance et de migration de population (BUR71).
Les dates sont celles de la publication de la version sur la branche de travail.

## 0.8.2 – 06/10/2026 : demande recalculée sans relancer la population

- **Recalculer la demande** (onglets Indicateurs et Résultats) : la demande en eau du calcul affiché est recalculée avec les paramètres actuels, en tâche de fond, sans relancer le modèle de population. Résultats dans un sous-dossier daté `demande_AAAAMMJJ_HHMM` (rasters, `summary.csv`, couche des mailles, `demande_parametres.json`) ; la dernière demande est celle chargée dans QGIS. On peut aussi ajouter la demande à un calcul lancé sans indicateur.
- Chaque calcul garde la population de chaque morceau de maille (`populations.npz`, quelques dizaines de Ko), avec sa classe : en mode libre, une maille colonisée garde les paramètres de son nouveau polygone.
- Calculs antérieurs : la population des mailles est répartie au prorata de la surface des morceaux, avec un avertissement.
- Si les couches ne donnent plus la grille du calcul, le recalcul s'arrête et l'explique.
- En ligne de commande : `python -m engine demand <dossier> [--scenario fichier]`.

## 0.8.1 – 06/10/2026

- Mode libre : les notes « Strates libres : les polygones s'étendent… » et « nouveaux noyaux désactivés » ne sont plus montrées comme des avertissements (elles restent dans le rapport).
- Couleurs des polygones (couche « Polygones » et style du raster polygon_id) : du gris clair pour le rang le plus bas au pétrole pour le plus urbain, comme le statut urbain.

## 0.8.0 – 06/10/2026 : polygones qui évoluent dans le temps (mode libre)

- **Onglet Strates** (fiche §3.5) : mode **Planifié** (par défaut, résultats identiques à l'outil actuel) ou **Libre**. En mode libre, un polygone saturé déborde sur ses voisines, qui prennent son identité et ses paramètres ; la vitesse des fronts est un résultat.
  - Règles : maille saturée, export minimal du colonisateur, part saturée du colonisateur, 3 voisines sur 8, rang supérieur ; exclusions et strates non colonisables protégées ; une couronne au plus par an ; pas interne annuel.
  - Rangs, colonisable, flux minimal et part saturée par strate ; nouveaux noyaux (désactivés par défaut, 16 mailles minimum, diagnostic « à vérifier »).
- **Taches bâties** : bouton **Préparer les taches bâties…** (carte, tableau, seuils) qui remplace la typologie administrative par les taches denses (1 500 hab/km², 5 000 habitants) et une strate Transition ; retour possible à la typologie d'origine. En ligne de commande : `python -m engine patches`.
- **Sorties du mode libre** : `polygon_id_AAAA.tif`, `statut_AAAA.tif`, `annee_colonisation.tif`, `polygones.gpkg` (polygones lissés, extensions, généalogie), champs de `mailles.gpkg`, `plausibilite.csv` (vitesse des fronts, étalement ou densification, compacité, nouveaux noyaux, effet de reclassement, bilan de masse) et section du rapport.
- **Comparaison des deux modes** : bouton **Comparer avec un calcul planifié…** (onglet Résultats) et `python -m engine compare`.
- Contrôle de conservation de la population à chaque pas, dans les deux modes.
- Banc de non-régression : cas `muramvya_libre`. Aide : page « Strates ». Liste de vérification : section 2 bis.

## 0.7.2 – 30/09/2026

- **Overture deux fois plus rapide** : les bâtiments sont traités par paquets de 5 000, au lieu d'un par un. Pour Muramvya, on passe ici de 25 s à 12,5 s, avec exactement les mêmes bâtiments.
- Crédits : Assoumpta et Sophie rejoignent les contributeurs.
- Outils de diagnostic du téléchargement : `tools/test_debit.py` (débit vers Overture et Google) et `tools/diag_overture.py` (temps de lecture par GDAL seul), réunis dans `dist/outils_diagnostic.zip`.

## 0.7.1 – 30/09/2026

- **Couche des mailles à la demande** : bouton **Générer** dans l'onglet Scénario. Il écrit la couche de l'exécution choisie dans le format voulu, sans relancer le calcul : moins d'une seconde pour Muramvya, contre 6 s pour un calcul. On peut donc lancer les calculs avec « Aucune » et ne générer la couche qu'au besoin.
- Chaque calcul garde un petit fichier `mailles_base.npz` (12 Ko pour Muramvya) qui rend cette génération immédiate. Pour un calcul plus ancien, la grille est redécoupée une fois.
- Ligne de commande : `python -m engine grid <dossier>`.

## 0.7.0 – 30/09/2026 : version du beta testing

- **Couche des mailles** (`mailles.gpkg`) : toutes les mailles de la zone d'étude, vides comprises, avec tous les résultats de chaque année de sortie (population, densité, capacité, non relocalisés, indicateurs), la classe et l'unité administrative. Elle est chargée dans le groupe des résultats. Le format se choisit dans l'onglet Scénario : GeoPackage par défaut, Shapefile en option (avec une table des noms de champs), les deux, ou aucune.
- Aide : fiche « Changement d'affectation planifié : ce qui est possible aujourd'hui », avec ses limites.
- Reste à faire : décisions du 30/09 sur les catégories qui changent dans le temps (extension urbaine et changements planifiés, à concevoir ensemble après le beta).

## 0.6.0 – 30/09/2026

- **Export Excel du calage** : bouton **Exporter en Excel…** de l'onglet Calage, qui enregistre le calage tel qu'il est affiché, réglages en cours compris. Chaque calcul qui part des toits écrit aussi un `calage.xlsx`.
  - Feuilles : Synthèse, Classes et Distribution de chaque groupe, Hypothèses, Sources.
  - Graphiques Excel natifs ; la population de chaque classe est une formule Excel.
  - Aucune dépendance ajoutée : le fichier est écrit directement.
- Ligne de commande : `python -m engine excel <dossier>`.

## 0.5.1 – 30/09/2026

- **Overture beaucoup plus rapide** : un index des fichiers de chaque version d'Overture, fourni avec le plugin et publié sur GitHub, évite d'interroger les 512 fichiers. On passe de 360 Mo et plus d'une demi-heure à environ 50 Mo pour Muramvya.
- **Annuler** arrête vraiment le téléchargement, et on peut relancer ensuite.
- La fenêtre dit ce qui se passe : recherche des fichiers, puis nombre de bâtiments lus.
- Lecture Overture fiable avec le GDAL 3.10 de QGIS 3.40 (champ `sources` complet).

## 0.5.0 – 30/09/2026

- **Overture Maps** comme seconde source de toits, dans la même fenêtre de téléchargement (liste **Source**).
  - Google, Microsoft et OpenStreetMap sont fusionnés sans doublons, et lus à distance pour la zone seulement : environ une minute pour une province.
  - Chaque toit garde sa source, son année, sa confiance (Google) et son type et sa hauteur (OpenStreetMap).
  - Muramvya : 39 385 bâtiments ; calage rural 16,9 et urbain 12,5 m² par habitant.
- Banc de non-régression : cas `telechargement_overture` (réseau et pilote Parquet).

## 0.4.0 – 30/09/2026 : version de référence

Consolidation avant les chantiers suivants (Overture, export Excel, rapport client) :

- **Banc de non-régression** (`tools/banc.py`) : les cas de référence de Muramvya et leurs chiffres clés, comparés aux valeurs attendues, avec un résumé `banc.md`. Cas couverts : raster → 2060, toits en mode « classeurs », toits avec le modèle actuel, téléchargement Google (option `--reseau`). Il tourne aussi avec les tests.
- Onglet Calage : le champ « ou fichier Open Buildings » est retiré, puisque le téléchargement le remplace. La tuile CSV d'un ancien scénario est gardée et affichée sous la couche des toits.
- Tableaux de paramètres (TCAM, densités, indicateurs) : cocher ou décocher « Croiser » ne perd plus les valeurs et ne laisse plus d'avertissement « Absent de la couche ».
- Toits téléchargés : l'année des images est remplie d'office (2023, version v3 de Google Open Buildings).
- **Relecture du code**, avec correction de sept défauts :
  - un téléchargement raté ou annulé n'abîme plus les toits déjà téléchargés ;
  - une tuile reçue incomplète n'est plus gardée en cache ;
  - télécharger à nouveau libère la couche avant de remplacer le fichier, ce qui évite l'erreur « permission denied » sous Windows ;
  - une couche de zones introuvable ne fait plus perdre les valeurs à l'enregistrement ;
  - les valeurs croisées reviennent quand on recoche « Croiser » ;
  - seules des valeurs numériques sont saisissables dans les tableaux ;
  - fichiers toujours refermés.
- Réglages de compatibilité avec QGIS 4 (énumérations qualifiées).
- Liste de vérification sur le poste réécrite en une seule recette, par onglet.

## 0.3.7 – 30/09/2026

- **Indicateurs** : chaque paramètre de l'eau (dotation, part non domestique, volume fixe, rendement, pointes) a son propre onglet, lié à sa propre couche, avec deux couches croisées au besoin. Les lignes se remplissent avec les valeurs du champ : on ne tape plus de noms.

## 0.3.6 – 30/09/2026

- Téléchargement des toits : fin de téléchargement affichée clairement, « Fermer » mis en avant, confirmation avant de télécharger à nouveau ; dans l'onglet Calage, « ✔ Toits téléchargés le … ».

## 0.3.5 – 30/09/2026

- **Téléchargement des toits de Google Open Buildings v3** depuis l'onglet Calage. On règle la zone (les strates), une marge, une limite facultative, le format (points ou polygones) et le seuil de confiance. Les tuiles sont gardées dans un cache, et un rapport indique la source, la date, les comptes et la licence.
- Contrôle sur Muramvya : 38 936 des 38 942 toits des classeurs retrouvés à l'identique.

## 0.3.4 – 30/09/2026

- Calage : plus d'erreur au passage en découpage « manuel » ; la courbe dessinée suit la méthode choisie (paliers, segments, polynôme).
- Après un calcul, toutes les années de sortie demandées sont chargées, et seule la dernière est cochée.

## 0.3.1 à 0.3.3 – 29/09/2026

- Raster inaccessible ignoré quand la population vient des toits ; messages qui nomment le réglage fautif et son onglet.
- Chemins réseau (`\\serveur\…`) et shapefiles ouverts par leur `.shx` ; crédits.

## 0.3.0 – 29/09/2026

- **Onglet Calage** : la population de départ est calculée à partir des toits.
  - Habitants entiers par toit, selon la classe de surface.
  - Classes entre un plancher et un plafond, avec un découpage automatique ou manuel sur un graphique.
  - Surface de toit par habitant ajustée au recensement, avec une alerte à ±2 %.
  - Vues Distribution et Cumul.
- **Rapport HTML** autonome (`report.html`), avec graphiques.
- Toits lus depuis un fichier ou une base PostGIS, sans enregistrer le mot de passe.

## 0.2.0 – 29/09/2026

- TCAM et densités maximales liés à leurs propres couches, avec croisement possible de deux couches.
- Projections lues depuis des classeurs xlsx, xls ou ods ; bibliothèque de scénarios.
- Nouvelle charte graphique ; un dossier daté par exécution, exécutions à conserver et nettoyage.
- Zones d'exclusion en lignes et en points, avec tampon.

## 0.1.0 – 29/09/2026

- Premier plugin QGIS sur le moteur Python : scénario, croissance, migration, non-convergence, demande en eau, rapports.
