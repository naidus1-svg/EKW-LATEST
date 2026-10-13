#!/usr/bin/env python3
"""One command: run every test of the portable folder and print the counts. Works from any directory.

  python3 tests/run_tests.py
"""
import os
import sys
import unittest

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
sys.path.insert(0, os.path.dirname(H))
r = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(H, pattern='test_*.py'))
print('TESTS run=%d failures=%d errors=%d skipped=%d passed=%d' % (
    r.testsRun, len(r.failures), len(r.errors), len(r.skipped), r.testsRun - len(r.failures) - len(r.errors) - len(r.skipped)))
sys.exit(0 if r.wasSuccessful() else 1)
