"""Lecture des réponses SNCF Connect : prix, trains, et empreintes de voitures."""

import hashlib
import json
import re

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


def prix(label):
    """Convertit un prix français ou international en float sans perdre les décimales."""
    if label is None:
        return None
    s = re.sub(r"[^0-9,.-]", "", str(label)).strip()
    if not s:
        return None
    # Si virgule et point coexistent, le dernier séparateur est le séparateur décimal.
    if "," in s and "." in s:
        decimal = "," if s.rfind(",") > s.rfind(".") else "."
        milliers = "." if decimal == "," else ","
        s = s.replace(milliers, "").replace(decimal, ".")
    elif "," in s:
        # Format français : 1 234,56
        s = s.replace(".", "").replace(",", ".")
    else:
        # Le point est conservé comme séparateur décimal.
        # Les espaces et séparateurs de milliers ont déjà été retirés.
        pass
    try:
        valeur = float(s)
        return valeur if valeur >= 0 else None
    except ValueError:
        return None


def propositions(data):
    ld = (data or {}).get("longDistance") or {}
    return ((ld.get("proposals") or {}).get("proposals")) or []


def journee_terminee(data):
    ld = (data or {}).get("longDistance") or {}
    pag = (ld.get("proposals") or {}).get("pagination") or {}
    suivant = pag.get("next")
    return (not suivant) or bool(suivant.get("changeDay"))


def _numero(texte):
    return re.sub(r"[^\dA-Za-z]", "", (texte or "").replace("n°", "")).strip()


def _ville(gare):
    """'Paris - Montparnasse - Hall 1 & 2' -> 'Paris' ; 'Lyon Part Dieu' -> 'Lyon Part Dieu'."""
    return (gare or "").split(" - ")[0].strip()


def troncons(p):
    """Les trains d'une proposition, d'après la frise détaillée."""
    out = []
    for step in ((p.get("globalTimeline") or {}).get("steps")) or []:
        t = step.get("train")
        if not t:
            continue
        tr = t.get("transporter") or {}
        out.append({
            "num": _numero(tr.get("number") or tr.get("referenceLabel")),
            "type": tr.get("description", ""),
            "de": (t.get("departure") or {}).get("stationLabel", ""),
            "a": (t.get("arrival") or {}).get("stationLabel", ""),
            "dep": (t.get("departure") or {}).get("timeLabel", ""),
            "arr": (t.get("arrival") or {}).get("timeLabel", ""),
            "services": [s.get("code") for s in (t.get("onBoardServices") or []) if s.get("code")],
        })
    return out


def _via(legs):
    """Gares de correspondance, avec le changement de gare s'il y en a un."""
    etapes = []
    for a, b in zip(legs, legs[1:]):
        if a["a"] and b["de"] and a["a"] != b["de"]:
            etapes.append("{} → {}".format(a["a"], b["de"]))
        elif a["a"]:
            etapes.append(a["a"])
    return " · ".join(etapes)


