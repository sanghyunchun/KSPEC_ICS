import sys
import asyncio
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]  # .../src
sys.path.insert(0, str(SRC))

from kspec_gfa_controller.gfa_actions import GFAActions


async def main():
    actions = GFAActions()
    # res = await actions.pointing(ra="00:00:00", dec="00:00:00")  # 또는 guiding()
    res = actions.ping()
    print(res)


if __name__ == "__main__":
    asyncio.run(main())
