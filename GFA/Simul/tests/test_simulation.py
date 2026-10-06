from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from GFA.Simul.simulated_camera import SimulatedCameraController
from GFA.Simul.simulation import create_simulated_actions


class _ResponseServer:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    async def send_message(self, destination: str, payload: str) -> None:
        self.messages.append((destination, json.loads(payload)))


class SimulatedCameraControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_grab_and_close(self) -> None:
        import logging

        controller = SimulatedCameraController(logging.getLogger("test.simulated-camera"))
        await controller.open_all_cameras()
        result = await controller.grabone(CamNum=1, ExpTime=0.1, Binning=4)

        self.assertFalse(result["timeout"])
        self.assertEqual(result["serial"], "SIM0001")
        self.assertEqual(result["image"].ndim, 2)

        await controller.close_all_cameras()
        self.assertFalse(any(controller.status().values()))


class SimulationCommandFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_and_grab_use_production_command_and_actions(self) -> None:
        # Import after the simulation factory installs the pypylon import shim.
        actions_root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(actions_root))
        actions = create_simulated_actions(save_root=actions_root)

        from GFA.command import identify_execute

        server = _ResponseServer()
        await identify_execute(
            server,
            actions,
            json.dumps({"func": "gfastatus", "message": "status"}),
        )
        status = server.messages[-1][1]
        self.assertEqual(status["status"], "success")
        self.assertEqual(set(status["message"]), {"Cam1", "Cam2", "Cam3", "Cam4", "Cam5", "Cam6"})

        await identify_execute(
            server,
            actions,
            json.dumps(
                {
                    "func": "gfagrab",
                    "message": "grab simulated camera",
                    "CamNum": 1,
                    "ExpTime": 0.1,
                    "ExpNum": 1,
                }
            ),
        )
        grab = server.messages[-1][1]
        self.assertEqual(grab["status"], "success")
        self.assertEqual(len(grab["grab_files"]), 1)
        self.assertTrue(Path(grab["grab_files"][0]).is_file())

    async def test_invalid_command_is_rejected_without_hardware(self) -> None:
        actions = create_simulated_actions(save_root=Path(tempfile.mkdtemp()))
        self.addCleanup(lambda: __import__("shutil").rmtree(actions.env.save_root))

        from GFA.command import identify_execute

        server = _ResponseServer()
        await identify_execute(
            server,
            actions,
            json.dumps(
                {
                    "func": "gfagrab",
                    "message": "bad grab",
                    "CamNum": 1,
                    "ExpTime": "not-a-number",
                    "ExpNum": 1,
                }
            ),
        )
        response = server.messages[-1][1]
        self.assertEqual(response["status"], "error")
        self.assertIn("ExpTime", response["message"])

    async def test_guiding_and_pointing_complete_with_simulated_products(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root))
        actions = create_simulated_actions(save_root=root)

        guiding = await actions.guiding(ExpTime=0.1, ExpNum=1, SaveGrabRaw=False)
        pointing = await actions.pointing(
            ra="00:00:00",
            dec="+00:00:00",
            ExpTime=0.1,
            ExpNum=1,
            SaveGrabRaw=False,
        )

        self.assertEqual(guiding["status"], "success")
        self.assertEqual(pointing["status"], "success")
        self.assertEqual(len(pointing["images"]), 6)


if __name__ == "__main__":
    unittest.main()
