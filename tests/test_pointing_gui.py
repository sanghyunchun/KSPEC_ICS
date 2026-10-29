"""Pointing coordinate modes without a GUI or TCS connection."""
import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from GFA.pointing import apply_offsets, dec_deg_to_dms, ra_deg_to_hms, radec_str_to_deg


def pointing_gui_class():
    source = Path(__file__).resolve().parents[1] / 'KSPECRUN_gui.py'
    window = next(n for n in ast.parse(source.read_text()).body
                  if isinstance(n, ast.ClassDef) and n.name == 'MainWindow')
    methods = []
    for node in window.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name in {
            '_handle_gfa_point_response', 'pointing_button_clicked',
        }:
            node.decorator_list = []
            methods.append(node)
    cls = ast.ClassDef(name='PointingGUI', bases=[], keywords=[], body=methods,
                       decorator_list=[])
    namespace = dict(json=json, radec_str_to_deg=radec_str_to_deg,
                     apply_offsets=apply_offsets, ra_deg_to_hms=ra_deg_to_hms,
                     dec_deg_to_dms=dec_deg_to_dms,
                     bytes_to_sexagesimal=lambda reply: {
                         b'RA': '00:58:48.000', b'DEC': '+00:00:00.00',
                     }[reply])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                 str(source), 'exec'), namespace)
    return namespace['PointingGUI']


class PointingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.gui = pointing_gui_class()()
        self.gui.delta_ra = self.gui.delta_dec = None
        self.gui.new_ra = self.gui.new_dec = None
        self.gui.logging = Mock()
        self.gui.send_telcom_command = AsyncMock(side_effect=[b'RA', b'DEC'])
        self.gui.send_udp_message = AsyncMock()
        self.gui.response_queue = SimpleNamespace(put=AsyncMock())
        self.gui.ui = SimpleNamespace(**{
            key: Mock() for key in ('lineEdit_offset', 'lineEdit_raoffset', 'lineEdit_decoffset')
        })

    async def receive_offset(self):
        # Target 14.5 deg, boresight 15.3 deg; offset is -0.8 deg.
        await self.gui._handle_gfa_point_response({
            'sepsec': 2880, 'dra': -2880, 'ddec': 0,
            'new_ra': '00:54:48.000', 'new_dec': '+00:00:00.00',
        }, 'success')

    def assert_sent_ra(self, expected):
        command = self.gui.send_udp_message.await_args.args[0]
        self.assertTrue(command.startswith('KSPEC>TC tmradec '))
        _, _, ra, dec = command.split()
        actual, _ = radec_str_to_deg(ra, dec)
        self.assertAlmostEqual(actual, expected, places=5)

    async def test_true_uses_tcs_position(self):
        await self.receive_offset()
        with patch.object(json, 'load', return_value={'GFA': {'pointing_use_tcs_coordinates': True}}):
            await self.gui.pointing_button_clicked()
        self.assert_sent_ra(13.9)
        self.assertEqual(self.gui.send_telcom_command.await_count, 2)

    async def test_false_uses_target_position(self):
        await self.receive_offset()
        with patch.object(json, 'load', return_value={'GFA': {'pointing_use_tcs_coordinates': False}}):
            await self.gui.pointing_button_clicked()
        self.assert_sent_ra(13.7)
        self.gui.send_telcom_command.assert_not_awaited()

    async def test_missing_setting_defaults_to_true(self):
        await self.receive_offset()
        with patch.object(json, 'load', return_value={'GFA': {}}):
            await self.gui.pointing_button_clicked()
        self.assert_sent_ra(13.9)

    async def test_tcs_error_does_not_slew(self):
        await self.receive_offset()
        self.gui.send_telcom_command.side_effect = RuntimeError('getra failed')
        with patch.object(json, 'load', return_value={'GFA': {'pointing_use_tcs_coordinates': True}}):
            await self.gui.pointing_button_clicked()
        self.gui.send_udp_message.assert_not_awaited()

    async def test_missing_offset_does_not_slew(self):
        await self.gui.pointing_button_clicked()
        self.gui.send_telcom_command.assert_not_awaited()
        self.gui.send_udp_message.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
