"""fbpoffset must not move when an unlocked axis would jump far from its current position."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules.setdefault('pyads', MagicMock())    # PLC library; only read_by_name of the fake PLC is used
sys.modules.setdefault('aio_pika', MagicMock())  # RabbitMQ client, imported by FBP.command / fbpcli

from FBP.kspec_positioner_controller import position_action  # noqa: E402

core = position_action._core


class FakePLC:
    def __init__(self, positions, locked=()):
        self.positions = positions          # local axis -> ActPos
        self.locked = set(locked)

    def read_by_name(self, name, plc_type=None):
        local_axis = int(name.split('[')[1].split(']')[0])
        if name.startswith('GVL.gAxisLocked'):
            return local_axis in self.locked
        if name.endswith('.ActPos'):
            return self.positions[local_axis]
        raise KeyError(name)


class OffsetGuardTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.map = core.POSITIONER_AXIS_MAP
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.saved = patch.object(core, 'save_result_json').start()
        self.main = patch.object(position_action._kspec_main, 'main',
                                 AsyncMock(return_value={'status': 'success'})).start()
        self.addCleanup(patch.stopall)

    def plcs(self, actual, locked=()):
        """actual: {(positioner, motor): ActPos}; other axes at 0."""
        positions = {'PLC1': {}, 'PLC2': {}}
        locks = {'PLC1': set(), 'PLC2': set()}
        for positioner, info in self.map.items():
            for motor in ('alpha', 'beta'):
                local_axis = info[motor]['local_axis']
                positions[info['plc']][local_axis] = actual.get((positioner, motor), 0.)
                if positioner in locked:
                    locks[info['plc']].add(local_axis)
        return {name: FakePLC(positions[name], locks[name]) for name in positions}

    def offset_files(self, targets):
        """targets: {(positioner, motor): angle}; other axes 0."""
        paths = []
        for motor in ('alpha', 'beta'):
            data = {p: targets.get((p, motor), 0.) for p in self.map}
            path = Path(self.directory.name) / f'{motor}.offset.json'
            path.write_text(json.dumps(data))
            paths.append(str(path))
        return paths

    async def test_alpha_wrapped_by_360_is_refused(self):
        positioner = next(iter(self.map))
        alpha_file, beta_file = self.offset_files({(positioner, 'alpha'): 140.})
        plcs = self.plcs({(positioner, 'alpha'): -220.})

        result = await position_action._rotate_offset_checked(plcs, alpha_file, beta_file, 45.)

        self.assertEqual(result['status'], 'fail')
        self.main.assert_not_awaited()
        [jump] = result['data']['jump_axes']
        self.assertEqual((jump['positioner'], jump['motor']), (positioner, 'alpha'))
        self.assertAlmostEqual(jump['jump'], 360.)
        self.saved.assert_called_once()

    async def test_small_offsets_move(self):
        positioner = next(iter(self.map))
        alpha_file, beta_file = self.offset_files({(positioner, 'alpha'): -218.5,
                                                   (positioner, 'beta'): 12.})
        plcs = self.plcs({(positioner, 'alpha'): -220., (positioner, 'beta'): 10.})

        result = await position_action._rotate_offset_checked(plcs, alpha_file, beta_file, 45.)

        self.assertEqual(result['status'], 'success')
        self.main.assert_awaited_once_with(plcs, alpha_file=alpha_file, beta_file=beta_file,
                                           offset_mode=True)

    async def test_locked_axis_is_not_checked(self):
        positioner = next(iter(self.map))
        alpha_file, beta_file = self.offset_files({(positioner, 'alpha'): 140.})
        plcs = self.plcs({(positioner, 'alpha'): -220.}, locked={positioner})

        result = await position_action._rotate_offset_checked(plcs, alpha_file, beta_file, 45.)

        self.assertEqual(result['status'], 'success')
        self.main.assert_awaited_once()

    async def test_null_axis_is_held_at_its_position(self):
        """MTL sends NaN (null) for fibres it did not measure: FBP keeps them where they are."""
        held, other = list(self.map)[:2]
        alpha_file, beta_file = self.offset_files({(held, 'alpha'): None, (held, 'beta'): None,
                                                   (other, 'alpha'): 3.})
        # the held axis stands 350 deg from what a stale command would ask: it must not count
        plcs = self.plcs({(held, 'alpha'): -328.5, (held, 'beta'): 120., (other, 'alpha'): 1.})

        result = await position_action._rotate_offset_checked(plcs, alpha_file, beta_file, 45.)

        self.assertEqual(result['status'], 'success')
        self.main.assert_awaited_once()
        alpha = json.loads(Path(alpha_file).read_text())
        beta = json.loads(Path(beta_file).read_text())
        self.assertEqual((alpha[held], beta[held]), (-328.5, 120.))   # target = ActPos: no motion
        self.assertEqual(alpha[other], 3.)
        self.assertEqual({(h['positioner'], h['motor']) for h in result['data']['held_axes']},
                         {(held, 'alpha'), (held, 'beta')})
        self.assertIn(held, result['message'])


class OffsetMessageTest(unittest.TestCase):
    def test_nan_in_the_mtl_json_becomes_null(self):
        from FBP.fbpcli import fbp_offset

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '9162_MetrologyTrial_1.json'
            path.write_text('{"C4_a": NaN, "C4_b": NaN, "C5_a": -12.5, "C5_b": 40.0}')
            message = json.loads(fbp_offset(str(path)))     # standard JSON on the wire
        self.assertEqual(message['offsets'], {'C4_a': None, 'C4_b': None, 'C5_a': -12.5, 'C5_b': 40.0})

    def test_saveoffset_keeps_null(self):
        from FBP import command

        positioners = list(core.POSITIONER_AXIS_MAP)
        offsets = {f'{p}_{m}': 1.0 for p in positioners for m in ('a', 'b')}
        offsets[f'{positioners[0]}_a'] = None
        with tempfile.TemporaryDirectory() as tmp,              patch.object(command, 'load_config', return_value={'FBP': {'fbpfilepath': tmp}}):
            status, _, alpha_file, _ = command.saveoffset({'offsets': offsets, 'source_name': 't.json'})
            self.assertEqual(status, 'success')
            self.assertIsNone(json.loads(Path(alpha_file).read_text())[positioners[0]])


if __name__ == '__main__':
    unittest.main()
