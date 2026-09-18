import asyncio

#PLC 연결
from kspec_1_open import open_plcs

#모든 축 0도로 보낸다음 연결 종료
from kspec_4_close import zero_and_close

from kspec_main import main
from kspec_reverse import reverse_main
from kspec_reverse_from_stop_step import reverse_from_stop_step

#부가 기동
from kspec_0_function import (
    rotate_one,
    positioner_lock,
    show_status,
    show_status_all,
)

###############################################################
###############################################################
async def run():

    plc_connections = await open_plcs()

    # # main
    # await main(plc_connections)

    # # reverse_main()
    # await reverse_main(plc_connections)

    # # reverse_from_stop_step()
    # await reverse_from_stop_step(plc_connections)


###############################################################
###############################################################
    #kspec_rotate_one()
#    await rotate_one(plc_connections, positioner="H4", motor="beta", angle=0 )

#     #kspec_lock()
#    await positioner_lock(plc_connections ,[])

#     #kspec_show_status()
    # await show_status(plc_connections, "O5")

#     #kspec_show_status_all
    # await show_status_all(plc_connections)


# ###############################################################
# ###############################################################
#     # zero_position_and_plc_close
#     # 실험 마지막에만 사용

#    await zero_and_close(plc_connections)









if __name__ == "__main__":
    asyncio.run(run())
