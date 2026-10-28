"""Check that runobs loads the FBP motion plan with the GUI Deploy angle convention."""
import ast
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

import Lib.mkmessage as mkmsg

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'script' / 'scriptcli.py'
SCIOBS = ROOT / 'SCIOBS' / 'sciobscli.py'


def parse(source):
    return ast.parse(source.read_text(encoding='utf-8'))


def runobs_loader():
    tree = parse(SCRIPT)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'load_obsplan_tile')
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {'re': re}
    exec(compile(module, str(SCRIPT), 'exec'), namespace)
    return namespace['load_obsplan_tile']


def sciobs_class():
    """sciobscli with only loadtile and load_motion (no AMQ or astropy imports)."""
    tree = parse(SCIOBS)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == 'sciobscli')
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef)
               and node.name in ('loadtile', 'load_motion')]
    module = ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
        name='Sciobs', bases=[], keywords=[], body=methods, decorator_list=[],
    )], type_ignores=[]))
    namespace = {'json': json, 'os': os, 'np': np, 'mkmsg': mkmsg}
    exec(compile(module, str(SCIOBS), 'exec'), namespace)
    return namespace['Sciobs']


class RunobsMotionTests(unittest.TestCase):
    def setUp(self):
        # load_motion reads ./Lib/KSPEC.ini (alpha 30, beta 150).
        cwd = os.getcwd()
        os.chdir(ROOT)
        self.addCleanup(os.chdir, cwd)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        directory = Path(self.directory.name)
        # Geometric path starting at the power-on pose (30, 150).
        (directory / 'ASPECS_2627_0005.path.txt').write_text(
            'F001_a, F001_b, F002_a, F002_b\n'
            '30.0, 150.0, 30.0, 150.0\n'
            '40.0, 120.0, 25.0, 160.0\n')

        self.sciobs = sciobs_class()()
        self.sciobs.project = 'ASPECS'
        self.sciobs.obsdate = '20260601'
        self.sciobs.filename = None
        self.sciobs.ra = self.sciobs.dec = None
        self.sciobs.motionpath = str(directory)
        self.sciobs.obsinfofile = str(directory / 'obs_info.json')
        self.sciobs.load_tilepos = Mock(return_value='tile')
        self.sciobs.load_target = Mock(return_value='objects')
        self.load_obsplan_tile = runobs_loader()

    def test_motion_starts_at_command_zero(self):
        _, _, alpha_msg, beta_msg = self.load_obsplan_tile(
            self.sciobs, 'ASPECS_obs_20260601.txt', '0005')
        alpha = json.loads(alpha_msg)
        beta = json.loads(beta_msg)
        self.assertEqual((alpha['arm'], beta['arm']), ('alpha', 'beta'))
        self.assertEqual(alpha['step'], [1, 2])
        for fiber in ('F001', 'F002'):
            self.assertEqual((alpha[fiber][0], beta[fiber][0]), (0.0, 0.0))
        # command = -geometric + offset
        self.assertEqual(alpha['F001'], [0.0, -10.0])
        self.assertEqual(beta['F001'], [0.0, 30.0])
        self.assertEqual(alpha['F002'], [0.0, 5.0])
        self.assertEqual(beta['F002'], [0.0, -10.0])

    def test_zenith_override_only_for_calibration_plan(self):
        self.load_obsplan_tile(self.sciobs, 'ASPECS_obs_20260601.txt', '0005')
        self.sciobs.load_target.assert_called_with(zenith_angle_override=None)
        self.load_obsplan_tile(self.sciobs, 'Calib_obsplan_20260601.txt', '0005')
        self.sciobs.load_target.assert_called_with(zenith_angle_override=0.0)

    def test_handle_obs_loads_tile_through_runobs_loader(self):
        tree = parse(SCRIPT)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == 'script')
        handle_obs = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef)
                          and node.name == 'handle_obs')
        calls = [node.func for node in ast.walk(handle_obs) if isinstance(node, ast.Call)]
        self.assertIn('load_obsplan_tile',
                      [func.id for func in calls if isinstance(func, ast.Name)])
        self.assertNotIn('loadtile',
                         [func.attr for func in calls if isinstance(func, ast.Attribute)])


if __name__ == '__main__':
    unittest.main()
