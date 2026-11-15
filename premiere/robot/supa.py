"""Client Supabase minimal pour Première.

Le robot utilise le compte utilisateur et le JWT Supabase Auth : les règles RLS
restent appliquées. Les POST d'écriture ne sont jamais rejoués automatiquement
après une erreur réseau, car le serveur a pu les traiter avant la coupure.
"""

import time
from urllib.parse import quote

import requests


class Supabase:
    def __init__(self, url, cle_anon, email, mot_de_passe):
        self.url = url.rstrip("/")
        self.cle = cle_anon
        self.email = email
        self.mdp = mot_de_passe
        self.jeton = None
        self.rafraichir = None
        self.expire = 0
        self.user_id = None
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "Premiere-Robot/2.0"})

    def _auth(self, corps, grant):
        r = self.http.post(
            "{}/auth/v1/token?grant_type={}".format(self.url, grant),
            json=corps, headers={"apikey": self.cle}, timeout=(10, 30)
        )
        if r.status_code >= 400:
            raise RuntimeError("Connexion Supabase refusée ({}) : {}".format(
                r.status_code, r.text[:200]))
        d = r.json()
        self.jeton = d["access_token"]
        self.rafraichir = d.get("refresh_token")
        self.expire = time.time() + int(d.get("expires_in", 3600)) - 120
        self.user_id = (d.get("user") or {}).get("id", self.user_id)

    def connecter(self):
        self._auth({"email": self.email, "password": self.mdp}, "password")

    def _entetes(self, extra=None):
        if not self.jeton or time.time() >= self.expire:
            if self.rafraichir:
                try:
                    self._auth({"refresh_token": self.rafraichir}, "refresh_token")
                except (requests.RequestException, ValueError, KeyError, RuntimeError):
                    self.connecter()
            else:
                self.connecter()
        h = {
            "apikey": self.cle,
            "Authorization": "Bearer " + self.jeton,
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _req(self, methode, table, params=None, json_=None, prefer=None, extra_headers=None):
        url = "{}/rest/v1/{}".format(self.url, table)
        if params:
            url += "?" + "&".join(
                "{}={}".format(k, quote(str(v), safe=",.():*-_"))
                for k, v in params.items()
            )
        extras = dict(extra_headers or {})
        if prefer:
            extras["Prefer"] = prefer
        h = self._entetes(extras)

        # GET et PATCH sont rejouables. Un POST peut avoir été accepté malgré
        # une coupure réseau : ne pas le répéter aveuglément.
        rejouable = methode.upper() in ("GET", "PATCH", "DELETE")
        essais = 3 if rejouable else 1
        for essai in range(essais):
            try:
                r = self.http.request(
                    methode, url, json=json_, headers=h, timeout=(10, 60)
                )
            except requests.RequestException:
                if essai + 1 >= essais:
                    raise
                time.sleep(2 ** (essai + 1))
                continue

            if r.status_code == 401 and essai == 0:
                self.connecter()
                h = self._entetes(extras)
                if rejouable:
                    continue
                raise RuntimeError("Session Supabase expirée pendant une écriture ; résultat à vérifier.")

            if r.status_code == 429 or r.status_code >= 500:
                if essai + 1 < essais:
                    attente = min(20, 2 ** (essai + 1))
                    time.sleep(attente)
                    continue

            if r.status_code >= 400:
                raise RuntimeError("Supabase {} {} : {}".format(
                    methode, table, r.text[:300]))
            return r.json() if r.text else None
        return None

    def lire(self, table, **params):
        return self._req("GET", table, params) or []

    def lire_tout(self, table, taille=500, **params):
        """Lit une table par pages pour ne pas tronquer les longues recherches."""
        resultat = []
        debut = 0
        while True:
            page = self._req(
                "GET", table, params,
                extra_headers={"Range": "{}-{}".format(debut, debut + taille - 1)}
            ) or []
            resultat.extend(page)
            if len(page) < taille:
                return resultat
            debut += taille

    def ajouter(self, table, lignes, retour=True, ignorer_doublons=False):
        prefer = "return=representation" if retour else "return=minimal"
        if ignorer_doublons:
            prefer = "resolution=ignore-duplicates," + prefer
        return self._req("POST", table, json_=lignes, prefer=prefer)

    def modifier(self, table, filtres, valeurs):
        return self._req("PATCH", table, filtres, json_=valeurs, prefer="return=minimal")

    def remplacer(self, table, ligne):
        return self._req(
            "POST", table, json_=ligne,
            prefer="resolution=merge-duplicates,return=minimal"
        )
