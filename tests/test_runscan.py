"""runscan (script/scriptcli.py) and the star-scan helpers (script/starscan.py), with fakes only.

Run from the repository root: python -m unittest tests.test_runscan
"""
import asyncio
import io
import json
import math
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import script.scriptcli as cli
from script import starscan

ROOT = Path(__file__).resolve().parents[1]
POSITIONERS = starscan.axis_map_positioners()
SCANNED = ['C4', 'D2', 'H5']
MONITOR = 'J3'


class FakeClient:
    """Answers every message with a Done reply on the ICS response queue."""

    def __init__(self, response_queue, fail_fbpoffset_at=None, trial_json=None):
        self.response_queue = response_queue
        self.sent = []
        self.fail_fbpoffset_at = fail_fbpoffset_at
        self.trial_json = trial_json
        self.offsets = []           # the 'offsets' of every fbpoffset, in order

    async def send_message(self, queue, message):
        msg = json.loads(message)
        func = msg['func']
        self.sent.append((queue, func))
        inst = {'ISOPLANE': 'SPEC'}.get(queue, queue)     # servers reply as themselves
        reply = {'inst': inst, 'func': func, 'process': 'Done', 'status': 'success',
                 'message': f'{func} done'}
        if func == 'fbpoffset':
            self.offsets.append(msg['offsets'])
            if self.fail_fbpoffset_at == len(self.offsets):
                reply.update(status='fail', message='PLC error')
        elif func == 'loadmotion':
            reply['arm'] = msg['arm']
        elif func == 'mtltrial':
            reply.update(filename=self.trial_json, itrial=1, err_max=0.008, err_median=0.004,
                         converged=True, should_continue=False, offsetx=[0.0], offsety=[0.0])
        elif func == 'getobj':
            labels = SCANNED + [MONITOR]
            reply.update(filename=f'frame{len(self.offsets)}.fits', backend='ISOPLANE',
                         zoflux={'ok': True, 'nfib': 43,
                                 'fibres': {'label': labels,
                                            'flux': [1000.0 + i for i in range(len(labels))]}})
        await self.response_queue.put(reply)


def write_tile(root):
    """A ZOSCAN tile 7 with all axis-map positioners; three scanned and one monitor on stars."""
    end = {h: (30.0, 150.0) for h in POSITIONERS}
    end.update(C4=(40.0, 140.0), D2=(25.0, 120.0), H5=(50.0, 100.0), J3=(35.0, 130.0))
    header = ','.join(f'{h}_{a}' for h in POSITIONERS for a in ('a', 'b'))
    rows = [{h: (30.0, 150.0) for h in POSITIONERS},
            {h: ((30 + a) / 2, (150 + b) / 2) for h, (a, b) in end.items()}, end]
    path = root / 'ZOSCAN_2627_0007.coarse.path.txt'
    path.write_text(header + '\n' + '\n'.join(
        ','.join(f'{v:.5f}' for h in POSITIONERS for v in row[h]) for row in rows) + '\n')
    assign = root / 'ZOSCAN_2627_0007.assign.txt'
    assign.write_text(''.join(
        f'{h} 0.0 0.0 {13.0 if h in end else 0.0} {1 if h in SCANNED + [MONITOR] else 0} '
        f'1 72.3 -30.0\n' for h in POSITIONERS))
    (root / 'ZOSCAN_2627.info.txt').write_text('7 72.344 -30.0\n')
    return assign, path, end


class RunscanTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = root = Path(self.directory.name)
        (root / 'Lib').mkdir()
        (root / 'Lib' / 'KSPEC.ini').write_text((ROOT / 'Lib' / 'KSPEC.ini').read_text())
        (root / 'SCIOBS' / 'observation').mkdir(parents=True)
        cwd = os.getcwd()
        os.chdir(root)
        self.addCleanup(os.chdir, cwd)
        self.assign, self.path, self.end = write_tile(root)
        # the converged MTL trial: the path end plus a small correction of C4
        self.trial = starscan.to_command(self.end)
        self.trial['C4_a'] += 0.05
        self.trial_json = str(root / 'ZOSCAN_2627_0007_MetrologyTrial_1.json')
        starscan.write_angles(self.trial_json, self.trial)
        self.outdir = root / 'scan'
        for target in ('handle_lamp',):
            patcher = patch.object(cli, target, AsyncMock())
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(cli, 'mtl_json_on_ics', lambda name: name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def scriptrun(self, **client):
        queue = asyncio.Queue()
        self.client = FakeClient(queue, trial_json=self.trial_json, **client)
        obs = cli.script()
        obs.ICSclient = self.client
        obs.response_queue = queue
        obs.GFA_response_queue = asyncio.Queue()
        return obs

    async def run_scan(self, *extra, **client):
        obs = self.scriptrun(**client)
        params = [str(self.assign), str(self.path), '--monitors', MONITOR, '--no-guide',
                  '--zenith-angle', '0', '--arms', 'design', '--outdir', str(self.outdir), *extra]
        with redirect_stdout(io.StringIO()) as out:
            await cli.handle_script('runscan ' + ' '.join(f'"{p}"' for p in params),
                                    scriptrun=obs)
            if obs.script_task is not None:
                await obs.script_task
        records = [json.loads(line) for line in
                   (self.outdir / 'ZOSCAN_0007_scan.jsonl').read_text().splitlines()] \
            if (self.outdir / 'ZOSCAN_0007_scan.jsonl').exists() else []
        return obs, out.getvalue(), records

    async def test_scan_sequence_and_offsets(self):
        obs, out, records = await self.run_scan('--pattern', 'cross', '--npts', '3',
                                                '--step', '35', '--unit', 'um')
        pattern = starscan.scan_pattern('cross', 35.0, 3)
        n = len(pattern)
        self.assertEqual(self.client.sent[:5], [
            ('MTL', 'loadobj'), ('MTL', 'mtlstart'), ('FBP', 'loadmotion'),
            ('FBP', 'loadmotion'), ('FBP', 'fbpmoveall')])
        # metrology loop: illuon, mtltrial (converged), illulightoff, illuoff
        self.assertEqual(self.client.sent[5:9], [
            ('ISOPLANE', 'illuon'), ('MTL', 'mtltrial'), ('ISOPLANE', 'illulightoff'),
            ('ISOPLANE', 'illuoff')])
        self.assertEqual(self.client.sent[9:], [('FBP', 'fbpoffset'), ('ISOPLANE', 'getobj')] * n
                         + [('FBP', 'fbpoffset')])

        # every fbpoffset is complete; scanned fibres move by the offset, the rest stay at A0
        for step, offsets in zip(pattern, self.client.offsets):
            starscan.check_complete(offsets, POSITIONERS)
            for key, value in offsets.items():
                hole = key[:-2]
                if hole not in SCANNED:
                    self.assertEqual(value, self.trial[key])
            for hole in SCANNED:
                a0, b0 = starscan.to_geometric(self.trial)[hole]
                a, b = starscan.to_geometric(offsets)[hole]
                x0, y0 = starscan.forward(a0, b0, starscan.DESIGN_ARMS)
                x, y = starscan.forward(a, b, starscan.DESIGN_ARMS)
                self.assertAlmostEqual((x - x0) * 1e3, step['dx'], places=6)
                self.assertAlmostEqual((y - y0) * 1e3, step['dy'], places=6)
        self.assertEqual(self.client.offsets[-1], self.trial)       # back to the centre

        kinds = [r['kind'] for r in records]
        self.assertEqual(kinds, ['start', 'centre'] + ['step'] * n + ['return', 'end'])
        steps = [r for r in records if r['kind'] == 'step']
        self.assertEqual(steps[0]['flux'], {'C4': 1000.0, 'D2': 1001.0, 'H5': 1002.0,
                                            'J3': 1003.0})
        self.assertEqual([(s['dx_um'], s['dy_um']) for s in steps],
                         [(p['dx'], p['dy']) for p in pattern])
        self.assertAlmostEqual(steps[1]['dE_arcsec'], pattern[1]['dx'] / 25.0)
        self.assertEqual(records[-1]['status'], 'done')
        self.assertEqual(records[1]['mtl_trial']['filename'], self.trial_json)

    async def test_fbp_failure_stops_without_return(self):
        obs, out, records = await self.run_scan('--npts', '3', fail_fbpoffset_at=2)
        scan = self.client.sent[9:]
        self.assertEqual(scan, [('FBP', 'fbpoffset'), ('ISOPLANE', 'getobj'),
                                ('FBP', 'fbpoffset')])
        self.assertEqual(records[-1]['status'], 'fbpoffset failed')
        self.assertNotIn('return', [r['kind'] for r in records])
        self.assertIn('Positioners are left where FBP stopped', out)

    async def test_refused_pattern_moves_nothing(self):
        obs, out, records = await self.run_scan('--npts', '9', '--step', '2.8')
        self.assertEqual(self.client.sent, [])
        self.assertIn('--max-offset-um', out)

    async def test_refused_offset_moves_nothing_for_the_scan(self):
        # H5 stretched (beta 0): offsets there are refused before the first scan move
        self.trial['H5_b'] = 150.0
        starscan.write_angles(self.trial_json, self.trial)
        obs, out, records = await self.run_scan('--npts', '3')
        self.assertNotIn(('FBP', 'fbpoffset'), self.client.sent[9:])
        self.assertEqual(records[-1]['kind'], 'end')
        self.assertIn('plan refused', records[-1]['status'])

    async def test_centre_json_skips_setup(self):
        obs, out, records = await self.run_scan('--npts', '3', '--pattern', 'line-x',
                                                '--centre', self.trial_json)
        self.assertEqual(self.client.sent[0], ('FBP', 'fbpoffset'))
        self.assertNotIn(('MTL', 'mtltrial'), self.client.sent)

    async def test_dry_run_sends_nothing(self):
        obs, out, records = await self.run_scan('--dry-run', '--mtl-check')
        self.assertEqual(self.client.sent, [])
        self.assertIn('DRY RUN', out)
        self.assertIn('[dry-run] FBP fbpoffset ZOSCAN_0007_scan000.json', out)
        self.assertTrue(records[0]['dry_run'])
        self.assertEqual(records[-1]['status'], 'done')
        n = len(starscan.scan_pattern('grid', 35.0, 5))
        self.assertEqual(len(list(self.outdir.glob('ZOSCAN_0007_scan*.json'))), n)
        # the stand-in centre is the path end in command angles
        self.assertEqual(starscan.read_angles(self.outdir / 'ZOSCAN_0007_centre.json'),
                         starscan.to_command(self.end))

    async def test_guiding_starts_and_stops(self):
        obs = self.scriptrun()

        async def guide(*args, **kwargs):
            obs.autoguide_task = asyncio.create_task(asyncio.sleep(3600))
        obs.run_autoguide = guide
        obs.autoguidestop = AsyncMock()
        params = [str(self.assign), str(self.path), '--zenith-angle', '0', '--arms', 'design',
                  '--guide-settle', '0', '--npts', '1', '--outdir', str(self.outdir)]
        with redirect_stdout(io.StringIO()):
            await obs.handle_scan(obs, None, cli.parse_scan_args(params))
        obs.autoguidestop.assert_awaited_once()
        obs.autoguide_task.cancel()
        steps = [json.loads(line) for line in
                 (self.outdir / 'ZOSCAN_0007_scan.jsonl').read_text().splitlines()]
        self.assertTrue(all(s['guiding'] for s in steps if s['kind'] == 'step'))

    def test_bad_options_do_not_exit(self):
        for params in ([], ['a', 'b', '--npts', '4'], ['a', 'b', '--bogus'], ['-h']):
            with self.assertRaises(cli.ScanArgsError), redirect_stdout(io.StringIO()):
                cli.parse_scan_args(params)


class StarscanHelperTests(unittest.TestCase):

    def test_command_convention(self):
        self.assertEqual(starscan.to_command({'C4': (30.0, 150.0)}), {'C4_a': 0.0, 'C4_b': 0.0})
        self.assertEqual(starscan.to_command({'C4': (40.0, 120.0)}),
                         {'C4_a': -10.0, 'C4_b': 30.0})
        self.assertEqual(starscan.to_geometric({'C4_a': -10.0, 'C4_b': 30.0}),
                         {'C4': (40.0, 120.0)})

    def test_inverse_kinematics_round_trip(self):
        arms = (5.2, 11.6)
        for alpha, beta in ((30, 150), (-170, 40), (400, 95), (10, -60)):
            x, y = starscan.forward(alpha, beta, arms)
            a, b = starscan.inverse(x, y, arms, near=(alpha + 0.3, beta - 0.2))
            self.assertAlmostEqual(a, alpha, places=9)
            self.assertAlmostEqual(b, beta, places=9)
        with self.assertRaises(ValueError):
            starscan.inverse(20.0, 0.0, arms, near=(0, 90))

    def test_quantum(self):
        centre = starscan.to_command({'C4': (40.0, 120.0)})
        angles, achieved = starscan.offset_command(centre, ['C4'], 35.0, 0.0, (5.2, 11.6),
                                                   quantum=0.0984, max_delta_deg=5)
        for key in ('C4_a', 'C4_b'):
            self.assertAlmostEqual(angles[key] / 0.0984, round(angles[key] / 0.0984), places=9)
        self.assertNotAlmostEqual(achieved['C4'][0], 35.0, places=3)

    def test_pattern(self):
        grid = starscan.scan_pattern('grid', 10.0, 3)
        self.assertEqual(len(grid), 9 + 2)      # centre at start and end; the middle one is
        self.assertTrue(grid[0]['centre'] and grid[-1]['centre'])     # the grid's own centre
        self.assertEqual([(p['dx'], p['dy']) for p in grid[1:4]],
                         [(-10.0, -10.0), (0.0, -10.0), (10.0, -10.0)])
        self.assertEqual(sum(p['centre'] for p in starscan.scan_pattern('grid', 10.0, 5)), 3)
        with self.assertRaises(ValueError):
            starscan.scan_pattern('grid', 10.0, 4)

    def test_tile_names(self):
        self.assertEqual(starscan.parse_tile_name('ASPECS_2627.0005.assign.txt'), ('ASPECS', 5))
        self.assertEqual(starscan.parse_tile_name('/x/ZOSCAN_2627_0005.coarse.path.txt'),
                         ('ZOSCAN', 5))
        with self.assertRaises(ValueError):
            starscan.parse_tile_name('ZOSCAN_0005.assign.txt')

    def test_check_complete(self):
        angles = starscan.to_command({h: (30.0, 150.0) for h in POSITIONERS})
        starscan.check_complete(angles, POSITIONERS)
        del angles['C4_b']
        with self.assertRaises(ValueError):
            starscan.check_complete(angles, POSITIONERS)

    def test_zero_order_fluxes(self):
        zo = {'ok': True, 'fibres': {'label': ['C4', 'D2'], 'flux': [5.0, 6.0]}}
        self.assertEqual(cli.zero_order_fluxes(zo, ['C4', 'H5']), {'C4': 5.0, 'H5': None})
        self.assertEqual(cli.zero_order_fluxes({'ok': False}, ['C4']), {'C4': None})


if __name__ == '__main__':
    unittest.main()
