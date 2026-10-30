"""script/pathtest.py with fake broker, prompts and lamps (nothing is sent anywhere)."""
import asyncio
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from collections import Counter
from unittest.mock import patch

from script import pathtest
from script.starscan import axis_map_positioners, check_complete, read_angles, to_command

HOLES = ['F001', 'F002']
ROWS = [  # geometric (alpha, beta) per hole; row 0 = power-on pose
    {'F001': (30.0, 150.0), 'F002': (30.0, 150.0)},
    {'F001': (40.0, 140.0), 'F002': (30.0, 150.0)},
    {'F001': (50.0, 130.0), 'F002': (25.0, 155.0)},
    {'F001': (60.0, 120.0), 'F002': (20.0, 160.0)},
]


def write_path(path, rows):
    holes = list(rows[0])
    with open(path, 'w', encoding='utf-8') as f:
        f.write(','.join(f'{h}_{arm}' for h in holes for arm in ('a', 'b')) + '\n')
        for r in rows:
            f.write(','.join(f'{v:.5f}' for h in holes for v in r[h]) + '\n')
    return path


class FakeLink:
    """Records sends in a shared event list; Done replies on demand.

    fbp_status : {n-th fbpoffset sent: status}
    raise_at   : {(func, n-th wait_done of func): exception}
    """

    def __init__(self, events, fbp_status=None, raise_at=None, illu_status=None):
        self.events = events
        self.fbp_status = fbp_status or {}
        self.illu_status = illu_status or {}
        self.raise_at = raise_at or {}
        self.sent = Counter()
        self.waits = Counter()
        self.last = {}

    async def send(self, key, body):
        d = json.loads(body)
        self.sent[d['func']] += 1
        self.last[d['func']] = d
        self.events.append((key, d['func'], d))

    async def wait_done(self, inst, func, timeout, match=None):
        self.waits[func] += 1
        exc = self.raise_at.get((func, self.waits[func]))
        if exc is not None:
            raise exc
        status = 'success'
        if func == 'fbpoffset':
            status = self.fbp_status.get(self.sent[func], 'success')
        elif func in self.illu_status:
            status = self.illu_status[func]
        reply = {'inst': inst, 'func': func, 'process': 'Done', 'status': status,
                 'message': f'fake {status}'}
        if func == 'mtltest':
            reply['images'] = [f"{self.last[func]['file']}_0.fits"]
        return reply


def funcs(events):
    return [func for _, func, _ in events]


def fbp_rows(events):
    return [int(re.search(r'_r(\d{3})\.json$', d['source_name'])[1])
            for _, func, d in events if func == 'fbpoffset']


class PathTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        self.path = write_path(os.path.join(self.dir, 'TEST_2627_0001.path.txt'), ROWS)
        self.events = []
        self.lines = []

    async def lamp(self, cmd):
        self.events.append(('LAMP', cmd, {}))

    def make(self, rows, link=None, answers=None, **kw):
        self.link = link or FakeLink(self.events)
        answers = list(answers or [])

        def ask(prompt):
            if answers:
                a = answers.pop(0)
                if isinstance(a, BaseException):
                    raise a
                return a
            return ''

        opts = dict(link=self.link, ask=ask, lamp=self.lamp,
                    outdir=os.path.join(self.dir, 'out'), positioners=HOLES, prompt=False,
                    out=self.lines.append)
        opts.update(kw)
        return pathtest.PathTest(self.path, rows, **opts)

    def records(self, test):
        with open(test.log.path, encoding='utf-8') as f:
            return [json.loads(line) for line in f]


