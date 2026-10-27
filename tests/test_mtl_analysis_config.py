"""MTL analysis settings must match the values validated in the kspec_metrology notebooks."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "MTL" / "kspec_metrology"))

from MTL.command import ANALYSIS_DEFAULTS, FINDER_OPTS, MTLContext, identify_execute  # noqa: E402
from MTL.mtlcli import _parse_mtlcal, mtl_cal, mtl_start  # noqa: E402

CONFIG = {"mtlfilepath": "/tmp/mtl-target", "mtlimagepath": "/tmp/mtl-data"}


class MTLAnalysisConfigTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_passes_notebook_analysis_settings(self):
        server = SimpleNamespace(send_message=AsyncMock())
        context = MTLContext()
        with patch("MTL.command._load_mtl_config", return_value=CONFIG), \
             patch("MTL.command.MetrologyRun") as run_type:
            run = run_type.return_value
            run.start.return_value = "/tmp/mtl-target/Trial_0.json"
            run.tile, run.itrial, run.max_trial = "verify", 0, 5
            run.nexposure, run.tolerance, run.metric = 1, 10.0, "max"
            await identify_execute(server, mtl_start(), context)

        settings = run_type.call_args.kwargs
        for key, value in ANALYSIS_DEFAULTS.items():
            self.assertEqual(settings[key], value, key)
        self.assertEqual(settings["finder_opts"], FINDER_OPTS)
        self.assertIsNone(settings["magnification"])          # package default (commissioning fit)
        self.assertIsNone(settings["use_measured_positioners"])  # package default (off for now)
        self.assertEqual(settings["fid_exptime"], [1.0, 10.0])
        reply = json.loads(server.send_message.call_args.args[1])
        self.assertEqual(reply["status"], "success")
        self.assertIn("kspec_metrology", reply["package"])
        self.assertAlmostEqual(reply["magnification_default"], -8.86, places=1)

    async def test_start_message_can_override_analysis_settings(self):
        server = SimpleNamespace(send_message=AsyncMock())
        message = json.loads(mtl_start())
        message.update(min_dist=40, model="radial+affine", magnification=8.4, threshold="2000",
                       use_measured_positioners="true")
        with patch("MTL.command._load_mtl_config", return_value=CONFIG), \
             patch("MTL.command.MetrologyRun") as run_type:
            run = run_type.return_value
            run.start.return_value = "/tmp/mtl-target/Trial_0.json"
            run.tile, run.itrial, run.max_trial = "verify", 0, 5
            run.nexposure, run.tolerance, run.metric = 1, 10.0, "max"
            await identify_execute(server, json.dumps(message), MTLContext())
        settings = run_type.call_args.kwargs
        self.assertEqual((settings["min_dist"], settings["model"], settings["magnification"], settings["threshold"]),
                         (40, "radial+affine", 8.4, 2000.0))
        self.assertIs(settings["use_measured_positioners"], True)

    async def test_cal_passes_fid_heads_and_analysis_settings(self):
        server = SimpleNamespace(send_message=AsyncMock())
        message = mtl_cal(head="tile_MetrologyTrial_1_",
                          fid_head=["tile_MetrologyTrial_1_fid0_", "tile_MetrologyTrial_1_fid1_"],
                          target_file="/tmp/object.info", json_dir="/tmp/json", target_name="tile", itrial=1)
        zeros = np.zeros(3)
        with patch("MTL.command._load_mtl_config", return_value=CONFIG), \
             patch("MTL.command.analyze_images", return_value=(zeros, zeros, zeros, zeros)) as analyze:
            await identify_execute(server, message, MTLContext())
        options = analyze.call_args.kwargs
        self.assertEqual(options["fid_head"], ["tile_MetrologyTrial_1_fid0_", "tile_MetrologyTrial_1_fid1_"])
        for key, value in ANALYSIS_DEFAULTS.items():
            self.assertEqual(options[key], value, key)
        self.assertEqual(options["finder_opts"], FINDER_OPTS)
        reply = json.loads(server.send_message.call_args.args[1])
        self.assertEqual(reply["status"], "success")

    def test_cli_parses_fid_heads(self):
        options = _parse_mtlcal(["--head", "t_1_", "--fid_head", "t_1_fid0_", "t_1_fid1_", "--itrial", "2"])
        self.assertEqual(options["fid_head"], ["t_1_fid0_", "t_1_fid1_"])
        self.assertEqual(options["threshold"], ANALYSIS_DEFAULTS["threshold"])
        self.assertIsNone(_parse_mtlcal(["--head", "t_1_"])["fid_head"])


if __name__ == "__main__":
    unittest.main()
