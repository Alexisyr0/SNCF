"""Automatisation contrôlée de l'interface SNCF Connect dans Chrome.

Le robot utilise les interactions de page et observe les réponses chargées par le site.
Il s'arrête sur les refus ou vérifications d'accès.
"""

import json
import re
import time
import unicodedata
from pathlib import Path
from datetime import datetime, timedelta

from playwright.sync_api import TimeoutError as PWTimeout

from analyse import JOURS, MOIS, journee_terminee

URL_FORMULAIRE = "https://www.sncf-connect.com/home/search/od"
API_RECHERCHE = "/bff/api/v1/itineraries"
API_SUIVANTS = "/bff/api/v1/itineraries/more"
TRANCHES = [(4, "CHILD_UNDER_FOUR"), (30, "YOUNG"), (60, "ADULT"), (200, "SENIOR")]


class Bloque(Exception):
    """SNCF Connect demande une vérification ou refuse la demande."""


class FormulaireImpossible(Exception):
    """Le robot n'a pas réussi à remplir le formulaire tout seul."""


class Garde:
    """Limiteur local persistant : cadence, quota journalier et coupe-circuit."""
    def __init__(self, pause=15, max_jour=40, cooldown=300, cooldown_max=3600,
                 chemin=None, journal=print):
        self.pause = max(10.0, float(pause))
        self.max_jour = max(1, int(max_jour))
        self.cooldown = max(30.0, float(cooldown))
        self.cooldown_max = max(self.cooldown, float(cooldown_max))
        self.chemin = Path(chemin or Path(__file__).resolve().parent / "garde.json")
        self.journal = journal
        self.etat = self._charger()

    def _charger(self):
        try:
            data = json.loads(self.chemin.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError, TypeError):
            pass
        return {"jour": "", "requêtes": 0, "derniere": 0, "erreurs": 0,
                "attendre_jusqua": 0, "bloque": False, "motif": ""}

    def _sauver(self):
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = self.chemin.with_suffix(".tmp")
        temporaire.write_text(json.dumps(self.etat, ensure_ascii=False, indent=2), encoding="utf-8")
        temporaire.replace(self.chemin)

    def reinitialiser(self):
        self.etat = {"jour": "", "requêtes": 0, "derniere": 0, "erreurs": 0,
                     "attendre_jusqua": 0, "bloque": False, "motif": ""}
        self._sauver()

    def verifier_disponible(self):
        maintenant = time.time()
        jour = time.strftime("%Y-%m-%d", time.localtime(maintenant))
        if self.etat.get("bloque"):
            raise Bloque("Coupe-circuit actif : {}. Vérifie SNCF Connect puis réinitialise la garde manuellement.".format(
                self.etat.get("motif") or "incident précédent"))
        if self.etat.get("jour") != jour:
            self.etat["jour"] = jour
            self.etat["requêtes"] = 0
        if int(self.etat.get("requêtes", 0)) >= self.max_jour:
            self._sauver()
            raise Bloque("Quota quotidien atteint ({} requêtes). Le robot reprendra après changement de jour.".format(self.max_jour))

    def avant_requete(self):
        self.verifier_disponible()
        maintenant = time.time()
        cible = max(float(self.etat.get("derniere", 0)) + self.pause,
                    float(self.etat.get("attendre_jusqua", 0)))
        attente = cible - maintenant
        if attente > 0:
            self.journal("  Garde : pause de {:.0f} s avant la prochaine requête.".format(attente))
            time.sleep(attente)
        jour = time.strftime("%Y-%m-%d", time.localtime())
        self.etat["jour"] = jour
        self.etat["requêtes"] = int(self.etat.get("requêtes", 0)) + 1
        self.etat["derniere"] = time.time()
        self._sauver()

    def requete_observee(self):
        """Comptabilise une requête déclenchée directement dans Chrome par l'utilisateur ou le site."""
        jour = time.strftime("%Y-%m-%d", time.localtime())
        if self.etat.get("jour") != jour:
            self.etat["jour"] = jour
            self.etat["requêtes"] = 0
        if int(self.etat.get("requêtes", 0)) >= self.max_jour:
            self.bloquer("quota quotidien atteint pendant une action manuelle")
            raise Bloque("Quota quotidien atteint ({} requêtes).".format(self.max_jour))
        self.etat["requêtes"] = int(self.etat.get("requêtes", 0)) + 1
        self.etat["derniere"] = time.time()
        self._sauver()

    def succes(self):
        self.etat["erreurs"] = 0
        self.etat["attendre_jusqua"] = 0
        self._sauver()

    def erreur_reseau(self, motif):
        erreurs = int(self.etat.get("erreurs", 0)) + 1
        delai = min(self.cooldown_max, self.cooldown * (2 ** min(erreurs - 1, 10)))
        self.etat["erreurs"] = erreurs
        self.etat["attendre_jusqua"] = time.time() + delai
        self._sauver()
        self.journal("  Garde : incident réseau, prochaine tentative différée d'au moins {:.0f} s ({})".format(delai, motif))

    def bloquer(self, motif):
        self.etat["bloque"] = True
        self.etat["motif"] = str(motif)[:300]
        self._sauver()


