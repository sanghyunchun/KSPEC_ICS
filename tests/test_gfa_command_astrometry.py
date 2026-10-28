"""GFA server: astrometry outputs are cleared so every solve uses fresh frames."""
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]

# GFA.command imports Lib.AMQ (aio_pika); the handlers under test do not use it.
sys.modules.setdefault('Lib.AMQ', types.ModuleType('Lib.AMQ'))
import GFA.command as command  # noqa: E402

KSPECINFO = json.loads((ROOT / 'Lib' / 'KSPEC.ini').read_text())
ASTRO_DIR = KSPECINFO['GFA']['final_astrometry_images']


def pointing_result(n):
    return {
        'status': 'success', 'message': 'Pointing completed.',
        'images': [f'astro_D20260124_T100007_4010365{i}_exp1s.fits' for i in range(n)],
        'crval1': [87.0 + 0.1 * i for i in range(n)],
        'crval2': [-46.0] * n,
    }


class CommandTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        os.chdir(ROOT)  # identify_execute reads ./Lib/KSPEC.ini
        self.server = Mock(send_message=AsyncMock())
        self.calls = Mock()
        patcher = patch.object(command, 'clear_astrometry_outputs',
                               self.calls.clear)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls.clear.return_value = 0
        command.guiding_task = None

    def tearDown(self):
        os.chdir(self._cwd)

    def replies(self):
        return [json.loads(c.args[1]) for c in self.server.send_message.call_args_list]


class PointingRetryTests(CommandTestCase):
    async def run_pointing(self, results):
        self.calls.attach_mock(AsyncMock(side_effect=results), 'pointing')
        actions = Mock(pointing=self.calls.pointing)
        cmd = json.dumps({'func': 'pointing', 'ExpTime': 5, 'ExpNum': 1,
                          'ra': '05:49:45.0', 'dec': '-46:00:00'})
        with patch.object(command, 'compute_boresight',
                          return_value=(87.44, -46.0, 'geometry',
                                        {'rms_arcsec': 1.5, 'used': ['a'] * 5})), \
             patch.object(command.asyncio, 'sleep', AsyncMock()):
            await command.identify_execute(self.server, actions, cmd)

    async def test_outputs_cleared_before_every_attempt(self):
        await self.run_pointing([pointing_result(2), pointing_result(2), pointing_result(3)])
        names = [c[0] for c in self.calls.mock_calls if c[0] in ('clear', 'pointing')]
        self.assertEqual(names, ['clear', 'pointing'] * 3)
        for c in self.calls.clear.call_args_list:
            self.assertEqual(c.args, (ASTRO_DIR,))
        final = self.replies()[-1]
        self.assertEqual(final['status'], 'success')
        self.assertEqual(final['bsmethod'], 'geometry')

    async def test_three_solved_cameras_are_enough(self):
        await self.run_pointing([pointing_result(3)])
        self.assertEqual([c[0] for c in self.calls.mock_calls if c[0] == 'pointing'], ['pointing'])
        self.assertEqual(self.replies()[-1]['status'], 'success')

    async def test_two_solved_cameras_fail_after_retries(self):
        await self.run_pointing([pointing_result(2)] * 3)
        final = self.replies()[-1]
        self.assertEqual(final['status'], 'fail')
        self.assertIn('less than 3', final['message'])

    async def test_valid_images_go_to_boresight(self):
        res = pointing_result(6)
        res['crval1'][2] = float('nan')
        with patch.object(command, 'compute_boresight',
                          return_value=(87.44, -46.0, 'geometry', {})) as cb, \
             patch.object(command.asyncio, 'sleep', AsyncMock()):
            actions = Mock(pointing=AsyncMock(return_value=res))
            cmd = json.dumps({'func': 'pointing', 'ExpTime': 5, 'ExpNum': 1,
                              'ra': '05:49:45.0', 'dec': '-46:00:00'})
            await command.identify_execute(self.server, actions, cmd)
        astro_dir, images, cr1, cr2, geometry_path = cb.call_args.args
        self.assertEqual(astro_dir, ASTRO_DIR)
        self.assertEqual(len(images), 5)
        self.assertNotIn(res['images'][2], images)
        self.assertEqual(len(cr1), 5)
        self.assertTrue(geometry_path.endswith(command.BORESIGHT_GEOMETRY_FILE))


class GuideStartTests(CommandTestCase):
    async def test_guide_start_clears_outputs_first(self):
        guiding = AsyncMock()
        with patch.object(command, 'handle_guiding', guiding):
            cmd = json.dumps({'func': 'gfaguide', 'ExpTime': 5, 'ExpNum': 1,
                              'save': False, 'ra': '05:49:45.0', 'dec': '-46:00:00'})
            await command.identify_execute(self.server, Mock(), cmd)
            await command.guiding_task
        self.calls.clear.assert_called_once_with(ASTRO_DIR)
        guiding.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
