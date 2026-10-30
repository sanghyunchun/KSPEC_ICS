"""Check that runobs loads the FBP motion plan with the GUI Deploy angle convention,
and that the CLI runobs path (KSPECRUN.py) runs through to the FBP motion plan."""
import ast
import asyncio
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import astropy.units as u
import numpy as np
from astropy.coordinates import Angle

import Lib.mkmessage as mkmsg

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'script' / 'scriptcli.py'
SCIOBS = ROOT / 'SCIOBS' / 'sciobscli.py'
KSPECRUN = ROOT / 'KSPECRUN.py'


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


def script_class(namespace):
    """script with the runobs methods and the module helpers they call."""
    tree = parse(SCRIPT)
    helpers = [node for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name in ('printing', 'clear_queue', 'load_obsplan_tile',
                                 'convert_to_sexagesimal')]
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == 'script')
    methods = [node for node in cls.body if isinstance(node, ast.AsyncFunctionDef)
               and node.name in ('run_obs', 'select_obsplan_tile', 'handle_obs')]
    module = ast.fix_missing_locations(ast.Module(body=helpers + [ast.ClassDef(
        name='Script', bases=[], keywords=[], body=methods, decorator_list=[],
    )], type_ignores=[]))
    exec(compile(module, str(SCRIPT), 'exec'), namespace)
    return namespace['Script']


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


class FakeClient:
    def __init__(self, response_queue):
        self.response_queue = response_queue
        self.sent = []

    async def send_message(self, inst, message):
        self.sent.append((inst, json.loads(message)))
        await self.response_queue.put({'inst': inst, 'process': 'Done'})


class RunobsCliTests(unittest.IsolatedAsyncioTestCase):
    """KSPECRUN.py runs `runobs` with logging=None: plan and tile are asked on stdin."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        # ./Lib/KSPEC.ini as in the repo, with the plan and motion files in the temp dir.
        kspecinfo = json.loads((ROOT / 'Lib' / 'KSPEC.ini').read_text(encoding='utf-8'))
        kspecinfo['SCIOBS']['obsplanpath'] = str(root) + '/'
        (root / 'Lib').mkdir()
        (root / 'Lib' / 'KSPEC.ini').write_text(json.dumps(kspecinfo))
        (root / 'ASPECS_obs_20260601.txt').write_text(
            'TileID ExpT ObsNum\n'
            '0005 900 3\n')
        (root / 'ASPECS_2627_0005.path.txt').write_text(
            'F001_a, F001_b\n'
            '30.0, 150.0\n'
            '40.0, 120.0\n')
        cwd = os.getcwd()
        os.chdir(root)
        self.addCleanup(os.chdir, cwd)

        class CliSciobs(sciobs_class()):
            def __init__(self):
                self.filename = None
                self.ra = self.dec = None
                self.motionpath = str(root)
                self.obsinfofile = str(root / 'obs_info.json')

            def load_tilepos(self):
                self.ra, self.dec = 270.872801, 10.806923
                return json.dumps({'func': 'loadtile', 'tid': int(self.tile_id),
                                   'ra': self.ra, 'dec': self.dec})

            def load_target(self, zenith_angle_override=None):
                return json.dumps({'func': 'loadobj', 'zenith_angle': zenith_angle_override})

        self.sleep = AsyncMock()
        redis = SimpleNamespace(Redis=lambda **kwargs: SimpleNamespace(get=lambda key: '0000'))
        namespace = {
            'asyncio': SimpleNamespace(sleep=self.sleep, create_task=asyncio.create_task,
                                       get_running_loop=asyncio.get_running_loop),
            'json': json, 'os': os, 'np': np, 're': re, 'Angle': Angle, 'u': u,
            'redis': redis, 'sciobscli': CliSciobs,
        }
        self.obs = script_class(namespace)()
        self.obs.TileID = self.obs.ra = self.obs.dec = None
        self.obs.project = self.obs.obsdate = None

        response_queue = asyncio.Queue()
        self.client = FakeClient(response_queue)
        self.scriptrun = SimpleNamespace(
            ICSclient=self.client, send_udp_message=AsyncMock(),
            response_queue=response_queue, GFA_response_queue=asyncio.Queue(),
            ADC_response_queue=asyncio.Queue(), SPEC_response_queue=asyncio.Queue(),
        )

    async def test_runobs_cli_loads_tile_and_slews(self):
        with patch('builtins.input', side_effect=['ASPECS_obs_20260601.txt', ' 0005 ']) as ask:
            await self.obs.run_obs(self.scriptrun, None)
            # Both prompts are answered before run_obs returns to the KSPECRUN.py prompt.
            self.assertEqual(ask.call_count, 2)
            self.assertEqual(self.client.sent, [])
            await self.obs.script_task

        self.assertEqual((self.obs.project, self.obs.obsdate, self.obs.TileID),
                         ('ASPECS', '20260601', '0005'))
        self.assertEqual([(inst, message['func']) for inst, message in self.client.sent],
                         [('MTL', 'loadobj'), ('FBP', 'loadobj'),
                          ('FBP', 'loadmotion'), ('FBP', 'loadmotion')])
        alpha, beta = self.client.sent[2][1], self.client.sent[3][1]
        self.assertEqual((alpha['arm'], beta['arm']), ('alpha', 'beta'))
        self.assertEqual((alpha['F001'], beta['F001']), ([0.0, -10.0], [0.0, 30.0]))
        self.scriptrun.send_udp_message.assert_awaited_once_with(
            'KSPEC>TC tmradec 18:03:29.47 +10:48:24.92')


class KspecrunScriptWiringTests(unittest.TestCase):
    def test_runner_gives_scriptrun_its_queues_and_senders(self):
        tree = parse(KSPECRUN)
        runner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == 'KSPECRunner')
        init = next(node for node in runner.body if isinstance(node, ast.FunctionDef)
                    and node.name == '__init__')
        call = next(node for node in ast.walk(init) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'initialize_dependencies')
        self.assertEqual(ast.unparse(call.func.value), 'self.scriptrun')
        self.assertEqual([ast.unparse(arg) for arg in call.args], [
            'ICS_client', 'self.send_udp_message', 'self.send_telcom_command',
            'self.response_queue', 'self.GFA_response_queue', 'self.ADC_response_queue',
            'self.SPEC_response_queue',
        ])


if __name__ == '__main__':
    unittest.main()
