# Reste à faire (état au 06/10/2026, version 0.8.0)

## 0. Version de référence 0.4.0 (30/09)

- Consolidation faite : banc de non-régression (`tools/banc.py`), recette unique par onglet (`verification_poste.md`), `CHANGELOG.md`, relecture du code et corrections.
- **À faire de votre côté** : passer la recette entière une fois. Elle devient la référence.
- Points relevés à la relecture, non bloquants, laissés pour plus tard :
  - « Estimer » attend la réponse du serveur sans rendre la main à QGIS : quelques secondes au plus ;
  - un proxy authentifié par le gestionnaire d'authentification de QGIS n'est pas encore pris en charge (pas de proxy à la SHER).

## 1. Calage : compléments

- **Régression par strate** (précision du 30/09) : une courbe par groupe de strates (rural, urbain), calée **uniquement sur le total recensé**. C'est ce que fait déjà l'onglet : la forme de la courbe vient d'une hypothèse (habitants proportionnels à la surface de toit, entiers, entre 1 et 15), et seul son niveau (la surface de toit par habitant) est ajusté au total. La régression multiple sur plusieurs strates reste dans le moteur, mais n'est plus prévue dans l'onglet.
- Fait (0.6.0) : **export Excel** du calage, avec graphiques Excel natifs (bouton de l'onglet Calage et `calage.xlsx` à chaque calcul).
- **Rapport client Word** : plus tard, selon le modèle fourni par la SHER.

## 1 bis. Indicateurs

- Fait (0.3.7) : chaque paramètre de l'eau est lié à sa propre couche (liste déroulante des valeurs, croisement de deux couches), comme le TCAM.
- **Besoins non domestiques tirés de l'affectation des bâtiments** (réponses du 30/09, besoins réels encore à connaître) :
  - un volume **par m² de toit** et par jour, pour chaque catégorie d'usage, sommé par maille ;
  - un volume **qui peut évoluer dans le temps** : valeurs par année, comme les autres paramètres ;
  - les toits dont le coefficient d'habitat vaut 0 sont **gardés pour ce calcul**, mais ne comptent pas d'habitants.
  - À coder quand les besoins seront connus ; plan à soumettre.

## 2. Téléchargement automatique des toits (`plan_telechargement_toits.md`, validé le 30/09)

- Fait : moteur Google Open Buildings (tuiles, zone avec marge et limite, cache, rapport) et contrôle sur Muramvya.
- Fait aussi : fenêtre du plugin (étape 3, version 0.3.5), à tester sur le poste (section 4 quater de `verification_poste.md`).
- Fait aussi : Overture Maps (étape 4, version 0.5.0), avec index des fichiers (0.5.1).
- **Chaque mois**, à la sortie d'une version d'Overture : lancer `python tools/overture_index.py`, puis faire le commit et le push de l'index. Sinon, le plugin prend la version précédente tant qu'Overture la garde en ligne (deux ou trois mois). Cette tâche pourra être automatisée par une action GitHub mensuelle, si vous le souhaitez.
- **Vitesse d'Overture** (mesures du 30/09 sur le poste) : le débit n'est pas en cause, puisque le test donne 2,7 Mo/s vers Overture comme vers Google, et 5 Mo/s avec huit requêtes en parallèle. Avec la 0.7.2 (traitement par paquets), il faut un peu plus de 10 s pour démarrer et un peu plus d'une minute au total pour Muramvya. GDAL seul, lancé depuis la console de QGIS, met 228 s pour la même lecture, contre 6 s ici. **Google reste la source prioritaire** ; Overture est une source d'appoint. Piste si besoin : télécharger en parallèle les morceaux utiles du fichier Parquet, puis les lire en local (gain attendu d'un facteur 2 au moins).
- **À prévoir (pas de modification pour l'instant)** : **le téléchargement ne doit pas bloquer l'utilisateur**. Il devrait se poursuivre en tâche de fond pendant qu'on saisit les données, les paramètres, les indicateurs… Aujourd'hui, la fenêtre de téléchargement est modale. Il faudra une fenêtre non modale, ou une progression dans la barre des tâches de QGIS, avec une notification à la fin, et interdire seulement ce qui dépend des toits en cours de téléchargement (calage, lancement d'un calcul à partir des toits).
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

## 4 bis. Chantier prioritaire (06/10) : évolution des polygones dans le temps, mode libre

- Plan : `plan_polygones_libres.md`. Étapes 1 à 5 faites (moteur, sorties, indicateurs de plausibilité, comparaison des deux modes, cas Muramvya au banc).
- Bilan et **décisions demandées** (D1 polygones de départ en taches bâties, D2 réglage des nouveaux noyaux, D3 valeurs par défaut) : `bilan_polygones_libres.md`.
- D1 fait (taches bâties : `python -m engine patches`, bilan §5). Plausibilité des fronts sur Muramvya à juger (P14).
- Étape 6 faite (version 0.8.0) : onglet Strates, taches bâties, résultats et comparaison dans le plugin.
- **Suite (06/10)** : (A) recalculer la demande seule sur un calcul déjà fait, puis (B) attraction des routes pour des fronts non circulaires (P14). Plan : `plan_demande_et_routes.md`. **A fait en 0.8.2**, avec le téléchargement des routes OpenStreetMap (onglet Données ; essai réel à faire sur poste, les serveurs Overpass étant bloqués depuis l'environnement de développement). **B en attente de validation.**

## 5. Catégories qui changent dans le temps : extension urbaine et changements planifiés (après le beta)

Retours des collègues et décisions du 30/09/2026. Les notes de suivi §3.4 et §3.5 restent la référence détaillée.

- **Un seul mécanisme pour deux besoins.** La catégorie d'une maille (rural, urbain, camp, village…) devient un état qui peut changer à chaque pas. Deux modes pilotent ce changement :
  - **par le modèle** : extension progressive des taches urbaines, par la migration vers les mailles voisines (seuil de densité, contiguïté, taille minimale, hystérésis ; note §3.4) ;
  - **par l'utilisateur** : changements planifiés, par exemple un camp de déplacés qui ferme en 2030 et devient village ou centre urbain secondaire.
  - **(i) et (iii) sont conçus et développés ensemble**, après les retours du beta testing.
- **Décisions déjà prises :**
  - **Option** : le calcul relit chaque maille à chaque pas, ce qui l'alourdit. C'est donc une option, désactivée par défaut, avec un bouton qui prévient de ce coût.
  - **Priorité** : les changements planifiés par l'utilisateur **priment** sur ceux du modèle. Par exemple, un camp n'est jamais une zone de débordement de l'urbain.
  - **Fermeture d'un camp** : la densité maximale baisse, et la population en excès **migre progressivement** vers d'autres mailles. Ce n'est ni une évacuation immédiate, ni un maintien sur place.
  - **Hiérarchie des catégories** : à organiser proprement. Il s'agit de dire quels passages sont permis et lesquels sont interdits, par exemple une zone réservée qui ne peut pas devenir urbaine.
- **Constat du 30/09** (vérifié sur un cas d'essai) : aujourd'hui, quand la densité maximale d'une zone baisse sous sa population, les habitants en trop **restent sur place** ; seules la croissance et les arrivées sont redirigées. La migration progressive du surplus à la fermeture d'un camp est donc une **règle nouvelle** du moteur, à concevoir : rythme de départ, destination, priorité par rapport à la croissance.
- **Sorties prévues** : la catégorie de chaque maille par année, l'année de changement, et les polygones des taches par date de sortie (lissés ; la grille reste la référence du calcul).
- **En attendant**, dans la version du beta : un changement planifié peut être imité avec des paramètres liés à la zone et variables dans le temps (TCAM, densité maximale), avec deux années proches pour un changement net.
- **Point d'architecture** : aujourd'hui, la catégorie est lue une fois par unité de calcul (`units.codes["class"]`), et le TCAM, la densité maximale et la capacité en dépendent. Il faudra la recalculer à chaque pas. C'est le cœur du chantier ; le banc de non-régression garantira qu'un calcul sans changement de catégorie reste identique.
- **Plan détaillé** : `plan_categories_dynamiques.md` (règles, table des changements planifiés, hiérarchie, sorties, étapes). Questions Q1 à Q10 tranchées le 30/09 ; à lancer après les retours du beta.

## 6. Plus tard

- **Zones à population planifiée** : par exemple un camp dont la population est connue ou prévue chaque année, imposée au modèle au lieu d'être calculée. Cas récurrent, laissé ouvert le 30/09 (plan des catégories dynamiques, Q10).

- **Langues** supplémentaires : es, pt, ar, sw, rw, rn, ru, uk.
- **Assistant IA** (phase 7, BYOK) : attend la politique d'envoi des données (Q7).
