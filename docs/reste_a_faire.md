# Reste à faire (état au 29/09/2026, version 0.3.3)

## 0. Test sur le poste (30/09, réseau SHER reconnecté)

- Calage de Muramvya avec les données locales ou réseau (sections 4 bis et 4 ter de `verification_poste.md`), ou avec `data/test/muramvya/scenario_muramvya_toits.json`.
- Réglage à vérifier : **Strates** = champ `COMMUNES`, **Groupe de régression** = `Type` (et non l'inverse).
- Corrections selon les retours.

## 1. Calage : compléments de l'interface

- Choix de la **source des habitants par classe** dans l'onglet Calage : surface de toit par habitant (actuel), **régression multiple** sur les strates (déjà dans le moteur, pas encore proposée dans l'onglet), ou saisie.
- Affichage de la qualité de la régression (R², écarts par strate) dans l'onglet.

## 2. Téléchargement automatique des toits (plan à soumettre avant de coder)

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

## 5. Plus tard

- **Extension urbaine** (phase 6 bis) : attend la définition de l'urbain (Q8).
- **Langues** supplémentaires : es, pt, ar, sw, rw, rn, ru, uk.
- **Assistant IA** (phase 7, BYOK) : attend la politique d'envoi des données (Q7).
