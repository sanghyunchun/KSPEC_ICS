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
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astropy.io import fits

from SPECTRO_ISOPLANE.backillum import RELEASE, STOP_HOLD, BackIllumination, FakeUno
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
        return self.replies(func, 'Done')

    def replies(self, func, process):
        return [m for _, m in self.sent if m['func'] == func and m['process'] == process]


def body(func, **kw):
    return json.dumps({'inst': 'SPEC', 'func': func, 'message': func, **kw})


class IsoplaneFakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = FakeServer()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, start_mm=0.0, unit=True, lf=None, bl_scale=0.005, **cfg_extra):
        lf = lf or FakeLightField(time_scale=0.001, shape=(1, 8, 10))
        bl = None
        if unit:
            bl = BackIllumination(FakeUno(time_scale=bl_scale, start_mm=start_mm),
                                  in_depth_mm=50, in_limit_mm=50, time_scale=bl_scale)
        cfg = {'datapath': os.path.join(self.tmp.name, 'raw'),
               'sharepath': os.path.join(self.tmp.name, 'share'), **cfg_extra}
        iso = Isoplane(cfg, lightfield=lf, backillum=bl)
        iso.light_settle_s = 0.0
        return iso

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
        self.assertEqual(first['status'], 'fail')  # refused, nothing done
        self.assertIn('not OUT', first['message'])
        self.assertEqual(self.server.done('specinitial')[1]['status'], 'fail')
        self.assertEqual(iso.lf.experiment, 'fake')  # the grating was not touched
        self.assertEqual(second['status'], 'success')
        self.assertEqual(iso.bl.state, 'OUT')

    def test_restart_away_from_near_blocks_until_illuoff(self):
        iso = self.make(start_mm=30.0)
        self.run_cmds(iso, body('specinitial', dirname='20261101'),
                      body('getbias', numframe=1, header=HEADER), body('illuoff'),
                      body('getbias', numframe=1, header=HEADER))
        refused, ok = self.server.done('getbias')
        self.assertEqual(refused['status'], 'fail')
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
            self.assertEqual(self.server.done(func)[0]['status'], 'fail')
        self.assertEqual(self.server.done('specinitial')[1]['status'], 'fail')
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

    def test_specstop_during_illuon_stops_stage_before_light(self):
        iso = self.make(bl_scale=0.05)  # the 50 mm move takes 0.25 s
        uno = iso.bl.link
        stop_line = 'MB ' + STOP_HOLD.hex().upper()

        async def go():
            await iso.start()
            await iso.handle(self.server, body('specinitial', dirname='20261101'))
            stage = asyncio.ensure_future(iso.handle(self.server, body('illuon')))
            while uno.position() < 5.0:
                await asyncio.sleep(0.005)
            n0 = len(uno.log)
            await iso.handle(self.server, body('specstop'))
            await stage  # the stop wakes illuon at once, which then fails
            stopped_at = uno.position()
            await asyncio.sleep(0.1)
            self.assertEqual(uno.position(), stopped_at)
            self.assertLess(stopped_at, 50.0)  # stopped mid-move: specstop did not wait
            stop_lines = [l for l in uno.log[n0:] if l in (stop_line, 'L OFF')]
            self.assertEqual(stop_lines[:2], [stop_line, 'L OFF'])
            for b in (body('getobj', time=5, numframe=1, header=HEADER), body('illuon'),
                      body('illuoff'), body('getobj', time=5, numframe=1, header=HEADER)):
                await iso.handle(self.server, b)
            iso.bl._stop_ping.set()
        asyncio.run(go())
        # While a command runs, specstop answers ING: illuon's own Done is the one Done.
        self.assertEqual(self.server.done('specstop'), [])
        stop = self.server.replies('specstop', 'ING')[0]
        self.assertEqual(stop['status'], 'success')
        self.assertIn('during illuon', stop['message'])
        illuon_first, illuon_again = self.server.done('illuon')
        self.assertEqual(illuon_first['status'], 'stopped')
        self.assertIn('stopped by specstop', illuon_first['message'])
        self.assertEqual(illuon_again['status'], 'error')  # position unknown: home first
        refused, ok = self.server.done('getobj')
        self.assertEqual(refused['status'], 'fail')
        self.assertIn('not OUT', refused['message'])
        self.assertEqual(self.server.done('illuoff')[0]['status'], 'success')
        self.assertEqual(ok['status'], 'success')
        self.assertFalse(uno.light)

    def test_specstop_during_exposure(self):
        iso = self.make(lf=SingleCallLightField(time_scale=0.002, shape=(1, 8, 10)))

        async def go():
            await iso.start()
            await iso.handle(self.server, body('specinitial', dirname='20261101'))
            obj = asyncio.ensure_future(
                iso.handle(self.server, body('getobj', time=200, numframe=2, header=HEADER)))
            while not iso.lf.running:
                await asyncio.sleep(0.005)
            await iso.handle(self.server, body('specstop'))
            await obj
            await iso.handle(self.server, body('illuoff'))
            await iso.handle(self.server, body('getbias', numframe=1, header=HEADER))
            iso.bl._stop_ping.set()
        asyncio.run(go())
        obj, = self.server.done('getobj')
        self.assertEqual(obj['status'], 'stopped')
        self.assertIn('acquisition stopped', obj['message'])
        raw = os.path.join(self.tmp.name, 'raw', '20261101')
        self.assertEqual([f for f in os.listdir(raw) if 'obj' in f], [])
        self.assertEqual(self.server.done('specstop'), [])
        self.assertEqual(self.server.replies('specstop', 'ING')[0]['status'], 'success')
        self.assertEqual(self.server.done('getbias')[0]['status'], 'success')

    def test_specstop_when_idle_does_not_block_next_command(self):
        iso = self.make(unit=False)
        self.run_cmds(iso, body('specinitial', dirname='20261101'), body('specstop'),
                      body('getbias', numframe=1, header=HEADER))
        self.assertEqual(self.server.done('specstop')[0]['message'],
                         'Emergency stop (idle): acquisition stopped.')
        self.assertEqual(self.server.done('getbias')[0]['status'], 'success')

    def test_no_unit_and_no_night(self):
        iso = self.make(unit=False)
        self.run_cmds(iso, body('getbias', numframe=1, header=HEADER), body('illuon'),
                      body('specstatus'))
        self.assertIn('specinitial', self.server.done('getbias')[0]['message'])
        self.assertEqual(self.server.done('illuon')[0]['status'], 'fail')
        self.assertEqual(self.server.done('specstatus')[0]['isoplane']['backillum']['state'],
                         'NONE')

    def test_close_leaves_release_frame_only_at_rest(self):
        for cmds, frame in (((body('illuon'), body('illuoff')), RELEASE),
                            ((body('illuon'),), STOP_HOLD)):
            iso = self.make()
            self.run_cmds(iso, *cmds)
            asyncio.run(iso.close())
            last = [l for l in iso.bl.link.log if l.startswith('WDTFRAME ')][-1]
            self.assertEqual(last, 'WDTFRAME ' + frame.hex().upper())

    def test_light_only_commands_keep_the_stage_in(self):
        iso = self.make()
        self.run_cmds(iso, body('specinitial', dirname='20261101'), body('illulighton'),
                      body('illuon'), body('illulightoff'), body('illulighton'),
                      body('illulightoff'), body('getobj', time=5, numframe=1, header=HEADER),
                      body('illuoff'))
        uno = iso.bl.link
        refused, on = self.server.done('illulighton')
        self.assertEqual(refused['status'], 'fail')  # stage OUT: light-only on is refused
        self.assertIn('not IN', refused['message'])
        self.assertEqual((on['status'], on['backillum']['state'], on['backillum']['light']),
                         ('success', 'IN', True))
        for off in self.server.done('illulightoff'):
            self.assertEqual((off['status'], off['backillum']['state'], off['backillum']['light']),
                             ('success', 'IN', False))
        moves = [l for l in uno.log if l.startswith('MB 01100028')]  # speed write before a move
        self.assertEqual(len(moves), 1 + 3)  # illuon: the move; illuoff: move, slow, reset
        self.assertEqual(self.server.done('getobj')[0]['status'], 'fail')  # stage IN
        self.assertEqual(iso.bl.state, 'OUT')
        self.assertFalse(uno.light)

    def test_shutter_open_only_while_the_light_is_on(self):
        class ShutterLog(FakeLightField):
            def __init__(self, fail_open=False, **kw):
                super().__init__(**kw)
                self.history, self.fail_open = [], fail_open

            def set_shutter_open(self, is_open):
                if is_open and self.fail_open:
                    raise RuntimeError("no camera")
                self.history.append(is_open)
                super().set_shutter_open(is_open)

        lf = ShutterLog(time_scale=0.001, shape=(1, 8, 10))
        iso = self.make(lf=lf)
        self.run_cmds(iso, body('specinitial', dirname='20261101'), body('illuon'),
                      body('illulightoff'), body('illulighton'), body('illuoff'))
        self.assertEqual(lf.history, [True, False, True, False])  # the light needs the shutter
        self.assertEqual(lf.status()['shutter'], 'Normal')
        # the shutter is opened first: if that fails, the light stays off
        lf = ShutterLog(fail_open=True, time_scale=0.001, shape=(1, 8, 10))
        self.server = FakeServer()
        iso = self.make(lf=lf)
        self.run_cmds(iso, body('specinitial', dirname='20261101'), body('illuon'), body('illuoff'))
        self.assertEqual(self.server.done('illuon')[0]['status'], 'error')
        self.assertFalse(iso.bl.link.light)
        self.assertEqual(iso.bl.state, 'OUT')

    def test_light_switches_off_after_light_max_on_s(self):
        iso = self.make()
        iso.light_max_on_s = 0.05

        async def go():
            await iso.start()
            await iso.handle(self.server, body('illuon'))
            await iso.handle(self.server, body('specstatus'))
            await asyncio.sleep(0.3)
            await iso.handle(self.server, body('illulighton'))  # re-arms
            await iso.handle(self.server, body('illulightoff'))  # cancels
            await asyncio.sleep(0.3)
            iso.bl._stop_ping.set()
        asyncio.run(go())
        auto = self.server.replies('illulightoff', 'ING')
        self.assertEqual(len(auto), 1)  # only the first light-on timed out
        self.assertIn('switched off after', auto[0]['message'])
        self.assertEqual((auto[0]['backillum']['state'], auto[0]['backillum']['light']),
                         ('IN', False))
        self.assertEqual(len(self.server.done('illulightoff')), 1)  # auto-off is never Done
        self.assertIn('auto_off_in_s', self.server.done('specstatus')[0]['isoplane']['backillum'])
        self.assertEqual(iso.bl.state, 'IN')
        self.assertFalse(iso.bl.link.light)

    def test_exposure_refused_outside_the_configured_camera_mode(self):
        lf = FakeLightField(time_scale=0.001, shape=(1, 8, 10), camera={'adc_speed_mhz': '2'})
        camera = {'adc_speed_mhz': 0.1, 'adc_gain': 'High', 'temp_status': 'Locked'}
        iso = self.make(lf=lf, camera=camera)

        async def go():
            await iso.start()
            await iso.handle(self.server, body('specinitial', dirname='20261101'))
            await iso.handle(self.server, body('getbias', numframe=1, header=HEADER))
            lf.camera.update(adc_speed_mhz='0.1', temp_status='Unlocked')
            await iso.handle(self.server, body('getbias', numframe=1, header=HEADER))
            lf.camera['temp_status'] = 'Locked'
            await iso.handle(self.server, body('specstatus'))
            await iso.handle(self.server, body('getbias', numframe=1, header=HEADER))
            iso.bl._stop_ping.set()
        asyncio.run(go())
        init, = self.server.done('specinitial')
        self.assertEqual(init['status'], 'success')  # loading is allowed; it warns
        self.assertEqual(init['camera_problems'], ['adc_speed_mhz 2 (expected 0.1)'])
        self.assertIn('Setup: experiment fake, grating [500nm,600][0][0] at 430.0 nm, '
                      'ADC 2 MHz High/LowNoise, -55 C Locked.', init['message'])
        speed, lock, ok = self.server.done('getbias')
        self.assertEqual(speed['status'], 'fail')
        self.assertIn('adc_speed_mhz 2 (expected 0.1)', speed['message'])
        self.assertIn('temp_status Unlocked (expected Locked)', lock['message'])
        self.assertEqual(ok['status'], 'success')
        status, = self.server.done('specstatus')
        self.assertEqual(status['isoplane']['camera_problems'], [])
        self.assertIn('ADC 0.1 MHz High/LowNoise', status['message'])
        raw = os.path.join(self.tmp.name, 'raw', '20261101')
        self.assertEqual(len(os.listdir(raw)), 1)  # nothing was exposed when refused

    def test_specinitial_loads_only_configured_experiments(self):
        iso = self.make(experiments=['KSPEC_150_620'])
        self.run_cmds(iso, body('specinitial', dirname='20261101', experiment='KSPEC_600_430'),
                      body('specinitial', dirname='20261101', experiment='KSPEC_150_620'))
        refused, ok = self.server.done('specinitial')
        self.assertEqual(refused['status'], 'fail')
        self.assertIn('not one of the configured setups (KSPEC_150_620)', refused['message'])
        self.assertEqual(ok['status'], 'success')
        self.assertEqual(iso.lf.experiment, 'KSPEC_150_620')

    def test_overscan_rows_are_marked_in_the_header(self):
        # 10 rows read of a 7-row sensor; with sensor_bias_rows=1 the last sensor row is a
        # bias row too (as on the 2026 PIXIS: 1330 read, 1300 sensor, bias rows 1300-1330)
        for overscan, bias_rows, sections in ((3, 0, ('[1:8,1:7]', '[1:8,8:10]')),
                                              (3, 1, ('[1:8,1:6]', '[1:8,7:10]')),
                                              (0, 1, ('[1:8,1:9]', '[1:8,10:10]')),
                                              (0, 0, None)):
            self.server = FakeServer()
            lf = FakeLightField(time_scale=0.001, shape=(1, 10, 8), overscan_rows=overscan)
            iso = self.make(lf=lf, lightfield={'sensor_bias_rows': bias_rows})
            self.run_cmds(iso, body('specinitial', dirname=f'2026110{overscan}{bias_rows}'),
                          body('getbias', numframe=1, header=HEADER))
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                h = fits.getheader(self.server.done('getbias')[0]['filename'])
            got = (h['DATASEC'], h['BIASSEC']) if 'BIASSEC' in h else None
            self.assertEqual(got, sections, (overscan, bias_rows))

    def test_late_exposure_is_stopped_and_fails(self):
        iso = self.make(lf=FakeLightField(time_scale=1000, shape=(1, 8, 10)))
        iso.expose_timeout_s = 0.05  # a 0.01 s exposure that would take 10 s

        async def go():
            await iso.start()
            await iso.handle(self.server, body('specinitial', dirname='20261101'))
            t0 = time.time()
            await iso.handle(self.server, body('getobj', time=0.01, numframe=1, header=HEADER))
            iso.bl._stop_ping.set()
            return time.time() - t0
        elapsed = asyncio.run(go())
        self.assertLess(elapsed, 2.0)
        obj, = self.server.done('getobj')
        self.assertEqual(obj['status'], 'error')
        self.assertIn('did not finish', obj['message'])


