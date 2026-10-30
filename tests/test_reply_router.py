"""Reply routing when independent instruments answer during Deploy."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from Lib.reply import ReplyRouter, send_and_wait_reply


class ReplyRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_obs_initial_routes_adc_replies_by_command(self):
        from script.scriptcli import script

        replies = ReplyRouter()
        run = SimpleNamespace(
            response_queue=replies,
            GFA_response_queue=asyncio.Queue(),
            ADC_response_queue=asyncio.Queue(),
            SPEC_response_queue=asyncio.Queue(),
            ICSclient=object(),
        )
        sent = []

        async def handle_adc(command, client, logging=None):
            sent.append(command)
            replies.put_nowait(dict(inst='FBP', func='fbpstatus', process='Done'))
            replies.put_nowait(dict(inst='ADC', func=command.split()[0],
                                     process='Done', status='success'))

        async def no_sleep(_):
            pass

        with patch('script.scriptcli.handle_adc', handle_adc), \
                patch('script.scriptcli.asyncio.sleep', no_sleep):
            await asyncio.wait_for(script().obs_initial(run, None), timeout=1)

        self.assertEqual(sent, ['adcconnect', 'adchome 1', 'adczero 4'])
        self.assertEqual(replies._waiters, [])

    async def test_unclaimed_fbp_reply_does_not_interrupt_mtl(self):
        replies = ReplyRouter()
        replies.put_nowait(dict(inst='FBP', func='fbpinitial', process='Done'))

        async def send():
            # A reply may arrive before the AMQP send coroutine returns.
            replies.put_nowait(dict(inst='FBP', func='fbpstatus', process='Done'))
            replies.put_nowait(dict(inst='MTL', func='loadobj', process='Done',
                                    status='success'))

        result = await send_and_wait_reply(replies, send(), 'MTL', 'loadobj', timeout=1)
        self.assertEqual(result['status'], 'success')
        self.assertTrue(replies.empty())
        self.assertEqual(replies._waiters, [])

    async def test_concurrent_commands_receive_only_their_own_reply(self):
        replies = ReplyRouter()
        both_sent = asyncio.Event()
        sent_count = 0

        async def send():
            nonlocal sent_count
            sent_count += 1
            if sent_count == 2:
                both_sent.set()
            await both_sent.wait()

        mtl = asyncio.create_task(send_and_wait_reply(
            replies, send(), 'MTL', 'mtltrial', timeout=1))
        fbp = asyncio.create_task(send_and_wait_reply(
            replies, send(), 'FBP', 'fbpoffset', timeout=1))
        await both_sent.wait()
        replies.put_nowait(dict(inst='FBP', func='fbpoffset', process='Done',
                                message='FBP finished'))
        replies.put_nowait(dict(inst='MTL', func='mtltrial', process='Done',
                                message='MTL finished'))
        self.assertEqual((await mtl)['message'], 'MTL finished')
        self.assertEqual((await fbp)['message'], 'FBP finished')

    async def test_loadmotion_arms_are_distinguished(self):
        replies = ReplyRouter()

        async def send():
            replies.put_nowait(dict(inst='FBP', func='loadmotion', arm='alpha',
                                    process='Done'))
            replies.put_nowait(dict(inst='FBP', func='loadmotion', arm='beta',
                                    process='Done'))

        result = await send_and_wait_reply(
            replies, send(), 'FBP', 'loadmotion', timeout=1,
            match={'arm': 'beta'})
        self.assertEqual(result['arm'], 'beta')

    async def test_timeout_and_send_error_remove_waiter(self):
        replies = ReplyRouter()

        async def no_reply():
            return None

        result = await send_and_wait_reply(
            replies, no_reply(), 'MTL', 'loadobj', timeout=0.01)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(replies._waiters, [])

        async def send_error():
            raise OSError('send failed')

        with self.assertRaises(OSError):
            await send_and_wait_reply(
                replies, send_error(), 'MTL', 'loadobj', timeout=1)
        self.assertEqual(replies._waiters, [])
