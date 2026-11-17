import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import aio_pika
import json
import logging
from datetime import datetime, timezone
from FBP.command import *


def _setup_fbp_logger():
    """
    FBP 서버의 모든 print 출력을 콘솔과 로그 파일에 동시에 기록한다.

    - 로그 파일 위치: KSPEC_ICS/FBP/FBPLOG/FBPYYYYMMDD.log
    - 날짜는 UTC 기준 (UT)
    - 서버 실행 중 날짜가 바뀌면 다음 메시지부터 새 파일에 기록된다.
    """
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'FBPLOG')
    os.makedirs(log_dir, exist_ok=True)

    class _DailyFileHandler(logging.Handler):
        """UT 날짜가 바뀔 때마다 새 파일로 전환하는 핸들러."""
        def __init__(self, log_dir):
            super().__init__()
            self.log_dir = log_dir
            self._current_date = None
            self._file = None

        def _get_file(self):
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            if today != self._current_date:
                if self._file:
                    self._file.close()
                log_path = os.path.join(self.log_dir, f'FBP{today}.log')
                self._file = open(log_path, 'a', encoding='utf-8', buffering=1)
                self._current_date = today
            return self._file

        def emit(self, record):
            try:
                msg = self.format(record)
                self._get_file().write(msg + '\n')
            except Exception:
                self.handleError(record)

        def close(self):
            if self._file:
                self._file.close()
            super().close()

    class _TeeStream:
        """print()를 콘솔과 logger에 동시에 보내는 스트림."""
        def __init__(self, original_stream, logger):
            self._original = original_stream
            self._logger = logger
            self._buf = ''

        def write(self, msg):
            self._original.write(msg)
            self._buf += msg
            while '\n' in self._buf:
                line, self._buf = self._buf.split('\n', 1)
                if line:
                    self._logger.info(line)

        def flush(self):
            self._original.flush()

        def isatty(self):
            return getattr(self._original, 'isatty', lambda: False)()

    logger = logging.getLogger('FBP')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # 콘솔 핸들러 (기존 출력 유지)
    console_handler = logging.StreamHandler(sys.__stdout__)
    console_handler.setLevel(logging.DEBUG)

    # 파일 핸들러 (날짜별 자동 전환)
    file_handler = _DailyFileHandler(log_dir)
    file_handler.setLevel(logging.DEBUG)

    # 타임스탬프 포맷 (UTC)
    formatter = logging.Formatter(
        fmt='%(asctime)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S'
    )
    formatter.converter = lambda *args: datetime.now(timezone.utc).timetuple()
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(logging.Formatter('%(message)s'))

    logger.addHandler(file_handler)

    # stdout을 TeeStream으로 교체하여 모든 print가 로그 파일에도 기록됨
    sys.stdout = _TeeStream(sys.__stdout__, logger)

    return log_dir


async def main():
    log_dir = _setup_fbp_logger()

    with open('./Lib/KSPEC.ini','r') as f:
        jdata=json.load(f)

    ip_addr = jdata['RabbitMQ']['ip_addr']
    idname = jdata['RabbitMQ']['idname']
    pwd = jdata['RabbitMQ']['pwd']

    print('FBP Server Started!!!')
    print(f'[FBP] Log directory: {log_dir}')
    FBP_server=AMQclass(ip_addr,idname,pwd,'FBP','ics.ex')  # Check queue name
    await FBP_server.connect()
    lock_result = await initialize_locks()
    print(f"[FBP] Initial lock state: {lock_result['message']}", flush=True)

    async def on_fbp_message(message: aio_pika.IncomingMessage):
        async with message.process():
            func = 'None'
            try:
                dict_data = json.loads(message.body)
                func = dict_data.get('func','None')
                message_text = dict_data['message']
                print('\033[94m' + '[FBP] received: ' + message_text + '\033[0m')

                await identify_execute(FBP_server, message.body)

            except Exception as e:
                comment = f'FBP command failed: {e}'
                print(f"Error in on_fbp_message: {comment}", flush=True)
                reply_data = mkmsg.fbpmsg()
                reply_data.update(
                    func=func,
                    process='Done',
                    status='fail',
                    message=comment,
                )
                try:
                    await FBP_server.send_message('ICS', json.dumps(reply_data))
                except Exception as send_error:
                    print(f"Error sending FBP failure response: {send_error}", flush=True)


        print('Waiting for message from client......')


    await FBP_server.define_consumer('FBP',on_fbp_message)
    print('Waiting for message from client......')
    while True:
        await asyncio.sleep(1)
#        msg=await FBP_server.receive_message("FBP")   # Check queue name
#        dict_data=json.loads(msg)
#        message=dict_data['message']
#        print('\033[94m'+'[FBP] received: ', message+'\033[0m')

#        await identify_execute(FBP_server,msg)

if __name__ == "__main__":
    asyncio.run(main())
