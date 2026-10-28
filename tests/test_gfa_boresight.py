"""Boresight from per-camera GFA geometry, which must work with a camera missing."""
import json
import re
import sys
import types
import unittest
import warnings
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

# GFA.command imports Lib.AMQ (aio_pika); compute_boresight does not use it.
sys.modules.setdefault('Lib.AMQ', types.ModuleType('Lib.AMQ'))
import GFA.calib_boresight as calib  # noqa: E402
import GFA.command as command  # noqa: E402
from GFA.pointing import (  # noqa: E402
    BORESIGHT_GEOMETRY_FILE, _vector_mean, boresight_from_wcs,
    calibrate_boresight_geometry, get_boresight, load_boresight_geometry, ring_centre,
)

warnings.simplefilter('ignore', FITSFixedWarning)

ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = ROOT / 'GFA' / 'etc' / BORESIGHT_GEOMETRY_FILE
# Geometry of the January 2026 installation, kept for the commissioning tests below.
GEOMETRY_JAN = ROOT / 'GFA' / 'etc' / 'boresight_geometry_2026-01.json'
COMMISSIONING = (ROOT / 'GFA' / 'Simul' / 'kspec_gfa_controller' / 'src'
                 / 'kspec_gfa_controller' / 'img' / 'tempfiles')
# solve-field .wcs of three 5-camera sets after the October 2026 reinstall (2026-10-28,
# three fields; camera 40103667 dead)
OCTOBER = ROOT / 'tests' / 'data' / 'gfa_wcs_20261028'
RING_DEG = 1.473
SCALE = 0.418 / 3600.0
NX, NY = 1332, 1152
# Six cameras on the ring (position angle around the boresight) with small mounting
# rotations; each camera's +y axis points at the boresight, as in the commissioning WCS.
CAMERAS = {f'4010{i:04d}': (pa, eps) for i, (pa, eps) in enumerate(
    [(0, 0.3), (60, -0.8), (120, 0.1), (180, 1.2), (240, -0.4), (300, 0.6)])}


def camera_headers(boresight, cameras=CAMERAS, extra_rot=None):
    """WCS headers of the GFA cameras for a given boresight (equatorial mount)."""
    headers = {}
    for serial, (pa, eps) in cameras.items():
        c = boresight.directional_offset_by(pa * u.deg, RING_DEG * u.deg)
        alpha = np.radians(c.position_angle(boresight).deg + eps
                           + (extra_rot or {}).get(serial, 0.0))
        w = WCS(naxis=2)
        w.wcs.ctype = ['RA---TAN', 'DEC--TAN']
        w.wcs.crpix = [(NX + 1) / 2, (NY + 1) / 2]
        w.wcs.crval = [c.ra.deg, c.dec.deg]
        # pixel +y -> sky position angle alpha, east-left (det < 0)
        w.wcs.cd = SCALE * np.array([[-np.cos(alpha), np.sin(alpha)],
                                     [np.sin(alpha), np.cos(alpha)]])
        h = w.to_header()
        h['NAXIS1'], h['NAXIS2'] = NX, NY
        headers[serial] = h
    return headers


class SyntheticBoresightTests(unittest.TestCase):
    def setUp(self):
        self.cal_bore = SkyCoord(87.4 * u.deg, -46.0 * u.deg)
        self.geometry = calibrate_boresight_geometry(camera_headers(self.cal_bore))

    def test_geometry_points_along_camera_y(self):
        for serial, (_, eps) in CAMERAS.items():
            g = self.geometry[serial]
            self.assertAlmostEqual(g['sep_deg'], RING_DEG, places=6)
            self.assertAlmostEqual(g['theta_deg'], 90.0 - eps, delta=0.01)

    def test_five_cameras_other_field(self):
        bore = SkyCoord(250.0 * u.deg, -68.0 * u.deg)
        headers = camera_headers(bore)
        for drop in headers:
            five = {s: h for s, h in headers.items() if s != drop}
            ra, dec, info = boresight_from_wcs(five, self.geometry)
            self.assertLess(bore.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec, 0.1)
            self.assertEqual(len(info['used']), 5)

            # The mean of the five camera centres is off by R/5
            crval = [WCS(h).wcs.crval for h in five.values()]
            ra_n, dec_n = get_boresight([c[0] for c in crval], [c[1] for c in crval])
            off = bore.separation(SkyCoord(ra_n * u.deg, dec_n * u.deg)).arcsec
            self.assertAlmostEqual(off, RING_DEG * 3600 / 5, delta=5)

    def test_badly_solved_camera_is_rejected(self):
        bore = SkyCoord(150.0 * u.deg, -30.0 * u.deg)
        headers = camera_headers(bore, extra_rot={'40100003': 1.0})  # 1 deg -> ~90"
        ra, dec, info = boresight_from_wcs(headers, self.geometry)
        self.assertEqual(info['rejected'], ['40100003'])
        self.assertLess(bore.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec, 0.1)

    def test_too_few_cameras_with_geometry(self):
        headers = camera_headers(self.cal_bore)
        with self.assertRaises(ValueError):
            boresight_from_wcs(headers, {'40100000': self.geometry['40100000']})


