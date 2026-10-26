"""Check GUI IsoPlane command parsing and RabbitMQ message shape."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from SPECTRO_ISOPLANE.specisocli import handle_speciso, make_speciso_command


class IsoPlaneCliTests(unittest.TestCase):
    def test_supported_commands_have_server_fields(self):
        cases = {
            "specstatus": {},
            "specstop": {},
            "illuon": {},
            "illuoff": {},
            "illulighton": {},
            "illulightoff": {},
            "specinitial 20261026 setup_A": {"dirname": "20261026", "experiment": "setup_A"},
            "getbias 3": {"numframe": 3, "header": {}},
            "getdark 30 2": {"time": 30.0, "numframe": 2, "header": {}},
            "getflat 2.5 4": {"time": 2.5, "numframe": 4, "header": {}},
            "getarc 1 1": {"time": 1.0, "numframe": 1, "header": {}},
            "getobj 60 2": {"time": 60.0, "numframe": 2, "header": {}},
        }
        for command, fields in cases.items():
            with self.subTest(command=command):
                data = json.loads(make_speciso_command(command))
                self.assertEqual(data["inst"], "SPEC")
                self.assertEqual(data["func"], command.split()[0])
                for key, value in fields.items():
                    self.assertEqual(data[key], value)

    def test_invalid_arguments_are_not_sent(self):
        client = AsyncMock()
        for command in ("getbias 0", "getflat nan 2", "getarc 2 1.5",
                        "illuon extra", "specinitial", "getobj 1"):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    asyncio.run(handle_speciso(command, client))
        client.send_message.assert_not_awaited()

    def test_send_uses_isoplane_routing_key(self):
        client = AsyncMock()
        asyncio.run(handle_speciso("getbias 2", client))
        routing_key, message = client.send_message.await_args.args
        self.assertEqual(routing_key, "ISOPLANE")
        self.assertEqual(json.loads(message)["numframe"], 2)


if __name__ == "__main__":
    unittest.main()