def _chemin(url):
    return url.split("?")[0].split("sncf-connect.com")[-1]


def est_recherche(r):
    return r.request.method == "POST" and _chemin(r.url) == API_RECHERCHE


def est_suivants(r):
    return r.request.method == "POST" and _chemin(r.url) == API_SUIVANTS


def _norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _lire(rep):
    """Lit une réponse attendue et s'arrête sur les refus explicites."""
    statut = rep.status
    try:
        corps = rep.text()[:12000].lower()
    except Exception:
        corps = ""
    marqueurs = (
        "accès temporairement restreint", "acces temporairement restreint",
        "trafic inhabituel", "vérifiez que vous êtes humain",
        "verify you are human", "captcha", "access denied",
        "request blocked", "temporarily restricted"
    )
    if statut in (401, 403, 407, 429, 503) or any(m in corps for m in marqueurs):
        raise Bloque("SNCF Connect a présenté un refus ou une vérification (HTTP {}).".format(statut))
    if statut != 200:
        raise Bloque("Réponse SNCF Connect inattendue (HTTP {}).".format(statut))
    try:
        data = rep.json()
    except Exception:
        raise Bloque("SNCF Connect n'a pas renvoyé une réponse exploitable.")
    if isinstance(data, dict):
        texte = json.dumps(data, ensure_ascii=False).lower()
        if any(m in texte for m in marqueurs):
            raise Bloque("SNCF Connect a renvoyé une page de restriction.")
    return data


def _verifier_page(page):
    """Détecte une page de vérification affichée sans se substituer à l'utilisateur."""
    try:
        texte = (page.locator("body").inner_text(timeout=1500) or "").lower()
    except Exception:
        return
    marqueurs = (
        "accès temporairement restreint", "acces temporairement restreint",
        "trafic inhabituel", "vérifiez que vous êtes humain",
        "verify you are human", "access denied", "captcha"
    )
    if any(m in texte for m in marqueurs):
        raise Bloque("Une page de restriction ou de vérification est affichée dans Chrome.")


