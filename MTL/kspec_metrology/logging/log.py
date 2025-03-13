import logging

_loggers = dict()
def get_logger(level='INFO', path=None, timestamps=False):
        
    if level == 'DEBUG':
        loglevel = logging.DEBUG
    elif level == 'INFO':
        loglevel = logging.INFO
    elif level == 'WARN' or level == 'WARNING':
        loglevel = logging.WARNING
    elif level == 'ERROR':
        loglevel = logging.ERROR
    elif level == 'FATAL' or level == 'CRITICAL':
        loglevel = logging.CRITICAL
    else:
        raise ValueError('Unknown log level {}; should be DEBUG/INFO/WARNING/ERROR/CRITICAL'.format(level))
        
    logger = logging.getLogger()
    logger.setLevel(loglevel)

    ch = logging.StreamHandler()
    ch.setLevel(loglevel)

    # optionally create file handler, similarly
    if path:
        fh = logging.FileHandler(filename=path, mode='a', encoding='utf-8')
        fh.setLevel(loglevel)
    else:
        fh = None

    # create formatter
    kwargs = {'fmt': '%(levelname)s:%(filename)s:%(lineno)s:%(funcName)s:%(message)s'}
    if timestamps:
        kwargs['fmt'] = '%(asctime)s:' + kwargs['fmt']
        kwargs['datefmt'] = '%Y%m%dT%H%M%S%z'
    formatter = logging.Formatter(**kwargs)

    # add formatter to ch
    ch.setFormatter(formatter)
    if fh:
        fh.setFormatter(formatter)

    # add handlers to logger
    logger.addHandler(ch)
    if fh:
        logger.addHandler(fh)
    
    _loggers[level] = logger

    return _loggers[level]