class MetrologyLoopTest(unittest.TestCase):
    """script.handle_metrology with the instrument clients replaced by queue fakes."""

    def setUp(self):
        try:
            from script import scriptcli
        except Exception as e:  # redis, pandas, ... exist on the ICS PC
            self.skipTest(f'script.scriptcli cannot be imported here: {e}')
        self.cli = scriptcli

    def run_loop(self, trials, mtl_status='success'):
        cli, sent, trials = self.cli, [], iter(trials)

        async def go():
            q = asyncio.Queue()
            run = SimpleNamespace(ICSclient=None, response_queue=q, lamp_state_callback=None)

            async def spec(cmd, client, header=None):
                sent.append(cmd)
                q.put_nowait({'inst': 'SPEC', 'func': cmd, 'process': 'Done', 'status': 'success'})
                return 1

            async def mtl(cmd, client, logging=None):
                sent.append(cmd)
                q.put_nowait({'inst': 'MTL', 'func': 'mtltrial', 'process': 'ING'})
                q.put_nowait({'inst': 'MTL', 'func': 'mtltrial', 'process': 'Done',
                              'status': mtl_status, 'filename': '/mtl/T_MetrologyTrial_1.json',
                              **next(trials)})

            async def fbp(cmd, client, logging=None):
                sent.append(cmd.split()[0])
                q.put_nowait({'inst': 'FBP', 'func': 'fbpoffset', 'process': 'START'})
                q.put_nowait({'inst': 'FBP', 'func': 'fbpoffset', 'process': 'Done',
                              'status': 'success'})
                return True

            async def lamp(cmd, client, logging=None, state_callback=None):
                sent.append(cmd)

            with patch.object(cli, 'handle_spec', spec), patch.object(cli, 'handle_mtl', mtl), \
                    patch.object(cli, 'handle_fbp', fbp), patch.object(cli, 'handle_lamp', lamp), \
                    patch.object(cli, 'spec_queue', return_value='ISOPLANE'), \
                    patch.object(cli, 'mtl_json_on_ics', side_effect=lambda f: f):
                return await cli.script().handle_metrology(run, None)
        return asyncio.run(go()), sent

    def test_light_only_on_during_trials(self):
        converged, sent = self.run_loop([{'converged': False, 'should_continue': True},
                                         {'converged': True, 'should_continue': False}])
        self.assertTrue(converged)
        self.assertEqual(sent, ['fiducialon', 'illuon', 'mtltrial', 'illulightoff', 'fbpoffset',
                                'illulighton', 'mtltrial', 'illulightoff', 'illuoff',
                                'fiducialoff'])

    def test_failed_trial_still_retracts(self):
        converged, sent = self.run_loop([{}], mtl_status='fail')
        self.assertFalse(converged)
        self.assertEqual(sent, ['fiducialon', 'illuon', 'mtltrial', 'illulightoff', 'illuoff',
                                'fiducialoff'])


