"""Mini client Supabase : le robot se connecte avec TON compte (mêmes droits que l'app)."""

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

    # --- connexion -----------------------------------------------------------
    def _auth(self, corps, grant):
        r = self.http.post("{}/auth/v1/token?grant_type={}".format(self.url, grant),
                           json=corps, headers={"apikey": self.cle}, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError("Connexion Supabase refusée ({}) : {}".format(r.status_code, r.text[:200]))
        d = r.json()
        self.jeton = d["access_token"]
        self.rafraichir = d.get("refresh_token")
        self.expire = time.time() + int(d.get("expires_in", 3600)) - 120
        self.user_id = (d.get("user") or {}).get("id", self.user_id)

    def connecter(self):
        self._auth({"email": self.email, "password": self.mdp}, "password")

    def _entetes(self, extra=None):
        if not self.jeton or time.time() > self.expire:
            try:
                if self.rafraichir:
                    self._auth({"refresh_token": self.rafraichir}, "refresh_token")
                else:
                    self.connecter()
            except Exception:
                self.connecter()
        h = {"apikey": self.cle, "Authorization": "Bearer " + self.jeton, "Content-Type": "application/json"}
        if extra:
            h.update(extra)
        return h

    # --- requêtes ------------------------------------------------------------
    def _req(self, methode, table, params=None, json_=None, prefer=None):
        url = "{}/rest/v1/{}".format(self.url, table)
        if params:
            url += "?" + "&".join("{}={}".format(k, quote(str(v), safe=",.():*-_")) for k, v in params.items())
        h = self._entetes({"Prefer": prefer} if prefer else None)
        for essai in range(3):
            try:
                r = self.http.request(methode, url, json=json_, headers=h, timeout=60)
            except requests.RequestException:
                if essai == 2:
                    raise
                time.sleep(3 + essai * 5)
                continue
            if r.status_code == 401 and essai == 0:
                self.connecter()
                h = self._entetes({"Prefer": prefer} if prefer else None)
                continue
            if r.status_code >= 400:
                raise RuntimeError("Supabase {} {} : {}".format(methode, table, r.text[:300]))
            return r.json() if r.text else None
        return None

    def lire(self, table, **params):
        return self._req("GET", table, params) or []

    def ajouter(self, table, lignes, retour=True):
        return self._req("POST", table, json_=lignes,
                         prefer="return=representation" if retour else "return=minimal")

    def modifier(self, table, filtres, valeurs):
        return self._req("PATCH", table, filtres, json_=valeurs, prefer="return=minimal")

    def remplacer(self, table, ligne):
        return self._req("POST", table, json_=ligne,
                         prefer="resolution=merge-duplicates,return=minimal")
