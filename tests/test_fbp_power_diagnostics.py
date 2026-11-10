"""Power ON timeout reports the PLC state of axes that remain unpowered."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "FBP" / "kspec_positioner_controller"))

from kspec_0_function import wait_for_powered_axes  # noqa: E402


class FakePLC:
    def __init__(self, values, failed_tags=()):
        self.values = values
        self.failed_tags = set(failed_tags)

    def read_by_name(self, tag, data_type):
        if tag in self.failed_tags:
            raise RuntimeError(f"Cannot read {tag}")
        return self.values[tag]


class PowerDiagnosticsTest(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_reports_only_unpowered_axis_and_its_state(self):
        plc1 = FakePLC({
            "GVL.gSystemReady": True,
            "GVL.gAxisCmd[1].Power": True,
            "GVL.gAxisState[1].Powered": True,
            "GVL.gAxisState[1].Error": False,
            "GVL.gAxisState[1].Busy": False,
        })
        plc2 = FakePLC({
            "GVL.gSystemReady": False,
            "GVL.gAxisCmd[2].Power": True,
            "GVL.gAxisState[2].Powered": False,
            "GVL.gAxisState[2].Error": True,
            "GVL.gAxisState[2].Busy": False,
        })
        targets = [
            ("PLC1", {"global_axis": 1, "local_axis": 1,
                      "positioner": "A1", "motor": "alpha"}),
            ("PLC2", {"global_axis": 78, "local_axis": 2,
                      "positioner": "B1", "motor": "beta"}),
        ]

        failed = await wait_for_powered_axes(
            {"PLC1": plc1, "PLC2": plc2}, targets, timeout=0
        )

        self.assertEqual(failed, [{
            "plc_name": "PLC2", "global_axis": 78, "local_axis": 2,
            "positioner": "B1", "motor": "beta", "system_ready": False,
            "power_command": True, "powered": False, "axis_error": True,
            "busy": False,
        }])

    async def test_failed_ads_reads_are_included_in_diagnostics(self):
        tag = "GVL.gAxisState[1].Powered"
        plc = FakePLC({
            "GVL.gSystemReady": True,
            "GVL.gAxisCmd[1].Power": True,
            "GVL.gAxisState[1].Error": False,
            "GVL.gAxisState[1].Busy": False,
        }, failed_tags={tag})
        target = ("PLC1", {"global_axis": 1, "local_axis": 1,
                           "positioner": "A1", "motor": "alpha"})

        failed = await wait_for_powered_axes({"PLC1": plc}, [target], timeout=0)

        self.assertEqual(failed[0]["powered"], None)
        self.assertIn("powered", failed[0]["read_errors"])
        self.assertEqual(failed[0]["power_command"], True)


if __name__ == "__main__":
    unittest.main()