class WaitReplyTest(unittest.TestCase):
    def test_skips_progress_and_other_commands(self):
        from Lib.reply import wait_reply

        async def go():
            q = asyncio.Queue()
            for m in ({'inst': 'SPEC', 'func': 'getobj', 'process': 'ING'},
                      {'inst': 'SPEC', 'func': 'specstatus', 'process': 'Done'},
                      {'inst': 'MTL', 'func': 'mtlstatus', 'process': 'Done'},
                      {'inst': 'SPEC', 'func': 'getobj', 'process': 'Done', 'status': 'success'},
                      {'inst': 'SPEC', 'func': 'illuoff', 'process': 'Done'}):
                q.put_nowait(m)
            skipped = []
            got = await wait_reply(q, 'SPEC', 'getobj', timeout=1,
                                   logging=lambda msg, level: skipped.append(level))
            late = await wait_reply(q, 'SPEC', 'getobj', timeout=0.05,
                                    logging=lambda msg, level: skipped.append(level))
            return got, late, skipped
        got, late, skipped = asyncio.run(go())
        self.assertEqual(got['status'], 'success')
        self.assertEqual(late['status'], 'error')  # timed out, after skipping illuoff
        self.assertEqual(skipped, ['warning', 'warning', 'warning', 'error'])


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


