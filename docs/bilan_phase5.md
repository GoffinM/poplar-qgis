# Bilan de la phase 5 : plugin QGIS

| | |
|---|---|
| **Date** | 29/09/2026 |
| **Statut** | Plugin fonctionnel et testé dans QGIS 3.34 (sans affichage) ; **vérification sur votre poste à faire** (`docs/verification_poste.md`) |
| **Fichier installable** | `dist/poplar-0.1.0.zip` (100 Ko, moteur inclus) |

## 1. Contenu

| Élément | Réalisation |
|---|---|
| Barre d'outils et menu « Population » | 9 boutons avec icônes et bulles d'aide : Scénario, Données, Paramètres, Calage (grisé, phase 6), Lancer, Résultats, Rapport, Aide, À propos |
| Fenêtre à onglets | Conforme à la maquette validée. Choix des couches et des champs dans les listes du projet. Tableaux éditables (exclusions, TCAM et densités max par classe et par année charnière, eau potable). Ouverture et enregistrement du scénario (même fichier JSON que le moteur et la ligne de commande). Les couches citées par un scénario sont ajoutées au projet si besoin. Chaque page défile si la fenêtre est petite |
| Système de coordonnées | Système du projet s'il est en mètres, UTM automatique, surfaces conservées, ou autre système au choix |
| Calcul en arrière-plan | `QgsTask` : progression, annulation, journal ; QGIS reste utilisable |
| Manque de place | Fenêtre de choix : hausse des densités (proposition calculée), couronne de mailles puits, non relocalisés, ou arrêt. Le calcul est ensuite relancé avec la solution choisie |
| Résultats | Chargement automatique de la population et de la densité finales dans un groupe « Poplar – *scénario* », avec dégradés de couleurs. Onglet pour charger d'autres grandeurs et années, ouvrir le tableau ou le dossier |
| Rapport | Affichage du rapport d'exécution |
| Processing | Algorithme **Poplar › Lancer un scénario**, avec texte d'aide. Il peut charger les résultats à la fin (ajout sûr, hors du fil de calcul) |
| Aide | Bulles d'aide sur tous les contrôles ; bouton **?** par onglet ; menu Aide navigable et consultable hors ligne (5 pages, avec recherche), généré depuis `docs/aide/` par `tools/build_help.py` ; fiche À propos ; champs `about`, `tracker` et `homepage` de `metadata.txt` |
| Langues | Interface en français et en anglais (298 textes), selon la langue de QGIS. Même mécanisme que le moteur : un catalogue JSON par langue (`plugin/poplar/i18n/`). **Écart assumé avec la spécification §15**, qui prévoyait les fichiers de traduction Qt : les catalogues JSON n'exigent aucun outil Qt et s'éditent directement, et ajouter une langue revient à ajouter un fichier |
| Paquet | `tools/build_plugin.py` : régénère l'aide, copie le moteur dans le plugin et produit le zip |
| Compatibilité | Qt importé uniquement via `qgis.PyQt`, énumérations Qt écrites sous leur forme complète (compatible Qt6), `supportsQt6=True` |

## 2. Tests (140 au total)

| Suite | Contenu |
|---|---|
| Moteur (`tests/`, 132 tests) | Inchangée, toujours verte |
| Plugin (`tests_plugin/`, 8 tests, dans QGIS 3.34 sans affichage) | Chargement et déchargement du plugin (9 boutons, fournisseur Processing) ; algorithme Processing sur Muramvya ; lecture et écriture du scénario par la fenêtre ; calcul depuis la fenêtre et chargement des couches ; aucun texte ni bulle non traduits ; catalogues français et anglais complets ; aide et À propos ; aide HTML à jour |

Les tests du plugin sont ignorés automatiquement quand QGIS n'est pas installé.

## 3. Captures

Captures des vraies fenêtres, rendues par QGIS dans `docs/captures/` : Scénario, Données, Paramètres, Indicateurs, Lancer, et la fenêtre de manque de place.

## 4. Limites connues

- **Testé avec QGIS 3.34**, la version fournie par Ubuntu. La version cible, 3.40 LTR, et QGIS 4 restent à vérifier sur votre poste.
- **L'aide n'existe qu'en français.** En anglais, l'interface est traduite, mais les pages d'aide s'affichent en français. Leur traduction est un travail de rédaction, sans code.
- **Pas d'aperçu graphique de l'interpolation** dans l'onglet Paramètres, contrairement à la maquette. C'est un ajout possible.
- **Fiche À propos** : l'organisme, la licence, le contact et la liste des auteurs restent à confirmer.

## 5. Suite

1. **Vérification sur votre poste**, avec la liste `docs/verification_poste.md`.
2. **Phase 6** : calage bâti → population (Google Open Buildings, régressions par strate, ajustement manuel), puis repérage de l'extension urbaine (phase 6 bis, qui demande la définition de l'urbain, Q8).
