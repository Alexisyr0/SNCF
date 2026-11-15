#!/usr/bin/env python3
"""Robot de Première : tourne en fond sur le Mac, exécute les recherches demandées
depuis l'app (Mac ou iPhone), revérifie les trajets suivis chaque jour, analyse les rames.

  python robot.py            tourne en continu (c'est ce que lance l'installation)
  python robot.py --une-fois traite ce qui est en attente puis s'arrête
"""

import argparse
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from analyse import JOURS, MOIS, empreintes, extraire_trajets, passe_par_paris
from sncf import SNCF, Garde, Bloque, FormulaireImpossible, jours_entre, maintenant_paris
from supa import Supabase

VERSION = "3.0.0"
ICI = Path(__file__).resolve().parent
PROFIL = ICI / "navigateur-profil"
CAPTURES = ICI / "captures"


_LOGGER = logging.getLogger("premiere.robot")
_LOGGER.setLevel(logging.INFO)
if not _LOGGER.handlers:
    _handler = RotatingFileHandler(
        ICI / "robot.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    _handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%d/%m %H:%M:%S"))
    _LOGGER.addHandler(_handler)


def journal(*morceaux):
    message = " ".join(str(x) for x in morceaux)
    horodatage = datetime.now().strftime("%d/%m %H:%M:%S")
    print(horodatage, message, flush=True)
    _LOGGER.info(message)


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
    try:
        conf["PAUSE"] = str(max(10.0, float(conf.get("PAUSE", "15"))))
        conf["MAX_REQUETES_JOUR"] = str(max(1, int(conf.get("MAX_REQUETES_JOUR", "40"))))
        conf["COOLDOWN_ERREUR"] = str(max(30.0, float(conf.get("COOLDOWN_ERREUR", "300"))))
        conf["COOLDOWN_MAX"] = str(max(float(conf["COOLDOWN_ERREUR"]), float(conf.get("COOLDOWN_MAX", "3600"))))
    except (TypeError, ValueError):
        sys.exit("PAUSE, MAX_REQUETES_JOUR, COOLDOWN_ERREUR ou COOLDOWN_MAX invalide.")
    if not conf["SUPABASE_URL"].startswith("https://"):
        sys.exit("SUPABASE_URL doit commencer par https://.")
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
        self.pause = float(conf.get("PAUSE", 15))
        self.garde = Garde(
            pause=self.pause,
            max_jour=int(conf.get("MAX_REQUETES_JOUR", 40)),
            cooldown=float(conf.get("COOLDOWN_ERREUR", 300)),
            cooldown_max=float(conf.get("COOLDOWN_MAX", 3600)),
            chemin=ICI / "garde.json", journal=journal
        )
        self.db = Supabase(conf["SUPABASE_URL"], conf["SUPABASE_ANON_KEY"], conf["EMAIL"], conf["MOT_DE_PASSE"])
        self.db.connecter()
        self.dernier_signe = 0
        self.reinitialiser_interrompues()

    def reinitialiser_interrompues(self):
        """Une instance unique du robot est garantie par verrou local : les tâches
        restées en_cours au lancement précédent peuvent donc être reprises."""
        recherches = self.db.lire("train_recherches", statut="eq.en_cours", archive="is.false")
        for r in recherches:
            self.db.modifier("train_recherches", {"id": "eq." + r["id"]}, {
                "statut": "en_attente",
                "message": "Reprise après interruption du robot. Le dernier jour terminé est conservé."
            })
        analyses = self.db.lire("train_analyses", statut="eq.en_cours")
        for a in analyses:
            self.db.modifier("train_analyses", {"id": "eq." + a["id"]}, {
                "statut": "en_attente", "message": "Analyse relancée après interruption du robot."
            })
        if recherches or analyses:
            journal("Reprise :", len(recherches), "recherche(s),", len(analyses), "analyse(s) interrompue(s).")

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
            def apple(texte_brut):
                valeur = str(texte_brut).replace("\\", "\\\\")
                valeur = valeur.replace('"', '\\"').replace("\n", " ")
                return '"' + valeur + '"'
            script = 'display notification {} with title {} sound name "Glass"'.format(
                apple(texte), apple(titre)
            )
            subprocess.run(["osascript", "-e", script], timeout=10, check=False)
        except Exception:
            pass
        sujet = self.conf.get("NTFY_TOPIC")
        if sujet:
            try:
                entetes = {"Title": titre.encode("utf-8"), "Tags": "train"}
                if lien:
                    entetes["Click"] = lien
                requests.post("https://ntfy.sh/{}".format(sujet.strip("/")), data=texte.encode("utf-8"),
                              headers=entetes, timeout=(5, 15))
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
                         statut="in.(terminee,erreur)",
                         prochaine_execution="lte." + iso_maintenant(),
                         order="prochaine_execution.asc", limit=1)
        if r:
            return "recherche", r[0]
        return None, None

    def ouvrir_navigateur(self, p):
        options = dict(headless=False, viewport=None, locale="fr-FR")
        chrome = Path("/Applications/Google Chrome.app")
        if chrome.exists():
            try:
                ctx = p.chromium.launch_persistent_context(
                    str(PROFIL), channel="chrome", **options
                )
            except Exception as e:
                raise RuntimeError(
                    "Chrome est installé mais n'a pas pu démarrer avec le profil Première. "
                    "Ferme les fenêtres Chrome utilisant ce profil puis relance le robot. "
                    "Détail : {}".format(str(e)[:220])
                )
        else:
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
    def _empreinte_recherche(self, rech):
        champs = ("origine", "destination", "aller_debut", "aller_fin", "retour_debut",
                  "retour_fin", "nuits_min", "nuits_max", "classe", "inoui_seul",
                  "via_paris", "voyageurs", "chiens")
        contenu = {k: rech.get(k) for k in champs}
        brut = json.dumps(contenu, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(brut.encode("utf-8")).hexdigest()

    def _charger_resultats_execution(self, execution_id, rech):
        lignes = self.db.lire_tout(
            "train_releves", execution_id="eq." + execution_id,
            select="sens,jour,depart,arrivee,duree,correspondances,trains,tarif,conditions,via,numeros,legs,prix,chien,chien_estime,total,cle"
        )
        meilleurs = {"aller": {}, "retour": {}}
        tous = {"aller": [], "retour": []}
        for l in lignes:
            sens = l.get("sens")
            if sens not in tous:
                continue
            t = dict(l)
            tous[sens].append(t)
            if rech.get("via_paris") and not passe_par_paris(t):
                continue
            jour = t.get("jour")
            if jour:
                prix_total = float(t.get("total") or 0)
                if jour not in meilleurs[sens] or prix_total < meilleurs[sens][jour]:
                    meilleurs[sens][jour] = prix_total
        return meilleurs, tous

    def faire_recherche(self, rech, p):
        rid = rech["id"]
        titre = "{} → {}".format(rech["origine"], rech["destination"])
        journal("▶︎ Recherche", titre)

        sens = [("aller", rech["origine"], rech["destination"],
                 date.fromisoformat(rech["aller_debut"]), date.fromisoformat(rech["aller_fin"]))]
        if rech.get("retour_debut") and rech.get("retour_fin"):
            sens.append(("retour", rech["destination"], rech["origine"],
                         date.fromisoformat(rech["retour_debut"]), date.fromisoformat(rech["retour_fin"])))
        if any(fin < debut for _, _, _, debut, fin in sens):
            raise ValueError("Une date de fin est antérieure à sa date de début.")
        total_jours = sum((f - d).days + 1 for _, _, _, d, f in sens)
        signature = self._empreinte_recherche(rech)
        checkpoint = rech.get("checkpoint") or {}
        execution_id = checkpoint.get("execution_id") if checkpoint.get("signature") == signature else None

        if execution_id:
            existante = self.db.lire("train_executions", id="eq." + execution_id, limit=1)
            if not existante:
                execution_id = None
        if execution_id:
            ex = existante[0]
            journal("  Reprise de l'exécution", execution_id)
        else:
            ex = self.db.ajouter("train_executions", [{
                "recherche_id": rid, "user_id": self.db.user_id
            }])[0]
            execution_id = ex["id"]
            checkpoint = {
                "signature": signature, "execution_id": execution_id,
                "sens_index": 0, "jour": sens[0][3].isoformat()
            }
            self.db.modifier("train_recherches", {"id": "eq." + rid}, {"checkpoint": checkpoint})

        meilleurs, tous = self._charger_resultats_execution(execution_id, rech)
        index_reprise = min(int(checkpoint.get("sens_index", 0)), len(sens))
        faits = sum((fin - debut).days + 1 for _, _, _, debut, fin in sens[:index_reprise])
        if index_reprise < len(sens) and checkpoint.get("jour"):
            faits += max(0, (date.fromisoformat(checkpoint["jour"]) - sens[index_reprise][3]).days)

        self.db.modifier("train_recherches", {"id": "eq." + rid}, {
            "statut": "en_cours", "progression": int(faits * 100 / max(total_jours, 1)),
            "message": "Reprise de la recherche…" if faits else "Ouverture de SNCF Connect…"
        })

        ctx, page = self.ouvrir_navigateur(p)
        robot = SNCF(page, pause=self.pause, journal=journal, garde=self.garde)
        try:
            debut_sens = int(checkpoint.get("sens_index", 0))
            for idx in range(debut_sens, len(sens)):
                nom_sens, o, d, debut, fin = sens[idx]
                jour_depart = date.fromisoformat(
                    checkpoint.get("jour", debut.isoformat()) if idx == debut_sens else debut.isoformat()
                )
                if jour_depart < debut or jour_depart > fin:
                    jour_depart = debut
                self.signe_de_vie(titre, force=True)
                try:
                    _, data = robot.rechercher(
                        o, d, jour_depart, rech.get("voyageurs") or [],
                        rech.get("chiens") or 0
                    )
                except FormulaireImpossible as e:
                    shot = self.capture(page, "acces-ou-formulaire")
                    journal("Intervention nécessaire :", e, shot or "")
                    self.db.modifier("train_recherches", {"id": "eq." + rid}, {
                        "statut": "bloquee",
                        "message": "Intervention nécessaire dans la fenêtre Chrome du Mac. "
                                   "Termine la vérification ou lance la recherche manuellement, "
                                   "puis relance depuis l'app."
                    })
                    self.notifier(
                        "Première : intervention nécessaire",
                        "Ouvre la fenêtre Chrome du Mac pour terminer la vérification ou la recherche."
                    )
                    data = robot.attendre_recherche_manuelle()
                for j in jours_entre(jour_depart, fin):
                    if j != jour_depart:
                        data = self._jour_suivant(robot, rid, j)
                    lignes = []
                    vus = set()
                    for rep in robot.suivants_du_jour(data):
                        for t in extraire_trajets(rep, rech.get("classe", "1re"),
                                                  rech.get("inoui_seul", True)):
                            if t["cle"] in vus or t["jour"] != j.isoformat():
                                continue
                            vus.add(t["cle"])
                            lignes.append({
                                "execution_id": execution_id, "recherche_id": rid,
                                "user_id": self.db.user_id, "sens": nom_sens,
                                "jour": t["jour"], "depart": t["depart"], "arrivee": t["arrivee"],
                                "duree": t["duree"], "correspondances": t["correspondances"],
                                "trains": t["trains"], "tarif": t["tarif"],
                                "conditions": t["conditions"], "via": t["via"],
                                "numeros": t["numeros"], "legs": t["legs"], "prix": t["prix"],
                                "chien": t["chien"], "chien_estime": t["chien_estime"],
                                "total": t["total"], "cle": t["cle"]
                            })
                    if lignes:
                        deja = self.db.lire(
                            "train_releves", execution_id="eq." + execution_id,
                            sens="eq." + nom_sens, jour="eq." + j.isoformat(), select="cle"
                        )
                        cles_existantes = {x.get("cle") for x in deja}
                        nouvelles = [x for x in lignes if x.get("cle") not in cles_existantes]
                        if nouvelles:
                            self.db.ajouter("train_releves", nouvelles, retour=False)

                    # Le point de reprise n'avance qu'après l'écriture et le contrôle du jour.
                    faits += 1
                    prochain = j + timedelta(days=1)
                    if prochain <= fin:
                        cp = {"signature": signature, "execution_id": execution_id,
                              "sens_index": idx, "jour": prochain.isoformat()}
                    elif idx + 1 < len(sens):
                        cp = {"signature": signature, "execution_id": execution_id,
                              "sens_index": idx + 1, "jour": sens[idx + 1][3].isoformat()}
                    else:
                        cp = {"signature": signature, "execution_id": execution_id,
                              "sens_index": len(sens), "jour": None}
                    self.db.modifier("train_recherches", {"id": "eq." + rid}, {
                        "checkpoint": cp,
                        "statut": "en_cours",
                        "progression": min(99, int(faits * 100 / max(total_jours, 1))),
                        "message": "{} : {} ({} train{})".format(
                            nom_sens.capitalize(), jour_fr(j), len(lignes),
                            "s" if len(lignes) > 1 else "")
                    })
                    journal("  {} {:<26} {:>3} trains".format(
                        nom_sens, jour_fr(j), len(lignes)))
                    self.signe_de_vie(titre)

            # Relit les données persistées : le résumé reste exact après une reprise
            # ou une insertion qui aurait été dédupliquée par PostgreSQL.
            meilleurs, tous = self._charger_resultats_execution(execution_id, rech)
            self.db.modifier("train_recherches", {"id": "eq." + rid}, {"checkpoint": None})
            return ex, meilleurs, tous
        except Bloque as e:
            self.db.modifier("train_recherches", {"id": "eq." + rid}, {
                "statut": "bloquee",
                "message": "Recherche arrêtée par un garde-fou SNCF. Consulte le journal et la procédure de réactivation avant de relancer."
            })
            self.db.modifier("train_executions", {"id": "eq." + execution_id}, {
                "fin": iso_maintenant(), "statut": "interrompue", "message": str(e)[:300]
            })
            self.notifier("Première : accès interrompu", "Le robot est en pause. Vérifie Chrome sur le Mac.")
            raise
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    def _jour_suivant(self, robot, rid, j):
        try:
            return robot.jour_suivant(j)
        except Bloque:
            self.db.modifier("train_recherches", {"id": "eq." + rid}, {
                "statut": "bloquee", "message": "SNCF Connect a interrompu la recherche. Le robot est arrêté. Vérifie le site avant toute réactivation."})
            raise

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
            robot = SNCF(page, pause=self.pause, journal=journal, garde=self.garde)
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
        except Bloque as e:
            self.capture(page, "rame")
            self.db.modifier("train_analyses", {"id": "eq." + aid}, {"statut": "bloquee", "message": str(e)})
            journal("  accès SNCF interrompu :", e)
        except FormulaireImpossible as e:
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
                    journal(traceback.format_exc())
                    table = "train_analyses" if genre == "analyse" else "train_recherches"
                    valeurs = {"statut": "erreur", "message": "Erreur du robot : {}".format(str(e)[:300])}
                    if genre == "recherche" and travail.get("suivi"):
                        valeurs["prochaine_execution"] = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
                    try:
                        # Ne pas écraser l'état bloquée déjà posé par faire_recherche.
                        courant = self.db.lire(table, id="eq." + travail["id"], select="statut", limit=1)
                        if not courant or courant[0].get("statut") != "bloquee":
                            self.db.modifier(table, {"id": "eq." + travail["id"]}, valeurs)
                    except Exception:
                        pass
                    time.sleep(10)
                self.signe_de_vie(None, force=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--une-fois", action="store_true")
    ap.add_argument("--reinitialiser-garde", action="store_true", help="réactive le robot après vérification manuelle de SNCF Connect")
    args = ap.parse_args()

    if args.reinitialiser_garde:
        garde = Garde(chemin=ICI / "garde.json", journal=journal)
        garde.reinitialiser()
        journal("Garde réinitialisée manuellement. Relance maintenant le LaunchAgent.")
        return 0

    # Empêche deux LaunchAgents ou deux lancements manuels de traiter la même file.
    verrou = open(ICI / "robot.lock", "w")
    try:
        fcntl.flock(verrou.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        journal("Une autre instance de Première Robot tourne déjà. Arrêt de cette instance.")
        return 0

    try:
        robot = Robot(lire_config())
    except (RuntimeError, requests.RequestException, ValueError, SystemExit) as e:
        journal("❌", e)
        journal("Vérifie la configuration puis relance : bash {}/installer.sh".format(ICI))
        time.sleep(300)  # évite une boucle de redémarrage LaunchAgent en cas d'erreur de configuration
        return 1
    robot.tourner(une_fois=args.une_fois)
    return 0


if __name__ == "__main__":
    main()
