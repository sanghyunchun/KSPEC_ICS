import asyncio

from kspec_0_function import (create_plc_connection, open_one_plc)


async def open_plcs():

    plc_connections = {
        "PLC1": create_plc_connection("PLC1"),
        "PLC2": create_plc_connection("PLC2"),
    }

    await asyncio.gather(
        open_one_plc("PLC1", plc_connections["PLC1"]),
        open_one_plc("PLC2", plc_connections["PLC2"])
    )

    print("PLC1, PLC2 연결 완료")

    return plc_connections