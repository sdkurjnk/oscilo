import unittest

from oscilo import oscilo_engine
from oscilo.Domain import Domain


class TestDomainProtocol(unittest.TestCase):
    def test_domain_values_match_existing_protocol(self):
        expected = {
            "LOCAL": 0,
            "GLOBAL": 1,
            "ENCLOSING": 2,
            "BUILTIN": 3,
            "NOT_FOUND": -1,
        }

        for name, value in expected.items():
            with self.subTest(domain=name):
                self.assertEqual(getattr(oscilo_engine, name), value)
                self.assertEqual(getattr(Domain, name).value, value)


if __name__ == "__main__":
    unittest.main(verbosity=2)