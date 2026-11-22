"""Pattern-fit boresight (GFA.pointing.pattern_centre): the chip centres as one pattern."""
import json
import math
import sys
import types
import unittest
import warnings
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import FITSFixedWarning

sys.modules.setdefault('Lib.AMQ', types.ModuleType('Lib.AMQ'))
import GFA.command as command  # noqa: E402
from GFA.pointing import (  # noqa: E402
    BORESIGHT_GEOMETRY_FILE, focal_to_sky, get_separation, load_gfa_pattern, pattern_centre,
    sky_to_focal,
)

warnings.simplefilter('ignore', FITSFixedWarning)
ROOT = Path(__file__).resolve().parents[1]
NX, NY = 1332, 1152
MAPPING = {"matrix": [[5159.77, -0.01], [-0.02, -5159.76]], "k1": 30.16, "k2": 5355.0, "k3": 0.0}
SERIALS = ("40103651", "40103663", "40103831", "40103833", "40103834")
# chips on a 1.473 deg ring (132.7 mm) at 30 + 60k deg with mounting errors of ~0.1 mm
AZ = np.radians([30, 90, 150, 210, 330])
PAT = {s: (132.7 * math.cos(a) + dx, 132.7 * math.sin(a) + dy)
       for s, a, dx, dy in zip(SERIALS, AZ, [-0.08, 0.09, -0.02, -0.08, 0.09], [0.09, 0.01, -0.10, 0.10, -0.10])}
PATTERN = {"mapping": MAPPING, "cameras": {s: {"x_mm": x, "y_mm": y} for s, (x, y) in PAT.items()}}


def chip_header(ra, dec):
    h = fits.Header()
    h['NAXIS1'], h['NAXIS2'] = NX, NY
    h['CTYPE1'], h['CTYPE2'] = 'RA---TAN', 'DEC--TAN'
    h['CRVAL1'], h['CRVAL2'] = ra, dec
    h['CRPIX1'], h['CRPIX2'] = (NX + 1) / 2, (NY + 1) / 2  # 0-based (NX - 1) / 2: the chip centre
    k = 0.418 / 3600
    h['CD1_1'], h['CD1_2'], h['CD2_1'], h['CD2_2'] = -k, 0.0, 0.0, k
    return h


def headers_for(centre, rot_deg=12.0, scale=1.0003, noise_mm=0.0, seed=0, serials=SERIALS):
    """Chip headers whose centres are the pattern turned, scaled and put at ``centre``."""
    rng = np.random.default_rng(seed)
    c, s_ = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    out = {}
    for s in serials:
        x, y = PAT[s]
        # pattern = a * focal  ->  focal = pattern / a
        z = complex(x, y) / (scale * complex(c, s_)) + complex(*rng.normal(0, noise_mm, 2))
        ra, dec = focal_to_sky(z.real, z.imag, *centre, MAPPING)
        out[s] = chip_header(ra, dec)
    return out


class TestPatternCentre(unittest.TestCase):
    def test_focal_round_trip(self):
        for x, y in ((132.7, 0.0), (-80.0, 100.0), (0.0, 0.0)):
            ra, dec = focal_to_sky(x, y, 150.0, -60.0, MAPPING)
            fx, fy = sky_to_focal(ra, dec, 150.0, -60.0, MAPPING)
            self.assertAlmostEqual(float(fx), x, places=7)
            self.assertAlmostEqual(float(fy), y, places=7)

    def test_recovers_the_centre_with_cameras_missing(self):
        centre = (359.9, -30.0)
        for serials in (SERIALS, SERIALS[1:], SERIALS[:2] + SERIALS[3:4]):
            ra, dec, info = pattern_centre(headers_for(centre, serials=serials), PATTERN)
            self.assertLess(get_separation(ra, dec, *centre), 0.002, serials)
            self.assertLess(info['rms_um'], 0.1)
            self.assertAlmostEqual(info['scale'], 1.0003, places=6)
            self.assertAlmostEqual(info['rot_deg'], 12.0, places=4)

    def test_noise_moves_the_centre_little_when_a_camera_drops(self):
        # 10 um of chip noise: dropping a camera moves the centre by about that (0.4")
        shifts = []
        for seed in range(20):
            h = headers_for((80.0, -45.0), noise_mm=0.01, seed=seed)
            ra5, dec5, info = pattern_centre(h, PATTERN)
            self.assertLess(info['rms_arcsec'], 1.0)
            h.pop(SERIALS[seed % 5])
            ra4, dec4, _ = pattern_centre(h, PATTERN)
            shifts.append(get_separation(ra5, dec5, ra4, dec4))
        self.assertLess(np.sqrt(np.mean(np.square(shifts))), 0.6)

    def test_needs_three_cameras(self):
        with self.assertRaises(ValueError):
            pattern_centre(headers_for((10.0, -20.0), serials=SERIALS[:2]), PATTERN)

    def test_shipped_pattern_loads(self):
        pat = load_gfa_pattern(ROOT / 'GFA' / 'etc' / BORESIGHT_GEOMETRY_FILE)
        self.assertIsNotNone(pat)
        self.assertEqual(sorted(pat['cameras']), sorted(SERIALS))
        for v in pat['cameras'].values():
            self.assertAlmostEqual(math.hypot(v['x_mm'], v['y_mm']), 135.6, delta=0.5)  # design-frame mm

    def test_compute_boresight_uses_the_pattern(self):
        import tempfile
        centre = (200.0, -40.0)
        h = headers_for(centre)
        with tempfile.TemporaryDirectory() as d:
            geo = json.loads((ROOT / 'GFA' / 'etc' / BORESIGHT_GEOMETRY_FILE).read_text())
            geo['pattern'] = dict(PATTERN, enabled=True)
            gp = Path(d) / BORESIGHT_GEOMETRY_FILE
            gp.write_text(json.dumps(geo))
            names = []
            for s, hh in h.items():
                name = f'astro_D20261108_T100000_{s}_exp5s.fits'
                fits.PrimaryHDU(np.zeros((NY, NX), np.uint8), header=hh).writeto(Path(d) / name)
                names.append(name)
            c1 = [hh['CRVAL1'] for hh in h.values()]
            c2 = [hh['CRVAL2'] for hh in h.values()]
            ra, dec, method, info = command.compute_boresight(d, names, c1, c2, str(gp))
            self.assertEqual(method, 'pattern')
            self.assertLess(get_separation(ra, dec, *centre), 0.002)
            self.assertFalse(info['stale'])
            geo['pattern']['enabled'] = False
            gp.write_text(json.dumps(geo))
            _, _, method, _ = command.compute_boresight(d, names, c1, c2, str(gp))
            self.assertEqual(method, 'geometry')


if __name__ == '__main__':
    unittest.main()
