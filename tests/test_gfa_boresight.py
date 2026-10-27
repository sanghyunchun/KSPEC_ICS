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
import GFA.command as command  # noqa: E402
from GFA.pointing import (
    BORESIGHT_GEOMETRY_FILE, _vector_mean, boresight_from_wcs,
    calibrate_boresight_geometry, get_boresight, load_boresight_geometry,
)

warnings.simplefilter('ignore', FITSFixedWarning)

ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = ROOT / 'GFA' / 'etc' / BORESIGHT_GEOMETRY_FILE
COMMISSIONING = (ROOT / 'GFA' / 'Simul' / 'kspec_gfa_controller' / 'src'
                 / 'kspec_gfa_controller' / 'img' / 'tempfiles')
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


@unittest.skipUnless(COMMISSIONING.is_dir(), 'commissioning solve-field outputs not present')
class CommissioningGeometryTests(unittest.TestCase):
    """The committed geometry on the 2026-01-23/24 solve-field outputs."""

    @staticmethod
    def frame_sets():
        sets = {}
        for f in sorted(COMMISSIONING.glob('*/*.wcs')):
            stamp = re.match(r'(D\d{8}_T\d{5})', f.name).group(1)  # 10 s buckets
            sets.setdefault(stamp, {})[re.search(r'_T\d{6}_(\d+)_', f.name).group(1)] = (
                fits.getheader(f))
        return [s for s in sets.values() if len(s) == 6]

    def test_committed_geometry_covers_all_cameras(self):
        geometry = load_boresight_geometry(GEOMETRY)
        serials = {c['SerialNumber'] for c in json.loads(
            (ROOT / 'GFA' / 'kspec_gfa_controller' / 'src' / 'kspec_gfa_controller'
             / 'etc' / 'cams.json').read_text()
        )['GfaController']['Elements']['Cameras']['Elements'].values()}
        self.assertEqual(set(geometry), serials)

    def test_five_cameras_match_six_camera_centre(self):
        geometry = load_boresight_geometry(GEOMETRY)
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


class ComputeBoresightTests(unittest.TestCase):
    def test_missing_geometry_falls_back_to_crval_mean(self):
        ra, dec, method, info = command.compute_boresight(
            '/nonexistent', ['astro_x.fits'] * 6, [10.0] * 6, [-30.0] * 6,
            '/nonexistent/boresight_geometry.json')
        self.assertEqual(method, 'crval_mean')
        self.assertAlmostEqual(dec, -30.0)
        self.assertEqual(info, {})

    @unittest.skipUnless((ROOT / 'GFA' / 'Simul').is_dir(), 'no commissioning outputs')
    def test_commissioning_five_cameras(self):
        files = sorted((ROOT / 'GFA' / 'Simul' / 'kspec_gfa_controller' / 'src'
                        / 'kspec_gfa_controller' / 'img' / 'tempfiles').glob(
                            'D20260124_T10000*/*.wcs'))
        self.assertEqual(len(files), 6)
        geometry_path = str(ROOT / 'GFA' / 'etc' / command.BORESIGHT_GEOMETRY_FILE)
        ra6, dec6, method6, _ = command.compute_boresight(
            '', [str(f) for f in files], [], [], geometry_path)
        ra5, dec5, method5, info5 = command.compute_boresight(
            '', [str(f) for f in files[1:]], [], [], geometry_path)
        self.assertEqual((method6, method5), ('geometry', 'geometry'))
        self.assertEqual(len(info5['used']), 5)
        sep = command.get_separation(ra6, dec6, ra5, dec5)
        self.assertLess(sep, 5.0)


if __name__ == '__main__':
    unittest.main()
