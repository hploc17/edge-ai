"""Exercise CLI defaults without importing Jetson-only DeepStream modules."""
import argparse
import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch


class MeasureEnvironmentTests(unittest.TestCase):
    def parse(self, environment, argv=()):
        source = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')
        start = source.index('    auto_measure_default =')
        end = source.index('    args = parser.parse_args()', start)
        import textwrap
        namespace = {'os': os, 'parser': argparse.ArgumentParser()}
        with patch.dict(os.environ, environment, clear=True):
            exec(compile(ast.parse(textwrap.dedent(source[start:end])), '<measure-cli>', 'exec'), namespace)
            return namespace['parser'].parse_args(argv)

    def test_environment_and_explicit_disable(self):
        args = self.parse({'AUTO_MEASURE': '0', 'MEASURE_PERF': '1',
                           'MEASURE_WARMUP': '5', 'MEASURE_INTERVAL': '2.5',
                           'MEASURE_OUT': 'custom_results'})
        self.assertFalse(args.measure)
        self.assertEqual((args.measure_warmup, args.measure_interval, args.measure_out),
                         (5, 2.5, 'custom_results'))

    def test_cli_overrides_environment(self):
        args = self.parse({'AUTO_MEASURE': '0', 'MEASURE_WARMUP': '5'},
                          ['--measure', '--measure-warmup', '0'])
        self.assertTrue(args.measure)
        self.assertEqual(args.measure_warmup, 0)

    def test_legacy_fallback(self):
        self.assertFalse(self.parse({'MEASURE_PERF': '0'}).measure)
        self.assertTrue(self.parse({}).measure)
