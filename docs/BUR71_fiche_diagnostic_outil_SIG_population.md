# BUR71 – Outil SIG de croissance et migration de population
## Fiche diagnostic : état des lieux et pistes d'évolution

| | |
|---|---|
| **Projet** | BUR71, application d'un outil générique |
| **Objet** | Faire évoluer l'outil vers un plugin QGIS automatisé, robuste et paramétrable |
| **Destinataires** | Camille, Lionel |
| **Rédaction** | Michel – 29/09/2026 |
| **Statut** | Document de travail, pour discussion |

---

## 1. Rappel : ce que fait l'outil aujourd'hui

| Étape | Fonctionnement actuel |
|---|---|
| Données d'entrée | Bâti extrait d'images satellites (surfaces de toit) et recensements de population |
| Temps initial | Lien surface de toit → population par **régression polynomiale calée dans Excel**, puis production d'un **raster de densité de population** |
| Projection | Évolution du raster par **croissance** et **migration** |
| Contraintes | Zones d'exclusion, taux de croissance différenciés, **densités maximales** au-delà desquelles la population migre |
| Code | En partie PyQGIS, en partie R *(répartition exacte à confirmer)* |

**Points forts :** les résultats sont consolidés et crédibles, et la logique métier a fait ses preuves. C'est cette base qu'on protège pendant l'évolution.

---

## 2. Diagnostic

| # | Constat | Cause probable | Impact |
|---|---|---|---|
| D1 | Plantages ou lenteurs sur les gros jeux de données | Rasters chargés entièrement en mémoire, boucles cellule par cellule, fichiers intermédiaires écrits sur disque à chaque étape | La résolution doit être dégradée pour que le calcul passe, donc on perd en précision |
| D2 | Pas de calcul automatique par pas de temps (1 an ou 5 ans) | Chaque horizon est lancé manuellement | Temps passé, risque d'erreur, peu de reproductibilité |
| D3 | Taux de croissance et densités max fixés une fois pour toutes | Pas de structure de paramètres qui varient à la fois dans l'espace et dans le temps | Impossible de modéliser simplement un scénario évolutif (densification, nouveaux pôles…) |
| D4 | Pas d'interpolation entre années de référence | Les paramètres ne sont pas indexés par année | Il faut préparer chaque horizon à la main |
| D5 | Calage initial dans Excel, hors de la chaîne SIG | Régression polynomiale réalisée manuellement | Pas de traçabilité, pas de validation croisée, risque d'extrapolation hasardeuse sur les grandes surfaces de toit |
| D6 | Deux langages (PyQGIS et R) | Historique de développement | Déploiement et maintenance plus lourds, dépendance à R sur chaque poste |
| D7 | Pas d'interface unifiée | Outil sous forme de scripts | Réservé à ceux qui connaissent le code, difficile à transmettre |

---

## 3. Pistes d'évolution

### 3.1 Choix technologiques

| Sujet | Recommandation | Justification |
|---|---|---|
| Langage | **Tout en Python** (NumPy / SciPy / GDAL) | Langage natif des plugins QGIS, pas de dépendance à R, NumPy et SciPy sont déjà fournis avec QGIS |
| Code R existant | Le garder comme **référence** | Il sert à spécifier la logique et à valider le nouveau code par non-régression |
| Architecture | **Moteur de calcul séparé de l'interface QGIS** | Le moteur peut être testé, accéléré et réutilisé, y compris hors de QGIS |
| Performance | Données en float32, **traitement par blocs**, migration vectorisée, calcul **en tâche de fond** dans QGIS | Permet des mailles fines sur de grandes emprises |
| Intégration QGIS | Barre d'outils avec panneau de paramètres, plus un **algorithme Processing** | Utilisable par un non-développeur, et aussi en traitement par lots ou dans le Model Builder |
| Compatibilité | QGIS 3.40 LTR et QGIS 4 (Qt6) | Ne pas avoir à refaire le travail à court terme |

### 3.2 Paramètres variables dans l'espace et dans le temps (répond à D3 et D4)

Principe : l'utilisateur fournit une **grille ou des polygones** (à la même maille que le calcul, ou par zones homogènes), avec pour chaque entité des valeurs aux **années charnières**. Le moteur interpole et transforme ces valeurs en raster **en interne**, à chaque pas de temps. Personne n'a à fabriquer de raster à la main.

