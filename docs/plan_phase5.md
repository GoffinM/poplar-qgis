# Plan de la phase 5 : plugin QGIS

| | |
|---|---|
| **Statut** | Proposition, à valider avec la maquette (`docs/maquette_plugin.html`) |
| **Cible** | QGIS 3.40 LTR et QGIS 4 (Qt6) ; Qt importé uniquement via `qgis.PyQt` |
| **Durée estimée** | 1,5 à 2 jours |

## 1. Contenu

| Élément | Contenu |
|---|---|
| Barre d'outils et menu « Population » | Scénario, Données, Paramètres, Calage (grisé jusqu'à la phase 6), Lancer, Résultats, Rapport, Aide, À propos |
| Fenêtre principale à onglets | Chaque bouton ouvre la même fenêtre sur le bon onglet. Les couches et leurs champs se choisissent dans des listes du projet. Les tableaux de paramètres (classes × années charnières) sont éditables, avec un aperçu de l'interpolation. La fenêtre lit et écrit le fichier de scénario (JSON) du moteur |
| Calcul en arrière-plan | `QgsTask` : QGIS reste utilisable, avec barre de progression, journal et annulation. En cas de manque de place, une fenêtre de choix s'ouvre (hausse des densités proposée, couronne, non relocalisés, arrêt) |
| Résultats | Rasters chargés dans un groupe par scénario, avec des styles prêts à l'emploi (population, densité, eau), et ouverture du tableau et du rapport |
| Algorithme Processing | « Lancer un scénario » (entrée : fichier de scénario), pour les traitements par lots et le Model Builder, avec son texte d'aide |
| Aide | Bulles d'aide sur tous les contrôles, bouton « ? » par onglet, menu Aide navigable hors ligne (pages HTML générées depuis `docs/aide/`), fiche À propos, champs `about`, `homepage` et `tracker` de `metadata.txt` |
| Langues | Textes de l'interface marqués traduisibles, fichiers de traduction `fr` et `en`, choix selon la langue de QGIS |
| Paquet | Script de construction du zip installable. Le moteur est inclus dans le plugin : rien d'autre à installer |

## 2. Structure

```
plugin/poplar/
├── metadata.txt, __init__.py, plugin.py   barre d'outils, menu
├── ui/                                     fenêtre à onglets, dialogue de non-convergence, aide, À propos
├── task.py                                 calcul en arrière-plan (QgsTask)
├── processing/                             fournisseur et algorithme Processing
├── styles/                                 styles QML des résultats
├── help/<langue>/                          pages d'aide HTML (générées)
├── i18n/                                   traductions de l'interface
└── engine/                                 copie du moteur (src/engine) au moment de la construction
```

## 3. Tests

- **Sans QGIS** : le moteur reste testé comme aujourd'hui (121 tests).
- **Avec QGIS, sans affichage** : chargement du plugin, algorithme Processing sur le scénario de Muramvya, tâche de fond, lecture et écriture du scénario depuis la fenêtre. J'essaierai d'installer QGIS dans l'environnement de développement (Ubuntu fournit QGIS 3.34 ; la 3.40 dépend de l'accès au dépôt de qgis.org).
- **Sur votre poste** : installation du zip dans QGIS 3.40 (et 4 si disponible), puis un calcul complet sur Muramvya. Je fournirai une liste de vérification courte.

## 4. Points à valider (voir la maquette)

1. Nom du plugin (« Poplar » proposé).
2. Une seule fenêtre à onglets plutôt qu'une fenêtre par bouton.
3. Liste des boutons de la barre d'outils.
4. Fiche À propos : auteurs, organisme, licence, contact.
5. Chargement automatique des résultats dans un groupe par scénario, avec des styles.
