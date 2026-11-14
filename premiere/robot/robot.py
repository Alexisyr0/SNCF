#!/usr/bin/env python3
"""Robot de Première : tourne en fond sur le Mac, exécute les recherches demandées
depuis l'app (Mac ou iPhone), revérifie les trajets suivis chaque jour, analyse les rames.

  python robot.py            tourne en continu (c'est ce que lance l'installation)
  python robot.py --une-fois traite ce qui est en attente puis s'arrête
"""

import argparse
import subprocess
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from analyse import JOURS, MOIS, empreintes, extraire_trajets, passe_par_paris
from sncf import SNCF, Bloque, FormulaireImpossible, jours_entre, maintenant_paris
from supa import Supabase

VERSION = "1.0"
ICI = Path(__file__).resolve().parent
PROFIL = ICI / "navigateur-profil"
CAPTURES = ICI / "captures"


def journal(*morceaux):
    print(datetime.now().strftime("%d/%m %H:%M:%S"), *morceaux, flush=True)


def lire_config():
    conf = {}
    fichier = ICI / "config.env"
    if fichier.exists():
        for ligne in fichier.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if ligne and not ligne.startswith("#") and "=" in ligne:
                k, v = ligne.split("=", 1)
                conf[k.strip()] = v.strip()
    for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "EMAIL", "MOT_DE_PASSE"):
        if not conf.get(k):
            sys.exit("Il manque {} dans robot/config.env (relance installer.sh).".format(k))
    return conf


def iso_maintenant():
    return datetime.now(timezone.utc).isoformat()


def jour_fr(d):
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return "{} {} {}".format(JOURS[d.weekday()], d.day, MOIS[d.month - 1])


def euros(v):
    if v is None:
        return "–"
    s = "{:,.2f}".format(v).replace(",", " ").replace(".", ",")
    return (s[:-3] if s.endswith(",00") else s) + " €"


