import tempfile
import unittest
from pathlib import Path

from sncf import Bloque, Garde, _lire


class Reponse:
    def __init__(self, status=200, body=None):
        self.status = status
        self._body = body or '{"ok": true}'

    def text(self):
        return self._body

    def json(self):
        import json
        return json.loads(self._body)


class LectureReponseTests(unittest.TestCase):
    def test_json_valide(self):
        self.assertEqual(_lire(Reponse()), {"ok": True})

    def test_statut_refuse(self):
        with self.assertRaises(Bloque):
            _lire(Reponse(403, "forbidden"))

    def test_page_restriction_http_200(self):
        with self.assertRaises(Bloque):
            _lire(Reponse(200, '{"message":"Accès temporairement restreint"}'))


class GardeTests(unittest.TestCase):
    def test_quota_journalier_bloque_les_requetes_suivantes(self):
        with tempfile.TemporaryDirectory() as dossier:
            garde = Garde(pause=10, max_jour=1, chemin=Path(dossier) / "garde.json")
            garde.avant_requete()
            with self.assertRaises(Bloque):
                garde.avant_requete()

    def test_coupe_circuit_persiste_apres_rechargement(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "garde.json"
            garde = Garde(chemin=chemin)
            garde.bloquer("CAPTCHA détecté")
            rechargee = Garde(chemin=chemin)
            with self.assertRaises(Bloque):
                rechargee.avant_requete()

    def test_reinitialisation_leve_le_coupe_circuit(self):
        with tempfile.TemporaryDirectory() as dossier:
            garde = Garde(chemin=Path(dossier) / "garde.json")
            garde.bloquer("restriction")
            garde.reinitialiser()
            self.assertFalse(garde.etat["bloque"])


if __name__ == "__main__":
    unittest.main()
