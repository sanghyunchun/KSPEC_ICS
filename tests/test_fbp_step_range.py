"""Range motion uses original, inclusive path steps and sends typed FBP commands."""
import ast
import asyncio
import json
import math
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    selected = [node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in names]
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    exec(compile(module, str(ROOT / path), 'exec'), namespace)
    return namespace


class PathRangeTests(unittest.TestCase):
    def setUp(self):
        self.namespace = load_functions(
            'FBP/kspec_positioner_controller/kspec_0_function.py',
            {'read_json', 'select_motion_steps'},
            {'json': json, 'POSITIONER_AXIS_MAP': {
                'A1': {'alpha': {'global_axis': 1}, 'beta': {'global_axis': 2}},
            }},
        )

    def test_original_files_are_sliced_in_both_directions(self):
        with tempfile.TemporaryDirectory() as directory:
            alpha = Path(directory) / 'alpha.json'
            beta = Path(directory) / 'beta.json'
            alpha.write_text(json.dumps({'step': list(range(1, 61)),
                                         'A1': list(range(1, 61))}))
            beta.write_text(json.dumps({'step': list(range(1, 61)),
                                        'A1': list(range(101, 161))}))
            points, total = self.namespace['read_json'](str(alpha), str(beta))
            backward, backward_steps = self.namespace['select_motion_steps'](
                points, total, 50, 1)
            forward, forward_steps = self.namespace['select_motion_steps'](
                points, total, 2, 40)

            self.assertEqual(backward_steps, list(range(50, 0, -1)))
            self.assertEqual((backward[1][0], backward[1][-1]), (50, 1))
            self.assertEqual((backward[2][0], backward[2][-1]), (150, 101))
            self.assertEqual(forward_steps, list(range(2, 41)))
            self.assertEqual((forward[1][0], forward[1][-1]), (2, 40))
            self.assertEqual(points[1], list(range(1, 61)))

    def test_invalid_step_is_rejected(self):
        select = self.namespace['select_motion_steps']
        for start, end in ((0, 1), (1, 61), (True, 2), ('2', 3)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                select({1: list(range(60))}, 60, start, end)

    def test_range_motion_has_distinct_plc_stop_mode(self):
        writes = []
        namespace = load_functions(
            'FBP/kspec_positioner_controller/kspec_0_function.py',
            {'set_forward_mode_sync'},
            {'MOTION_MODE_FORWARD': 1, 'pyads': SimpleNamespace(PLCTYPE_INT=object())},
        )
        plc = SimpleNamespace(write_by_name=lambda *args: writes.append(args))
        namespace['set_forward_mode_sync']('PLC1', plc, 6)
        self.assertEqual(writes[0][:2], ('GVL.gMotionModeCommand', 6))


class RangeStartPositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_target_requires_current_or_adjacent_path_step(self):
        source = ROOT / 'FBP/kspec_positioner_controller/kspec_main.py'
        tree = ast.parse(source.read_text())
        guard = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                     and any(isinstance(child, ast.Name) and child.id == 'start_tolerance'
                             for child in ast.walk(node)))
        check = ast.AsyncFunctionDef(
            name='check_start',
            args=ast.arguments(posonlyargs=[], args=[], vararg=None, kwonlyargs=[],
                               kw_defaults=[], kwarg=None, defaults=[]),
            body=[guard], decorator_list=[],
        )
        module = ast.fix_missing_locations(ast.Module(body=[check], type_ignores=[]))
        code = compile(module, str(source), 'exec')

        class PLC:
            def __init__(self, position):
                self.position = position
            def read_by_name(self, tag, datatype):
                return self.position

        async def attempt(start, end, position):
            namespace = {
                'selected_steps': [start, end], 'step_from': start, 'step_to': end,
                'original_total_steps': 60, 'original_axis_points': {1: list(range(1, 61))},
                'plc_motion_routes': {'PLC1': [{
                    'plc_name': 'PLC1', 'positioner': 'A1', 'motor': 'alpha',
                    'global_axis': 1, 'local_axis': 1,
                }]},
                'plc_connections': {'PLC1': PLC(position)},
                'asyncio': asyncio, 'math': math,
                'pyads': SimpleNamespace(PLCTYPE_LREAL=object()),
                'save_result_json': Mock(),
            }
            exec(code, namespace)
            return await namespace['check_start']()

        self.assertIsNone(await attempt(2, 40, 1))
        self.assertIsNone(await attempt(50, 1, 51))
        rejected = await attempt(50, 1, 60)
        self.assertEqual(rejected['status'], 'fail')
        self.assertEqual(rejected['data']['accepted_start_steps'], [50, 51])


class CommandRangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fbp_server_uses_loaded_paths_and_reports_final_state(self):
        replies = []
        async def send_reply(server, result=None, **updates):
            replies.append({**(result or {}), **updates})

        rotate_range = AsyncMock(return_value={
            'status': 'success', 'data': {'original_total_steps': 60},
        })
        namespace = load_functions(
            'FBP/command.py', {'_identify_execute'},
            {'json': json, 'loaded_motion_paths': lambda: {
                'alpha_file': 'loaded_alpha.json', 'beta_file': 'loaded_beta.json',
            }, '_locks_ready': True, 'FBP_action': SimpleNamespace(rotate_range=rotate_range),
             'send_fbp_response': send_reply},
        )
        await namespace['_identify_execute'](object(), json.dumps({
            'func': 'fbpmoverange', 'step_from': 50, 'step_to': 1,
        }))

        rotate_range.assert_awaited_once_with(
            alpha_file='loaded_alpha.json', beta_file='loaded_beta.json',
            step_from=50, step_to=1,
        )
        self.assertEqual([reply['process'] for reply in replies], ['START', 'Done'])
        self.assertEqual(replies[-1]['fbp_state'], 'initial')

    async def test_invalid_request_does_not_start_motion(self):
        replies = []
        async def send_reply(server, result=None, **updates):
            replies.append({**(result or {}), **updates})
        rotate_range = AsyncMock()
        namespace = load_functions(
            'FBP/command.py', {'_identify_execute'},
            {'json': json, 'loaded_motion_paths': lambda: {
                'alpha_file': 'a', 'beta_file': 'b',
            }, '_locks_ready': True, 'FBP_action': SimpleNamespace(rotate_range=rotate_range),
             'send_fbp_response': send_reply},
        )
        await namespace['_identify_execute'](object(), json.dumps({
            'func': 'fbpmoverange', 'step_from': 0, 'step_to': 40,
        }))
        rotate_range.assert_not_awaited()
        self.assertEqual(replies[0]['status'], 'fail')


class GuiRangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_move_button_sends_entered_steps(self):
        source = ROOT / 'KSPECRUN_gui_expand.py'
        tree = ast.parse(source.read_text())
        window = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == 'MainWindow')
        method = next(node for node in window.body if isinstance(node, ast.AsyncFunctionDef)
                      and node.name == 'FBP_move_button_clicked')
        method.decorator_list = []
        module = ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
            name='TestWindow', bases=[], keywords=[], body=[method], decorator_list=[],
        )], type_ignores=[]))
        handle = AsyncMock(return_value=True)
        namespace = {'re': re, 'handle_fbp': handle}
        exec(compile(module, str(source), 'exec'), namespace)
        gui = namespace['TestWindow']()
        gui.check_connection = Mock(return_value=True)
        gui.check_syscheck = Mock(return_value=True)
        gui.logging = Mock()
        gui.fbp_state = 'manual'
        gui.ICS_client = object()
        gui.ui = SimpleNamespace(
            lineEdit_step_from=SimpleNamespace(text=lambda: '50'),
            lineEdit_step_to=SimpleNamespace(text=lambda: '1'),
        )
        await gui.FBP_move_button_clicked()
        handle.assert_awaited_once_with(
            'fbpmoverange 50 1', gui.ICS_client, logging=gui.logging,
        )


if __name__ == '__main__':
    unittest.main()
