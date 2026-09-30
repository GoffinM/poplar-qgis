# Reste à faire (état au 30/09/2026, version 0.3.5)

## 0. Retour de test du 30/09 (corrigé en 0.3.4)

- Calage validé sur le poste (mêmes résultats), exécution rapide.
- Corrigé : erreur Python au passage du découpage en « manuel » ; courbe toujours dessinée en paliers (segments et polynôme s'affichent maintenant) ; après un calcul, **toutes les années de sortie** sont chargées (la dernière cochée).

## 1. Calage : compléments

- **Régression par strate** (précision du 30/09) : une courbe par groupe de strates (rural, urbain), calée **uniquement sur le total recensé**. C'est ce que fait déjà l'onglet : la forme de la courbe vient d'une hypothèse (habitants proportionnels à la surface de toit, entiers, entre 1 et 15), et seul son niveau (la surface de toit par habitant) est ajusté au total. La régression multiple sur plusieurs strates reste dans le moteur, mais n'est plus prévue dans l'onglet.
- **Export Excel** du calage : classeur .xlsx mis en forme, avec **graphiques Excel natifs** (distribution des surfaces, courbe d'habitants par toit, cumul), écrit sans nouvelle dépendance. Plan de contenu à soumettre.
- **Rapport client Word** : plus tard, selon le modèle fourni par la SHER.

## 2. Téléchargement automatique des toits (`plan_telechargement_toits.md`, validé le 30/09)

- Fait : moteur Google Open Buildings (tuiles, zone avec marge et limite, cache, rapport) et contrôle sur Muramvya.
- Fait aussi : fenêtre du plugin (étape 3, version 0.3.5), à tester sur le poste (section 4 quater de `verification_poste.md`).
- Reste : Overture (étape 4), puis version 0.4.0.
- Bouton « Télécharger les toits de la zone d'étude » dans l'onglet Calage.
- Sources : **Google Open Buildings v3** (priorité, décision B1), puis **Overture Maps** (si le GDAL de QGIS lit le Parquet distant), éventuellement Microsoft Building Footprints.
- Emprise de la zone d'étude, téléchargement en tâche de fond (progression, annulation), cache local réutilisable (GeoPackage), rapport de ce qui a été téléchargé (source, date, version, nombre de toits).

## 3. Grandes bases PostGIS

- Centroïde et surface calculés **par le serveur** (`ST_Centroid`, `ST_Area`) : seuls des points et des nombres transitent.
- Mesure de performance sur plusieurs millions de toits.

## 4. Recette et documentation (phase 8)

- Non-régression complète contre `reference_outputs/`, test sous **QGIS 4 (Qt6)**, performance sur une emprise nationale.
- Aide en **anglais** (seul le français existe), bilan de la phase 6, README.
- Fiche À propos : **organisme, licence, contact** à confirmer.

## 5. Planifié après les chantiers en cours (note de suivi du 30/09, §3.4 et §3.5)

Ces deux points ne seront attaqués qu'une fois les sections 1 à 4 terminées. Un plan sera soumis avant tout code.

### 5.1 Strates dynamiques (§3.5, prioritaire)

- La strate (rural, urbain…) devient une **variable d'état** qui évolue à chaque pas, au lieu d'être fixée une fois pour toutes.
- Deux modes : **Planifié** (les transitions suivent un plan) et **Libre** (elles suivent des règles de densité) ; surplus redistribué ou compté comme non accueilli.
- Hiérarchie des strates et **table des transitions** : `seuil_densite`, `voisins_min`, `duree_min`, `reversible`.
- Polygones redessinés à chaque sortie (filtre majoritaire, `SieveFilter`, `Polygonize`, lissage de Chaikin) ; la grille reste la référence du calcul.
- Identité et **généalogie des taches** : `id_tache`, événements, table `genealogie`, rasters `strate_AAAA` et `annee_changement_strate`.
- Point d'architecture : aujourd'hui la classe de typologie est lue une fois par unité de calcul (`units.codes["class"]`) et tous les paramètres liés à la typologie (TCAM, densités, plafonds) en dépendent. Il faudra la recalculer à chaque pas et relire les paramètres en conséquence. C'est le cœur du chantier.

### 5.2 Extension urbaine (§3.4)

- Seuil de densité, contiguïté à 8 voisins, taille minimale, **hystérésis**.
- Raster de statut (codes 0/1/2/3/9), raster `annee_urbanisation`, polygones des taches urbaines, tableau par zone (`scipy.ndimage`).
- Recouvre en partie 5.1 : l'extension urbaine peut devenir un cas particulier des strates dynamiques (transition rural → urbain). À trancher dans le plan.

## 6. Plus tard

- **Langues** supplémentaires : es, pt, ar, sw, rw, rn, ru, uk.
- **Assistant IA** (phase 7, BYOK) : attend la politique d'envoi des données (Q7).
