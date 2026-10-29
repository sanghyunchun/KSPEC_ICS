"""Tile Deploy accepts both dot and underscore input file names."""
import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


def loader_class():
    source = Path(__file__).resolve().parents[1] / 'SCIOBS' / 'sciobscli.py'
    tree = ast.parse(source.read_text())
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == '_tile_data_file')
    original = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name == 'sciobscli')
    methods = [node for node in original.body
               if isinstance(node, ast.FunctionDef)
               and node.name in ('load_tilepos', 'load_target', 'load_motion', 'loadtile')]
    cls = ast.ClassDef(name='Loader', bases=[], keywords=[], body=methods,
                       decorator_list=[])
    namespace = {'os': os, 'json': json, 'np': np,
                 'mkmsg': SimpleNamespace(fbpmsg=lambda: {'inst': 'FBP'})}
    module = ast.fix_missing_locations(ast.Module(body=[helper, cls], type_ignores=[]))
    exec(compile(module, str(source), 'exec'), namespace)
    return namespace['Loader']


class TileFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.loader = loader_class()()
        self.loader.targetpath = str(self.root)
        self.loader.motionpath = str(self.root)
        self.loader.obsinfofile = str(self.root / 'obs_info.json')
        self.loader.project = 'PROJECT'
        self.loader.filename = 'PROJECT_obsplan.txt'
        self.loader.obsdate = '20261029'

    def write_set(self, assign_separator, path_separator=None, tile=9111):
        path_separator = assign_separator if path_separator is None else path_separator
        (self.root / 'PROJECT_2627.info.txt').write_text(f'{tile} 14.5 0.0\n')
        (self.root / f'PROJECT_2627{assign_separator}{tile}.assign.txt').write_text(
            'E1 1.0 2.0 19.0 SCIENCE 0 14.5 0.0\n'
        )
        (self.root / f'PROJECT_2627{path_separator}{tile}.path.txt').write_text(
            'E1_a,E1_b\n10.0,20.0\n'
        )

    def assert_loaded(self):
        _, objmsg, alpha, beta = self.loader.loadtile('9111', zenith_angle_override=0.0)
        self.assertEqual(json.loads(objmsg)['xp'], [1.0])
        self.assertEqual(json.loads(alpha)['E1'], [40.0])
        self.assertEqual(json.loads(beta)['E1'], [170.0])

    def test_2627_dot_names(self):
        self.write_set('.')
        self.assert_loaded()

    def test_2627_underscore_names(self):
        self.write_set('_')
        self.assert_loaded()

    def test_assign_and_path_can_use_different_separators(self):
        self.write_set('.', '_')
        self.assert_loaded()

    def test_duplicate_assign_names_are_rejected_as_ambiguous(self):
        self.write_set('.')
        (self.root / 'PROJECT_2627_9111.assign.txt').write_text(
            'E1 1.0 2.0 19.0 SCIENCE 0 14.5 0.0\n'
        )
        with self.assertRaisesRegex(ValueError, 'Ambiguous assign files'):
            self.loader.loadtile('9111', zenith_angle_override=0.0)


if __name__ == '__main__':
    unittest.main()
