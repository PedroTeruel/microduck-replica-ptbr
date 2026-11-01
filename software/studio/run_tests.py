"""Executa todos os testes: python3 -I run_tests.py (no computador, use py -3.13 -I run_tests.py). Usa apenas unittest da biblioteca padrão."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "deps"), HERE, os.path.join(HERE, "dev")]

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(os.path.join(HERE, "tests"), top_level_dir=HERE)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
