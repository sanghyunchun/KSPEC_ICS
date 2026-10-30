import asyncio


class ReplyRouter(asyncio.Queue):
    """Deliver Done replies to the command that registered before sending it.

    Unclaimed replies have already been logged by the GUI and are not retained.
    The Queue base lets existing queue-clearing code keep working.
    """

    def __init__(self):
        super().__init__()
        self._waiters = []

    def expect(self, inst, func, *, match=None):
        future = asyncio.get_running_loop().create_future()
        waiter = (inst, func, match or {}, future)
        self._waiters.append(waiter)
        return waiter

    def cancel_expectation(self, waiter):
        if waiter in self._waiters:
            self._waiters.remove(waiter)
        if not waiter[3].done():
            waiter[3].cancel()

    def put_nowait(self, reply):
        if isinstance(reply, dict) and reply.get('process') == 'Done':
            for waiter in self._waiters:
                inst, func, match, future = waiter
                if (reply.get('inst') == inst
                        and reply.get('func', 'None') in (func, None, 'None')
                        and all(reply.get(key) == value for key, value in match.items())):
                    self._waiters.remove(waiter)
                    future.set_result(reply)
                    return
        # The GUI has already displayed this reply; no command is waiting for it.


async def send_and_wait_reply(queue, send, inst, func, timeout=None, logging=None, *, match=None):
    """Register the reply destination before sending to avoid a fast-reply race."""
    if not isinstance(queue, ReplyRouter):
        await send
        return await wait_reply(queue, inst, func, timeout=timeout, logging=logging)

    waiter = queue.expect(inst, func, match=match)
    try:
        await send
        try:
            return await asyncio.wait_for(waiter[3], timeout=timeout)
        except asyncio.TimeoutError:
            msg = f'No reply from {inst} to {func} within {timeout:g} s.'
            _log(logging, msg, 'error')
            return {'inst': inst, 'func': func, 'process': 'Done',
                    'status': 'error', 'message': msg}
    finally:
        queue.cancel_expectation(waiter)


async def wait_reply(queue, inst, func, timeout=None, logging=None):
    """Wait for a Done reply, retaining the old asyncio.Queue fallback.

    With ReplyRouter, prefer send_and_wait_reply so registration precedes sending.
    Plain asyncio.Queue callers still skip unrelated replies. A silent server
    returns an error response after the timeout.
    """
    if isinstance(queue, ReplyRouter):
        waiter = queue.expect(inst, func)
        try:
            try:
                return await asyncio.wait_for(waiter[3], timeout=timeout)
            except asyncio.TimeoutError:
                msg = f'No reply from {inst} to {func} within {timeout:g} s.'
                _log(logging, msg, 'error')
                return {'inst': inst, 'func': func, 'process': 'Done',
                        'status': 'error', 'message': msg}
        finally:
            queue.cancel_expectation(waiter)

    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout
    while True:
        left = None if deadline is None else max(0.0, deadline - loop.time())
        try:
            rsp = await asyncio.wait_for(queue.get(), timeout=left)
        except asyncio.TimeoutError:
            msg = f'No reply from {inst} to {func} within {timeout:g} s.'
            _log(logging, msg, 'error')
            return {'inst': inst, 'func': func, 'process': 'Done', 'status': 'error', 'message': msg}
        if not isinstance(rsp, dict) or rsp.get('process') != 'Done':
            continue
        if rsp.get('inst') == inst and rsp.get('func', 'None') in (func, None, 'None'):
            return rsp
        _log(logging, f"Skipped a reply while waiting for {inst} {func}: "
             f"{rsp.get('inst')} {rsp.get('func')}: {rsp.get('message')}", 'warning')


def _log(logging, message, level):
    if logging is not None:
        logging(message, level=level)
    else:
        print(f'[ICS] {message}', flush=True)
