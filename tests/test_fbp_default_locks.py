import ast
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import Lib.mkmessage as mkmsg
from FBP.lock_policy import load_default_locks, normalize_positioners


def command_namespace(action, defaults):
    source = Path(__file__).resolve().parents[1] / 'FBP' / 'command.py'
    tree = ast.parse(source.read_text())
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    namespace = {'asyncio': asyncio, 'json': json, 'os': os, 'Path': Path,
                 'mkmsg': mkmsg, 'FBP_action': action,
                 'load_default_locks': Mock(return_value=(defaults, {'A1', 'A2', 'A3'})),
                 'normalize_positioners': normalize_positioners}
    exec(compile(tree, str(source), 'exec'), namespace)
    return namespace


class Server:
    def __init__(self):
        self.replies = []

    async def send_message(self, routing_key, message):
        self.replies.append(json.loads(message))


class DefaultLockTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.action = SimpleNamespace(
            check_plcs_ready=AsyncMock(return_value={'status': 'success'}),
            positioner_lock=AsyncMock(return_value={'status': 'success', 'message': 'Locked', 'data': {}}),
            activate_and_play_all_plcs=AsyncMock(return_value={
                'status': 'success', 'message': 'Runtime ready', 'data': {'plcs': {}}}),
        )
        self.command = command_namespace(self.action, {'A1'})
        self.server = Server()

    async def send(self, func, **kwargs):
        await self.command['identify_execute'](
            self.server, json.dumps({'func': func, 'message': func, **kwargs}))
        return self.server.replies[-1]

    async def test_default_and_additional_locks(self):
        self.assertEqual((await self.command['initialize_locks']())['status'], 'success')
        self.action.positioner_lock.assert_awaited_with(['A1'])

        response = await self.send('fbplock', positioners='A2')
        self.assertEqual(response['data']['default_locks'], ['A1'])
        self.assertEqual(response['data']['extra_locks'], ['A2'])
        self.action.positioner_lock.assert_awaited_with(['A1', 'A2'])

        response = await self.send('fbplock', positioners='')
        self.assertEqual(response['data']['extra_locks'], [])
        self.action.positioner_lock.assert_awaited_with(['A1'])

    async def test_activation_reapplies_temporary_locks(self):
        await self.command['initialize_locks']()
        await self.send('fbplock', positioners='A2')
        response = await self.send('fbpactivate')
        self.assertEqual(response['status'], 'success')
        self.assertEqual(response['data']['locks']['locked_positioners'], ['A1', 'A2'])
        self.action.positioner_lock.assert_awaited_with(['A1', 'A2'])

    async def test_failed_initialization_blocks_motion(self):
        self.action.check_plcs_ready.return_value = {'status': 'error', 'message': 'Not ready'}
        self.assertEqual((await self.command['initialize_locks']())['status'], 'error')
        response = await self.send('fbpmoveone')
        self.assertEqual(response['status'], 'fail')
        self.assertIn('not verified', response['message'])

    async def test_invalid_extra_does_not_change_locks(self):
        await self.command['initialize_locks']()
        self.action.positioner_lock.reset_mock()
        response = await self.send('fbplock', positioners='BAD')
        self.assertEqual(response['status'], 'fail')
        self.action.positioner_lock.assert_not_awaited()

    async def test_failed_reapply_blocks_motion(self):
        await self.command['initialize_locks']()
        self.action.positioner_lock.return_value = {'status': 'error', 'message': 'PLC write failed'}
        response = await self.send('fbpactivate')
        self.assertEqual(response['status'], 'error')
        self.assertIn('default locks failed', response['message'])
        self.assertEqual((await self.send('fbpmoveone'))['status'], 'fail')

    async def test_invalid_default_file_blocks_activation_and_motion(self):
        await self.command['initialize_locks']()
        self.command['load_default_locks'].side_effect = ValueError('Unknown ID')
        response = await self.send('fbpactivate')
        self.assertEqual(response['status'], 'error')
        self.action.activate_and_play_all_plcs.assert_not_awaited()
        self.assertEqual((await self.send('fbpmoveone'))['status'], 'fail')


class DefaultLockFileTests(unittest.TestCase):
    def test_load_and_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            default_path = Path(directory) / 'defaults.json'
            axis_map_path = Path(directory) / 'axes.json'
            axis_map_path.write_text(json.dumps({'A1': {}, 'A2': {}}))
            default_path.write_text(json.dumps({'positioners': ['a1', 'A1']}))
            self.assertEqual(load_default_locks(default_path, axis_map_path),
                             ({'A1'}, {'A1', 'A2'}))
            default_path.write_text(json.dumps({'positioners': ['BAD']}))
            with self.assertRaises(ValueError):
                load_default_locks(default_path, axis_map_path)
            default_path.write_text(json.dumps({'positioners': []}))
            with self.assertRaises(ValueError):
                load_default_locks(default_path, axis_map_path)


if __name__ == '__main__':
    unittest.main()
