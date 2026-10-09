"""Exercise GUI pointing logic without opening a GUI or contacting hardware."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from GFA.pointing import (
    apply_offsets, dec_deg_to_dms, ra_deg_to_hms, radec_str_to_deg,
)


def gui_pointing_class(loop):
    source = Path(__file__).resolve().parents[1] / 'KSPECRUN_gui.py'
    tree = ast.parse(source.read_text())
    window = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                  and n.name == 'MainWindow')
    methods = []
    for node in window.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            '_handle_gfa_point_response', 'pointing_button_clicked', 'send_udp_message',
        }:
            node.decorator_list = []
            methods.append(node)
    cls = ast.ClassDef(name='PointingGUI', bases=[], keywords=[], body=methods,
                       decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = dict(
        asyncio=SimpleNamespace(get_running_loop=lambda: loop),
        UDPClientProtocol=Mock(), radec_str_to_deg=radec_str_to_deg,
        apply_offsets=apply_offsets, ra_deg_to_hms=ra_deg_to_hms,
        dec_deg_to_dms=dec_deg_to_dms,
    )
    exec(compile(module, str(source), 'exec'), namespace)
    return namespace['PointingGUI']


class PointingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.transport = Mock()
        loop = SimpleNamespace(
            create_future=Mock(),
            create_datagram_endpoint=AsyncMock(return_value=(self.transport, Mock())),
        )
        self.gui = gui_pointing_class(loop)()
        self.gui.ra, self.gui.dec = '10:00:00.000', '+00:00:00.00'
        self.gui._pointing_command_coordinates = None
        self.gui._pointing_command_target = None
        self.gui.tcsagentIP, self.gui.tcsagentPort = '127.0.0.1', 0
        self.gui.logging = Mock()
        self.gui.response_queue = SimpleNamespace(put=AsyncMock())
        self.gui.ui = SimpleNamespace(**{
            name: Mock() for name in ('lineEdit_offset', 'lineEdit_raoffset',
                                     'lineEdit_decoffset')
        })

    async def calculate(self, dra, ddec=0):
        # Server new_ra/new_dec still use the Tile center. The GUI must use
        # measured residuals and its last transmitted command instead.
        await self.gui._handle_gfa_point_response(dict(
            sepsec=abs(dra), dra=dra, ddec=ddec,
            new_ra=self.gui.ra, new_dec=self.gui.dec,
        ), 'success')

    def assert_command_offset(self, ra_arcsec, dec_arcsec=0):
        ra, dec = radec_str_to_deg(self.gui.new_ra, self.gui.new_dec)
        # RA commands round to 0.001 time seconds (0.015 arcsec);
        # DEC commands round to 0.01 arcsec.
        self.assertAlmostEqual((ra - 150) * 3600, ra_arcsec, delta=0.008)
        self.assertAlmostEqual(dec * 3600, dec_arcsec, delta=0.006)

    async def test_repeated_corrections_preserve_previous_command(self):
        target = (self.gui.ra, self.gui.dec)
        await self.calculate(30, -12)
        self.assert_command_offset(30, -12)
        await self.gui.pointing_button_clicked()
        first_command = self.gui._pointing_command_coordinates
        await self.calculate(2, 1)
        self.assert_command_offset(32, -11)
        await self.gui.pointing_button_clicked()
        await self.calculate(0, 0)
        self.assert_command_offset(32, -11)
        self.assertEqual((self.gui.ra, self.gui.dec), target)
        self.assertNotEqual(self.gui._pointing_command_coordinates, first_command)
        self.assertEqual(self.transport.sendto.call_count, 2)

    async def test_calculation_without_pointing_does_not_accumulate(self):
        await self.calculate(30)
        await self.calculate(30)
        self.assert_command_offset(30)
        self.assertIsNone(self.gui._pointing_command_coordinates)
        self.transport.sendto.assert_not_called()

    async def test_changed_target_uses_new_tile_center(self):
        await self.calculate(30)
        await self.gui.pointing_button_clicked()
        self.gui.ra = '11:00:00.000'
        await self.calculate(3)
        ra, _ = radec_str_to_deg(self.gui.new_ra, self.gui.new_dec)
        self.assertAlmostEqual((ra - 165) * 3600, 3, places=2)

    async def test_new_slew_replaces_previous_correction(self):
        await self.calculate(30)
        await self.gui.pointing_button_clicked()
        await self.gui.send_udp_message(
            f'KSPEC>TC tmradec {self.gui.ra} {self.gui.dec}'
        )
        await self.calculate(2)
        self.assert_command_offset(2)


if __name__ == '__main__':
    unittest.main()
