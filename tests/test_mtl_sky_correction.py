"""MTL sky correction at mtlstart: precession (TETE) + instrument rotation offset."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "MTL" / "kspec_metrology"))

from kspec_metrology.analysis import fiber_config as cfg  # noqa: E402
from kspec_metrology.analysis.sky_correction import (  # noqa: E402
    correct_target, corrected_path, precession_rotation_deg, write_corrected_target,
)
from MTL.command import MTLContext, identify_execute  # noqa: E402
from MTL.mtlcli import mtl_start  # noqa: E402

# tile 9140 (2026-10-29): GFA / planner check in proj-kspecdr gives -PA = +0.1648 deg
CENTRE = (86.48438, -25.94448)
TIME = "2026-10-29T12:00:00"


def tile_target(n_out=False):
    """Every fibre 11 mm east of its hole (in reach); optionally two at full extension."""
    ids = cfg.fiber_ids()
    hole = cfg.hole_xy(ids)
    xp, yp = hole[:, 0] + 11.0, hole[:, 1].copy()
    cls = ["2"] * len(ids)
    if n_out:
        a1, a2 = cfg.arm_lengths(False)
        r = np.hypot(hole[:, 0], hole[:, 1])
        for k, c in zip(np.argsort(r)[-2:], ("2", "9")):
            # at full extension along the direction the rotation moves the point: out of reach after
            t = np.array([-hole[k, 1], hole[k, 0]]) / r[k]
            xp[k], yp[k] = hole[k] + (a1[k] + a2[k] - 0.002) * t
            cls[k] = c
    # sky positions of the targets, planner convention (x = +E, y = -N, 5160 mm/rad)
    dec = CENTRE[1] - np.degrees(yp / 5160.0)
    ra = CENTRE[0] + np.degrees(xp / 5160.0) / np.cos(np.radians(CENTRE[1]))
    return {"tile_id": 9140, "project": "ASPECS", "ra": ra.tolist(), "dec": dec.tolist(),
            "xp": xp.tolist(), "yp": yp.tolist(), "class": cls, "zenith_angle": 9.1}


class SkyCorrectionTest(unittest.TestCase):
    def test_precession_rotation_at_tile_9140(self):
        self.assertAlmostEqual(precession_rotation_deg(*CENTRE, TIME), 0.1648, delta=0.002)
        # RA 0h: the ICRS and TETE norths nearly agree
        self.assertLess(abs(precession_rotation_deg(0.0, -20.0, TIME)), 0.01)

    def test_rotation_is_precession_plus_offset_about_the_origin(self):
        t = tile_target()
        out, s = correct_target(t, TIME, precession=True, instrument_offset_deg=0.18,
                                use_measured=False)
        self.assertAlmostEqual(s["rotation_deg"], s["precession_deg"] + 0.18, places=5)
        # the fitted sky rotation is the TETE-north PA term, the scale the ~5e-5 aberration
        self.assertAlmostEqual(s["precession_deg"], precession_rotation_deg(*CENTRE, TIME), delta=2e-3)
        self.assertLess(abs(s["scale"] - 1), 2e-4)
        a, k = np.radians(s["rotation_deg"]), s["scale"]
        x0, y0 = np.array(t["xp"]), np.array(t["yp"])
        np.testing.assert_allclose(out["xp"], k * (np.cos(a) * x0 - np.sin(a) * y0), atol=1e-4)  # 0.1 um
        np.testing.assert_allclose(out["yp"], k * (np.sin(a) * x0 + np.cos(a) * y0), atol=1e-4)
        self.assertEqual(out["xp_planner"], t["xp"])
        self.assertEqual(out["zenith_angle"], 9.1)  # other keys kept
        self.assertEqual(s["clipped"], [])

    def test_time_with_timezone_and_default_now(self):
        # astropy cannot read '+00:00' / 'Z' (datetime.isoformat() output); the server default is now
        t = tile_target()
        ref = correct_target(t, TIME, use_measured=False)[1]
        for time in ("2026-10-29T12:00:00+00:00", "2026-10-29T23:00:00+11:00",
                     "2026-10-29T12:00:00Z", "2026-10-29 12:00:00"):
            s = correct_target(t, time, use_measured=False)[1]
            self.assertEqual(s["time_utc"], "2026-10-29T12:00:00.000")
            self.assertEqual(s["rotation_deg"], ref["rotation_deg"])
        s = correct_target(t, None, use_measured=False)[1]
        self.assertAlmostEqual(s["rotation_deg"], ref["rotation_deg"], delta=0.01)

    def test_options_off(self):
        t = tile_target()
        out, s = correct_target(t, TIME, precession=False, instrument_offset_deg=0.0,
                                use_measured=False)
        self.assertEqual(s["rotation_deg"], 0.0)
        np.testing.assert_allclose(out["xp"], t["xp"], atol=1e-12)
        _, s = correct_target(t, TIME, precession=False, instrument_offset_deg=0.18,
                              use_measured=False)
        self.assertAlmostEqual(s["rotation_deg"], 0.18, places=9)

    def test_corrected_file_is_not_corrected_twice(self):
        t = tile_target()
        once, _ = correct_target(t, TIME, instrument_offset_deg=0.18, use_measured=False)
        twice, _ = correct_target(once, TIME, instrument_offset_deg=0.18, use_measured=False)
        np.testing.assert_allclose(twice["xp"], once["xp"], atol=1e-12)
        self.assertEqual(corrected_path("/a/ASPECS_2627_9140.assign.json"),
                         "/a/ASPECS_2627_9140.assign_skycorr.json")
        self.assertEqual(corrected_path("/a/x_skycorr.json"), "/a/x_skycorr.json")

    def test_out_of_reach_class9_kept_others_clipped(self):
        t = tile_target(n_out=True)
        out, s = correct_target(t, TIME, instrument_offset_deg=0.18, use_measured=False)
        self.assertEqual(len(s["kept_class9"]), 1)
        self.assertEqual([c["class"] for c in s["clipped"]], ["2"])
        k9 = cfg.fiber_ids().index(s["kept_class9"][0])
        self.assertEqual((out["xp"][k9], out["yp"][k9]), (t["xp"][k9], t["yp"][k9]))
        kc = cfg.fiber_ids().index(s["clipped"][0]["fiber"])
        hole = cfg.hole_xy(cfg.fiber_ids())[kc]
        a1, a2 = cfg.arm_lengths(False)
        r = np.hypot(out["xp"][kc] - hole[0], out["yp"][kc] - hole[1])
        self.assertLessEqual(r, a1[kc] + a2[kc])


class SkyCorrectionGuardTest(unittest.TestCase):
    def test_calibration_targets_are_not_corrected(self):
        n = len(cfg.fiber_ids())
        calib = {"tile_id": 1, "project": "Calib", "ra": [0.0] * n, "dec": [0.0] * n,
                 "xp": tile_target()["xp"], "yp": tile_target()["yp"], "class": ["0"] * n,
                 "zenith_angle": 0.0}
        for target in (calib, {"alpha": [0.0] * n, "beta": [0.0] * n}):
            out, s = correct_target(target, TIME, instrument_offset_deg=0.18, use_measured=False)
            self.assertIn("skipped", s)
            self.assertEqual(out, target)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Calib_2627_0001.assign.json"
            path.write_text(json.dumps(calib))
            used, s = write_corrected_target(str(path), time=TIME, instrument_offset_deg=0.18)
            self.assertEqual(used, str(path))
            self.assertFalse(Path(corrected_path(str(path))).exists())

    def test_calib_in_the_name_or_project_is_not_corrected(self):
        t = tile_target()                                  # real sky coordinates
        with tempfile.TemporaryDirectory() as tmp:
            for name, project in (("CALIB_arm_scan.json", "ASPECS"), ("x.json", "Calib")):
                path = Path(tmp) / name
                path.write_text(json.dumps(dict(t, project=project)))
                used, s = write_corrected_target(str(path), time=TIME, instrument_offset_deg=0.18)
                self.assertEqual(used, str(path))
                self.assertTrue(s["skipped"].startswith("calibration target"))
            path = Path(tmp) / "ASPECS_2627_9140.assign.json"
            path.write_text(json.dumps(t))
            used, s = write_corrected_target(str(path), time=TIME, instrument_offset_deg=0.18)
            self.assertNotIn("skipped", s)

    def test_class9_is_not_corrected(self):
        t = tile_target()
        cls = ["9" if k % 3 == 0 else "2" for k in range(len(t["xp"]))]
        t["class"] = cls
        out, s = correct_target(t, TIME, instrument_offset_deg=0.18, use_measured=False)
        for k, c in enumerate(cls):
            moved = (out["xp"][k], out["yp"][k]) != (t["xp"][k], t["yp"][k])
            self.assertEqual(moved, c != "9")
        self.assertEqual(len(s["kept_class9"]), cls.count("9"))

    def test_held_fibres_take_the_last_finite_command(self):
        from kspec_metrology.analysis import mtlcal

        n = len(cfg.fiber_ids())
        with tempfile.TemporaryDirectory() as tmp:
            t0 = np.tile([-100.0, 50.0], n) + np.linspace(0, 1, 2 * n)
            t1 = t0 + 0.5
            t1[0:2] = np.nan                           # fibre 0 held in trial 1
            mtlcal.save_angles(tmp, "9162", 0, t0)
            mtlcal.save_angles(tmp, "9162", 1, t1)
            prev = mtlcal.angle_array(json.loads(Path(mtlcal.json_path(tmp, "9162", 1)).read_text()))
            filled = mtlcal.held_previous(prev, tmp, "9162", 2)
        np.testing.assert_array_equal(filled[0:2], t0[0:2])
        np.testing.assert_array_equal(filled[2:], t1[2:])

    def test_non_finite_result_is_not_written(self):
        t = tile_target()
        with patch("kspec_metrology.analysis.sky_correction.icrs_to_tete_focal",
                   return_value=(float("nan"), float("nan"))):
            with self.assertRaises(ValueError):
                correct_target(t, TIME, use_measured=False)


class MtlStartSkyCorrectionTest(unittest.IsolatedAsyncioTestCase):
    async def run_start(self, config, **message):
        tmp = tempfile.mkdtemp()
        target = Path(tmp) / "ASPECS_2627_9140.assign.json"
        target.write_text(json.dumps(tile_target()))
        msg = json.loads(mtl_start())
        msg.update(target_file=str(target), obs_time=TIME, **message)
        server = SimpleNamespace(send_message=AsyncMock())
        context = MTLContext()
        config = dict(config, mtlfilepath=tmp, mtlimagepath=tmp)
        with patch("MTL.command._load_mtl_config", return_value=config), \
             patch("MTL.command.MetrologyRun") as run_type:
            run = run_type.return_value
            run.start.return_value = str(Path(tmp) / "9140_MetrologyTrial_0.json")
            run.tile, run.itrial, run.max_trial = "9140", 0, 10
            run.nexposure, run.tolerance, run.metric = 1, 10.0, "max"
            await identify_execute(server, json.dumps(msg), context)
        reply = json.loads(server.send_message.call_args.args[1])
        return run_type.call_args.kwargs["target_file"], context, reply, target

    async def test_enabled_writes_and_uses_the_corrected_file(self):
        sc = {"sky_correction": {"enabled": True, "precession": True, "instrument_offset": True,
                                 "instrument_offset_deg": 0.18}}
        used, context, reply, target = await self.run_start(sc)
        self.assertTrue(used.endswith("ASPECS_2627_9140.assign_skycorr.json"))
        self.assertEqual(context.target_file, used)
        corrected = json.loads(Path(used).read_text())
        self.assertAlmostEqual(corrected["sky_correction"]["rotation_deg"], 0.1648 + 0.18, delta=0.002)
        self.assertAlmostEqual(reply["sky_correction"]["instrument_offset_deg"], 0.18)
        self.assertEqual(json.loads(target.read_text())["xp"], tile_target()["xp"])  # input unchanged

    async def test_message_overrides_config(self):
        sc = {"sky_correction": {"enabled": True, "instrument_offset_deg": 0.18}}
        used, _, reply, target = await self.run_start(sc, instrument_offset="false")
        self.assertAlmostEqual(reply["sky_correction"]["rotation_deg"],
                               reply["sky_correction"]["precession_deg"], places=9)
        used, _, reply, target = await self.run_start(sc, sky_correction="false")
        self.assertEqual(used, str(target))
        self.assertIsNone(reply["sky_correction"])

    async def test_off_without_config(self):
        used, _, reply, target = await self.run_start({})
        self.assertEqual(used, str(target))
        self.assertIsNone(reply["sky_correction"])


if __name__ == "__main__":
    unittest.main()
