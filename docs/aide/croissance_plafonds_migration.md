# Croissance, plafonds et migration

Cette page explique comment l'outil fait évoluer la population d'une année à l'autre.

## Les mailles et leurs morceaux

Le territoire est découpé en **mailles** carrées, de 250 m de côté par défaut (réglable). Une maille traversée par une limite (commune, zone urbaine ou rurale, forêt…) est coupée en **morceaux**. Chaque morceau garde sa propre surface, sa classe (par exemple *Rural* ou *Urbain1*) et sa population.

## Chaque année, deux étapes

### 1. La croissance

La population de chaque maille est multipliée par le taux de croissance annuel moyen (TCAM) de sa zone.

> Exemple : 120 habitants avec un TCAM de 2,2 % donnent 122,64 habitants un an plus tard.

Si le taux change au cours d'une période, par exemple 3 % en 2026 et 2 % en 2040, l'outil utilise le **taux moyen** de chaque pas de temps. Entre deux années que vous avez renseignées, les valeurs sont interpolées en ligne droite.

L'outil garde les décimales pendant le calcul. Sans elles, une petite maille de 7 habitants ne grandirait jamais : 7 × 1,022 = 7,15, et un arrondi redonnerait 7 chaque année. Les résultats publiés, eux, sont des nombres entiers, et leur total est conservé.

### 2. La migration

Chaque maille a un **plafond**, c'est-à-dire une population maximale :

- plafond = surface × densité maximale de sa classe (par exemple 2 500 hab/km² en rural) ;
- une maille **déjà au-dessus** de cette densité au départ garde sa densité de départ comme plafond ;
- une maille en **zone sans migration** (forêt, domaine militaire…) a pour plafond sa population de départ : elle n'accueille personne, et sa croissance part ailleurs.

Quand une maille dépasse son plafond d'au moins **un habitant**, l'excès part, **à parts égales**, vers les **3 mailles les plus proches** qui ont encore de la place. La maille de départ revient à son plafond. Si une maille receveuse déborde à son tour, elle redistribue son propre excès, et ainsi de suite jusqu'à ce que plus aucune maille ne dépasse son plafond.

> Exemple : une maille de plafond 10 compte 46 habitants, et ses voisines sont vides. Elle envoie 12 habitants à chacune de ses 3 voisines les plus proches, qui dépassent alors leur plafond de 2. Ces 3 × 2 habitants partent vers la maille libre suivante. Au final, on obtient 10, 10, 10, 10 et 6 habitants : les 46 habitants sont tous là.

**Ce qui est garanti :**
- **Aucun habitant ne disparaît.** On déplace des habitants, pas des densités : une maille incomplète en bordure reçoit exactement le nombre d'habitants qui quitte la maille de départ.
- **Personne ne s'installe dans une zone sans migration.**
- **Le résultat est reproductible** : les mêmes données donnent toujours le même résultat.

**Un excès de moins d'un habitant reste sur place.** Il s'ajoute à la croissance de l'année suivante et part dès qu'il atteint un habitant. Chaque maille peut donc dépasser son plafond de moins d'un habitant.

## Paramètres utiles

| Paramètre | Rôle | Défaut |
|---|---|---|
| Nombre de voisins | Nombre de mailles qui se partagent l'excès | 3 |
| Tolérance | Excès minimal pour déclencher un déplacement | 1 habitant |
| Nombre maximal d'itérations | Garde-fou par pas de temps | 10 000 |

Si la place manque, consultez la page **Non-convergence : que faire**.
