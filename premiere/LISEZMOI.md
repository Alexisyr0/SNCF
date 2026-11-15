# Première

Version du robot : **3.0.0**

Les meilleurs prix SNCF en 1re, jour par jour, sur une période : aller-retour, suivi quotidien avec alertes, et repérage des voitures Océane.

## Comment c'est construit

- **L'app** (dossier `web`) : une page web installable sur iPhone et Mac, hébergée gratuitement sur Cloudflare Pages. Elle lit et écrit dans Supabase.
- **Le robot** (dossier `robot`) : il tourne en fond sur le Mac. Il récupère les recherches demandées dans l'app, remplit SNCF Connect dans une vraie fenêtre Chrome, fait défiler les trains jour par jour et renvoie les prix dans Supabase.
- **Supabase** : la base de données partagée. Toutes les tables commencent par `train_`, donc elles peuvent aller dans le projet de Radar Prod ou de Loupe.

SNCF Connect peut limiter ou refuser les accès automatisés : le robot détecte les refus, s'arrête et demande une intervention lorsque le site l'exige. Les recherches se font sur le Mac : il doit être allumé et ne pas être en veille pour avancer. Les recherches lancées depuis l'iPhone attendent que le Mac soit disponible.

## Mise à jour vers Robot 3.0

Avant de lancer cette version sur une base déjà utilisée :

1. Fais une sauvegarde de la base Supabase.
2. Ouvre `premiere/supabase/schema.sql` dans le SQL Editor et exécute-le à nouveau. La migration ajoute la colonne `checkpoint` si elle manque et réapplique les règles de sécurité des tables `train_*`. Elle ne supprime aucun relevé.
3. Remplace le dossier du dépôt par cette version, puis exécute `bash premiere/robot/installer.sh` sur le Mac.

Le point de reprise est enregistré après chaque journée terminée. Si le Mac s'arrête au milieu d'une journée, celle-ci est relancée et les relevés déjà présents pour cette exécution sont contrôlés avant insertion.


### 1. Supabase
1. Ouvre ton projet Supabase (celui de Radar Prod convient très bien), puis **SQL Editor › New query**.
2. Colle le contenu de `supabase/schema.sql` et clique sur **Run**.
3. Dans **Project Settings › API**, note l'**URL du projet** et la **clé anon (public)**.

### 2. L'app en ligne (Cloudflare Pages)
1. Mets ce dossier dans un dépôt GitHub privé, par exemple `Premiere`.
2. Dans Cloudflare : **Workers & Pages › Create › Pages › Connect to Git**, puis choisis le dépôt.
3. Laisse **Build command** vide et mets **Build output directory** sur `web`. Déploie.
4. Ouvre l'adresse obtenue (par exemple `https://premiere-xxx.pages.dev`). L'app te demande l'URL et la clé anon de Supabase, puis ton compte. Si tu as pris le projet de Radar Prod, c'est le même compte.
5. Sur iPhone, ouvre la même adresse dans Safari, puis **Partager › Sur l'écran d'accueil**.

### 3. Le robot sur le Mac
Dans le Terminal (après avoir exécuté le SQL et créé ton compte dans l'app) :
```
git clone https://github.com/Alexisyr0/SNCF.git ~/Projets/SNCF
cd ~/Projets/SNCF/premiere/robot
bash installer.sh
```
L'installation te demande l'URL Supabase, la clé anon, ton e-mail et ton mot de passe de l'app. Elle demande aussi, si tu veux, un sujet **ntfy** (une suite de mots au hasard, par exemple `premiere-alexis-7f3k`). Ensuite le robot démarre tout seul à chaque ouverture de session.

- Voir ce que fait le robot : `bash ~/Projets/SNCF/premiere/robot/installer.sh journal`
- L'arrêter : `bash ~/Projets/SNCF/premiere/robot/installer.sh arreter`
- Le mettre à jour : `cd ~/Projets/SNCF && git pull && bash premiere/robot/installer.sh`

### 4. Alertes sur l'iPhone
Installe l'app gratuite **ntfy** et abonne-toi au sujet choisi pendant l'installation. Quand le prix d'un trajet suivi baisse, tu reçois une notification. Le Mac en affiche une aussi.

## Utilisation

- **Nouvelle recherche** : départ, arrivée, période aller et, si tu veux, période retour avec un nombre de nuits minimum et maximum, voyageurs et cartes, chiens. Par défaut, la recherche est en 1re classe sur tous les trains et en TGV INOUI uniquement. L'option « Correspondance à Paris » écarte les trajets qui changent ailleurs, à Lyon par exemple.
- **Calendrier** : le prix le moins cher de chaque jour, avec les 3 meilleurs jours marqués ★. Touche un jour pour voir tous ses trains, avec les numéros, le choix de place et les changements de gare (Gare de Lyon → Montparnasse).
- **Aller-retour** : les 3 meilleurs couples de dates selon tes nuits sur place.
- **Suivi** : le robot repasse chaque jour à l'heure choisie. La courbe « Évolution » montre le meilleur prix à chaque passage. Les « Tendances » montrent quels jours de la semaine et quels trains sont les moins chers.
- **Rames** : SNCF Connect ne dit pas si une rame est Océane. Le robot ouvre donc le plan de salle (en 1re, sans rien mettre au panier) et relève, voiture par voiture et salle par salle, les sièges, leur orientation, les tablettes, les tables, les places isolées et les places PMR. Chaque plan identique reçoit la même **empreinte**, que la voiture soit affichée dans un sens ou dans l'autre. Quand tu reconnais une voiture Océane, marque son empreinte « Océane » une fois. L'app la repère ensuite dans tous tes trains, et le filtre « Rames Océane » ne garde que ces trajets. Le tableau « Trains déjà observés » montre combien de fois chaque numéro de train avait des voitures Océane.

## Si quelque chose coince

- **Le robot n'arrive pas à remplir le formulaire** (SNCF a changé son site) : la recherche passe en « Besoin d'aide sur le Mac ». Fais la recherche à la main dans la fenêtre Chrome ouverte par le robot, et il reprend à partir de là. Une capture d'écran est enregistrée dans `robot/captures`.
- **CAPTCHA, refus ou restriction SNCF Connect** : le robot arrête immédiatement les requêtes et active un coupe-circuit persistant. Il ne reprend pas automatiquement. Voir la procédure de réactivation dans `CONFIGURATION.md`.
- **« Mac hors ligne » dans l'app** : le Mac est en veille ou le robot est arrêté. Vérifie avec `bash installer.sh journal`.
- Le robot attend au minimum 10 secondes entre les requêtes SNCF Connect (`PAUSE`, défaut 15). Un quota quotidien limite les appels à 40 par défaut (`MAX_REQUETES_JOUR`). Après incident réseau, le délai augmente progressivement. En cas de CAPTCHA, refus ou restriction, un coupe-circuit persistant arrête toutes les requêtes jusqu'à réactivation manuelle après vérification de l'accès. Voir `robot/CHANGELOG-3.0.md` et `CONFIGURATION.md`.