def write_wcs_files(tmp, headers, stamp):
    """Header-only files named like solve-field .wcs outputs (IMAGEW/IMAGEH)."""
    paths = []
    for serial, h in headers.items():
        h = h.copy()
        h['IMAGEW'], h['IMAGEH'] = h.pop('NAXIS1'), h.pop('NAXIS2')
        p = Path(tmp) / f'{stamp}_{serial}_exp5s.wcs'
        fits.PrimaryHDU(header=h).writeto(p)
        paths.append(p)
    return paths


class RingCalibrationTests(unittest.TestCase):
    """Calibrating the geometry when not every camera is available."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.five = {s: v for s, v in CAMERAS.items() if s != '40100005'}

    def tearDown(self):
        self._tmp.cleanup()

    def test_ring_centre_from_five_or_three_cameras(self):
        bore = SkyCoord(200.0 * u.deg, -72.0 * u.deg)
        centres = [SkyCoord(*WCS(h).wcs.crval, unit='deg')
                   for h in camera_headers(bore, self.five).values()]
        for subset in (centres, centres[:3]):
            c, radii = ring_centre(subset)
            self.assertLess(bore.separation(c).arcsec, 0.05)
            np.testing.assert_allclose(radii, RING_DEG * 3600, atol=0.05)
        with self.assertRaises(ValueError):
            ring_centre(centres[:2])

    def test_five_camera_calibration_then_add_sixth(self):
        sets = []
        for i, bore in enumerate([SkyCoord(87.4 * u.deg, -46 * u.deg),
                                  SkyCoord(157.0 * u.deg, -37 * u.deg)]):
            sets.append(write_wcs_files(self.tmp, camera_headers(bore, self.five),
                                        f'D20261101_T03{i}000'))
        geometry, _, _ = calib.calibrate(sets, center='ring')
        self.assertEqual(set(geometry), set(self.five))

        bore = SkyCoord(300.0 * u.deg, -65.0 * u.deg)
        headers = camera_headers(bore, self.five)
        for drop in headers:
            ra, dec, _ = boresight_from_wcs(
                {s: h for s, h in headers.items() if s != drop}, geometry)
            self.assertLess(bore.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec, 0.1)

        # The sixth camera comes back: calibrate it alone against the other five
        six = write_wcs_files(self.tmp, camera_headers(SkyCoord(10 * u.deg, -30 * u.deg)),
                              'D20261102_T030000')
        updated, _, _ = calib.calibrate([six], update=geometry, cameras=['40100005'])
        self.assertEqual(set(updated), set(CAMERAS))
        for s in self.five:
            self.assertEqual(updated[s], geometry[s])
        headers = camera_headers(bore)
        ra, dec, _ = boresight_from_wcs({'40100005': headers['40100005']}, updated,
                                        min_cameras=1)
        self.assertLess(bore.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec, 0.1)

    def test_boresight_offset_carries_to_other_fields(self):
        # True boresight 4" east, 3" south of the ring centre (measured by a dither)
        sets = []
        for i, ring in enumerate([SkyCoord(87.4 * u.deg, -46 * u.deg),
                                  SkyCoord(157.0 * u.deg, -37 * u.deg)]):
            sets.append(write_wcs_files(self.tmp, camera_headers(ring, self.five),
                                        f'D20261101_T03{i}000'))
        geometry, _, report = calib.calibrate(sets, center='ring', offset=(4.0, -3.0))
        ring = SkyCoord(300.0 * u.deg, -65.0 * u.deg)
        expected = ring.spherical_offsets_by(4.0 * u.arcsec, -3.0 * u.arcsec)
        ra, dec, _ = boresight_from_wcs(camera_headers(ring, self.five), geometry)
        self.assertLess(expected.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec, 0.1)
        with self.assertRaises(ValueError):
            calib.calibrate(sets[:1], center='radec', boresight=ring, offset=(1.0, 0.0))

    def test_given_boresight(self):
        bore = SkyCoord(87.4 * u.deg, -46 * u.deg)
        files = write_wcs_files(self.tmp, camera_headers(bore, self.five), 'D20261101_T030000')
        offset = bore.spherical_offsets_by(4 * u.arcsec, -3 * u.arcsec)  # measured on sky
        geometry, _, _ = calib.calibrate([files], center='radec', boresight=offset)
        ra, dec, _ = boresight_from_wcs(camera_headers(bore, self.five), geometry)
        self.assertLess(offset.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec, 0.05)
        with self.assertRaises(ValueError):
            calib.calibrate([files, files], center='radec', boresight=offset)


def camera_serials():
    return {c['SerialNumber'] for c in json.loads(
        (ROOT / 'GFA' / 'kspec_gfa_controller' / 'src' / 'kspec_gfa_controller'
         / 'etc' / 'cams.json').read_text()
    )['GfaController']['Elements']['Cameras']['Elements'].values()}


@unittest.skipUnless(COMMISSIONING.is_dir(), 'commissioning solve-field outputs not present')
class CommissioningGeometryTests(unittest.TestCase):
    """The January 2026 geometry on the 2026-01-23/24 solve-field outputs."""

    @staticmethod
    def frame_sets():
        sets = {}
        for f in sorted(COMMISSIONING.glob('*/*.wcs')):
            stamp = re.match(r'(D\d{8}_T\d{5})', f.name).group(1)  # 10 s buckets
            sets.setdefault(stamp, {})[re.search(r'_T\d{6}_(\d+)_', f.name).group(1)] = (
                fits.getheader(f))
        return [s for s in sets.values() if len(s) == 6]

    def test_january_geometry_covers_all_cameras(self):
        geometry = load_boresight_geometry(GEOMETRY_JAN)
        self.assertEqual(set(geometry), camera_serials())

    def test_five_cameras_match_six_camera_centre(self):
        geometry = load_boresight_geometry(GEOMETRY_JAN)
        sets = self.frame_sets()
        self.assertEqual(len(sets), 3)
        for headers in sets:
            bore6 = _vector_mean([SkyCoord(*WCS(h).wcs.crval, unit='deg')
                                  for h in headers.values()])
            for drop in headers:
                five = {s: h for s, h in headers.items() if s != drop}
                ra, dec, _ = boresight_from_wcs(five, geometry)
                sep = bore6.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec
                self.assertLess(sep, 5.0, f'drop {drop}: {sep:.1f}"')

    def test_five_camera_ring_calibration(self):
        """Calibrate without one camera (ring centre), use it on the other nights."""
        files = sorted(COMMISSIONING.glob('*/*.wcs'))
        path_sets = calib.group_frame_sets(files)
        self.assertEqual(len(path_sets), 3)
        for missing in ('40103833', '40103651'):
            for i in range(3):
                cal_sets = [[p for p in s if missing not in p.name]
                            for j, s in enumerate(path_sets) if j != i]
                geometry, _, _ = calib.calibrate(cal_sets, center='ring')
                headers = calib.read_headers([p for p in path_sets[i] if missing not in p.name])
                ring, _ = ring_centre([SkyCoord(*WCS(h).wcs.crval, unit='deg')
                                       for h in headers.values()])
                for drop in headers:
                    ra, dec, _ = boresight_from_wcs(
                        {s: h for s, h in headers.items() if s != drop}, geometry)
                    sep = ring.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec
                    self.assertLess(sep, 5.0, f'missing {missing}, drop {drop}: {sep:.1f}"')


class ComputeBoresightTests(unittest.TestCase):
    def write_frames(self, tmp, headers, stamp='D20261101_T030000'):
        names = []
        for serial, h in headers.items():
            name = f'astro_{stamp}_{serial}_exp5s.fits'
            h = h.copy()
            del h['NAXIS1'], h['NAXIS2']  # set by the data
            fits.writeto(Path(tmp) / name, np.zeros((NY, NX), np.float32), h)
            names.append(name)
        return names

    @staticmethod
    def crvals(headers):
        crval = [WCS(h).wcs.crval for h in headers.values()]
        return [c[0] for c in crval], [c[1] for c in crval]

    def test_missing_geometry_falls_back_to_ring_centre(self):
        bore = SkyCoord(120.0 * u.deg, -50.0 * u.deg)
        five = dict(list(camera_headers(bore).items())[1:])
        cr1, cr2 = self.crvals(five)
        ra, dec, method, info = command.compute_boresight(
            '/nonexistent', ['astro_D20261101_T030000_40100001_exp5s.fits'] * 5, cr1, cr2,
            '/nonexistent/boresight_geometry.json')
        self.assertEqual(method, 'ring')
        self.assertLess(bore.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec, 0.1)

    def test_turned_gfa_plate_is_flagged(self):
        import tempfile
        cal = calibrate_boresight_geometry(camera_headers(SkyCoord(87.4 * u.deg, -46 * u.deg)))
        # cameras reinstalled: the whole GFA plate turned by 0.5 deg
        bore = SkyCoord(30.0 * u.deg, -40.0 * u.deg)
        turned = camera_headers(bore, extra_rot={s: 0.5 for s in CAMERAS})
        five = dict(list(turned.items())[:5])
        with tempfile.TemporaryDirectory() as tmp:
            names = self.write_frames(tmp, five)
            geo = Path(tmp) / BORESIGHT_GEOMETRY_FILE
            geo.write_text(json.dumps({'cameras': cal}))
            cr1, cr2 = self.crvals(five)
            ra, dec, method, info = command.compute_boresight(tmp, names, cr1, cr2, str(geo))
        self.assertEqual(method, 'geometry')
        self.assertTrue(info['stale'])
        self.assertGreater(info['rms_arcsec'], command.RMS_CHECK_ARCSEC)
        # a rigid turn mostly cancels in the mean: R * 0.5 deg / 5 with five cameras
        self.assertLess(bore.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec, 12.0)

    @unittest.skipUnless((ROOT / 'GFA' / 'Simul').is_dir(), 'no commissioning outputs')
    def test_commissioning_five_cameras(self):
        files = sorted((ROOT / 'GFA' / 'Simul' / 'kspec_gfa_controller' / 'src'
                        / 'kspec_gfa_controller' / 'img' / 'tempfiles').glob(
                            'D20260124_T10000*/*.wcs'))
        self.assertEqual(len(files), 6)
        geometry_path = str(GEOMETRY_JAN)
        ra6, dec6, method6, _ = command.compute_boresight(
            '', [str(f) for f in files], [], [], geometry_path)
        ra5, dec5, method5, info5 = command.compute_boresight(
            '', [str(f) for f in files[1:]], [], [], geometry_path)
        self.assertEqual((method6, method5), ('geometry', 'geometry'))
        self.assertEqual(len(info5['used']), 5)
        self.assertFalse(info5['stale'])
        sep = command.get_separation(ra6, dec6, ra5, dec5)
        self.assertLess(sep, 5.0)


@unittest.skipUnless(OCTOBER.is_dir(), 'October 2026 solve-field outputs not present')
class OctoberGeometryTests(unittest.TestCase):
    """The committed geometry on 2026-10-28 frame sets, after the reinstall."""

    @staticmethod
    def frame_sets():
        sets = {}
        for f in sorted(OCTOBER.glob('*.wcs')):
            stamp = re.match(r'(D\d{8}_T\d{6})', f.name).group(1)
            sets.setdefault(stamp, {})[re.search(r'_T\d{6}_(\d+)_', f.name).group(1)] = f
        return sets

    def test_committed_geometry_covers_the_live_cameras(self):
        geometry = load_boresight_geometry(GEOMETRY)
        self.assertLessEqual(set(geometry), camera_serials())
        live = {s for files in self.frame_sets().values() for s in files}
        self.assertLessEqual(live, set(geometry))

    def test_committed_geometry_matches_ring_centre(self):
        geometry = load_boresight_geometry(GEOMETRY)
        sets = self.frame_sets()
        self.assertEqual(len(sets), 3)
        for stamp, files in sets.items():
            headers = {s: fits.getheader(f) for s, f in files.items()}
            ring, _ = ring_centre([SkyCoord(*WCS(h).wcs.crval, unit='deg')
                                   for h in headers.values()])
            ra, dec, info = boresight_from_wcs(headers, geometry)
            self.assertEqual(info['rejected'], [], stamp)
            self.assertLess(info['rms_arcsec'], 5.0, stamp)
            self.assertLess(ring.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec, 3.0, stamp)
            for drop in headers:
                ra, dec, _ = boresight_from_wcs(
                    {s: h for s, h in headers.items() if s != drop}, geometry)
                sep = ring.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec
                self.assertLess(sep, 5.0, f'{stamp} drop {drop}: {sep:.1f}"')

    def test_january_geometry_is_stale_after_the_reinstall(self):
        for stamp, files in self.frame_sets().items():
            paths = [str(f) for f in files.values()]
            _, _, method, info = command.compute_boresight('', paths, [], [], str(GEOMETRY_JAN))
            self.assertEqual(method, 'geometry')
            self.assertTrue(info['stale'], stamp)
            _, _, _, info = command.compute_boresight('', paths, [], [], str(GEOMETRY))
            self.assertFalse(info['stale'], stamp)


if __name__ == '__main__':
    unittest.main()
