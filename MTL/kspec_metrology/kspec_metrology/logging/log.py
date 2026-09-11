# import logging

# _loggers = dict()
# def get_logger(level='INFO', path=None, timestamps=False):
        
#     if level == 'DEBUG':
#         loglevel = logging.DEBUG
#     elif level == 'INFO':
#         loglevel = logging.INFO
#     elif level == 'WARN' or level == 'WARNING':
#         loglevel = logging.WARNING
#     elif level == 'ERROR':
#         loglevel = logging.ERROR
#     elif level == 'FATAL' or level == 'CRITICAL':
#         loglevel = logging.CRITICAL
#     else:
#         raise ValueError('Unknown log level {}; should be DEBUG/INFO/WARNING/ERROR/CRITICAL'.format(level))
        
#     logger = logging.getLogger()
#     logger.setLevel(loglevel)

#     ch = logging.StreamHandler()
#     ch.setLevel(loglevel)

#     # optionally create file handler, similarly
#     if path:
#         fh = logging.FileHandler(filename=path, mode='a', encoding='utf-8')
#         fh.setLevel(loglevel)
#     else:
#         fh = None

#     # create formatter
#     kwargs = {'fmt': '%(levelname)s:%(filename)s:%(lineno)s:%(funcName)s:%(message)s'}
#     if timestamps:
#         kwargs['fmt'] = '%(asctime)s:' + kwargs['fmt']
#         kwargs['datefmt'] = '%Y%m%dT%H%M%S%z'
#     formatter = logging.Formatter(**kwargs)

#     # add formatter to ch
#     ch.setFormatter(formatter)
#     if fh:
#         fh.setFormatter(formatter)

#     # add handlers to logger
#     logger.addHandler(ch)
#     if fh:
#         logger.addHandler(fh)
    
#     _loggers[level] = logger

#     return _loggers[level]

import logging

_loggers = {}

def get_logger(name="app", level="INFO", path=None, timestamps=False):
    # level 문자열 -> logging 상수
    level_u = level.upper()
    if level_u == "DEBUG":
        loglevel = logging.DEBUG
    elif level_u == "INFO":
        loglevel = logging.INFO
    elif level_u in ("WARN", "WARNING"):
        loglevel = logging.WARNING
    elif level_u == "ERROR":
        loglevel = logging.ERROR
    elif level_u in ("FATAL", "CRITICAL"):
        loglevel = logging.CRITICAL
    else:
        raise ValueError(f"Unknown log level {level}")

    key = (name, loglevel, path, timestamps)
    if key in _loggers:
        return _loggers[key]

    # ✅ root logger가 아니라 이름 있는 logger 사용
    logger = logging.getLogger(name)
    logger.setLevel(loglevel)

    # ✅ root로 전파되며 2번 찍히는 것 방지
    logger.propagate = False

    # ✅ (노트북/재호출 대비) 기존 핸들러가 있으면 제거
    #    - 같은 logger에 또 addHandler 되는 걸 막음
    if logger.handlers:
        logger.handlers.clear()

    # formatter
    fmt = "%(levelname)s:%(filename)s:%(lineno)d:%(funcName)s:%(message)s"
    if timestamps:
        fmt = "%(asctime)s:" + fmt
        formatter = logging.Formatter(fmt=fmt, datefmt="%Y%m%dT%H%M%S%z")
    else:
        formatter = logging.Formatter(fmt=fmt)

    # stream handler
    ch = logging.StreamHandler()
    ch.setLevel(loglevel)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # file handler (optional)
    if path:
        fh = logging.FileHandler(filename=path, mode="a", encoding="utf-8")
        fh.setLevel(loglevel)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    _loggers[key] = logger
    return logger