class SNCF:
    def __init__(self, page, pause=15.0, journal=print, garde=None):
        self.page = page
        self.pause = pause
        self.journal = journal
        self.garde = garde

    def _lire_reponse(self, rep):
        try:
            data = _lire(rep)
        except Bloque as e:
            if self.garde:
                self.garde.bloquer(str(e))
            raise
        if self.garde:
            self.garde.succes()
        return data

    # --- petites aides -------------------------------------------------------
    def _verifier_page(self):
        try:
            _verifier_page(self.page)
        except Bloque as e:
            if self.garde:
                self.garde.bloquer(str(e))
            raise

    def _attendre(self, s=None):
        time.sleep(self.pause if s is None else s)

    def _dialogue(self):
        return self.page.get_by_role("dialog").last

    def fermer_dialogues(self):
        for _ in range(4):
            if self.page.get_by_role("dialog").count() == 0:
                return
            bouton = self.page.get_by_role("button", name=re.compile(r"^Fermer"))
            try:
                if bouton.count():
                    bouton.last.click(timeout=3000)
                else:
                    self.page.keyboard.press("Escape")
            except Exception:
                self.page.keyboard.press("Escape")
            time.sleep(0.8)

    def _cookies(self):
        bouton = self.page.get_by_role("button", name="Continuer sans accepter")
        try:
            bouton.wait_for(timeout=4000)
            bouton.click()
        except PWTimeout:
            pass

    # --- formulaire ----------------------------------------------------------
    def _lieu(self, index, texte):
        champ = self.page.get_by_role("combobox", name="Gare, ville, lieu...").nth(index)
        champ.click()
        champ.fill("")
        champ.press_sequentially(texte, delay=70)
        options = self.page.locator('[role="option"]')
        options.first.wait_for(timeout=12000)
        time.sleep(0.6)
        cible, voulu = None, _norm(texte)
        n = min(options.count(), 10)
        lignes = []
        for i in range(n):
            o = options.nth(i)
            lignes.append((o, o.get_attribute("id") or "", _norm((o.inner_text() or "").split("\n")[0])))
        for o, oid, nom in lignes:  # la ville d'abord (toutes ses gares)
            if nom == voulu and oid.startswith("CITY_"):
                cible = o
                break
        if cible is None:
            for o, oid, nom in lignes:
                if nom == voulu:
                    cible = o
                    break
        if cible is None:
            exemples = ", ".join(nom for _, _, nom in lignes[:4])
            raise FormulaireImpossible(
                "La gare « {} » n'a pas été reconnue sans ambiguïté. Suggestions : {}"
                .format(texte, exemples or "aucune")
            )
        cible.click()
        time.sleep(0.6)

    def _date(self, jour, heure):
        self.page.get_by_role("button", name=re.compile(r"^Aller :")).first.click()
        nom = re.compile(r"^{} {:02d} {} {}".format(JOURS[jour.weekday()], jour.day,
                                                   MOIS[jour.month - 1], jour.year))
        bouton = self.page.get_by_role("button", name=nom).first
        bouton.wait_for(timeout=10000)
        bouton.scroll_into_view_if_needed()
        bouton.click()
        heure = max(0, min(22, heure - heure % 2))
        radio = self.page.get_by_role("radio", name=re.compile(r"^{:02d}h".format(heure)))
        if not radio.count():
            raise FormulaireImpossible("Le créneau de départ {}h n'est plus proposé.".format(heure))
        radio.first.click()
        self.page.get_by_role("button", name="Confirmer").click()
        time.sleep(0.8)

    def _voyageur(self, numero, age, carte):
        if numero == 1:
            self.page.get_by_text(re.compile(r"^Voyageur 1 :")).first.click()
        else:
            self.page.get_by_role("button", name="Ajouter un voyageur").click()
        dlg = self._dialogue()
        dlg.wait_for(timeout=8000)
        age = int(age)
        tranche = next(code for limite, code in TRANCHES if age < limite)
        dlg.locator("#typology").click()
        self.page.locator('[role="listbox"] [role="option"][data-value="{}"]'.format(tranche)).click()
        time.sleep(0.5)
        champ_age = dlg.get_by_label(re.compile(r"Âge"))
        if champ_age.count():
            champ_age.first.fill(str(age))
        if carte:
            dlg.get_by_role("button", name=re.compile(r"^Cartes de réduction")).click()
            time.sleep(0.8)
            case = self.page.get_by_role("checkbox", name=carte)
            if case.count() == 0:
                case = self.page.get_by_label(carte, exact=True)
            if case.count() == 0:
                raise FormulaireImpossible("Carte « {} » introuvable dans SNCF Connect.".format(carte))
            if not case.first.is_checked():
                case.first.click()
            self.page.get_by_role("button", name="Valider").click()
            time.sleep(0.8)
        self.page.get_by_role("button", name="Appliquer ce profil").click()
        time.sleep(0.8)

    def _retirer_voyageurs_en_trop(self):
        for _ in range(6):
            autres = self.page.get_by_text(re.compile(r"^Voyageur [2-9] :"))
            if autres.count() == 0:
                return
            autres.last.click()
            self.page.get_by_role("button", name="Retirer de la recherche").click()
            time.sleep(0.8)

    def _animaux(self, n):
        deja = self.page.get_by_text(re.compile(r"^Animal \d+$")).count()
        if deja == n:
            return
        if deja > n:
            raise FormulaireImpossible("Il y a déjà {} animal(aux) dans le formulaire.".format(deja))
        self.page.get_by_role("button", name="Ajouter un animal").click()
        plus = self.page.get_by_role("button", name="Ajouter un chien tenu en laisse et muselé")
        plus.wait_for(timeout=8000)
        for _ in range(n - deja):
            plus.click()
            time.sleep(0.4)
        self.page.get_by_role("button", name=re.compile(r"^Ajouter ce")).click()
        time.sleep(0.8)

    def _verifier(self, voyageurs, chiens):
        texte = self.page.locator("main").inner_text()
        for v in voyageurs:
            if v.get("carte") and v["carte"] not in texte:
                raise FormulaireImpossible("La carte « {} » n'apparaît pas dans le formulaire.".format(v["carte"]))
        if chiens and "Animal" not in texte:
            raise FormulaireImpossible("Le chien n'apparaît pas dans le formulaire.")

    def rechercher(self, origine, destination, jour, voyageurs, chiens, heure=4):
        """Remplit le formulaire et lance la recherche. Renvoie (jour, données)."""
        if self.garde:
            self.garde.verifier_disponible()
        self.page.goto(URL_FORMULAIRE, wait_until="domcontentloaded")
        self._verifier_page()
        self._cookies()
        try:
            self.page.get_by_role("combobox", name="Gare, ville, lieu...").first.wait_for(timeout=25000)
            self._lieu(0, origine)
            self._lieu(1, destination)
            self._date(jour, heure)
            self._retirer_voyageurs_en_trop()
            for i, v in enumerate(voyageurs or [{"age": 35, "carte": ""}], 1):
                self._voyageur(i, v.get("age", 35), v.get("carte") or "")
            self._animaux(int(chiens or 0))
            self._verifier(voyageurs or [], chiens)
        except FormulaireImpossible:
            raise
        except PWTimeout as e:
            raise FormulaireImpossible("Élément du formulaire introuvable ({}).".format(str(e).split("\n")[0][:120]))
        self._verifier_page()
        bouton = self.page.get_by_role("button", name="Voir les prix")
        if self.garde:
            self.garde.avant_requete()
        try:
            with self.page.expect_response(est_recherche, timeout=60000) as info:
                bouton.click()
        except PWTimeout:
            if self.garde:
                self.garde.erreur_reseau("délai dépassé sur la recherche")
            raise Bloque("Pas de réponse de SNCF Connect. Le robot s'arrête sans relancer la requête.")
        return jour, self._derniere_recherche(info.value)

    def _derniere_recherche(self, rep):
        data = self._lire_reponse(rep)
        while True:  # SNCF Connect relance parfois la recherche juste après : on garde la dernière
            try:
                rep = self.page.wait_for_event("response", predicate=est_recherche, timeout=6000)
                if self.garde:
                    self.garde.requete_observee()
                d = self._lire_reponse(rep)
                if d is not None:
                    data = d
            except PWTimeout:
                break
        if data is None:
            motif = "SNCF Connect n'a pas renvoyé de résultats exploitables."
            if self.garde:
                self.garde.bloquer(motif)
            raise Bloque(motif)
        return data

    def attendre_recherche_manuelle(self, delai_min=15):
        """Mode assisté : on attend que tu lances la recherche toi-même dans la fenêtre."""
        fin = time.time() + delai_min * 60
        while time.time() < fin:
            try:
                rep = self.page.wait_for_event("response", predicate=est_recherche, timeout=30000)
            except PWTimeout:
                continue
            if self.garde:
                self.garde.requete_observee()
            return self._derniere_recherche(rep)
        raise Bloque("Personne n'a relancé la recherche dans la fenêtre.")

    # --- parcours des jours --------------------------------------------------
    def _cliquer(self, bouton, predicat):
        if self.garde:
            self.garde.verifier_disponible()
        self._verifier_page()
        if self.garde:
            self.garde.avant_requete()
        else:
            self._attendre()
        try:
            with self.page.expect_response(predicat, timeout=45000) as info:
                bouton.click(timeout=15000)
        except PWTimeout:
            if self.garde:
                self.garde.erreur_reseau("délai dépassé sur une interaction")
            self._verifier_page()
            raise Bloque("Pas de réponse de SNCF Connect. Le robot s'arrête sans relancer la requête.")
        d = self._lire_reponse(info.value)
        self._verifier_page()
        if d is None:
            motif = "Réponse illisible de SNCF Connect."
            if self.garde:
                self.garde.bloquer(motif)
            raise Bloque(motif)
        return d

    def suivants_du_jour(self, data):
        """Fait défiler « Afficher les trajets suivants » ; renvoie toutes les réponses du jour."""
        reponses = [data]
        clics = 0
        while not journee_terminee(data) and clics < 15:
            bouton = self.page.get_by_role("button", name="Afficher les trajets suivants")
            if bouton.count() == 0:
                raise FormulaireImpossible(
                    "La pagination des trains s'est arrêtée avant la fin de la journée."
                )
            data = self._cliquer(bouton.first, est_suivants)
            reponses.append(data)
            clics += 1
        if not journee_terminee(data):
            raise FormulaireImpossible(
                "La limite de pagination a été atteinte ; journée non considérée comme complète."
            )
        return reponses

    def jour_suivant(self, jour):
        nom = re.compile(r"^Résultats pour le {} {}(er)? {} {}$".format(
            JOURS[jour.weekday()], jour.day, MOIS[jour.month - 1], jour.year))
        bouton = self.page.get_by_role("button", name=nom)
        if bouton.count() == 0:
            bouton = self.page.get_by_role("button", name="Afficher le jour suivant")
        if bouton.count() == 0:
            raise FormulaireImpossible("Impossible d'afficher le {} {}.".format(jour.day, MOIS[jour.month - 1]))
        return self._cliquer(bouton.first, est_recherche)

    # --- plan de salle -------------------------------------------------------
    def plan_de_salle(self, origine, destination, jour, depart, numero=None):
        """Ouvre le plan du train choisi (1re classe) et renvoie les données du plan.
        Ne clique jamais sur « Continuer » : rien n'est ajouté au panier."""
        heure = int(depart[:2]) if depart[:2].isdigit() else 6
        self.rechercher(origine, destination, jour, [{"age": 35, "carte": ""}], 0, heure=heure)
        for _ in range(8):
            titres = self.page.get_by_role("heading", name=re.compile(r"Départ de .* {} à destination".format(re.escape(depart))))
            for i in range(titres.count()):
                carte = titres.nth(i).locator("xpath=..")
                carte.scroll_into_view_if_needed()
                carte.click()
                dlg = self._dialogue()
                try:
                    dlg.wait_for(timeout=8000)
                except PWTimeout:
                    continue
                time.sleep(1)
                texte = dlg.inner_text()
                if numero and ("n° {}".format(numero) not in texte):
                    self.fermer_dialogues()
                    continue
                return self._ouvrir_plan(dlg)
            bouton = self.page.get_by_role("button", name="Afficher les trajets suivants")
            if bouton.count() == 0:
                break
            self._cliquer(bouton.first, est_suivants)
        raise FormulaireImpossible("Train de {} introuvable ce jour-là.".format(depart))

    def _ouvrir_plan(self, dlg):
        libelle = dlg.get_by_text(re.compile(r"^1re classe : "))
        if libelle.count() == 0:
            self.fermer_dialogues()
            raise FormulaireImpossible("Pas d'offre en 1re classe sur ce train.")
        bloc = libelle.first.locator(
            "xpath=ancestor::*[.//button[starts-with(normalize-space(.), 'Choisir cet aller')]][1]")
        bloc.get_by_role("button", name=re.compile(r"^Choisir cet aller")).first.click()
        choisir = self.page.get_by_role("button", name="Choisir votre place")
        try:
            choisir.first.wait_for(timeout=10000)
        except PWTimeout:
            self.fermer_dialogues()
            raise FormulaireImpossible("Le choix de place sur plan n'est pas proposé pour ce train.")
        if self.garde:
            self.garde.verifier_disponible()
            self.garde.avant_requete()
        try:
            with self.page.expect_response(lambda r: "/seatmap" in r.url, timeout=30000) as info:
                choisir.first.click()
        except PWTimeout:
            if self.garde:
                self.garde.erreur_reseau("délai dépassé sur le plan de salle")
            raise Bloque("Pas de réponse de SNCF Connect pour le plan de salle.")
        rep = info.value
        brut = self._lire_reponse(rep)
        time.sleep(1)
        self.fermer_dialogues()
        donnees = brut.get("seatMapData")
        return json.loads(donnees) if isinstance(donnees, str) else (donnees or brut)


def jours_entre(debut, fin):
    j = debut
    while j <= fin:
        yield j
        j += timedelta(days=1)


def maintenant_paris():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:
        return datetime.now()