class RowSelectionTests(unittest.TestCase):
    def test_every_k_includes_last_row(self):
        self.assertEqual(pathtest.select_rows(48, 8), [0, 8, 16, 24, 32, 40, 47])
        self.assertEqual(pathtest.select_rows(48, 1), list(range(48)))
        self.assertEqual(pathtest.select_rows(48, 47), [0, 47])
        self.assertEqual(pathtest.select_rows(48, 100), [0, 47])

    def test_slices(self):
        self.assertEqual(pathtest.select_rows(48, 8, '8:'), [8, 16, 24, 32, 40, 47])
        self.assertEqual(pathtest.select_rows(48, 5, '3:20'), [3, 8, 13, 18, 20])
        self.assertEqual(pathtest.select_rows(48, 4, ':10'), [0, 4, 8, 10])
        # reversed slices run backwards and still end on the last row of the slice
        self.assertEqual(pathtest.select_rows(48, 4, '10:2'), [10, 6, 2])
        self.assertEqual(pathtest.select_rows(48, 4, '10:3'), [10, 6, 3])
        self.assertEqual(pathtest.select_rows(48, 1, '47:47'), [47])

    def test_row_lists(self):
        self.assertEqual(pathtest.select_rows(48, 1, '47,40,8,0'), [47, 40, 8, 0])
        self.assertEqual(pathtest.select_rows(48, 1, '5'), [5])

    def test_bad_rows(self):
        for every, rows in ((1, '0:48'), (2, '1,2'), (0, None), (1, '3,3'), (1, '-1:4')):
            with self.subTest(every=every, rows=rows), self.assertRaises(ValueError):
                pathtest.select_rows(48, every, rows)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.positioners = axis_map_positioners()

    def test_json_files_are_complete_command_angles(self):
        geo = [{h: (30.0, 150.0) for h in self.positioners},
               {h: (30.0 + i, 150.0 - 2 * i) for i, h in enumerate(self.positioners)},
               {h: (10.0, 170.0) for h in self.positioners}]
        path = write_path(os.path.join(self.tmp.name, 'ZOSCAN_2627_0005.coarse.path.txt'), geo)
        stem = pathtest.path_stem(path)
        self.assertEqual(stem, 'ZOSCAN_2627_0005_coarse')
        _, files = pathtest.make_plan(path, [0, 2, 1], self.tmp.name, stem, self.positioners)
        self.assertEqual(sorted(files), [0, 1, 2])
        for row, json_file in files.items():
            self.assertEqual(os.path.basename(json_file), f'{stem}_r{row:03d}.json')
            angles = read_angles(json_file)
            check_complete(angles, self.positioners)
            self.assertEqual(len(angles), 2 * len(self.positioners))
            for key, value in to_command(geo[row]).items():
                self.assertAlmostEqual(angles[key], value, places=4)
        self.assertTrue(all(v == 0.0 for v in read_angles(files[0]).values()))

    def test_missing_positioner_refused_before_anything(self):
        path = write_path(os.path.join(self.tmp.name, 'X.path.txt'),
                          [{h: (30.0, 150.0) for h in self.positioners[:-1]}])
        with self.assertRaises(ValueError):
            pathtest.make_plan(path, [0], self.tmp.name, 'X', self.positioners)


