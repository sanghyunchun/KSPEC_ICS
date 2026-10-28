"""fbpoffset must not move when an unlocked axis would jump far from its current position."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules.setdefault('pyads', MagicMock())    # PLC library; only read_by_name of the fake PLC is used

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


if __name__ == '__main__':
    unittest.main()
