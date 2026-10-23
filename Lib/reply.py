import asyncio


async def wait_reply(queue, inst, func, timeout=None, logging=None):
    """Wait for the Done reply of `func` from `inst` on the shared response queue.

    The ICS pairs replies with commands by their order, so one stray Done (a status query sent
    from the GUI meanwhile, a late reply) would shift every later wait by one. Progress replies
    and Done replies of other commands are skipped. Servers that leave `func` unset (the SPEC
    simulation) are matched on `inst` alone. On timeout a Done reply with status error is
    returned, so a silent server stops the caller instead of hanging it.
    """
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
