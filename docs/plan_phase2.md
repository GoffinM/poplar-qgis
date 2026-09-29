# Plan de la phase 2 : migration et non-convergence

| | |
|---|---|
| **Statut** | Proposition, à valider avant d'écrire le code |
| **Référence** | `docs/spec_moteur.md`, §6 et §7 |
| **Durée estimée** | 1 à 1,5 jour |

## 1. Objectif

Répartir l'excès de population au-delà des plafonds, sur **un pas de temps**, en conservant la population. Traiter les cas où la capacité ne suffit pas. L'enchaînement des années viendra en phase 3.

## 2. Modules

| Module | Contenu |
|---|---|
| `migration.py` | **Migration conservative** : à chaque itération, chaque unité en excès envoie son excès, à parts égales, à ses k unités receveuses les plus proches (3 par défaut), puis elle est ramenée à son plafond. Les itérations continuent jusqu'à ce qu'il n'y ait plus d'excès.<br>• Recherche des voisins avec `scipy.spatial.cKDTree`, sur les receveuses seulement.<br>• Transferts vectorisés (`numpy.add.at`).<br>• En cas d'égalité de distance, la receveuse de plus petit indice est retenue, ce qui rend le résultat déterministe.<br>• Garde-fous : nombre maximal d'itérations et seuil de tolérance |
| `migration.py`, mode `legacy` | Reproduction de l'algorithme actuel (transfert en densité, arrondis à l'entier), pour la comparaison uniquement |
| `nonconvergence.py` | **Contrôle préalable** de capacité, avant toute itération.<br>**Quatre politiques** :<br>• `stop` : arrêt avec un message explicite ;<br>• `raise_dmax` : calcul de la hausse minimale des densités max, sur toute l'emprise ou sur des zones choisies, proposée par paliers de 5 % et appliquée seulement après validation ;<br>• `sink` : couronne de mailles puits autour de la zone d'étude ;<br>• `unallocated` : enregistrement de la population non relocalisée, unité par unité |
| `units.py` (complément) | Construction de la couronne de mailles puits (4 mailles de large par défaut) |
| `report.py` | Bilan d'un pas, sous forme de fichier JSON et de texte lisible : populations avant et après, nombre d'itérations, convergence, population non relocalisée, ajustements appliqués, avertissements, statut (`success`, `success_with_adjustments`, `partial`, `failed`) |

Le **mécanisme d'évacuation** d'une zone (plafond nul, plus aucun accueil) est aussi codé dans cette phase. Il servira en phase 3 aux zones qui deviennent inhabitables à une date donnée (X1, `relocate`).

## 3. Tests

| Type | Contenu |
|---|---|
| Cas calculés à la main | T4 (une itération), T5 (cascade), T6 (maille incomplète, dans les deux modes), T7 (zone sans migration), T8 (maille surchargée), T9 (non-convergence, avec les politiques `stop`, `raise_dmax` et `unallocated`), T12 (déterminisme) |
| Invariants, sur des grilles aléatoires | Population conservée (I1) ; aucune unité au-dessus de son plafond après convergence (I2) ; les zones sans migration ne reçoivent rien (I3) ; même résultat à chaque exécution (I4) |
| Muramvya | Croissance 2024 → 2025, puis migration. On vérifie la conservation exacte, l'absence de dépassement et le bilan de la forêt. Comparaison qualitative avec `pentree_final` 2025 : les écarts dus à l'erreur de plafond de l'ancien outil (RF3) sont expliqués, pas corrigés |
| Mode `legacy` sur Muramvya | Mesure de l'écart entre l'ancien et le nouvel algorithme, sur les mêmes données |
| Performance (`-m slow`) | Une migration sur 2,25 millions d'unités, dont environ 5 % en excès. Objectif : **moins d'une minute** |

Le cas T14 (première année de migration) dépend de l'enchaînement des années : il sera traité en phase 3.

## 4. Documentation livrée avec la phase

- Mise à jour de `docs/spec_moteur.md` si l'implémentation fait apparaître un point à préciser.
- `docs/bilan_phase2.md`, sur le modèle de la phase 1.
- Première version des pages d'aide « Croissance, plafonds et migration » et « Non-convergence : que faire » (`docs/aide/`), en vue du menu Aide du plugin (spécification §14).

## 5. Points validés (29/09/2026)

- **Tolérance entière, 1 habitant par défaut** (décision du 29/09/2026). Un excès de moins d'un habitant reste dans sa maille, et une maille dont la place libre est inférieure à un habitant ne reçoit personne. Le calcul interne reste en valeurs réelles (R2), et seules les populations publiées sont arrondies.
- 10 000 itérations au maximum par pas. Si cette limite est atteinte, la non-convergence est déclarée.
- `raise_dmax` ne modifie jamais les densités max sans validation. En mode automatique, un plafond de hausse autorisée est fixé dans le scénario, et au-delà le calcul s'arrête.
- Couronne de mailles puits : 4 mailles de large, avec la densité max de la classe la moins dense (S5).
