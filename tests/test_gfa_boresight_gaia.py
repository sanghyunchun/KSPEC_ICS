"""Refit (Gaia) chip solutions use their own boresight geometry ("cameras_gaia")."""
import json
import sys
import types
import unittest
from pathlib import Path

from astropy.io import fits

sys.modules.setdefault('Lib.AMQ', types.ModuleType('Lib.AMQ'))
from GFA.pointing import (  # noqa: E402
    BORESIGHT_GEOMETRY_FILE, geometry_for_headers, load_boresight_geometry,
    load_boresight_geometry_gaia,
)

GEOMETRY = Path(__file__).resolve().parents[1] / 'GFA' / 'etc' / BORESIGHT_GEOMETRY_FILE


class GaiaGeometryTests(unittest.TestCase):
    def test_shipped_file_has_both_calibrations_for_the_same_cameras(self):
        sip = load_boresight_geometry(GEOMETRY)
        gaia = load_boresight_geometry_gaia(GEOMETRY)
        self.assertEqual(set(sip), set(gaia))
        for s in sip:
            self.assertLess(abs(sip[s]['sep_deg'] - gaia[s]['sep_deg']) * 3600, 0.1)
            self.assertLess(abs(sip[s]['theta_deg'] - gaia[s]['theta_deg']), 0.01)

    def test_refit_frames_take_the_gaia_entry(self):
        geom = {'a': {'sep_deg': 1.0, 'theta_deg': 90.0}, 'b': {'sep_deg': 1.0, 'theta_deg': 90.0}}
        gaia = {'a': {'sep_deg': 1.0, 'theta_deg': 90.5}, 'b': {'sep_deg': 1.0, 'theta_deg': 90.5}}
        refit, plain = fits.Header(), fits.Header()
        refit['GFAREFIT'] = True
        out = geometry_for_headers({'a': refit, 'b': plain, 'c': refit}, geom, gaia)
        self.assertEqual(out['a']['theta_deg'], 90.5)
        self.assertEqual(out['b']['theta_deg'], 90.0)
        self.assertNotIn('c', out)  # no geometry at all for that camera

    def test_without_gaia_calibration_everything_uses_the_old_one(self):
        geom = {'a': {'sep_deg': 1.0, 'theta_deg': 90.0}}
        refit = fits.Header()
        refit['GFAREFIT'] = True
        self.assertEqual(geometry_for_headers({'a': refit}, geom, {}), geom)
        self.assertEqual(geometry_for_headers({'a': refit}, geom, None), geom)

    def test_file_without_the_key(self):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump({'cameras': {}}, f)
        self.assertEqual(load_boresight_geometry_gaia(f.name), {})


if __name__ == '__main__':
    unittest.main()
