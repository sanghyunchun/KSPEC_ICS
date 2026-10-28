"""MTL absolute alpha command angles must use the tile path planner's range, not (-180, 180]."""

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "MTL" / "kspec_metrology"))

from kspec_metrology import lab  # noqa: E402
from kspec_metrology.analysis import fiber_config as cfg  # noqa: E402
from kspec_metrology.analysis.mtlcal import _flatten_angles  # noqa: E402


class CommandAngleTest(unittest.TestCase):
    def setUp(self):
        sign, zero = cfg.ANGLE_SIGN, cfg.ANGLE_ZERO
        cfg.ANGLE_SIGN, cfg.ANGLE_ZERO = (-1., -1.), (-30., -150.)
        self.addCleanup(setattr, cfg, "ANGLE_SIGN", sign)
        self.addCleanup(setattr, cfg, "ANGLE_ZERO", zero)

    def test_absolute_alpha_keeps_planner_range(self):
        # geometric alpha 250 deg is command -220 on the tile path, not 140
        geometric = np.radians([0., 30., 200., 250., 359.])
        np.testing.assert_allclose(cfg.command_alpha(geometric), [30., 0., -170., -220., -329.], atol=1e-9)

        angles = _flatten_angles(geometric, np.radians([150.] * 5))
        np.testing.assert_allclose(angles[0::2], [30., 0., -170., -220., -329.], atol=1e-9)
        np.testing.assert_allclose(angles[1::2], 0., atol=1e-12)

    def test_rotation_takes_the_short_way(self):
        rotation = _flatten_angles(np.radians([-2., 179., 181.]), np.zeros(3), absolute=False)
        np.testing.assert_allclose(rotation[0::2], [2., -179., 179.])

    def test_lab_xy2ab_round_trip(self):
        alpha, beta = np.array([-220., -10., 25.]), np.array([40., 90., 120.])
        x, y = lab.ab2xy(0., 0., alpha, beta, 5.2, 11.6)
        alpha_back, beta_back = lab.xy2ab(0., 0., x, y, 5.2, 11.6)
        np.testing.assert_allclose(alpha_back, alpha, atol=1e-6)
        np.testing.assert_allclose(beta_back, beta, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
