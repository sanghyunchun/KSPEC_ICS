"""Check that PLC activation responses do not interrupt Deploy replies."""
import ast
import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


def gui_method(method_name, namespace=None):
    source = Path(__file__).resolve().parents[1] / 'KSPECRUN_gui.py'
    tree = ast.parse(source.read_text())
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                  and node.name == 'MainWindow')
    handler = next(node for node in window.body if isinstance(node, ast.AsyncFunctionDef)
                   and node.name == method_name)
    handler.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
        name='MessageGUI', bases=[], keywords=[], body=[handler], decorator_list=[],
    )], type_ignores=[]))
    namespace = {'json': json, 'IncomingMessage': object, **(namespace or {})}
    exec(compile(module, str(source), 'exec'), namespace)
    return namespace['MessageGUI']


@asynccontextmanager
async def processed_message():
    yield


class FbpActivateQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.gui = gui_method('on_ics_message')()
        self.gui.response_queue = asyncio.Queue()
        self.gui.set_inst_pos_state = Mock()
        self.gui.show_status = Mock()
        self.gui._log_received_message = Mock()
        self.gui._handle_in_progress_response = AsyncMock(return_value=False)
        self.gui._handle_gfa_guiding_terminal_response = AsyncMock(return_value=False)
        self.gui.logging = Mock()

    async def deliver(self, response):
        message = SimpleNamespace(body=json.dumps(response).encode(), process=processed_message)
        await self.gui.on_ics_message(message)

    async def test_start_and_done_never_enter_deploy_queue(self):
        waiter = asyncio.get_running_loop().create_future()
        self.gui._fbp_activate_waiter = waiter
        await self.deliver(dict(inst='FBP', func='fbpactivate', process='START',
                                status='success', message='Starting'))
        self.assertTrue(self.gui.response_queue.empty())
        self.assertFalse(waiter.done())

        await self.deliver(dict(inst='FBP', func='fbpactivate', process='Done',
                                status='success', message='Ready'))
        self.assertEqual(waiter.result()['message'], 'Ready')
        self.assertTrue(self.gui.response_queue.empty())

        await self.deliver(dict(inst='MTL', func='loadobj', process='Done',
                                status='success', message='Loaded'))
        self.assertEqual((await self.gui.response_queue.get())['func'], 'loadobj')

    async def test_late_activation_reply_does_not_pollute_queue(self):
        self.gui._fbp_activate_waiter = None
        await self.deliver(dict(inst='FBP', func='fbpactivate', process='Done',
                                status='success', message='Ready'))
        self.assertTrue(self.gui.response_queue.empty())

    async def test_deploy_waiter_receives_only_mtl_reply(self):
        from Lib.reply import ReplyRouter, send_and_wait_reply

        self.gui.response_queue = ReplyRouter()

        async def send_loadobj():
            await self.deliver(dict(inst='FBP', func='fbpinitial', process='Done',
                                    status='success', message='Initial complete'))
            await self.deliver(dict(inst='MTL', func='loadobj', process='Done',
                                    status='success', message='Objects loaded'))

        result = await send_and_wait_reply(
            self.gui.response_queue, send_loadobj(), 'MTL', 'loadobj', timeout=1)
        self.assertEqual(result['message'], 'Objects loaded')
        self.assertTrue(self.gui.response_queue.empty())


class SyscheckRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.gui = gui_method('syscheck', {
            'obslog': lambda directory: SimpleNamespace(message='Log ready'),
        })()
        self.gui.msglog_path = None
        self.gui.logging = Mock()
        self.gui.check_connection = Mock(return_value=True)
        self.gui.scriptrun = SimpleNamespace(
            initialize_dependencies=Mock(), obs_initial=AsyncMock(), obslog=None,
        )
        self.gui._activate_fbp_runtime = AsyncMock(return_value=True)
        self.gui.fbp_runtime_initialized = False
        self.gui.dir_name = 'test'
        self.gui.ICS_client = Mock()
        self.gui.send_udp_message = Mock()
        self.gui.send_telcom_command = Mock()
        self.gui.response_queue = asyncio.Queue()
        self.gui.GFA_response_queue = asyncio.Queue()
        self.gui.ADC_response_queue = asyncio.Queue()
        self.gui.SPEC_response_queue = asyncio.Queue()
        self.gui.show_status = Mock()
        status_label = SimpleNamespace(styleSheet=lambda: '')
        self.gui.ui = SimpleNamespace(**{
            name: status_label for name in (
                'label_status_gfa', 'label_status_adc', 'label_status_fiber',
                'label_status_metrology', 'label_status_spectrograph',
                'label_status_lamp',
            )
        })

    async def test_initial_syscheck_activates_runtime(self):
        await self.gui.syscheck()
        self.gui._activate_fbp_runtime.assert_awaited_once_with('Initial Sys check')
        self.assertTrue(self.gui.dependencies)

    async def test_failed_runtime_stops_syscheck(self):
        self.gui._activate_fbp_runtime.return_value = False
        await self.gui.syscheck()
        self.assertFalse(self.gui.dependencies)
        self.assertIsNone(self.gui.scriptrun.obslog)

    async def test_initialized_runtime_is_not_restarted(self):
        self.gui.fbp_runtime_initialized = True
        await self.gui.syscheck()
        self.gui._activate_fbp_runtime.assert_not_awaited()
        self.assertTrue(self.gui.dependencies)


if __name__ == '__main__':
    unittest.main()
