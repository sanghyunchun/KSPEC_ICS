import asyncio

from kspec_1_open import open_plcs
from kspec_stop import stop_all_positioner


async def stop_run():

    plc_connections = await open_plcs()

    await stop_all_positioner(plc_connections)


if __name__ == "__main__":
    asyncio.run(stop_run())