class ExistingFrameTest(unittest.TestCase):
    def test_existing_fits_or_spe_refused(self):
        # LightField writes '<name> - (2).fits' instead of failing, so a name on disk is refused
        lf = FakeLightField(time_scale=0.0, shape=(1, 4, 4))
        with tempfile.TemporaryDirectory() as d:
            for ext in ('.fits', '.spe'):
                path = os.path.join(d, 'n_0001_obj' + ext)
                open(path, 'wb').close()
                with self.assertRaises(FileExistsError):
                    lf.expose(0.0, False, d, 'n_0001_obj')
                os.remove(path)
            self.assertTrue(os.path.exists(lf.expose(0.0, False, d, 'n_0001_obj').path))


class SpecCliRoutingTest(unittest.TestCase):
    def test_isoplane_queue_routes_illumination_and_frames(self):
        from SPECTRO import speccli

        client = AsyncMock()
        with patch.object(speccli, 'spec_queue', return_value='ISOPLANE'), \
                patch.object(speccli, 'set_illumination', AsyncMock()) as relay:
            state = asyncio.run(speccli.handle_spec('illuon', client))
            asyncio.run(speccli.handle_spec('getarc 3 2', client, {}))
            asyncio.run(speccli.handle_spec('specinitial 20261101 KSPEC_600_430', client))
            asyncio.run(speccli.handle_spec('specstop', client))
        relay.assert_not_awaited()
        self.assertEqual(state, 1)
        keys = [c.args[0] for c in client.send_message.await_args_list]
        self.assertEqual(keys, ['ISOPLANE'] * 4)
        self.assertEqual(json.loads(client.send_message.await_args_list[3].args[1])['func'],
                         'specstop')
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
