# Code existant (référence)

Code de l'outil actuel, fourni pour BUR71. **Ne jamais modifier ces fichiers** : ils servent de référence pour la spécification et la non-régression.

| Fichier | Rôle | Emplacement d'origine |
|---|---|---|
| `Modeleur de migration_Q 2.model3` | Modèle graphique QGIS `ModèleMigration_V2` (groupe CAM12). Il prépare la population de référence : grille de mailles, densité, `Pmax`, exclusions, croissance | `Donne_COMMUNE_MURAMVYA_BUR71/Code/` |
| `CAM12_migration.py` | Script Processing PyQGIS (algorithme `OUG05_migration`). Il fait la migration itérative de l'excédent, un horizon à la fois | `Donne_COMMUNE_MURAMVYA_BUR71/Code/` |

Analyse détaillée : `docs/etat_des_lieux_code.md`.
