from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from FBP.kspec_positioner_controller import position_action


async def main() -> int:
    """
    position_action.rotate_all()을 직접 실행한다.

    RabbitMQ나 GUI를 거치지 않고 같은 컴퓨터에서 전체 포지셔너 정방향
    구동을 실행하기 위한 수동 실행 스크립트이다.
    """
    result = await position_action.rotate_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("rotate_all 실행이 사용자에 의해 중단되었습니다.")
        raise SystemExit(130)