class RunTests(PathTestBase):
    async def test_message_order_with_backlight(self):
        test = self.make([0, 1, 2], backlight=True)
        outcome = await test.run()
        self.assertEqual(outcome, 'done, returned')
        image = ['illulighton', 'mtltest', 'illulightoff']
        self.assertEqual(funcs(self.events),
                         ['illuon', 'illulightoff']
                         + ['fbpoffset'] + image + ['fbpoffset'] + image + ['fbpoffset'] + image
                         + ['fbpoffset'] + image + ['fbpoffset'] + image
                         + ['illuoff'])
        self.assertEqual(fbp_rows(self.events), [0, 1, 2, 1, 0])
        files = [d['file'] for _, f, d in self.events if f == 'mtltest']
        self.assertEqual(files, ['TEST_2627_0001_r000', 'TEST_2627_0001_r001',
                                 'TEST_2627_0001_r002', 'TEST_2627_0001_r001_ret',
                                 'TEST_2627_0001_r000_ret'])
        self.assertTrue(all(key == 'ISOPLANE' for key, f, _ in self.events if f.startswith('illu')))
        steps = [r for r in self.records(test) if r['event'] == 'step']
        self.assertEqual([(r['phase'], r['row']) for r in steps],
                         [('forward', 0), ('forward', 1), ('forward', 2),
                          ('return', 1), ('return', 0)])
        self.assertEqual(steps[0]['max_dangle_deg'], 0.0)
        self.assertEqual(steps[1]['max_dangle_deg'], 10.0)
        self.assertEqual((steps[1]['n_move'], steps[1]['movers']), (1, ['F001']))
        self.assertEqual(steps[2]['mtl_images'], ['TEST_2627_0001_r002_0.fits'])
        self.assertEqual(steps[2]['fbp_status'], 'success')

    async def test_no_mtl_moves_only(self):
        test = self.make([0, 3], mtl=False, backlight=True)
        self.assertEqual(await test.run(), 'done, returned')
        self.assertEqual(funcs(self.events), ['fbpoffset'] * 3)
        self.assertEqual(fbp_rows(self.events), [0, 3, 0])

    async def test_no_return(self):
        test = self.make([0, 1, 2], mtl=False, do_return=False)
        self.assertEqual(await test.run(), 'done')
        self.assertEqual(fbp_rows(self.events), [0, 1, 2])
        self.assertTrue(any('--rows 2,1,0 --no-return' in line for line in self.lines))

    async def test_q_stops_forward_and_returns_through_visited_rows(self):
        test = self.make([0, 1, 2, 3], prompt=True, answers=['', 'm', 'q', '', 'x', ''])
        self.assertEqual(await test.run(), 'quit, returned')
        self.assertEqual(fbp_rows(self.events), [0, 1, 0])
        # 'm' moved without an image; 'x' was asked again
        self.assertEqual([d['file'] for _, f, d in self.events if f == 'mtltest'],
                         ['TEST_2627_0001_r000', 'TEST_2627_0001_r000_ret'])

    async def test_q_while_returning_leaves_command_to_return(self):
        test = self.make([0, 1, 2], prompt=True, mtl=False, answers=['', '', '', 'q'])
        self.assertEqual(await test.run(), 'done, return quit')
        self.assertEqual(fbp_rows(self.events), [0, 1, 2])
        self.assertTrue(any('--rows 2,1,0 --no-return' in line for line in self.lines))

    async def test_fbp_failure_stops_without_return(self):
        link = FakeLink(self.events, fbp_status={2: 'fail'})
        test = self.make([0, 1, 2], link=link, backlight=True, fiducials=True)
        self.assertEqual(await test.run(), 'fbp_failed')
        self.assertEqual(fbp_rows(self.events), [0, 1])
        self.assertEqual(funcs(self.events)[0], 'fiducialon')
        self.assertEqual(funcs(self.events)[-2:], ['illuoff', 'fiducialoff'])
        self.assertEqual(funcs(self.events).count('mtltest'), 1)
        steps = [r for r in self.records(test) if r['event'] == 'step']
        self.assertEqual(steps[-1]['result'], 'fbp_failed')
        self.assertEqual(self.records(test)[-1]['outcome'], 'fbp_failed')
        self.assertTrue(any('--rows 0 --no-return' in line for line in self.lines))

    async def test_fbp_timeout_reply_is_a_failure(self):
        link = FakeLink(self.events, fbp_status={1: 'error'})
        test = self.make([0, 1], link=link, mtl=False)
        self.assertEqual(await test.run(), 'fbp_failed')
        self.assertEqual(fbp_rows(self.events), [0])

    async def test_setup_failure_moves_nothing(self):
        link = FakeLink(self.events, illu_status={'illuon': 'fail'})
        test = self.make([0, 1], link=link, backlight=True)
        self.assertEqual(await test.run(), 'setup_failed')
        self.assertEqual(funcs(self.events), ['illuon', 'illuoff'])

    async def test_mtl_failure_stops_forward_and_still_returns(self):
        class FailingMtl(FakeLink):
            async def wait_done(self, inst, func, timeout, match=None):
                reply = await super().wait_done(inst, func, timeout, match)
                if func == 'mtltest' and self.waits[func] in (3, 4):
                    reply['status'] = 'fail'
                return reply
        test = self.make([0, 1, 2, 3], link=FailingMtl(self.events), backlight=True)
        self.assertEqual(await test.run(), 'aux, returned')
        self.assertEqual(fbp_rows(self.events), [0, 1, 2, 1, 0])
        # r002 fails: forward stops; r001_ret fails: the rest of the return has no images
        files = [d['file'] for _, f, d in self.events if f == 'mtltest']
        self.assertEqual(files, ['TEST_2627_0001_r000', 'TEST_2627_0001_r001',
                                 'TEST_2627_0001_r002', 'TEST_2627_0001_r001_ret'])
        self.assertEqual(funcs(self.events)[-1], 'illuoff')


