import asyncio

from kspec_zero_position import zero_main
from kspec_0_function import clear_one_plc_motion_flags



async def zero_and_close(plc_connections):
    """
    순서:
        1. zero_main(plc_connections) 실행
        2. 모든 0도 이동 대상 축이 정상적으로 0도 도착했는지 확인
        3. 성공한 경우에만 모션 플래그 초기화
        4. PLC1 / PLC2 연결 종료

    zero_main()이 실패하면 PLC 연결은 종료하지 않는다.
    """

    print("전체 포지셔너 0도 이동 시작")

    # ========================================================
    # 0도 이동
    # ========================================================
    result = await zero_main(plc_connections)


    if result.get("status") != "success":
        print(
            "0도 이동이 정상 완료되지 않아 "
            "PLC 연결을 종료하지 않습니다."
        )

        return result

    print("전체 포지셔너 0도 이동 완료")

    # ========================================================
    # PLC 종료 전 모션 플래그 초기화
    # ========================================================
    plc_names = ["PLC1", "PLC2"]
    
    await asyncio.gather(
        *[
            clear_one_plc_motion_flags(
                plc_name,
                plc_connections[plc_name]
            )
            for plc_name in plc_names
        ],
        return_exceptions=True
    )
    
    # ========================================================
    # PLC1 / PLC2 연결 종료
    # ========================================================
    close_results = await asyncio.gather(
        *[
            asyncio.to_thread(
                plc_connections[plc_name].close
            )
            for plc_name in plc_names
        ],
        return_exceptions=True
    )

    failed_close_plcs = {
        plc_name: str(close_result)
        for plc_name, close_result in zip(
            plc_names,
            close_results
        )
        if isinstance(close_result, Exception)
    }

    if failed_close_plcs:
        close_result = {
            "status": "error",
            "message": (
                "0도 이동은 정상 완료되었지만 "
                "일부 PLC 연결 종료에 실패했습니다."
            ),
            "data": {
                "zero_result": result,
                "failed_close_plcs": failed_close_plcs,
            }
        }

        print(close_result["message"])
        return close_result

    print("PLC1, PLC2 연결 종료 완료")
    print("오늘 K-SPEC 구동 종료")

    return {
        "status": "success",
        "message": (
            "전체 포지셔너 0도 이동 후 "
            "PLC1, PLC2 연결을 정상 종료했습니다."
        ),
        "data": {
            "zero_result": result,
            "closed_plcs": plc_names,
        }
    }