# Non-convergence : que faire ?

## De quoi s'agit-il ?

Il y a **non-convergence** quand la population ne tient plus dans les mailles autorisées : la somme des plafonds est inférieure à la population à loger. C'est le cas quand la croissance est forte, les densités maximales basses, ou les zones d'exclusion étendues.

L'outil le détecte **avant** de déplacer qui que ce soit, en comparant la population en excès aux places libres. Il vous indique alors combien d'habitants ne peuvent pas être placés.

## Les quatre réponses possibles

Vous choisissez la réponse dans le scénario ou, avec le plugin, dans la fenêtre qui s'ouvre au moment où le problème apparaît.

| Réponse | Ce qui se passe | Quand l'utiliser |
|---|---|---|
| **Arrêter** (par défaut) | Le calcul s'arrête avec un message qui indique le nombre d'habitants en trop. Les résultats déjà produits sont conservés | Pour vérifier d'abord ses hypothèses |
| **Relever les densités maximales** | L'outil calcule la hausse minimale nécessaire et la propose arrondie au palier de 5 % supérieur (par exemple +25 %), sur toute la zone ou sur les zones que vous choisissez. **Rien n'est modifié sans votre accord.** En mode automatique, le scénario fixe une hausse maximale autorisée, au-delà de laquelle le calcul s'arrête | Quand une densification est plausible |
| **Mailles puits en périphérie** | Une couronne de mailles, 4 mailles de large par défaut, est ajoutée autour de la zone d'étude pour accueillir l'excédent. La population placée dans la couronne est reportée à part | Pour représenter un étalement au-delà du périmètre étudié |
| **Population non relocalisée** | L'outil place tout ce qu'il peut, puis enregistre le reste, maille par maille et année par année | Pour mesurer l'ampleur du problème sans modifier les hypothèses |

Dans tous les cas, le **rapport d'exécution** indique pour chaque pas de temps :
- le statut : réussi, réussi avec ajustements, partiel ou échec ;
- les populations avant et après ;
- le nombre d'habitants déplacés ;
- les ajustements appliqués ;
- la population non relocalisée.

## Exemple

Deux mailles de plafond 10 comptent 15 et 10 habitants : il y a 5 habitants en trop.
- **Arrêter** : message « Capacité insuffisante : 5 habitants ne peuvent pas être placés ».
- **Relever les densités** : l'outil propose +25 %. Après validation, les deux plafonds passent à 12,5, et chaque maille compte 12,5 habitants.
- **Non relocalisés** : les deux mailles restent à 10, et 5 habitants sont enregistrés comme non relocalisés.
