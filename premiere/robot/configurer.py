#!/usr/bin/env python3
"""Crée ou corrige robot/config.env, puis vérifie que la connexion à Supabase marche."""

import getpass
import os
import sys
from pathlib import Path

import requests

ICI = Path(__file__).resolve().parent
FICHIER = ICI / "config.env"
ORDRE = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "EMAIL", "MOT_DE_PASSE", "NTFY_TOPIC", "APP_URL", "PAUSE"]


def lire():
    conf = {}
    if FICHIER.exists():
        for ligne in FICHIER.read_text(encoding="utf-8").splitlines():
            if ligne.strip() and not ligne.lstrip().startswith("#") and "=" in ligne:
                k, v = ligne.split("=", 1)
                conf[k.strip()] = v.strip()
    return conf


def ecrire(conf):
    lignes = ["{}={}".format(k, conf.get(k, "")) for k in ORDRE]
    FICHIER.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    os.chmod(FICHIER, 0o600)


def demander(texte, defaut="", cache=False):
    suffixe = " [{}]".format(defaut) if defaut and not cache else ""
    v = (getpass.getpass if cache else input)("     {}{} : ".format(texte, suffixe)).strip()
    return v or defaut


def tester(conf):
    url = conf.get("SUPABASE_URL", "").rstrip("/")
    try:
        r = requests.post(url + "/auth/v1/token?grant_type=password",
                          json={"email": conf.get("EMAIL", ""), "password": conf.get("MOT_DE_PASSE", "")},
                          headers={"apikey": conf.get("SUPABASE_ANON_KEY", "")}, timeout=20)
    except Exception as e:
        return "url", "Impossible de joindre Supabase ({}).".format(e.__class__.__name__)
    if r.status_code == 200:
        return "ok", r.json().get("user", {}).get("email", "")
    try:
        d = r.json()
    except Exception:
        d = {}
    code = d.get("error_code") or d.get("error") or ""
    msg = d.get("msg") or d.get("message") or d.get("error_description") or r.text[:120]
    if code in ("invalid_credentials", "invalid_grant", "user_not_found"):
        return "identifiants", "Supabase ne reconnaît pas cet e-mail avec ce mot de passe."
    if code == "email_not_confirmed":
        return "identifiants", "Ton e-mail n'est pas encore confirmé : clique sur le lien reçu de Supabase."
    if r.status_code in (401, 404) or "apikey" in msg.lower() or "api key" in msg.lower():
        return "url", "L'URL ou la clé anon ne correspondent pas à un projet Supabase ({}).".format(msg)
    return "autre", "Refus de Supabase ({}) : {}".format(r.status_code, msg)


def main():
    conf = lire()
    conf.setdefault("PAUSE", "5")
    if not conf.get("SUPABASE_URL") or not conf.get("SUPABASE_ANON_KEY"):
        conf["SUPABASE_URL"] = demander("URL Supabase (https://xxxx.supabase.co)", conf.get("SUPABASE_URL", ""))
        conf["SUPABASE_ANON_KEY"] = demander("Clé anon (publique) Supabase", conf.get("SUPABASE_ANON_KEY", ""))
    if not conf.get("EMAIL") or not conf.get("MOT_DE_PASSE"):
        conf["EMAIL"] = demander("E-mail de ton compte dans l'app", conf.get("EMAIL", ""))
        conf["MOT_DE_PASSE"] = demander("Mot de passe de l'app (rien ne s'affiche, c'est normal)", cache=True)
        print("     ({} caractères reçus)".format(len(conf["MOT_DE_PASSE"])))
    if "NTFY_TOPIC" not in conf:
        conf["NTFY_TOPIC"] = demander("Sujet ntfy pour les alertes iPhone (Entrée = aucun)")
    if "APP_URL" not in conf:
        conf["APP_URL"] = demander("Adresse de l'app (Entrée = plus tard)")

    for essai in range(4):
        etat, detail = tester(conf)
        if etat == "ok":
            ecrire(conf)
            print("     ✅ Connexion à Supabase réussie ({}).".format(detail))
            return 0
        print("     ⚠️  " + detail)
        if essai == 3:
            break
        if etat == "url":
            conf["SUPABASE_URL"] = demander("URL Supabase", conf.get("SUPABASE_URL", ""))
            conf["SUPABASE_ANON_KEY"] = demander("Clé anon (publique) Supabase", conf.get("SUPABASE_ANON_KEY", ""))
        else:
            print("     Utilise exactement l'e-mail et le mot de passe avec lesquels tu te connectes dans l'app.")
            conf["EMAIL"] = demander("E-mail", conf.get("EMAIL", ""))
            conf["MOT_DE_PASSE"] = demander("Mot de passe (rien ne s'affiche)", cache=True)
            print("     ({} caractères reçus)".format(len(conf["MOT_DE_PASSE"])))
    ecrire(conf)
    print("     ❌ Toujours refusé. Vérifie ton compte dans l'app, puis relance : bash installer.sh")
    return 1


if __name__ == "__main__":
    sys.exit(main())