class InterruptTests(PathTestBase):
    async def test_ctrl_c_at_prompt_returns_and_backlight_off(self):
        test = self.make([0, 1, 2, 3], prompt=True, backlight=True,
                         answers=['', '', KeyboardInterrupt(), ''])
        self.assertEqual(await test.run(), 'interrupt, returned')
        self.assertEqual(fbp_rows(self.events), [0, 1, 0])
        self.assertEqual(funcs(self.events)[-1], 'illuoff')

    async def test_ctrl_c_during_mtl_image(self):
        link = FakeLink(self.events, raise_at={('mtltest', 2): KeyboardInterrupt()})
        test = self.make([0, 1, 2], link=link, backlight=True)
        self.assertEqual(await test.run(), 'interrupt, returned')
        self.assertEqual(fbp_rows(self.events), [0, 1, 0])
        f = funcs(self.events)
        second = [i for i, x in enumerate(f) if x == 'mtltest'][1]
        self.assertEqual(f[second + 1], 'illulightoff')       # light off before moving back
        self.assertEqual(f[-1], 'illuoff')

    async def test_cancelled_during_mtl_image(self):
        link = FakeLink(self.events, raise_at={('mtltest', 1): asyncio.CancelledError()})
        test = self.make([0, 1, 2], link=link, backlight=True)
        self.assertEqual(await test.run(), 'interrupt')
        self.assertEqual(fbp_rows(self.events), [0])
        self.assertEqual(funcs(self.events)[-1], 'illuoff')

    async def test_ctrl_c_during_move_waits_for_its_reply(self):
        link = FakeLink(self.events, raise_at={('fbpoffset', 2): KeyboardInterrupt()})
        test = self.make([0, 1, 2], link=link, backlight=True)
        self.assertEqual(await test.run(), 'interrupt, returned')
        self.assertEqual(fbp_rows(self.events), [0, 1, 0])
        self.assertEqual(link.waits['fbpoffset'], 4)    # the interrupted move was waited twice
        self.assertEqual(funcs(self.events).count('mtltest'), 2)   # no image at row 1
        self.assertEqual(funcs(self.events)[-1], 'illuoff')

    async def test_second_ctrl_c_during_move_aborts_without_return(self):
        link = FakeLink(self.events, raise_at={('fbpoffset', 2): KeyboardInterrupt(),
                                               ('fbpoffset', 3): KeyboardInterrupt()})
        test = self.make([0, 1, 2], link=link, backlight=True, fiducials=True)
        self.assertEqual(await test.run(), 'aborted')
        self.assertEqual(fbp_rows(self.events), [0, 1])
        self.assertEqual(funcs(self.events)[-2:], ['illuoff', 'fiducialoff'])

    async def test_ctrl_c_while_returning_stops_there(self):
        test = self.make([0, 1, 2], prompt=True, mtl=False, backlight=True,
                         answers=['', '', '', KeyboardInterrupt()])
        self.assertEqual(await test.run(), 'done, return interrupt')
        self.assertEqual(fbp_rows(self.events), [0, 1, 2])
        self.assertTrue(any('--rows 2,1,0 --no-return' in line for line in self.lines))


class DryRunTests(unittest.TestCase):
    def test_dry_run_sends_nothing_and_writes_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            positioners = axis_map_positioners()
            geo = [{h: (30.0, 150.0) for h in positioners},
                   {h: (35.0, 140.0) for h in positioners},
                   {h: (40.0, 130.0) for h in positioners}]
            path = write_path(os.path.join(tmp, 'ZOSCAN_2627_0005.coarse.path.txt'), geo)
            outdir = os.path.join(tmp, 'out')
            stdout = io.StringIO()
            with patch.object(pathtest, 'BrokerLink', side_effect=AssertionError('broker')), \
                    patch('LAMP.lampcli.handle_lamp', side_effect=AssertionError('lamp')), \
                    patch('builtins.input', side_effect=AssertionError('prompt')), \
                    contextlib.redirect_stdout(stdout):
                code = pathtest.main(['--path', path, '--backlight', '--fiducials',
                                      '--dry-run', '--outdir', outdir])
            text = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn('DRY RUN: nothing is sent', text)
            self.assertNotIn('LIVE RUN', text)
            self.assertIn('[dry-run] would send FBP fbpoffset ZOSCAN_2627_0005_coarse_r001.json '
                          '(146 angles)', text)
            self.assertIn('[dry-run] would switch LAMP fiducialon', text)
            self.assertTrue(all(line.startswith(('[dry-run] would', '[fwd', '[ret', '='))
                                or '->' not in line for line in text.splitlines()))
            stem = 'ZOSCAN_2627_0005_coarse'
            for row in range(3):
                angles = read_angles(os.path.join(outdir, f'{stem}_r{row:03d}.json'))
                self.assertEqual(len(angles), 146)
            with open(os.path.join(outdir, f'{stem}_pathtest.jsonl'), encoding='utf-8') as f:
                records = [json.loads(line) for line in f]
            self.assertTrue(all(r['dry_run'] for r in records))
            self.assertEqual([r['row'] for r in records if r['event'] == 'step'],
                             [0, 1, 2, 1, 0])
            self.assertEqual(records[-1]['outcome'], 'done, returned')


if __name__ == '__main__':
    unittest.main()
