"""Keep GUI and MTL exposure units aligned with the observing setup."""

import ast
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "MTL" / "kspec_metrology"))

from MTL.command import MTLContext, identify_execute  # noqa: E402
from MTL.mtlcli import mtl_set, mtl_start  # noqa: E402


class MTLExposureConfigTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_uses_30_ms_fiber_and_two_fiducial_frames(self):
        message = mtl_start()
        self.assertEqual(json.loads(message)["time"], 30_000.0)  # wire: microseconds

        server = SimpleNamespace(send_message=AsyncMock())
        context = MTLContext()
        config = {"mtlfilepath": "/tmp/mtl-target", "mtlimagepath": "/tmp/mtl-data"}
        with patch("MTL.command._load_mtl_config", return_value=config), \
             patch("MTL.command.MetrologyRun") as run_type:
            run = run_type.return_value
            run.start.return_value = "/tmp/mtl-target/Trial_0.json"
            run.tile, run.itrial, run.max_trial = "verify", 0, 5
            run.nexposure, run.tolerance, run.metric = 1, 10.0, "max"
            await identify_execute(server, message, context)

        settings = run_type.call_args.kwargs
        self.assertEqual(settings["exptime"], 30.0)  # camera: milliseconds
        self.assertEqual(settings["fid_exptime"], [1.0, 10.0])
        self.assertEqual(settings["nexposure"], 1)
        self.assertIs(context.run, run_type.return_value)
        reply = json.loads(server.send_message.call_args.args[1])
        self.assertEqual((reply["func"], reply["status"]), ("mtlstart", "success"))

    def test_empty_gui_exposure_fields_use_30_ms_and_one_frame(self):
        source = ROOT / "KSPECRUN_gui.py"
        tree = ast.parse(source.read_text())
        window = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                      and n.name == "MainWindow")
        method = next(n for n in window.body if isinstance(n, ast.FunctionDef)
                      and n.name == "_mtl_exposure_inputs")
        cls = ast.ClassDef(name="Window", bases=[], keywords=[], body=[method],
                           decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
        namespace = {"mtl_set": mtl_set}
        exec(compile(module, str(source), "exec"), namespace)

        gui = namespace["Window"]()
        exptime = Mock()
        exptime.text.return_value = ""
        count = Mock()
        count.text.return_value = ""
        gui.ui = SimpleNamespace(lineEdit_MTL_exptime=exptime,
                                 lineEdit_MTL_expnum=count)
        self.assertEqual(gui._mtl_exposure_inputs(), (0.03, 1))
        exptime.setText.assert_called_once_with("0.03")
        count.setText.assert_called_once_with("1")


if __name__ == "__main__":
    unittest.main()
