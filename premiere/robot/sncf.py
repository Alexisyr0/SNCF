"""Pilotage de SNCF Connect dans une vraie fenêtre Chrome, comme le ferait une personne :
remplir le formulaire, faire défiler les trains, passer au jour suivant, ouvrir un plan de salle.
Le robot lit uniquement les réponses que le site charge lui-même pour s'afficher."""

import json
import re
import time
import unicodedata
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
    if rep.status in (403, 429):
        raise Bloque("SNCF Connect a refusé la demande ({}).".format(rep.status))
    if rep.status != 200:
        return None
    try:
        return rep.json()
    except Exception:
        return None


class SNCF:
    def __init__(self, page, pause=5.0, journal=print):
        self.page = page
        self.pause = pause
        self.journal = journal

    # --- petites aides -------------------------------------------------------
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
            cible = lignes[0][0]
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
        for h in (heure, 4, 6):
            radio = self.page.get_by_role("radio", name=re.compile(r"^{:02d}h".format(h)))
            if radio.count():
                radio.first.click()
                break
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
        self.page.goto(URL_FORMULAIRE, wait_until="domcontentloaded")
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
        bouton = self.page.get_by_role("button", name="Voir les prix")
        with self.page.expect_response(est_recherche, timeout=60000) as info:
            bouton.click()
        return jour, self._derniere_recherche(info.value)

    def _derniere_recherche(self, rep):
        data = _lire(rep)
        while True:  # SNCF Connect relance parfois la recherche juste après : on garde la dernière
            try:
                rep = self.page.wait_for_event("response", predicate=est_recherche, timeout=6000)
                d = _lire(rep)
                if d is not None:
                    data = d
            except PWTimeout:
                break
        if data is None:
            raise Bloque("SNCF Connect n'a pas renvoyé de résultats.")
        return data

    def attendre_recherche_manuelle(self, delai_min=15):
        """Mode assisté : on attend que tu lances la recherche toi-même dans la fenêtre."""
        fin = time.time() + delai_min * 60
        while time.time() < fin:
            try:
                rep = self.page.wait_for_event("response", predicate=est_recherche, timeout=30000)
            except PWTimeout:
                continue
            try:
                return self._derniere_recherche(rep)
            except Bloque:
                continue
        raise Bloque("Personne n'a relancé la recherche dans la fenêtre.")

    # --- parcours des jours --------------------------------------------------
    def _cliquer(self, bouton, predicat):
        self._attendre()
        try:
            with self.page.expect_response(predicat, timeout=45000) as info:
                bouton.click(timeout=15000)
        except PWTimeout:
            raise Bloque("Pas de réponse de SNCF Connect (vérification affichée ?).")
        d = _lire(info.value)
        if d is None:
            raise Bloque("Réponse illisible de SNCF Connect.")
        return d

    def suivants_du_jour(self, data):
        """Fait défiler « Afficher les trajets suivants » ; renvoie toutes les réponses du jour."""
        reponses = [data]
        clics = 0
        while not journee_terminee(data) and clics < 15:
            bouton = self.page.get_by_role("button", name="Afficher les trajets suivants")
            if bouton.count() == 0:
                break
            data = self._cliquer(bouton.first, est_suivants)
            reponses.append(data)
            clics += 1
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
        with self.page.expect_response(lambda r: "/seatmap" in r.url, timeout=30000) as info:
            choisir.first.click()
        rep = info.value
        if rep.status != 200:
            raise Bloque("Plan de salle refusé ({}).".format(rep.status))
        brut = rep.json()
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
