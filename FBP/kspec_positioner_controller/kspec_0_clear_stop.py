import asyncio

from kspec_1_open import open_plcs
from kspec_0_function import clear_stopped_info_all_plcs


async def clear_stop():

    plc_connections = await open_plcs()

    try:
        await clear_stopped_info_all_plcs(
            plc_connections,
            ["PLC1", "PLC2"],
            timeout=2.0
        )

        print("PLC1, PLC2 Stop 기록 삭제 완료")

    finally:
        await asyncio.gather(
            *[
                asyncio.to_thread(plc.close)
                for plc in plc_connections.values()
            ],
            return_exceptions=True
        )


if __name__ == "__main__":
    asyncio.run(clear_stop())