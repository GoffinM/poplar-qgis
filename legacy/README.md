# Code existant (référence)

Code de l'outil actuel, fourni pour BUR71. **Ne jamais modifier ces fichiers** : ils servent de référence pour la spécification et la non-régression.

| Fichier | Rôle | Emplacement d'origine |
|---|---|---|
| `Modeleur de migration_Q 2.model3` | Modèle graphique QGIS `ModèleMigration_V2` (groupe CAM12). Il prépare la population de référence : grille de mailles, densité, `Pmax`, exclusions, croissance | `Donne_COMMUNE_MURAMVYA_BUR71/Code/` |
| `CAM12_migration.py` | Script Processing PyQGIS (algorithme `OUG05_migration`). Il fait la migration itérative de l'excédent, un horizon à la fois | `Donne_COMMUNE_MURAMVYA_BUR71/Code/` |

Analyse détaillée : `docs/etat_des_lieux_code.md`.

## Calage bâti → population (`calage/`)

| Fichier | Rôle | Emplacement d'origine |
|---|---|---|
| `calage/demand_conso_Muramvya-Rural.xlsx` | Calage de la zone rurale : 33 246 bâtiments (centroïde et surface), classes de surface, polynôme de degré 3 | `Donne_COMMUNE_MURAMVYA_BUR71/` |
| `calage/demand_conso_Muramvya-Urbain.xlsx` | Même calage pour la zone urbaine : 5 696 bâtiments | `Donne_COMMUNE_MURAMVYA_BUR71/` |

Analyse détaillée : `docs/etat_des_lieux_code.md`, §11.
