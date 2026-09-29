# Résultats de référence : Muramvya

Ces fichiers sont les résultats de l'outil actuel (`legacy/`) sur le jeu `data/test/muramvya/`. Ils ont été fournis par Michel le 29/09/2026 et ne sont **pas modifiés** : seuls leurs noms ont changé.

| Fichier | Nom d'origine | Contenu |
|---|---|---|
| `p2023_entree.*` | `P2023entree MURAMVYA.*` | Sortie du modèle de préparation : 4 386 mailles avec les champs `P2023value` (hab/km²), `Pmax` (hab/km²), `P2025value`, `Area` (km², 3 décimales) et `P2024` |
| `pentree_final.*` | `Pentree MURAMVYA Final .*` | Résultat final, avec la même géométrie : `ID`, `Pmax`, `Area`, `COMMUNE`, puis pour chaque année 2024, 2025, 2030 … 2060 la densité `PopD<année>` (hab/km²) et la population entière `Pop<année>` |

- Système de coordonnées : WGS 84 / UTM 35S.
- Version de QGIS : 3.34.11, d'après les fichiers `.qmd`.

Analyse détaillée : `docs/etat_des_lieux_code.md`, §10.

Pour les tests de non-régression, il reste à connaître :
- la procédure et les paramètres qui mènent de `p2023_entree` à `pentree_final` (taux de croissance par période, recalage éventuel) ;
- la version exacte du modèle qui a produit `p2023_entree`.