class Robot:
    def __init__(self, conf):
        self.conf = conf
        self.pause = float(conf.get("PAUSE", 5))
        self.db = Supabase(conf["SUPABASE_URL"], conf["SUPABASE_ANON_KEY"], conf["EMAIL"], conf["MOT_DE_PASSE"])
        self.db.connecter()
        self.dernier_signe = 0

    # --- présence et notifications ---------------------------------------------
    def signe_de_vie(self, occupe=None, force=False):
        if not force and time.time() - self.dernier_signe < 30:
            return
        try:
            self.db.remplacer("train_robot", {"user_id": self.db.user_id, "vu_le": iso_maintenant(),
                                              "version": VERSION, "occupe": occupe})
            self.dernier_signe = time.time()
        except Exception as e:
            journal("signe de vie impossible :", e)

    def notifier(self, titre, texte, lien=None):
        journal("🔔", titre, "—", texte)
        try:
            subprocess.run(["osascript", "-e", 'display notification "{}" with title "{}" sound name "Glass"'.format(
                texte.replace('"', "'"), titre.replace('"', "'"))], timeout=10, check=False)
        except Exception:
            pass
        sujet = self.conf.get("NTFY_TOPIC")
        if sujet:
            try:
                entetes = {"Title": titre.encode("utf-8"), "Tags": "train"}
                if lien:
                    entetes["Click"] = lien
                requests.post("https://ntfy.sh/{}".format(sujet), data=texte.encode("utf-8"),
                              headers=entetes, timeout=15)
            except Exception as e:
                journal("ntfy impossible :", e)

    # --- file d'attente ---------------------------------------------------------
    def prochain_travail(self):
        a = self.db.lire("train_analyses", statut="eq.en_attente", order="created_at.asc", limit=1)
        if a:
            return "analyse", a[0]
        r = self.db.lire("train_recherches", statut="eq.en_attente", archive="is.false",
                         order="created_at.asc", limit=1)
        if r:
            return "recherche", r[0]
        r = self.db.lire("train_recherches", suivi="is.true", archive="is.false",
                         statut="in.(terminee,erreur,bloquee)",
                         prochaine_execution="lte." + iso_maintenant(),
                         order="prochaine_execution.asc", limit=1)
        if r:
            return "recherche", r[0]
        return None, None

    def ouvrir_navigateur(self, p):
        options = dict(headless=False, viewport=None, locale="fr-FR")
        try:
            ctx = p.chromium.launch_persistent_context(str(PROFIL), channel="chrome", **options)
        except Exception:
            ctx = p.chromium.launch_persistent_context(str(PROFIL), **options)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        return ctx, page

    def capture(self, page, nom):
        try:
            CAPTURES.mkdir(exist_ok=True)
            chemin = CAPTURES / "{}-{}.png".format(datetime.now().strftime("%Y%m%d-%H%M%S"), nom)
            page.screenshot(path=str(chemin))
            return chemin.name
        except Exception:
            return None

    # --- une recherche ------------------------------------------------------------
    def faire_recherche(self, rech, p):
        rid = rech["id"]
        titre = "{} → {}".format(rech["origine"], rech["destination"])
        journal("▶︎ Recherche", titre)
        ex = self.db.ajouter("train_executions", [{"recherche_id": rid, "user_id": self.db.user_id}])[0]
        self.db.modifier("train_recherches", {"id": "eq." + rid},
                         {"statut": "en_cours", "progression": 0, "message": "Ouverture de SNCF Connect…"})
        sens = [("aller", rech["origine"], rech["destination"],
                 date.fromisoformat(rech["aller_debut"]), date.fromisoformat(rech["aller_fin"]))]
        if rech.get("retour_debut") and rech.get("retour_fin"):
            sens.append(("retour", rech["destination"], rech["origine"],
                         date.fromisoformat(rech["retour_debut"]), date.fromisoformat(rech["retour_fin"])))
        total_jours = sum((f - d).days + 1 for _, _, _, d, f in sens)
        faits = 0
        meilleurs = {"aller": {}, "retour": {}}
        tous = {"aller": [], "retour": []}
        ctx, page = self.ouvrir_navigateur(p)
        robot = SNCF(page, pause=self.pause, journal=journal)
        try:
            for nom_sens, o, d, debut, fin in sens:
                self.signe_de_vie(titre, force=True)
                try:
                    _, data = robot.rechercher(o, d, debut, rech.get("voyageurs") or [], rech.get("chiens") or 0)
                except FormulaireImpossible as e:
                    shot = self.capture(page, "formulaire")
                    journal("Formulaire :", e, shot or "")
                    self.db.modifier("train_recherches", {"id": "eq." + rid}, {
                        "statut": "bloquee",
                        "message": "Je n'arrive pas à remplir le formulaire ({}). Fais la recherche {} → {} du {} "
                                   "dans la fenêtre Chrome du Mac, je reprends ensuite.".format(e, o, d, jour_fr(debut))})
                    self.notifier("Première : coup de main", "Lance la recherche {} → {} du {} dans la fenêtre du Mac."
                                  .format(o, d, jour_fr(debut)))
                    data = robot.attendre_recherche_manuelle()
                for j in jours_entre(debut, fin):
                    if j != debut:
                        data = self._jour_suivant(robot, rid, j)
                    lignes = []
                    vus = set()
                    for rep in robot.suivants_du_jour(data):
                        for t in extraire_trajets(rep, rech.get("classe", "1re"), rech.get("inoui_seul", True)):
                            if t["cle"] in vus or t["jour"] != j.isoformat():
                                continue
                            vus.add(t["cle"])
                            tous[nom_sens].append(t)
                            lignes.append({
                                "execution_id": ex["id"], "recherche_id": rid, "user_id": self.db.user_id,
                                "sens": nom_sens, "jour": t["jour"], "depart": t["depart"], "arrivee": t["arrivee"],
                                "duree": t["duree"], "correspondances": t["correspondances"], "trains": t["trains"],
                                "tarif": t["tarif"], "conditions": t["conditions"], "via": t["via"],
                                "numeros": t["numeros"], "legs": t["legs"], "prix": t["prix"], "chien": t["chien"],
                                "chien_estime": t["chien_estime"], "total": t["total"], "cle": t["cle"]})
                    if lignes:
                        self.db.ajouter("train_releves", lignes, retour=False)
                    gardes = [l for l in lignes if not rech.get("via_paris") or passe_par_paris(l)]
                    if gardes:
                        meilleurs[nom_sens][j.isoformat()] = min(l["total"] for l in gardes)
                    faits += 1
                    self.db.modifier("train_recherches", {"id": "eq." + rid}, {
                        "statut": "en_cours", "progression": int(faits * 100 / total_jours),
                        "message": "{} : {} ({} train{})".format(nom_sens.capitalize(), jour_fr(j), len(lignes),
                                                                  "s" if len(lignes) > 1 else "")})
                    journal("  {} {:<26} {:>3} trains  min {}".format(
                        nom_sens, jour_fr(j), len(lignes), euros(meilleurs[nom_sens].get(j.isoformat()))))
                    self.signe_de_vie(titre)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
        return ex, meilleurs, tous

    def _jour_suivant(self, robot, rid, j):
        try:
            return robot.jour_suivant(j)
        except Bloque as e:
            self.db.modifier("train_recherches", {"id": "eq." + rid}, {
                "statut": "bloquee", "message": "SNCF Connect demande une vérification : fais-la dans la fenêtre "
                                                "Chrome du Mac, puis clique sur le {} dans le bandeau des dates.".format(jour_fr(j))})
            self.notifier("Première : vérification SNCF", "Fais la vérification dans la fenêtre du Mac. ({})".format(e))
            return robot.attendre_recherche_manuelle()

    def apres_recherche(self, rech, ex, meilleurs, tous):
        rid = rech["id"]
        b_aller = min(meilleurs["aller"].values()) if meilleurs["aller"] else None
        b_retour = min(meilleurs["retour"].values()) if meilleurs["retour"] else None
        b_total = b_aller
        couple = None
        if rech.get("retour_debut"):
            b_total = None
            nmin, nmax = rech.get("nuits_min") or 0, rech.get("nuits_max")
            for ja, pa in meilleurs["aller"].items():
                for jr, pr in meilleurs["retour"].items():
                    n = (date.fromisoformat(jr) - date.fromisoformat(ja)).days
                    if n < nmin or (nmax is not None and n > nmax):
                        continue
                    if b_total is None or pa + pr < b_total:
                        b_total, couple = pa + pr, (ja, jr)
        self.db.modifier("train_executions", {"id": "eq." + ex["id"]}, {
            "fin": iso_maintenant(), "statut": "terminee", "meilleur_aller": b_aller,
            "meilleur_retour": b_retour, "meilleur_total": b_total})

        prochaine = None
        if rech.get("suivi"):
            mp = maintenant_paris()
            demain = (mp + timedelta(days=1)).replace(hour=int(rech.get("heure_suivi") or 8), minute=5,
                                                      second=0, microsecond=0)
            prochaine = demain.isoformat()
        if b_total is None:
            msg = "Aucun train ne correspond sur la période."
        elif couple:
            msg = "Meilleur aller-retour : {} ({} + {})".format(euros(b_total), jour_fr(couple[0]), jour_fr(couple[1]))
        else:
            msg = "Meilleur prix : {}".format(euros(b_total))
        self.db.modifier("train_recherches", {"id": "eq." + rid}, {
            "statut": "terminee", "progression": 100, "message": msg,
            "derniere_execution": iso_maintenant(), "prochaine_execution": prochaine})

        # Baisse de prix par rapport au passage précédent ?
        precedents = self.db.lire("train_executions", recherche_id="eq." + rid, statut="eq.terminee",
                                  id="neq." + ex["id"], order="debut.desc", limit=1)
        ancien = precedents[0].get("meilleur_total") if precedents else None
        seuil = rech.get("seuil")
        if b_total is not None and ancien is not None:
            ancien = float(ancien)
            baisse = b_total <= ancien - 1
            sous_seuil = seuil is not None and b_total <= float(seuil) < ancien
            if baisse or sous_seuil:
                detail = msg
                self.db.ajouter("train_alertes", [{"user_id": self.db.user_id, "recherche_id": rid,
                                                   "ancien": ancien, "nouveau": b_total, "detail": detail}], retour=False)
                self.notifier("Première : le prix baisse",
                              "{} → {} : {} (avant {})".format(rech["origine"], rech["destination"],
                                                              euros(b_total), euros(ancien)),
                              self.conf.get("APP_URL"))
        elif b_total is not None and seuil is not None and b_total <= float(seuil):
            self.notifier("Première : sous ton seuil", "{} → {} : {}".format(
                rech["origine"], rech["destination"], euros(b_total)), self.conf.get("APP_URL"))

        # Rames des meilleurs trains : on demande leur plan de salle
        if rech.get("analyser_rames"):
            self.programmer_analyses(rech, tous)

    def programmer_analyses(self, rech, tous):
        candidats = []
        for nom_sens in ("aller", "retour"):
            liste = [t for t in tous[nom_sens] if not rech.get("via_paris") or passe_par_paris(t)]
            for t in sorted(liste, key=lambda t: t["total"])[:3]:
                for leg in t["legs"]:
                    if leg.get("type") == "TGV INOUI" and leg.get("num") and leg.get("de") and leg.get("dep"):
                        candidats.append((t["jour"], leg))
        deja = set()
        recents = self.db.lire("train_voitures", select="numero_train,jour",
                               created_at="gte." + (datetime.now(timezone.utc) - timedelta(days=5)).isoformat())
        for v in recents:
            deja.add((v["numero_train"], v["jour"]))
        attente = self.db.lire("train_analyses", select="numero,jour", statut="in.(en_attente,en_cours)")
        for a in attente:
            deja.add((a["numero"], a["jour"]))
        nouvelles = []
        for jour, leg in candidats:
            if (leg["num"], jour) in deja or len(nouvelles) >= 8:
                continue
            deja.add((leg["num"], jour))
            nouvelles.append({"user_id": self.db.user_id, "recherche_id": rech["id"], "jour": jour,
                              "origine": leg["de"].split(" - ")[0], "destination": leg["a"].split(" - ")[0],
                              "depart": leg["dep"], "numero": leg["num"]})
        if nouvelles:
            self.db.ajouter("train_analyses", nouvelles, retour=False)
            journal("  {} plan(s) de salle à analyser".format(len(nouvelles)))

    # --- une analyse de rame ---------------------------------------------------------
    def faire_analyse(self, an, p):
        aid = an["id"]
        journal("▶︎ Rame", an.get("numero") or "", an["origine"], "→", an["destination"], an["jour"], an["depart"])
        self.db.modifier("train_analyses", {"id": "eq." + aid}, {"statut": "en_cours", "message": None})
        ctx, page = self.ouvrir_navigateur(p)
        try:
            robot = SNCF(page, pause=self.pause, journal=journal)
            plan = robot.plan_de_salle(an["origine"], an["destination"], date.fromisoformat(an["jour"]),
                                       an["depart"], an.get("numero"))
            voitures = empreintes(plan)
            if not voitures:
                raise FormulaireImpossible("Plan de salle vide.")
            self.db.ajouter("train_voitures", [{
                "user_id": self.db.user_id, "analyse_id": aid, "numero_train": an.get("numero") or "?",
                "jour": an["jour"], "voiture": v["voiture"], "classe": v["classe"], "signature": v["signature"],
                "resume": v["resume"], "plan": v["plan"]} for v in voitures], retour=False)
            connues = {e["signature"]: e["etiquette"] for e in self.db.lire("train_etiquettes")}
            reperees = sorted({connues[v["signature"]] for v in voitures if v["signature"] in connues})
            msg = "{} voitures analysées".format(len(voitures)) + (" · " + ", ".join(reperees) if reperees else "")
            self.db.modifier("train_analyses", {"id": "eq." + aid}, {"statut": "terminee", "message": msg})
            journal("  ", msg)
        except (FormulaireImpossible, Bloque) as e:
            self.capture(page, "rame")
            self.db.modifier("train_analyses", {"id": "eq." + aid}, {"statut": "erreur", "message": str(e)})
            journal("  rame impossible :", e)
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    # --- boucle ------------------------------------------------------------------------
    def tourner(self, une_fois=False):
        journal("Robot Première {} prêt ({}).".format(VERSION, self.conf["EMAIL"]))
        with sync_playwright() as p:
            while True:
                self.signe_de_vie(None)
                try:
                    genre, travail = self.prochain_travail()
                except Exception as e:
                    journal("Supabase injoignable :", e)
                    genre, travail = None, None
                if genre is None:
                    if une_fois:
                        journal("Plus rien en attente.")
                        return
                    time.sleep(20)
                    continue
                try:
                    if genre == "analyse":
                        self.signe_de_vie("Plan de salle {}".format(travail.get("numero") or ""), force=True)
                        self.faire_analyse(travail, p)
                    else:
                        ex, meilleurs, tous = self.faire_recherche(travail, p)
                        self.apres_recherche(travail, ex, meilleurs, tous)
                except Exception as e:
                    journal("Erreur :", e)
                    traceback.print_exc()
                    table = "train_analyses" if genre == "analyse" else "train_recherches"
                    valeurs = {"statut": "erreur", "message": "Erreur du robot : {}".format(str(e)[:300])}
                    if genre == "recherche" and travail.get("suivi"):
                        valeurs["prochaine_execution"] = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
                    try:
                        self.db.modifier(table, {"id": "eq." + travail["id"]}, valeurs)
                    except Exception:
                        pass
                    time.sleep(10)
                self.signe_de_vie(None, force=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--une-fois", action="store_true")
    args = ap.parse_args()
    try:
        robot = Robot(lire_config())
    except RuntimeError as e:
        journal("❌", e)
        journal("Corrige l'e-mail ou le mot de passe avec : bash {}/installer.sh".format(ICI))
        time.sleep(300)  # évite de réessayer en boucle avec de mauvais identifiants
        sys.exit(1)
    robot.tourner(une_fois=args.une_fois)


if __name__ == "__main__":
    main()
