import asyncio
from contextlib import suppress
import random
import json

class GfaLoopTest():
    async def start_loop(self):
        self._check_task = asyncio.create_task(self._check_loop())
        return self
            
    async def stop_loop(self):
        print('stopstopstop')
        if hasattr(self, '_check_task'):
            await self.cancel_task(self._check_task)

    async def _check_loop(self):
        while True:
            print("Loop is running...")
            await asyncio.sleep(1)  # Asynchronous wait to prevent blocking

    async def cancel_task(self, task: asyncio.Future):
        """Safely cancels a task."""
        if task is None or task.done():
            return

        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

async def autoguide():
	num=random.randrange(1,11)
	comment='Autoguiding now.......'
	dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','comments': comment}
	rsp=json.dumps(dict_data)
	return rsp


async def main():
    cl = await GfaLoopTest().start_loop()  # 루프 시작
    await asyncio.sleep(5)  # 루프가 5초 동안 실행되도록 대기
    await cl.stop_loop()  # 루프 종료

if __name__ == "__main__":
    asyncio.run(main())