def extraire_trajets(data, classe="1re", inoui_seul=True):
    """Pour chaque train proposé : l'offre la moins chère qui respecte la classe sur
    TOUS les tronçons et, si demandé, uniquement des TGV INOUI."""
    cle = "firstComfortClassOffers" if classe == "1re" else "secondComfortClassOffers"
    trajets = []
    for p in propositions(data):
        if not (p.get("status") or {}).get("isBookable", True):
            continue
        legs = troncons(p)
        meilleur = None
        for o in ((p.get(cle) or {}).get("offers")) or []:
            fares = o.get("travelersFares") or []
            voyageurs = [f for f in fares if f.get("travelerIcon") != "PET"]
            animaux = [f for f in fares if f.get("travelerIcon") == "PET"]
            segments = [s for f in voyageurs for s in (f.get("segmentFares") or [])]
            if not voyageurs or not segments:
                continue
            if any(s.get("comfort") != classe for s in segments):
                continue
            if inoui_seul and any(s.get("transporterName") != "TGV INOUI" for s in segments):
                continue
            prix_voyageurs = [prix(f.get("priceLabel")) for f in voyageurs]
            total = prix(o.get("priceLabel")) if None in prix_voyageurs else sum(prix_voyageurs)
            if total is None:
                continue
            segs0 = voyageurs[0].get("segmentFares") or []
            chien, chien_estime = 0.0, False
            for a in animaux:
                pa = prix(a.get("priceLabel"))
                if pa is None:  # pas toujours affiché avant paiement : 10 € par train (tarif 2026)
                    pa, chien_estime = 10.0 * len(segs0), True
                chien += pa
            placements = ((o.get("segmentPlacements") or {}).get("segments")) or []
            tarifs = []
            details = []
            for i, s in enumerate(segs0):
                if s.get("fareName") and s["fareName"] not in tarifs:
                    tarifs.append(s["fareName"])
                leg = dict(legs[i]) if i < len(legs) else {
                    "num": _numero(s.get("transporterDescription")), "type": s.get("transporterName", ""),
                    "de": "", "a": "", "dep": "", "arr": "", "services": []}
                leg["classe"] = s.get("comfort")
                leg["tarif"] = s.get("fareName")
                leg["prix"] = prix(s.get("price"))
                if i < len(placements):
                    leg["choix_place"] = placements[i].get("defaultPlacement") == "FRONT_SEAT_MAP"
                details.append(leg)
            cand = {
                "jour": (p.get("travelId") or "")[:10],
                "depart": (p.get("departure") or {}).get("timeLabel", ""),
                "arrivee": (p.get("arrival") or {}).get("timeLabel", ""),
                "duree": p.get("durationLabel", ""),
                "correspondances": p.get("transporterDescription", ""),
                "trains": " → ".join("{} {}".format(l["type"], l["num"]).strip() for l in details),
                "tarif": " + ".join(tarifs),
                "conditions": o.get("title", ""),
                "via": _via(details),
                "numeros": [l["num"] for l in details if l.get("num")],
                "legs": details,
                "prix": round(total, 2),
                "chien": round(chien, 2),
                "chien_estime": chien_estime,
                "total": round(total + chien, 2),
                "cle": p.get("travelId", ""),
            }
            if meilleur is None or cand["total"] < meilleur["total"]:
                meilleur = cand
        if meilleur and meilleur["jour"]:
            trajets.append(meilleur)
    return trajets


def passe_par_paris(t):
    return (not t.get("via")) or ("Paris" in t["via"])


# --------------------------------------------------------------------------
# Empreintes de voitures (plan de salle)
# --------------------------------------------------------------------------

def _code_case(c, retourne):
    t = c.get("type", "")
    o = c.get("orientationAngle", "")
    if retourne:
        o = {"EAST": "WEST", "WEST": "EAST", "NORTH": "SOUTH", "SOUTH": "NORTH"}.get(o, o)
    if t == "SEAT":
        s = c.get("seat") or {}
        return "S:{}:{}:{}".format(s.get("type", "?"), s.get("position", "?"), o)
    if t == "TABLE":
        return "TABLE"
    return t


def _plan_canonique(deck):
    """Le plan d'une salle, identique quel que soit le sens d'affichage de la voiture
    (SNCF ne donne pas le sens de marche : on compare le plan et son demi-tour)."""
    grille = deck.get("deckGrid") or {}
    cols, rows = grille.get("columnSize", 0), grille.get("rowSize", 0)
    cases = grille.get("deckCells") or []

    def rendu(retourne):
        items = []
        for c in cases:
            col, row = c.get("columnRank", 0), c.get("rowRank", 0)
            w, h = c.get("columnStretch", 1), c.get("rowStretch", 1)
            if retourne:
                col, row = cols - col - w, rows - row - h
            items.append((col, row, w, h, _code_case(c, retourne)))
        items.sort()
        return "{}x{}|".format(cols, rows) + ";".join("{},{},{},{},{}".format(*i) for i in items)

    return min(rendu(False), rendu(True))


