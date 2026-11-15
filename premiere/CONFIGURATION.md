# Configuration de Première (sans aucun secret)

Il y a quatre endroits où l'on configure Première. Aucun secret n'est stocké dans le dépôt.

## 1. Robot du Mac : `premiere/robot/config.env`
Non versionné (exclu par `.gitignore`), droits 600, créé par `bash installer.sh` via `configurer.py`, qui teste la connexion avant d'enregistrer. Modèle complet : `premiere/robot/config-exemple.env`.

| Variable | Obligatoire | Contenu | Utilisée par |
|---|---|---|---|
| `SUPABASE_URL` | oui | `https://<projet>.supabase.co` | supa.py (Auth + REST `/rest/v1/train_*`) |
| `SUPABASE_ANON_KEY` | oui | clé publique `sb_publishable_…` ou `anon` | en-tête `apikey` |
| `EMAIL` | oui | e-mail du compte de l'app | connexion `POST /auth/v1/token?grant_type=password` |
| `MOT_DE_PASSE` | oui | mot de passe de ce compte (**secret**) | idem |
| `NTFY_TOPIC` | non | nom du canal ntfy.sh | robot.py, `POST https://ntfy.sh/<sujet>` |
| `APP_URL` | non | adresse de l'app | lien ouvert depuis l'alerte ntfy |
| `PAUSE` | non | délai minimum entre requêtes SNCF (défaut 15 s, minimum 10 s) | sncf.py |
| `MAX_REQUETES_JOUR` | non | quota quotidien de requêtes SNCF, tous types confondus (défaut 40) | sncf.py |
| `COOLDOWN_ERREUR` | non | délai après incident réseau, doublé à chaque incident consécutif (défaut 300 s) | sncf.py |
| `COOLDOWN_MAX` | non | plafond du délai progressif (défaut 3 600 s) | sncf.py |

Lecture : `lire_config()` dans robot.py. Les lignes vides ou commençant par `#` sont ignorées, et la valeur est prise telle quelle (tout ce qui suit le premier `=`).

La garde locale `premiere/robot/garde.json` conserve le compteur quotidien, le délai après incident et le coupe-circuit. Elle est exclue de Git. Après un CAPTCHA, une restriction ou un refus du site, le robot s'arrête et ne reprend pas automatiquement. Après vérification manuelle de l'accès au site, réactivation explicite depuis le Terminal :

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/fr.premiere.robot.plist
cd "<dossier du projet>/premiere/robot"
.venv/bin/python robot.py --reinitialiser-garde
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/fr.premiere.robot.plist
```

La séquence arrête le robot, réinitialise la garde, puis redémarre le LaunchAgent. Elle remet aussi le compteur quotidien à zéro. Ne l'utiliser qu'après avoir vérifié que SNCF Connect autorise à nouveau l'accès. Le compteur de quota se réinitialise automatiquement au changement de jour. Une tâche arrêtée sur quota devra être relancée depuis l'app le jour suivant. Les erreurs réseau déclenchent un délai progressif, sans relance automatique de la requête échouée.

## 2. App web : `premiere/web/config.js`
```js
window.PREMIERE_CONFIG = {
  supabaseUrl: "",      // https://<projet>.supabase.co
  supabaseAnonKey: ""   // clé publique (publishable / anon)
};
```
Laissé vide dans le dépôt. Si c'est vide, l'app demande ces deux valeurs au premier lancement et les garde dans le navigateur (`localStorage` : `premiere.url` et `premiere.cle`). La session de connexion est gérée par supabase-js (`persistSession: true`).

## 3. Hébergement Cloudflare : `wrangler.jsonc` (racine du dépôt)
```jsonc
{
  "name": "sncf",                     // doit correspondre au nom du Worker dans Cloudflare
  "compatibility_date": "2026-11-14",
  "assets": { "directory": "./premiere/web" }
}
```
Site statique uniquement : pas de script Worker, pas de variables d'environnement ni de secrets Cloudflare. Déploiement : Workers Builds sur push vers `main` (commande `npx wrangler deploy`).

## 4. Supabase
- Schéma : `premiere/supabase/schema.sql`, à exécuter dans le SQL Editor (rejouable sans erreur). Il ajoute notamment `train_recherches.checkpoint`, utilisé pour reprendre une recherche interrompue. Toutes les tables sont préfixées `train_`, avec RLS `user_id = auth.uid()`.
- Authentification : e-mail + mot de passe (Supabase Auth). Le compte est partagé avec mes autres apps hébergées dans le même projet.
- Aucune Edge Function, aucun secret serveur, aucune clé `service_role` utilisée.

## 5. Démarrage automatique du robot (macOS)
`~/Library/LaunchAgents/fr.premiere.robot.plist`, généré par `installer.sh` : lance `premiere/robot/.venv/bin/python -u robot.py` à la connexion (RunAtLoad, KeepAlive, ThrottleInterval 30), avec un journal rotatif dans `premiere/robot/robot.log` (5 Mo par fichier, 5 archives conservées). Une seule instance peut tourner à la fois (`robot.lock`).
