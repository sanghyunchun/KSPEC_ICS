"""Exercise the ISOPLANE server with the fake LightField and the fake Uno (no hardware).

Run from the repository root: python -m unittest tests.test_isoplane_fake
"""
import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
import warnings
from unittest.mock import AsyncMock, patch

from astropy.io import fits

from SPECTRO_ISOPLANE.backillum import BackIllumination, FakeUno
from SPECTRO_ISOPLANE.command import Isoplane
from SPECTRO_ISOPLANE.fitsio import append_cards
from SPECTRO_ISOPLANE.lightfield import FakeLightField

HEADER = {'OBSDATE': '20261101', 'OBSTYPE': 'Object', 'PROJID': 'P1', 'TileID': '0123',
          'RA': '10:00:00', 'DEC': '-30:00:00', 'EXPTIME': 5, 'EXPNUM': '1/1', 'FWHM': 1.2}


class SingleCallLightField(FakeLightField):
    """Like the real driver: one LightField call at a time, so status() waits for expose()."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.call = threading.Lock()

    def status(self):
        with self.call:
            return super().status()

    def expose(self, *args):
        with self.call:
            return super().expose(*args)


class FakeServer:
    def __init__(self):
        self.sent = []

    async def send_message(self, key, message):
        self.sent.append((key, json.loads(message)))

    def done(self, func):
        return [m for _, m in self.sent if m['func'] == func and m['process'] == 'Done']


def body(func, **kw):
    return json.dumps({'inst': 'SPEC', 'func': func, 'message': func, **kw})


class IsoplaneFakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = FakeServer()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, start_mm=0.0, unit=True, lf=None):
        lf = lf or FakeLightField(time_scale=0.001, shape=(1, 8, 10))
        bl = None
        if unit:
            bl = BackIllumination(FakeUno(time_scale=0.005, start_mm=start_mm),
                                  in_depth_mm=50, in_limit_mm=50, time_scale=0.005)
        cfg = {'datapath': os.path.join(self.tmp.name, 'raw'),
               'sharepath': os.path.join(self.tmp.name, 'share')}
        return Isoplane(cfg, lightfield=lf, backillum=bl)

    def run_cmds(self, iso, *bodies, start=True):
        async def go():
            if start:
                await iso.start()
            for b in bodies:
                await iso.handle(self.server, b)
            if iso.bl is not None:
                iso.bl._stop_ping.set()
        asyncio.run(go())

    def test_frames_named_copied_and_carded(self):
        iso = self.make()
        self.run_cmds(iso, body('specinitial', dirname='20261101'),
                      body('getbias', numframe=2, header=HEADER),
                      body('getobj', time=5, numframe=1, header=HEADER))
        bias, obj = self.server.done('getbias')[0], self.server.done('getobj')[0]
        self.assertEqual(bias['status'], 'success')
        self.assertEqual([os.path.basename(p) for p in bias['filenames']],
                         ['20261101_0001_bias.fits', '20261101_0002_bias.fits'])
        self.assertTrue(obj['filename'].startswith(os.path.join(self.tmp.name, 'share')))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            h = fits.getheader(obj['filename'])
        self.assertEqual((h['TILEID'], h['EXPNUM'], h['BILLUM'], h['SPECBACK']),
                         ('0123', '1/1', 'OUT', 'ISOPLANE'))
        self.assertEqual(h['EXPTIME'], '5000')  # LightField's own card is kept (ms)
        self.assertEqual(h['EXPREQ'], '5')

    def test_exposure_and_experiment_refused_while_stage_in(self):
        iso = self.make()
        self.run_cmds(iso, body('specinitial', dirname='20261101'), body('illuon'),
                      body('getobj', time=5, numframe=1, header=HEADER),
                      body('specinitial', dirname='20261101', experiment='KSPEC_600_430'),
                      body('illuoff'),
                      body('getobj', time=5, numframe=1, header=HEADER))
        self.assertEqual(self.server.done('illuon')[0]['status'], 'success')
        first, second = self.server.done('getobj')
        self.assertEqual(first['status'], 'error')
        self.assertIn('not OUT', first['message'])
        self.assertEqual(self.server.done('specinitial')[1]['status'], 'error')
        self.assertEqual(iso.lf.experiment, 'fake')  # the grating was not touched
        self.assertEqual(second['status'], 'success')
        self.assertEqual(iso.bl.state, 'OUT')

    def test_restart_away_from_near_blocks_until_illuoff(self):
        iso = self.make(start_mm=30.0)
        self.run_cmds(iso, body('specinitial', dirname='20261101'),
                      body('getbias', numframe=1, header=HEADER), body('illuoff'),
                      body('getbias', numframe=1, header=HEADER))
        refused, ok = self.server.done('getbias')
        self.assertEqual(refused['status'], 'error')
        self.assertEqual(ok['status'], 'success')

    def test_commands_refused_while_busy(self):
        iso = self.make()

        async def go():
            await iso.start()
            await iso.handle(self.server, body('specinitial', dirname='20261101'))
            stage = asyncio.ensure_future(iso.handle(self.server, body('illuon')))
            await asyncio.sleep(0)  # illuon holds the lock and is moving the stage
            for b in (body('getobj', time=5, numframe=1, header=HEADER), body('illuoff'),
                      body('specinitial', dirname='20261101', experiment='KSPEC_600_430')):
                await iso.handle(self.server, b)
            self.assertFalse(stage.done())  # all three were answered during the move
            await stage
            iso.bl._stop_ping.set()
        asyncio.run(go())
        for func in ('getobj', 'illuoff'):
            self.assertEqual(self.server.done(func)[0]['message'],
                             f'{func} refused: busy with illuon.')
        self.assertEqual(self.server.done('specinitial')[1]['status'], 'error')
        self.assertEqual(iso.lf.experiment, 'fake')  # the refused load never ran
        self.assertEqual(self.server.done('illuon')[0]['status'], 'success')
        self.assertFalse(any(m['message'].startswith('Waiting') for _, m in self.server.sent))

    def test_specstatus_does_not_wait_for_exposure(self):
        iso = self.make(lf=SingleCallLightField(time_scale=0.002, shape=(1, 8, 10)))

        async def go():
            await iso.start()
            await iso.handle(self.server, body('specinitial', dirname='20261101'))
            obj = asyncio.ensure_future(
                iso.handle(self.server, body('getobj', time=200, numframe=1, header=HEADER)))
            while not iso.lf.running:  # the 0.4 s exposure holds the LightField call lock
                await asyncio.sleep(0.005)
            t0 = time.time()
            await iso.handle(self.server, body('specstatus'))
            elapsed = time.time() - t0
            self.assertFalse(obj.done())
            await obj
            await iso.handle(self.server, body('specstatus'))
            iso.bl._stop_ping.set()
            return elapsed
        elapsed = asyncio.run(go())
        self.assertLess(elapsed, 0.1)
        during, after = self.server.done('specstatus')
        self.assertTrue(during['message'].startswith('IsoPlane: busy (getobj)'))
        self.assertIn('(as of ', during['message'])
        self.assertEqual(during['isoplane']['lightfield']['grating'], '[500nm,600][0][0]')
        self.assertTrue(after['message'].startswith('IsoPlane: ready'))
        self.assertEqual(self.server.done('getobj')[0]['status'], 'success')

    def test_no_unit_and_no_night(self):
        iso = self.make(unit=False)
        self.run_cmds(iso, body('getbias', numframe=1, header=HEADER), body('illuon'),
                      body('specstatus'))
        self.assertIn('specinitial', self.server.done('getbias')[0]['message'])
        self.assertEqual(self.server.done('illuon')[0]['status'], 'error')
        self.assertEqual(self.server.done('specstatus')[0]['isoplane']['backillum']['state'],
                         'NONE')


class AppendCardsTest(unittest.TestCase):
    def test_lightfield_continue_cards_survive(self):
        cards = ["SIMPLE  =                    T", "BITPIX  =                   16",
                 "NAXIS   =                    2", "NAXIS1  =                    4",
                 "NAXIS2  =                    3", "LONGSTRN= 'OGIP 1.0'",
                 "HIERARCH PI CAMERA EXPERIMENT FILENAMEGENERATION DIRECTORY='&'",
                 "CONTINUE  'C:\\Data\\LightField\\20260128'",
                 "END"]
        head = b"".join(c.ljust(80).encode() for c in cards)
        head += b" " * (-len(head) % 2880)
        data = bytes(range(24)) + b"\0" * (2880 - 24)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'lf.fits')
            with open(path, 'wb') as f:
                f.write(head + data)
            append_cards(path, [('TILEID', '0123', 'ICS tile')])
            raw = open(path, 'rb').read()
            self.assertEqual(raw[:8 * 80], head[:8 * 80])  # LightField cards untouched
            self.assertEqual(raw[-2880:], data)
            self.assertIn(b"TILEID  = '0123    '", raw[:2880])  # FITS pads to 8 chars
            with self.assertRaises(KeyError):
                append_cards(path, [('TILEID', 'x', '')])


class SpecCliRoutingTest(unittest.TestCase):
    def test_isoplane_queue_routes_illumination_and_frames(self):
        from SPECTRO import speccli

        client = AsyncMock()
        with patch.object(speccli, 'spec_queue', return_value='ISOPLANE'), \
                patch.object(speccli, 'set_illumination', AsyncMock()) as relay:
            state = asyncio.run(speccli.handle_spec('illuon', client))
            asyncio.run(speccli.handle_spec('getarc 3 2', client, {}))
            asyncio.run(speccli.handle_spec('specinitial 20261101 KSPEC_600_430', client))
        relay.assert_not_awaited()
        self.assertEqual(state, 1)
        keys = [c.args[0] for c in client.send_message.await_args_list]
        self.assertEqual(keys, ['ISOPLANE'] * 3)
        init = json.loads(client.send_message.await_args_list[2].args[1])
        self.assertEqual(init['experiment'], 'KSPEC_600_430')

    def test_spec_queue_keeps_webrelay(self):
        from SPECTRO import speccli

        client = AsyncMock()
        with patch.object(speccli, 'spec_queue', return_value='SPEC'), \
                patch.object(speccli, 'set_illumination', AsyncMock(return_value=1)) as relay:
            asyncio.run(speccli.handle_spec('illuon', client))
        relay.assert_awaited_once_with(True)
        client.send_message.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
