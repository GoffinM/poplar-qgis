# Outil SIG de croissance et de migration de population (BUR71)

Refonte de l'outil interne SHER (modèle QGIS + script PyQGIS) en moteur Python, puis en plugin QGIS.

| Dossier | Contenu |
|---|---|
| `docs/` | Fiche diagnostic, état des lieux du code existant, spécification du moteur, bilans de phase |
| `legacy/` | Code et classeurs de calage existants : référence, **jamais modifiés** |
| `data/test/muramvya/` | Jeu de test de la commune de Muramvya |
| `reference_outputs/muramvya/` | Résultats de l'outil actuel sur le jeu de test |
| `src/engine/` | Moteur de calcul (numpy, scipy, GDAL ; n'importe jamais `qgis`) |
| `tests/` | Tests pytest |
| `tools/` | Outils de développement (préparation des données de test) |

## Lancer les tests

Il faut Python ≥ 3.9 avec GDAL, numpy, scipy et pytest, soit les bibliothèques fournies avec QGIS, plus pytest. Sous Ubuntu : `apt install python3-gdal python3-numpy python3-scipy python3-pytest`.

```bash
python3 -m pytest            # tests rapides (quelques secondes)
python3 -m pytest -m slow -s # performance sur un million de bâtiments (~1 min)
```

## Lancer une simulation

```bash
cd src
python3 -m engine run ../data/test/muramvya/scenario_muramvya.json
```

Les résultats sont écrits dans `data/test/muramvya/outputs/`, qui n'est pas versionné. Le fonctionnement et les paramètres sont décrits dans `docs/aide/`.
