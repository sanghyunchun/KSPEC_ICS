"""Regression tests for the reference-guided fiducial path used in later MTL trials."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "MTL" / "kspec_metrology"))

from kspec_metrology import naming  # noqa: E402
from kspec_metrology.analysis import mtlcal  # noqa: E402


class FiducialReferenceTest(unittest.TestCase):
    def test_missing_reference_position_is_not_queried(self):
        reference = np.column_stack((np.arange(30, dtype=float), np.zeros(30)))
        reference[0] = np.nan
        observed = reference[1:].copy()
        peaks = (None, observed[:, 0], observed[:, 1],
                 np.ones(len(observed)), np.zeros(len(observed), dtype=int))

        with patch.object(mtlcal, "findpeak", return_value=peaks):
            x, y, choice = mtlcal.measure_fiducials_ref(
                ["fid"], np.zeros(30), np.zeros(30), reference, ".", 1, 10)

        self.assertTrue(np.isnan(x[0]) and np.isnan(y[0]))
        self.assertEqual(choice[0], -1)
        np.testing.assert_allclose(x[1:], observed[:, 0])
        np.testing.assert_allclose(y[1:], observed[:, 1])

    def test_saving_first_reference_creates_output_directory(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "new_output"
            measured = np.arange(30, dtype=float)
            mtlcal.save_fid_ref(output, "tile", 1, measured, measured)

            trial = np.load(naming.fid_path(output, "tile", 1))
            shared = np.load(naming.fid_ref_path(output))
            np.testing.assert_array_equal(trial, np.column_stack((measured, measured)))
            np.testing.assert_array_equal(shared, trial)


if __name__ == "__main__":
    unittest.main()
