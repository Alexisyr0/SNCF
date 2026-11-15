import unittest

from analyse import prix


class PrixTests(unittest.TestCase):
    def test_formats_francais(self):
        self.assertEqual(prix("120,70 €"), 120.70)
        self.assertEqual(prix("1 234,56 €"), 1234.56)
        self.assertEqual(prix("1.234,56 €"), 1234.56)

    def test_formats_point_decimal(self):
        self.assertEqual(prix("1234.56 EUR"), 1234.56)

    def test_valeurs_invalides(self):
        self.assertIsNone(prix(None))
        self.assertIsNone(prix("prix indisponible"))


if __name__ == "__main__":
    unittest.main()
