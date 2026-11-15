# Première Robot 3.0.0

## Objectif

Renforcer la maîtrise du rythme et la stabilité des recherches personnelles.

## Changements

- Cadence minimale configurable entre les requêtes SNCF Connect : 15 secondes par défaut, 10 secondes minimum.
- Quota journalier persistant de 40 requêtes par défaut, partagé entre recherches, pagination, actions manuelles observées et chargement des plans de salle.
- Compteur local conservé dans `garde.json`, exclu de Git.
- Délai progressif après incident réseau : 5 minutes, puis doublement à chaque incident consécutif, plafonné à 1 heure par défaut.
- Pas de rejeu automatique d'une requête dont le résultat est incertain.
- Coupe-circuit persistant sur CAPTCHA, refus HTTP, page de restriction ou réponse SNCF inattendue.
- Après déclenchement du coupe-circuit, aucune nouvelle requête SNCF n'est lancée, y compris pour une autre tâche en attente.
- Réactivation manuelle explicite avec `python robot.py --reinitialiser-garde`, après arrêt du LaunchAgent et vérification de l'accès au site.
- Les erreurs réseau et les refus d'accès ne sont plus confondus avec un simple problème de formulaire. L'assistance manuelle ne permet pas de poursuivre après un refus ou un CAPTCHA.
- Le verrou local d'instance unique est conservé.

## Configuration

Variables facultatives dans `robot/config.env` :

- `PAUSE=15`
- `MAX_REQUETES_JOUR=40`
- `COOLDOWN_ERREUR=300`
- `COOLDOWN_MAX=3600`

Les valeurs sont des garde-fous locaux. Les réduire augmente le volume de requêtes et n'est pas recommandé.

## Réactivation après restriction

Si le coupe-circuit se déclenche, vérifier l'état du compte et l'accès au site. Ne réinitialiser la garde que lorsque l'accès est de nouveau autorisé. La commande remet également le compteur quotidien à zéro.

## Tests et limites

Les 11 tests unitaires couvrent le parsing des prix, les réponses de restriction, le quota, la persistance du coupe-circuit, sa réinitialisation et les appels Supabase simulés. Ils ne valident pas le comportement en production. Aucun test n'a été effectué sur SNCF Connect réel ni sur le projet Supabase réel. La cadence et le quota sont des limites locales choisies pour réduire les appels, pas une garantie d'absence de blocage ni une garantie de conformité aux conditions du service.
