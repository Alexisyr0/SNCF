import unittest
from unittest.mock import Mock

import requests

from supa import Supabase


class FakeResponse:
    def __init__(self, payload, status=200, text="json"):
        self._payload = payload
        self.status_code = status
        self.text = text

    def json(self):
        return self._payload


class SupabaseTests(unittest.TestCase):
    def make_client(self):
        db = Supabase("https://example.supabase.co", "public-key", "a@example.com", "secret")
        db.jeton = "access"
        db.expire = 10**20
        return db

    def test_lire_tout_pagine(self):
        db = self.make_client()
        db.http.request = Mock(side_effect=[
            FakeResponse([{"id": 1}, {"id": 2}]),
            FakeResponse([{"id": 3}]),
        ])
        lignes = db.lire_tout("train_releves", taille=2, select="id")
        self.assertEqual([x["id"] for x in lignes], [1, 2, 3])
        appels = db.http.request.call_args_list
        self.assertEqual(appels[0].kwargs["headers"]["Range"], "0-1")
        self.assertEqual(appels[1].kwargs["headers"]["Range"], "2-3")

    def test_post_non_rejoue_apres_coupure(self):
        db = self.make_client()
        db.http.request = Mock(side_effect=requests.ConnectionError("coupure"))
        with self.assertRaises(requests.ConnectionError):
            db.ajouter("train_releves", [{"cle": "x"}], retour=False)
        self.assertEqual(db.http.request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