| Élément | Proposition |
|---|---|
| Format | **GeoPackage** de préférence au shapefile. Le shapefile limite les noms de champs à 10 caractères et la taille à 2 Go, et éclate les données en plusieurs fichiers. La lecture du shapefile reste acceptée |
| Structure | Une couche de géométries `zones` (identifiant `zone_id`) et une **table longue** `parametres` : `zone_id`, `annee`, `tcam` (taux de croissance annuel moyen, %), `dmax` (hab/ha), `exclusion` (0/1) |
| Interpolation | **Linéaire** entre années charnières, valeur **constante** avant la première et après la dernière année (extrapolation en option) |
| Pas de temps | Calcul annuel en interne, sorties aux années choisies (par ex. tous les 5 ans et à l'horizon du projet) |
| Contrôles automatiques | Zones qui se chevauchent ou vides, valeurs aberrantes, cohérence entre `dmax` et la densité initiale |
| Calage macro | Option de **recalage sur les projections démographiques officielles** (total national ou provincial par année), avec rapport des écarts |
| Traçabilité | Chaque scénario est enregistré dans un fichier (YAML/JSON) et versionné avec les résultats |

### 3.3 Module de calage initial, intégré et « AI-powered » (répond à D5)

| Niveau | Contenu | Remarque |
|---|---|---|
| **A – Calage statistique intégré** (socle, obligatoire) | Régression surface de toit → population **directement dans l'outil** : polynomiale, log-linéaire ou par morceaux, **par strate** (urbain / périurbain / rural, types de bâti), validation croisée, graphiques de diagnostic, détection des valeurs aberrantes | Remplace Excel. Le calcul est **déterministe et reproductible** |
| **B – Assistant IA** (optionnel, clé API fournie par l'utilisateur) | Propose une forme de modèle et une stratification, commente les diagnostics, signale les incohérences de paramètres, rédige la **note méthodologique** de calage | L'IA **propose**, le moteur **calcule**, l'utilisateur **valide**. Chaque choix est journalisé |

**Mode « apporte ta propre clé » (BYOK) : points d'implémentation**

| Point | Proposition |
|---|---|
| Fournisseurs | Anthropic (Claude), OpenAI (ChatGPT), Google (Gemini), plus un **point d'accès compatible OpenAI** qui couvre Mistral, Azure et les modèles locaux (Ollama) |
| Technique | Une interface commune et un connecteur par fournisseur, en appels HTTP directs. On évite les grosses bibliothèques difficiles à installer dans le Python de QGIS |
| Sécurité des clés | Stockage dans le **gestionnaire d'authentification chiffré de QGIS** (QgsAuthManager), jamais en clair dans les projets |
| Confidentialité | N'envoyer que des **statistiques agrégées** (échantillons de calage, indicateurs), jamais les données brutes ou géolocalisées sans accord explicite |
| Hors ligne | L'outil doit fonctionner **entièrement sans IA**. Le module B est un plus, pas une dépendance |

### 3.4 Repérage de l'extension urbaine (nouveau)

Objectif : identifier dans les résultats les cellules **urbaines dès l'état initial**, et celles qui **deviennent urbaines** au fil des années sous l'effet de la croissance et de la migration depuis les cellules urbaines voisines.

**Règles de classement (appliquées à chaque pas de temps)**

| Règle | Proposition |
|---|---|
| Critère urbain | Densité supérieure ou égale à un **seuil** (hab/ha), qui peut varier par zone ou par année via la table `parametres` |
| Contiguïté | Une cellule nouvellement urbaine est une **extension** si elle touche une cellule déjà urbaine (8 voisins). Sinon, c'est un **nouveau noyau** |
| Taille minimale | Option : une tache ne compte comme urbaine qu'au-delà d'une population ou d'une surface minimale (inspiré de la méthode « Degree of Urbanisation » de l'ONU et d'Eurostat) |
| Hystérésis | Une cellule qui devient urbaine **le reste**, ou bien on utilise deux seuils (entrée et sortie). On évite ainsi qu'elle bascule d'un statut à l'autre d'une année sur l'autre |
| Origine de la croissance | Option : suivre séparément la population venue de la **croissance naturelle** et celle venue de la **migration**, pour savoir ce qui a fait basculer la cellule |

**Codage du raster de statut** (entier sur 8 bits, un raster par horizon)

| Code | Signification |
|---|---|
| 0 | Non urbain |
| 1 | Urbain dès l'état initial |
| 2 | Devenu urbain par **extension** d'une tache existante |
| 3 | Devenu urbain comme **nouveau noyau** isolé |
| 9 | Zone d'exclusion |

**Sorties associées**

| Sortie | Usage |
|---|---|
| Raster `statut_AAAA` (codes ci-dessus) | Cartographie de l'évolution urbaine |
| Raster `annee_urbanisation` | Année où chaque cellule franchit le seuil : un seul raster suffit pour animer toute la série |
| Polygones de la **tache urbaine** par horizon | Superposition avec les réseaux d'eau potable, priorisation des extensions de réseau |
| Tableau par zone | Surface et population urbaines, taux d'urbanisation, part des extensions et des nouveaux noyaux |

**Mise en œuvre :** avec `scipy.ndimage` (dilatation et étiquetage des taches), le calcul est vectorisé et peu coûteux. Un raster sur 8 bits prend peu de place (environ 280 Mo pour 280 millions de cellules), donc on peut le traiter sur toute l'emprise d'un coup, sans découpage en blocs.

---

## 4. Architecture cible

```
Plugin QGIS
├── Interface (barre d'outils + panneau)
│   ├── Données d'entrée : bâti, recensement, zones/paramètres
│   ├── Calage initial (+ assistant IA optionnel)
│   ├── Scénario : années charnières, pas de temps, horizons de sortie
│   └── Lancement en tâche de fond, progression, journal
├── Algorithme Processing (batch / Model Builder)
└── Moteur Python (indépendant de QGIS)
    ├── calage.py        régression surface de toit → population
    ├── parametres.py    lecture GPKG, interpolation, conversion en raster
    ├── croissance.py    application du TCAM
    ├── migration.py     débordement au-delà de dmax, conservation de la population
    ├── urbanisation.py  statut urbain, extension / nouveau noyau, tache urbaine
    ├── tuiles.py        traitement par blocs avec recouvrement
    └── ia/              connecteurs BYOK (Anthropic, OpenAI, Gemini, compatibles OpenAI)
```

---

## 5. Phasage et estimation (développement assisté par IA)

Hypothèse : un ingénieur pilote le développement avec un agent de code (Claude Code ou équivalent) et valide chaque étape par des tests.

| Phase | Contenu | Durée indicative |
|---|---|---|
| 0 | Lecture du code existant, **spécification de l'algorithme de migration**, constitution d'un jeu de référence BUR71 | 1 j |
| 1 | Moteur Python : densité initiale, croissance, exclusions | 1–1,5 j |
| 2 | Paramètres variables dans l'espace et dans le temps, interpolation, pas de temps automatique, fichier de scénario | 1,5–2 j |
| 3 | Migration et traitement par blocs (performance) | 1,5–2 j |
| 4 | Module de calage intégré (niveau A) | 1–1,5 j |
| 4 bis | Repérage de l'extension urbaine (statut, année d'urbanisation, tache urbaine, statistiques) | 1–1,5 j |
| 5 | Plugin QGIS : interface, Processing, tâche de fond | 1,5–2 j |
| 6 | Assistant IA BYOK (niveau B) | 1,5–2 j |
| 7 | Non-régression par rapport aux résultats actuels, calage, installateur, documentation | 1,5–2 j |
| | **Total** | **≈ 12–16 jours ouvrés** |

Pour comparaison, un développement classique prendrait environ 3 à 4 mois. Les phases 0 à 5 (y compris 4 bis) forment un **premier livrable exploitable** ; la phase 6 peut venir ensuite.

---

## 6. Points à trancher (Camille / Lionel)

| # | Question |
|---|---|
| Q1 | Quelle est la répartition exacte entre PyQGIS et R dans le code actuel, et qui en est le référent ? |
| Q2 | Comment fonctionne précisément la migration : vers les voisins immédiats, dans un rayon donné, vers des zones attractives ? Itérations jusqu'à convergence ? Que devient l'excédent s'il ne reste plus de capacité ? |
| Q3 | Les paramètres sont-ils fournis sur une grille régulière (même maille que le calcul) ou sur des zones administratives ou d'urbanisme ? |
| Q4 | Quelles années charnières et quels horizons de sortie pour BUR71 ? |
| Q5 | Faut-il recaler sur les projections officielles ? Si oui, lesquelles ? |
| Q6 | Quelle résolution cible sur quelle emprise pour BUR71 (pour dimensionner le traitement par blocs) ? |
| Q7 | Quelle est la politique interne sur l'envoi de données vers des API d'IA externes (pour le niveau B) ? |
| Q8 | Quelle définition de l'urbain pour BUR71 : seuil de densité (hab/ha), taille minimale de tache, référence à une définition nationale (par ex. celle de l'institut de statistique du Burundi) ? |

---

## 7. Risques et parades

| Risque | Parade |
|---|---|
| Écart entre les résultats du nouveau code et ceux de l'outil actuel | Jeu de référence BUR71 et tests de non-régression avec tolérances définies |
| Erreurs sur l'API PyQGIS (fréquentes avec le code généré par IA) | Tests réels dans QGIS pour chaque version cible |
| La régression extrapole mal sur les grandes surfaces de toit | Modèles par strate, bornes de validité, diagnostic automatique |
| L'IA donne des résultats différents d'un essai à l'autre | L'IA ne fait que conseiller, le calcul reste déterministe, tout est journalisé |
| Installation difficile sur les postes Windows | Dépendances limitées à celles fournies avec QGIS, installation par un simple fichier zip |
