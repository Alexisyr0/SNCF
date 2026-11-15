# Première Robot 2.0.0

## Changements

- Reprise d'une recherche à partir du dernier jour terminé, avec un point de reprise JSON dans `train_recherches.checkpoint`.
- Relecture des relevés déjà écrits pour reconstruire le meilleur prix et les candidats à l'analyse des rames.
- Contrôle des clés déjà enregistrées avant de réinsérer les résultats d'une journée interrompue.
- Détection des refus HTTP et des pages de restriction qui peuvent être renvoyées avec HTTP 200.
- Arrêt sans relance automatique lorsqu'un refus d'accès est rencontré. La recherche passe en `bloquee` et reste relançable depuis l'application.
- Vérification qu'une journée a bien été entièrement paginée avant de déplacer le point de reprise.
- Sélection de gare stricte : le robot ne choisit plus silencieusement la première suggestion si le lieu demandé n'est pas reconnu.
- Protection contre deux instances simultanées sur le même Mac.
- Journal avec rotation (5 Mo, 5 archives).
- Gestion des sessions Supabase améliorée. Les POST ne sont pas rejoués aveuglément après une coupure réseau.
- Correction de la lecture des prix avec virgules et points décimaux.

## Migration Supabase

Avant le premier lancement de la version 2.0.0 sur une base existante :

1. Faire une sauvegarde de la base.
2. Réexécuter `premiere/supabase/schema.sql`.
3. Vérifier que la colonne `checkpoint` existe sur `train_recherches`.
4. Installer la version du robot avec `bash installer.sh`.

La migration est additive : elle ajoute la colonne manquante sans supprimer les données existantes.

## Limites de validation

Les 8 tests automatisés de la version 2.0 couvraient les conversions de prix, la détection des réponses de restriction, la pagination Supabase simulée et l'absence de rejeu automatique des POST. Lancer avec `python -m unittest discover -s tests -v` depuis `premiere/robot`. Aucun test réel n'a été effectué sur SNCF Connect ni sur le projet Supabase de production. Le comportement du site peut évoluer et un refus d'accès doit être respecté : le robot s'arrête et attend une intervention.
