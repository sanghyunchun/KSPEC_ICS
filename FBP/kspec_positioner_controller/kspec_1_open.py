import asyncio

from kspec_0_function import (create_plc_connection, open_one_plc)


async def open_plcs():
    # [PLC1 단독 모드] PLC2 EtherCAT 불안정으로 PLC1만 사용합니다.
    # PLC2를 다시 활성화하려면 아래 주석을 해제하고 PLC1 단독 블록을 주석 처리하세요.

    # [PLC2 비활성화됨]
    # plc_connections = {
    #     "PLC1": create_plc_connection("PLC1"),
    #     "PLC2": create_plc_connection("PLC2"),
    # }
    # await asyncio.gather(
    #     open_one_plc("PLC1", plc_connections["PLC1"]),
    #     open_one_plc("PLC2", plc_connections["PLC2"])
    # )
    # print("PLC1, PLC2 연결 완료")

    # [PLC1 단독 활성화]
    plc_connections = {
        "PLC1": create_plc_connection("PLC1"),
        "PLC2": create_plc_connection("PLC2"),  # 연결 객체는 생성하되 오픈하지 않음
    }

    await open_one_plc("PLC1", plc_connections["PLC1"])

    print("PLC1 단독 연결 완료 (PLC2 비활성화)")

    return plc_connections