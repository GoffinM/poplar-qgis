# Jeu de test : commune de Muramvya (BUR71)

Les fichiers ont été renommés sans espaces. Leur contenu est identique aux originaux.

| Fichier | Contenu | Nom d'origine (`Donne_COMMUNE_MURAMVYA_BUR71/`) |
|---|---|---|
| `pop2023_muramvya.tif` (+ `.aux.xml`) | Densité de population 2023 (hab/km²), float32, pixels de 250 m, EPSG:32735 | `Raster/POP2023 MURAMVYA.tif` |
| `commune_muramvya.*` | Deux polygones de commune, avec le champ `Type` (`Rural`, `Urbain1`) | `SHAPEFILE DU COMMUNE/COMMUNE MURAMVYA.*` |
| `zone_sans_migration.*` | Zone sans migration (forêt, source OSM) | `SHAPEFILE DU COMMUNE/ZONE SANS MIGRATION.*` |
| `pop_admin2024.xlsx` | Population totale par commune (19 communes) | `BUR71_Pop admin2024 1.xlsx` |

Tous les fichiers vectoriels et le raster sont en WGS 84 / UTM zone 35S.

Le fichier `.qmd` contient les métadonnées QGIS du shapefile correspondant. Il n'est pas nécessaire pour le calcul.