def _resume_salle(deck):
    cases = (deck.get("deckGrid") or {}).get("deckCells") or []
    sieges = [c for c in cases if c.get("type") == "SEAT" and c.get("seat")]
    est = sum(1 for c in sieges if c.get("orientationAngle") == "EAST")
    ouest = sum(1 for c in sieges if c.get("orientationAngle") == "WEST")
    return {
        "salle": {"BOTTOM": "basse", "TOP": "haute"}.get(deck.get("deckType"), "unique"),
        "sieges": len(sieges),
        "tablettes": sum(1 for c in sieges if (c["seat"].get("type") == "SHELF")),
        "pmr": sum(1 for c in sieges if (c["seat"].get("type") == "WHEELCHAIR")),
        "tables": sum(1 for c in cases if c.get("type") == "TABLE"),
        "sens_majoritaire": max(est, ouest),
        "sens_minoritaire": min(est, ouest),
        "isolees": sum(1 for c in sieges if c["seat"].get("position") == "WINDOW"
                       and not any(o is not c and o.get("type") == "SEAT"
                                   and o.get("columnRank") == c.get("columnRank")
                                   and abs(o.get("rowRank", 0) - c.get("rowRank", 0)) == 1 for o in sieges)),
        "elements": sorted({c.get("type") for c in cases} - {"SEAT", "HALLWAY", "EMPTY_AREA"}),
    }


def _plan_compact(deck):
    """Plan réduit pour le dessiner dans l'app."""
    g = deck.get("deckGrid") or {}
    cases = []
    for c in g.get("deckCells") or []:
        t = c.get("type")
        if t in ("HALLWAY", "EMPTY_AREA"):
            continue
        code = {"SEAT": "S", "TABLE": "T", "LUGGAGE_RACK": "L", "STAIRS": "E", "WC": "W"}.get(t, "X")
        extra = ""
        if t == "SEAT":
            s = c.get("seat") or {}
            extra = {"SHELF": "t", "WHEELCHAIR": "p"}.get(s.get("type"), "") + (c.get("orientationAngle", "E")[:1])
        cases.append([c.get("columnRank", 0), c.get("rowRank", 0), c.get("columnStretch", 1),
                      c.get("rowStretch", 1), code + extra])
    return {"salle": {"BOTTOM": "basse", "TOP": "haute"}.get(deck.get("deckType"), "unique"),
            "cols": g.get("columnSize", 0), "rows": g.get("rowSize", 0), "cases": cases}


def empreintes(seatmap):
    """Liste des voitures d'un plan de salle avec leur empreinte."""
    if isinstance(seatmap, str):
        seatmap = json.loads(seatmap)
    if "seatMapData" in seatmap:
        seatmap = json.loads(seatmap["seatMapData"]) if isinstance(seatmap["seatMapData"], str) else seatmap["seatMapData"]
    voitures = []
    for car in seatmap.get("carriages") or []:
        for co in car.get("coaches") or []:
            decks = sorted(co.get("decks") or [], key=lambda d: d.get("deckType", ""))
            if not decks:
                continue
            classe = "1re" if str(co.get("travelClass")) == "1" else "2de"
            base = "{}|{}|".format(co.get("@type", ""), classe) + "/".join(
                "{}:{}".format(d.get("deckType", ""), _plan_canonique(d)) for d in decks)
            salles = [_resume_salle(d) for d in decks]
            voitures.append({
                "voiture": co.get("number"),
                "classe": classe,
                "signature": hashlib.sha1(base.encode()).hexdigest()[:10],
                "resume": {"type": co.get("@type"), "sieges": sum(s["sieges"] for s in salles),
                           "salles": salles},
                "plan": [_plan_compact(d) for d in decks],
            })
    return voitures
